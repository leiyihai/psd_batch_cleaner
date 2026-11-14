"""Real Tk widgets -> shared batch -> filesystem; no mocked cleaning logic."""
from contextlib import nullcontext
import errno
import gc
import io
import json
import threading
import os
import subprocess
import sys
from unittest.mock import patch
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from psd_tools.psd import PSD
from prototype.batch import run
from psd_tools.constants import Resource
from test_prototype import tiny, embedded, XMP, TARGET_ELEMENT
from fs_faults import fail_report_update_at, forbid_file_access


class GuiTests(unittest.TestCase):
    def setUp(self):
        # Prior unittest cases can leave unreachable Tk cycles. Reclaim them
        # on Tk's owner thread before a new worker can trigger cyclic GC.
        gc.collect()
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'GUI display unavailable: {exc}')
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        from prototype.gui import CleanerWindow
        self.app = CleanerWindow(self.root)
        self.app.pack(fill='both', expand=True)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.inputs = self.base / '输入 空格'
        self.inputs.mkdir()
        self.output = self.base / 'output'
        self.app.input_path.set(str(self.inputs))
        self.app.output_path.set(str(self.output))

    def finish(self):
        deadline = time.monotonic() + 15
        while self.app.start_button.instate(['disabled']) and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.app.start_button.instate(['disabled']), 'GUI job did not finish')
        self.root.update()

    def wait_for(self, event):
        deadline = time.monotonic() + 5
        while not event.is_set() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(event.is_set(), 'filesystem gate was not entered')

    def test_serial_release_full_workflow_matches_cli_and_preserves_history(self):
        deep = tiny(children=[embedded(tiny(2, children=[embedded(tiny())]))])
        fixtures = {'00-bad.psd': b'broken', '01-deep.PSD': deep,
                    'A/01-same.PsB': tiny(2, xmp=None),
                    'A/02-partial.psd': tiny(children=[embedded(b'%PDF opaque')]),
                    'B/01-same.psd': tiny()}
        for relative, content in fixtures.items():
            path = self.inputs / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (self.inputs / '空目录').mkdir()
        (self.inputs / 'ignore.jpg').write_bytes(b'not input')
        with patch('tkinter.filedialog.askdirectory', side_effect=[str(self.inputs), str(self.output)]):
            self.app.input_browse.invoke()
            self.app.output_browse.invoke()
        self.assertTrue(self.app.recursive.get())
        archived: dict[Path, bytes] = {}

        def export_round(name):
            destination = self.base / f'08-{name}.json'
            with patch('tkinter.filedialog.asksaveasfilename', return_value=str(destination)):
                self.app.export_button.invoke()
                self.finish()
            payload = json.loads(destination.read_text(encoding='utf-8'))
            if payload['task']['source_report']:
                report = Path(payload['task']['source_report'])
                self.assertEqual(json.loads(report.read_text(encoding='utf-8')), payload['results'])
                archived.setdefault(report, report.read_bytes())
            for row in payload['results']:
                if row['output']:
                    path = Path(row['output'])
                    archived.setdefault(path, path.read_bytes())
            for path, content in archived.items():
                self.assertEqual(path.read_bytes(), content, f'historical artifact changed: {path}')
            return payload

        def execute(name):
            self.app.start_button.invoke()
            self.finish()
            return export_round(name)

        first = execute('first')
        self.assertEqual([row['status'] for row in first['results']], ['失败', '成功', '无需清理', '部分清理', '成功'])
        self.assertEqual((first['results'][1]['documents'], first['results'][1]['removed']), (3, 3))
        report_root = Path(first['task']['source_report']).parent
        self.assertTrue((report_root / 'files/A/01-same.PsB').is_file())
        self.assertTrue((report_root / 'files/B/01-same.psd').is_file())
        second = execute('repeat')
        self.assertEqual([row['status'] for row in second['results']], ['失败', '未变化', '未变化', '部分清理', '未变化'])
        self.assertEqual(second['summary']['counted_files'], 1)
        self.assertNotEqual(first['results'][3]['output'], second['results'][3]['output'])
        source = self.inputs / '01-deep.PSD'
        before = source.stat()
        updated = deep.replace(b'Shanghai', b'Shenzhen')
        source.write_bytes(updated)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        fixtures['01-deep.PSD'] = updated
        changed = execute('input-updated')
        self.assertEqual(changed['results'][1]['status'], '成功')
        self.assertNotEqual(changed['results'][1]['output'], first['results'][1]['output'])
        manifest = self.output / '.cleaner-cache.json'
        records = json.loads(manifest.read_text(encoding='utf-8'))
        for record in records.values():
            record['rule'] = 'previous-serial-rule'
        manifest.write_text(json.dumps(records), encoding='utf-8')
        upgraded = execute('rule-upgraded')
        self.assertEqual([row['status'] for row in upgraded['results']], ['失败', '成功', '无需清理', '部分清理', '成功'])
        damaged_output = Path(upgraded['results'][2]['output'])
        damaged_output.write_bytes(b'intentionally damaged output')
        archived[damaged_output] = damaged_output.read_bytes()
        repaired = execute('output-repaired')
        self.assertEqual(repaired['results'][2]['status'], '无需清理')
        self.assertNotEqual(repaired['results'][2]['output'], str(damaged_output))
        lock = self.output / '.cleaner.lock'
        lock.write_text('integration-owned simulated conflict', encoding='utf-8')
        try:
            blocked = execute('task-error')
            self.assertEqual(blocked['task']['state'], 'error')
            self.assertEqual(blocked['results'], [])
            self.assertEqual(lock.read_text(encoding='utf-8'), 'integration-owned simulated conflict')
        finally:
            lock.unlink()  # This test, not the cleaner, owns the simulated lock.
        entered, release = threading.Event(), threading.Event()
        path_open = Path.open

        def hold_current_file(path, mode='r', *args, **kwargs):
            if mode == 'rb' and path == source.resolve():
                entered.set()
                if not release.wait(10):
                    raise TimeoutError('integrated stop gate timed out')
            return path_open(path, mode, *args, **kwargs)

        with patch('pathlib.Path.open', new=hold_current_file):
            self.app.start_button.invoke()
            try:
                self.wait_for(entered)
                self.app.stop_button.invoke()
                self.assertEqual(self.app.phase.get(), '请求停止')
                self.assertTrue(self.app.start_button.instate(['disabled']))
            finally:
                release.set()
                self.finish()
        stopped = export_round('stopped')
        self.assertEqual((stopped['task']['state'], stopped['task']['completed'], stopped['task']['total']), ('stopped', 2, 5))
        self.assertEqual([Path(row['source']).name for row in stopped['results']], ['00-bad.psd', '01-deep.PSD'])
        resumed = execute('resumed')
        self.assertEqual((resumed['task']['state'], resumed['task']['completed'], resumed['task']['total']), ('finished', 5, 5))
        cli_output = self.base / 'independent-cli'
        cli_rows = []
        for iteration in range(2):
            result = subprocess.run([sys.executable, '-m', 'prototype.batch', '--input', str(self.inputs),
                                     '--output', str(cli_output)], env={**os.environ, 'PYTHONUTF8': '1'},
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            terminal = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual((terminal['state'], terminal['completed'], terminal['total']), ('finished', 5, 5))
            cli_rows = json.loads(Path(terminal['report']).read_text(encoding='utf-8'))
            if iteration:
                self.assertEqual([row['status'] for row in cli_rows], ['失败', '未变化', '未变化', '部分清理', '未变化'])
        for gui_row, cli_row in zip(resumed['results'], cli_rows):
            self.assertEqual(gui_row['source'], cli_row['source'])
            if gui_row['output']:
                self.assertEqual(Path(gui_row['output']).read_bytes(), Path(cli_row['output']).read_bytes())
            else:
                self.assertIsNone(cli_row['output'])
        for relative, content in fixtures.items():
            self.assertEqual((self.inputs / relative).read_bytes(), content)
        for path, content in archived.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse(lock.exists())
        self.assertFalse((cli_output / '.cleaner.lock').exists())

    def test_result_details_and_classified_statistics_use_real_batch_records(self):
        historical_source = self.inputs / 'c-历史.psd'
        historical_source.write_bytes(tiny())
        self.app.start_button.invoke()
        self.finish()
        first = json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))[0]
        fixtures = {'a-清理.psd': tiny(), 'b-原样.psb': tiny(2, xmp=None),
                    'd-部分.psd': tiny(children=[embedded(b'%PDF opaque')]), 'e-损坏.psd': b'broken'}
        for name, content in fixtures.items():
            (self.inputs / name).write_bytes(content)
        self.app.start_button.invoke()
        self.finish()
        rows = json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))
        self.assertEqual([row['status'] for row in rows], ['成功', '无需清理', '未变化', '部分清理', '失败'])
        self.assertEqual(rows[2]['output'], first['output'])
        statistics = self.app.statistics.get()
        for text in ('成功 1', '无需清理 1', '未变化 1', '部分清理 1', '失败 1', '本轮可核实净减少',
                     '历史复用、失败、未发布', '部分清理不等于完整成功'):
            self.assertIn(text, statistics)
        for item, row in zip(self.app.results.get_children(), rows):
            self.app.results.selection_set(item)
            self.root.update()
            details = self.app.details.get('1.0', 'end')
            self.assertIn(row['source'], details)
            self.assertIn(row['output'] or '未发布（无可用输出）', details)
            self.assertIn(f"原始大小：{row['before']} 字节", details)
            if row['status'] == '失败':
                self.assertIn('结果大小：未知', details)
                self.assertIn(row['error'], details)
            elif row['status'] == '未变化':
                self.assertIn('复用历史副本', details)
                self.assertIn('不计入本轮收益', details)
            else:
                self.assertIn(f"结果大小：{row['after']} 字节", details)
                self.assertIn(f"清理文档数量：{row['documents']}", details)
                self.assertIn(f"跳过外链数量：{row['skipped_links']}", details)
            if row['status'] == '部分清理':
                self.assertIn('不等于完整清理成功', details)
                for index, issue in enumerate(row['issues'], 1):
                    self.assertIn(f'{index}. {issue}', details)

    def test_json_export_matches_the_same_batch_rows_and_classified_statistics(self):
        self.assertTrue(self.app.export_button.instate(['disabled']))
        fixtures = {'a.psd': tiny(), 'b.psb': tiny(2, xmp=None),
                    'c.psd': tiny(children=[embedded(b'%PDF opaque')]), 'd.psd': b'broken'}
        for name, content in fixtures.items():
            (self.inputs / name).write_bytes(content)
        self.app.start_button.invoke()
        self.assertTrue(self.app.export_button.instate(['disabled']))
        self.finish()
        report = Path(self.app.report_path.get())
        rows = json.loads(report.read_text(encoding='utf-8'))
        phase, statistics = self.app.phase.get(), self.app.statistics.get()
        destination = self.base / '中文 导出.json'
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(destination)):
            self.app.export_button.invoke()
            self.assertTrue(self.app.start_button.instate(['disabled']))
            self.finish()
        exported = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(exported['results'], rows)
        self.assertEqual(exported['task']['state'], 'finished')
        self.assertEqual(exported['task']['source_report'], str(report))
        self.assertEqual((exported['task']['completed'], exported['task']['total']), (4, 4))
        self.assertEqual(exported['summary']['counts'], {'成功': 1, '无需清理': 1, '未变化': 0, '部分清理': 1, '失败': 1})
        expected = sum(len(fixtures[Path(row['source']).name]) - Path(row['output']).stat().st_size
                       for row in rows if row['status'] in ('成功', '无需清理', '部分清理'))
        self.assertEqual(exported['summary']['savings_bytes'], expected)
        self.assertIn('已导出', self.app.export_status.get())
        self.assertEqual(self.app.phase.get(), phase)
        self.assertEqual(self.app.statistics.get(), statistics)
        self.assertFalse(self.app.export_button.instate(['disabled']))
        self.assertEqual(json.loads(report.read_text(encoding='utf-8')), rows)
        self.app.start_button.invoke()
        self.finish()
        reused_rows = json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))
        self.assertEqual([row['status'] for row in reused_rows], ['未变化', '未变化', '部分清理', '失败'])
        reused_export = self.base / '含历史复用.json'
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(reused_export)):
            self.app.export_button.invoke()
            self.finish()
        reused_payload = json.loads(reused_export.read_text(encoding='utf-8'))
        self.assertEqual(reused_payload['results'], reused_rows)
        self.assertEqual(reused_payload['summary']['counted_files'], 1)
        self.assertEqual(reused_payload['summary']['savings_bytes'],
                         reused_rows[2]['before'] - reused_rows[2]['after'])

    def test_export_cancel_overwrite_io_and_thread_errors_preserve_batch_and_allow_retry(self):
        (self.inputs / 'a.psd').write_bytes(tiny())
        self.app.start_button.invoke()
        self.finish()
        report = Path(self.app.report_path.get())
        original_report = report.read_bytes()
        phase, statistics = self.app.phase.get(), self.app.statistics.get()
        with patch('tkinter.filedialog.asksaveasfilename', return_value=''):
            self.app.export_button.invoke()
        self.assertFalse(self.app.start_button.instate(['disabled']))
        occupied = self.base / '已有用户文件.json'
        occupied.write_bytes(b'user data')
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(occupied)):
            self.app.export_button.invoke()
            self.finish()
        self.assertIn('拒绝覆盖', self.app.export_status.get())
        self.assertEqual(occupied.read_bytes(), b'user data')
        failed = self.base / '失败导出.json'
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(failed)), \
                patch('os.fsync', side_effect=OSError(errno.ENOSPC, '导出磁盘已满')):
            self.app.export_button.invoke()
            self.finish()
        self.assertIn('导出磁盘已满', self.app.export_status.get())
        self.assertFalse(failed.exists())
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(failed)), \
                patch('threading.Thread.start', side_effect=RuntimeError('无法启动导出线程')):
            self.app.export_button.invoke()
            self.finish()
        self.assertIn('无法启动导出线程', self.app.export_status.get())
        self.assertFalse(failed.exists())
        with patch('tkinter.filedialog.asksaveasfilename', side_effect=RuntimeError('保存对话框不可用')):
            self.app.export_button.invoke()
        self.assertIn('保存对话框不可用', self.app.export_status.get())
        self.assertFalse(self.app.export_button.instate(['disabled']))
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(failed)):
            self.app.export_button.invoke()
            self.finish()
        self.assertEqual(json.loads(failed.read_text(encoding='utf-8'))['results'], json.loads(original_report))
        self.assertEqual(report.read_bytes(), original_report)
        self.assertEqual(self.app.phase.get(), phase)
        self.assertEqual(self.app.statistics.get(), statistics)

    def test_export_runs_off_tk_thread_locks_snapshot_and_does_not_start_another_batch(self):
        (self.inputs / 'a.psd').write_bytes(tiny())
        self.app.start_button.invoke()
        self.finish()
        report = Path(self.app.report_path.get())
        rows = json.loads(report.read_text(encoding='utf-8'))
        destination = self.base / '异步导出.json'
        entered, release = threading.Event(), threading.Event()
        path_open = Path.open
        ticks = []

        def gated_export(path, mode='r', *args, **kwargs):
            stream = path_open(path, mode, *args, **kwargs)
            if path == destination and mode == 'x':
                write = stream.write

                def delayed_write(content):
                    entered.set()
                    if not release.wait(10):
                        raise TimeoutError('export filesystem gate timed out')
                    return write(content)

                stream.write = delayed_write
            return stream

        self.app.output_path.set(str(self.base / 'not-the-job-output'))
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(destination)), \
                patch('pathlib.Path.open', new=gated_export):
            self.app.export_button.invoke()
            try:
                self.wait_for(entered)
                self.root.after(1, lambda: ticks.append('responsive'))
                self.root.update()
                time.sleep(.01)
                self.root.update()
                self.assertTrue(ticks)
                self.assertTrue(self.app.export_button.instate(['disabled']))
                self.assertTrue(self.app.start_button.instate(['disabled']))
                self.assertTrue(self.app.input_entry.instate(['disabled']))
                self.assertTrue(self.app.stop_button.instate(['disabled']))
                self.app.start()  # Programmatic start must also respect export ownership.
                self.app.request_close()
                self.assertTrue(self.root.winfo_exists())
                self.assertEqual(len(list(self.output.glob('*/report.json'))), 1)
            finally:
                release.set()
                self.finish()
        exported = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(exported['results'], rows)
        self.assertEqual(exported['task']['output'], str(self.output))
        self.assertEqual(exported['task']['source_report'], str(report))
        self.assertFalse((self.base / 'not-the-job-output').exists())

    def test_task_report_failure_export_preserves_observed_rows_and_task_error_context(self):
        for name in ('a.psd', 'b.psd', 'c.psd'):
            (self.inputs / name).write_bytes(tiny())
        with fail_report_update_at(2):
            self.app.start_button.invoke()
            self.finish()
        self.assertEqual(self.app.phase.get(), '任务异常')
        report = Path(self.app.report_path.get())
        self.assertEqual(len(json.loads(report.read_text(encoding='utf-8'))), 1)
        destination = self.base / '任务异常记录.json'
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(destination)):
            self.app.export_button.invoke()
            self.finish()
        exported = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(exported['task']['state'], 'error')
        self.assertEqual((exported['task']['completed'], exported['task']['total']), (2, 3))
        self.assertIn('结果报告写入失败', exported['task']['message'])
        self.assertEqual(len(exported['results']), 2)
        self.assertEqual(exported['summary']['counted_files'], 2)
        self.assertEqual(exported['task']['source_report'], str(report))
        self.assertTrue(all(Path(row['output']).is_file() for row in exported['results']))
        self.assertEqual(self.app.phase.get(), '任务异常')

    def test_empty_and_setup_error_exports_do_not_claim_files_completed(self):
        self.app.start_button.invoke()
        self.finish()
        for expected_state in ('finished', 'error'):
            if expected_state == 'error':
                self.app.input_path.set(str(self.base / 'missing'))
                self.app.start_button.invoke()
                self.finish()
            destination = self.base / f'{expected_state}.json'
            with patch('tkinter.filedialog.asksaveasfilename', return_value=str(destination)):
                self.app.export_button.invoke()
                self.finish()
            exported = json.loads(destination.read_text(encoding='utf-8'))
            self.assertEqual(exported['task']['state'], expected_state)
            self.assertEqual(exported['task']['completed'], 0)
            self.assertEqual(exported['results'], [])
            self.assertEqual(exported['summary']['counted_files'], 0)
            self.assertEqual(exported['summary']['savings_bytes'], 0)
            if expected_state == 'error':
                self.assertIsNone(exported['task']['total'])
                self.assertEqual(exported['task']['source_report'], '')
                self.assertIn('输入目录不存在', exported['task']['message'])

    def test_statistics_wrap_to_the_real_window_width(self):
        self.root.geometry('800x800')
        self.root.deiconify()
        self.app.start_button.invoke()
        self.finish()
        self.root.update()
        self.assertLessEqual(int(self.app.statistics_label.cget('wraplength')), self.app.winfo_width() - 48)
        self.assertGreater(self.app.statistics_label.winfo_height(), 40)
        self.assertIn('负数表示体积增加', self.app.statistics.get())

    def test_incremental_second_run_explains_full_hashing_and_historical_outputs(self):
        originals = {'a.PSD': tiny(), 'b.PSB': tiny(2, xmp=None)}
        for name, content in originals.items():
            (self.inputs / name).write_bytes(content)
        self.assertIn('完整读盘', self.app.summary.get())
        self.app.start_button.invoke()
        self.finish()
        first_report = Path(self.app.report_path.get())
        first = json.loads(first_report.read_text(encoding='utf-8'))
        self.assertEqual([r['status'] for r in first], ['成功', '无需清理'])
        historical = [r['output'] for r in first]
        before = {path: Path(path).read_bytes() for path in historical}
        self.app.start_button.invoke()
        self.finish()
        report = Path(self.app.report_path.get())
        second = json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual([r['status'] for r in second], ['未变化', '未变化'])
        self.assertEqual([r['output'] for r in second], historical)
        self.assertFalse((report.parent / 'files').exists())
        self.assertIn('历史复用 2', self.app.summary.get())
        self.assertIn('不在本轮重复复制', self.app.summary.get())
        self.assertIn('复用历史副本', self.app.details.get('1.0', 'end'))
        self.assertIn(historical[-1], self.app.details.get('1.0', 'end'))
        activity = self.app.activity.get('1.0', 'end')
        self.assertIn('检查变化', activity)
        self.assertIn('完整读盘', activity)
        self.assertNotIn('清理中', activity)
        self.assertNotIn('校验中', activity)
        for path, content in before.items():
            self.assertEqual(Path(path).read_bytes(), content)
        for name, content in originals.items():
            self.assertEqual((self.inputs / name).read_bytes(), content)

    def test_incremental_invalidation_from_gui_preserves_independent_outputs(self):
        source = self.inputs / '设计.PsB'
        original = tiny(2)
        for reason in ('same-size-time', 'rule', 'missing', 'tampered'):
            with self.subTest(reason=reason):
                output = self.base / reason
                self.app.output_path.set(str(output))
                source.write_bytes(original)
                self.app.start_button.invoke()
                self.finish()
                first_report = Path(self.app.report_path.get())
                first = json.loads(first_report.read_text(encoding='utf-8'))[0]
                historical = Path(first['output'])
                old_output, old_report = historical.read_bytes(), first_report.read_bytes()
                if reason == 'same-size-time':
                    before = source.stat()
                    source.write_bytes(original.replace(b'Shanghai', b'Shenzhen'))
                    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
                    self.assertEqual((source.stat().st_size, source.stat().st_mtime_ns),
                                     (before.st_size, before.st_mtime_ns))
                elif reason == 'missing':
                    historical.unlink()
                elif reason == 'tampered':
                    historical.write_bytes(b'tampered historical output')
                with patch('prototype.batch.RULE_VERSION', 'ticket06-new-rule') if reason == 'rule' else nullcontext():
                    self.app.start_button.invoke()
                    self.finish()
                report = Path(self.app.report_path.get())
                second = json.loads(report.read_text(encoding='utf-8'))[0]
                self.assertEqual(second['status'], '成功')
                self.assertNotEqual(second['output'], first['output'])
                self.assertTrue(Path(second['output']).is_file())
                self.assertIn(report.parent, Path(second['output']).parents)
                self.assertEqual(first_report.read_bytes(), old_report)
                self.assertIn('清理中', self.app.activity.get('1.0', 'end'))
                if reason not in ('missing', 'tampered'):
                    self.assertEqual(historical.read_bytes(), old_output)
                expected = original.replace(b'Shanghai', b'Shenzhen') if reason == 'same-size-time' else original
                self.assertEqual(source.read_bytes(), expected)

    def test_failed_and_partial_files_retry_instead_of_becoming_incremental_hits(self):
        bad, partial, normal = self.inputs / 'a.psd', self.inputs / 'b.psd', self.inputs / 'c.psd'
        bad.write_bytes(b'not PSD')
        partial.write_bytes(tiny(children=[embedded(b'%PDF opaque')]))
        normal.write_bytes(tiny(xmp=None))
        self.app.start_button.invoke()
        self.finish()
        first = json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))
        self.assertEqual([r['status'] for r in first], ['失败', '部分清理', '无需清理'])
        self.app.start_button.invoke()
        self.finish()
        second = json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))
        self.assertEqual([r['status'] for r in second], ['失败', '部分清理', '未变化'])
        self.assertNotEqual(first[1]['output'], second[1]['output'])
        self.assertTrue(second[1]['issues'])
        self.assertTrue(Path(first[1]['output']).is_file())
        self.assertTrue(Path(second[1]['output']).is_file())
        manifest = self.output / '.cleaner-cache.json'
        self.assertEqual(set(json.loads(manifest.read_text(encoding='utf-8'))), {str(normal.resolve())})
        bad.write_bytes(tiny())
        partial.write_bytes(tiny())
        self.app.start_button.invoke()
        self.finish()
        repaired = json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))
        self.assertEqual([r['status'] for r in repaired], ['成功', '成功', '未变化'])

    def test_input_changes_during_hash_history_or_cleaning_never_reuse_or_publish_stale_output(self):
        source = self.inputs / 'a.psd'
        original = tiny()
        changed = original.replace(b'Shanghai', b'Shenzhen')
        path_open = Path.open
        for stage in ('hash', 'history', 'clean'):
            with self.subTest(stage=stage):
                output = self.base / stage
                self.app.output_path.set(str(output))
                source.write_bytes(original)
                self.app.start_button.invoke()
                self.finish()
                historical = Path(json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))[0]['output'])
                old_output = historical.read_bytes()
                manifest = output / '.cleaner-cache.json'
                if stage == 'clean':
                    records = json.loads(manifest.read_text(encoding='utf-8'))
                    records[str(source.resolve())]['rule'] = 'older-rule'
                    manifest.write_text(json.dumps(records), encoding='utf-8')
                old_cache = manifest.read_bytes()
                before = source.stat()
                mutated = False

                def mutate():
                    nonlocal mutated
                    if not mutated:
                        mutated = True
                        source.write_bytes(changed)
                        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))

                def racing_open(path, mode='r', *args, **kwargs):
                    stream = path_open(path, mode, *args, **kwargs)
                    if mode == 'rb' and stage == 'hash' and path == source.resolve() and not mutated:
                        read = stream.read

                        def read_then_change(size=-1):
                            data = read(size)
                            mutate()
                            return data

                        stream.read = read_then_change
                    elif mode == 'rb' and ((stage == 'history' and path == historical)
                                           or (stage == 'clean' and path.name == 'result.tmp')):
                        mutate()
                    return stream

                with patch('pathlib.Path.open', new=racing_open):
                    self.app.start_button.invoke()
                    self.finish()
                self.assertTrue(mutated)
                rows = json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))
                self.assertEqual(rows[0]['status'], '失败')
                self.assertIsNone(rows[0]['output'])
                self.assertRegex(rows[0]['error'], '发生变化|校验失败')
                self.assertEqual(self.app.phase.get(), '处理结束（存在失败）')
                self.assertFalse((Path(self.app.report_path.get()).parent / 'files').exists())
                self.assertEqual(historical.read_bytes(), old_output)
                self.assertEqual(manifest.read_bytes(), old_cache)
                self.assertEqual(source.read_bytes(), changed)
                self.app.start_button.invoke()
                self.finish()
                retried = json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))
                self.assertEqual(retried[0]['status'], '成功')
                self.assertNotEqual(retried[0]['output'], str(historical))

    def test_invalid_cache_from_gui_is_task_error_preserves_records_and_can_recover(self):
        source = self.inputs / 'a.psd'
        source.write_bytes(tiny())
        self.app.start_button.invoke()
        self.finish()
        report = Path(self.app.report_path.get())
        original_report = report.read_bytes()
        historical = Path(json.loads(original_report)[0]['output'])
        original_output = historical.read_bytes()
        manifest = self.output / '.cleaner-cache.json'
        valid = manifest.read_text(encoding='utf-8')
        records = json.loads(valid)
        key = str(source.resolve())
        outside = self.base / 'outside.psd'
        outside.write_bytes(b'private external data')
        escaped = {key: {**records[key], 'output': str(outside.resolve())}}
        damaged_cases = ['not JSON', json.dumps({key: None}), json.dumps(escaped),
                         json.dumps({key: {**records[key], 'source_hash': 'broken'}})]
        for damaged in damaged_cases:
            with self.subTest(damaged=damaged):
                manifest.write_text(damaged, encoding='utf-8')
                with forbid_file_access(outside):
                    self.app.start_button.invoke()
                    self.finish()
                self.assertEqual(self.app.phase.get(), '任务异常')
                self.assertIn('增量记录', self.app.activity.get('1.0', 'end'))
                self.assertEqual(len(self.app.results.get_children()), 0)
                self.assertEqual(manifest.read_text(encoding='utf-8'), damaged)
                self.assertEqual(report.read_bytes(), original_report)
                self.assertEqual(historical.read_bytes(), original_output)
                self.assertFalse((self.output / '.cleaner.lock').exists())
        manifest.write_text(valid, encoding='utf-8')
        self.app.start_button.invoke()
        self.finish()
        recovered = json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))
        self.assertEqual(recovered[0]['status'], '未变化')
        self.assertEqual(recovered[0]['output'], str(historical))
        self.assertEqual(outside.read_bytes(), b'private external data')

    def test_worker_gc_after_prior_window_fixtures_keeps_batch_responsive(self):
        source = self.inputs / 'a.psd'
        original = tiny()
        source.write_bytes(original)
        collected = threading.Event()
        unraisable: list[object] = []
        path_open = Path.open

        def collect_on_read(path, mode='r', *args, **kwargs):
            if mode == 'rb' and path == source.resolve() and not collected.is_set():
                collected.set()
                gc.collect()
            return path_open(path, mode, *args, **kwargs)

        with patch('pathlib.Path.open', new=collect_on_read), patch('sys.unraisablehook', new=unraisable.append):
            self.app.start_button.invoke()
            self.finish()
        self.assertTrue(collected.is_set())
        self.assertEqual(unraisable, [])
        self.assertEqual(self.app.phase.get(), '处理完成')
        rows = json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))
        self.assertEqual(rows[0]['status'], '成功')
        self.assertTrue(Path(rows[0]['output']).is_file())
        self.assertEqual(source.read_bytes(), original)

    def test_stop_waits_for_current_write_or_validation_and_can_restart(self):
        original = tiny()
        for name in ('a.psd', 'b.psd'):
            (self.inputs / name).write_bytes(original)
        self.assertTrue(self.app.stop_button.instate(['disabled']))
        path_open = Path.open
        for stage in ('write', 'validation'):
            with self.subTest(stage=stage):
                output = self.base / stage
                self.app.output_path.set(str(output))
                entered, release = threading.Event(), threading.Event()

                def gated_open(path, mode='r', *args, **kwargs):
                    if path.name == 'result.tmp' and mode == ('xb' if stage == 'write' else 'rb'):
                        entered.set()
                        if not release.wait(10):
                            raise TimeoutError('test filesystem gate timed out')
                    return path_open(path, mode, *args, **kwargs)

                with patch('pathlib.Path.open', new=gated_open):
                    self.app.start_button.invoke()
                    try:
                        self.wait_for(entered)
                        lock = output / '.cleaner.lock'
                        owner = lock.read_bytes()
                        with self.assertRaisesRegex(RuntimeError, '已有任务'):
                            run(self.inputs, output, emit=lambda _: None)
                        self.assertEqual(lock.read_bytes(), owner)
                        self.app.stop_button.invoke()
                        self.root.update()
                        self.assertEqual(self.app.phase.get(), '请求停止')
                        self.assertTrue(self.app.start_button.instate(['disabled']))
                        self.assertTrue(self.app.stop_button.instate(['disabled']))
                        self.assertEqual(len(self.app.results.get_children()), 0)
                        self.app.request_close()
                        self.assertTrue(self.root.winfo_exists())
                    finally:
                        release.set()
                        self.finish()
                self.assertEqual(self.app.phase.get(), '已停止')
                self.assertIn('1 / 2', self.app.summary.get())
                self.assertIn('未处理 1', self.app.summary.get())
                report = Path(self.app.report_path.get())
                rows = json.loads(report.read_text(encoding='utf-8'))
                self.assertEqual([Path(r['source']).name for r in rows], ['a.psd'])
                self.assertEqual(rows[0]['status'], '成功')
                self.assertTrue(Path(rows[0]['output']).is_file())
                self.assertFalse(list(output.glob('*/files/b.psd')))
                self.assertFalse((output / '.cleaner.lock').exists())
                self.app.start_button.invoke()
                self.finish()
                self.assertEqual(self.app.phase.get(), '处理完成')
                self.assertEqual(len(self.app.results.get_children()), 2)
                self.assertTrue(self.app.stop_button.instate(['disabled']))
        for name in ('a.psd', 'b.psd'):
            self.assertEqual((self.inputs / name).read_bytes(), original)

    def test_report_failure_preserves_outputs_shows_task_error_and_can_restart(self):
        for name in ('a.psd', 'b.psd', 'c.psd'):
            (self.inputs / name).write_bytes(tiny())
        with fail_report_update_at(2):
            self.app.start_button.invoke()
            self.finish()
        self.assertEqual(self.app.phase.get(), '任务异常')
        self.assertIn('结果报告写入失败', self.app.activity.get('1.0', 'end'))
        self.assertEqual(len(self.app.results.get_children()), 2)
        report = Path(self.app.report_path.get())
        self.assertEqual(len(json.loads(report.read_text(encoding='utf-8'))), 1)
        self.assertEqual(len(list(self.output.glob('*/files/*.psd'))), 2)
        self.assertFalse(list(self.output.glob('*/files/c.psd')))
        self.assertTrue(self.app.stop_button.instate(['disabled']))
        self.assertFalse(self.app.input_entry.instate(['disabled']))
        self.assertFalse((self.output / '.cleaner.lock').exists())
        self.app.start_button.invoke()
        self.finish()
        self.assertEqual(self.app.phase.get(), '处理完成')
        self.assertEqual(len(self.app.results.get_children()), 3)
        self.assertEqual(len(json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8'))), 3)

    def test_stop_during_scan_stays_requested_until_scan_safely_returns(self):
        (self.inputs / 'a.psd').write_bytes(tiny())
        entered, release = threading.Event(), threading.Event()
        scandir = os.scandir

        def gated_scan(path):
            if Path(path) == self.inputs.resolve():
                entered.set()
                if not release.wait(10):
                    raise TimeoutError('test scan gate timed out')
            return scandir(path)

        with patch('os.scandir', side_effect=gated_scan):
            self.app.start_button.invoke()
            try:
                self.wait_for(entered)
                self.app.stop_button.invoke()
                self.root.update()
                self.assertEqual(self.app.phase.get(), '请求停止')
                self.assertTrue(self.app.start_button.instate(['disabled']))
            finally:
                release.set()
                self.finish()
        self.assertEqual(self.app.phase.get(), '已停止')
        self.assertIn('0 / 1', self.app.summary.get())
        self.assertEqual(json.loads(Path(self.app.report_path.get()).read_text(encoding='utf-8')), [])
        self.assertFalse(list(self.output.glob('*/files/*.psd')))
        self.app.start_button.invoke()
        self.finish()
        self.assertEqual(self.app.phase.get(), '处理完成')

    def test_recursive_option_defaults_on_maps_nested_names_and_freezes_scope(self):
        (self.inputs / '子目录' / '多层 空格').mkdir(parents=True)
        (self.inputs / '空目录').mkdir()
        originals = {
            '同名.PSD': tiny(),
            '子目录/同名.PSD': tiny(2),
            '子目录/多层 空格/设计.PsB': tiny(2),
        }
        for relative, content in originals.items():
            (self.inputs / relative).write_bytes(content)
        (self.inputs / '忽略.jpg').write_bytes(b'not PSD')
        self.assertTrue(self.app.recursive.get())
        self.app.start_button.invoke()
        self.assertTrue(self.app.recursive_check.instate(['disabled']))
        self.app.recursive.set(False)  # Cannot alter the captured running scope.
        self.finish()
        self.assertEqual(len(self.app.results.get_children()), 3)
        self.assertEqual(str(self.app.progress['mode']), 'determinate')
        self.assertEqual(float(self.app.progress['value']), 3)
        self.assertEqual(float(self.app.progress['maximum']), 3)
        self.assertIn('3 / 3', self.app.summary.get())
        self.assertFalse(self.app.recursive_check.instate(['disabled']))
        run_dir = next(self.output.glob('*/report.json')).parent
        self.assertEqual(sorted(p.relative_to(run_dir / 'files').as_posix()
                                for p in (run_dir / 'files').rglob('*') if p.is_file()), sorted(originals))
        for relative, content in originals.items():
            self.assertEqual((self.inputs / relative).read_bytes(), content)
            self.assertLess((run_dir / 'files' / relative).stat().st_size, len(content))
        self.app.start_button.invoke()  # The next job uses the changed setting.
        self.finish()
        self.assertEqual(len(self.app.results.get_children()), 1)
        self.assertIn('1 / 1', self.app.summary.get())
        self.assertEqual(len(list(self.output.glob('*/report.json'))), 2)
        self.assertTrue((run_dir / 'files' / '子目录' / '同名.PSD').is_file())

    def test_start_cleans_current_level_and_keeps_window_responsive(self):
        self.app.recursive_check.invoke()
        self.assertFalse(self.app.recursive.get())
        original = tiny()
        source = self.inputs / '设计.PSD'
        source.write_bytes(original)
        (self.inputs / 'nested').mkdir()
        (self.inputs / 'nested' / 'ignored.psd').write_bytes(b'invalid')
        ticks = []
        self.root.after(1, lambda: ticks.append('responsive'))
        self.app.start_button.invoke()
        self.assertTrue(self.app.input_entry.instate(['disabled']))
        self.assertTrue(self.app.start_button.instate(['disabled']))
        self.app.start_button.invoke()  # Disabled: no second job.
        self.finish()
        self.assertTrue(ticks)
        items = self.app.results.get_children()
        self.assertEqual(len(items), 1)
        self.assertEqual(self.app.results.item(items[0], 'values')[0], '成功')
        reports = list(self.output.glob('*/report.json'))
        self.assertEqual(len(reports), 1)
        published = next(self.output.glob('*/files/设计.PSD'))
        doc = PSD.read(io.BytesIO(published.read_bytes()))
        self.assertEqual(doc.image_resources[Resource.XMP_METADATA].data, XMP.replace(TARGET_ELEMENT, b''))
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.app.phase.get(), '处理完成')
        self.assertFalse(self.app.input_entry.instate(['disabled']))
        text = self.app.activity.get('1.0', 'end')
        for phase in ('检查变化', '清理中', '校验中'):
            self.assertIn(phase, text)

    def test_scan_permission_error_is_visible_without_partial_total_or_results(self):
        denied = self.inputs / '拒绝扫描'
        denied.mkdir()
        original = tiny()
        (self.inputs / 'a.psd').write_bytes(original)
        scandir = os.scandir

        def unavailable(path):
            if Path(path) == denied.resolve():
                raise PermissionError('无权限扫描子目录')
            return scandir(path)

        with patch('os.scandir', side_effect=unavailable):
            self.app.start_button.invoke()
            self.finish()
        self.assertEqual(self.app.phase.get(), '任务异常')
        self.assertIn('无权限扫描子目录', self.app.activity.get('1.0', 'end'))
        self.assertNotIn('扫描完成', self.app.activity.get('1.0', 'end'))
        self.assertEqual(len(self.app.results.get_children()), 0)
        self.assertFalse(self.app.recursive_check.instate(['disabled']))
        self.assertEqual((self.inputs / 'a.psd').read_bytes(), original)
        self.assertFalse(list(self.output.glob('*/files/*')))

    def test_directory_errors_restore_controls_and_preserve_another_job_lock(self):
        self.output.mkdir()
        lock = self.output / '.cleaner.lock'
        lock.write_text('another-job', encoding='utf-8')
        self.app.start_button.invoke()
        self.finish()
        self.assertEqual(self.app.phase.get(), '任务异常')
        self.assertEqual(lock.read_text(encoding='utf-8'), 'another-job')
        self.assertFalse(self.app.output_entry.instate(['disabled']))
        self.assertIn('任务异常', self.app.activity.get('1.0', 'end'))

    def test_worker_setup_error_is_visible_and_does_not_leave_gui_busy(self):
        self.app.input_path.set('~')
        with patch.dict(os.environ, {}, clear=True):
            self.app.start_button.invoke()
            self.finish()
        self.assertEqual(self.app.phase.get(), '任务异常')
        self.assertIn('home', self.app.activity.get('1.0', 'end').lower())

    def test_mixed_results_are_not_presented_as_all_success_and_can_restart(self):
        (self.inputs / 'a-bad.psd').write_bytes(b'not a PSD')
        (self.inputs / 'b-partial.psd').write_bytes(tiny(children=[embedded(b'%PDF opaque')]))
        unchanged = tiny(xmp=None)
        (self.inputs / 'c-normal.psb').write_bytes(unchanged)
        self.app.start_button.invoke()
        # Programmatic edits also must not change captured parameters.
        self.app.output_path.set(str(self.base / 'wrong-output'))
        self.finish()
        statuses = [self.app.results.item(item, 'values')[0] for item in self.app.results.get_children()]
        self.assertEqual(statuses, ['失败', '部分清理', '无需清理'])
        self.assertEqual(self.app.phase.get(), '处理结束（存在失败）')
        self.assertFalse((self.base / 'wrong-output').exists())
        self.assertEqual(next(self.output.glob('*/files/c-normal.psb')).read_bytes(), unchanged)
        first = self.app.results.get_children()[0]
        self.app.results.selection_set(first)
        self.root.update()
        self.assertIn('错误：', self.app.details.get('1.0', 'end'))
        self.assertFalse(list(self.output.glob('*/files/a-bad.psd')))
        self.app.input_path.set(str(self.base / 'missing'))
        self.app.start_button.invoke()
        self.finish()
        self.assertEqual(self.app.phase.get(), '任务异常')
        self.assertIn('输入目录不存在', self.app.activity.get('1.0', 'end'))

    def test_browse_uses_selected_paths_and_overlap_is_rejected(self):
        with patch('tkinter.filedialog.askdirectory', side_effect=[str(self.inputs), str(self.inputs / 'nested-output')]):
            self.app.input_browse.invoke()
            self.app.output_browse.invoke()
        self.assertEqual(self.app.input_path.get(), str(self.inputs))
        self.app.start_button.invoke()
        self.finish()
        self.assertEqual(self.app.phase.get(), '任务异常')
        self.assertFalse((self.inputs / 'nested-output').exists())
        self.assertIn('不能相互包含', self.app.activity.get('1.0', 'end'))

    def test_empty_input_is_explicit_and_output_file_is_not_overwritten(self):
        (self.inputs / '空目录' / '多层').mkdir(parents=True)
        self.app.start_button.invoke()
        self.finish()
        self.assertEqual(self.app.phase.get(), '处理完成')
        self.assertIn('没有可处理', self.app.summary.get())
        self.assertIn('0 / 0', self.app.summary.get())
        occupied = self.base / 'occupied'
        occupied.write_text('preserve', encoding='utf-8')
        self.app.output_path.set(str(occupied))
        self.app.start_button.invoke()
        self.finish()
        self.assertEqual(self.app.phase.get(), '任务异常')
        self.assertEqual(occupied.read_text(encoding='utf-8'), 'preserve')

    def test_thread_launch_error_restores_window_and_empty_paths_do_not_start(self):
        with patch('threading.Thread.start', side_effect=RuntimeError('无法启动工作线程')):
            self.app.start_button.invoke()
            self.finish()
        self.assertEqual(self.app.phase.get(), '任务异常')
        self.assertIn('无法启动工作线程', self.app.activity.get('1.0', 'end'))
        self.app.input_path.set('')
        self.app.start_button.invoke()
        self.assertFalse(self.app.start_button.instate(['disabled']))
        self.assertFalse(self.output.exists())
        self.assertIn('请填写', self.app.activity.get('1.0', 'end'))

    def test_close_during_processing_does_not_destroy_window_or_abort_writes(self):
        (self.inputs / 'a.psd').write_bytes(tiny())
        self.app.start_button.invoke()
        self.app.request_close()
        self.assertTrue(self.root.winfo_exists())
        self.finish()
        self.assertTrue(list(self.output.glob('*/files/a.psd')))


if __name__ == '__main__':
    unittest.main()
