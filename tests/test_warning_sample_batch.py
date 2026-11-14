"""Opt-in acceptance: the real warning sample must not block the next file.

This is normal Python batch acceptance, not Photoshop UI automation. The warning
itself must be established separately through the real host reproduction record.
All writes stay below a new directory selected with PSD_WARNING_BATCH_OUTPUT.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


@unittest.skipUnless(
    all(os.environ.get(key) for key in ('PSD_WARNING_BATCH_SOURCE', 'PSD_WARNING_BATCH_NORMAL', 'PSD_WARNING_BATCH_OUTPUT')),
    'requires explicit real warning-sample batch acceptance opt-in',
)
class WarningSampleBatchTests(unittest.TestCase):
    def test_reported_warning_sample_does_not_block_following_normal_file(self):
        from prototype.batch import sha256_file
        source = Path(os.environ['PSD_WARNING_BATCH_SOURCE']).resolve()
        normal = Path(os.environ['PSD_WARNING_BATCH_NORMAL']).resolve()
        directory = Path(os.environ['PSD_WARNING_BATCH_OUTPUT']).resolve()
        for protected in (source.parent, normal.parent):
            self.assertNotEqual(directory, protected)
            self.assertNotIn(protected, directory.parents)
            self.assertNotIn(directory, protected.parents)
        directory.mkdir(parents=True, exist_ok=False)
        inputs = directory / 'input'
        inputs.mkdir()
        before = [sha256_file(source), sha256_file(normal)]
        fixtures = [inputs / '01-warning-sample.psd', inputs / '02-normal.psd']
        for original, fixture in zip((source, normal), fixtures):
            shutil.copy2(original, fixture)
        output = directory / 'output'
        result = subprocess.run(
            [sys.executable, '-m', 'prototype.batch', '--input', str(inputs), '--output', str(output)],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, 'PYTHONUTF8': '1'}, capture_output=True, text=True, encoding='utf-8', timeout=180,
        )
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        reports = list(output.glob('*/report.json'))
        self.assertEqual(len(reports), 1)
        rows = json.loads(reports[0].read_text(encoding='utf-8'))
        self.assertEqual([Path(row['source']).name for row in rows], [path.name for path in fixtures])
        # The documented real pair: non-native content is retained, not flattened
        # or silently promoted to a complete cleaning success.
        self.assertEqual(rows[0]['status'], '部分清理')
        self.assertTrue(rows[0]['issues'])
        self.assertEqual(rows[1]['status'], '无需清理')
        self.assertEqual(sha256_file(Path(rows[1]['output'])), before[1])
        for row in rows:
            published = Path(row['output']).resolve()
            self.assertIn(output, published.parents)
            self.assertTrue(published.is_file())
        for index, (original, fixture) in enumerate(zip((source, normal), fixtures)):
            self.assertEqual(sha256_file(original), before[index])
            self.assertEqual(sha256_file(fixture), before[index])
        (directory / 'cli-stdout.log').write_text(result.stdout, encoding='utf-8')
        (directory / 'cli-stderr.log').write_text(result.stderr, encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
