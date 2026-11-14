"""Bounded-memory PSD/PSB editing: patch metadata and framing, copy everything else.

Unlike PSD.write(), this never reserializes unknown tags, layer records or pixels.
The psd-tools header/descriptor readers and tag definitions supply format semantics.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from pathlib import Path
import os
import struct
import zlib
from typing import BinaryIO, Any, Callable, cast

from psd_tools.constants import Compression, Tag
from psd_tools.psd.header import FileHeader
from psd_tools.psd.descriptor import DescriptorBlock
from psd_tools.psd.layer_and_mask import LayerRecord
from psd_tools.psd.parse_limits import parse_container, parse_context
from psd_tools.psd.tagged_blocks import TaggedBlock

from prototype.cleaner import LINK_TAGS, UnsafeFile, strip_ancestors

CHUNK = 4 * 1024**2
LAYER_METADATA_LIMIT = 128 * 1024**2
LINK_KEYS = {tag.value for tag in LINK_TAGS}
BIG_KEYS = {tag.value for tag in TaggedBlock._BIG_KEYS}
ALTERNATIVE_LAYER_KEYS = {Tag.LAYER_16.value, Tag.LAYER_32.value, Tag.LAYER.value}


@dataclass
class Patch:
    offset: int
    size: int
    data: bytes


@dataclass
class FileResult:
    documents: int = 0
    removed: int = 0
    linked: int = 0
    issues: list[str] = field(default_factory=list)
    max_depth: int = 0
    xmp_bytes: int = 0
    embedded_psd: int = 0
    embedded_psb: int = 0

    @property
    def status(self) -> str:
        return "部分清理" if self.issues else ("成功" if self.removed else "无需清理")


class Window:
    """Absolute-offset reader with strict bounds, also usable by psd-tools readers."""
    def __init__(self, fp: BinaryIO, start: int, end: int):
        if start < 0 or end < start:
            raise UnsafeFile("无效文件区间")
        self.fp, self.start, self.end = fp, start, end
        self.seek(start)

    def tell(self) -> int:
        return self.fp.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        target = offset if whence == 0 else self.tell() + offset if whence == 1 else self.end + offset
        if not self.start <= target <= self.end:
            raise UnsafeFile("文件区间越界")
        return self.fp.seek(target)

    def read(self, size: int = -1) -> bytes:
        size = self.end - self.tell() if size < 0 else size
        if size < 0 or self.tell() + size > self.end:
            raise UnsafeFile("声明长度超过文件区间")
        data = self.fp.read(size)
        if len(data) != size:
            raise UnsafeFile("文件截断")
        return data

    def uint(self, width: int) -> int:
        return int.from_bytes(self.read(width), "big")

    def skip(self, size: int) -> None:
        self.seek(size, 1)


class Planner:
    def __init__(self, fp: BinaryIO, *, max_depth: int, max_xmp_bytes: int):
        self.fp = fp
        self.max_depth = max_depth
        self.max_xmp_bytes = max_xmp_bytes
        self.patches: list[Patch] = []
        self.replacement_bytes = 0
        self.result = FileResult()

    def add_patch(self, patch: Patch) -> None:
        self.replacement_bytes += len(patch.data)
        if self.replacement_bytes > 256 * 1024**2:
            raise UnsafeFile("累计替换数据超过 256 MiB 安全上限")
        self.patches.append(patch)

    def length_patch(self, offset: int, width: int, old: int, new: int) -> None:
        if not 0 <= new < 1 << (width * 8):
            raise UnsafeFile("修改后的长度溢出，不能自动转换文件格式")
        if old != new:
            self.add_patch(Patch(offset, width, new.to_bytes(width, "big")))

    def padding(self, offset: int, old: int, new: int, align: int) -> int:
        before, after = (-old) % align, (-new) % align
        if before != after:
            self.add_patch(Patch(offset, before, b"\0" * after))
        return after - before

    def descriptor(self, item: Window) -> None:
        bounded = Window(self.fp, item.tell(), min(item.end, item.tell() + 16 * 1024**2))
        DescriptorBlock.read(cast(BinaryIO, bounded), padding=1)

    def layer_info(self, window: Window, version: int, *, block: bool = False) -> None:
        if block:
            # Keep LayerInfoBlock's enclosing descriptor/object nesting budget.
            with parse_context(), parse_container():
                self._layer_info_records(window, version, block=True)
        else:
            self._layer_info_records(window, version, block=False)

    def _layer_info_records(self, window: Window, version: int, *, block: bool) -> None:
        # LayerInfo contains both records and *all* channel pixels. Budget the
        # records/index, not the pixel payload; do not bulk-load the outer
        # ChannelImageData. Record extra tags still use the library parser.
        if block:
            end = window.end
        else:
            size = window.uint(8 if version == 2 else 4)
            end = window.tell() + size
            if end > window.end:
                raise UnsafeFile("图层信息区越界")
            if not size:
                return
        start = window.tell()
        body = Window(self.fp, start, end)
        count = int.from_bytes(body.read(2), 'big', signed=True)
        cursor = body.tell()
        lengths: array[int] = array('Q')
        for _ in range(abs(count)):
            budget_end = min(end, start + LAYER_METADATA_LIMIT - len(lengths) * lengths.itemsize)
            record_window = Window(self.fp, cursor, budget_end)
            try:
                record = LayerRecord.read(cast(BinaryIO, record_window), version=version)
            except (UnsafeFile, OSError) as exc:
                if budget_end < end:
                    raise UnsafeFile(f"图层记录元数据无法在 128 MiB 预算内安全读取：{exc}") from exc
                raise
            cursor = record_window.tell()
            for channel in record.channel_info:
                if channel.length == 1:
                    raise UnsafeFile("图层通道长度为 1，缺少完整压缩头")
                if channel.length:
                    if cursor - start + (len(lengths) + 1) * lengths.itemsize > LAYER_METADATA_LIMIT:
                        raise UnsafeFile("图层记录元数据及通道索引超过 128 MiB 校验预算")
                    lengths.append(channel.length)
            del record
        pixels = Window(self.fp, cursor, end)
        for length in lengths:
            # Match psd-tools ChannelData.read: validate the compression enum
            # and declared bounds, but do not decompress/re-encode layer pixels.
            Compression(pixels.uint(2))
            pixels.skip(length - 2)
        # Preserve opaque trailing allocation/padding, just as the bounded
        # LayerInfo reader did. The copy/verify gate checks these bytes too.
        window.seek(end)

    def merged_image(self, w: Window, header: Any) -> None:
        compression = w.uint(2)
        row_bytes = (header.width * header.depth + 7) // 8
        rows = header.height * header.channels
        expected = row_bytes * rows
        if expected > 128 * 1024**2:
            raise UnsafeFile("解压合成图超过 128 MiB 校验上限")
        if compression == 0:
            w.skip(expected)
        elif compression == 1:
            width = 4 if header.version == 2 else 2
            if rows * width > 8 * 1024**2:
                raise UnsafeFile("合成图 RLE 行表超过安全上限")
            table = w.read(rows * width)
            for (length,) in struct.iter_unpack(">I" if width == 4 else ">H", table):
                if length > 16 * 1024**2:
                    raise UnsafeFile("合成图 RLE 行超过安全上限")
                encoded = w.read(length)
                cursor = decoded = 0
                while cursor < len(encoded):
                    control = encoded[cursor]
                    cursor += 1
                    if control < 128:
                        count = control + 1
                        cursor += count
                        decoded += count
                    elif control > 128:
                        cursor += 1
                        decoded += 257 - control
                    if cursor > len(encoded) or decoded > row_bytes:
                        raise UnsafeFile("合成图 RLE 行无效")
                if decoded != row_bytes:
                    raise UnsafeFile("合成图 RLE 行截断")
        elif compression in (2, 3):
            decoder = zlib.decompressobj()
            decoded = 0
            try:
                while w.tell() < w.end and not decoder.eof:
                    chunk = w.read(min(CHUNK, w.end - w.tell()))
                    while chunk:
                        decoded += len(decoder.decompress(chunk, CHUNK))
                        if decoded > expected:
                            raise UnsafeFile("合成图 ZIP 解压长度溢出")
                        chunk = decoder.unconsumed_tail
                if not decoder.eof or decoded != expected:
                    raise UnsafeFile("合成图 ZIP 数据截断")
            except zlib.error as exc:
                raise UnsafeFile(f"合成图 ZIP 数据无效：{exc}") from exc
        else:
            raise UnsafeFile("未知合成图压缩方式")

    def document(self, start: int, size: int, depth: int, label: str) -> int:
        if depth > self.max_depth:
            self.result.issues.append(f"{label}：超过嵌套深度限制，原样保留")
            return 0
        self.result.documents += 1
        if self.result.documents > 10000:
            raise UnsafeFile("嵌入文档数量超过安全上限")
        self.result.max_depth = max(depth, self.result.max_depth)
        w = Window(self.fp, start, start + size)
        header: Any = FileHeader.read(cast(BinaryIO, w))
        version = int(header.version)
        width = 8 if version == 2 else 4
        if depth:
            if version == 2:
                self.result.embedded_psb += 1
            else:
                self.result.embedded_psd += 1
        color_size = w.uint(4)
        w.skip(color_size)
        resource_length_at = w.tell()
        resource_size = w.uint(4)
        resource_end = w.tell() + resource_size
        if resource_end > w.end:
            raise UnsafeFile("图像资源区越界")
        resource_delta = 0
        while w.tell() < resource_end:
            r = Window(self.fp, w.tell(), resource_end)
            if r.read(4) not in (b"8BIM", b"MeSa"):
                raise UnsafeFile("无法识别图像资源签名")
            resource_key = r.uint(2)
            name_length = r.uint(1)
            r.skip(name_length + (-(name_length + 1)) % 2)
            length_at = r.tell()
            length = r.uint(4)
            payload = r.tell()
            padded_end = payload + length + length % 2
            if padded_end > resource_end:
                raise UnsafeFile("图像资源载荷越界")
            if resource_key == 1060:
                self.result.xmp_bytes += length
                if length > self.max_xmp_bytes:
                    raise UnsafeFile(f"{label}：单个 XMP 超过安全上限 {self.max_xmp_bytes} 字节")
                packet = r.read(length)
                cleaned, count = strip_ancestors(packet)
                if count:
                    self.result.removed += count
                    self.add_patch(Patch(payload, length, cleaned))
                    self.length_patch(length_at, 4, length, len(cleaned))
                    resource_delta += len(cleaned) - length
                    resource_delta += self.padding(payload + length, length, len(cleaned), 2)
                del packet, cleaned
            w.seek(padded_end)
        self.length_patch(resource_length_at, 4, resource_size, resource_size + resource_delta)
        layer_length_at = w.tell()
        layer_size = w.uint(width)
        layer_start = w.tell()
        layer_end = layer_start + layer_size
        if layer_end > w.end:
            raise UnsafeFile("图层区越界")
        layer_delta = 0
        if layer_size:
            layers = Window(self.fp, layer_start, layer_end)
            # Read-only validation; pixels/records remain byte-copied, never serialized.
            self.layer_info(layers, version)
            if layers.end - layers.tell() >= 4:
                marker = layers.read(4)
                layers.skip(-4)
                if marker not in (b"8BIM", b"8B64"):
                    mask_size = layers.uint(4)
                    layers.skip(mask_size)
            while layers.tell() < layer_end:
                block_start = layers.tell()
                # Some valid files have a short trailing allocation pad. Preserve it verbatim.
                if layer_end - block_start < 12:
                    layers.seek(layer_end)
                    break
                signature, key = layers.read(4), layers.read(4)
                if signature not in (b"8BIM", b"8B64"):
                    raise UnsafeFile("无法识别全局图层标签签名")
                block_width = 8 if version == 2 and key in BIG_KEYS else 4
                length_at = layers.tell()
                length = layers.uint(block_width)
                payload = layers.tell()
                padded_end = payload + length + (-length) % 4
                if padded_end > layer_end:
                    raise UnsafeFile("全局图层标签越界")
                if key in ALTERNATIVE_LAYER_KEYS:
                    if key == Tag.LAYER.value:
                        raise UnsafeFile("暂不支持安全验证 Layr 替代图层存储，拒绝发布")
                    self.layer_info(Window(self.fp, payload, payload + length), version, block=True)
                if key in LINK_KEYS:
                    delta = self.linked(payload, length, depth, label)
                    self.length_patch(length_at, block_width, length, length + delta)
                    delta += self.padding(payload + length, length, length + delta, 4)
                    layer_delta += delta
                layers.seek(padded_end)
        self.length_patch(layer_length_at, width, layer_size, layer_size + layer_delta)
        w.seek(layer_end)
        self.merged_image(w, header)
        return resource_delta + layer_delta

    def linked(self, start: int, size: int, depth: int, label: str) -> int:
        w = Window(self.fp, start, start + size)
        total_delta = 0
        index = 0
        while w.end - w.tell() >= 8:
            index += 1
            if index > 10000:
                raise UnsafeFile("智能对象条目超过安全上限")
            item_length_at = w.tell()
            item_size = w.uint(8)
            item_start = w.tell()
            item_end = item_start + item_size
            padded_end = item_end + (-item_size) % 4
            if padded_end > w.end:
                raise UnsafeFile("智能对象条目越界")
            item = Window(self.fp, item_start, item_end)
            kind = item.read(4)
            child_label = f"{label}/智能对象{index}"
            delta = 0
            if kind not in (b"liFD", b"liFE", b"liFA"):
                self.result.issues.append(f"{child_label}：未知嵌入类型，原样保留")
            else:
                version = item.uint(4)
                if not 1 <= version <= 8:
                    raise UnsafeFile("不支持的智能对象条目版本")
                uuid_size = item.uint(1)
                item.skip(uuid_size)
                filename_units = item.uint(4)
                if filename_units > 8192:
                    raise UnsafeFile("智能对象名称超过安全上限")
                item.skip(filename_units * 2 + 8)  # filename, filetype, creator
                data_length_at = item.tell()
                data_size = item.uint(8)
                has_descriptor = item.uint(1)
                if has_descriptor:
                    self.descriptor(item)
                if kind == b"liFD":
                    data_start = item.tell()
                    if data_start + data_size > item_end:
                        raise UnsafeFile("嵌入内容越界")
                    signature = item.read(min(6, data_size))
                    if signature in (b"8BPS\x00\x01", b"8BPS\x00\x02"):
                        delta = self.document(data_start, data_size, depth + 1, child_label)
                        self.length_patch(data_length_at, 8, data_size, data_size + delta)
                    else:
                        self.result.issues.append(f"{child_label}：非 PSD/PSB 嵌入内容，原样保留")
                    item.seek(data_start + data_size)
                elif kind == b"liFE":
                    self.result.linked += 1
                    self.descriptor(item)
                    if version > 3:
                        item.skip(16)  # I4Bd timestamp
                    item.skip(8)  # external filesize, deliberately never changed
                    if version > 2:
                        item.skip(data_size)
                else:
                    self.result.issues.append(f"{child_label}：别名，原样保留")
                    item.skip(8)
                # Validate mandatory known suffixes without serializing their bytes.
                if version >= 5:
                    item.skip(item.uint(4) * 2)  # child_id UTF-16
                if version >= 6:
                    item.skip(8)  # mod_time
                if version >= 7:
                    item.skip(1)  # lock_state
                if version >= 8:
                    self.descriptor(item)
                if kind == b"liFE" and version == 2:
                    item.skip(data_size)
                # Any remaining opaque allocation bytes are copied verbatim.
            self.length_patch(item_length_at, 8, item_size, item_size + delta)
            delta += self.padding(item_end, item_size, item_size + delta, 4)
            total_delta += delta
            w.seek(padded_end)
        return total_delta


def plan_file(path: Path, *, max_depth: int = 16, max_xmp_bytes: int = 128 * 1024**2) -> tuple[list[Patch], FileResult]:
    with path.open("rb") as stream:
        planner = Planner(stream, max_depth=max_depth, max_xmp_bytes=max_xmp_bytes)
        planner.document(0, path.stat().st_size, 0, "主文档")
    patches = sorted(planner.patches, key=lambda patch: (patch.offset, patch.size))
    cursor = 0
    for patch in patches:
        if patch.offset < cursor:
            raise UnsafeFile("修改区间重叠")
        cursor = patch.offset + patch.size
    return patches, planner.result


def copy_exact(source: BinaryIO, output: BinaryIO, size: int) -> None:
    while size:
        data = source.read(min(size, CHUNK))
        if not data:
            raise UnsafeFile("复制时文件截断")
        output.write(data)
        size -= len(data)


def verify_ranges(source: Path, output: Path, patches: list[Patch]) -> None:
    """Prove every untouched byte and every planned replacement matches the output."""
    with source.open("rb") as original, output.open("rb") as result:
        cursor = 0
        for patch in [*patches, Patch(source.stat().st_size, 0, b"")]:
            remaining = patch.offset - cursor
            while remaining:
                size = min(remaining, CHUNK)
                left, right = original.read(size), result.read(size)
                if len(left) != size or left != right:
                    raise UnsafeFile("未修改区间校验失败")
                remaining -= size
            if result.read(len(patch.data)) != patch.data:
                raise UnsafeFile("修改区间校验失败")
            original.seek(patch.size, 1)
            cursor = patch.offset + patch.size
        if result.read(1):
            raise UnsafeFile("输出长度不一致")


def clean_file(source: Path, output: Path, *, on_validate: Callable[[], None] | None = None) -> FileResult:
    """Write an exclusive temporary result; caller publishes it only after source recheck."""
    patches, result = plan_file(source)
    created = False
    try:
        with source.open("rb") as original, output.open("xb") as destination:
            created = True
            cursor = 0
            for patch in patches:
                copy_exact(original, destination, patch.offset - cursor)
                destination.write(patch.data)
                original.seek(patch.size, 1)
                cursor = patch.offset + patch.size
            copy_exact(original, destination, source.stat().st_size - cursor)
            destination.flush()
            os.fsync(destination.fileno())
        if on_validate is not None:
            on_validate()
        verify_ranges(source, output, patches)
        remaining, verified = plan_file(output)
        if remaining or verified.removed:
            raise UnsafeFile("输出仍有应清理的祖先数据")
        if result.documents != verified.documents or result.issues != verified.issues:
            raise UnsafeFile("输出文档结构不一致")
        return result
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise
