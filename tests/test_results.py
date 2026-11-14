"""Shared result records, conservative statistics and JSON export contracts."""
import errno
import json
import os
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

from prototype.batch import BatchEvent, run
from test_prototype import tiny, embedded
from result_scenarios import result_scenarios


class ResultStatisticsTests(unittest.TestCase):
    def test_counts_and_savings_include_only_measured_current_publications(self):
        from prototype.results import summarize
        rows = result_scenarios()
        summary = summarize(rows)
        self.assertEqual(summary.counts, {'成功': 2, '无需清理': 1, '未变化': 1, '部分清理': 2, '失败': 1})
        self.assertEqual(summary.savings_bytes, 984)
        self.assertEqual(summary.counted_files, 3)
        self.assertEqual(summary.partial_savings_bytes, -40)
        self.assertEqual(summary.partial_counted_files, 1)
        self.assertEqual(summary.unmeasured_files, 1)
        self.assertEqual(summarize([rows[3]]).savings_bytes, -40)

    def test_presentation_keeps_exact_bytes_negative_differences_and_unknown_values(self):
        from prototype.results import describe_result, describe_summary, summarize
        rows = result_scenarios()
        success = describe_result(rows[0])
        self.assertIn('2048 字节（2.00 KiB）', success)
        self.assertIn('1024 字节（1.00 KiB）', success)
        self.assertIn('清理文档数量：3', success)
        self.assertIn('跳过外链数量：2', success)
        partial = describe_result(rows[3])
        self.assertIn('不等于完整清理成功', partial)
        self.assertIn('-40 字节', partial)
        self.assertIn('1. 图层 A：PDF 原样保留', partial)
        self.assertIn('2. 图层 B：嵌入格式未知', partial)
        self.assertIn(rows[4]['error'], describe_result(rows[4]))
        self.assertIn('不计入本轮收益', describe_result(rows[4]))
        self.assertIn('未发布（无可用输出）', describe_result(rows[5]))
        unknown = describe_result(rows[6])
        self.assertIn('原始大小：未知', unknown)
        self.assertIn('实际差异（前 - 后）：未知', unknown)
        self.assertIn('清理文档数量：未知', unknown)
        self.assertIn('跳过外链数量：未知', unknown)
        summary = describe_summary(summarize(rows))
        for text in ('成功 2', '无需清理 1', '未变化 1', '部分清理 2', '失败 1', '984 字节', '-40 字节',
                     '大小未知 1', '历史复用、失败、未发布', '负数表示体积增加'):
            self.assertIn(text, summary)

    def test_invalid_or_missing_sizes_and_legacy_unproven_publications_never_inflate_savings(self):
        from prototype.results import summarize
        valid = result_scenarios()[0]
        for before, after in ((None, 0), (10, None), (-1, 0), (True, 0), ('2048', 0)):
            with self.subTest(before=before, after=after):
                summary = summarize([{**valid, 'before': before, 'after': after}])
                self.assertEqual(summary.savings_bytes, 0)
                self.assertEqual(summary.counted_files, 0)
                self.assertEqual(summary.unmeasured_files, 1)
        legacy = valid.copy()
        del legacy['published']
        self.assertEqual(summarize([legacy]).counted_files, 0)


