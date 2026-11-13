import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from psd_tools.constants import LinkedLayerType, Resource, Tag
from psd_tools.psd import PSD
from psd_tools.psd.header import FileHeader
from psd_tools.psd.image_data import ImageData
from psd_tools.psd.image_resources import ImageResource
from psd_tools.psd.layer_and_mask import GlobalLayerMaskInfo, LayerInfo
from psd_tools.psd.linked_layer import LinkedLayer
from psd_tools.psd.tagged_blocks import TaggedBlocks

from prototype.cleaner import UnsafeFile, clean_bytes, strip_ancestors

XMP = b'''<?xpacket begin=""?><x:xmpmeta xmlns:x="adobe:ns:meta/">
<r:RDF xmlns:r="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<r:Description xmlns:p="http://ns.adobe.com/photoshop/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/" dc:creator="Alice &amp; Bob">
<p:DocumentAncestors><r:Bag><r:li>ancestor-id</r:li></r:Bag></p:DocumentAncestors>
<p:City>Shanghai</p:City></r:Description></r:RDF></x:xmpmeta>  <?xpacket end="w"?>'''
TARGET_ELEMENT = b'<p:DocumentAncestors><r:Bag><r:li>ancestor-id</r:li></r:Bag></p:DocumentAncestors>'


def tiny(version=1, xmp=XMP, children=()):
    header = FileHeader(version=version, width=2, height=2, channels=3, depth=8)
    doc = PSD(header=header, image_data=ImageData.new(header, color=(10, 20, 30)))
    if xmp is not None:
        doc.image_resources[Resource.XMP_METADATA] = ImageResource(key=Resource.XMP_METADATA, data=xmp)
    if children:
        lm = doc.layer_and_mask_information
        lm.layer_info = LayerInfo()
        lm.global_layer_mask_info = GlobalLayerMaskInfo()
        lm.tagged_blocks = TaggedBlocks()
        lm.tagged_blocks.set_data(Tag.LINKED_LAYER2, list(children))
    return doc.tobytes()


def embedded(blob, uuid="shared-id"):
    return LinkedLayer(kind=LinkedLayerType.DATA, version=1, uuid=uuid, filename="inside.psb", data=blob)


class XmpTests(unittest.TestCase):
    def test_preserves_every_unrelated_byte(self):
        result, count = strip_ancestors(XMP)
        self.assertEqual(count, 1)
        self.assertEqual(result, XMP.replace(TARGET_ELEMENT, b""))
        self.assertEqual(strip_ancestors(result), (result, 0))

    def test_attribute_and_different_namespace(self):
        source = b'<r xmlns:p="http://ns.adobe.com/photoshop/1.0/" xmlns:q="other" p:DocumentAncestors="abc" q:DocumentAncestors="keep"><p:DocumentAncestors/><q:DocumentAncestors/></r>'
        result, count = strip_ancestors(source)
        self.assertEqual(count, 2)
        self.assertEqual(result, source.replace(b' p:DocumentAncestors="abc"', b'').replace(b'<p:DocumentAncestors/>', b''))

    def test_nested_prefix_rebinding(self):
        source = b'<r xmlns:p="http://ns.adobe.com/photoshop/1.0/"><p:DocumentAncestors/><a xmlns:p="other"><p:DocumentAncestors/></a><p:DocumentAncestors/></r>'
        result, count = strip_ancestors(source)
        self.assertEqual(count, 2)
        self.assertIn(b'<a xmlns:p="other"><p:DocumentAncestors/></a>', result)

    def test_rejects_property_as_entire_document(self):
        with self.assertRaises(UnsafeFile):
            strip_ancestors(b'<p:DocumentAncestors xmlns:p="http://ns.adobe.com/photoshop/1.0/"/>')

    def test_rejects_malformed_dtd_and_utf16(self):
        for source in (b'<unclosed>', b'<!DOCTYPE r [<!ENTITY x "hello">]><r>&x;</r>', '<r/>'.encode('utf-16')):
            with self.subTest(source=source), self.assertRaises(UnsafeFile):
                strip_ancestors(source)


