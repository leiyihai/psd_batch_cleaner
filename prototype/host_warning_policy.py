"""Exact, fail-closed warning permission for opt-in host acceptance only.

Normal Python cleaning must never import or invoke this UI policy.
"""
from dataclasses import dataclass
from pathlib import Path

UNKNOWN_DATA_TEXT = '此文档包含未知数据，将扔掉未知数据以保持图层可编辑。若要改为保留原始外观，请选择“拼合”以将复合数据作为拼合的图像载入。'


@dataclass(frozen=True)
class WarningButton:
    handle: int
    text: str
    enabled: bool


@dataclass(frozen=True)
class WarningDialog:
    handle: int
    process_id: int
    window_class: str
    title: str
    messages: tuple[str, ...]
    buttons: tuple[WarningButton, ...]


@dataclass(frozen=True)
class WarningPermission:
    run_id: str
    photoshop_pid: int
    isolated_document: Path


@dataclass(frozen=True)
class HostStage:
    run_id: str
    document: Path
    phase: str
    layer_id: int | None
    document_count: int


def keep_layers_button(dialog: WarningDialog, permission: WarningPermission, stage: HostStage) -> int | None:
    """Return only the permitted Keep Layers control, or refuse without action."""
    if (dialog.window_class != 'PSDialogBox' or dialog.title != 'Adobe Photoshop'
            or dialog.messages != (UNKNOWN_DATA_TEXT,)):
        return None
    if (not permission.run_id or permission.photoshop_pid <= 0
            or dialog.process_id != permission.photoshop_pid
            or stage.run_id != permission.run_id
            or stage.document.resolve() != permission.isolated_document.resolve()
            or (stage.phase, stage.layer_id, stage.document_count) not in (
                ('before-edit-556', 556, 1), ('before-open-main', None, 0))):
        return None
    if (dialog.handle <= 0 or len(dialog.buttons) != 3
            or {button.text for button in dialog.buttons} != {'保留图层', '取消', '拼合'}
            or any(not button.enabled or button.handle <= 0 for button in dialog.buttons)
            or len({button.handle for button in dialog.buttons}) != 3
            or dialog.handle in {button.handle for button in dialog.buttons}):
        return None
    return next(button.handle for button in dialog.buttons if button.text == '保留图层')
