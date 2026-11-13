"""Download pinned upstream fixtures and exercise real smart-object containers.

The injected copies are explicitly modified fixtures, NOT pristine Photoshop output.
Run with: python -m prototype.verify_samples
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import urllib.request

from psd_tools.constants import LinkedLayerType, Resource
from psd_tools.psd import PSD
from psd_tools.psd.image_resources import ImageResource

from prototype.cleaner import LINK_TAGS, clean_bytes

SAMPLES = ("smart-object-slice.psd", "smart-object-slice.psb", "smart-object-v8.psd", "placedLayer.psd")
XMP = b'''<x:xmpmeta xmlns:x="adobe:ns:meta/"><r:RDF xmlns:r="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><r:Description xmlns:p="http://ns.adobe.com/photoshop/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/" dc:creator="fixture-author"><p:DocumentAncestors><r:Bag><r:li>test-ancestor</r:li></r:Bag></p:DocumentAncestors><p:City>fixture-city</p:City></r:Description></r:RDF></x:xmpmeta>'''


def inject(blob):
    stream = io.BytesIO(blob)
    doc = PSD.read(stream)
    trailer = blob[stream.tell():]
    doc.image_resources[Resource.XMP_METADATA] = ImageResource(key=Resource.XMP_METADATA, data=XMP)
    blocks = doc.layer_and_mask_information.tagged_blocks
    if blocks:
        for tag in LINK_TAGS:
            for item in blocks.get_data(tag, []):
                if item.kind == LinkedLayerType.DATA and item.data and item.data[:6] in (b"8BPS\x00\x01", b"8BPS\x00\x02"):
                    item.data = inject(item.data)
    return doc.tobytes() + trailer


def check_visual_storage(before, after):
    old = PSD.read(io.BytesIO(before))
    new = PSD.read(io.BytesIO(after))
    assert old.image_data.tobytes() == new.image_data.tobytes(), "merged pixels changed"
    old_lm, new_lm = old.layer_and_mask_information, new.layer_and_mask_information
    assert old_lm.layer_info.tobytes() == new_lm.layer_info.tobytes(), "layer storage changed"
    old_blocks, new_blocks = old_lm.tagged_blocks, new_lm.tagged_blocks
    if old_blocks:
        for tag in LINK_TAGS:
            for old_item, new_item in zip(old_blocks.get_data(tag, []), new_blocks.get_data(tag, []), strict=True):
                assert old_item.uuid == new_item.uuid
                if old_item.kind == LinkedLayerType.DATA and old_item.data and old_item.data[:6] in (b"8BPS\x00\x01", b"8BPS\x00\x02"):
                    check_visual_storage(old_item.data, new_item.data)
                else:
                    assert old_item.tobytes() == new_item.tobytes(), "opaque/external content changed"


def main():
    base = Path(".prototype-data").resolve()
    for name in ("original", "injected", "cleaned"):
        (base / name).mkdir(parents=True, exist_ok=True)
    reports = []
    for name in SAMPLES:
        url = f"https://raw.githubusercontent.com/psd-tools/psd-tools/v1.26.1/tests/psd_files/{name}"
        original = base / "original" / name
        if not original.exists():
            with urllib.request.urlopen(url, timeout=60) as response:
                original.write_bytes(response.read())
        pristine = original.read_bytes()
        record = {"sample": name, "url": url, "sha256": hashlib.sha256(pristine).hexdigest()}
        try:
            actual = clean_bytes(pristine)
            record["pristine_status"] = actual.status
            record["pristine_removed"] = actual.removed
            injected = inject(pristine)
            (base / "injected" / name).write_bytes(injected)
            result = clean_bytes(injected)
            assert result.removed > 0
            check_visual_storage(injected, result.data)
            (base / "cleaned" / name).write_bytes(result.data)
            again = clean_bytes(result.data)
            assert again.removed == 0 and again.data == result.data
            record.update(status=result.status, removed=result.removed, documents=result.documents,
                          skipped_links=result.linked, issues=result.issues,
                          pixels_and_layer_storage_unchanged=True)
        except Exception as exc:
            record["error"] = str(exc)
        reports.append(record)
        print(json.dumps(record, ensure_ascii=False))
    (base / "sample-report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(any("error" in record for record in reports))


if __name__ == "__main__":
    raise SystemExit(main())
