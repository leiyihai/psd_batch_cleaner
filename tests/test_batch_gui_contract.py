"""Shared batch interface used by the GUI, with real files and outputs."""
import io
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
