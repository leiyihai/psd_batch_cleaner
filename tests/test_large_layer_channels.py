"""Real batch seam with valid synthetic PSD/PSB channel framing.

Sparse payloads keep fixture construction bounded. They are format regression
fixtures, not substitutes for native Photoshop editability acceptance.
"""
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from psd_tools.constants import Resource, Tag
from psd_tools.psd.header import FileHeader
from psd_tools.psd.image_resources import ImageResource
from psd_tools.psd.layer_and_mask import ChannelInfo, LayerRecord
from psd_tools.psd.descriptor import DescriptorBlock2
from psd_tools.psd.tagged_blocks import TaggedBlock, TaggedBlocks
from psd_tools.psd.parse_limits import ParseLimitError, ParseLimits, parse_context
from prototype.batch import run, sha256_file
from test_prototype import XMP, TARGET_ELEMENT


def large_channel_document(path: Path, version: int, depth: int, *, alternative: bool = False, xmp: bytes = XMP,
                           large: bool = True, declared_extra: int = 0, compression: int = 0,
                           with_descriptor: bool = False) -> None:
    width = 4096 if large else 2
    height = (128 * 1024**2) // (3 * width * (depth // 8)) + 1 if large else 2
    plane = width * height * (depth // 8)
    tagged = TaggedBlocks()
    if with_descriptor:
        tagged[Tag.OBJECT_BASED_EFFECTS_LAYER_INFO] = TaggedBlock(
            key=Tag.OBJECT_BASED_EFFECTS_LAYER_INFO, data=DescriptorBlock2().tobytes())
    record = LayerRecord(right=width, bottom=height, name='large raw RGB layer', tagged_blocks=tagged,
                         channel_info=[ChannelInfo(id=i, length=plane + 2 + (declared_extra if i == 0 else 0)) for i in range(3)]).tobytes(version=version)
    raw_size = 2 + len(record) + 3 * (plane + 2)
    info_size = raw_size + (-raw_size) % 4
    resources = ImageResource(key=Resource.XMP_METADATA, data=xmp).tobytes()
    integer = '>Q' if version == 2 else '>I'
    # Lr16/Lr32 have no inner length prefix; both use 64-bit tag sizes in PSB.
    section_size = ((8 if version == 2 else 4) + 4 + 8 + (8 if version == 2 else 4) + info_size
                    if alternative else (8 if version == 2 else 4) + info_size + 4)
    with path.open('xb') as fp:
        fp.write(FileHeader(version=version, width=2, height=2, channels=3, depth=depth).tobytes())
        fp.write(struct.pack('>II', 0, len(resources)))
        fp.write(resources)
        fp.write(struct.pack(integer, section_size))
        if alternative:
            fp.write(struct.pack(integer, 0))
            fp.write(struct.pack('>I', 0))
            fp.write(b'8BIM' + (b'Lr16' if depth == 16 else b'Lr32'))
        fp.write(struct.pack(integer, info_size))
        fp.write(struct.pack('>h', 1))
        fp.write(record)
        for channel in range(3):
            fp.write(struct.pack('>H', compression))  # RAW unless deliberately invalid.
            fp.write(bytes([10 + channel]))
            fp.seek(plane - 2, 1)
            fp.write(bytes([90 + channel]))
        fp.write(b'\0' * ((-raw_size) % 4))
        if not alternative:
            fp.write(struct.pack('>I', 0))
        fp.write(b'\0\0' + b'\0' * (2 * 2 * 3 * (depth // 8)))


class ReadCeilingFile:
    """Filesystem adapter that rejects a single giant pixel read."""
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def read(self, size=-1):
        if size < 0 or size > 4 * 1024**2:
            raise OSError('single read exceeds 4 MiB test ceiling')
        return self.wrapped.read(size)

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def __enter__(self):
        self.wrapped.__enter__()
        return self

    def __exit__(self, *args):
        return self.wrapped.__exit__(*args)


class LargeLayerChannelTests(unittest.TestCase):
    def test_large_channel_payloads_clean_without_changing_any_other_bytes(self):
        for version, depth, alternative in [(1, 8, False), (2, 8, False), (1, 16, True), (2, 32, True)]:
            with self.subTest(version=version, depth=depth, alternative=alternative), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                inputs = base / 'input'
                inputs.mkdir()
                source = inputs / ('large.psb' if version == 2 else 'large.psd')
                large_channel_document(source, version, depth, alternative=alternative)
                expected = base / 'expected.psd'
                large_channel_document(expected, version, depth, alternative=alternative, xmp=XMP.replace(TARGET_ELEMENT, b''))
                original_hash = sha256_file(source)
                rows, _ = run(inputs, base / 'output', emit=lambda _: None)
                self.assertEqual(rows[0]['status'], '成功', rows[0].get('error'))
                self.assertEqual(rows[0]['removed'], 1)
                self.assertEqual(sha256_file(Path(rows[0]['output'])), sha256_file(expected))
                self.assertEqual(sha256_file(source), original_hash)

    def test_large_channels_do_not_require_a_bulk_payload_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            source = inputs / 'large.psd'
            large_channel_document(source, 1, 8)
            path_open = Path.open

            def limited(path, mode='r', *args, **kwargs):
                handle = path_open(path, mode, *args, **kwargs)
                if mode == 'rb' and path.resolve() == source.resolve():
                    return ReadCeilingFile(handle)
                return handle

            # The batch and cleaner are real. Only the system file reader has
            # a resource ceiling, catching a return to ChannelData bulk reads.
            with patch('pathlib.Path.open', new=limited):
                rows, _ = run(inputs, base / 'output', emit=lambda _: None)
            self.assertEqual(rows[0]['status'], '成功', rows[0].get('error'))
            self.assertTrue(Path(rows[0]['output']).is_file())

    def test_malformed_channel_bounds_and_compression_refuse_without_blocking_next_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            large_channel_document(inputs / 'a-bounds.psd', 1, 8, large=False, declared_extra=1024)
            large_channel_document(inputs / 'b-compression.psb', 2, 32, alternative=True, large=False, compression=99)
            large_channel_document(inputs / 'c-valid.psd', 1, 8, large=False)
            before = {path.name: sha256_file(path) for path in inputs.iterdir()}
            rows, report = run(inputs, base / 'output', emit=lambda _: None)
            self.assertEqual([row['status'] for row in rows], ['失败', '失败', '成功'])
            for row in rows[:2]:
                self.assertIsNone(row['output'])
                self.assertTrue(row['error'])
                self.assertFalse((report.parent / 'files' / Path(row['source']).name).exists())
            for path in inputs.iterdir():
                self.assertEqual(sha256_file(path), before[path.name])

    def test_alternative_layer_storage_keeps_library_nesting_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            large_channel_document(inputs / 'nested.psd', 1, 16, alternative=True,
                                   large=False, with_descriptor=True)
            # Lr16's container plus a descriptor must exceed a one-level budget,
            # matching the previous LayerInfoBlock reader's safety behavior.
            with self.assertRaises(ParseLimitError):
                with parse_context(ParseLimits(max_nesting_depth=1)):
                    rows, report = run(inputs, base / 'output', emit=lambda _: None)
                    self.assertEqual(rows[0]['status'], '失败')
                    self.assertIn('max_nesting_depth', rows[0]['error'])
                    self.assertIsNone(rows[0]['output'])
                    self.assertFalse((report.parent / 'files' / 'nested.psd').exists())

    def test_actual_record_metadata_budget_still_refuses_before_allocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = base / 'input'
            inputs.mkdir()
            source = inputs / 'oversized-extra.psd'
            payload_size = 128 * 1024**2
            record = LayerRecord(bottom=2, right=2).tobytes()
            # A valid unknown tagged block in record extra data, not pixel data.
            extra_prefix = b'\0' * 12 + b'8BIMzzzz' + struct.pack('>I', payload_size)
            prefix = record[:30] + struct.pack('>I', len(extra_prefix) + payload_size) + extra_prefix
            raw_size = 2 + len(prefix) + payload_size
            info_size = raw_size + (-raw_size) % 4
            with source.open('xb') as fp:
                fp.write(FileHeader(width=2, height=2, channels=3, depth=8).tobytes())
                fp.write(struct.pack('>IIIIh', 0, 0, 4 + info_size + 4, info_size, 1))
                fp.write(prefix)
                fp.seek(payload_size, 1)
                fp.write(b'\0' * ((-raw_size) % 4) + struct.pack('>I', 0) + b'\0' * 14)
            before = sha256_file(source)
            rows, report = run(inputs, base / 'output', emit=lambda _: None)
            self.assertEqual(rows[0]['status'], '失败')
            self.assertIn('128 MiB', rows[0]['error'])
            self.assertIsNone(rows[0]['output'])
            self.assertFalse((report.parent / 'files' / source.name).exists())
            self.assertEqual(sha256_file(source), before)


if __name__ == '__main__':
    unittest.main()
