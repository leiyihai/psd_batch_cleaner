"""Opt-in real unknown-data PSB preservation and protective batch refusal.

The sample is byte-extracted from hall root/556, with its warning independently
captured in Photoshop. No host API is imported or called by this acceptance.
"""
import json
import os
from pathlib import Path
import shutil
import unittest


@unittest.skipUnless(
    os.environ.get('PSD_WARNING_BRANCH_SOURCE') and os.environ.get('PSD_WARNING_BRANCH_OUTPUT'),
    'requires explicit real unknown-data branch acceptance opt-in',
)
class WarningBranchAcceptanceTests(unittest.TestCase):
    def test_preserves_real_unknown_branch_and_refuses_damage_without_blocking_next_file(self):
        from prototype.batch import run, sha256_file
        source = Path(os.environ['PSD_WARNING_BRANCH_SOURCE']).resolve()
        output = Path(os.environ['PSD_WARNING_BRANCH_OUTPUT']).resolve()
        expected = '60dcb46c42beb16f4e346aa5a825f0d419d3c46a0b7e0c49b84469bbb62ed22e'
        self.assertEqual(sha256_file(source), expected, 'Requires the recorded real warning payload')
        self.assertNotEqual(output, source.parent)
        self.assertNotIn(source.parent, output.parents)
        self.assertNotIn(output, source.parent.parents)
        output.mkdir(parents=True, exist_ok=False)
        inputs = output / 'input'
        inputs.mkdir()
        good = inputs / '01-known-warning.psb'
        damaged = inputs / '02-truncated-warning.psb'
        following = inputs / '03-following-normal.psd'
        shutil.copy2(source, good)
        damaged.write_bytes(source.read_bytes()[:64])
        from psd_tools import PSDImage
        PSDImage.new('RGB', (2, 2), (10, 20, 30)).save(following)
        fingerprints = {p.name: sha256_file(p) for p in (good, damaged, following)}
        rows, report = run(inputs, output / 'batch', emit=lambda message: None)
        self.assertEqual([Path(row['source']).name for row in rows], list(fingerprints))
        self.assertEqual([row['status'] for row in rows], ['无需清理', '失败', '无需清理'])
        for row, fingerprint in ((rows[0], expected), (rows[2], fingerprints[following.name])):
            published = Path(row['output']).resolve()
            self.assertIn(output / 'batch', published.parents)
            # Entire real warning document, including its unknown fields, stays
            # byte-identical; choosing Keep Layers in Photoshop is not cleaning.
            self.assertEqual(sha256_file(published), fingerprint)
        self.assertIsNone(rows[1]['output'])
        self.assertTrue(rows[1]['error'])
        self.assertFalse((report.parent / 'files' / damaged.name).exists())
        self.assertEqual(json.loads(report.read_text(encoding='utf-8')), rows)
        for path in (good, damaged, following):
            self.assertEqual(sha256_file(path), fingerprints[path.name])
        self.assertEqual(sha256_file(source), expected)


if __name__ == '__main__':
    unittest.main()
