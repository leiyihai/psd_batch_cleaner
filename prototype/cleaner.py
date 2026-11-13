"""Experimental, fail-closed PSD/PSB metadata cleaner. No Photoshop automation.

Uses private/low-level psd-tools APIs deliberately. Not a production compatibility claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
from importlib.metadata import version
import re
from xml.parsers import expat

from psd_tools.constants import LinkedLayerType, Resource, Tag
from psd_tools.psd import PSD

if version("psd-tools") != "1.26.1":
    raise RuntimeError("此验证原型仅支持 psd-tools 1.26.1，请使用项目虚拟环境并安装 requirements.txt")

RULE_VERSION = "ancestors-file-patches-v3-validated-psdtools-1.26.1"
PHOTOSHOP_NS = "http://ns.adobe.com/photoshop/1.0/"
TARGET = PHOTOSHOP_NS + "}DocumentAncestors"
LINK_TAGS = (Tag.LINKED_LAYER1, Tag.LINKED_LAYER2, Tag.LINKED_LAYER3, Tag.LINKED_LAYER_EXTERNAL)
ATTRIBUTE = re.compile(rb'''\s+([^\s=<>/]+)\s*=\s*(?:"[^"]*"|'[^']*')''')


class UnsafeFile(ValueError):
    """Do not publish output when parsing or lossless serialization cannot be verified."""


def strip_ancestors(packet: bytes) -> tuple[bytes, int]:
    """Remove only the namespace-qualified property; retain all other packet bytes.

    Both RDF element and abbreviated attribute representations are supported.
    UTF-16/32 and DTD-bearing packets are rejected rather than normalized.
    """
    if b"\x00" in packet:
        raise UnsafeFile("暂不支持含 NUL 的 XMP 编码")
    parser = expat.ParserCreate(namespace_separator="}")
    namespace_stack = [{"xml": "http://www.w3.org/XML/1998/namespace"}]
    pending_namespaces = []
    elements = []
    removals = []
    count = 0

    def tag_end(start):
        quote = None
        for index in range(start, len(packet)):
            char = packet[index]
            if quote:
                if char == quote:
                    quote = None
            elif char in (34, 39):
                quote = char
            elif char == 62:
                return index + 1
        raise UnsafeFile("XMP 标签未闭合")

    def start(name, attrs):
        nonlocal count
        ns = namespace_stack[-1].copy()
        ns.update(pending_namespaces)
        pending_namespaces.clear()
        namespace_stack.append(ns)
        offset = parser.CurrentByteIndex
        end = tag_end(offset)
        opening = packet[offset:end]
        is_target = name == TARGET
        elements.append((offset, end, opening.rstrip().endswith(b"/>"), is_target))
        if is_target:
            count += 1
        if TARGET in attrs:
            for match in ATTRIBUTE.finditer(opening):
                qname = match.group(1).decode("utf-8")
                if ":" in qname:
                    prefix, local = qname.split(":", 1)
                    if ns.get(prefix) == PHOTOSHOP_NS and local == "DocumentAncestors":
                        removals.append((offset + match.start(), offset + match.end()))
                        count += 1

    def end(name):
        offset, opening_end, self_closing, is_target = elements.pop()
        if is_target:
            finish = opening_end if self_closing else tag_end(parser.CurrentByteIndex)
            removals.append((offset, finish))
        namespace_stack.pop()

    def reject_doctype(*args):
        raise UnsafeFile("不接受含 DTD 的 XMP")

    parser.StartNamespaceDeclHandler = lambda prefix, uri: pending_namespaces.append((prefix or "", uri))
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = reject_doctype
    try:
        parser.Parse(packet, True)
    except (expat.ExpatError, UnicodeError) as exc:
        raise UnsafeFile(f"XMP 无法安全解析：{exc}") from exc
    finally:
        # Handlers close over parser and packet. Break the cycle immediately: nested
        # 96 MB packets must not accumulate until Python's cyclic GC happens to run.
        parser.StartNamespaceDeclHandler = None
        parser.StartElementHandler = None
        parser.EndElementHandler = None
        parser.StartDoctypeDeclHandler = None
    # Merge nested removals; leave every unrelated byte (including packet padding) intact.
    merged = []
    for begin, finish in sorted(removals):
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], finish))
        else:
            merged.append((begin, finish))
    result = bytearray()
    cursor = 0
    for begin, finish in merged:
        result.extend(packet[cursor:begin])
        cursor = finish
    result.extend(packet[cursor:])
    cleaned = bytes(result)
    if count:
        try:
            expat.ParserCreate().Parse(cleaned, True)
        except expat.ExpatError as exc:
            raise UnsafeFile(f"删除属性后 XMP 不再是有效 XML：{exc}") from exc
    return cleaned, count


@dataclass
class Result:
    data: bytes
    documents: int = 0
    removed: int = 0
    issues: list[str] = field(default_factory=list)
    linked: int = 0

    @property
    def status(self):
        return "部分清理" if self.issues else ("成功" if self.removed else "无需清理")


def clean_bytes(data: bytes, *, max_depth: int = 16, max_total_bytes: int = 2 * 1024**3) -> Result:
    """Recursively clean DATA entries once per content hash, never follow external links.

    A byte-exact unmodified read/write roundtrip is mandatory before changing a document.
    This intentionally rejects some valid files rather than silently dropping opaque bytes.
    """
    memo = {}
    total = 0

    def visit(blob, depth, location):
        nonlocal total
        if depth > max_depth:
            return Result(blob, issues=[f"{location}：超过嵌套深度限制 {max_depth}"])
        digest = hashlib.sha256(blob).digest()
        if digest in memo:
            return memo[digest]
        total += len(blob)
        if total > max_total_bytes:
            raise UnsafeFile("累计解析内容超过安全上限")
        if blob[:6] not in (b"8BPS\x00\x01", b"8BPS\x00\x02"):
            raise UnsafeFile(f"{location}：不是 PSD/PSB")
        source = io.BytesIO(blob)
        try:
            doc = PSD.read(source)
            # Preserve trailing bytes; some embedded files are padded to a fixed allocation.
            trailer = blob[source.tell():]
            baseline = doc.tobytes() + trailer
        except Exception as exc:
            raise UnsafeFile(f"{location}：PSD/PSB 解析失败：{exc}") from exc
        result = Result(blob, documents=1)
        resource = doc.image_resources.get(Resource.XMP_METADATA)
        if resource is not None:
            replacement, removed = strip_ancestors(resource.data)
            if removed:
                resource.data = replacement
                result.removed += removed
        blocks = doc.layer_and_mask_information.tagged_blocks
        if blocks is not None:
            for tag in LINK_TAGS:
                if tag not in blocks:
                    continue
                for item in blocks.get_data(tag):
                    label = f"{location}/{item.filename.rstrip(chr(0)) or item.uuid}"
                    if item.kind == LinkedLayerType.EXTERNAL:
                        result.linked += 1
                        continue
                    if item.kind != LinkedLayerType.DATA:
                        result.issues.append(f"{label}：别名/未知嵌入类型，原样保留")
                        continue
                    if not item.data or item.data[:6] not in (b"8BPS\x00\x01", b"8BPS\x00\x02"):
                        result.issues.append(f"{label}：非 PSD/PSB 嵌入内容，原样保留")
                        continue
                    child = visit(item.data, depth + 1, label)
                    item.data = child.data
                    result.documents += child.documents
                    result.removed += child.removed
                    result.linked += child.linked
                    result.issues.extend(child.issues)
        if result.removed:
            if baseline != blob:
                raise UnsafeFile(f"{location}：原文件不能逐字节往返序列化，拒绝发布修改结果")
            try:
                output = doc.tobytes() + trailer
                verified = PSD.read(io.BytesIO(output))
                if verified.tobytes() != doc.tobytes():
                    raise UnsafeFile("输出结构重新解析后不一致")
                # Explicitly check that merged image compression/pixels have not changed.
                if verified.image_data.tobytes() != doc.image_data.tobytes():
                    raise UnsafeFile("输出合成图数据不一致")
                result.data = output
            except Exception as exc:
                raise UnsafeFile(f"{location}：输出校验失败：{exc}") from exc
        memo[digest] = result
        return result

    return visit(data, 0, "主文档")
