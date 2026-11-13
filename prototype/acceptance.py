"""Read-only source/reference inventory and isolated, resource-monitored batch acceptance.

Private design assets and generated files remain local. Workers only write under --output.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any


def root_summary(path: Path) -> dict[str, Any]:
    from psd_tools.constants import Tag
    from psd_tools.psd.header import FileHeader
    from psd_tools.psd.image_data import ImageData
    from psd_tools.psd.layer_and_mask import LayerInfo
    from prototype.file_cleaner import Window
    logging.getLogger("psd_tools").setLevel(logging.CRITICAL)
    with path.open("rb") as stream:
        w = Window(stream, 0, path.stat().st_size)
        header = FileHeader.read(stream)
        width = 8 if header.version == 2 else 4
        w.skip(w.uint(4))
        w.skip(w.uint(4))
        layer_size = w.uint(width)
        layer_start = w.tell()
        records: Any = LayerInfo.read(stream, version=header.version).layer_records if layer_size else []
        identifiers = []
        for record in records:
            for tag in (Tag.SMART_OBJECT_LAYER_DATA1, Tag.SMART_OBJECT_LAYER_DATA2):
                config = record.tagged_blocks.get_data(tag)
                if config is not None:
                    value = config.data.get(b"Idnt")
                    identifiers.append(str(getattr(value, "value", value)).strip("\0"))
                    break
        w.seek(layer_start + layer_size)
        # Only merged pixels are decompressed, never individual layers or linked payloads.
        merged = ImageData.read(stream).get_data(header, split=False, max_output_bytes=128 * 1024**2)
        if not isinstance(merged, bytes):
            raise ValueError("合成图数据类型异常")
        counts = Counter(identifiers)
        return {"version": header.version, "width": header.width, "height": header.height,
                "depth": header.depth, "channels": header.channels, "layer_records": len(records),
                "smart_object_instances": len(identifiers), "shared_id_groups": sum(n > 1 for n in counts.values()),
                "merged_pixels_sha256": hashlib.sha256(merged).hexdigest()}


def worker(source: Path, reference: Path | None, output: Path, response: Path) -> None:
    import psutil
    from prototype.batch import run, sha256_file, atomic_json
    started = time.perf_counter()
    source_before = sha256_file(source)
    reference_before = sha256_file(reference) if reference is not None else None
    rows, report = run(source.parent, output, selected_files={source}, emit=lambda _: None)
    if len(rows) != 1:
        raise ValueError("验收文件未被处理")
    row = rows[0]
    record: dict[str, Any] = {"source_name": source.name, "source_bytes": source.stat().st_size,
                              "source_sha256": source_before, "batch_report": str(report), "batch": row}
    record["source_summary"] = root_summary(source)
    if reference is not None:
        record["jsx_reference_bytes"] = reference.stat().st_size
        record["jsx_reference_sha256"] = reference_before
        record["jsx_reference_summary"] = root_summary(reference)
    if row["output"]:
        result_path = Path(row["output"])
        record["python_output_sha256"] = sha256_file(result_path)
        record["python_summary"] = root_summary(result_path)
        record["python_merged_pixels_equal_source"] = record["python_summary"]["merged_pixels_sha256"] == record["source_summary"]["merged_pixels_sha256"]
        record["python_root_layer_count_equal_source"] = record["python_summary"]["layer_records"] == record["source_summary"]["layer_records"]
        if reference is not None:
            record["python_bytes_minus_jsx"] = result_path.stat().st_size - reference.stat().st_size
            record["jsx_merged_pixels_equal_source"] = record["jsx_reference_summary"]["merged_pixels_sha256"] == record["source_summary"]["merged_pixels_sha256"]
    record["source_unchanged"] = sha256_file(source) == source_before
    record["reference_unchanged"] = reference is None or sha256_file(reference) == reference_before
    record["worker_seconds"] = round(time.perf_counter() - started, 6)
    info = psutil.Process().memory_info()
    record["peak_working_set_bytes"] = getattr(info, "peak_wset", info.rss)
    record["peak_measurement"] = "Windows process PeakWorkingSetSize" if hasattr(info, "peak_wset") else "sampled RSS (not exact peak)"
    atomic_json(response, record)


def supervise(source: Path, reference: Path | None, output: Path, memory_mib: int, timeout: int,
              relative: Path) -> dict[str, Any]:
    import psutil
    directory = output / "measurements" / relative
    directory.mkdir(parents=True)
    response = directory / "result.json"
    args = [sys.executable, "-m", "prototype.acceptance", "--worker", "--input", str(source),
            "--output", str(directory / "batch"), "--response", str(response)]
    if reference is not None:
        args += ["--reference", str(reference)]
    started = time.perf_counter()
    peak = 0
    failure = None
    # stdout/stderr can be large on corrupt metadata: stream to local files, not PIPE.
    with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(args, stdout=stdout, stderr=stderr)
        watched = psutil.Process(process.pid)
        children: dict[int, Any] = {}
        try:
            while process.poll() is None:
                try:
                    # Windows venv python.exe can be a launcher: measure the owned
                    # interpreter descendants too, not just the tiny launcher RSS.
                    for child in watched.children(recursive=True):
                        children[child.pid] = child
                    rss = watched.memory_info().rss
                    for child in list(children.values()):
                        try:
                            rss += child.memory_info().rss
                        except psutil.NoSuchProcess:
                            children.pop(child.pid, None)
                    peak = max(peak, rss)
                except psutil.NoSuchProcess:
                    break
                if peak > memory_mib * 1024**2:
                    failure = "worker memory budget exceeded"
                    break
                if time.perf_counter() - started > timeout:
                    failure = "worker timeout"
                    break
                time.sleep(0.05)
        finally:
            if failure or process.poll() is None:
                # This exact PID is our newly created worker, never Photoshop or a user process.
                for child in reversed(list(children.values())):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                if process.poll() is None:
                    process.kill()
            process.wait()
        if failure is None and process.returncode != 0:
            failure = f"worker exited {process.returncode}; inspect local stderr.log"
    if failure or not response.exists():
        return {"source_name": source.name, "status": "验收未完成", "reason": failure or "missing worker response",
                "sampled_peak_rss_bytes": peak, "seconds": round(time.perf_counter() - started, 6),
                "evidence_directory": str(directory)}
    record = json.loads(response.read_text(encoding="utf-8"))
    record["sampled_peak_rss_bytes"] = peak
    record["supervisor_scope"] = "owned launcher and interpreter descendants"
    record["supervisor_seconds"] = round(time.perf_counter() - started, 6)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="真实 PSD/PSB 隔离验收；不修改输入或 JSX 参考结果")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--memory-mib", type=int, default=2048)
    parser.add_argument("--timeout", type=int, default=600, help="每个样本超时秒数")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--response", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    source, output = args.input.resolve(), args.output.resolve()
    reference = args.reference.resolve() if args.reference is not None else None
    if args.worker:
        if args.response is None:
            raise ValueError("worker response missing")
        worker(source, reference, output, args.response)
        return 0
    if not source.is_dir() or reference is not None and not reference.is_dir():
        raise ValueError("输入与参考位置必须为目录")
    if args.memory_mib <= 0 or args.timeout <= 0:
        raise ValueError("资源预算必须为正数")
    for protected in (source, reference):
        if protected is not None and (protected == output or protected in output.parents or output in protected.parents):
            raise ValueError("验收输出必须与输入和 JSX 参考目录独立")
    from prototype.batch import atomic_json, discover
    from prototype.cleaner import RULE_VERSION
    destination = output / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination.mkdir(parents=True)
    report: dict[str, Any] = {"environment": {"python": sys.version, "platform": platform.platform(), "rule": RULE_VERSION},
                              "memory_budget_mib": args.memory_mib, "timeout_seconds": args.timeout, "samples": []}
    for path in discover(source):
        matching = reference / path.relative_to(source) if reference is not None else None
        if matching is not None and not matching.is_file():
            matching = None
        relative = path.relative_to(source)
        record = supervise(path, matching, destination, args.memory_mib, args.timeout, relative)
        record["sample_relative_path"] = str(relative)
        record["automatic_checks_passed"] = (
            record.get("batch", {}).get("status") in ("成功", "无需清理", "未变化", "部分清理")
            and all(record.get(flag) is True for flag in ("source_unchanged", "reference_unchanged",
                    "python_merged_pixels_equal_source", "python_root_layer_count_equal_source")))
        report["samples"].append(record)
        atomic_json(destination / "acceptance.json", report)
        print(json.dumps({"sample": path.name, "automatic_checks_passed": record["automatic_checks_passed"],
                          "status": record.get("batch", {}).get("status", record.get("status")),
                          "report": str(destination / "acceptance.json")}, ensure_ascii=True), flush=True)
    atomic_json(destination / "acceptance.json", report)
    print(str(destination / "acceptance.json"), flush=True)
    return int(not report["samples"] or any(not r["automatic_checks_passed"] for r in report["samples"]))


if __name__ == "__main__":
    raise SystemExit(main())
