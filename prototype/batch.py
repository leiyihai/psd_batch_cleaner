"""Serial CLI validation harness, not the final GUI. Outputs never replace source files."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any

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


def discover(root: Path):
    def fail(error):
        raise error
    for current, directories, names in os.walk(root, followlinks=False, onerror=fail):
        directories[:] = sorted(d for d in directories if not Path(current, d).is_symlink())
        for name in sorted(names):
            path = Path(current, name)
            if path.suffix.lower() in (".psd", ".psb") and not path.is_symlink():
                yield path


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


def run(input_dir: Path, output_dir: Path, *, stop=None, emit=print,
        selected_files: set[Path] | None = None):
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
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        manifest = output / ".cleaner-cache.json"
        cache = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        if not isinstance(cache, dict):
            raise ValueError("增量记录格式错误")
        run_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_dir = output / run_name
        run_dir.mkdir()
        rows = []
        report = run_dir / "report.json"
        for source in discover(root):
            if selection is not None and source not in selection:
                continue
            if stop.is_set():
                break
            row: dict[str, Any] = {"source": str(source), "status": "失败", "output": None}
            started = time.perf_counter()
            infrastructure_error: RuntimeError | None = None
            try:
                emit(f"检查变化：{source}")
                digest = sha256_file(source)
                key = str(source)
                previous = cache.get(key, {})
                prior_path = output / previous.get("output", "")
                # Never trust a cache path outside the designated output directory.
                cached = (previous.get("rule") == RULE_VERSION and previous.get("source_hash") == digest
                          and previous.get("status") in ("成功", "无需清理")
                          and output in prior_path.resolve().parents and prior_path.is_file())
                if cached and sha256_file(prior_path) == previous.get("output_hash"):
                    if sha256_file(source) != digest:
                        raise ValueError("输入在验证历史输出期间发生变化，稍后重试")
                    row.update(status="未变化", output=str(prior_path))
                else:
                    emit(f"清理中：{source}")
                    before = source.stat().st_size
                    with tempfile.TemporaryDirectory(dir=run_dir) as temporary:
                        staged = Path(temporary) / "result.tmp"
                        result = clean_file(source, staged)
                        output_hash = sha256_file(staged)
                        if sha256_file(source) != digest:
                            raise ValueError("输入在清理期间发生变化，取消发布")
                        destination = run_dir / "files" / source.relative_to(root)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        os.link(staged, destination)
                        row.update(status=result.status, output=str(destination), before=before,
                                   after=staged.stat().st_size, removed=result.removed,
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
                row["status"] = "失败"
                row["error"] = str(exc)
            row["elapsed_seconds"] = round(time.perf_counter() - started, 6)
            rows.append(row)
            atomic_json(report, rows)
            emit(f"{row['status']}：{source}" + (f"；{row['error']}" if "error" in row else ""))
            if infrastructure_error is not None:
                raise infrastructure_error
        # Even an empty input or a cancelled run has a report.
        atomic_json(report, rows)
        return rows, report
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="PSD/PSB 深度清理验证原型（尚未通过 Photoshop 验收）")
    parser.add_argument("--input", type=Path, required=True, help="输入目录，递归扫描 PSD/PSB")
    parser.add_argument("--output", type=Path, required=True, help="独立输出目录；每次运行生成新子目录")
    args = parser.parse_args()
    rows, report = run(args.input, args.output)
    print(f"结果报告：{report}")
    return 1 if any(row["status"] == "失败" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
