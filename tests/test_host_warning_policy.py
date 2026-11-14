"""Test the user-authorized UI boundary, never dispatch real window messages."""
from dataclasses import replace
from pathlib import Path
import unittest
from prototype.host_warning_policy import (
    HostStage, WarningButton, WarningDialog, WarningPermission, keep_layers_button,
)


class HostWarningPolicyTests(unittest.TestCase):
    def setUp(self):
        # Text and captions captured from the real root/556 warning, not a
        # permissive substring or an implementation-generated expected string.
        self.dialog = WarningDialog(100, 21940, 'PSDialogBox', 'Adobe Photoshop', (
            '此文档包含未知数据，将扔掉未知数据以保持图层可编辑。若要改为保留原始外观，请选择“拼合”以将复合数据作为拼合的图像载入。',
        ), (WarningButton(101, '保留图层', True), WarningButton(102, '取消', True), WarningButton(103, '拼合', True)))
        self.document = Path('isolated/run-unique/source.psd').resolve()
        self.permission = WarningPermission('run-unique', 21940, self.document)
        self.stage = HostStage('run-unique', self.document, 'before-edit-556', 556, 1)

    def test_only_exact_authorized_warning_selects_keep_layers(self):
        self.assertEqual(keep_layers_button(self.dialog, self.permission, self.stage), 101)

    def test_refuses_wrong_process_run_document_or_host_phase(self):
        cases = [
            (replace(self.dialog, process_id=999), self.permission, self.stage),
            (self.dialog, replace(self.permission, run_id=''), self.stage),
            (self.dialog, self.permission, replace(self.stage, run_id='another-run')),
            (self.dialog, self.permission, replace(self.stage, document=Path('user-original.psd'))),
            (self.dialog, self.permission, replace(self.stage, phase='before-save')),
            (self.dialog, self.permission, replace(self.stage, layer_id=557)),
            (self.dialog, self.permission, replace(self.stage, document_count=2)),
            (self.dialog, self.permission, replace(self.stage, phase='before-open-main', layer_id=None, document_count=1)),
            (self.dialog, self.permission, replace(self.stage, phase='before-open-main', layer_id=556, document_count=0)),
        ]
        for dialog, permission, stage in cases:
            with self.subTest(dialog=dialog, stage=stage):
                self.assertIsNone(keep_layers_button(dialog, permission, stage))

    def test_refuses_altered_text_buttons_and_disabled_controls(self):
        cases = [
            replace(self.dialog, messages=('此文档包含未知数据',)),
            replace(self.dialog, messages=self.dialog.messages + ('另外一个错误',)),
            replace(self.dialog, title='另存为'),
            replace(self.dialog, window_class='#32770'),
            replace(self.dialog, buttons=self.dialog.buttons[:2]),
            replace(self.dialog, buttons=(WarningButton(101, '是', True),) + self.dialog.buttons[1:]),
            replace(self.dialog, buttons=(WarningButton(101, '保留图层', False),) + self.dialog.buttons[1:]),
            replace(self.dialog, buttons=(WarningButton(102, '保留图层', True),) + self.dialog.buttons[1:]),
            replace(self.dialog, handle=101),
        ]
        for dialog in cases:
            with self.subTest(dialog=dialog):
                self.assertIsNone(keep_layers_button(dialog, self.permission, self.stage))

    def test_exact_warning_on_authorized_standalone_copy_with_no_open_documents(self):
        standalone = replace(self.stage, phase='before-open-main', layer_id=None, document_count=0)
        self.assertEqual(keep_layers_button(self.dialog, self.permission, standalone), 101)

    def test_button_order_does_not_select_flatten(self):
        reordered = replace(self.dialog, buttons=tuple(reversed(self.dialog.buttons)))
        self.assertEqual(keep_layers_button(reordered, self.permission, self.stage), 101)


if __name__ == '__main__':
    unittest.main()
