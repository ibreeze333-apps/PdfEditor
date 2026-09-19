# tests/test_errlog.py — 삼킨 예외 기록기
"""errlog 자체가 터지면 앱이 죽는다. 여기가 제일 방어적이어야 한다."""
from __future__ import annotations
import logging

import pytest

from utils import errlog


@pytest.fixture(autouse=True)
def clean_counts():
    errlog._counts.clear()
    yield
    errlog._counts.clear()


def test_records_site_and_count():
    """자리마다 횟수를 센다."""
    for _ in range(3):
        try:
            raise ValueError('테스트')
        except ValueError:
            errlog.swallowed()
    counts = errlog.counts()
    assert len(counts) == 1
    (where, n), = counts.items()
    assert n == 3
    assert 'test_errlog.py' in where
    assert 'test_records_site_and_count' in where


def test_first_occurrence_logs_traceback(caplog):
    """첫 1회만 트레이스백까지 남기고, 그 뒤엔 조용해야 한다.

    (안 그러면 페인트·휠 이벤트 안의 것들 때문에 로그가 수백 MB가 된다)
    """
    with caplog.at_level(logging.INFO, logger='pdf_editor.swallowed'):
        for _ in range(5):
            try:
                raise RuntimeError('boom')
            except RuntimeError:
                errlog.swallowed()
    assert len(caplog.records) == 1, f'5번 삼켰는데 로그가 {len(caplog.records)}줄'
    rec = caplog.records[0]
    assert rec.exc_info is not None, '첫 회에는 트레이스백이 있어야 한다'
    assert 'RuntimeError' in rec.getMessage()


def test_milestone_logs_again(caplog):
    """10회째에는 한 번 더 알린다 — 폭주하는 자리를 놓치지 않게."""
    with caplog.at_level(logging.INFO, logger='pdf_editor.swallowed'):
        for _ in range(10):
            try:
                raise KeyError('k')
            except KeyError:
                errlog.swallowed()
    assert len(caplog.records) == 2   # 1회째 + 10회째


def test_different_sites_are_separate():
    """자리가 다르면 따로 센다."""
    def a():
        try:
            raise ValueError()
        except ValueError:
            errlog.swallowed()

    def b():
        try:
            raise ValueError()
        except ValueError:
            errlog.swallowed()

    a(); a(); b()
    counts = errlog.counts()
    assert len(counts) == 2
    assert sorted(counts.values()) == [1, 2]


def test_never_raises_outside_except_block():
    """예외가 없는 상태에서 불러도 죽으면 안 된다."""
    errlog.swallowed()          # 예외 없이 그냥 호출
    errlog.swallowed('메모만')
    assert len(errlog.counts()) >= 1


def test_never_raises_even_if_logging_breaks(monkeypatch):
    """로깅이 터져도 swallowed() 는 조용히 넘어가야 한다.

    로그를 남기려다 앱을 죽이면 본말전도다.
    """
    def broken(*a, **k):
        raise OSError('로그 파일 잠김')

    monkeypatch.setattr(errlog.logger, 'info', broken)
    try:
        raise ValueError()
    except ValueError:
        errlog.swallowed()      # 여기서 예외가 새어 나오면 실패


def test_summary_is_readable():
    """요약은 사람이 읽을 수 있어야 한다."""
    assert errlog.summary() == '삼킨 예외 없음'
    for _ in range(2):
        try:
            raise ValueError()
        except ValueError:
            errlog.swallowed()
    text = errlog.summary()
    assert '총 2회' in text
    assert 'test_errlog.py' in text
