"""Opt-in real Photoshop integration test; never launches Photoshop itself.

Set PSD_HOST_EDIT_REPORT to a single-sample acceptance report and
PSD_HOST_EDIT_OUTPUT to a not-yet-existing directory below that report's parent.
An idle, empty Photoshop session is required. Never retry after a timeout
without human inspection of Photoshop.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(os.environ.get('PSD_HOST_EDIT_REPORT'), 'requires explicit real Photoshop acceptance opt-in')
class HostEditAcceptanceTests(unittest.TestCase):
    def test_nested_edit_and_shared_instance_persist_after_reopen(self):
        report = Path(os.environ['PSD_HOST_EDIT_REPORT'])
        output = Path(os.environ['PSD_HOST_EDIT_OUTPUT'])
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'prototype.host_edit_acceptance',
                 '--report', str(report), '--output', str(output), '--timeout', '120'],
                capture_output=True, text=True, timeout=140,
            )
        except subprocess.TimeoutExpired:
            self.fail('验证子进程超过外围时限；Photoshop 操作可能仍在继续，请人工检查，不能自动重试。')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads((output / 'host-edit-report.json').read_text(encoding='utf-8'))
        self.assertGreater(evidence['nested_depth'], 0)
        self.assertEqual(len(evidence['shared_layer_ids']), 2)
        self.assertNotEqual(*evidence['shared_layer_ids'])
        for flag in ('deep_marker_absent_before', 'deep_marker_after_save',
                     'deep_marker_after_reopen', 'shared_markers_absent_before',
                     'shared_peer_after_save', 'shared_first_after_reopen',
                     'shared_peer_after_reopen', 'render_equal_after_save_reopen',
                     'render_matches_no_edit_save_control',
                     'python_output_unchanged'):
            self.assertIs(evidence[flag], True, flag)
        self.assertEqual(evidence['documents_after'], 0)

        # Independently inspect the saved artifact, not just the verifier's flags.
        import io
        from psd_tools import PSDImage
        from psd_tools.api.layers import SmartObjectLayer
        plan = json.loads((output / 'plan.json').read_text(encoding='utf-8'))
        saved = PSDImage.open(plan['saved'])
        original = PSDImage.open(plan['input'])
        self.assertEqual(
            [(layer.layer_id, layer.name, layer.visible) for layer in saved.descendants()],
            [(layer.layer_id, layer.name, layer.visible) for layer in original.descendants()],
        )
        child = saved
        for layer_id in plan['chain']:
            layer = next(layer for layer in child.descendants()
                         if isinstance(layer, SmartObjectLayer) and layer.layer_id == layer_id)
            child = PSDImage.open(io.BytesIO(layer.smart_object.data))
        markers = [layer for layer in child if layer.name == plan['deepMarker']]
        self.assertEqual(len(markers), 1)
        self.assertFalse(markers[0].visible)
        instances = [next(layer for layer in saved.descendants()
                          if isinstance(layer, SmartObjectLayer) and layer.layer_id == layer_id)
                     for layer_id in plan['shared']]
        self.assertEqual(instances[0].smart_object.unique_id, instances[1].smart_object.unique_id)
        self.assertEqual(instances[0].smart_object.data, instances[1].smart_object.data)
        content = PSDImage.open(io.BytesIO(instances[0].smart_object.data))
        markers = [layer for layer in content if layer.name == plan['sharedMarker']]
        self.assertEqual(len(markers), 1)
        self.assertFalse(markers[0].visible)


if __name__ == '__main__':
    unittest.main()
