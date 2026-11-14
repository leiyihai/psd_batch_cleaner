"""Shared serial batch engine and CLI. Outputs never replace source files."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable

from prototype.cleaner import RULE_VERSION
from prototype.file_cleaner import clean_file


def sha256_file(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("文件在计算哈希期间发生变化")
    return digest.hexdigest()


def discover(root: Path, *, recursive: bool = True):
    pending = [root]
    while pending:
        current = pending.pop()
        directories = []
        with os.scandir(current) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                # os.walk suppresses is_dir() errors. Explicit non-following
                # stat must succeed before we can claim a complete scan.
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode) or entry.is_junction():
                    continue
                path = Path(entry.path)
                if stat.S_ISDIR(metadata.st_mode):
                    if recursive:
                        directories.append(path)
                elif stat.S_ISREG(metadata.st_mode) and path.suffix.lower() in ('.psd', '.psb'):
                    yield path
        pending.extend(reversed(directories))


def atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class BatchEvent:
    """Shared progress/result notification; observers must not alter the row."""
    kind: str
    phase: str = ''
    source: Path | None = None
    row: dict[str, Any] | None = None
    report: Path | None = None
    message: str = ''
    total: int | None = None
    completed: int = 0


def run(input_dir: Path, output_dir: Path, *, stop=None, emit=print,
        selected_files: set[Path] | None = None, recursive: bool = True,
        on_event: Callable[[BatchEvent], None] | None = None):
    notify = on_event if on_event is not None else lambda event: None
    try:
        notify(BatchEvent('phase', phase='扫描文件'))
        rows, report, total, stopped = _run(input_dir, output_dir, stop=stop, emit=emit,
                            selected_files=selected_files, recursive=recursive, notify=notify)
    except Exception as exc:
        notify(BatchEvent('error', message=str(exc)))
        raise
    notify(BatchEvent('stopped' if stopped else 'finished', report=report, total=total, completed=len(rows)))
    return rows, report


def _run(input_dir: Path, output_dir: Path, *, notify: Callable[[BatchEvent], None], stop=None, emit=print,
         selected_files: set[Path] | None = None, recursive: bool = True):
    def announce_phase(name: str, source: Path) -> None:
        notify(BatchEvent('phase', phase=name, source=source))
        emit(f"{name}：{source}")

    root, output = input_dir.resolve(), output_dir.resolve()
    if not root.is_dir():
        raise ValueError("输入目录不存在")
    if root == output or root in output.parents or output in root.parents:
        raise ValueError("输入和输出目录必须独立，不能相互包含")
    selection = None if selected_files is None else {path.resolve() for path in selected_files}
    if selection is not None and any(root not in path.parents for path in selection):
        raise ValueError("指定验收文件不在输入目录内")
    output.mkdir(parents=True, exist_ok=True)
    stop = stop or threading.Event()
    lock = output / ".cleaner.lock"
    # Refuse overlapping jobs that could race on the cache or the same source tree.
    try:
        stream = lock.open('x', encoding='utf-8')
    except FileExistsError as exc:
        raise RuntimeError(f'输出目录已有任务或遗留锁：{lock}。请先确认该目录无任务运行；仅确认后才可手动移除遗留锁，勿强制解锁。') from exc
    try:
        with stream:
            stream.write(str(os.getpid()))
        manifest = output / ".cleaner-cache.json"
        cache = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        if not isinstance(cache, dict):
            raise ValueError("增量记录格式错误")
        run_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_dir = output / run_name
        run_dir.mkdir()
        rows = []
        report = run_dir / "report.json"
        # Freeze the selected scope before processing: a failed scan must never
        # publish a partial total or be mistaken for a completed directory tree.
        sources = [source for source in discover(root, recursive=recursive)
                   if selection is None or source in selection]
        total = len(sources)
        notify(BatchEvent('scanned', total=total))
        emit(f'扫描完成：共 {total} 个文件')
        for source in sources:
            if stop.is_set():
                break
            row: dict[str, Any] = {"source": str(source), "status": "失败", "output": None}
            started = time.perf_counter()
            infrastructure_error: RuntimeError | None = None
            accessing_output = False
            try:
                announce_phase('检查变化', source)
                digest = sha256_file(source)
                key = str(source)
                previous = cache.get(key, {})
                prior_path = output / previous.get("output", "")
                # Never trust a cache path outside the designated output directory.
                accessing_output = True
                cached = (previous.get("rule") == RULE_VERSION and previous.get("source_hash") == digest
                          and previous.get("status") in ("成功", "无需清理")
                          and output in prior_path.resolve().parents)
                if cached:
                    try:
                        # is_file() suppresses OS errors; only missing outputs
                        # are a cache miss, not an unreadable output volume.
                        cached = (stat.S_ISREG(prior_path.stat().st_mode)
                                  and sha256_file(prior_path) == previous.get("output_hash"))
                    except FileNotFoundError:
                        cached = False
                accessing_output = False
                if cached:
                    if sha256_file(source) != digest:
                        raise ValueError("输入在验证历史输出期间发生变化，稍后重试")
                    row.update(status="未变化", output=str(prior_path))
                else:
                    announce_phase('清理中', source)
                    before = source.stat().st_size
                    accessing_output = True
                    with tempfile.TemporaryDirectory(dir=run_dir) as temporary:
                        staged = Path(temporary) / "result.tmp"
                        result = clean_file(source, staged, on_validate=lambda: announce_phase('校验中', source))
                        output_hash = sha256_file(staged)
                        if sha256_file(source) != digest:
                            raise ValueError("输入在清理期间发生变化，取消发布")
                        after = staged.stat().st_size
                        destination = run_dir / "files" / source.relative_to(root)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            os.link(staged, destination)
                        except FileExistsError as exc:
                            raise ValueError(f'输出已存在，拒绝覆盖：{destination}') from exc
                        row['output'] = str(destination)
                        row.update(status=result.status, before=before,
                                   after=after, removed=result.removed,
                                   documents=result.documents, skipped_links=result.linked,
                                   issues=result.issues, max_depth=result.max_depth,
                                   xmp_bytes=result.xmp_bytes, embedded_psd=result.embedded_psd,
                                   embedded_psb=result.embedded_psb)
                    if result.status != "部分清理":
                        cache[key] = {"rule": RULE_VERSION, "source_hash": digest, "status": result.status,
                                      "output": str(destination.relative_to(output)), "output_hash": output_hash}
                        try:
                            atomic_json(manifest, cache)
                        except Exception as exc:
                            infrastructure_error = RuntimeError(f"输出已发布，但增量记录写入失败，任务终止：{exc}")
                            raise infrastructure_error from exc
            except Exception as exc:
                # psd-tools also raises OSError without errno for malformed
                # content. Only actual OS I/O errors here indicate a potentially
                # unavailable output volume; parser rejections remain per-file.
                if accessing_output and isinstance(exc, OSError) and exc.errno is not None:
                    infrastructure_error = RuntimeError(f'输出读写或发布失败，任务终止：{exc}')
                row["status"] = "失败"
                row["error"] = str(infrastructure_error or exc)
            row["elapsed_seconds"] = round(time.perf_counter() - started, 6)
            rows.append(row)
            try:
                atomic_json(report, rows)
            except Exception as exc:
                infrastructure_error = RuntimeError(f'结果报告写入失败，任务终止；已完成输出和此前报告保留：{exc}')
            notify(BatchEvent('file', source=source, row=dict(row), report=report if report.is_file() else None,
                              total=total, completed=len(rows)))
            emit(f"{row['status']}：{source}" + (f"；{row['error']}" if "error" in row else ""))
            if infrastructure_error is not None:
                raise infrastructure_error
        # Even an empty input or a cancelled run has a report.
        atomic_json(report, rows)
        return rows, report, total, stop.is_set()
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="PSD/PSB 串行批处理：生成独立瘦身副本")
    parser.add_argument("--input", type=Path, required=True, help="输入目录，扫描 PSD/PSB")
    parser.add_argument("--output", type=Path, required=True, help="独立输出目录；每次运行生成新子目录")
    parser.add_argument('--recursive', action=argparse.BooleanOptionalAction, default=True,
                        help='包含子文件夹（默认开启）；--no-recursive 仅扫描当前层级')
    args = parser.parse_args()
    rows, report = run(args.input, args.output, recursive=args.recursive)
    print(f"结果报告：{report}")
    return 1 if any(row["status"] == "失败" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