class RecursiveTests(unittest.TestCase):
    def test_psd_psb_nested_and_pixels_preserved(self):
        child = tiny(2, children=[embedded(tiny(1))])
        for version in (1, 2):
            with self.subTest(version=version):
                original = tiny(version, children=[embedded(child)])
                result = clean_bytes(original)
                self.assertEqual(result.removed, 3)
                self.assertEqual(result.documents, 3)
                self.assertEqual(result.status, "成功")
                current, old = result.data, original
                for _ in range(3):
                    new_doc, old_doc = PSD.read(io.BytesIO(current)), PSD.read(io.BytesIO(old))
                    self.assertEqual(new_doc.image_data.tobytes(), old_doc.image_data.tobytes())
                    self.assertEqual(new_doc.image_resources[Resource.XMP_METADATA].data, XMP.replace(TARGET_ELEMENT, b""))
                    blocks = new_doc.layer_and_mask_information.tagged_blocks
                    if blocks and Tag.LINKED_LAYER2 in blocks:
                        new_item = blocks.get_data(Tag.LINKED_LAYER2)[0]
                        old_item = old_doc.layer_and_mask_information.tagged_blocks.get_data(Tag.LINKED_LAYER2)[0]
                        self.assertEqual(new_item.uuid, old_item.uuid)
                        current, old = new_item.data, old_item.data
                self.assertEqual(clean_bytes(result.data).data, result.data)

    def test_external_and_non_psd_preserved(self):
        # EXTERNAL version 1 does not carry DATA; paths are never opened.
        from psd_tools.psd.descriptor import DescriptorBlock
        external = LinkedLayer(kind=LinkedLayerType.EXTERNAL, version=1, uuid="external", filename="missing.psd", linked_file=DescriptorBlock(), filesize=99)
        opaque = embedded(b"%PDF-1.7 opaque content", "pdf-id")
        result = clean_bytes(tiny(children=[external, opaque]))
        self.assertEqual(result.status, "部分清理")
        self.assertEqual(result.linked, 1)
        items = PSD.read(io.BytesIO(result.data)).layer_and_mask_information.tagged_blocks.get_data(Tag.LINKED_LAYER2)
        self.assertEqual(items[0].tobytes(), external.tobytes())
        self.assertEqual(items[1].data, opaque.data)

    def test_no_changes_byte_identical(self):
        blob = tiny(xmp=None) + b"trailing-allocation-padding"
        self.assertEqual(clean_bytes(blob).data, blob)
        self.assertEqual(clean_bytes(blob).status, "无需清理")

    def test_shared_payload_preserves_uuid_and_both_entries(self):
        child = tiny(2)
        result = clean_bytes(tiny(children=[embedded(child), embedded(child)]))
        entries = PSD.read(io.BytesIO(result.data)).layer_and_mask_information.tagged_blocks.get_data(Tag.LINKED_LAYER2)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].data, entries[1].data)
        self.assertEqual([item.uuid for item in entries], ["shared-id", "shared-id"])

    def test_non_lossless_source_refused(self):
        blob = bytearray(tiny())
        marker = b"8BIM" + int(Resource.XMP_METADATA).to_bytes(2, "big")
        # Nonzero resource-name padding is ignored by the reader, then normalized by writer.
        blob[blob.index(marker) + 7] = 127
        with self.assertRaisesRegex(UnsafeFile, "逐字节"):
            clean_bytes(bytes(blob))

    def test_limits_and_invalid_embedded_psd(self):
        with self.assertRaises(UnsafeFile):
            clean_bytes(tiny(), max_total_bytes=1)
        result = clean_bytes(tiny(children=[embedded(tiny())]), max_depth=0)
        self.assertEqual(result.status, "部分清理")
        with self.assertRaises(UnsafeFile):
            clean_bytes(tiny(children=[embedded(b"8BPS\x00\x01broken")]))


