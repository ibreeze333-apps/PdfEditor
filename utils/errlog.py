# utils/errlog.py — 삼킨 예외 기록
"""`except ...: pass` 로 조용히 지나간 예외를 흔적으로 남긴다.

이 앱에서 가장 찾기 힘든 버그는 "눌렀는데 아무 일도 안 일어남" 이다.
예외를 잡아서 그냥 넘기면 사용자에게도 개발자에게도 아무 단서가 안 남는다.
그렇다고 전부 로그로 뱉으면 페인트·휠 이벤트 안에서 도는 것들 때문에
로그가 수백 MB가 된다.

그래서 **자리마다 첫 1회만 트레이스백을 남기고, 그 뒤엔 세기만** 한다.
종료할 때 summary() 로 어디서 몇 번 삼켰는지 한 번에 볼 수 있다.

동작은 바꾸지 않는다 — 예외는 그대로 삼켜지고 프로그램은 계속 간다.
이 함수는 어떤 경우에도 예외를 올리지 않는다(로깅하다 죽으면 본말전도).
"""
from __future__ import annotations
import logging
import os
import sys
import threading

logger = logging.getLogger('pdf_editor.swallowed')

_lock = threading.Lock()
_counts: dict[str, int] = {}
# 몇 번째마다 다시 알릴지 — 첫 회 이후엔 확 줄여서 로그가 안 넘치게.
_MILESTONES = (10, 100, 1000, 10000)


def _site(depth: int = 2) -> str:
    """호출한 자리를 '파일:줄 함수' 로."""
    try:
        f = sys._getframe(depth)
        return '%s:%d %s' % (os.path.basename(f.f_code.co_filename),
                             f.f_lineno, f.f_code.co_name)
    except Exception:
        return '?'


def swallowed(note: str = '') -> None:
    """except 블록 안에서 호출한다. 예외를 삼킨 사실만 남기고 그대로 진행."""
    try:
        where = _site()
        exc = sys.exc_info()[1]
        with _lock:
            n = _counts.get(where, 0) + 1
            _counts[where] = n
        if n == 1:
            # 첫 회만 트레이스백까지. INFO 라 로그 파일에는 남고 콘솔엔 안 뜬다.
            logger.info('[삼킴] %s%s — %s: %s', where,
                        (' (%s)' % note) if note else '',
                        type(exc).__name__ if exc else '?', exc,
                        exc_info=True)
        elif n in _MILESTONES:
            logger.info('[삼킴] %s — %d회째 (%s)', where, n,
                        type(exc).__name__ if exc else '?')
    except Exception:
        pass        # 여기서만은 진짜로 조용히 넘어간다


def counts() -> dict[str, int]:
    """{자리: 횟수} 사본."""
    with _lock:
        return dict(_counts)


def summary(top: int = 30) -> str:
    """어디서 몇 번 삼켰는지 요약 문자열."""
    items = sorted(counts().items(), key=lambda kv: -kv[1])
    if not items:
        return '삼킨 예외 없음'
    total = sum(n for _, n in items)
    lines = ['삼킨 예외 %d곳 / 총 %d회' % (len(items), total)]
    lines += ['  %6d  %s' % (n, where) for where, n in items[:top]]
    if len(items) > top:
        lines.append('  … 외 %d곳' % (len(items) - top))
    return '\n'.join(lines)


def log_summary() -> None:
    """종료 시 호출 — 요약을 로그에 남긴다."""
    try:
        if _counts:
            logger.info('%s', summary())
    except Exception:
        pass
