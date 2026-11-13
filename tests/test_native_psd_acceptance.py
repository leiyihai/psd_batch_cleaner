"""Explicit real-host acceptance of a user-supplied native embedded PSD branch."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(os.environ.get('PSD_NATIVE_PSD_REPORT'), 'requires explicit native embedded PSD host acceptance opt-in')
class NativePsdAcceptanceTests(unittest.TestCase):
    def test_native_psd_branch_edit_survives_save_reopen_without_shared_pair(self):
        output = Path(os.environ['PSD_NATIVE_PSD_OUTPUT'])
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'prototype.host_edit_acceptance',
                 '--report', os.environ['PSD_NATIVE_PSD_REPORT'], '--output', str(output),
                 '--embedded-format', 'psd', '--skip-shared', '--timeout', '120'],
                capture_output=True, text=True, timeout=140,
            )
        except subprocess.TimeoutExpired:
            self.fail('验证子进程超过外围时限；Photoshop 操作可能仍在继续，请人工检查，不能自动重试。')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads((output / 'host-edit-report.json').read_text(encoding='utf-8'))
        self.assertEqual(evidence['embedded_format'], 'psd')
        self.assertEqual(evidence['shared_check'], 'skipped-explicitly')
        self.assertEqual(evidence['shared_layer_ids'], [])
        for flag in ('shared_markers_absent_before', 'shared_peer_after_save',
                     'shared_first_after_reopen', 'shared_peer_after_reopen'):
            self.assertIsNone(evidence[flag], flag)
        for flag in ('deep_marker_absent_before', 'deep_marker_after_save',
                     'deep_marker_after_reopen', 'render_equal_after_save_reopen',
                     'render_matches_no_edit_save_control', 'python_output_unchanged'):
            self.assertIs(evidence[flag], True, flag)
        self.assertEqual(evidence['documents_after'], 0)

        from psd_tools import PSDImage
        from psd_tools.api.layers import SmartObjectLayer
        plan = json.loads((output / 'plan.json').read_text(encoding='utf-8'))
        self.assertTrue(plan['chain'], '必须实际进入嵌入文档，不能只编辑外层 PSD')
        saved = PSDImage.open(plan['saved'])
        original = PSDImage.open(plan['input'])
        self.assertEqual(
            [(layer.layer_id, layer.name, layer.visible) for layer in saved.descendants()],
            [(layer.layer_id, layer.name, layer.visible) for layer in original.descendants()],
        )
        for document, expected_count in ((original, 0), (saved, 1)):
            for layer_id in plan['chain']:
                layer = next(layer for layer in document.descendants()
                             if isinstance(layer, SmartObjectLayer) and layer.layer_id == layer_id)
                payload = layer.smart_object.data
                document = PSDImage.open(io.BytesIO(payload))
            # Header, not extension or declared filename, proves native PSD v1.
            self.assertEqual(payload[:6], b'8BPS\0\1')
            markers = [layer for layer in document if layer.name == plan['deepMarker']]
            self.assertEqual(len(markers), expected_count)
            if markers:
                self.assertFalse(markers[0].visible)


if __name__ == '__main__':
    unittest.main()
