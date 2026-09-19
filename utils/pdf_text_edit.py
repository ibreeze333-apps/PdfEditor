# utils/pdf_text_edit.py — PDF 콘텐츠 스트림에서 텍스트를 정밀하게 제거
"""지정한 영역에 그려지는 '글자 그리기 명령'만 콘텐츠 스트림에서 골라 지운다.

왜 필요한가
-----------
본문 글자를 고치려면 옛 글자를 없애야 하는데, 두 가지 흔한 방법에 각각 문제가
있다.

* 흰 사각형으로 덮기 — 화면에서만 가려질 뿐 텍스트는 그대로 남는다. 같은 자리를
  다시 편집하면 옛 글자와 새 글자가 겹쳐 읽혀 뒤죽박죽이 된다.
* redaction(apply_redactions) — 페이지 콘텐츠를 통째로 다시 쓰기 때문에, 한글
  조판 PDF에서 멀리 떨어진 볼드 제목(ToUnicode 가 깨진 서브셋 글꼴)까지 함께
  사라지는 부작용이 있다.

여기서는 스트림을 바이트 단위로 훑으며 대상 영역의 Tj/TJ 만 빼고 나머지는 원래
바이트 그대로 남긴다. 손대지 않은 글자는 어떤 영향도 받지 않는다.

한계
----
Tm/Td/TD/T* 로 지정되는 텍스트 위치만 추적한다(일반적인 조판 PDF의 형태).
cm(좌표 변환) 안에서 그려지는 텍스트는 위치 계산이 어긋날 수 있으므로, 호출부는
반환값과 실제 결과를 확인하고 필요하면 다른 방법으로 넘어가야 한다.
"""
from __future__ import annotations

import re
from utils.errlog import swallowed

_NUM = r'[-+]?[0-9]*\.?[0-9]+'
_RE_TM = re.compile(rf'({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})\s+Tm')
_RE_TD = re.compile(rf'({_NUM})\s+({_NUM})\s+(TD|Td)\b')
_RE_TSTAR = re.compile(r'\bT\*')
_RE_TL = re.compile(rf'({_NUM})\s+TL\b')
# 글자를 실제로 찍는 연산자: [..]TJ, (..)Tj, <..>Tj, (..)', (..)"
_RE_SHOW = re.compile(
    rb'(\[[^\]]*\]\s*TJ|\([^)\\]*(?:\\.[^)\\]*)*\)\s*(?:Tj|\'|")|<[0-9A-Fa-f\s]*>\s*Tj)')


def remove_text_in_rect(page, rect, pad: float = 2.0) -> int:
    """rect(fitz 좌표계) 안에 그려지는 텍스트 명령을 지우고 지운 개수를 반환.

    위치 지정 연산자(Tm/Td)는 그대로 두고 글자 표시 연산자만 제거하므로, 뒤따르는
    다른 텍스트의 위치는 흐트러지지 않는다.
    """
    doc = page.parent
    if doc is None:
        return 0
    page_h = page.rect.height
    # PDF 는 좌하단 원점 — fitz(좌상단) 사각형을 뒤집어 맞춘다.
    y_lo = page_h - rect.y1 - pad
    y_hi = page_h - rect.y0 + pad
    x_lo = rect.x0 - pad
    x_hi = rect.x1 + pad

    total = 0
    for xref in page.get_contents():
        try:
            data = doc.xref_stream(xref)
        except Exception:
            continue
        if not data:
            continue
        out = bytearray()
        pos = 0
        cur_x = cur_y = None
        leading = 0.0
        removed_here = 0
        while pos < len(data):
            m = _RE_SHOW.search(data, pos)
            if m is None:
                out += data[pos:]
                break
            seg = data[pos:m.start()]
            out += seg
            # 이 구간의 위치 지정 연산자를 순서대로 반영
            s = seg.decode('latin-1', 'replace')
            for mm in _RE_TL.finditer(s):
                leading = float(mm.group(1))
            for mm in _RE_TM.finditer(s):
                cur_x, cur_y = float(mm.group(5)), float(mm.group(6))
            for mm in _RE_TD.finditer(s):
                if cur_x is None:
                    cur_x = cur_y = 0.0
                cur_x += float(mm.group(1))
                cur_y += float(mm.group(2))
            for _ in _RE_TSTAR.finditer(s):
                if cur_y is not None:
                    cur_y -= leading
            inside = (cur_x is not None and cur_y is not None
                      and x_lo <= cur_x <= x_hi and y_lo <= cur_y <= y_hi)
            if inside:
                removed_here += 1          # 글자 표시 명령을 버린다
            else:
                out += m.group(0)
            pos = m.end()
        if removed_here:
            try:
                doc.update_stream(xref, bytes(out))
                total += removed_here
            except Exception:
                swallowed()
    return total


