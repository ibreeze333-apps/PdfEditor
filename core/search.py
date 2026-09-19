# core/search.py — PDF 본문 검색 엔진 (Qt 없음, 단독 테스트 가능)
"""찾기 막대와 검색 결과 패널이 함께 쓰는 검색 로직.

위치 찾기는 MuPDF 의 page.search_for() 에 맡긴다. 공백·하이픈 정규화 같은
PDF 텍스트 특유의 까다로운 부분을 잘 처리하고 빠르기 때문이다.

다만 search_for 는 항상 대소문자를 무시하고 '단어 단위' 개념이 없다. 그런
옵션이 켜져 있으면 찾은 위치의 실제 글자를 문자 단위로 다시 읽어 걸러낸다.
그래서 옵션을 켠 결과는 언제나 옵션 없는 검색 결과의 부분집합이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import fitz

MODE_PHRASE = 'phrase'   # 정확한 문구
MODE_ALL = 'all'         # 모든 단어 포함 (페이지에 모든 단어가 있어야 함)
MODE_ANY = 'any'         # 하나라도 포함

_CONTEXT_CHARS = 28      # 결과 목록에 보여 줄 앞뒤 글자 수


@dataclass(frozen=True)
class SearchOptions:
    case_sensitive: bool = False
    whole_word: bool = False


@dataclass
class Hit:
    page: int
    rect: fitz.Rect | None   # None 이면 OCR 텍스트에서 찾은 것(화면 위치 없음)
    context: str = ''


def split_words(text: str) -> list[str]:
    return [w for w in re.split(r'\s+', (text or '').strip()) if w]


def page_has_text(page: fitz.Page) -> bool:
    """페이지에 검색할 수 있는 글자가 있는지 (없으면 이미지 스캔본)."""
    try:
        return bool(page.get_text('text').strip())
    except Exception:
        return False


def _is_word_char(ch: str) -> bool:
    # 한글 음절도 isalnum() 이 True — '제64조의2' 안의 '제64조'는 단어가 아니다
    return bool(ch) and (ch.isalnum() or ch == '_')


def _squash(s: str) -> str:
    return ''.join(s.split())


def _page_lines(page: fitz.Page) -> list:
    """페이지의 줄 목록 — [(줄 영역, [(글자, 글자 영역), ...]), ...]."""
    lines = []
    try:
        raw = page.get_text('rawdict')
    except Exception:
        return lines
    for block in raw.get('blocks', []):
        for line in block.get('lines', []):
            chars = []
            for span in line.get('spans', []):
                for ch in span.get('chars', []):
                    c = ch.get('c', '')
                    if c:
                        chars.append((c, fitz.Rect(ch['bbox'])))
            if chars:
                lines.append((fitz.Rect(line['bbox']), chars))
    return lines


def _locate(lines, rect: fitz.Rect):
    """검색 위치(rect)에 해당하는 줄과 글자 범위. 못 찾으면 None."""
    best, best_overlap = None, 0.0
    for lrect, chars in lines:
        overlap = min(lrect.y1, rect.y1) - max(lrect.y0, rect.y0)
        if overlap <= 0 or lrect.x1 < rect.x0 or lrect.x0 > rect.x1:
            continue
        if overlap > best_overlap:
            best, best_overlap = chars, overlap
    if best is None:
        return None
    idx = [i for i, (_, bb) in enumerate(best)
           if rect.x0 - 1.0 <= (bb.x0 + bb.x1) / 2.0 <= rect.x1 + 1.0]
    if not idx:
        return None
    return best, idx[0], idx[-1]


def _snippet(text: str, start: int, end: int) -> str:
    a = max(0, start - _CONTEXT_CHARS)
    b = min(len(text), end + _CONTEXT_CHARS)
    return ('…' if a > 0 else '') + text[a:b].strip() + ('…' if b < len(text) else '')


def _ocr_hits(page_index: int, query: str, opts: SearchOptions, ocr_text: str) -> list[Hit]:
    words = split_words(query)
    if not words:
        return []
    pat = r'\s+'.join(re.escape(w) for w in words)   # PDF 검색처럼 공백은 느슨하게
    if opts.whole_word:
        if _is_word_char(query[0]):
            pat = r'(?<!\w)' + pat
        if _is_word_char(query[-1]):
            pat = pat + r'(?!\w)'
    flags = 0 if opts.case_sensitive else re.IGNORECASE
    hits = []
    for line in ocr_text.splitlines():
        for m in re.finditer(pat, line, flags):
            hits.append(Hit(page_index, None, _snippet(line, m.start(), m.end())))
    return hits


def find_in_page(page: fitz.Page, page_index: int, query: str,
                 opts: SearchOptions | None = None, *,
                 want_context: bool = False, ocr_text: str = '',
                 _cache: dict | None = None) -> list[Hit]:
    """한 페이지에서 query 를 찾는다.

    ocr_text: 페이지에 글자가 전혀 없을 때(스캔본) 대신 뒤져 볼 OCR 결과.
              여기서 찾은 결과는 화면 위치가 없다(rect=None).
    """
    opts = opts or SearchOptions()
    query = (query or '').strip()
    if not query:
        return []
    try:
        quads = page.search_for(query, quads=True)
    except Exception:
        quads = []
    if not quads:
        if ocr_text and not page_has_text(page):
            return _ocr_hits(page_index, query, opts, ocr_text)
        return []

    check = opts.case_sensitive or opts.whole_word
    lines = None
    if check or want_context:
        cache = _cache if _cache is not None else {}
        lines = cache.get('lines')
        if lines is None:
            lines = cache['lines'] = _page_lines(page)

    sq_query = _squash(query)
    hits = []
    for quad in quads:
        rect = quad.rect
        loc = _locate(lines, rect) if lines is not None else None
        if loc is None:
            # 글자 단위로 확인할 수 없는 위치(회전된 글자 등)는 놓치지 않게 남긴다
            hits.append(Hit(page_index, rect, ''))
            continue
        chars, i0, i1 = loc
        if opts.case_sensitive:
            matched = ''.join(c for c, _ in chars[i0:i1 + 1])
            # 한 결과가 줄바꿈으로 나뉘면 이 줄에는 일부만 있으므로 '포함'으로 본다
            if _squash(matched) not in sq_query:
                continue
        if opts.whole_word:
            before = chars[i0 - 1][0] if i0 > 0 else ''
            after = chars[i1 + 1][0] if i1 + 1 < len(chars) else ''
            if _is_word_char(query[0]) and _is_word_char(before):
                continue
            if _is_word_char(query[-1]) and _is_word_char(after):
                continue
        context = ''
        if want_context:
            context = _snippet(''.join(c for c, _ in chars), i0, i1 + 1)
        hits.append(Hit(page_index, rect, context))
    return hits


def search_page_advanced(page: fitz.Page, page_index: int, query: str,
                         mode: str = MODE_PHRASE, exclude: str = '',
                         opts: SearchOptions | None = None, *,
                         ocr_text: str = '') -> list[Hit]:
    """결과 목록 패널용 검색 — 검색 방식과 제외 단어를 지원한다.

    MODE_PHRASE: query 전체를 한 문구로 찾는다.
    MODE_ALL:    공백으로 나눈 모든 단어가 이 페이지에 있을 때만 결과로 친다.
    MODE_ANY:    단어 중 하나라도 있으면 결과로 친다.
    exclude:     이 단어 중 하나라도 있는 페이지는 결과에서 뺀다.
    """
    opts = opts or SearchOptions()
    cache: dict = {}    # 한 페이지를 여러 단어로 찾을 때 글자 정보를 한 번만 읽는다
    for word in split_words(exclude):
        if find_in_page(page, page_index, word, opts, ocr_text=ocr_text, _cache=cache):
            return []
    if mode == MODE_PHRASE:
        return find_in_page(page, page_index, query, opts, want_context=True,
                            ocr_text=ocr_text, _cache=cache)
    words = split_words(query)
    if not words:
        return []
    per_word = [find_in_page(page, page_index, w, opts, want_context=True,
                             ocr_text=ocr_text, _cache=cache) for w in words]
    if mode == MODE_ALL and not all(per_word):
        return []
    hits = [h for group in per_word for h in group]
    hits.sort(key=lambda h: (h.rect.y0, h.rect.x0) if h.rect is not None else (-1.0, -1.0))
    return hits
