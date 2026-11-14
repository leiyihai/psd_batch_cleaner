"""Stable recorded-result scenarios; not claims of real PSD compatibility."""
from typing import Any


def result_scenarios() -> list[dict[str, Any]]:
    return [
        {'source': '=中文 输入/缩小.psd', 'output': '本轮/缩小.psd', 'status': '成功',
         'published': True, 'before': 2048, 'after': 1024, 'documents': 3,
         'skipped_links': 2, 'removed': 5, 'issues': []},
        {'source': '原样.psb', 'output': '本轮/原样.psb', 'status': '无需清理',
         'published': True, 'before': 512, 'after': 512, 'documents': 1,
         'skipped_links': 0, 'removed': 0, 'issues': []},
        {'source': '历史.psd', 'output': '历史/历史.psd', 'status': '未变化',
         'published': False, 'before': 4096, 'after': 2048},
        {'source': '部分.psd', 'output': '本轮/部分.psd', 'status': '部分清理',
         'published': True, 'before': 100, 'after': 140, 'documents': 2,
         'skipped_links': 1, 'removed': 2,
         'issues': ['图层 A：PDF 原样保留', '图层 B：嵌入格式未知']},
        {'source': '失败.psd', 'output': '本轮/已发布但后续失败.psd', 'status': '失败',
         'published': True, 'before': 8192, 'after': 1,
         'error': '完整错误：缓存写入失败\n请保留已发布副本'},
        {'source': '未发布.psd', 'output': None, 'status': '成功',
         'published': False, 'before': 9000, 'after': 0},
        {'source': '大小未知.psd', 'output': '本轮/大小未知.psd', 'status': '部分清理',
         'published': True, 'before': None, 'after': 10, 'issues': ['旧记录缺少大小']},
    ]
