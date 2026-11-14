"""Real Tk widgets -> shared batch -> filesystem; no mocked cleaning logic."""
import io
import json
import threading
import os
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


class GuiTests(unittest.TestCase):
    def setUp(self):
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
                        deadline = time.monotonic() + 5
                        while not entered.is_set() and time.monotonic() < deadline:
                            self.root.update()
                            time.sleep(.01)
                        self.assertTrue(entered.is_set())
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
        replace = os.replace

        def report_unavailable(source, destination):
            if Path(destination).name == 'report.json':
                rows = json.loads(Path(source).read_text(encoding='utf-8'))
                if len(rows) == 2:
                    raise PermissionError('报告目录不可写')
            return replace(source, destination)

        with patch('os.replace', side_effect=report_unavailable):
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
                deadline = time.monotonic() + 5
                while not entered.is_set() and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(.01)
                self.assertTrue(entered.is_set())
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
