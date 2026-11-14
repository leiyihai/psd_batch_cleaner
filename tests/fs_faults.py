"""Filesystem-boundary fault injection shared by batch and real GUI acceptance."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
from typing import Iterator
from unittest.mock import patch


@contextmanager
def forbid_file_access(forbidden: Path) -> Iterator[None]:
    """Fail before a batch or GUI job can open a forbidden history file."""
    target = forbidden.resolve()
    path_open = Path.open

    def guarded_open(path, mode='r', *args, **kwargs):
        if path.resolve() == target:
            raise AssertionError(f'禁止读取输出范围外的历史副本：{path}')
        return path_open(path, mode, *args, **kwargs)

    with patch('pathlib.Path.open', new=guarded_open):
        yield


@contextmanager
def fail_report_update_at(file_count: int) -> Iterator[None]:
    replace = os.replace

    def unavailable(source, destination):
        if Path(destination).name == 'report.json':
            rows = json.loads(Path(source).read_text(encoding='utf-8'))
            if len(rows) == file_count:
                raise PermissionError('报告目录不可写')
        return replace(source, destination)

    with patch('os.replace', side_effect=unavailable):
        yield
