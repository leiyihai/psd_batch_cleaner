"""One interpretation of shared batch records for display and JSON export."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


STATUSES = ('成功', '无需清理', '未变化', '部分清理', '失败')
BENEFIT_POLICY = ('仅计本轮已发布且大小已核实的成功、无需清理及部分清理；'
                  '历史复用、失败、未发布和未知大小不计入。部分清理不等于完整成功；负数表示体积增加。')


@dataclass(frozen=True)
class ResultSummary:
    counts: dict[str, int]
    savings_bytes: int = 0
    counted_files: int = 0
    partial_savings_bytes: int = 0
    partial_counted_files: int = 0
    unmeasured_files: int = 0


def _size(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def difference(row: Mapping[str, Any]) -> int | None:
    before, after = _size(row.get('before')), _size(row.get('after'))
    return None if before is None or after is None else before - after


def summarize(rows: Iterable[Mapping[str, Any]]) -> ResultSummary:
    counts = dict.fromkeys(STATUSES, 0)
    savings = counted = partial_savings = partial_counted = unmeasured = 0
    for row in rows:
        status = row['status']
        if status not in counts:
            raise ValueError(f'未知文件状态：{status}')
        counts[status] += 1
        if status not in ('成功', '无需清理', '部分清理') or row.get('published') is not True or not row.get('output'):
            continue
        delta = difference(row)
        if delta is None:
            unmeasured += 1
            continue
        savings += delta
        counted += 1
        if status == '部分清理':
            partial_savings += delta
            partial_counted += 1
    return ResultSummary(counts, savings, counted, partial_savings, partial_counted, unmeasured)


def format_bytes(value: int | None) -> str:
    if type(value) is not int:
        return '未知'
    amount: float = abs(value)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB'):
        if amount < 1024 or unit == 'EiB':
            readable = str(abs(value)) if unit == 'B' else f'{amount:.2f}'
            return f'{value} 字节（{"-" if value < 0 else ""}{readable} {unit}）'
        amount /= 1024
    raise AssertionError('unreachable unit')


def describe_summary(summary: ResultSummary) -> str:
    counts = '，'.join(f'{status} {summary.counts[status]}' for status in STATUSES)
    return (f'{counts}。\n本轮可核实净减少：{format_bytes(summary.savings_bytes)}；计入 {summary.counted_files} 个，'
            f'其中部分清理 {summary.partial_counted_files} 个（{format_bytes(summary.partial_savings_bytes)}）；'
            f'已发布大小未知 {summary.unmeasured_files} 个未计。\n口径：{BENEFIT_POLICY}')


def describe_result(row: Mapping[str, Any]) -> str:
    status = row['status']
    lines = [f'状态：{status}']
    if status == '部分清理':
        lines.append('部分清理不等于完整清理成功；请查看下方未处理内容。')
    elif status == '未变化':
        lines.append('复用历史副本：源内容、规则和输出校验一致；本轮未重复清理或复制。')
    if row.get('error'):
        lines.append(f'错误：{row["error"]}')
    lines.extend((f'输入：{row["source"]}', f'输出：{row.get("output") or "未发布（无可用输出）"}',
                  f'原始大小：{format_bytes(_size(row.get("before")))}',
                  f'结果大小：{format_bytes(_size(row.get("after")))}',
                  f'实际差异（前 - 后）：{format_bytes(difference(row))}',
                  f'清理文档数量：{_size(row.get("documents")) if _size(row.get("documents")) is not None else "未知"}（已检查文档，含无需清理）',
                  f'删除祖先字段数量：{_size(row.get("removed")) if _size(row.get("removed")) is not None else "未知"}（不代表完整成功）',
                  f'跳过外链数量：{_size(row.get("skipped_links")) if _size(row.get("skipped_links")) is not None else "未知"}'))
    lines.append('计入本轮净变化。' if summarize([row]).counted_files else '不计入本轮收益（历史复用、失败、未发布或大小未知）。')
    issues = row.get('issues')
    if issues:
        lines.append('未处理内容：')
        lines.extend(f'{index}. {issue}' for index, issue in enumerate(issues, 1))
    else:
        lines.append('未处理内容：无' if 'issues' in row else '未处理内容：未知（本条记录未提供）')
    return '\n'.join(lines)


def export_report(destination: Path, rows: list[dict[str, Any]], *, task: Mapping[str, Any]) -> None:
    """Export the same records and statistics; never replace a user's file."""
    payload = {'format_version': 1, 'task': dict(task), 'summary': asdict(summarize(rows)),
               'benefit_policy': BENEFIT_POLICY, 'results': rows}
    content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    try:
        stream = destination.open('x', encoding='utf-8', newline='\n')
    except FileExistsError as exc:
        raise FileExistsError(f'导出目标已存在，拒绝覆盖：{destination}') from exc
    try:
        with stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # Creation was exclusive: this can only remove our incomplete export,
        # never an existing user's file rejected by open('x').
        destination.unlink(missing_ok=True)
        raise
