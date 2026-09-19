# utils/online_dict.py — 네이버사전 간이 뜻 조회 (온라인 롤오버 사전용)
"""네이버 영한사전 자동완성 API로 단어의 간단한 뜻을 가져온다.

- 엔드포인트: https://ac-dict.naver.com/enko/ac (웹 사전이 쓰는 공개 자동완성)
- 영→한, 한→영 양방향으로 짧은 뜻을 반환하므로 롤오버 팝업에 적합
- 메모리 캐시로 같은 단어 재조회 방지, 실패해도 예외를 던지지 않음
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QRunnable, Signal
from utils.errlog import swallowed

logger = logging.getLogger('pdf_editor')

_AC_URL = 'https://ac-dict.naver.com/enko/ac'
_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

_CACHE_MAX = 300
_cache: dict[str, str] = {}          # word(lower) -> 표시 텍스트 ('' = 결과 없음)
_cache_lock = threading.Lock()
_inflight: set[str] = set()          # 중복 요청 방지
_inflight_lock = threading.Lock()


def get_cached(word: str) -> str | None:
    """캐시된 결과. 없으면 None ('' 은 '결과 없음'이 캐시된 것)."""
    with _cache_lock:
        return _cache.get(word.strip().lower())


def _store(word: str, text: str):
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            # 간단한 용량 제한 — 오래된 것부터 절반 제거
            for k in list(_cache.keys())[:_CACHE_MAX // 2]:
                del _cache[k]
        _cache[word.strip().lower()] = text


def naver_brief(word: str, timeout: float = 4.0) -> str:
    """네이버사전에서 간단한 뜻을 가져온다. 결과 없음/실패 시 ''.

    반환 형식:
        뜻1, 뜻2, 뜻3
        • 관련 구문 — 뜻
        • 관련 구문 — 뜻
    """
    word = (word or '').strip()
    if not word:
        return ''
    cached = get_cached(word)
    if cached is not None:
        return cached

    try:
        import requests
        r = requests.get(
            _AC_URL,
            params={'q': word, 'st': '11001', 'r_lt': '11001'},
            headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        items = r.json().get('items') or []
        entries = items[0] if items else []
    except Exception as e:
        logger.debug('[online_dict] 네이버 조회 실패 (%s): %s', word, e)
        return ''   # 실패는 캐시하지 않음 — 다음 hover 때 재시도

    main = ''
    related: list[str] = []
    wl = word.lower()
    for entry in entries:
        try:
            w = (entry[0][0] or '').strip()
            meaning = (entry[2][0] or '').strip()
        except (IndexError, TypeError):
            continue
        if not w or not meaning:
            continue
        if not main and w.lower() == wl:
            main = meaning
        elif len(related) < 2 and w.lower() != wl:
            related.append(f'• {w} — {meaning}')

    # 정확히 일치하는 표제어가 없으면 첫 항목을 본문으로
    if not main and entries:
        try:
            w = (entries[0][0][0] or '').strip()
            meaning = (entries[0][2][0] or '').strip()
            if meaning:
                main = f'{w}: {meaning}' if w.lower() != wl else meaning
                related = [rel for rel in related if not rel.startswith(f'• {w} ')]
        except (IndexError, TypeError):
            swallowed()

    text = '\n'.join([p for p in ([main] + related) if p])
    _store(word, text)
    return text


# ── 백그라운드 워커 (hover 시 GUI 블로킹 방지) ─────────────────────────

class NaverBriefSignals(QObject):
    finished = Signal(str, str)   # (word, text — '' 이면 결과 없음/실패)


class NaverBriefWorker(QRunnable):
    def __init__(self, word: str):
        super().__init__()
        self.signals = NaverBriefSignals()
        self._word = word
        self.setAutoDelete(True)

    def run(self):
        word = self._word
        with _inflight_lock:
            if word.lower() in _inflight:
                return          # 같은 단어 요청이 이미 진행 중
            _inflight.add(word.lower())
        try:
            text = naver_brief(word)
        finally:
            with _inflight_lock:
                _inflight.discard(word.lower())
        self.signals.finished.emit(word, text)
