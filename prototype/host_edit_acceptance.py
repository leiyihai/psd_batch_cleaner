"""Opt-in real Photoshop editing/linkage acceptance; never used by cleaning.

Only a new isolated copy of one recorded Python output is edited. A running,
empty Photoshop session is required. Timeout exits this process, NOT Photoshop;
a human must inspect the session before any retry.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import shutil
import threading
import uuid
from typing import Any

from prototype.batch import atomic_json, sha256_file
from prototype.host_acceptance import deepest_chain


def shared_pair(blob: bytes) -> list[int]:
    """Choose two root instances of the same native embedded PSD/PSB content."""
    from psd_tools import PSDImage
    from psd_tools.api.layers import SmartObjectLayer

    doc = PSDImage.open(io.BytesIO(blob))
    groups: dict[str, list[int]] = {}
    sizes: dict[str, int] = {}
    for layer in doc.descendants():
        if not isinstance(layer, SmartObjectLayer) or layer.smart_object.kind != 'data':
            continue
        obj = layer.smart_object
        payload = obj.data
        if payload[:6] not in (b'8BPS\0\1', b'8BPS\0\2'):
            continue
        key = obj.unique_id
        groups.setdefault(key, []).append(layer.layer_id)
        sizes[key] = len(payload)
    candidates = [key for key, ids in groups.items() if len(set(ids)) >= 2]
    if not candidates:
        raise ValueError('样本没有可供验收的共享原生 PSD/PSB 嵌入实例')
    key = min(candidates, key=lambda candidate: sizes[candidate])
    return list(dict.fromkeys(groups[key]))[:2]


def main() -> int:
    parser = argparse.ArgumentParser(description='隔离副本的嵌入编辑持久化与共享实例关联实机验收')
    parser.add_argument('--report', type=Path, required=True, help='仅含一个样本的验收报告')
    parser.add_argument('--output', type=Path, required=True, help='报告目录下尚不存在的隔离目录')
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    if args.timeout <= 0:
        raise ValueError('timeout 必须为正数')
    report = json.loads(args.report.read_text(encoding='utf-8'))
    if len(report['samples']) != 1:
        raise ValueError('逐份验收，报告必须恰好包含一个样本')
    record = report['samples'][0]
    output = args.output.resolve()
    if args.report.resolve().parent not in output.parents:
        raise ValueError('输出必须位于报告目录内')
    source = Path(record['batch']['output']).resolve()
    # Protect source designs AND the existing cleaned result from output nesting.
    for protected in (Path(record['batch']['source']).resolve().parent, source.parent):
        if output == protected or protected in output.parents or output in protected.parents:
            raise ValueError('隔离目录不能与原稿或既有结果目录相互包含')
    import pythoncom
    import win32com.client
    from PIL import Image

    created = False
    com_initialized = False
    watchdog = None
    try:
        output.mkdir(parents=True, exist_ok=False)
        created = True

        def timed_out():
            try:
                atomic_json(output / 'host-failure.json', {
                    'status': 'timeout',
                    'note': '只退出验证进程，不取消宿主操作；请人工检查 Photoshop，不自动重试或强制结束宿主。',
                })
            finally:
                # Failure to write timeout evidence must not disable the deadline.
                os._exit(124)

        watchdog = threading.Timer(args.timeout, timed_out)
        watchdog.daemon = True
        watchdog.start()
        # COM discovery and document-count reads can block too: include preflight
        # in the deadline, not just the JSX execution.
        pythoncom.CoInitialize()
        com_initialized = True
        app = win32com.client.GetActiveObject('Photoshop.Application')
        app._FlagAsMethod('DoJavaScript')
        if int(app.Documents.Count) != 0:
            raise ValueError('请先人工确认 Photoshop 空闲且没有打开文档')
        version = str(app.Version)
        source_hash = sha256_file(source)
        fixture = output / ('isolated' + source.suffix)
        shutil.copy2(source, fixture)
        if sha256_file(fixture) != source_hash:
            raise ValueError('隔离副本与既有输出不一致')
        blob = fixture.read_bytes()
        chain = deepest_chain(blob)
        if not chain:
            raise ValueError('缺少原生嵌入链，不能验收深层编辑')
        pair = shared_pair(blob)
        del blob
        token = uuid.uuid4().hex
        plan: dict[str, Any] = {
            'input': str(fixture), 'saved': str(output / ('edited-roundtrip' + source.suffix)),
            'beforePng': str(output / 'before.png'), 'afterPng': str(output / 'after.png'),
            'editedPng': str(output / 'edited-before-save.png'), 'edit': True,
            'log': str(output / 'host-stages.log'), 'chain': chain, 'shared': pair,
            'deepMarker': 'acceptance-deep-' + token, 'sharedMarker': 'acceptance-shared-' + token,
        }
        # Identical embedded saves with NO marker edits form a rendering control.
        # Photoshop can refresh stale embedded composite caches even without edits.
        control_directory = output / 'no-edit-control'
        control_directory.mkdir()
        control = {**plan, 'edit': False}
        for key in ('input', 'saved', 'beforePng', 'afterPng', 'editedPng', 'log'):
            control[key] = str(control_directory / Path(plan[key]).name)
        shutil.copy2(fixture, control['input'])
        template = Path(__file__).with_suffix('.jsx').read_text(encoding='utf-8')
        for directory, current in ((control_directory, control), (output, plan)):
            if int(app.Documents.Count) != 0:
                raise ValueError('前一阶段没有释放宿主文档，停止验收')
            atomic_json(directory / 'plan.json', current)
            script = template.replace('__PLAN__', json.dumps(current, ensure_ascii=True))
            (directory / 'actual-script.jsx').write_text(script, encoding='utf-8')
            if str(app.DoJavaScript(script)) != 'passed':
                raise ValueError('宿主未返回完整通过结果')
        with Image.open(output / 'before.png') as image:
            before = image.convert('RGBA')
        with Image.open(output / 'after.png') as image:
            after = image.convert('RGBA')
        with Image.open(output / 'edited-before-save.png') as image:
            edited = image.convert('RGBA')
        with Image.open(control_directory / 'after.png') as image:
            control_after = image.convert('RGBA')
        entry = {
            'sample': source.name, 'photoshop_version': version, 'nested_depth': len(chain),
            'shared_layer_ids': pair,
            # The script throws at each unmet condition; these describe the
            # completed protocol, not inferred success from merely opening a file.
            'deep_marker_absent_before': True, 'deep_marker_after_save': True,
            'deep_marker_after_reopen': True, 'shared_markers_absent_before': True,
            'shared_peer_after_save': True, 'shared_first_after_reopen': True,
            'shared_peer_after_reopen': True,
            'render_equal_after_save_reopen': edited.size == after.size and edited.tobytes() == after.tobytes(),
            'render_matches_no_edit_save_control': control_after.size == after.size and control_after.tobytes() == after.tobytes(),
            'initial_cached_render_unchanged': before.size == after.size and before.tobytes() == after.tobytes(),
            'python_output_unchanged': sha256_file(source) == source_hash,
            'documents_after': int(app.Documents.Count),
            'python_output_sha256': source_hash,
        }
        atomic_json(output / 'host-edit-report.json', entry)
        print(json.dumps(entry, ensure_ascii=True), flush=True)
        return int(not (entry['render_equal_after_save_reopen']
                        and entry['render_matches_no_edit_save_control']
                        and entry['python_output_unchanged'] and entry['documents_after'] == 0))
    except Exception as exc:
        if created:
            atomic_json(output / 'host-failure.json', {'status': 'failed', 'error': str(exc),
                        'note': '本次不计为通过；重试前人工检查 Photoshop 会话。'})
        raise
    finally:
        # Keep the deadline active during COM teardown as well.
        try:
            if com_initialized:
                pythoncom.CoUninitialize()
        finally:
            if watchdog is not None:
                watchdog.cancel()


if __name__ == '__main__':
    raise SystemExit(main())
