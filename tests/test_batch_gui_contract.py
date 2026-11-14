"""Shared batch interface used by the GUI, with real files and outputs."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from test_prototype import tiny, XMP, TARGET_ELEMENT
from psd_tools.psd import PSD
from psd_tools.constants import Resource
from prototype.batch import BatchEvent, run


class BatchGuiContractTests(unittest.TestCase):
    def test_current_directory_only_keeps_cli_recursive_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / '输入'
            (inputs / '子目录').mkdir(parents=True)
            (inputs / 'a.PSD').write_bytes(tiny())
            (inputs / '子目录' / 'b.psb').write_bytes(tiny(2))
            rows, _ = run(inputs, base / 'flat', recursive=False, emit=lambda _: None)
            self.assertEqual([Path(r['source']).name for r in rows], ['a.PSD'])
            self.assertEqual((inputs / 'a.PSD').read_bytes(), tiny())
            doc = PSD.read(io.BytesIO(Path(rows[0]['output']).read_bytes()))
            self.assertEqual(doc.image_resources[Resource.XMP_METADATA].data, XMP.replace(TARGET_ELEMENT, b''))
            recursive_rows, _ = run(inputs, base / 'recursive', emit=lambda _: None)
            self.assertEqual(len(recursive_rows), 2)

    def test_structured_events_show_real_validation_and_final_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            (inputs / 'clean.psd').write_bytes(tiny())
            events: list[BatchEvent] = []
            rows, report = run(inputs, base / 'output', recursive=False, on_event=events.append, emit=lambda _: None)
            phases = [event.phase for event in events if event.kind == 'phase']
            self.assertEqual(phases, ['扫描文件', '检查变化', '清理中', '校验中'])
            finished_file = next(event for event in events if event.kind == 'file')
            self.assertEqual(finished_file.row, rows[0])
            self.assertEqual(events[-1].kind, 'finished')
            self.assertEqual(events[-1].report, report)
            self.assertTrue(report.is_file())

    def test_scan_total_precedes_processing_and_progress_counts_selected_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / '输入 空格'
            (inputs / '子目录').mkdir(parents=True)
            first = inputs / 'a.PSD'
            second = inputs / '子目录' / 'b.PsB'
            first.write_bytes(tiny())
            second.write_bytes(tiny(2))
            (inputs / 'ignore.txt').write_text('not an input')
            for recursive, expected in ((False, 1), (True, 2)):
                with self.subTest(recursive=recursive):
                    events = []
                    rows, _ = run(inputs, base / str(recursive), recursive=recursive,
                                  on_event=events.append, emit=lambda _: None)
                    scanned = next(event for event in events if event.kind == 'scanned')
                    self.assertEqual((scanned.completed, scanned.total), (0, expected))
                    self.assertLess(events.index(scanned), next(i for i, e in enumerate(events) if e.source))
                    progress = [(e.completed, e.total) for e in events if e.kind == 'file']
                    self.assertEqual(progress, [(1, 1)] if not recursive else [(1, 2), (2, 2)])
                    self.assertEqual((events[-1].completed, events[-1].total), (expected, expected))
                    self.assertEqual(len(rows), expected)
            selected_events = []
            run(inputs, base / 'selected', selected_files={second},
                on_event=selected_events.append, emit=lambda _: None)
            self.assertEqual(next(e.total for e in selected_events if e.kind == 'scanned'), 1)

    def test_scan_failure_never_claims_total_or_completion_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            denied = inputs / '无权限 子目录'
            denied.mkdir(parents=True)
            source = inputs / 'a.psd'
            original = tiny()
            source.write_bytes(original)
            output = base / 'output'
            rows, old_report = run(inputs, output, recursive=False, emit=lambda _: None)
            published = Path(rows[0]['output'])
            old_bytes = published.read_bytes()
            old_report_bytes = old_report.read_bytes()
            scandir = os.scandir
            for error in (PermissionError('无权限扫描目录'), OSError('扫描设备错误')):
                events = []

                def unavailable(path):
                    if Path(path) == denied.resolve():
                        raise type(error)(str(error))
                    return scandir(path)

                with self.subTest(error=type(error).__name__), patch('os.scandir', side_effect=unavailable):
                    with self.assertRaisesRegex(type(error), str(error)):
                        run(inputs, output, on_event=events.append, emit=lambda _: None)
                self.assertEqual(events[-1].kind, 'error')
                self.assertFalse(any(e.kind in ('scanned', 'file', 'finished') for e in events))
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(published.read_bytes(), old_bytes)
                self.assertEqual(old_report.read_bytes(), old_report_bytes)
                self.assertFalse((output / '.cleaner.lock').exists())

    def test_links_are_excluded_and_nested_empty_scope_has_zero_total(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            (inputs / '空目录' / '多层').mkdir(parents=True)
            outside = base / 'outside'
            outside.mkdir()
            original = tiny()
            (outside / 'external.psd').write_bytes(original)
            try:
                (inputs / 'linked-directory').symlink_to(outside, target_is_directory=True)
                (inputs / 'linked-file.PSD').symlink_to(outside / 'external.psd')
                (inputs / 'cycle').symlink_to(inputs, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f'symlink creation unavailable: {exc}')
            events = []
            rows, report = run(inputs, base / 'output', on_event=events.append, emit=lambda _: None)
            self.assertEqual(rows, [])
            self.assertEqual(json.loads(report.read_text(encoding='utf-8')), [])
            self.assertEqual(next(e.total for e in events if e.kind == 'scanned'), 0)
            self.assertEqual((events[-1].completed, events[-1].total), (0, 0))
            self.assertEqual((outside / 'external.psd').read_bytes(), original)

    def test_containment_is_rejected_in_both_directions(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            original = tiny()
            (inputs / 'a.psd').write_bytes(original)
            for output in (inputs, inputs / 'output', base):
                with self.subTest(output=output):
                    events = []
                    with self.assertRaisesRegex(ValueError, '不能相互包含'):
                        run(inputs, output, on_event=events.append, emit=lambda _: None)
                    self.assertEqual(events[-1].kind, 'error')
                    self.assertFalse(any(e.kind in ('scanned', 'file', 'finished') for e in events))
            self.assertEqual((inputs / 'a.psd').read_bytes(), original)
            self.assertFalse((inputs / 'output').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows directory junction protection')
    def test_directory_junction_cannot_rescan_historical_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            output = base / 'output'
            output.mkdir()
            original = tiny()
            (output / 'historical.psd').write_bytes(original)
            junction = inputs / '历史输出联接'
            created = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(output)],
                                     capture_output=True)
            self.assertEqual(created.returncode, 0, repr(created.stderr))
            try:
                rows, _ = run(inputs, output, emit=lambda _: None)
                self.assertEqual(rows, [])
                self.assertEqual((output / 'historical.psd').read_bytes(), original)
            finally:
                junction.rmdir()

    def test_cli_can_disable_recursion(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / '输入 空格'
            (inputs / '子目录').mkdir(parents=True)
            (inputs / 'a.PSD').write_bytes(tiny())
            (inputs / '子目录' / 'b.psb').write_bytes(tiny(2))
            result = subprocess.run([sys.executable, '-m', 'prototype.batch', '--input', str(inputs),
                                     '--output', str(base / 'output'), '--no-recursive'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = next((base / 'output').glob('*/report.json'))
            self.assertEqual(len(json.loads(report.read_text(encoding='utf-8'))), 1)

    def test_invalid_directories_emit_task_error_without_file_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            events: list[BatchEvent] = []
            with self.assertRaisesRegex(ValueError, '输入目录不存在'):
                run(base / 'missing', base / 'output', on_event=events.append, emit=lambda _: None)
            self.assertEqual(events[-1].kind, 'error')
            self.assertFalse(any(event.kind in ('file', 'finished') for event in events))
            self.assertFalse((base / 'output').exists())

    def test_text_observer_also_receives_validation_phase(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            (inputs / 'a.psd').write_bytes(tiny())
            messages: list[str] = []
            run(inputs, base / 'output', emit=messages.append)
            self.assertTrue(any(message.startswith('校验中：') for message in messages))

    def test_infrastructure_failure_keeps_report_and_emits_error_not_finished(self):
        import os
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            (inputs / 'a.psd').write_bytes(tiny())
            (inputs / 'b.psd').write_bytes(tiny())
            events: list[BatchEvent] = []
            replace = os.replace

            def unavailable_cache(source, destination):
                if Path(destination).name == '.cleaner-cache.json':
                    raise PermissionError('缓存无法落盘')
                return replace(source, destination)

            with patch('os.replace', side_effect=unavailable_cache):
                with self.assertRaisesRegex(RuntimeError, '任务终止'):
                    run(inputs, base / 'output', on_event=events.append, emit=lambda _: None)
            self.assertEqual(events[-1].kind, 'error')
            self.assertFalse(any(event.kind == 'finished' for event in events))
            file_event = next(event for event in events if event.kind == 'file')
            self.assertIsNotNone(file_event.report)
            assert file_event.report is not None and file_event.row is not None
            self.assertTrue(file_event.report.is_file())
            self.assertEqual(file_event.row['status'], '失败')
            self.assertTrue(Path(file_event.row['output']).is_file())
            self.assertFalse(list((base / 'output').glob('*/files/b.psd')))

    def test_unwritable_output_fails_before_processing_any_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            source = inputs / 'a.psd'
            original = tiny()
            source.write_bytes(original)
            events: list[BatchEvent] = []
            path_open = Path.open

            def denied(path, mode='r', *args, **kwargs):
                if path == (base / 'output' / '.cleaner.lock').resolve() and mode == 'x':
                    raise PermissionError('输出目录不可写')
                return path_open(path, mode, *args, **kwargs)

            # Filesystem fault injection, not a mock of the batch implementation.
            with patch('pathlib.Path.open', new=denied):
                with self.assertRaisesRegex(PermissionError, '不可写'):
                    run(inputs, base / 'output', on_event=events.append, emit=lambda _: None)
            self.assertEqual(events[-1].kind, 'error')
            self.assertFalse(any(event.kind in ('file', 'finished') for event in events))
            self.assertFalse(list((base / 'output').glob('*/files/*')))
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
