# utils/freeze_watchdog.py — GUI 멈춤(행) 감지 워치독
"""GUI 스레드가 일정 시간 이상 응답하지 않으면 전체 스레드의 파이썬 스택을
logs/freeze_*.log 로 덤프한다.

앱이 '모래시계 상태로 멈추는' 문제는 예외가 아니라서 excepthook/crash 로그에
아무것도 남지 않는다 — 이 워치독이 멈춘 순간 GUI 스레드가 정확히 어느
함수에서 블로킹돼 있는지를 기록해 원인 추적을 가능하게 한다.

동작:
  - GUI 스레드의 QTimer 가 0.5초마다 하트비트 갱신
  - 데몬 스레드가 1초마다 검사, threshold(기본 5초) 초과 시 스택 덤프 1회
  - 회복되면 멈춤 지속 시간을 로그에 남기고 재무장
"""
from __future__ import annotations

import faulthandler
import logging
import os
import threading
import time
from utils.errlog import swallowed

logger = logging.getLogger('pdf_editor')

_started = False
_keepalive = []   # QTimer GC 방지


def start_watchdog(log_dir: str, threshold: float = 5.0):
    """GUI 스레드에서 호출 (QApplication 생성 후)."""
    global _started
    if _started:
        return
    _started = True

    from PySide6.QtCore import QTimer

    state = {'beat': time.monotonic(), 'dumped': False, 'freeze_start': 0.0}

    timer = QTimer()
    timer.setInterval(500)
    timer.timeout.connect(lambda: state.__setitem__('beat', time.monotonic()))
    timer.start()
    _keepalive.append(timer)

    def _watch():
        while True:
            time.sleep(1.0)
            gap = time.monotonic() - state['beat']
            if gap > threshold and not state['dumped']:
                state['dumped'] = True
                state['freeze_start'] = state['beat']
                try:
                    os.makedirs(log_dir, exist_ok=True)
                    path = os.path.join(
                        log_dir, time.strftime('freeze_%Y%m%d_%H%M%S.log'))
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(f'GUI 스레드 {gap:.1f}초 이상 무응답 — '
                                f'전체 스레드 스택 덤프\n'
                                f'(MainThread 스택의 마지막 줄이 멈춘 지점)\n\n')
                        faulthandler.dump_traceback(file=f, all_threads=True)
                    logger.warning(
                        '[Watchdog] GUI %.1f초 멈춤 감지 — 스택 덤프: %s',
                        gap, path)
                except Exception:
                    swallowed()
            elif gap < 1.5 and state['dumped']:
                frozen_for = time.monotonic() - state['freeze_start']
                logger.warning('[Watchdog] GUI 응답 회복 — 총 %.1f초 멈춤',
                               frozen_for)
                state['dumped'] = False

    threading.Thread(target=_watch, name='freeze-watchdog',
                     daemon=True).start()