class BatchTests(unittest.TestCase):
    def test_batch_rejects_invalid_alternative_layers_and_one_byte_channels(self):
        import struct
        from psd_tools.psd.layer_and_mask import LayerRecord, ChannelInfo
        from psd_tools.psd.tagged_blocks import TaggedBlock
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            alternative = PSD.read(io.BytesIO(tiny(children=[embedded(tiny())])))
            alternative.layer_and_mask_information.tagged_blocks[Tag.LAYER_16] = TaggedBlock(key=Tag.LAYER_16, data=b"\x00\x01")
            (source / "a.psd").write_bytes(alternative.tobytes())
            blob = tiny()
            image_size = len(PSD.read(io.BytesIO(blob)).image_data.tobytes())
            record = LayerRecord(bottom=1, right=1, channel_info=[ChannelInfo(length=1)])
            body = struct.pack(">h", 1) + record.tobytes() + b"\x00"
            body += b"\x00" * (-len(body) % 4)
            section = struct.pack(">I", len(body)) + body + struct.pack(">I", 0)
            image_at = len(blob) - image_size
            malformed = blob[:image_at - 4] + struct.pack(">I", len(section)) + section + blob[image_at:]
            (source / "b.psd").write_bytes(malformed)
            (source / "c.psd").write_bytes(tiny())
            rows, _ = run(source, root / "output", emit=lambda _: None)
            self.assertEqual([r["status"] for r in rows], ["失败", "失败", "成功"])
            self.assertTrue(all(r["output"] is None for r in rows[:2]))

    def test_batch_preserves_valid_16bit_alternative_layer_storage(self):
        from psd_tools.psd.layer_and_mask import LayerInfoBlock
        from psd_tools.psd.tagged_blocks import TaggedBlock
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            doc = PSD.read(io.BytesIO(tiny(children=[embedded(tiny(2))])))
            doc.header.depth = 16
            doc.image_data = ImageData.new(doc.header, color=(1, 2, 3))
            alternative = LayerInfoBlock().tobytes()
            doc.layer_and_mask_information.tagged_blocks[Tag.LAYER_16] = TaggedBlock(key=Tag.LAYER_16, data=alternative)
            (source / "16bit.psd").write_bytes(doc.tobytes())
            rows, _ = run(source, root / "output", emit=lambda _: None)
            self.assertEqual(rows[0]["status"], "成功", rows[0].get("error"))
            result = PSD.read(io.BytesIO(Path(rows[0]["output"]).read_bytes()))
            self.assertEqual(result.header.depth, 16)
            self.assertEqual(result.layer_and_mask_information.tagged_blocks.get_data(Tag.LAYER_16).tobytes(), alternative)
            self.assertEqual(result.image_data.tobytes(), doc.image_data.tobytes())

    def test_batch_rejects_missing_merged_data_and_truncated_layer_records(self):
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            blob = tiny()
            image_size = len(PSD.read(io.BytesIO(blob)).image_data.tobytes())
            (source / "a.psd").write_bytes(blob[:-image_size])
            invalid = PSD.read(io.BytesIO(blob))
            invalid.layer_and_mask_information.layer_info = LayerInfo(layer_count=1)
            (source / "b.psd").write_bytes(invalid.tobytes())
            (source / "c.psd").write_bytes(tiny())
            rows, _ = run(source, root / "output", emit=lambda _: None)
            self.assertEqual([r["status"] for r in rows], ["失败", "失败", "成功"])
            self.assertTrue(all(r["output"] is None for r in rows[:2]))

    def test_batch_rejects_missing_required_linked_suffix(self):
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            # psd-tools permits writing this inconsistent fixture: v8 mandates
            # child_id/mod_time/lock_state/content_descriptor, all absent here.
            invalid = LinkedLayer(kind=LinkedLayerType.DATA, version=8, uuid="bad", filename="bad.psb", data=tiny(2))
            (source / "a.psd").write_bytes(tiny(children=[invalid]))
            (source / "b.psd").write_bytes(tiny())
            rows, _ = run(source, root / "output", emit=lambda _: None)
            self.assertEqual([r["status"] for r in rows], ["失败", "成功"])
            self.assertIsNone(rows[0]["output"])

    def test_streamed_batch_preserves_v8_suffix_and_opaque_entries(self):
        from prototype.batch import run
        from psd_tools.psd.descriptor import DescriptorBlock
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            item = LinkedLayer(kind=LinkedLayerType.DATA, version=8, uuid="stable-id", filename="nested.psb",
                               data=tiny(2), child_id="child", mod_time=12.5, lock_state=0,
                               content_descriptor=DescriptorBlock())
            external = LinkedLayer(kind=LinkedLayerType.EXTERNAL, version=1, uuid="external", filename="missing.psd",
                                   linked_file=DescriptorBlock(), filesize=99)
            opaque = embedded(b"%PDF-1.7 opaque", "opaque")
            for version in (1, 2):
                (source / f"v{version}.psd").write_bytes(tiny(version, children=[item, external, opaque]))
            rows, _ = run(source, root / "output", emit=lambda _: None)
            self.assertEqual([r["status"] for r in rows], ["部分清理", "部分清理"])
            for row in rows:
                self.assertEqual(row["removed"], 2)
                self.assertEqual(row["skipped_links"], 1)
                doc = PSD.read(io.BytesIO(Path(row["output"]).read_bytes()))
                cleaned, link, pdf = doc.layer_and_mask_information.tagged_blocks.get_data(Tag.LINKED_LAYER2)
                self.assertEqual((cleaned.uuid, cleaned.child_id, cleaned.mod_time, cleaned.lock_state),
                                 ("stable-id", "child", 12.5, 0))
                self.assertEqual(cleaned.content_descriptor.tobytes(), item.content_descriptor.tobytes())
                self.assertEqual(link.tobytes(), external.tobytes())
                self.assertEqual(pdf.tobytes(), opaque.tobytes())
                self.assertNotIn(b"DocumentAncestors", PSD.read(io.BytesIO(cleaned.data)).image_resources[Resource.XMP_METADATA].data)

    def test_preserves_opaque_padding_while_cleaning_through_batch(self):
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            blob = bytearray(tiny(children=[embedded(tiny(2))]))
            marker = b"8BIM" + int(Resource.XMP_METADATA).to_bytes(2, "big")
            blob[blob.index(marker) + 7] = 127
            path = source / "opaque.psd"
            path.write_bytes(blob)
            rows, _ = run(source, root / "output", emit=lambda _: None)
            self.assertEqual(rows[0]["status"], "成功", rows[0].get("error"))
            output = Path(rows[0]["output"]).read_bytes()
            self.assertEqual(output[output.index(marker) + 7], 127)
            doc = PSD.read(io.BytesIO(output))
            self.assertNotIn(b"DocumentAncestors", doc.image_resources[Resource.XMP_METADATA].data)
            child = doc.layer_and_mask_information.tagged_blocks.get_data(Tag.LINKED_LAYER2)[0]
            self.assertNotIn(b"DocumentAncestors", PSD.read(io.BytesIO(child.data)).image_resources[Resource.XMP_METADATA].data)
            self.assertEqual(path.read_bytes(), bytes(blob))

    def test_completed_batch_releases_xmp_without_waiting_for_cyclic_gc(self):
        import gc
        import tracemalloc
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            packet = XMP.replace(b"ancestor-id", b"a" * 1024**2)
            blob = tiny(2, xmp=packet)
            for _ in range(6):
                blob = tiny(2, xmp=packet, children=[embedded(blob)])
            (source / "nested.psb").write_bytes(blob)
            gc.collect()
            was_enabled = gc.isenabled()
            gc.disable()
            tracemalloc.start()
            try:
                rows, _ = run(source, root / "output", emit=lambda _: None)
                retained, _ = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
                if was_enabled:
                    gc.enable()
                gc.collect()
            self.assertEqual(rows[0]["status"], "成功", rows[0].get("error"))
            self.assertLess(retained, 2 * 1024**2, f"completed batch retained {retained} bytes")

    def test_acceptance_can_isolate_one_source_without_copying_originals(self):
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            (source / "a.psd").write_bytes(tiny())
            selected = source / "b.psb"
            selected.write_bytes(tiny(2, children=[embedded(tiny(1, children=[embedded(tiny(2))]))]))
            rows, _ = run(source, root / "output", selected_files={selected}, emit=lambda _: None)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source"], str(selected.resolve()))
            self.assertEqual(rows[0]["removed"], 3)
            self.assertEqual(rows[0]["max_depth"], 2)
            self.assertGreaterEqual(rows[0]["elapsed_seconds"], 0)
            self.assertEqual(clean_bytes(Path(rows[0]["output"]).read_bytes()).removed, 0)

    def test_cache_persistence_error_is_a_task_failure_not_success(self):
        import json
        import os
        from unittest.mock import patch
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            (source / "a.psd").write_bytes(tiny())
            (source / "b.psd").write_bytes(tiny())
            output = root / "output"
            replace = os.replace
            def failing_replace(src, dst):
                if Path(dst).name == ".cleaner-cache.json":
                    raise OSError("simulated cache write failure")
                return replace(src, dst)
            with patch("os.replace", side_effect=failing_replace):
                with self.assertRaisesRegex(RuntimeError, "增量记录"):
                    run(source, output, emit=lambda _: None)
            reports = list(output.glob("*/report.json"))
            self.assertEqual(len(reports), 1)
            rows = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "失败")
            self.assertTrue(Path(rows[0]["output"]).is_file())
            self.assertFalse((output / ".cleaner.lock").exists())

    def test_incremental_hash_output_and_rule_invalidation(self):
        import os
        from unittest.mock import patch
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            target = root / "output"
            path = source / "a.PSB"
            original = tiny(2)
            path.write_bytes(original)
            def execute():
                return run(source, target, emit=lambda _: None)[0][0]
            first = execute()
            self.assertEqual(first["status"], "成功")
            self.assertEqual(execute()["status"], "未变化")
            # A same-size edit with restored timestamps must still invalidate the cache.
            before_stat = path.stat()
            path.write_bytes(original.replace(b"Shanghai", b"Shenzhen"))
            os.utime(path, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
            second = execute()
            self.assertEqual(second["status"], "成功")
            self.assertNotEqual(second["output"], first["output"])
            self.assertEqual(execute()["status"], "未变化")
            Path(second["output"]).write_bytes(b"tampered output")
            self.assertEqual(execute()["status"], "成功")
            with patch("prototype.batch.RULE_VERSION", "new-rule"):
                self.assertEqual(execute()["status"], "成功")
            self.assertEqual(path.read_bytes(), original.replace(b"Shanghai", b"Shenzhen"))
            self.assertTrue(Path(first["output"]).exists())

    def test_source_change_during_cached_output_verification_is_not_skipped(self):
        from unittest.mock import patch
        from prototype.batch import run, sha256_file
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            path = source / "a.psd"
            path.write_bytes(tiny())
            output = root / "output"
            rows, _ = run(source, output, emit=lambda _: None)
            cached_output = Path(rows[0]["output"])
            def racing_hash(file):
                result = sha256_file(file)
                if file == cached_output:
                    path.write_bytes(tiny().replace(b"Shanghai", b"Shenzhen"))
                return result
            with patch("prototype.batch.sha256_file", side_effect=racing_hash):
                rows, _ = run(source, output, emit=lambda _: None)
            self.assertEqual(rows[0]["status"], "失败")
            self.assertIn("发生变化", rows[0]["error"])

    def test_no_metadata_copy_and_failed_file_continues(self):
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            (source / "a.psd").write_bytes(b"broken")
            sub = source / "sub"
            sub.mkdir()
            blob = tiny(xmp=None)
            (sub / "b.psd").write_bytes(blob)
            rows, report = run(source, root / "output", emit=lambda _: None)
            self.assertEqual([r["status"] for r in rows], ["失败", "无需清理"])
            self.assertEqual(Path(rows[1]["output"]).read_bytes(), blob)
            self.assertTrue(report.exists())
            self.assertIsNone(rows[0]["output"])
            self.assertFalse((root / "output" / ".cleaner.lock").exists())

    def test_output_overlap_and_existing_file_protected(self):
        import os
        from unittest.mock import patch
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            (source / "a.psd").write_bytes(tiny())
            link = os.link
            collisions = []
            def conflicting_link(src, dst):
                Path(dst).write_bytes(b"existing result")
                collisions.append(Path(dst))
                return link(src, dst)
            with patch("os.link", side_effect=conflicting_link):
                rows, _ = run(source, root / "output", emit=lambda _: None)
            self.assertEqual(rows[0]["status"], "失败")
            self.assertEqual(collisions[0].read_bytes(), b"existing result")
            self.assertIsNone(rows[0]["output"])
            with self.assertRaises(ValueError):
                run(root, root / "output")

    def test_stop_before_next_file(self):
        import threading
        from prototype.batch import run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            (source / "a.psd").write_bytes(tiny())
            (source / "b.psd").write_bytes(tiny())
            stop = threading.Event()
            def emit(message):
                if message.startswith("成功"):
                    stop.set()
            rows, _ = run(source, root / "output", stop=stop, emit=emit)
            self.assertEqual(len(rows), 1)


class AcceptanceTests(unittest.TestCase):
    def test_recursive_same_names_get_independent_acceptance_outputs(self):
        import json
        import os
        from unittest.mock import patch
        from prototype.acceptance import main
        class WorkerProcess:
            pid = os.getpid()
            returncode = 0
            def __init__(self, args, **kwargs):
                response = Path(args[args.index("--response") + 1])
                response.write_text(json.dumps({"batch": {"status": "成功"}, "source_unchanged": True,
                    "reference_unchanged": True, "python_merged_pixels_equal_source": True,
                    "python_root_layer_count_equal_source": True}), encoding="utf-8")
            def poll(self): return 0
            def wait(self): return 0
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            for name in ("a", "b"):
                (source / name).mkdir(parents=True)
                (source / name / "same.psd").write_bytes(tiny())
            args = ["acceptance", "--input", str(source), "--output", str(root / "output")]
            with patch("sys.argv", args), patch("subprocess.Popen", WorkerProcess):
                self.assertEqual(main(), 0)
            self.assertEqual(len(list((root / "output").glob("*/measurements/*/same.psd/result.json"))), 2)

    def test_worker_report_mismatch_makes_acceptance_cli_fail(self):
        import json
        import os
        from unittest.mock import patch
        from prototype.acceptance import main
        # Only mock the external worker boundary, not the cleaner or comparator.
        class WorkerProcess:
            pid = os.getpid()
            returncode = 0
            def __init__(self, args, **kwargs):
                response = Path(args[args.index("--response") + 1])
                response.write_text(json.dumps({"batch": {"status": "成功"}, "source_unchanged": True,
                    "reference_unchanged": True, "python_merged_pixels_equal_source": False,
                    "python_root_layer_count_equal_source": True}), encoding="utf-8")
            def poll(self):
                return 0
            def wait(self):
                return 0
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            (source / "sample.psd").write_bytes(tiny())
            args = ["acceptance", "--input", str(source), "--output", str(root / "output")]
            with patch("sys.argv", args), patch("subprocess.Popen", WorkerProcess):
                self.assertEqual(main(), 1)


if __name__ == "__main__":
    unittest.main()
