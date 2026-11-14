"""Incremental safety through the shared batch entry and actual filesystem."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prototype.batch import BatchEvent, run
from prototype.cleaner import RULE_VERSION
from test_prototype import tiny


class IncrementalTests(unittest.TestCase):
    def test_record_binds_full_hashes_identity_rule_status_and_output_without_duplicate_copies(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / 'input', base / 'output'
            inputs.mkdir()
            originals = {'a.psd': tiny(), 'b.psb': tiny(2, xmp=None)}
            for name, content in originals.items():
                (inputs / name).write_bytes(content)
            first, _ = run(inputs, output, emit=lambda _: None)
            manifest = output / '.cleaner-cache.json'
            original_manifest = manifest.read_bytes()
            records = json.loads(original_manifest)
            for row in first:
                source = Path(row['source'])
                record = records[str(source.resolve())]
                self.assertEqual(record['source_hash'], hashlib.sha256(originals[source.name]).hexdigest())
                self.assertEqual(record['output_hash'], hashlib.sha256(Path(row['output']).read_bytes()).hexdigest())
                self.assertEqual(record['rule'], RULE_VERSION)
                self.assertEqual(record['status'], row['status'])
                self.assertEqual((output / record['output']).resolve(), Path(row['output']))
            path_open = Path.open

            def no_new_cleaning_output(path, mode='r', *args, **kwargs):
                if mode == 'xb':
                    self.fail('cache hit attempted to save a new cleaning output')
                return path_open(path, mode, *args, **kwargs)

            events: list[BatchEvent] = []
            with patch('pathlib.Path.open', new=no_new_cleaning_output):
                second, report = run(inputs, output, on_event=events.append, emit=lambda _: None)
            self.assertEqual([row['status'] for row in second], ['未变化', '未变化'])
            self.assertEqual([row['output'] for row in second], [row['output'] for row in first])
            self.assertFalse((report.parent / 'files').exists())
            self.assertEqual(manifest.read_bytes(), original_manifest)
            self.assertFalse(any(e.phase in ('清理中', '校验中') for e in events))

    @unittest.skipUnless(os.name == 'nt', 'Windows junction containment acceptance')
    def test_junction_escape_is_rejected_at_load_and_again_before_history_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / 'input', base / 'output'
            inputs.mkdir()
            source = inputs / 'a.psd'
            source.write_bytes(tiny())
            first, _ = run(inputs, output, emit=lambda _: None)
            historical = Path(first[0]['output'])
            original_output = historical.read_bytes()
            outside = base / 'outside'
            outside.mkdir()
            external = outside / 'a.psd'
            external.write_bytes(original_output)
            alias = output / 'alias'
            manifest = output / '.cleaner-cache.json'
            records = json.loads(manifest.read_text(encoding='utf-8'))
            records[str(source.resolve())]['output'] = 'alias/a.psd'
            cache_text = json.dumps(records)
            manifest.write_text(cache_text, encoding='utf-8')
            path_open = Path.open

            def point_to(target):
                if alias.exists():
                    alias.rmdir()
                made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(target)], capture_output=True)
                self.assertEqual(made.returncode, 0, repr(made.stderr))

            def guarded_open(path, mode='r', *args, **kwargs):
                if path.resolve() == external.resolve():
                    self.fail('read escaped historical output through a junction')
                return path_open(path, mode, *args, **kwargs)

            try:
                for escape_at in ('load', 'use'):
                    with self.subTest(escape_at=escape_at):
                        point_to(outside if escape_at == 'load' else historical.parent)
                        events: list[BatchEvent] = []

                        def receive(event):
                            events.append(event)
                            if escape_at == 'use' and event.phase == '检查变化':
                                point_to(outside)

                        with patch('pathlib.Path.open', new=guarded_open):
                            with self.assertRaisesRegex(RuntimeError, '增量记录.*输出引用越界'):
                                run(inputs, output, on_event=receive, emit=lambda _: None)
                        self.assertEqual(events[-1].kind, 'error')
                        self.assertFalse(any(e.kind == 'finished' for e in events))
                        self.assertEqual(manifest.read_text(encoding='utf-8'), cache_text)
                        self.assertEqual(historical.read_bytes(), original_output)
                        self.assertFalse((output / '.cleaner.lock').exists())
            finally:
                if alias.exists():
                    alias.rmdir()
            self.assertEqual(external.read_bytes(), original_output)

    def test_out_of_bounds_cache_reference_is_rejected_without_reading_external_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / 'input', base / 'output'
            inputs.mkdir()
            source = inputs / 'a.psd'
            source.write_bytes(tiny())
            run(inputs, output, emit=lambda _: None)
            manifest = output / '.cleaner-cache.json'
            records = json.loads(manifest.read_text(encoding='utf-8'))
            outside = base / 'outside.psd'
            outside.write_bytes(b'private external data')
            path_open = Path.open
            for reference in ('../outside.psd', str(outside.resolve()), '..\\outside.psd', 'C:outside.psd'):
                with self.subTest(reference=reference):
                    records[str(source.resolve())]['output'] = reference
                    damaged = json.dumps(records)
                    manifest.write_text(damaged, encoding='utf-8')
                    events: list[BatchEvent] = []

                    def guarded_open(path, mode='r', *args, **kwargs):
                        if path.resolve() == outside.resolve():
                            self.fail('attempted to read outside the designated output')
                        return path_open(path, mode, *args, **kwargs)

                    with patch('pathlib.Path.open', new=guarded_open):
                        with self.assertRaisesRegex(RuntimeError, '增量记录.*输出'):
                            run(inputs, output, on_event=events.append, emit=lambda _: None)
                    self.assertEqual(events[-1].kind, 'error')
                    self.assertFalse(any(e.kind in ('file', 'finished') for e in events))
                    self.assertEqual(manifest.read_text(encoding='utf-8'), damaged)
                    self.assertFalse((output / '.cleaner.lock').exists())
            self.assertEqual(outside.read_bytes(), b'private external data')

    def test_invalid_cache_fields_are_not_silently_treated_as_misses(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / 'input', base / 'output'
            inputs.mkdir()
            source = inputs / 'a.psd'
            source.write_bytes(tiny())
            run(inputs, output, emit=lambda _: None)
            manifest = output / '.cleaner-cache.json'
            key = str(source.resolve())
            valid = json.loads(manifest.read_text(encoding='utf-8'))[key]
            malformed = ['not json', '[]', json.dumps({'relative.psd': valid})]
            for field, value in (('rule', ''), ('rule', 3), ('source_hash', 'g' * 64),
                                 ('output_hash', 'f' * 63), ('source_hash', None),
                                 ('status', '部分清理'), ('status', '失败')):
                malformed.append(json.dumps({key: {**valid, field: value}}))
            for field in valid:
                record = valid.copy()
                del record[field]
                malformed.append(json.dumps({key: record}))
            for damaged in malformed:
                with self.subTest(damaged=damaged):
                    manifest.write_text(damaged, encoding='utf-8')
                    events: list[BatchEvent] = []
                    with self.assertRaisesRegex(RuntimeError, '增量记录'):
                        run(inputs, output, on_event=events.append, emit=lambda _: None)
                    self.assertEqual(events[-1].kind, 'error')
                    self.assertFalse(any(e.kind in ('file', 'finished') for e in events))
                    self.assertEqual(manifest.read_text(encoding='utf-8'), damaged)
                    self.assertFalse((output / '.cleaner.lock').exists())

    def test_malformed_cache_record_is_task_error_not_a_completed_file_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / 'input', base / 'output'
            inputs.mkdir()
            source = inputs / 'a.psd'
            original = tiny()
            source.write_bytes(original)
            first, report = run(inputs, output, emit=lambda _: None)
            published = Path(first[0]['output'])
            original_output = published.read_bytes()
            original_report = report.read_bytes()
            manifest = output / '.cleaner-cache.json'
            damaged = json.dumps({str(source.resolve()): None})
            manifest.write_text(damaged, encoding='utf-8')
            events: list[BatchEvent] = []
            with self.assertRaisesRegex(RuntimeError, '增量记录'):
                run(inputs, output, on_event=events.append, emit=lambda _: None)
            self.assertEqual(events[-1].kind, 'error')
            self.assertFalse(any(e.kind in ('file', 'finished') for e in events))
            self.assertEqual(published.read_bytes(), original_output)
            self.assertEqual(report.read_bytes(), original_report)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(manifest.read_text(encoding='utf-8'), damaged)
            self.assertFalse((output / '.cleaner.lock').exists())


if __name__ == '__main__':
    unittest.main()