def _squash(s: str) -> str:
    return re.sub(r'\s+', '', s or '')


def erase_text_area(page, rect, pad: float = 0.5) -> bool:
    """rect 안의 글자를 실제로 지운다. 성공하면 True.

    지운 뒤 (1) 대상 영역이 실제로 비었는지 (2) 영역 밖 글자가 휩쓸려 사라지지
    않았는지 검사한다. 어느 하나라도 어긋나면 원래 스트림으로 되돌리고 False 를
    돌려주어, 호출부가 기존 방식(흰 덮개)으로 안전하게 넘어갈 수 있게 한다.
    """
    doc = page.parent
    if doc is None:
        return False
    try:
        before_tgt = _squash(page.get_textbox(rect))
        before_all = _squash(page.get_text('text'))
    except Exception:
        return False
    if not before_tgt:
        return True                     # 지울 글자가 없음

    # 되돌릴 수 있도록 원본 스트림을 보관
    backup = []
    try:
        for xref in page.get_contents():
            backup.append((xref, doc.xref_stream(xref)))
    except Exception:
        return False

    def _restore():
        for xref, data in backup:
            try:
                doc.update_stream(xref, data)
            except Exception:
                swallowed()

    try:
        n = remove_text_in_rect(page, rect, pad=pad)
    except Exception:
        _restore()
        return False
    if n <= 0:
        return False

    try:
        after_tgt = _squash(page.get_textbox(rect))
        after_all = _squash(page.get_text('text'))
    except Exception:
        _restore()
        return False

    # ① 대상이 거의 다 지워졌는가
    if len(after_tgt) > max(1, len(before_tgt) * 0.2):
        _restore()
        return False
    # ② 영역 밖 글자가 휩쓸리지 않았는가(대상보다 2자 넘게 더 지워지면 위험)
    removed_all = len(before_all) - len(after_all)
    if removed_all - len(before_tgt) > 2:
        _restore()
        return False
    return True


# ── 줄바꿈(워드랩) ────────────────────────────────────────────────────
# PyMuPDF 의 insert_textbox 는 상자 하나에 균일한 폭으로만 글을 흘린다. 각주처럼
# '첫 줄은 왼쪽, 이어지는 줄은 들여쓰기'(내어쓰기)인 구조는 줄마다 쓸 수 있는
# 폭이 달라서 직접 줄을 나눠야 한다.

def _token_split(text: str):
    """공백을 유지한 채 토큰으로 나눈다(공백은 앞 토큰에 붙인다)."""
    out, cur = [], ''
    for ch in text:
        if ch == ' ':
            cur += ch
            out.append(cur)
            cur = ''
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def wrap_text(text: str, font, fontsize: float, widths) -> list[str]:
    """text 를 줄 폭에 맞춰 나눈다.

    widths: 줄 번호(0부터)를 받아 그 줄에 쓸 수 있는 폭을 돌려주는 콜백,
            또는 [첫줄폭, 이후줄폭] 형태의 리스트.
    한국어는 어절(공백) 단위로 끊고, 한 토큰이 통째로 넘칠 때만 글자 단위로
    쪼갠다. 반환값의 각 줄은 앞뒤 공백이 정리된 상태.
    """
    if not text:
        return []
    if callable(widths):
        width_of = widths
    else:
        ws = list(widths) or [1e9]
        width_of = lambda i: ws[min(i, len(ws) - 1)]

    def _w(s: str) -> float:
        try:
            return font.text_length(s, fontsize=fontsize)
        except Exception:
            return len(s) * fontsize * 0.5

    lines: list[str] = []
    cur = ''
    limit = width_of(0)
    for tok in _token_split(text):
        cand = cur + tok
        if cur and _w(cand.rstrip()) > limit:
            lines.append(cur.rstrip())
            limit = width_of(len(lines))
            cur = tok
        else:
            cur = cand
        # 한 토큰이 한 줄보다 길면 글자 단위로 강제 분할
        while _w(cur.rstrip()) > limit and len(cur.strip()) > 1:
            cut = len(cur)
            while cut > 1 and _w(cur[:cut].rstrip()) > limit:
                cut -= 1
            if cut <= 1:
                break
            lines.append(cur[:cut].rstrip())
            limit = width_of(len(lines))
            cur = cur[cut:]
    if cur.strip():
        lines.append(cur.rstrip())
    return lines