class ResultExportTests(unittest.TestCase):
    def test_failed_export_removes_only_its_new_file_and_can_retry(self):
        from prototype.results import export_report
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / '结果.json'
            with patch('os.fsync', side_effect=OSError(errno.ENOSPC, '导出磁盘已满')):
                with self.assertRaisesRegex(OSError, '导出磁盘已满'):
                    export_report(destination, result_scenarios(), task={'state': 'stopped'})
            self.assertFalse(destination.exists())
            export_report(destination, result_scenarios(), task={'state': 'stopped'})
            self.assertEqual(json.loads(destination.read_text(encoding='utf-8'))['task']['state'], 'stopped')
            invalid = Path(temporary) / '不能序列化.json'
            with self.assertRaises(TypeError):
                export_report(invalid, result_scenarios(), task={'bad': object()})
            self.assertFalse(invalid.exists())

    def test_export_preserves_chinese_raw_rows_shared_totals_and_refuses_overwrite(self):
        from prototype.results import export_report
        rows = result_scenarios()
        task = {'state': 'finished', 'completed': 7, 'total': 7,
                'source_report': '本轮/report.json', 'message': ''}
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / '中文 结果.json'
            export_report(destination, rows, task=task)
            text = destination.read_text(encoding='utf-8')
            exported = json.loads(text)
            self.assertEqual(exported['results'], rows)
            self.assertEqual(exported['task'], task)
            self.assertEqual(exported['summary']['savings_bytes'], 984)
            self.assertEqual(exported['summary']['partial_savings_bytes'], -40)
            self.assertEqual(exported['summary']['unmeasured_files'], 1)
            self.assertIn('部分清理不等于完整成功', exported['benefit_policy'])
            self.assertIn('=中文 输入/缩小.psd', text)
            before = destination.read_bytes()
            with self.assertRaisesRegex(FileExistsError, '拒绝覆盖'):
                export_report(destination, [], task={'state': 'error'})
            self.assertEqual(destination.read_bytes(), before)


class BatchResultTests(unittest.TestCase):
    def test_published_but_failed_record_keeps_actual_output_and_is_excluded_from_savings(self):
        from prototype.results import summarize
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / 'input', base / 'output'
            inputs.mkdir()
            (inputs / 'a.psd').write_bytes(tiny())
            replace = os.replace
            events: list[BatchEvent] = []

            def cache_unavailable(source, destination):
                if Path(destination).name == '.cleaner-cache.json':
                    raise OSError(errno.ENOSPC, '缓存写入失败')
                return replace(source, destination)

            with patch('os.replace', side_effect=cache_unavailable):
                with self.assertRaisesRegex(RuntimeError, '增量记录写入失败'):
                    run(inputs, output, on_event=events.append, emit=lambda _: None)
            file_event = next(event for event in events if event.kind == 'file')
            assert file_event.row is not None and file_event.report is not None
            row = file_event.row
            self.assertEqual(row['status'], '失败')
            self.assertIs(row['published'], True)
            self.assertEqual(row['after'], Path(row['output']).stat().st_size)
            self.assertEqual(json.loads(file_event.report.read_text(encoding='utf-8')), [row])
            self.assertEqual(summarize([row]).counted_files, 0)
            self.assertEqual(summarize([row]).savings_bytes, 0)

    def test_records_distinguish_current_publication_history_and_known_failure_sizes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs, output = base / '输入', base / '输出'
            inputs.mkdir()
            originals = {'a.psd': tiny(), 'b.psb': tiny(2, xmp=None),
                         'c.psd': tiny(children=[embedded(b'%PDF opaque')]), 'd.psd': b'broken'}
            for name, content in originals.items():
                (inputs / name).write_bytes(content)
            first, report = run(inputs, output, emit=lambda _: None)
            self.assertEqual([row['status'] for row in first], ['成功', '无需清理', '部分清理', '失败'])
            self.assertEqual([row['published'] for row in first], [True, True, True, False])
            self.assertEqual([row['before'] for row in first], [len(content) for content in originals.values()])
            for row in first[:3]:
                self.assertEqual(row['after'], Path(row['output']).stat().st_size)
            self.assertIsNone(first[3]['after'])
            self.assertIsNone(first[3]['output'])
            self.assertTrue(first[2]['issues'])
            self.assertEqual(json.loads(report.read_text(encoding='utf-8')), first)
            second, _ = run(inputs, output, emit=lambda _: None)
            self.assertEqual([row['published'] for row in second], [False, False, True, False])
            for index in (0, 1):
                self.assertEqual(second[index]['status'], '未变化')
                self.assertEqual(second[index]['output'], first[index]['output'])
                self.assertEqual((second[index]['before'], second[index]['after']),
                                 (first[index]['before'], first[index]['after']))
            for name, content in originals.items():
                self.assertEqual((inputs / name).read_bytes(), content)


if __name__ == '__main__':
    unittest.main()
