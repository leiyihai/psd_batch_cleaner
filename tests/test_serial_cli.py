"""Scheduler-facing contract exercised in independent normal-cleaning processes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Any

from test_prototype import tiny, embedded


class SerialCliTests(unittest.TestCase):
    def invoke(self, *arguments: str, env: dict[str, str] | None = None,
               bootstrap: str | None = None) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, '-c', bootstrap] if bootstrap is not None else [sys.executable, '-m', 'prototype.batch']
        return subprocess.run([*command, *arguments], env={**os.environ, 'PYTHONUTF8': '1', **(env or {})},
                              capture_output=True, text=True, encoding='utf-8', timeout=30)

    def terminal(self, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        self.assertTrue(result.stdout.strip(), result.stderr)
        payload = json.loads(result.stdout.splitlines()[-1])
        self.assertIsInstance(payload, dict)
        return payload

    def test_task_errors_have_exit_two_readable_error_and_machine_terminal_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            (inputs / 'a.psd').write_bytes(tiny())
            for kind in ('missing', 'lock', 'cache'):
                with self.subTest(kind=kind):
                    output = base / kind
                    output.mkdir()
                    lock = output / '.cleaner.lock'
                    manifest = output / '.cleaner-cache.json'
                    if kind == 'lock':
                        lock.write_text('another-task', encoding='utf-8')
                    elif kind == 'cache':
                        manifest.write_text('broken JSON', encoding='utf-8')
                    selected = base / 'missing-input' if kind == 'missing' else inputs
                    result = self.invoke('--input', str(selected), '--output', str(output))
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn('任务异常', result.stderr)
                    self.assertNotIn('Traceback', result.stderr)
                    terminal = self.terminal(result)
                    self.assertEqual((terminal['state'], terminal['exit_code'], terminal['completed']), ('error', 2, 0))
                    self.assertIsNone(terminal['total'])
                    self.assertIsNone(terminal['report'])
                    self.assertTrue(terminal['message'])
                    self.assertFalse(list(output.glob('*/report.json')))
                    if kind == 'lock':
                        self.assertEqual(lock.read_text(encoding='utf-8'), 'another-task')
                    else:
                        self.assertFalse(lock.exists())
                    if kind == 'cache':
                        self.assertEqual(manifest.read_text(encoding='utf-8'), 'broken JSON')

    def test_redirected_legacy_console_encoding_does_not_break_chinese_or_emoji_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / '输入 🎨', base / '输出 🎨'
            inputs.mkdir()
            original = tiny()
            source = inputs / '设计🎨.PSD'
            source.write_bytes(original)
            result = self.invoke('--input', str(inputs), '--output', str(output),
                                 env={'PYTHONIOENCODING': 'ascii', 'PYTHONUTF8': '0'})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            terminal = self.terminal(result)
            self.assertEqual((terminal['state'], terminal['exit_code'], terminal['completed'], terminal['total']),
                             ('finished', 0, 1, 1))
            self.assertEqual(terminal['counts']['成功'], 1)
            self.assertIn('设计🎨.PSD', result.stdout)
            self.assertEqual(source.read_bytes(), original)
            self.assertTrue(Path(terminal['report']).is_file())

    def test_file_failure_takes_priority_over_partial_and_does_not_block_following_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / 'input', base / 'output'
            inputs.mkdir()
            (inputs / '00-bad.psd').write_bytes(b'broken')
            (inputs / '01-partial.psd').write_bytes(tiny(children=[embedded(b'%PDF opaque')]))
            (inputs / '02-normal.psb').write_bytes(tiny(2, xmp=None))
            result = self.invoke('--input', str(inputs), '--output', str(output), env={'PYTHONPROFILEIMPORTTIME': '1'})
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            terminal = self.terminal(result)
            self.assertEqual((terminal['state'], terminal['exit_code'], terminal['completed'], terminal['total']),
                             ('finished', 1, 3, 3))
            self.assertEqual(terminal['counts']['失败'], 1)
            self.assertEqual(terminal['counts']['部分清理'], 1)
            rows = json.loads(Path(terminal['report']).read_text(encoding='utf-8'))
            self.assertEqual([row['status'] for row in rows], ['失败', '部分清理', '无需清理'])
            self.assertIsNone(rows[0]['output'])
            self.assertTrue(all(Path(row['output']).is_file() for row in rows[1:]))
            for forbidden in ('prototype.host_acceptance', 'prototype.host_edit_acceptance', 'win32com', 'pythoncom', 'photoshop.api'):
                self.assertNotIn(forbidden, result.stderr)

    def test_empty_scope_is_successful_with_explicit_zero_total_and_a_real_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / 'input', base / 'output'
            inputs.mkdir()
            result = self.invoke('--input', str(inputs), '--output', str(output))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            terminal = self.terminal(result)
            self.assertEqual((terminal['state'], terminal['completed'], terminal['total']), ('finished', 0, 0))
            self.assertEqual(json.loads(Path(terminal['report']).read_text(encoding='utf-8')), [])

    def test_help_is_usable_even_when_scheduler_inherits_ascii_output(self):
        result = self.invoke('--help', env={'PYTHONIOENCODING': 'ascii', 'PYTHONUTF8': '0'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('串行批处理', result.stdout)
        self.assertIn('--no-recursive', result.stdout)

    def test_task_error_after_a_file_failure_retains_latest_report_and_takes_priority(self):
        bootstrap = ('import runpy,sys; from fs_faults import fail_report_update_at; '
                     'sys.argv[0]="prototype.batch"; '
                     '\nwith fail_report_update_at(2): runpy.run_module("prototype.batch",run_name="__main__")')
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / 'input', base / 'output'
            inputs.mkdir()
            fixtures = {'00-bad.psd': b'broken', '01-valid.psd': tiny(), '02-next.psd': tiny()}
            for name, content in fixtures.items():
                (inputs / name).write_bytes(content)
            result = self.invoke('--input', str(inputs), '--output', str(output), bootstrap=bootstrap,
                                 env={'PYTHONPATH': str(Path(__file__).parent)})
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            terminal = self.terminal(result)
            self.assertEqual((terminal['state'], terminal['exit_code'], terminal['completed'], terminal['total']),
                             ('error', 2, 2, 3))
            self.assertEqual(terminal['counts']['失败'], 1)
            self.assertEqual(terminal['counts']['成功'], 1)
            self.assertIn('结果报告写入失败', terminal['message'])
            report = Path(terminal['report'])
            durable = report.read_bytes()
            self.assertEqual(len(json.loads(durable)), 1)
            published = next(output.glob('*/files/01-valid.psd'))
            original_output = published.read_bytes()
            self.assertFalse(list(output.glob('*/files/02-next.psd')))
            self.assertFalse((output / '.cleaner.lock').exists())
            retried = self.invoke('--input', str(inputs), '--output', str(output))
            self.assertEqual(retried.returncode, 1, retried.stdout + retried.stderr)
            final = self.terminal(retried)
            rows = json.loads(Path(final['report']).read_text(encoding='utf-8'))
            self.assertEqual([row['status'] for row in rows], ['失败', '未变化', '成功'])
            self.assertEqual(report.read_bytes(), durable)
            self.assertEqual(published.read_bytes(), original_output)
            for name, content in fixtures.items():
                self.assertEqual((inputs / name).read_bytes(), content)

    def test_partial_cleaning_is_not_reported_as_all_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / '输入 空格', base / '输出'
            inputs.mkdir()
            source = inputs / 'a-部分.PSD'
            original = tiny(children=[embedded(b'%PDF opaque')])
            source.write_bytes(original)
            (inputs / 'b-正常.psb').write_bytes(tiny(2, xmp=None))
            result = self.invoke('--input', str(inputs), '--output', str(output))
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            terminal = self.terminal(result)
            self.assertEqual((terminal['state'], terminal['exit_code'], terminal['completed'], terminal['total']),
                             ('finished', 3, 2, 2))
            self.assertEqual(terminal['counts']['部分清理'], 1)
            self.assertEqual(terminal['counts']['失败'], 0)
            rows = json.loads(next(output.glob('*/report.json')).read_text(encoding='utf-8'))
            self.assertEqual([row['status'] for row in rows], ['部分清理', '无需清理'])
            self.assertTrue(all(Path(row['output']).is_file() for row in rows))
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
