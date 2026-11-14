"""Safe stop and task failures through the shared batch/filesystem seam."""
import errno
import json
import os
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile
import threading
import unittest

from prototype.batch import BatchEvent, run
from test_prototype import tiny
from fs_faults import fail_report_update_at


class BatchStopTests(unittest.TestCase):
    def test_stop_before_first_file_writes_empty_report_not_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            (inputs / 'a.psd').write_bytes(tiny())
            stop = threading.Event()
            stop.set()
            events: list[BatchEvent] = []
            rows, report = run(inputs, base / 'output', stop=stop, on_event=events.append, emit=lambda _: None)
            self.assertEqual(rows, [])
            self.assertEqual(json.loads(report.read_text(encoding='utf-8')), [])
            self.assertEqual(events[-1].kind, 'stopped')
            self.assertEqual((events[-1].completed, events[-1].total), (0, 1))
            self.assertFalse(any(e.kind == 'file' for e in events))
            self.assertFalse((base / 'output' / '.cleaner.lock').exists())

    def test_validation_corruption_is_a_file_failure_and_stop_still_applies(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            original = tiny()
            for name in ('a.psd', 'b.psd'):
                (inputs / name).write_bytes(original)
            for request_stop in (False, True):
                with self.subTest(request_stop=request_stop):
                    output = base / str(request_stop)
                    stop = threading.Event()
                    events: list[BatchEvent] = []

                    def corrupt_output(event):
                        events.append(event)
                        if event.phase == '校验中' and event.source is not None and event.source.name == 'a.psd':
                            staged = next(output.glob('*/tmp*/result.tmp'))
                            with staged.open('r+b') as stream:
                                stream.write(b'BAD!')
                            if request_stop:
                                stop.set()

                    rows, report = run(inputs, output, stop=stop, on_event=corrupt_output, emit=lambda _: None)
                    self.assertEqual([row['status'] for row in rows], ['失败'] if request_stop else ['失败', '成功'])
                    self.assertIn('校验失败', rows[0]['error'])
                    self.assertIsNone(rows[0]['output'])
                    self.assertFalse(list(output.glob('*/files/a.psd')))
                    self.assertFalse(list(output.glob('*/tmp*')))
                    self.assertEqual(json.loads(report.read_text(encoding='utf-8')), rows)
                    self.assertEqual(events[-1].kind, 'stopped' if request_stop else 'finished')
                    self.assertEqual((inputs / 'a.psd').read_bytes(), original)
                    self.assertEqual((inputs / 'b.psd').read_bytes(), original)

    def test_staged_write_failure_is_fatal_and_removes_incomplete_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            for name in ('a.psd', 'b.psd'):
                (inputs / name).write_bytes(tiny())
            output = base / 'output'
            path_open = Path.open
            events: list[BatchEvent] = []

            def failing_write(path, mode='r', *args, **kwargs):
                stream = path_open(path, mode, *args, **kwargs)
                if path.name == 'result.tmp' and mode == 'xb':
                    stream.write = Mock(side_effect=OSError(errno.ENOSPC, '写入时磁盘已满', str(path)))
                return stream

            with patch('pathlib.Path.open', new=failing_write):
                with self.assertRaisesRegex(RuntimeError, '磁盘已满'):
                    run(inputs, output, on_event=events.append, emit=lambda _: None)
            self.assertEqual(events[-1].kind, 'error')
            report = next(e.report for e in events if e.kind == 'file')
            assert report is not None
            rows = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['status'], '失败')
            self.assertFalse(list(output.glob('*/files/*.psd')))
            self.assertFalse(list(output.glob('*/tmp*')))
            self.assertFalse((output / '.cleaner.lock').exists())

    def test_owned_lock_is_released_even_when_its_initial_write_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            output = base / 'output'
            path_open = Path.open

            def failing_lock_write(path, mode='r', *args, **kwargs):
                stream = path_open(path, mode, *args, **kwargs)
                if path.name == '.cleaner.lock' and mode == 'x':
                    stream.write = Mock(side_effect=OSError('锁内容无法写入'))
                return stream

            with patch('pathlib.Path.open', new=failing_lock_write):
                with self.assertRaisesRegex(OSError, '锁内容无法写入'):
                    run(inputs, output, emit=lambda _: None)
            self.assertFalse((output / '.cleaner.lock').exists())
            rows, report = run(inputs, output, emit=lambda _: None)
            self.assertEqual(rows, [])
            self.assertTrue(report.is_file())

    def test_lock_conflict_is_readable_and_never_removes_another_tasks_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / 'input', base / 'output'
            inputs.mkdir()
            output.mkdir()
            (inputs / 'a.psd').write_bytes(tiny())
            lock = output / '.cleaner.lock'
            lock.write_text('other-job', encoding='utf-8')
            events: list[BatchEvent] = []
            with self.assertRaisesRegex(RuntimeError, '已有任务.*确认.*无任务'):
                run(inputs, output, on_event=events.append, emit=lambda _: None)
            self.assertEqual(lock.read_text(encoding='utf-8'), 'other-job')
            self.assertIn(str(lock.resolve()), events[-1].message)
            self.assertEqual(events[-1].kind, 'error')
            self.assertFalse(list(output.glob('*/report.json')))
            lock.unlink()  # Test owns this simulated stale lock, not production auto-unlock.
            rows, _ = run(inputs, output, emit=lambda _: None)
            self.assertEqual(rows[0]['status'], '成功')

    def test_report_failure_keeps_last_durable_rows_and_exposes_published_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            for name in ('a.psd', 'b.psd', 'c.psd'):
                (inputs / name).write_bytes(tiny())
            output = base / 'output'
            events: list[BatchEvent] = []
            with fail_report_update_at(2):
                with self.assertRaisesRegex(RuntimeError, '结果报告.*任务终止'):
                    run(inputs, output, on_event=events.append, emit=lambda _: None)
            self.assertEqual(events[-1].kind, 'error')
            files = [e for e in events if e.kind == 'file']
            self.assertEqual(len(files), 2)
            report = files[-1].report
            assert report is not None and files[-1].row is not None
            durable = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual([Path(row['source']).name for row in durable], ['a.psd'])
            self.assertTrue(Path(files[-1].row['output']).is_file())
            self.assertFalse(list(output.glob('*/files/c.psd')))
            self.assertFalse(any(e.kind in ('finished', 'stopped') for e in events))
            self.assertFalse((output / '.cleaner.lock').exists())
            retried, _ = run(inputs, output, emit=lambda _: None)
            self.assertEqual([row['status'] for row in retried], ['未变化', '未变化', '成功'])

    def test_historical_output_read_error_terminates_task_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            for name in ('a.psd', 'b.psd'):
                (inputs / name).write_bytes(tiny())
            output = base / 'output'
            previous, old_report = run(inputs, output, emit=lambda _: None)
            historical = Path(previous[0]['output'])
            original_output = historical.read_bytes()
            original_report = old_report.read_bytes()
            path_open = Path.open
            events: list[BatchEvent] = []

            def failing_read(path, mode='r', *args, **kwargs):
                if path == historical and mode == 'rb':
                    raise OSError(errno.EIO, '历史输出读取失败', str(path))
                return path_open(path, mode, *args, **kwargs)

            with patch('pathlib.Path.open', new=failing_read):
                with self.assertRaisesRegex(RuntimeError, '历史输出读取失败'):
                    run(inputs, output, on_event=events.append, emit=lambda _: None)
            self.assertEqual(events[-1].kind, 'error')
            files = [event for event in events if event.kind == 'file']
            self.assertEqual(len(files), 1)
            assert files[0].row is not None and files[0].report is not None
            self.assertEqual(files[0].row['status'], '失败')
            self.assertEqual(len(json.loads(files[0].report.read_text(encoding='utf-8'))), 1)
            self.assertEqual(historical.read_bytes(), original_output)
            self.assertEqual(old_report.read_bytes(), original_report)
            self.assertFalse((output / '.cleaner.lock').exists())
            retried, _ = run(inputs, output, emit=lambda _: None)
            self.assertEqual([row['status'] for row in retried], ['未变化', '未变化'])

    def test_published_output_is_reported_without_relying_on_later_staged_stat(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            (inputs / 'a.psd').write_bytes(tiny())
            output = base / 'output'
            link, path_stat = os.link, Path.stat
            published = []

            def publish(source, destination):
                link(source, destination)
                published.append(Path(destination))

            def inaccessible_staged(path, *args, **kwargs):
                if published and path.name == 'result.tmp':
                    raise OSError(errno.EIO, '发布后暂存元数据不可读', str(path))
                return path_stat(path, *args, **kwargs)

            with patch('os.link', side_effect=publish), patch('pathlib.Path.stat', new=inaccessible_staged):
                rows, report = run(inputs, output, emit=lambda _: None)
            self.assertEqual(rows[0]['status'], '成功')
            self.assertEqual(rows[0]['output'], str(published[0]))
            self.assertTrue(published[0].is_file())
            self.assertEqual(rows[0]['after'], published[0].stat().st_size)
            self.assertEqual(json.loads(report.read_text(encoding='utf-8')), rows)
            self.assertFalse((output / '.cleaner.lock').exists())

    def test_output_publication_failure_terminates_task_and_can_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            original = tiny()
            for name in ('a.psd', 'b.psd'):
                (inputs / name).write_bytes(original)
            output = base / 'output'
            events: list[BatchEvent] = []
            with patch('os.link', side_effect=OSError(errno.EIO, '输出卷无法发布')):
                with self.assertRaisesRegex(RuntimeError, '输出.*任务终止'):
                    run(inputs, output, on_event=events.append, emit=lambda _: None)
            self.assertEqual(events[-1].kind, 'error')
            self.assertFalse(any(e.kind in ('finished', 'stopped') for e in events))
            file_event = next(e for e in events if e.kind == 'file')
            assert file_event.report is not None
            rows = json.loads(file_event.report.read_text(encoding='utf-8'))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['status'], '失败')
            self.assertIsNone(rows[0]['output'])
            self.assertIn('输出卷无法发布', rows[0]['error'])
            self.assertFalse(list(output.glob('*/files/*.psd')))
            self.assertFalse(list(output.glob('*/tmp*')))
            self.assertFalse((output / '.cleaner.lock').exists())
            retried, _ = run(inputs, output, emit=lambda _: None)
            self.assertEqual([row['status'] for row in retried], ['成功', '成功'])
            for name in ('a.psd', 'b.psd'):
                self.assertEqual((inputs / name).read_bytes(), original)

    def test_request_during_validation_finishes_file_and_reports_stopped(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            original = tiny()
            for name in ('a.psd', 'b.psd'):
                (inputs / name).write_bytes(original)
            stop = threading.Event()
            events: list[BatchEvent] = []

            def receive(event):
                events.append(event)
                if event.phase == '校验中':
                    stop.set()

            rows, report = run(inputs, base / 'output', stop=stop, on_event=receive, emit=lambda _: None)
            self.assertEqual(events[-1].kind, 'stopped')
            self.assertEqual((events[-1].completed, events[-1].total), (1, 2))
            self.assertFalse(any(e.kind == 'finished' for e in events))
            self.assertEqual([Path(row['source']).name for row in rows], ['a.psd'])
            self.assertEqual(rows[0]['status'], '成功')
            self.assertTrue(Path(rows[0]['output']).is_file())
            self.assertEqual(json.loads(report.read_text(encoding='utf-8')), rows)
            self.assertFalse(list((base / 'output').glob('*/files/b.psd')))
            self.assertFalse((base / 'output' / '.cleaner.lock').exists())
            for name in ('a.psd', 'b.psd'):
                self.assertEqual((inputs / name).read_bytes(), original)
            again, _ = run(inputs, base / 'output', emit=lambda _: None)
            self.assertEqual([row['status'] for row in again], ['未变化', '成功'])


if __name__ == '__main__':
    unittest.main()
