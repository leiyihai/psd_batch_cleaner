"""Filesystem-boundary fault injection shared by batch and real GUI acceptance."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
from typing import Iterator
from unittest.mock import patch


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
