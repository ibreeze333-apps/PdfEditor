# ui/canvas_view.py — PdfCanvasView: 메인 PDF 렌더링 뷰
from __future__ import annotations
import fitz
import threading
import logging
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer, QPoint, QRect, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QThread, QCoreApplication
from PySide6.QtGui import (QWheelEvent, QMouseEvent, QKeyEvent,
                            QTransform, QPixmap, QColor, QPainter, QLinearGradient, QBrush, QPen, QImage, QPolygonF, QPainterPath)
from PySide6.QtWidgets import (QGraphicsView, QGraphicsPixmapItem,
                                QGraphicsDropShadowEffect, QToolTip,
                                QLineEdit, QPlainTextEdit, QWidget, QHBoxLayout,
                                QLabel, QComboBox, QGraphicsRectItem,
                                QGraphicsOpacityEffect, QGraphicsPolygonItem, QGraphicsLineItem,
                                QGraphicsPathItem, QToolButton)
from ui.canvas_scene import PdfCanvasScene
from tools.base_tool import BaseTool
from tools.select_tool import SelectTool
from utils.pending_layer import PendingLayer, PendingAnnotation
from utils.fitz_qt_bridge import render_page
from utils.errlog import swallowed


_retired_scroll_workers = set()


def _wait_for_retired_scroll_workers():
    # Native page rendering cannot be forcefully interrupted. Never terminate it.
    for worker in tuple(_retired_scroll_workers):
        worker.wait()


def _retire_scroll_worker(worker):
    """Keep a slow worker alive after its canvas/tab is closed."""
    worker.setParent(None)
    _retired_scroll_workers.add(worker)
    worker.finished.connect(lambda: _retired_scroll_workers.discard(worker))
    worker.finished.connect(worker.deleteLater)
    if worker.isFinished():
        _retired_scroll_workers.discard(worker)
        worker.deleteLater()
    app = QCoreApplication.instance()
    if app is not None and not getattr(app, '_scroll_cleanup_installed', False):
        app.aboutToQuit.connect(_wait_for_retired_scroll_workers)
        app._scroll_cleanup_installed = True


# ─────────────────────────────────────────────────────────────────
# 인라인 텍스트 에디터 위젯 (뷰포트 위에 떠 있음)
# ─────────────────────────────────────────────────────────────────
# 한글/CJK 포함 여부 판단
def _has_cjk(text: str) -> bool:
    for c in text:
        cp = ord(c)
        if (0xAC00 <= cp <= 0xD7A3 or   # 한글 음절
                0x1100 <= cp <= 0x11FF or  # 한글 자모
                0x3000 <= cp <= 0x9FFF or  # CJK
                0xF900 <= cp <= 0xFAFF):
            return True
    return False


# 텍스트가 "깨진 문자"처럼 보이는지 휴리스틱으로 판단
def _looks_garbled(text: str) -> bool:
    if not text:
        return False
    bad = sum(1 for c in text
              if c in '\ufffd\x00' or
              (ord(c) < 0x20 and c not in '\t\n') or
              0xE000 <= ord(c) <= 0xF8FF)   # PUA(사용자영역)
    return (bad / len(text)) > 0.2



def _tokenize_lookup_word(text: str) -> list[str]:
    tokens: list[str] = []
    current = ''
    mode = ''
    for ch in text:
        if ch.isspace():
            if current:
                tokens.append(current)
                current = ''
                mode = ''
            continue
        code = ord(ch)
        is_hangul = 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF
        is_alpha = ch.isalpha() or ch.isdigit() or ch in ("'", '-', '_')
        if is_hangul:
            ch_mode = 'hangul'
        elif is_alpha:
            ch_mode = 'latin'
        else:
            ch_mode = 'other'
        if ch_mode == 'other':
            if current:
                tokens.append(current)
                current = ''
                mode = ''
            continue
        if mode and ch_mode != mode:
            tokens.append(current)
            current = ch
        else:
            current += ch
        mode = ch_mode
    if current:
        tokens.append(current)
    return tokens


def _best_lookup_word(text: str) -> str:
    tokens = _tokenize_lookup_word(text.strip())
    if not tokens:
        return ''
    tokens.sort(key=lambda t: (-len(t), t))
    return tokens[0]


def _best_lookup_word_at(text: str, fitz_x: float, x0: float, x1: float) -> str:
    stripped = text.strip()
    if not stripped:
        return ''
    tokens = _tokenize_lookup_word(stripped)
    if len(tokens) > 1:
        rel = 0.5 if x1 <= x0 else max(0.0, min(1.0, (fitz_x - x0) / max(1e-6, x1 - x0)))
        char_pos = min(len(stripped) - 1, max(0, int(rel * len(stripped))))
        acc = 0
        for token in tokens:
            start = acc
            end = acc + len(token)
            if start <= char_pos < end:
                return token
            acc = end
        return tokens[0]
    if len(stripped) <= 10:
        return stripped
    rel = 0.5 if x1 <= x0 else max(0.0, min(1.0, (fitz_x - x0) / max(1e-6, x1 - x0)))
    char_pos = min(len(stripped) - 1, max(0, int(rel * len(stripped))))
    left = max(0, char_pos - 3)
    right = min(len(stripped), char_pos + 4)
    chunk = stripped[left:right].strip(".,!?;:\"'()[]{}")
    return chunk or stripped

def _normalize_lookup_word(word: str) -> str:
    word = (word or '').strip(".,!?;:\"'()[]{}")
    if len(word) < 2:
        return word
    if not all(('가' <= ch <= '힣') for ch in word):
        return word

    suffixes = (
        '으로는', '으로도', '으로만', '으로서', '으로써',
        '에게서', '한테서',
        '에서는', '에서만', '에서도',
        '한테는', '한테도',
        '에게는', '에게도',
        '까지는', '까지도', '부터는', '부터도',
        '이라도', '라도',
        '으로', '에서', '에게', '한테',
        '까지', '부터',
        '처럼', '보다', '마저', '조차',
        '이며', '이고', '이나', '나',
        '은', '는', '이', '가', '을', '를',
        '와', '과', '도', '만', '의', '에',
    )
    for suffix in suffixes:
        if len(word) > len(suffix) and word.endswith(suffix):
            return word[:-len(suffix)]
    return word


def _join_word_tokens(tokens: list[str]) -> str:
    text = ''
    no_space_before = {',', '.', '!', '?', ';', ':', '%', ')', ']', '}', '"', "'"}
    no_space_after = {'(', '[', '{', '"', "'"}
    for token in tokens:
        if not token:
            continue
        if not text:
            text = token
            continue
        if token[0] in no_space_before or text[-1] in no_space_after:
            text += token
        else:
            text += ' ' + token
    return text.strip()



# 인라인 편집 시 선택 가능한 글꼴 목록
# (표시명, TTF 경로, PDF 폰트명, Qt 패밀리 이름)
_INLINE_FONT_OPTIONS = [
    ('KoPub 바탕 Light',  'C:/Windows/Fonts/KoPub Batang Light.ttf',  'KoPubBatangLight',  'KoPubBatang'),
    ('KoPub 바탕 Medium', 'C:/Windows/Fonts/KoPub Batang Medium.ttf', 'KoPubBatangMedium', 'KoPubBatang'),
    ('KoPub 바탕 Bold',   'C:/Windows/Fonts/KoPub Batang Bold.ttf',   'KoPubBatangBold',   'KoPubBatang'),
    ('KoPub 돋움 Light',  'C:/Windows/Fonts/KoPub Dotum Light.ttf',   'KoPubDotumLight',   'KoPubDotum'),
    ('KoPub 돋움 Medium', 'C:/Windows/Fonts/KoPub Dotum Medium.ttf',  'KoPubDotumMedium',  'KoPubDotum'),
    ('KoPub 돋움 Bold',   'C:/Windows/Fonts/KoPub Dotum Bold.ttf',    'KoPubDotumBold',    'KoPubDotum'),
    ('맑은 고딕',         'C:/Windows/Fonts/malgun.ttf',               'MalgunGothic',      'Malgun Gothic'),
    ('맑은 고딕 Bold',    'C:/Windows/Fonts/malgunbd.ttf',             'MalgunGothicBold',  'Malgun Gothic'),
    ('함초롬바탕',        'C:/Windows/Fonts/HANBatang.ttf',            'HanBatang',         '함초롬바탕'),
    ('함초롬바탕 Bold',   'C:/Windows/Fonts/HANBatangB.ttf',           'HanBatangB',        '함초롬바탕'),
]


# ─────────────────────────────────────────────────────────────────
class _InlineEdit(QLineEdit):
    """PDF 본문 텍스트를 제자리에서 편집하는 오버레이 위젯.
    Enter → 확정 / Esc → 취소 / 포커스 이탈 → 취소 (실수 방지)"""

    _STYLE_NORMAL = """
        QLineEdit {
            background: rgba(255, 255, 200, 245);
            border: 2px solid #1a7fc1;
            border-radius: 2px;
            padding: 0px 3px;
            selection-background-color: #90caf9;
        }
    """
    _STYLE_WARN = """
        QLineEdit {
            background: rgba(255, 235, 200, 245);
            border: 2px solid #e65100;
            border-radius: 2px;
            padding: 0px 3px;
            selection-background-color: #ffcc80;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fitz_rect:     fitz.Rect | None = None
        self.fs:            float            = 11.0
        self.original_text: str              = ''
        self._committed:    bool             = False
        self.origin:        tuple | None     = None   # (x, y) 실제 베이스라인 점
        self.font_key:      int              = 0      # _INLINE_FONT_OPTIONS 인덱스
        self.text_color:    tuple            = (0.0, 0.0, 0.0)  # 감지된 글자색
        self.orig_font:     str              = ''     # 원본 스팬 글꼴명
        self._companion:    QWidget | None   = None   # 글꼴 선택 바 (companion)
        self.setStyleSheet(self._STYLE_NORMAL)

    def set_warning(self, on: bool):
        self.setStyleSheet(self._STYLE_WARN if on else self._STYLE_NORMAL)
        tip = ('⚠ 이 PDF의 글자가 깨져 추출됐습니다.\n'
               '텍스트를 직접 다시 입력 후 Enter로 확정하세요.\n'
               'Esc = 취소 (원본 유지)') if on else 'Enter=확정  Esc=취소'
        self.setToolTip(tip)

    def _hide_all(self):
        self.hide()
        if self._companion:
            self._companion.hide()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self._committed = False
            self._hide_all()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._committed = True
            # 부모 view의 commit 핸들러 직접 호출
            pv = self.parentWidget()
            while pv and not hasattr(pv, '_on_inline_committed'):
                pv = pv.parentWidget()
            if pv:
                pv._on_inline_committed(self.text())
            self._hide_all()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        # 포커스 이탈 = 취소 (실수로 적용되는 것을 방지)
        self._committed = False
        self._hide_all()
        super().focusOutEvent(event)


# ── 본문 텍스트 스팬의 색·글꼴 자동 감지 ────────────────────────────────
# HWP 조판 PDF가 쓰는, 삽입용 글꼴에 글리프가 없어 □로 깨지는 특수 문장부호를
# 널리 지원되는 등가 문자로 정규화한다(예: DOT OPERATOR ⋅ → MIDDLE DOT ·).
# 편집한 줄이 여백을 넘칠 때, 글자 크기를 줄이기 전에 가로로 조일 수 있는 한계.
# 크기가 조금만 달라져도 주변 글자와 어긋나 보이므로(특히 각주처럼 작은 글씨),
# 이 비율까지는 크기를 그대로 두고 가로로만 조인다.
_SQUEEZE_MIN = 0.70

_PUNCT_NORMALIZE = {
    '⋅': '·',   # ⋅ DOT OPERATOR → · MIDDLE DOT
    '∙': '·',   # ∙ BULLET OPERATOR
    '‧': '·',   # ‧ HYPHENATION POINT
    '・': '·',   # ・ KATAKANA MIDDLE DOT
    '･': '·',   # ･ HALFWIDTH KATAKANA MIDDLE DOT
}


def _normalize_punct(s: str) -> str:
    if not s:
        return s
    for a, b in _PUNCT_NORMALIZE.items():
        if a in s:
            s = s.replace(a, b)
    return s


def _para_visual_rows(page, rect, skip=None) -> list:
    """문단 사각형을 '시각적 행' 목록으로 복원한다.

    skip: [[x0, y0, x1, y1, n], ...] — 이전 편집으로 흰 덮개를 씌운 영역과 그
    시점의 옛 글자 수. 각 영역에서 처음 n개 글자는 화면에 안 보이는 '유령
    글자'이므로 건너뛴다(옛 글자와 새 글자가 겹쳐 읽히는 것을 막는다).

    한글 학술 PDF(HWP 계열 조판)는 텍스트층에 단어 사이 공백이 없고 문장부호·
    아래첨자가 스트림 순서상 뒤죽박죽인 경우가 많다. 그대로 뽑으면 붙어버리거나
    순서가 뒤엉킨다. 그래서 글자(char) 단위 위치로 (1) 같은 시각적 행끼리 y로
    묶고 (2) 행 안에서 x로 정렬하고 (3) 글자 간격이 벌어지면 공백을 넣어
    사람이 보는 대로 복원한다.

    반환: [{'y','x0','x1','y0','y1','baseline','fs','bold','font','text'}, ...]
    (위→아래). 실패 시 빈 목록."""
    import statistics as _st
    try:
        d = page.get_text('rawdict', clip=rect)
    except Exception:
        return []
    # 남은 '건너뛸 개수'를 이 호출 동안만 세는 사본 (원본 기록은 보존)
    _skip_state = [list(s) for s in skip] if skip else None
    chars = []
    for b in d.get('blocks', []):
        if b.get('type', 0) != 0:
            continue
        for ln in b.get('lines', []):
            for sp in ln.get('spans', []):
                fs = sp.get('size', 10) or 10
                font = sp.get('font', '') or ''
                flags = int(sp.get('flags', 0))
                bold = bool(flags & 16) or 'bold' in font.lower()
                for ch in sp.get('chars', []):
                    cb = ch['bbox']
                    if cb[2] < rect.x0 or cb[0] > rect.x1:
                        continue
                    if cb[3] < rect.y0 or cb[1] > rect.y1:
                        continue
                    if _skip_state is not None:
                        # 덮개 영역 안이면, 그 영역의 옛 글자 수만큼 먼저 버린다
                        cx = (cb[0] + cb[2]) / 2.0
                        cy = (cb[1] + cb[3]) / 2.0
                        _hit = None
                        for st in _skip_state:
                            if (st[0] - 1 <= cx <= st[2] + 1
                                    and st[1] - 1 <= cy <= st[3] + 1):
                                _hit = st
                                break
                        if _hit is not None and _hit[4] > 0:
                            _hit[4] -= 1
                            continue      # 화면에 안 보이는 옛 글자
                    org = ch.get('origin', (cb[0], cb[3]))
                    chars.append({'x0': cb[0], 'x1': cb[2], 'y0': cb[1], 'y1': cb[3],
                                  'yc': (cb[1] + cb[3]) / 2.0, 'base': org[1],
                                  'c': ch.get('c', ''), 'fs': fs,
                                  'bold': bold, 'font': font})
    if not chars:
        return []
    fs_med = _st.median(c['fs'] for c in chars)
    tol = fs_med * 0.5
    chars.sort(key=lambda c: c['yc'])         # y-중심으로 정렬
    rows, cur, base = [], [], None
    for c in chars:
        if base is None or abs(c['yc'] - base) <= tol:
            cur.append(c)
            base = c['yc'] if base is None else (base * (len(cur) - 1) + c['yc']) / len(cur)
        else:
            rows.append(cur); cur = [c]; base = c['yc']
    if cur:
        rows.append(cur)
    out = []
    for row in rows:
        row.sort(key=lambda c: c['x0'])       # 행 안에서 좌→우
        s, prev_x1 = [], None
        for c in row:
            if prev_x1 is not None and (c['x0'] - prev_x1) > c['fs'] * 0.22 \
                    and c['c'] != ' ' and s and s[-1] != ' ':
                s.append(' ')
            s.append(c['c']); prev_x1 = c['x1']
        txt = _normalize_punct(''.join(s).rstrip())
        if not txt:
            continue
        nb = sum(1 for c in row if c['bold'])
        out.append({
            'y': _st.median(c['yc'] for c in row),
            'x0': min(c['x0'] for c in row),
            'x1': max(c['x1'] for c in row),
            'y0': min(c['y0'] for c in row),
            'y1': max(c['y1'] for c in row),
            'baseline': _st.median(c['base'] for c in row),
            'fs': _st.median(c['fs'] for c in row),
            'bold': nb * 2 >= len(row),        # 행의 과반이 굵으면 굵게
            'font': row[0]['font'],
            'text': txt,
        })
    out.sort(key=lambda r: r['y'])
    return out


def _reconstruct_para_text(page, rect) -> str:
    """문단 사각형의 텍스트를 시각적 순서·간격으로 복원(공백·순서 보존)."""
    rows = _para_visual_rows(page, rect)
    if not rows:
        return page.get_textbox(rect).rstrip('\n').rstrip()
    return '\n'.join(r['text'] for r in rows).strip()


def _paragraph_runs(rows: list, right_margin: float) -> list:
    """행 목록을 '논리 문단' 단위로 끊는다 → [[row,...], ...].

    문단은 '오른쪽 여백에 못 미치는 짧은 줄'에서 끝난다(마지막 줄). 각주처럼
    여러 항목이 한 블록에 묶여도 항목끼리 섞이지 않게 해 준다."""
    import statistics as _st
    if not rows:
        return []
    fs = _st.median(r['fs'] for r in rows) or 10.0
    thr = max(4.0, fs * 0.6)
    runs, cur = [], []
    for r in rows:
        cur.append(r)
        if r['x1'] < right_margin - thr:      # 짧은 줄 = 문단 끝
            runs.append(cur); cur = []
    if cur:
        runs.append(cur)
    return runs


def _rows_have_hanging_indent(rows: list) -> bool:
    """각주처럼 '첫 줄은 왼쪽, 이어지는 줄은 들여쓴' 구조인지."""
    import statistics as _st
    if len(rows) < 3:
        return False
    fs = _st.median(r['fs'] for r in rows) or 10.0
    lefts = [r['x0'] for r in rows]
    base = min(lefts)
    indented = sum(1 for x in lefts if x - base > fs * 0.5)
    # 다수가 들여쓰기면 내어쓰기(행잉) 구조로 본다
    return indented >= max(2, int(len(rows) * 0.4))


# 뒷줄이 이런 조사·어미로 시작하면 앞 단어에 붙는다 → 이음매에 공백 없음
_SEAM_PARTICLE_START = {
    '은', '는', '이', '가', '을', '를', '의', '에', '와', '과', '로', '도', '만',
    '으로', '에서', '에게', '부터', '까지', '라고', '이나', '처럼', '대로',
    '보다', '밖에', '조차', '마다', '로써', '으로써', '이란', '이라는', '라는',
    '던', '다', '고', '서', '며', '면', '지', '게', '한', '할', '된', '될',
    '함', '됨', '임', '들', '적', '인',
    '서는', '에서는', '으로서', '로서', '이고', '이며', '이라', '이다', '이나',
    '에는', '에도', '으로는', '로는', '와는', '과는', '만이', '까지도',
}
# 앞줄이 이런 글자로 끝나면 어절이 끝난 것 → 이음매에 공백을 넣는다
_SEAM_WORD_FINAL = set('은는이가을를의에와과로도만서고다며면나자지게여야'
                       '음함됨임한할된될던든써요죠네것수등적인')


def _join_seam(prev: str, nxt: str) -> str:
    """줄 이음매에 띄어쓰기를 넣을지 판단해 이어 붙인다.

    이 계열 PDF는 줄 끝 공백을 기록하지 않아 원래 띄어쓰기였는지 알 수 없다.
    그래서 한국어 어절 규칙으로 추정한다:
      1) 뒷줄이 조사/어미로 시작하면 앞 단어에 붙는다(공백 없음).
      2) 앞줄이 조사/어미로 끝나면 어절이 끝난 것 → 공백.
      3) 그 밖에는 단어 중간에서 끊긴 것으로 보고 붙인다.
    라틴/숫자는 항상 공백에서 줄이 바뀌므로 공백을 넣는다."""
    import re as _re
    if not prev:
        return nxt
    if not nxt:
        return prev
    a, b = prev[-1], nxt[0]
    # ① 뒷줄 첫 한글 덩어리가 조사/어미면 앞 단어에 붙는다. 각주번호·괄호가
    #    뒤에 붙어 있어도('이고3)') 한글 부분만 보고 판단하며, 앞줄이 괄호·
    #    따옴표로 끝나도('Loewenstein)' + '은') 이 규칙을 먼저 적용한다.
    _m = _re.match(r'^[가-힣]+', nxt)
    if _m and _m.group(0) in _SEAM_PARTICLE_START:
        return prev + nxt
    if a in '.?!;:,】」』…':
        return prev + ' ' + nxt
    if (a.isascii() and a.isalnum()) or (b.isascii() and b.isalnum()):
        return prev + ' ' + nxt
    if a in ')”’':                             # 닫는 괄호·따옴표 뒤는 보통 띄움
        return prev + ' ' + nxt
    if a in _SEAM_WORD_FINAL:                  # ② 어절 끝 → 띄움
        return prev + ' ' + nxt
    return prev + nxt                          # ③ 단어 중간 → 붙임


def _flow_text_from_rows(rows: list, right_margin: float) -> str:
    """행들을 '문단별로 이어 붙인' 흐르는 텍스트로 만든다(캔바식 편집용).

    문단 첫 줄이 들여쓰기였으면 전각공백을 앞에 붙여 재배치 후에도 들여쓰기가
    남게 한다."""
    import statistics as _st
    runs = _paragraph_runs(rows, right_margin)
    if not runs:
        return ''
    body_left = min(r['x0'] for r in rows)
    fs = _st.median(r['fs'] for r in rows) or 10.0
    out = []
    for run in runs:
        s = ''
        for r in run:
            s = _join_seam(s, r['text'].strip())
        s = s.strip()
        if not s:
            continue
        if run[0]['x0'] - body_left > fs * 0.5:      # 원래 들여쓴 문단
            s = '　' + s
        out.append(s)
    return '\n'.join(out)


def _detect_para_layout(rows: list, block_rect):
    """복원된 시각적 행들로 정렬과 줄간격 배수를 추정한다.

    반환: (align, lineheight_mult). lineheight_mult 은 fontsize 대비 줄간격
    배수(baseline↔baseline)로, insert_textbox 의 lineheight 로 넘겨 원본의
    넉넉한 줄간격을 재현한다."""
    import fitz as _f
    import statistics as _st
    align = _f.TEXT_ALIGN_LEFT
    lh_mult = None
    if not rows:
        return align, lh_mult
    fs = _st.median(r['fs'] for r in rows) or 10.0

    # ── 줄간격 배수: 인접 행 y중심 간격의 중앙값 / fs ──
    if len(rows) >= 2:
        ys = sorted(r['y'] for r in rows)
        gaps = [b - a for a, b in zip(ys, ys[1:]) if (b - a) > fs * 0.4]
        if gaps:
            lh_mult = max(1.0, min(2.5, _st.median(gaps) / fs))

    # ── 정렬: 오른쪽 여백에 '닿는' 줄의 비율로 판단(들쭉날쭉한 조판·첫 줄
    #    들여쓰기·짧은 마지막 줄에도 강건) ──
    if len(rows) >= 2:
        lefts = [r['x0'] for r in rows]
        rights = [r['x1'] for r in rows]
        thr = max(4.0, fs * 0.6)
        n = len(rows)
        right_margin = max(rights)
        left_margin = min(lefts)
        # 오른쪽 여백까지 닿는 줄 수(양쪽맞춤이면 마지막 줄 빼고 거의 전부)
        reach = sum(1 for x in rights if x >= right_margin - thr)
        # 왼쪽 여백에서 시작하는 줄 수
        at_left = sum(1 for x in lefts if x <= left_margin + thr)
        centers = [(l + r) / 2 for l, r in zip(lefts, rights)]
        center_var = max(centers) - min(centers)
        many_reach = reach >= max(2, int(round(n * 0.6)))     # 대다수가 우측 여백까지
        many_left = at_left >= max(2, int(round(n * 0.6)))    # 대다수가 좌측 여백서 시작
        if n >= 3 and many_reach and many_left:
            align = _f.TEXT_ALIGN_JUSTIFY          # 양쪽 맞춤(학술문서 본문)
        elif many_reach and not many_left:
            align = _f.TEXT_ALIGN_RIGHT            # 오른쪽 정렬(들쭉날쭉 좌측)
        elif center_var < thr and not many_reach and not many_left:
            align = _f.TEXT_ALIGN_CENTER
    return align, lh_mult


def _span_color_rgb(span) -> tuple[float, float, float]:
    """PDF 스팬의 글자색(sRGB 정수) → (r,g,b) 0~1."""
    try:
        r, g, b = fitz.sRGB_to_rgb(int(span.get('color', 0)))
        return (r / 255.0, g / 255.0, b / 255.0)
    except Exception:
        return (0.0, 0.0, 0.0)


def _detect_inline_font_index(span) -> int:
    """스팬의 글꼴명/굵기 플래그로 _INLINE_FONT_OPTIONS 인덱스 추정."""
    name = (span.get('font') or '').lower()
    flags = int(span.get('flags', 0))
    bold = bool(flags & 16) or any(k in name for k in
                                   ('bold', 'black', 'heavy', 'semibold'))
    serif = bool(flags & 4) or any(k in name for k in (
        'batang', 'myeongjo', 'myungjo', 'mincho', 'serif', 'times',
        'roman', 'song', 'gungsuh', 'bat', '바탕', '명조', '궁서'))
    if serif:
        return 2 if bold else 0     # KoPub 바탕 Bold / Light
    if any(k in name for k in ('malgun', 'gulim', 'dotum', '맑은', '굴림', '돋움')):
        if 'malgun' in name or '맑은' in name:
            return 7 if bold else 6     # 맑은 고딕 / Bold
    return 5 if bold else 3             # KoPub 돋움 Bold / Light


_KO_BOLD_MAP = {0: 2, 1: 2, 3: 5, 4: 5, 6: 7, 8: 9}   # 한글 글꼴 → Bold 변형 인덱스


_FONT_OBJ_CACHE: dict = {}
# 한글 글꼴이 못 그리는 글자(악센트 라틴 ü·é, 엠대시 — 등)를 대신 그릴, 한글과
# 라틴을 모두 갖춘 대체 글꼴. 앞쪽이 우선(바탕=세리프라 학술문서와 어울림).
_BROAD_FONT_CANDIDATES = [
    ('batangBroad', 'C:/Windows/Fonts/batang.ttc'),
    ('HanBatangBroad', 'C:/Windows/Fonts/HANBatang.ttf'),
    ('malgunBroad', 'C:/Windows/Fonts/malgun.ttf'),
]
_CJK_BUILTIN_FONTS = {'korea', 'china-s', 'china-t', 'japan'}


def _font_obj(fontfile: str | None, fontname: str):
    key = fontfile or fontname
    if key in _FONT_OBJ_CACHE:
        return _FONT_OBJ_CACHE[key]
    try:
        f = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font(fontname=fontname)
    except Exception:
        f = None
    _FONT_OBJ_CACHE[key] = f
    return f


def _font_covers(fontfile: str | None, fontname: str, text: str) -> bool:
    """이 글꼴로 text의 모든 글자를 그릴 수 있는지 검사."""
    if not fontfile:
        # 내장 CJK 글꼴은 has_glyph 가 실제 렌더와 어긋난다(ü 있다고 하고 □ 출력).
        # ASCII·한글 외 글자가 섞여 있으면 믿지 않는다. base-14 라틴 글꼴은 신뢰.
        if (fontname or '').lower() in _CJK_BUILTIN_FONTS:
            return not any(not (ord(c) < 0x80 or 0xAC00 <= ord(c) <= 0xD7A3)
                           for c in text)
        return True
    f = _font_obj(fontfile, fontname)
    if f is None:
        return True
    for c in text:
        if ord(c) < 0x21:          # 공백·제어문자는 검사 제외
            continue
        try:
            if f.has_glyph(ord(c)) == 0:
                return False
        except Exception:
            return True
    return True


def _broad_font_for(text: str):
    """text 전체를 그릴 수 있는 대체 글꼴 → (fontfile, fontname) | (None, None)."""
    import os as _os
    for name, path in _BROAD_FONT_CANDIDATES:
        if _os.path.exists(path) and _font_covers(path, name, text):
            return path, name
    return None, None


def _pick_insert_font(text: str, orig_font: str, font_key: int,
                      bold: bool = False, italic: bool = False):
    """재삽입할 글꼴을 정한다 → (fontfile | None, fontname).
    라틴/숫자는 원본과 같은 계열의 base-14 폰트(굵게/기울임 변형 포함)를 유지,
    한글은 선택된 한글 폰트(굵으면 Bold 변형)를 쓴다."""
    import os as _os
    has_ko = any(0xAC00 <= ord(c) <= 0xD7A3 for c in text)
    n = (orig_font or '').lower()
    if not has_ko:
        if any(k in n for k in ('times', 'serif', 'roman', 'georgia',
                                'minion', 'garamond', 'batang', 'myeongjo', 'mincho')):
            fam = {(False, False): 'Times-Roman', (True, False): 'Times-Bold',
                   (False, True): 'Times-Italic', (True, True): 'Times-BoldItalic'}
        elif any(k in n for k in ('courier', 'mono', 'consol')):
            fam = {(False, False): 'cour', (True, False): 'cobo',
                   (False, True): 'coit', (True, True): 'cobi'}
        else:
            fam = {(False, False): 'helv', (True, False): 'hebo',
                   (False, True): 'heit', (True, True): 'hebi'}
        return None, fam[(bool(bold), bool(italic))]
    fidx = max(0, min(font_key, len(_INLINE_FONT_OPTIONS) - 1))
    if bold:
        fidx = _KO_BOLD_MAP.get(fidx, fidx)
    _, fpath, fname, _ = _INLINE_FONT_OPTIONS[fidx]
    if _os.path.exists(fpath):
        return fpath, fname
    return None, 'korea'


class _InlineBlockEdit(QPlainTextEdit):
    """PDF 본문 텍스트 '블록(문단)'을 여러 줄로 편집하는 오버레이.
    Ctrl+Enter → 확정 / Esc → 취소 / 포커스 이탈 → 취소."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fitz_rect: fitz.Rect | None = None
        self.fs: float = 11.0
        self.original_text: str = ''
        self.font_key: int = 0
        self.text_color: tuple = (0.0, 0.0, 0.0)
        self.align: int = 0        # fitz.TEXT_ALIGN_*
        self.page_idx: int = 0
        self.orig_font: str = ''
        self.bold: bool = False
        self.italic: bool = False
        self.underline: bool = False
        self._bg = '#ffffff'
        self._fg = '#000000'
        self._companion = None
        self._committing = False
        self.setFrameStyle(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._apply_style(focused=True)

    def _apply_style(self, focused: bool):
        # 문서와 똑같이 보이도록 페이지 배경색·글자색을 그대로 쓰고,
        # 편집 중임을 알리는 얇은 점선 테두리만 둔다 (유료앱 제자리 편집 느낌).
        border = '1px dashed rgba(26,127,193,0.9)' if focused else '1px solid rgba(0,0,0,0.15)'
        self.setStyleSheet(
            f'QPlainTextEdit {{ background: {self._bg}; color: {self._fg};'
            f' border: {border}; border-radius: 1px; padding: 0px 1px;'
            f' selection-background-color: #a8d1ff; }}')

    def set_appearance(self, qfont, color_rgb, bg_rgb=(1, 1, 1)):
        self.setFont(qfont)
        self._fg = '#%02x%02x%02x' % (int(color_rgb[0]*255), int(color_rgb[1]*255), int(color_rgb[2]*255))
        self._bg = '#%02x%02x%02x' % (int(bg_rgb[0]*255), int(bg_rgb[1]*255), int(bg_rgb[2]*255))
        self._apply_style(focused=True)

    def _hide_all(self):
        self.hide()
        if self._companion:
            self._companion.hide()

    def _commit(self):
        if self._committing:
            return
        self._committing = True
        try:
            pv = self.parentWidget()
            while pv and not hasattr(pv, '_on_block_committed'):
                pv = pv.parentWidget()
            if pv:
                pv._on_block_committed(self.toPlainText())
        finally:
            self._committing = False
        self._hide_all()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self._hide_all()          # 취소 (원본 유지)
            return
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and
                event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._commit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        # 다른 곳을 클릭해 편집기를 벗어나면 자동 확정 (유료앱처럼 자연스럽게)
        if self.isVisible() and not self._committing:
            self._commit()
        super().focusOutEvent(event)


# 렌더링 품질 줌 (fitz → QImage). 뷰 줌과 별개.
# 화면 표시는 QGraphicsView 트랜스폼으로 처리 → 어노테이션 좌표 변환은 이 값 사용.
_BASE_RENDER_ZOOM = 2.0

# PDF 선 어노테이션의 화살촉(/LE) 크기 — MuPDF 렌더 결과 실측값.
# 화살촉 길이 ≈ 10.25 × 선굵기, 반폭 ≈ 5.25 × 선굵기.
_PDF_ARROW_LEN_RATIO = 10.25
_PDF_ARROW_ANGLE     = 0.474   # atan(5.25 / 10.25) rad
_HQ_IDLE_DELAY_MS = 180
_SCROLL_PREFETCH_BUFFER = 4   # 뷰포트 위아래 미리 렌더링할 페이지 수
_SCROLL_RETAIN_MARGIN   = 12  # 렌더 창 밖에서 픽스맵을 유지할 여유 페이지 수


class _ScrollRenderWorker(QThread):
    """세로 스크롤 모드 백그라운드 페이지 렌더링 워커.

    별도 fitz.Document 인스턴스를 열어 메인 스레드와 독립적으로 렌더링한다.
    우선순위 큐: prioritize() 호출로 보이는 페이지를 앞으로 당긴다.
    """
    page_ready = Signal(int, QImage)

    def __init__(self, doc_path: str, zoom: float, parent=None, password: str = ''):
        super().__init__(parent)
        self._doc_path = doc_path
        self._zoom = zoom
        self._password = password or ''
        self._queue: list[int] = []
        self._rendered: set[int] = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop_flag = False

    def set_window(self, pages: list[int]):
        """큐를 지정된 페이지들로만 교체 (이미 렌더링 완료된 것 제외)."""
        with self._lock:
            self._queue = [p for p in pages if p not in self._rendered]
        self._wake.set()

    def stop(self):
        self._stop_flag = True
        self._wake.set()

    def forget(self, indices):
        """축출된 페이지를 '렌더된 적 없음'으로 되돌린다 (재방문 시 재렌더)."""
        with self._lock:
            self._rendered.difference_update(indices)

    def run(self):
        try:
            # 파일에서 lazy 로딩 — 대용량 PDF도 전체를 메모리에 올리지
            # 않는다. 저장 전에는 canvas.release_file_handles()가 워커를
            # 중단시켜 핸들을 해제한다.
            doc = fitz.open(self._doc_path)
            if doc.needs_pass and self._password:
                doc.authenticate(self._password)   # 암호화 문서 인증
        except Exception:
            return
        try:
            while not self._stop_flag:
                self._wake.wait()
                self._wake.clear()
                while not self._stop_flag:
                    with self._lock:
                        if not self._queue:
                            break
                        idx = self._queue.pop(0)
                        if idx in self._rendered:
                            continue
                    try:
                        page = doc[idx]
                        mat = fitz.Matrix(self._zoom, self._zoom)
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                        img = QImage(
                            bytes(pix.samples), pix.width, pix.height,
                            pix.stride, QImage.Format.Format_RGB888
                        ).copy()
                        del pix
                        with self._lock:
                            self._rendered.add(idx)
                        self.page_ready.emit(idx, img)
                    except Exception:
                        swallowed()
        finally:
            doc.close()



_HQ_RENDER_MIN_ZOOM = 3.0
_HQ_RENDER_MAX_ZOOM = 10.0          # 확대해도 항상 벡터 품질에 가깝게
_HQ_RENDER_MAX_PIXELS = 25_000_000  # A4 기준 ≈7.1× 렌더 허용 (~75 MB/page)



def _make_line_path(x1: float, y1: float, x2: float, y2: float,
                    width: float,
                    line_end_start: int = 0,
                    line_end_end: int = 0) -> QPainterPath:
    import math as _math

    path = QPainterPath()
    path.moveTo(x1, y1)
    path.lineTo(x2, y2)

    def _add_head(ax: float, ay: float, bx: float, by: float, line_end: int):
        if line_end not in (
            fitz.PDF_ANNOT_LE_OPEN_ARROW,
            fitz.PDF_ANNOT_LE_CLOSED_ARROW,
        ):
            return
        dx, dy = bx - ax, by - ay
        length = _math.hypot(dx, dy)
        if length <= 1e-3:
            return
        arrow_len = max(14.0, width * 6.5)
        angle = 0.48
        ux, uy = dx / length, dy / length
        hx1 = bx - arrow_len * (ux * _math.cos(angle) - uy * _math.sin(angle))
        hy1 = by - arrow_len * (uy * _math.cos(angle) + ux * _math.sin(angle))
        hx2 = bx - arrow_len * (ux * _math.cos(angle) + uy * _math.sin(angle))
        hy2 = by - arrow_len * (uy * _math.cos(angle) - ux * _math.sin(angle))
        path.moveTo(hx1, hy1)
        path.lineTo(bx, by)
        path.lineTo(hx2, hy2)
        if line_end == fitz.PDF_ANNOT_LE_CLOSED_ARROW:
            path.closeSubpath()

    _add_head(x2, y2, x1, y1, line_end_start)
    _add_head(x1, y1, x2, y2, line_end_end)
    return path

def _make_pending_item(pa, offset: QPointF, zoom: float):
    """PendingAnnotation → QGraphicsItem (씬 좌표계).
    offset: 해당 페이지의 씬 내 좌상단 위치."""
    from PySide6.QtGui import QPainterPath, QPen, QBrush
    from PySide6.QtWidgets import (QGraphicsRectItem, QGraphicsEllipseItem,
                                   QGraphicsPathItem, QGraphicsLineItem,
                                   QGraphicsPixmapItem)

    ox, oy = offset.x(), offset.y()

    def qc(c, alpha=255):
        if c is None:
            return QColor(0, 0, 0, 0)
        return QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255), alpha)

    def pw(width: float, minimum: float = 0.3) -> float:
        """PDF 포인트 단위 선 굵기 → 씬 단위.

        도형 좌표는 zoom 배로 확대해 그리므로 선 굵기도 같이 곱해야
        커밋 후(실제 PDF 렌더) 굵기와 미리보기가 일치한다.
        """
        return max(minimum, float(width) * zoom)

    def qdash(dashes, width: float = 1.0) -> list[float]:
        """대시 패턴 → Qt 대시 패턴 (둘 다 '선 굵기의 배수' 단위)."""
        return [max(0.01, float(v)) for v in dashes]

    at = pa.annot_type

    if at == 'rect':
        r    = pa.fitz_rect
        item = QGraphicsRectItem(r.x0*zoom+ox, r.y0*zoom+oy,
                                 r.width*zoom,  r.height*zoom)
        alpha = int(pa.opacity * 255)
        pen = QPen(qc(pa.stroke_color, alpha), pw(pa.border_width))
        if pa.dashes:
            pen.setDashPattern(qdash(pa.dashes, pa.border_width))
        item.setPen(pen)
        item.setBrush(QBrush(qc(pa.fill_color, alpha) if pa.fill_color
                             else QColor(0, 0, 0, 0)))
        return item

    elif at == 'ink':
        path = QPainterPath()
        for stroke in (pa.points or []):
            if not stroke:
                continue
            path.moveTo(stroke[0][0]*zoom+ox, stroke[0][1]*zoom+oy)
            for x, y in stroke[1:]:
                path.lineTo(x*zoom+ox, y*zoom+oy)
        item = QGraphicsPathItem()
        item.setPath(path)
        pen = QPen(qc(pa.stroke_color), pw(pa.border_width))
        # 획이 꺾이는 곳을 둥글게 — 각져 보이던 문제
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if pa.dashes:
            pen.setDashPattern(qdash(pa.dashes, pa.border_width))
        item.setPen(pen)
        item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        return item

    elif at == 'arrow':
        # 몸통 + 화살촉 (화살촉 크기는 도구가 이미 정해 두었다)
        from PySide6.QtWidgets import QGraphicsItemGroup
        strokes = pa.points or []
        group = QGraphicsItemGroup()
        if strokes:
            def _mk(stroke):
                path = QPainterPath()
                path.moveTo(stroke[0][0]*zoom+ox, stroke[0][1]*zoom+oy)
                for x, y in stroke[1:]:
                    path.lineTo(x*zoom+ox, y*zoom+oy)
                return QGraphicsPathItem(path)

            shaft = _mk(strokes[0])
            spen = QPen(qc(pa.stroke_color), pw(pa.border_width))
            spen.setCapStyle(Qt.PenCapStyle.RoundCap)
            if pa.dashes:
                spen.setDashPattern(qdash(pa.dashes, pa.border_width))
            shaft.setPen(spen)
            shaft.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            group.addToGroup(shaft)
            closed = bool(pa.line_end_end)
            for head in strokes[1:]:
                if len(head) < 2:
                    continue
                item = _mk(head)
                if closed:
                    item.setPen(QPen(qc(pa.stroke_color),
                                     pw(pa.border_width * 0.12, 0.3)))
                    item.setBrush(QBrush(qc(pa.fill_color or pa.stroke_color)))
                else:
                    hpen = QPen(qc(pa.stroke_color), pw(pa.border_width))
                    hpen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                    item.setPen(hpen)
                    item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                group.addToGroup(item)
        if pa.opacity < 0.99:
            group.setOpacity(pa.opacity)
        return group

    elif at == 'circle':
        r    = pa.fitz_rect
        item = QGraphicsEllipseItem(r.x0*zoom+ox, r.y0*zoom+oy,
                                    r.width*zoom,  r.height*zoom)
        pen = QPen(qc(pa.stroke_color), pw(pa.border_width))
        if pa.dashes:
            pen.setDashPattern(qdash(pa.dashes, pa.border_width))
        item.setPen(pen)
        item.setBrush(QBrush(qc(pa.fill_color) if pa.fill_color
                             else QColor(0, 0, 0, 0)))
        return item

    elif at == 'line':
        from PySide6.QtWidgets import QGraphicsItemGroup
        import math as _math

        def _head_geometry(ax, ay, bx, by, width):
            dx, dy = bx - ax, by - ay
            length = _math.hypot(dx, dy)
            if length <= 1e-3:
                return None
            # PDF 의 화살촉(/LE)은 뷰어가 선 굵기에 비례해 그린다.
            # MuPDF 실측: 길이 ≈ 9.5w, 반폭 ≈ 4.5w (w = 선 굵기).
            # 미리보기도 같은 비율로 그려야 "적용하면 화살촉만 커지는" 착시가 없다.
            arrow_len = max(4.0, width * _PDF_ARROW_LEN_RATIO)
            angle = _PDF_ARROW_ANGLE
            ux, uy = dx / length, dy / length
            hx1 = bx - arrow_len * (ux * _math.cos(angle) - uy * _math.sin(angle))
            hy1 = by - arrow_len * (uy * _math.cos(angle) + ux * _math.sin(angle))
            hx2 = bx - arrow_len * (ux * _math.cos(angle) + uy * _math.sin(angle))
            hy2 = by - arrow_len * (uy * _math.cos(angle) - ux * _math.sin(angle))
            return (hx1, hy1), (hx2, hy2), ((hx1 + hx2) / 2.0, (hy1 + hy2) / 2.0)

        def _head_path(ax, ay, bx, by, width, closed):
            geom = _head_geometry(ax, ay, bx, by, width)
            if geom is None:
                return QPainterPath()
            (hx1, hy1), (hx2, hy2), _ = geom
            path = QPainterPath()
            path.moveTo(hx1, hy1)
            path.lineTo(bx, by)
            path.lineTo(hx2, hy2)
            if closed:
                path.closeSubpath()
            return path

        x1, y1 = pa.p1.x*zoom+ox, pa.p1.y*zoom+oy
        x2, y2 = pa.p2.x*zoom+ox, pa.p2.y*zoom+oy
        w = pw(pa.border_width)
        shaft_pen = QPen(qc(pa.stroke_color), w)
        if pa.dashes:
            shaft_pen.setDashPattern(qdash(pa.dashes, pa.border_width))
        if pa.line_end_end or pa.line_end_start:
            group = QGraphicsItemGroup()
            shaft_x2, shaft_y2 = x2, y2
            if pa.line_end_end:
                geom = _head_geometry(x1, y1, x2, y2, w)
                if geom is not None:
                    _, _, (shaft_x2, shaft_y2) = geom
            shaft = QGraphicsLineItem(x1, y1, shaft_x2, shaft_y2)
            shaft.setPen(shaft_pen)
            group.addToGroup(shaft)
            head_pen = QPen(qc(pa.stroke_color), w)
            head_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            if pa.line_end_end:
                closed = pa.line_end_end == fitz.PDF_ANNOT_LE_CLOSED_ARROW
                head = QGraphicsPathItem(_head_path(x1, y1, x2, y2, w, closed))
                head.setPen(head_pen)
                if closed and pa.fill_color:
                    head.setBrush(QBrush(qc(pa.fill_color)))
                else:
                    head.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                group.addToGroup(head)
            if pa.line_end_start:
                closed = pa.line_end_start == fitz.PDF_ANNOT_LE_CLOSED_ARROW
                head = QGraphicsPathItem(_head_path(x2, y2, x1, y1, w, closed))
                head.setPen(head_pen)
                if closed and pa.fill_color:
                    head.setBrush(QBrush(qc(pa.fill_color)))
                else:
                    head.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                group.addToGroup(head)
            item = group
        else:
            item = QGraphicsLineItem(x1, y1, x2, y2)
            item.setPen(shaft_pen)
        return item

    elif at == 'polygon':
        path = QPainterPath()
        for poly in (pa.points or []):
            if not poly:
                continue
            x0, y0 = poly[0]
            path.moveTo(x0*zoom+ox, y0*zoom+oy)
            for x, y in poly[1:]:
                path.lineTo(x*zoom+ox, y*zoom+oy)
            path.closeSubpath()
        item = QGraphicsPathItem()
        item.setPath(path)
        pen = QPen(qc(pa.stroke_color), pw(pa.border_width))
        if pa.dashes:
            pen.setDashPattern(qdash(pa.dashes, pa.border_width))
        item.setPen(pen)
        item.setBrush(QBrush(qc(pa.fill_color) if pa.fill_color
                             else QColor(0, 0, 0, 0)))
        if pa.opacity < 0.99:
            item.setOpacity(pa.opacity)
        return item

    elif at == 'freetext':
        from PySide6.QtWidgets import QGraphicsItemGroup, QGraphicsTextItem
        from PySide6.QtGui import QFont as _QFont
        r  = pa.fitz_rect
        x, y, w, h = r.x0*zoom+ox, r.y0*zoom+oy, r.width*zoom, r.height*zoom
        group = QGraphicsItemGroup()
        # 실제 모습에 가까운 미리보기: 점선 대신 옅은 실선 프레임만
        bg = QGraphicsRectItem(x, y, w, h)
        bg.setPen(QPen(QColor(130, 165, 235, 150), 1.0))
        bg.setBrush(QBrush(QColor(165, 195, 255, 26)))
        group.addToGroup(bg)
        if pa.text:
            txt = QGraphicsTextItem(pa.text)
            _ko = any(0xAC00 <= ord(c) <= 0xD7A3 for c in pa.text)
            f = _QFont('Malgun Gothic' if _ko else '')
            f.setPixelSize(max(8, int(pa.fontsize * zoom)))
            txt.setFont(f)
            tc = pa.text_color or (0.0, 0.0, 0.0)
            txt.setDefaultTextColor(QColor(int(tc[0]*255), int(tc[1]*255), int(tc[2]*255)))
            txt.setPos(x + 3, y + 1)
            txt.setTextWidth(max(1, w - 6))
            group.addToGroup(txt)
        rot_deg = getattr(pa, 'rotation_deg', 0.0)
        if rot_deg != 0.0:
            group.setTransformOriginPoint(x + w / 2, y + h / 2)
            group.setRotation(rot_deg)
        return group

    elif at == 'text':   # 스티키 메모 — 실제 종이 포스트잇처럼 그린다
        from PySide6.QtWidgets import (QGraphicsItemGroup, QGraphicsTextItem,
                                       QGraphicsPathItem)
        from PySide6.QtGui import QFont as _QFont, QLinearGradient
        from PySide6.QtWidgets import QGraphicsTextItem as _QGTextItem
        from PySide6.QtGui import QFont as _QFont0, QTextOption as _QTextOption
        r  = pa.fitz_rect
        # 메모 내용을 보여주는 읽기 쉬운 미리보기 (실제 PDF 어노테이션은 20×20 아이콘)
        # 임계값을 아이콘 크기로 낮춰, 사용자가 메모를 축소해도 크기가 튀지 않게 함
        legacy_note = getattr(pa, 'tool_name', '') == 'note' and r.width * zoom <= 36.0 and r.height * zoom <= 36.0
        w = 200.0 if legacy_note else max(48.0, r.width * zoom)
        x, y = r.x0*zoom+ox, r.y0*zoom+oy
        group = QGraphicsItemGroup()

        # ── 텍스트를 먼저 만들어 '필요한 높이'를 잰다 ──────────────────
        # 세로로 줄여도 글이 밖으로 튀어나가지 않도록, 상자 높이를 텍스트에
        # 필요한 만큼은 항상 확보한다 (가로 줄바꿈은 폭에 맞춰 자동).
        body_txt = None
        text_h = 0.0
        if pa.text:
            body_txt = _QGTextItem(pa.text)
            _fam = getattr(pa, 'fontname', '') or ''
            _ko = any(0xAC00 <= ord(c) <= 0xD7A3 for c in pa.text)
            if not _fam or _fam.lower() in ('helv', 'cour', 'times-roman') or len(_fam) <= 4:
                _fam = 'Malgun Gothic' if _ko else 'Segoe UI'
            _bf = _QFont0(_fam)
            _bf.setPixelSize(max(9, int(getattr(pa, 'fontsize', 12.0) * zoom)))
            body_txt.setFont(_bf)
            body_txt.setDefaultTextColor(QColor(64, 52, 12))
            body_txt.setTextWidth(max(1, w - 16))
            _opt = _QTextOption()
            _opt.setWrapMode(_QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            body_txt.document().setDefaultTextOption(_opt)
            text_h = body_txt.boundingRect().height()

        # 상자 높이 = 사용자가 정한 높이와 텍스트 필요 높이 중 큰 값
        if legacy_note:
            h = 78.0
        else:
            h = max(30.0, r.height * zoom, text_h + 12)
            # 텍스트 때문에 높이가 늘어났으면 실제 좌표(fitz_rect)도 맞춰
            # 히트/핸들 위치가 어긋나지 않게 함
            if abs(h - r.height * zoom) > 1.0:
                pa.fitz_rect = fitz.Rect(r.x0, r.y0,
                                         r.x0 + w / zoom, r.y0 + h / zoom)

        # 메모 색상 (fill_color가 지정되면 그 색, 아니면 기본 노랑)
        fc = getattr(pa, 'fill_color', None)
        if fc:
            base = QColor(int(fc[0]*255), int(fc[1]*255), int(fc[2]*255))
            top_col = base.lighter(112)
            bot_col = base.darker(103)
            edge_col = base.darker(120)
        else:
            top_col = QColor(255, 246, 158)
            bot_col = QColor(255, 224, 92)
            edge_col = QColor(214, 182, 84)

        # 본체: 오른쪽 아래 모서리가 접힌 종이 모양
        fold = max(8.0, min(20.0, w * 0.14, h * 0.32))
        body_path = QPainterPath()
        body_path.moveTo(x, y)
        body_path.lineTo(x + w, y)
        body_path.lineTo(x + w, y + h - fold)
        body_path.lineTo(x + w - fold, y + h)
        body_path.lineTo(x, y + h)
        body_path.closeSubpath()

        # 그림자 — 그래픽 이펙트(QGraphicsDropShadowEffect) 대신 직접 그린다.
        # 이펙트를 그룹에 걸면 이동/재렌더 중 크래시·렉이 생겨서 제거함.
        shadow_item = QGraphicsPathItem(body_path.translated(2.5, 3.5))
        shadow_item.setBrush(QBrush(QColor(60, 50, 15, 60)))
        shadow_item.setPen(QPen(Qt.PenStyle.NoPen))
        group.addToGroup(shadow_item)

        body = QGraphicsPathItem(body_path)
        grad = QLinearGradient(x, y, x, y + h)
        grad.setColorAt(0.0, top_col)
        grad.setColorAt(0.12, base if fc else QColor(255, 240, 130))
        grad.setColorAt(1.0, bot_col)
        body.setBrush(QBrush(grad))
        body.setPen(QPen(QColor(edge_col.red(), edge_col.green(), edge_col.blue(), 160), 1.0))
        group.addToGroup(body)

        # 상단 살짝 밝은 종이 결(라이트 밴드)
        band = QGraphicsRectItem(x + 1, y + 1, w - 2, max(4.0, h * 0.18))
        band.setBrush(QBrush(QColor(255, 255, 255, 55)))
        band.setPen(QPen(Qt.PenStyle.NoPen))
        group.addToGroup(band)

        # 접힌 모서리 (뒤로 넘어간 종이)
        fold_path = QPainterPath()
        fold_path.moveTo(x + w - fold, y + h)
        fold_path.lineTo(x + w, y + h - fold)
        fold_path.lineTo(x + w - fold, y + h - fold)
        fold_path.closeSubpath()
        fold_item = QGraphicsPathItem(fold_path)
        fgrad = QLinearGradient(x + w - fold, y + h - fold, x + w, y + h)
        fgrad.setColorAt(0.0, edge_col.lighter(112))
        fgrad.setColorAt(1.0, edge_col.darker(112))
        fold_item.setBrush(QBrush(fgrad))
        fold_item.setPen(QPen(QColor(edge_col.red(), edge_col.green(), edge_col.blue(), 130), 0.8))
        group.addToGroup(fold_item)

        if body_txt is not None:
            body_txt.setPos(x + 8, y + 6)
            group.addToGroup(body_txt)

        op = getattr(pa, 'opacity', 1.0)
        if op is not None and op < 0.99:
            group.setOpacity(max(0.1, float(op)))

        rot_deg = getattr(pa, 'rotation_deg', 0.0)
        if rot_deg != 0.0:
            group.setTransformOriginPoint(x + w / 2, y + h / 2)
            group.setRotation(rot_deg)
        return group

    elif at == 'index_tab':   # 인덱스 포스트잇 — 페이지 가장자리에 붙는 색 탭
        from PySide6.QtWidgets import (QGraphicsItemGroup, QGraphicsTextItem,
                                       QGraphicsPathItem, QGraphicsDropShadowEffect)
        from PySide6.QtGui import QFont as _QFont, QLinearGradient
        r = pa.fitz_rect
        w = max(20.0, r.width * zoom)
        h = max(14.0, r.height * zoom)
        x, y = r.x0*zoom+ox, r.y0*zoom+oy
        group = QGraphicsItemGroup()

        fc = pa.fill_color or (0.36, 0.68, 0.94)
        base = QColor(int(fc[0]*255), int(fc[1]*255), int(fc[2]*255))
        vertical = getattr(pa, 'text_align', 0) == 99   # 99 = 세로쓰기 표식

        # 둥근 탭 본체 (바깥쪽 모서리만 둥글게 하면 자연스럽지만 단순 라운드로)
        radius = min(6.0, h * 0.28, w * 0.28)
        body_path = QPainterPath()
        body_path.addRoundedRect(QRectF(x, y, w, h), radius, radius)
        body = QGraphicsPathItem(body_path)
        grad = QLinearGradient(x, y, x, y + h)
        grad.setColorAt(0.0, base.lighter(115))
        grad.setColorAt(1.0, base)
        body.setBrush(QBrush(grad))
        body.setPen(QPen(base.darker(120), 0.8))
        group.addToGroup(body)

        if pa.text:
            # 세로쓰기는 글자를 한 줄에 하나씩 쌓아 표현 (커밋 결과와 일치)
            label = '\n'.join(list(pa.text)) if vertical else pa.text
            txt = QGraphicsTextItem(label)
            _ko = any(0xAC00 <= ord(c) <= 0xD7A3 for c in pa.text)
            fam = getattr(pa, 'fontname', '') or ''
            if not fam or len(fam) <= 4 or fam.lower() in ('helv', 'cour', 'times-roman'):
                fam = 'Malgun Gothic' if _ko else 'Segoe UI'
            tf = _QFont(fam)
            tf.setBold(True)
            tf.setPixelSize(max(9, int(getattr(pa, 'fontsize', 11.0) * zoom)))
            txt.setFont(tf)
            from PySide6.QtGui import QTextOption as _QTextOption
            txt.document().setDefaultTextOption(_QTextOption(Qt.AlignmentFlag.AlignHCenter))
            txt.setTextWidth(max(1, w - 4))
            # 밝은 배경엔 검정, 어두운 배경엔 흰 글자
            lum = 0.299*base.red() + 0.587*base.green() + 0.114*base.blue()
            txt.setDefaultTextColor(QColor(20, 20, 20) if lum > 150 else QColor(255, 255, 255))
            txt.setPos(x + 2, y + max(0, (h - txt.boundingRect().height()) / 2))
            group.addToGroup(txt)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(8)
        shadow.setOffset(1.5, 2.0)
        shadow.setColor(QColor(40, 40, 40, 80))
        group.setGraphicsEffect(shadow)

        op = getattr(pa, 'opacity', 1.0)
        if op is not None and op < 0.99:
            group.setOpacity(max(0.1, float(op)))
        return group

    elif at == 'stamp':
        from PySide6.QtWidgets import QGraphicsItemGroup, QGraphicsTextItem
        from PySide6.QtGui import QFont as _QFont
        from tools.stamp_tool import STAMP_NAMES, format_stamp_label
        r = pa.fitz_rect
        x, y, w, h = r.x0*zoom+ox, r.y0*zoom+oy, r.width*zoom, r.height*zoom
        group = QGraphicsItemGroup()
        bg = QGraphicsRectItem(x, y, w, h)
        bg.setPen(QPen(QColor('#cc3300'), 2.0))
        bg.setBrush(QBrush(QColor(255, 220, 220, 140)))
        group.addToGroup(bg)
        label = STAMP_NAMES[pa.stamp_index] if 0 <= pa.stamp_index < len(STAMP_NAMES) else 'STAMP'
        txt = QGraphicsTextItem(format_stamp_label(label).upper())
        f = _QFont('Malgun Gothic')
        f.setBold(True)
        f.setPixelSize(max(9, int(min(h * 0.45, 18 * zoom))))
        txt.setFont(f)
        txt.setDefaultTextColor(QColor('#cc3300'))
        txt.setTextWidth(max(1, w - 8))
        text_option = txt.document().defaultTextOption()
        text_option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        txt.document().setDefaultTextOption(text_option)
        txt.setPos(x + 4, y + max(0, (h - txt.boundingRect().height()) / 2 - 2))
        group.addToGroup(txt)
        return group

    elif at == 'direct_text':
        from PySide6.QtWidgets import QGraphicsItemGroup, QGraphicsTextItem
        from PySide6.QtGui import QFont as _QFont
        r  = pa.fitz_rect
        x, y, w, h = r.x0*zoom+ox, r.y0*zoom+oy, r.width*zoom, r.height*zoom
        group = QGraphicsItemGroup()
        bg = QGraphicsRectItem(x, y, w, h)
        bg.setPen(QPen(QColor('#1a7fc1'), 1.5, Qt.PenStyle.DashLine))
        bg.setBrush(QBrush(QColor(255, 255, 200, 180)))
        group.addToGroup(bg)
        if pa.text:
            txt = QGraphicsTextItem(pa.text)
            _ko = any(0xAC00 <= ord(c) <= 0xD7A3 for c in pa.text)
            f = _QFont('Malgun Gothic' if _ko else '')
            f.setPixelSize(max(8, int(pa.fontsize * zoom)))
            txt.setFont(f)
            tc = pa.text_color or (0.0, 0.0, 0.0)
            txt.setDefaultTextColor(QColor(int(tc[0]*255), int(tc[1]*255), int(tc[2]*255)))
            txt.setPos(x + 3, y + 1)
            txt.setTextWidth(max(1, w - 6))
            group.addToGroup(txt)
        rot_deg = getattr(pa, 'rotation_deg', 0.0)
        if rot_deg != 0.0:
            group.setTransformOriginPoint(x + w / 2, y + h / 2)
            group.setRotation(rot_deg)
        return group

    elif at == 'ink_outlined':
        from PySide6.QtWidgets import QGraphicsItemGroup
        # 각 polygon을 채워진 닫힌 경로로 렌더링 (유선형 몸체 + 삼각 화살촉)
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)  # 겹침 영역도 빈틈 없이 채우기
        for poly in (pa.points or []):
            if not poly:
                continue
            path.moveTo(poly[0][0]*zoom+ox, poly[0][1]*zoom+oy)
            for x, y in poly[1:]:
                path.lineTo(x*zoom+ox, y*zoom+oy)
            path.closeSubpath()
        item = QGraphicsPathItem()
        item.setPath(path)
        color = qc(pa.stroke_color)
        item.setPen(QPen(color, 0.3))
        item.setBrush(QBrush(color))
        return item

    elif at == 'image_bytes':
        r = pa.fitz_rect
        image_bytes = getattr(pa, '_image_bytes', None)
        if image_bytes:
            try:
                pxm = QPixmap()
                pxm.loadFromData(image_bytes, 'PNG')
                if not pxm.isNull():
                    pxm = pxm.scaled(
                        max(1, int(r.width*zoom)), max(1, int(r.height*zoom)),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
                    it2 = QGraphicsPixmapItem(pxm)
                    it2.setPos(r.x0*zoom+ox, r.y0*zoom+oy)
                    return it2
            except Exception:
                swallowed()
        item = QGraphicsRectItem(r.x0*zoom+ox, r.y0*zoom+oy,
                                 r.width*zoom,  r.height*zoom)
        item.setPen(QPen(QColor(65, 105, 225), 1.5, Qt.PenStyle.DashLine))
        item.setBrush(QBrush(QColor(90, 140, 255, 45)))
        return item

    elif at == 'image':
        r   = pa.fitz_rect
        rot = getattr(pa, 'rotation_deg', 0.0)
        if pa.image_path:
            try:
                pxm = QPixmap(pa.image_path)
                if not pxm.isNull():
                    pw = max(1, int(r.width  * zoom))
                    ph = max(1, int(r.height * zoom))
                    pxm = pxm.scaled(pw, ph,
                                     Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
                    it2 = QGraphicsPixmapItem(pxm)
                    if rot != 0.0:
                        it2.setTransformOriginPoint(pw / 2.0, ph / 2.0)
                        it2.setRotation(rot)
                    it2.setPos(r.x0 * zoom + ox, r.y0 * zoom + oy)
                    return it2
            except Exception:
                swallowed()
        # 폴백: 점선 사각형
        item = QGraphicsRectItem(r.x0*zoom+ox, r.y0*zoom+oy,
                                 r.width*zoom,  r.height*zoom)
        item.setPen(QPen(QColor(100, 100, 255), 2, Qt.PenStyle.DashLine))
        return item

    return None


def _book_page_path(rect: QRectF, side: str) -> QPainterPath:
    """책보기 페이지의 위·아래 곡률과 바깥 모서리 경로."""
    x0, x1 = rect.left(), rect.right()
    y0, y1 = rect.top(), rect.bottom()
    curve = min(18.0, max(8.0, rect.height() * 0.018))
    path = QPainterPath()
    if side == 'left':
        path.moveTo(x1, y0 + curve * 0.7)
        path.cubicTo(x1 - rect.width() * 0.18, y0 - 2.0,
                     x0 + rect.width() * 0.15, y0 - 1.0,
                     x0 + curve, y0 + curve)
        path.lineTo(x0 + curve * 0.55, y1 - curve)
        path.cubicTo(x0 + rect.width() * 0.16, y1 + 2.0,
                     x1 - rect.width() * 0.2, y1 + 3.0,
                     x1, y1 - curve * 0.65)
    else:
        path.moveTo(x0, y0 + curve * 0.7)
        path.cubicTo(x0 + rect.width() * 0.18, y0 - 2.0,
                     x1 - rect.width() * 0.15, y0 - 1.0,
                     x1 - curve, y0 + curve)
        path.lineTo(x1 - curve * 0.55, y1 - curve)
        path.cubicTo(x1 - rect.width() * 0.16, y1 + 2.0,
                     x0 + rect.width() * 0.2, y1 + 3.0,
                     x0, y1 - curve * 0.65)
    path.closeSubpath()
    return path


class _BookPagePixmapItem(QGraphicsPixmapItem):
    def __init__(self, pixmap: QPixmap, side: str):
        super().__init__(pixmap)
        self._book_side = side

    def paint(self, painter: QPainter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipPath(_book_page_path(self.boundingRect(), self._book_side))
        super().paint(painter, option, widget)
        painter.restore()


class PdfCanvasView(QGraphicsView):
    page_changed            = Signal(int)
    pending_count_changed   = Signal(int)   # 미확정 어노테이션 개수 변경
    annot_committed         = Signal()      # 어노테이션 자동 커밋 완료
    display_zoom_changed    = Signal(float) # 표시 배율 변경 (1.0 = 100%)
    # 우클릭 컨텍스트 메뉴 요청: (씬 좌표, 화면 좌표)
    context_menu_requested  = Signal(object, object)
    # 영역 캡처 완료
    region_captured         = Signal(QPixmap)
    status_message          = Signal(str)   # 상태 표시줄 안내/경고

    def __init__(self, doc, renderer, parent=None):
        super().__init__(parent)
        self._doc      = doc
        self._renderer = renderer
        self._zoom     = 1.0        # 뷰 표시 배율 (1.0 = BASE_RENDER_ZOOM 원본 크기)
        self._cur_page = 0
        self._tool: BaseTool = SelectTool()
        self._page_item: QGraphicsPixmapItem | None = None
        self._page_item_r: QGraphicsPixmapItem | None = None  # 우측 (양면)
        self._double_mode = False
        self._right_page: int = 0   # 양면 모드의 오른쪽 페이지 (-1 = 빈 페이지)
        self._scroll_mode = False
        self._segment_mode = False
        self._segment_count = 1
        self._segment_index = 0
        self._inline_ed: _InlineEdit | None = None   # 인라인 텍스트 에디터
        # ── 영역 캡처 모드 ─────────────────────────────────────
        self._region_capture_mode = False
        self._region_rb_start: QPoint | None = None  # 뷰포트 좌표
        self._region_rubber_band = None              # QRubberBand (지연 생성)
        self._pending    = PendingLayer()            # 미확정 어노테이션 레이어
        self._page_offsets: dict[int, QPointF] = {} # 씬 내 각 페이지 좌상단 위치
        self._page_render_scale: dict[int, float] = {}  # 페이지별 렌더 스케일 보정
        self._search_hit_items: list = []           # 검색 결과 하이라이트 아이템

        scene = PdfCanvasScene(self)
        self.setScene(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # 배경색을 팔레트에서 읽어 명시적으로 설정 (마스크 색상과 일치시킴)
        from PySide6.QtGui import QPalette, QBrush as _QBrush
        _bg = self.palette().color(QPalette.ColorRole.Window)
        self._default_bg = _bg
        self._book_bg = QColor('#e7dcc5')
        self._book_texture_strength = 18
        self.setBackgroundBrush(_QBrush(_bg))

        # 키보드 이벤트를 받기 위해 강한 포커스 정책 설정
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 마우스 추적 활성화 (버튼 미클릭 상태에서도 hover 이벤트 발생)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        # 인라인 텍스트 에디터 (뷰포트 자식 위젯, 처음엔 숨김)
        self._inline_ed = _InlineEdit(self.viewport())
        self._inline_ed.hide()
        # 여러 줄(블록) 편집기
        self._inline_block_ed = _InlineBlockEdit(self.viewport())
        self._inline_block_ed.hide()
        # 본문 편집 모드 (툴바 버튼으로 토글) — 켜면 클릭한 문단 전체를 편집
        self._text_edit_mode = False
        self._edit_locked = False   # 권한 제한 문서에서 본문 편집 잠금
        self._para_rect_cache: dict = {}   # 페이지별 문단 사각형 캐시 (호버용)
        self._block_rows: list | None = None   # 편집 중 문단의 시각적 행 기하
        self._covered_bands: dict = {}         # 본문 편집으로 흰 덮개를 씌운 영역
        self._reflow_mode: bool = False        # 캔바식 '문단 다시 흘리기'
        self._edit_hover_item = None

        # 글꼴 선택 바 (인라인 에디터 위에 표시)
        self._inline_font_bar = self._make_inline_font_bar()
        self._inline_font_bar.hide()
        self._inline_ed._companion = self._inline_font_bar
        self._inline_block_ed._companion = self._inline_font_bar

        # 롤오버 사전
        self._dict_popup: object | None = None
        self._dict_hover_pos: QPointF | None = None
        self._dict_hover_gpos: QPoint | None = None
        self._dict_last_word: str = ''
        self._dict_drag_anchor: QPointF | None = None
        self._dict_selected_text: str = ''
        self._dict_timer = QTimer(self)
        self._dict_timer.setSingleShot(True)
        self._dict_timer.timeout.connect(self._on_dict_hover)
        self._hq_timer = QTimer(self)
        self._hq_timer.setSingleShot(True)
        self._hq_timer.timeout.connect(self._refresh_visible_page_quality)
        self._hq_text_page_cache: dict[int, bool] = {}
        self._scroll_page_items: dict[int, QGraphicsPixmapItem] = {}
        self._scroll_loaded: set[int] = set()   # 풀사이즈 픽스맵 보유 페이지
        self._suppress_scroll_tracking = False
        # 스크롤 위치 변경 시 HQ 타이머 재시작 (정지 후 선명하게)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_bar_moved)
        self.horizontalScrollBar().valueChanged.connect(self._on_scroll_bar_moved)
        self._settings = None
        self._book_mode_visual = False
        self._book_display_crop_norm: tuple[float, float, float, float] | None = None
        self._book_anim_group = None
        self._book_anim_overlay = None
        self._book_page_clips: dict[int, fitz.Rect | None] = {}  # 페이지별 자동 감지 마진 크롭

        # 세로 스크롤 백그라운드 렌더 워커 + 배치 업데이트
        self._scroll_worker: _ScrollRenderWorker | None = None
        self._scroll_pending_updates: dict[int, QImage] = {}
        self._scroll_batch_timer = QTimer(self)
        self._scroll_batch_timer.setInterval(40)   # ~25fps 배치 플러시
        self._scroll_batch_timer.timeout.connect(self._flush_scroll_page_updates)
        # 스크롤 멈춘 후 200ms 뒤에 윈도우 갱신 (디바운스)
        self._scroll_window_timer = QTimer(self)
        self._scroll_window_timer.setSingleShot(True)
        self._scroll_window_timer.setInterval(200)
        self._scroll_window_timer.timeout.connect(self._prioritize_visible_scroll_pages)

        # 줌 HUD (책보기/분할보기 몰입 모드에서 우하단에 표시)
        self._zoom_hud = self._make_zoom_hud()
        self._zoom_hud.hide()
        # HUD 자동 숨김 타이머 (4초 후 숨김)
        self._hud_hide_timer = QTimer(self)
        self._hud_hide_timer.setSingleShot(True)
        self._hud_hide_timer.setInterval(4000)
        self._hud_hide_timer.timeout.connect(lambda: self._zoom_hud.hide())

        # 문서 교체 직후 페이지 상태 초기화 — MainWindow의 show_page(0)보다
        # 먼저 실행돼야 이전 문서의 페이지 번호가 새(더 짧은) 문서에 남아
        # hover 툴팁 등에서 IndexError가 나는 것을 막는다.
        # (canvas가 MainWindow보다 먼저 connect하므로 항상 먼저 호출됨)
        self._doc.opened.connect(self._reset_page_state_on_open)
        # 문서가 닫히면(탭 닫기 등) 화면을 즉시 비운다
        self._doc.closed.connect(self._on_doc_closed)

        # 인덱스 포스트잇(책갈피) 사이드 탭 바 — 모든 페이지에서 항상 표시.
        # 책보기/양면보기에서는 좌우 두 바로 책의 양 가장자리에 붙는다.
        from ui.index_tab_bar import IndexTabBar, IndexFilterButton
        self._index_filter = 'all'    # 'all' | 'mine' | 'toc'
        self._index_tab_bar = IndexTabBar(self, side='right')
        self._index_tab_bar_left = IndexTabBar(self, side='left')
        self._index_filter_btn = IndexFilterButton(self)
        self._index_filter_btn.clicked_cycle.connect(self._cycle_index_filter)
        self._index_filter_btn.move_toc_side.connect(
            lambda side: self._bulk_move_index('toc', side))
        self._index_filter_btn.move_mine_side.connect(
            lambda side: self._bulk_move_index('mine', side))
        for _b in (self._index_tab_bar, self._index_tab_bar_left):
            _b.navigate.connect(self.jump_to_page)
            _b.edit_requested.connect(self._edit_index_tab)
            _b.delete_requested.connect(self._delete_index_tab)
            _b.move_y_requested.connect(
                lambda idx, y: self._doc.update_index_tab(idx, y=y))
            _b.side_change_requested.connect(
                lambda idx, side: self._doc.update_index_tab(idx, side=side))
        self._doc.opened.connect(lambda *_: self._refresh_index_bars())
        self._doc.closed.connect(self._clear_index_bars)
        self._doc.index_tabs_changed.connect(self._refresh_index_bars)
        self.page_changed.connect(self._on_page_changed_index_bars)

        # 하단 페이지 이동 슬라이더(평소 숨김, hover 시 노출)
        from ui.page_slide_bar import PageSlideBar
        self._page_slider = PageSlideBar(self)
        self._page_slider.navigate.connect(self.jump_to_page)
        self._doc.opened.connect(lambda *_: self._refresh_page_slider())
        self._doc.closed.connect(self._page_slider.hide)
        self.page_changed.connect(
            lambda p: self._page_slider.set_current_page(p))

        # 초기 도구 활성화
        self._tool.activate(self)

    def _refresh_page_slider(self):
        sl = getattr(self, '_page_slider', None)
        if sl is None:
            return
        if self._doc.is_open:
            sl.set_page_count(self._doc.page_count())
            sl.set_current_page(self._cur_page)
        else:
            sl.hide()

    # ── 인덱스 포스트잇(책갈피) ──────────────────────────────────────
    def jump_to_page(self, page: int):
        """인덱스 탭 클릭 시 현재 보기 모드에 맞춰 해당 페이지로 이동."""
        if not self._doc.is_open:
            return
        page = max(0, min(page, self._doc.page_count() - 1))
        if self._scroll_mode:
            self.goto_in_scroll(page)
        elif self._double_mode:
            self.show_double(page if page % 2 == 0 else page - 1)
        elif self._segment_mode:
            self.show_segment(page, 0, self._segment_count or 2)
        else:
            self.show_page(page)
        self.setFocus()

    def refresh_index_tabs(self):
        self._refresh_index_bars()

    def _clear_index_bars(self):
        self._index_tab_bar.set_tabs([])
        self._index_tab_bar_left.set_tabs([])

    def _on_page_changed_index_bars(self, page: int):
        self._index_tab_bar.set_current_page(page)
        self._index_tab_bar_left.set_current_page(page)

    def _bulk_move_index(self, origin: str, side: str):
        """목차/내 인덱스 탭을 한꺼번에 왼쪽·오른쪽으로 옮긴다."""
        if not self._doc.is_open:
            return
        self._doc.set_side_bulk(side, origin=origin)
        who = '문서 목차' if origin == 'toc' else '내 인덱스'
        where = '왼쪽' if side == 'left' else '오른쪽'
        self.status_message.emit(f'{who} 인덱스를 모두 {where}으로 옮겼습니다.')

    def _cycle_index_filter(self):
        """인덱스 표시 필터 순환: 전체 → 내 인덱스만 → 목차만 → 숨김 → 전체."""
        order = ['all', 'mine', 'toc', 'off']
        cur = order.index(getattr(self, '_index_filter', 'all')) \
            if getattr(self, '_index_filter', 'all') in order else 0
        self._index_filter = order[(cur + 1) % len(order)]
        self._refresh_index_bars()
        names = {'all': '전체 인덱스', 'mine': '내 인덱스만',
                 'toc': '문서 목차만', 'off': '숨김'}
        self.status_message.emit(f'인덱스 표시: {names[self._index_filter]}')

    def _refresh_index_bars(self):
        """문서의 책갈피를 각 탭의 side(왼/오른)에 따라 좌우 바에 분배한다.
        모든 보기 모드(단면/스크롤/책보기)에서 양쪽 가장자리에 붙일 수 있다.
        표시 필터(전체/내 인덱스/목차)에 따라 걸러서 보여 준다."""
        tabs = self._doc.get_index_tabs() if self._doc.is_open else []
        flt = getattr(self, '_index_filter', 'all')
        if flt == 'off':
            tabs = []
        elif flt == 'mine':
            tabs = [t for t in tabs if t.get('origin') == 'mine']
        elif flt == 'toc':
            tabs = [t for t in tabs if t.get('origin') != 'mine']
        left = [t for t in tabs if t.get('side') == 'left']
        right = [t for t in tabs if t.get('side') != 'left']
        self._index_tab_bar_left.set_tabs(left)
        self._index_tab_bar.set_tabs(right)
        self._index_tab_bar.set_current_page(self._cur_page)
        self._index_tab_bar_left.set_current_page(self._cur_page)
        # 필터 버튼: 문서가 열려 있으면 항상 표시(헷갈리지 않게).
        btn = getattr(self, '_index_filter_btn', None)
        if btn is not None:
            if self._doc.is_open:
                btn.set_mode(flt)
                btn.reposition()
                btn.show(); btn.raise_()
            else:
                btn.hide()

    def _edit_index_tab(self, tab_index: int):
        tabs = self._doc.get_index_tabs()
        tab = next((t for t in tabs if t['idx'] == tab_index), None)
        if tab is None:
            return
        from tools.index_tab_tool import _IndexTabDialog
        dlg = _IndexTabDialog(self, initial_text=tab['label'],
                              initial_color=tab.get('color'),
                              initial_side=tab.get('side', 'right'))
        if dlg.exec():
            label = dlg.label_text()
            if not label:
                self._doc.remove_index_tab(tab_index)
            else:
                self._doc.update_index_tab(tab_index, label=label,
                                           color=dlg.color(), side=dlg.side())

    def _delete_index_tab(self, tab_index: int):
        self._doc.remove_index_tab(tab_index)

    def page_edge_in_viewport(self, side: str) -> float | None:
        """페이지(문서)의 바깥 가장자리를 뷰포트 x좌표로 반환.
        side='right'|'left'. 책보기/양면보기는 스프레드의 바깥 가장자리를 쓴다."""
        if not self._doc.is_open:
            return None
        try:
            two_sided = self._double_mode or self._book_mode_visual
            if two_sided and self._page_item is not None:
                lrect = self._page_item.mapRectToScene(self._page_item.boundingRect())
                if side == 'left':
                    return float(self.mapFromScene(lrect.topLeft()).x())
                # right: 오른쪽 페이지가 있으면 그 오른쪽 끝, 없으면 왼쪽 페이지 오른쪽 끝
                if self._page_item_r is not None:
                    rrect = self._page_item_r.mapRectToScene(self._page_item_r.boundingRect())
                    return float(self.mapFromScene(rrect.topRight()).x())
                return float(self.mapFromScene(lrect.topRight()).x())
            r = self._current_page_scene_rect()
            if r is None or r.isNull():
                return None
            if side == 'left':
                return float(self.mapFromScene(r.topLeft()).x())
            return float(self.mapFromScene(r.topRight()).x())
        except Exception:
            return None

    def page_vspan_in_viewport(self, side: str = 'right'):
        """현재 페이지(스프레드)의 세로 범위를 뷰포트 y좌표 (top, bottom) 로 반환.
        인덱스 바를 페이지 높이에 맞추는 데 쓴다. 알 수 없으면 None."""
        if not self._doc.is_open:
            return None
        try:
            two_sided = self._double_mode or self._book_mode_visual
            item = None
            if two_sided:
                if side == 'left':
                    item = self._page_item
                else:
                    item = self._page_item_r or self._page_item
            if item is not None:
                sr = item.mapRectToScene(item.boundingRect())
            else:
                sr = self._current_page_scene_rect()
            if sr is None or sr.isNull():
                return None
            top = float(self.mapFromScene(sr.topLeft()).y())
            bot = float(self.mapFromScene(sr.bottomLeft()).y())
            if bot <= top:
                return None
            return (top, bot)
        except Exception:
            return None

    def _reposition_index_bar(self):
        for attr in ('_index_tab_bar', '_index_tab_bar_left'):
            bar = getattr(self, attr, None)
            if bar is not None and bar.isVisible():
                bar._reposition()
        btn = getattr(self, '_index_filter_btn', None)
        if btn is not None and btn.isVisible():
            btn.reposition()
        sl = getattr(self, '_page_slider', None)
        if sl is not None and sl.isVisible():
            sl.reposition()

    def _reset_page_state_on_open(self, _path: str = ''):
        """새 문서가 열리면 이전 문서 기준의 페이지 상태를 모두 리셋한다."""
        self._cur_page = 0
        self._right_page = 0
        self._segment_index = 0
        self._hq_text_page_cache.clear()
        self._book_page_clips.clear()
        self._para_rect_cache.clear()
        self._covered_bands.clear()    # 새 문서 — 이전 문서의 덮개 기록 폐기
        self._edit_hover_item = None   # scene 이 비워지며 아이템도 사라짐

    def _on_doc_closed(self):
        """문서가 닫히면 렌더링된 페이지·미확정 어노테이션을 즉시 지운다.

        탭 닫기(마지막 탭은 문서만 닫힘) 시 이전 페이지가 화면에 그대로
        남아 있던 문제 방지.
        """
        self._stop_scroll_worker()
        self._pending.remove_all_from_scene_and_clear()
        self._clear_scene()
        self._scroll_page_items.clear()
        self.scene().setSceneRect(QRectF())
        self._reset_page_state_on_open()
        self._renderer.invalidate_all()
        self.notify_pending_changed()

    def set_settings(self, settings) -> None:
        self._settings = settings
        self._book_bg = QColor(getattr(settings, 'book_bg_color', '#e7dcc5'))
        self._book_texture_strength = int(getattr(settings, 'book_texture_strength', 18))
        if self._dict_popup is not None and hasattr(self._dict_popup, '_settings'):
            self._dict_popup._settings = settings
            if hasattr(self._dict_popup, '_apply_settings_font'):
                self._dict_popup._apply_settings_font()
        if self._book_mode_visual:
            from PySide6.QtGui import QBrush as _QBrush
            self.setBackgroundBrush(_QBrush(self._book_bg))
            if self._doc.is_open:
                self.refresh_page()


    # ── 글꼴 선택 바 생성 ────────────────────────────────────────────
    # ── 줌 HUD ──────────────────────────────────────────────────────
    def _make_zoom_hud(self) -> QWidget:
        """우하단 반투명 줌 컨트롤 위젯 생성."""
        hud = QWidget(self.viewport())
        hud.setObjectName('zoom_hud')
        hud.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        hud.setStyleSheet("""
            QWidget#zoom_hud {
                background: rgba(18, 18, 18, 215);
                border-radius: 26px;
                border: 1px solid rgba(255, 255, 255, 14);
            }
            QToolButton {
                background: transparent;
                color: rgba(255, 255, 255, 230);
                font-size: 22px;
                font-weight: 300;
                border: none;
                padding: 0 14px;
                min-width: 42px;
                min-height: 48px;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 28);
                border-radius: 22px;
            }
            QToolButton:pressed {
                background: rgba(255, 255, 255, 50);
            }
            QLabel#zoom_label {
                color: rgba(255, 255, 255, 210);
                font-size: 15px;
                font-weight: 600;
                min-width: 60px;
                padding: 0 10px;
                border-left:  1px solid rgba(255, 255, 255, 20);
                border-right: 1px solid rgba(255, 255, 255, 20);
            }
        """)
        layout = QHBoxLayout(hud)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(0)

        btn_out = QToolButton()
        # 주의: U+2212 '−' 대신 ASCII '-' 사용 — 기본 폰트 폴백에 없는
        # 글리프는 첫 렌더링 시 전체 폰트 DB 스캔(~3초)을 유발한다.
        btn_out.setText('-')
        btn_out.setToolTip('축소 (-)')
        btn_out.clicked.connect(lambda: self._zoom_step(-1))

        self._zoom_hud_label = QLabel('100%')
        self._zoom_hud_label.setObjectName('zoom_label')
        self._zoom_hud_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_hud_label.setToolTip('클릭: 화면에 맞춤')
        self._zoom_hud_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zoom_hud_label.mousePressEvent = lambda e: self.fit_width()

        btn_in = QToolButton()
        btn_in.setText('+')
        btn_in.setToolTip('확대 (+)')
        btn_in.clicked.connect(lambda: self._zoom_step(1))

        layout.addWidget(btn_out)
        layout.addWidget(self._zoom_hud_label)
        layout.addWidget(btn_in)

        hud.adjustSize()
        return hud

    def _show_hud_timed(self):
        """HUD를 표시하고 자동 숨김 타이머를 재시작한다."""
        if not self._book_mode_visual:
            return
        if not self._zoom_hud.isVisible():
            self._zoom_hud.show()
            self._zoom_hud.raise_()
        self._hud_hide_timer.start()

    def _zoom_step(self, direction: int):
        """HUD/단축키용 줌 단계 변경."""
        self._show_hud_timed()
        factor = 1.20 if direction > 0 else 1 / 1.20

        if self._book_mode_visual and self._page_item is not None:
            # 책보기: 페이지 스프레드가 화면을 꽉 채우는 줌을 최대치로 제한 후 중앙 정렬
            page_bounds = self._page_item.mapRectToScene(self._page_item.boundingRect())
            if self._page_item_r is not None:
                page_bounds = page_bounds.united(
                    self._page_item_r.mapRectToScene(self._page_item_r.boundingRect()))
            pw, ph = max(1.0, page_bounds.width()), max(1.0, page_bounds.height())
            vw = max(1, self.viewport().width() - 4)
            vh = max(1, self.viewport().height() - 4)
            max_zoom = min(vw / pw, vh / ph)          # 이보다 크면 스프레드가 화면 밖으로 나감
            new_zoom = max(0.05, min(max_zoom, self._zoom * factor))
            self._zoom = new_zoom
            self._apply_transform()
            self.centerOn(page_bounds.center())
            self._schedule_hq_refresh()
            return

        # 일반 모드: 현재 뷰포트 중심을 기준으로 줌
        vp_center = self.viewport().rect().center()
        scene_center = self.mapToScene(vp_center)
        new_zoom = max(0.05, min(10.0, self._zoom * factor))
        self._zoom = new_zoom
        self._apply_transform()
        self.centerOn(scene_center)
        self._schedule_hq_refresh()

    def _reposition_zoom_hud(self):
        """뷰포트 크기에 맞춰 HUD 위치를 우하단으로 조정."""
        if not hasattr(self, '_zoom_hud'):
            return
        hud = self._zoom_hud
        hud.adjustSize()
        vp = self.viewport()
        margin = 16
        hud.move(vp.width() - hud.width() - margin,
                 vp.height() - hud.height() - margin)

    def _update_zoom_hud_label(self):
        """현재 줌 배율을 HUD 라벨에 반영."""
        if hasattr(self, '_zoom_hud_label'):
            self._zoom_hud_label.setText(f'{int(self._zoom * 100)}%')

    def set_book_view_enabled(self, enabled: bool):
        self._book_mode_visual = bool(enabled)
        # 책보기(전체화면)에서는 인덱스 바를 가장자리 숨김(peek)으로 — 본문을
        # 가리지 않게. 마우스를 대면 쓱 나온다. 다른 모드는 항상 표시.
        for _attr in ('_index_tab_bar', '_index_tab_bar_left'):
            _b = getattr(self, _attr, None)
            if _b is not None:
                _b.set_peek(bool(enabled))
        from PySide6.QtGui import QBrush as _QBrush
        self.setBackgroundBrush(_QBrush(self._book_bg if enabled else self._default_bg))
        if self.scene() is not None:
            self.viewport().update()
        if enabled:
            self._book_page_clips.clear()   # 진입 시 캐시 초기화 (패딩 설정 반영)
            self._zoom_hud.show()
            self._zoom_hud.raise_()
            QTimer.singleShot(0, self._reposition_zoom_hud)
            self._hud_hide_timer.start()    # 4초 후 자동 숨김
        else:
            self._zoom_hud.hide()
            self._book_page_clips.clear()   # 책보기 종료 시 마진 캐시 초기화

    def set_book_display_crop(self, norm_rect: tuple[float, float, float, float] | None):
        self._book_display_crop_norm = norm_rect
        if self._doc.is_open and self._book_mode_visual:
            self.refresh_page()

    def _book_display_clip_for_page(self, index: int) -> fitz.Rect | None:
        if not self._book_display_crop_norm:
            return None
        try:
            page_rect = self._doc.fitz_page(index).rect
        except Exception:
            return None
        x0n, y0n, x1n, y1n = self._book_display_crop_norm
        x0 = page_rect.x0 + page_rect.width * x0n
        y0 = page_rect.y0 + page_rect.height * y0n
        x1 = page_rect.x0 + page_rect.width * x1n
        y1 = page_rect.y0 + page_rect.height * y1n
        x0 = min(max(x0, page_rect.x0), page_rect.x1)
        x1 = min(max(x1, page_rect.x0), page_rect.x1)
        y0 = min(max(y0, page_rect.y0), page_rect.y1)
        y1 = min(max(y1, page_rect.y0), page_rect.y1)
        if x1 - x0 < 10 or y1 - y0 < 10:
            return None
        return fitz.Rect(x0, y0, x1, y1)

    def _tighten_book_display_clip(self, index: int, clip: fitz.Rect) -> fitz.Rect:
        try:
            page = self._doc.fitz_page(index)
            words = page.get_text('words')
            page_rect = page.rect
        except Exception:
            return clip

        all_boxes: list[tuple[float, float, float, float]] = []
        core_boxes: list[tuple[float, float, float, float]] = []
        top_band = clip.y0 + clip.height * 0.18
        bottom_band = clip.y1 - clip.height * 0.10
        for word in words:
            try:
                wx0, wy0, wx1, wy1, token = word[:5]
            except Exception:
                continue
            token = str(token).strip()
            if not token:
                continue
            if wx1 <= clip.x0 or wx0 >= clip.x1 or wy1 <= clip.y0 or wy0 >= clip.y1:
                continue
            box = (float(wx0), float(wy0), float(wx1), float(wy1))
            all_boxes.append(box)
            width = float(wx1) - float(wx0)
            in_header_footer = float(wy0) <= top_band or float(wy1) >= bottom_band
            if in_header_footer and width < clip.width * 0.55:
                continue
            core_boxes.append(box)

        boxes = core_boxes if len(core_boxes) >= 12 else all_boxes
        if not boxes:
            return clip

        pad_x = page_rect.width * 0.012
        pad_top = page_rect.height * 0.008
        pad_bottom = page_rect.height * 0.014
        new_x0 = max(clip.x0, min(b[0] for b in boxes) - pad_x)
        new_y0 = max(clip.y0, min(b[1] for b in boxes) - pad_top)
        new_x1 = min(clip.x1, max(b[2] for b in boxes) + pad_x)
        new_y1 = min(clip.y1, max(b[3] for b in boxes) + pad_bottom)
        if new_x1 - new_x0 < 10 or new_y1 - new_y0 < 10:
            return clip
        return fitz.Rect(new_x0, new_y0, new_x1, new_y1)

    def _start_book_turn_animation(self, forward: bool = True):
        return
    # ── 책 마진 자동 감지 ─────────────────────────────────────────────
    def _detect_page_content_rect(self, index: int) -> 'fitz.Rect | None':
        """저해상도 픽셀 스캔으로 페이지 실제 콘텐츠 영역을 감지한다.

        ⚠ get_text() 를 절대 사용하지 않는다.
        일부 한글 CID 폰트 PDF 에서 page.get_text() 가 MuPDF 내부 상태를
        변경하여 이후 get_pixmap() 결과를 깨뜨리는 버그가 있기 때문이다.
        저해상도(zoom 0.12) 렌더링으로 비흰색 픽셀 범위를 구하면
        텍스트·이미지를 모두 포함하면서도 해당 버그를 완전히 회피한다.
        """
        try:
            page = self._doc.fitz_page(index)
            pr = page.rect

            # 아주 작은 해상도로만 렌더 — 속도/메모리 최소화
            ZOOM = 0.12
            mat = fitz.Matrix(ZOOM, ZOOM)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            w, h = pix.width, pix.height
            if w <= 0 or h <= 0:
                return None

            data   = bytes(pix.samples)   # RGB bytes (stride=w*3)
            stride = pix.stride           # 실제 stride (패딩 있을 수 있음)
            WHITE  = 245                  # 흰 배경 밝기 임계값

            top_px  = h;  bottom_px = -1
            left_px = w;  right_px  = -1

            for y in range(h):
                row = y * stride
                for x in range(w):
                    base = row + x * 3
                    if (data[base] < WHITE or
                            data[base + 1] < WHITE or
                            data[base + 2] < WHITE):
                        if y < top_px:    top_px    = y
                        if y > bottom_px: bottom_px = y
                        if x < left_px:   left_px   = x
                        if x > right_px:  right_px  = x

            del pix  # fitz Pixmap 즉시 해제

            if bottom_px < 0 or right_px < 0:   # 콘텐츠 없음
                return None

            # 픽셀 좌표 → PDF 좌표
            sx = pr.width  / w
            sy = pr.height / h
            PAD_X = 36.0   # 좌우 여유 패딩 (pt)
            PAD_Y = 28.0   # 상하 여유 패딩 (pt)
            x0 = max(pr.x0, pr.x0 + left_px   * sx - PAD_X)
            y0 = max(pr.y0, pr.y0 + top_px    * sy - PAD_Y)
            x1 = min(pr.x1, pr.x0 + right_px  * sx + PAD_X)
            y1 = min(pr.y1, pr.y0 + bottom_px * sy + PAD_Y)

            if x1 - x0 < 50 or y1 - y0 < 50:
                return None
            return fitz.Rect(x0, y0, x1, y1)
        except Exception:
            return None

    def _ensure_book_clips(self, *indices: int):
        """아직 감지 안 된 페이지의 마진 크롭을 캐시에 저장."""
        for idx in indices:
            if idx >= 0 and idx not in self._book_page_clips:
                self._book_page_clips[idx] = self._detect_page_content_rect(idx)

    def _effective_book_clip(self, index: int) -> 'fitz.Rect | None':
        """책보기 모드에서 index 페이지에 적용할 크롭 rect 반환."""
        if index in self._book_page_clips:
            return self._book_page_clips[index]
        return self._book_display_clip_for_page(index)

    def _crop_img_for_book(self, img: 'QImage', index: int,
                           render_zoom: float, clip: 'fitz.Rect') -> 'QImage':
        """QImage를 fitz 좌표 clip으로 잘라낸다. 실패 시 원본 반환."""
        try:
            page_rect = self._doc.fitz_page(index).rect
            px0 = max(0, int((clip.x0 - page_rect.x0) * render_zoom))
            py0 = max(0, int((clip.y0 - page_rect.y0) * render_zoom))
            pw  = max(1, min(int(clip.width  * render_zoom), img.width()  - px0))
            ph  = max(1, min(int(clip.height * render_zoom), img.height() - py0))
            return img.copy(px0, py0, pw, ph)
        except Exception:
            return img

    def _add_book_frame(self, rect: QRectF, side: str):
        cover_rect = rect.adjusted(-5.0 if side == 'left' else 0.0, 3.0,
                                   5.0 if side == 'right' else 0.0, 9.0)
        cover = QGraphicsPathItem(_book_page_path(cover_rect, side))
        cover.setPen(QPen(QColor(54, 45, 36, 145), 1.6))
        cover.setBrush(QColor(58, 49, 39, 92))
        cover.setZValue(-0.35)
        self.scene().addItem(cover)

        frame = QGraphicsPathItem(_book_page_path(rect, side))
        frame.setPen(QPen(QColor(112, 91, 64, 118), 1.25))
        frame.setBrush(Qt.BrushStyle.NoBrush)
        frame.setZValue(0.5)
        self.scene().addItem(frame)

    def _add_book_spine(self, left_rect: QRectF, right_rect: QRectF):
        gutter_x = (left_rect.right() + right_rect.left()) / 2.0
        top = min(left_rect.top(), right_rect.top())
        height = max(left_rect.height(), right_rect.height())
        half_width = min(72.0, max(36.0, left_rect.width() * 0.13))
        grad = QLinearGradient(gutter_x - half_width, 0, gutter_x + half_width, 0)
        grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.34, QColor(92, 72, 48, 26))
        grad.setColorAt(0.47, QColor(64, 49, 33, 76))
        grad.setColorAt(0.5, QColor(42, 33, 24, 116))
        grad.setColorAt(0.53, QColor(255, 255, 255, 46))
        grad.setColorAt(0.66, QColor(92, 72, 48, 25))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        spine = QGraphicsRectItem(gutter_x - half_width, top, half_width * 2, height)
        spine.setPen(QPen(Qt.PenStyle.NoPen))
        spine.setBrush(QBrush(grad))
        spine.setZValue(0.42)
        self.scene().addItem(spine)

        fold_path = QPainterPath()
        fold_path.moveTo(gutter_x, top + 7.0)
        fold_path.cubicTo(gutter_x - 3.0, top + height * 0.3,
                          gutter_x + 3.0, top + height * 0.7,
                          gutter_x, top + height - 7.0)
        fold = QGraphicsPathItem(fold_path)
        fold.setPen(QPen(QColor(66, 50, 34, 112), 1.15))
        fold.setBrush(Qt.BrushStyle.NoBrush)
        fold.setZValue(0.53)
        self.scene().addItem(fold)

    def _add_book_texture(self, rect: QRectF, side: str):
        strength = max(0, min(40, int(self._book_texture_strength)))
        if strength <= 0:
            return
        base_alpha = 8 + int(strength * 0.8)
        gloss_hi = 10 + int(strength * 0.9)
        gloss_lo = max(4, int(strength * 0.35))
        edge_alpha = 8 + int(strength * 0.6)

        page_path = _book_page_path(rect, side)
        base = QGraphicsPathItem(page_path)
        base.setPen(QPen(Qt.PenStyle.NoPen))
        base.setBrush(QColor(255, 250, 238, base_alpha))
        base.setZValue(0.15)
        self.scene().addItem(base)

        gloss = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        gloss.setColorAt(0.0, QColor(255, 255, 255, gloss_hi))
        gloss.setColorAt(0.45, QColor(255, 248, 232, gloss_lo))
        gloss.setColorAt(1.0, QColor(214, 196, 164, max(6, gloss_hi - 6)))
        gloss_item = QGraphicsPathItem(page_path)
        gloss_item.setPen(QPen(Qt.PenStyle.NoPen))
        gloss_item.setBrush(QBrush(gloss))
        gloss_item.setZValue(0.16)
        self.scene().addItem(gloss_item)

        edge = QLinearGradient(rect.left(), 0, rect.right(), 0)
        edge.setColorAt(0.0, QColor(120, 92, 62, edge_alpha))
        edge.setColorAt(0.08, QColor(255, 255, 255, 0))
        edge.setColorAt(0.92, QColor(255, 255, 255, 0))
        edge.setColorAt(1.0, QColor(120, 92, 62, edge_alpha))
        edge_item = QGraphicsPathItem(page_path)
        edge_item.setPen(QPen(Qt.PenStyle.NoPen))
        edge_item.setBrush(QBrush(edge))
        edge_item.setZValue(0.17)
        self.scene().addItem(edge_item)

    def _add_book_stack(self, rect: QRectF, side: str):
        direction = -1.0 if side == 'left' else 1.0
        for i in range(7, 0, -1):
            layer_rect = rect.translated(direction * i * 2.7, i * 1.15)
            layer_rect = layer_rect.adjusted(-i * 0.35, i * 0.45,
                                             i * 0.35, -i * 0.25)
            sheet = QGraphicsPathItem(_book_page_path(layer_rect, side))
            alpha = 34 + (7 - i) * 5
            sheet.setPen(QPen(QColor(119, 96, 67, 34 + i * 3), 0.75))
            sheet.setBrush(QColor(247, 239, 221, alpha))
            sheet.setZValue(-0.18 - i * 0.018)
            self.scene().addItem(sheet)

    def _add_book_corner_details(self, rect: QRectF, side: str):
        outer_x = rect.left() if side == 'left' else rect.right()
        direction = -1 if side == 'left' else 1
        for vertical_name, y in (('top', rect.top()), ('bottom', rect.bottom())):
            for depth in range(3):
                edge = 12 + depth * 5
                drift = 8 + depth * 4
                if vertical_name == 'top':
                    poly = QPolygonF([
                        QPointF(outer_x, y + depth * 2.2),
                        QPointF(outer_x + direction * edge, y + depth * 1.5),
                        QPointF(outer_x + direction * drift, y + 18 + depth * 2.0),
                    ])
                else:
                    poly = QPolygonF([
                        QPointF(outer_x, y - depth * 2.2),
                        QPointF(outer_x + direction * edge, y - depth * 1.5),
                        QPointF(outer_x + direction * drift, y - 18 - depth * 2.0),
                    ])
                alpha = 80 - depth * 16
                flap = QGraphicsPolygonItem(poly)
                flap.setPen(QPen(QColor(126, 100, 72, 48), 0.8))
                flap.setBrush(QColor(250, 244, 230, alpha))
                flap.setZValue(0.33 - depth * 0.01)
                self.scene().addItem(flap)

            line_len = 26
            line_offset = 4
            if vertical_name == 'top':
                line = QGraphicsLineItem(
                    outer_x,
                    y + line_offset,
                    outer_x + direction * line_len,
                    y + 14,
                )
            else:
                line = QGraphicsLineItem(
                    outer_x,
                    y - line_offset,
                    outer_x + direction * line_len,
                    y - 14,
                )
            line.setPen(QPen(QColor(158, 126, 90, 72), 1.2))
            line.setZValue(0.36)
            self.scene().addItem(line)

    def _make_inline_font_bar(self) -> QWidget:
        """제자리 편집용 서식 툴바 (글꼴·크기·굵기·기울임·밑줄·색·정렬)."""
        from PySide6.QtWidgets import QSpinBox, QToolButton, QPushButton
        bar = QWidget(self.viewport())
        bar.setStyleSheet(
            'QWidget { background: #f6f8fe; border: 1px solid #b7c3de;'
            ' border-radius: 5px; }'
            'QComboBox, QSpinBox { border: 1px solid #b7c3de; border-radius: 3px;'
            ' background: white; font-size: 11px; padding: 0 3px; min-height: 20px; }'
            'QToolButton { border: 1px solid transparent; border-radius: 3px;'
            ' min-width: 22px; min-height: 20px; font-size: 12px; }'
            'QToolButton:hover { background: #e3e9f7; }'
            'QToolButton:checked { background: #cfe0ff; border-color: #6f9be8; }')
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(5, 3, 5, 3)
        lay.setSpacing(3)

        cb = QComboBox()
        for name, *_ in _INLINE_FONT_OPTIONS:
            cb.addItem(name)
        cb.setFixedWidth(112)
        cb.currentIndexChanged.connect(self._on_inline_font_changed)
        lay.addWidget(cb)

        b_minus = QToolButton(); b_minus.setText('−')
        b_minus.clicked.connect(lambda: self._nudge_inline_size(-1))
        lay.addWidget(b_minus)
        size = QSpinBox(); size.setRange(4, 400); size.setValue(12); size.setFixedWidth(46)
        size.valueChanged.connect(self._on_inline_size_changed)
        lay.addWidget(size)
        b_plus = QToolButton(); b_plus.setText('+')
        b_plus.clicked.connect(lambda: self._nudge_inline_size(1))
        lay.addWidget(b_plus)

        bB = QToolButton(); bB.setText('B'); bB.setCheckable(True)
        bB.setStyleSheet('font-weight:bold;')
        bB.toggled.connect(lambda on: self._on_inline_style('bold', on))
        lay.addWidget(bB)
        bI = QToolButton(); bI.setText('I'); bI.setCheckable(True)
        bI.setStyleSheet('font-style:italic;')
        bI.toggled.connect(lambda on: self._on_inline_style('italic', on))
        lay.addWidget(bI)
        bU = QToolButton(); bU.setText('U'); bU.setCheckable(True)
        bU.setStyleSheet('text-decoration:underline;')
        bU.toggled.connect(lambda on: self._on_inline_style('underline', on))
        lay.addWidget(bU)

        col = QPushButton(); col.setFixedSize(22, 20)
        col.setToolTip('글자 색')
        col.clicked.connect(self._on_inline_color)
        lay.addWidget(col)

        aL = QToolButton(); aL.setText('⯇'); aL.setCheckable(True); aL.setToolTip('왼쪽')
        aC = QToolButton(); aC.setText('≡'); aC.setCheckable(True); aC.setToolTip('가운데')
        aR = QToolButton(); aR.setText('⯈'); aR.setCheckable(True); aR.setToolTip('오른쪽')
        for btn, al in ((aL, 0), (aC, 1), (aR, 2)):
            btn.clicked.connect(lambda _c=False, _a=al: self._on_inline_align(_a))
            lay.addWidget(btn)

        # ── 문단 다시 흘리기(캔바식) 토글 ──
        rf = QToolButton(); rf.setText('↩흘리기'); rf.setCheckable(True)
        rf.setToolTip(
            '문단 다시 흘리기(캔바식)\n'
            '켜면 문단이 하나의 흐르는 글로 열려 자유롭게 줄바꿈됩니다.\n'
            '끄면 원본 줄 위치를 그대로 보존합니다(각주·내어쓰기 안전).')
        rf.toggled.connect(self._on_toggle_reflow_mode)
        lay.addWidget(rf)

        bar.adjustSize()
        bar._combo = cb          # type: ignore[attr-defined]
        bar._size = size         # type: ignore[attr-defined]
        bar._bold = bB           # type: ignore[attr-defined]
        bar._italic = bI         # type: ignore[attr-defined]
        bar._underline = bU      # type: ignore[attr-defined]
        bar._color = col         # type: ignore[attr-defined]
        bar._align = (aL, aC, aR)  # type: ignore[attr-defined]
        bar._reflow = rf         # type: ignore[attr-defined]
        return bar

    def _on_toggle_reflow_mode(self, on: bool):
        """캔바식 '문단 다시 흘리기' 모드 전환 → 편집 중이면 즉시 다시 로드."""
        self._reflow_mode = bool(on)
        ed = self._inline_block_ed
        if ed is not None and ed.isVisible() and ed.fitz_rect is not None:
            rows = getattr(self, '_block_rows', None) or []
            right = max([r['x1'] for r in rows] + [ed.fitz_rect.x1]) if rows else 0
            ed.blockSignals(True)
            txt = (_flow_text_from_rows(rows, right) if on
                   else '\n'.join(r['text'] for r in rows).strip())
            ed.original_text = txt
            ed.setPlainText(txt)
            ed.blockSignals(False)
            ed.setFocus()
        self._notify_reflow_state()

    def _notify_reflow_state(self):
        """모드와 위험 여부를 상태 표시줄에 알린다."""
        rows = getattr(self, '_block_rows', None) or []
        if not self._reflow_mode:
            self.status_message.emit('본문 편집: 원본 줄 위치 보존 모드')
            return
        if _rows_have_hanging_indent(rows):
            self.status_message.emit(
                '⚠ 다시 흘리기 ON — 이 문단은 각주/내어쓰기 구조라 '
                '저장 시 들여쓰기가 단순해지고 볼드 제목이 유실될 수 있습니다.')
        else:
            self.status_message.emit(
                '다시 흘리기 ON — 문단 전체가 자연스럽게 재배치됩니다. '
                '줄 끝 띄어쓰기가 어색하면 편집창에서 바로 고치세요.')

    def _active_inline_editor(self):
        return (self._inline_block_ed if self._inline_block_ed.isVisible()
                else self._inline_ed)

    def _refresh_block_font(self):
        """블록 편집기의 미리보기 글꼴을 현재 속성(글꼴·크기·굵기 등)으로 갱신."""
        from PySide6.QtGui import QFont
        ed = self._inline_block_ed
        _, _, _, qt_family = _INLINE_FONT_OPTIONS[
            max(0, min(ed.font_key, len(_INLINE_FONT_OPTIONS) - 1))]
        _txt = ed.toPlainText() or ed.original_text
        _ko = any(0xAC00 <= ord(c) <= 0xD7A3 for c in _txt)
        fam = qt_family if _ko else self._qt_family_for(ed.orig_font, False)
        f = QFont(fam)
        f.setPixelSize(max(6, int(round(ed.fs * self.zoom() * self._zoom))))
        f.setBold(ed.bold); f.setItalic(ed.italic); f.setUnderline(ed.underline)
        ed.set_appearance(f, ed.text_color)

    def _on_inline_font_changed(self, idx: int):
        from PySide6.QtGui import QFont
        if self._inline_block_ed.isVisible():
            self._inline_block_ed.font_key = idx
            self._refresh_block_font()
        else:
            ed = self._inline_ed
            ed.font_key = idx
            _, _, _, qt_family = _INLINE_FONT_OPTIONS[idx]
            f = QFont(qt_family)
            f.setPointSizeF(max(6.0, ed.fs * self._zoom))
            ed.setFont(f)

    def _nudge_inline_size(self, delta: int):
        bar = self._inline_font_bar
        bar._size.setValue(bar._size.value() + delta)

    def _on_inline_size_changed(self, v: int):
        if self._inline_block_ed.isVisible():
            self._inline_block_ed.fs = float(v)
            self._refresh_block_font()

    def _on_inline_style(self, which: str, on: bool):
        if self._inline_block_ed.isVisible():
            setattr(self._inline_block_ed, which, bool(on))
            self._refresh_block_font()

    def _on_inline_align(self, a: int):
        bar = self._inline_font_bar
        for i, btn in enumerate(bar._align):
            btn.setChecked(i == a)
        if self._inline_block_ed.isVisible():
            self._inline_block_ed.align = a

    def _on_inline_color(self):
        from PySide6.QtWidgets import QColorDialog
        ed = self._inline_block_ed
        c0 = QColor(int(ed.text_color[0]*255), int(ed.text_color[1]*255), int(ed.text_color[2]*255))
        c = QColorDialog.getColor(c0, self, '글자 색')
        if c.isValid():
            ed.text_color = (c.redF(), c.greenF(), c.blueF())
            self._inline_font_bar._color.setStyleSheet(
                f'background:{c.name()}; border:1px solid #888; border-radius:3px;')
            self._refresh_block_font()

    # ── 접근자 ──────────────────────────────────────────────────────
    def doc(self):            return self._doc
    def renderer(self):       return self._renderer
    def pending_layer(self):  return self._pending

    def page_at_scene(self, scene_pos: QPointF) -> int:
        """씬 좌표가 속한 페이지 인덱스.

        양면 모드는 좌/우, 스크롤 모드는 커서 아래 실제 페이지를 판별한다 —
        스크롤 모드에서 _cur_page(가장 많이 보이는 페이지)를 그대로 쓰면
        커서가 다른 페이지 위에 있을 때 좌표가 어긋난다.
        """
        if self._scroll_mode and self._scroll_page_items:
            best_idx = None
            best_dist = float('inf')
            y = scene_pos.y()
            for idx, item in self._scroll_page_items.items():
                rect = item.sceneBoundingRect()
                if rect.contains(scene_pos):
                    return idx
                # 세로로 쌓인 레이아웃 — y축 거리로 가장 가까운 페이지
                dist = 0.0 if rect.top() <= y <= rect.bottom() else \
                    min(abs(y - rect.top()), abs(y - rect.bottom()))
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx
            if best_idx is not None:
                return best_idx
        if not self._double_mode or self._right_page < 0:
            return self._cur_page
        right_off = self._page_offsets.get(self._right_page)
        if right_off is not None and scene_pos.x() >= right_off.x():
            return self._right_page
        return self._cur_page

    def page_offset(self, page_idx: int) -> QPointF:
        """페이지의 씬 내 좌상단 오프셋 (단일 모드 = (0,0))."""
        return self._page_offsets.get(page_idx, QPointF(0, 0))

    def rebuild_pending_item(self, pa: PendingAnnotation):
        if pa.page_index != self._cur_page:
            pa.remove_from_scene()
            return
        pa.remove_from_scene()
        offset = self._page_offsets.get(pa.page_index, QPointF(0, 0))
        item = _make_pending_item(pa, offset, _BASE_RENDER_ZOOM)
        if item is not None:
            item.setZValue(20)
            self.scene().addItem(item)
            pa.q_item = item

    def notify_pending_changed(self):
        """미확정 어노테이션 수가 변경됐음을 UI에 알린다."""
        self.pending_count_changed.emit(self._pending.count())

    def zoom(self) -> float:
        """어노테이션 좌표 변환용 렌더 줌 반환 (scene px / zoom = fitz pt)."""
        return _BASE_RENDER_ZOOM

    def display_zoom(self) -> float:
        """현재 표시 배율 (뷰 트랜스폼 기준)."""
        return self._zoom

    def current_page(self): return self._cur_page
    def is_double_mode(self) -> bool: return self._double_mode
    def is_scroll_mode(self) -> bool: return self._scroll_mode
    def is_segment_mode(self) -> bool: return self._segment_mode

    # ── 도구 교체 ────────────────────────────────────────────────────
    def set_tool(self, tool: BaseTool):
        self._tool.deactivate(self)
        self._tool = tool
        self._tool.activate(self)

    def current_tool(self) -> BaseTool:
        return self._tool

    def take_insert_pos(self):
        """현재 도구에 저장된 마커 위치를 꺼낸다 (없으면 None).
        컨텍스트 메뉴에서 메모/텍스트 삽입 위치로 사용."""
        if hasattr(self._tool, 'take_pos'):
            return self._tool.take_pos(self)
        return None

    # ── 뷰 트랜스폼 적용 ─────────────────────────────────────────────
    def _apply_transform(self):
        """현재 _zoom 값으로 QGraphicsView 트랜스폼 업데이트 (즉시, 재렌더 없음)."""
        t = QTransform()
        t.scale(self._zoom, self._zoom)
        self.setTransform(t)
        self._update_zoom_hud_label()
        self.display_zoom_changed.emit(self._zoom)
        self._reposition_index_bar()

    # ── 페이지 표시 ──────────────────────────────────────────────────
    def show_page(self, index: int):
        if not self._doc.is_open:
            return
        index = max(0, min(index, self._doc.page_count() - 1))
        prev_page = self._cur_page
        if self._book_mode_visual and self._page_item is not None and index != prev_page:
            self._start_book_turn_animation(index > prev_page)
        self._stop_scroll_worker()
        self._cur_page = index
        self._double_mode = False
        self._scroll_mode = False
        self._segment_mode = False
        self._segment_count = 1
        self._segment_index = 0
        self._hq_text_page_cache.clear()
        self._render_single(index)
        self._schedule_hq_refresh()
        self.page_changed.emit(index)
        self._refresh_index_bars()   # 단면 모드 → 오른쪽 바만

    def show_double(self, left: int, right: int | None = None):
        if not self._doc.is_open:
            return
        n = self._doc.page_count()
        left = max(0, min(left, n - 1))
        right = min(right if right is not None else left + 1, n - 1)
        if left == right:
            right = -1
        self._stop_scroll_worker()
        self._right_page = right
        prev_page = self._cur_page
        if self._book_mode_visual and self._page_item is not None and left != prev_page:
            self._start_book_turn_animation(left > prev_page)
        self._cur_page = left
        self._double_mode = True
        self._scroll_mode = False
        self._segment_mode = False
        self._segment_count = 1
        self._segment_index = 0
        self._hq_text_page_cache.clear()
        # 책보기 표시 전에 표시용 이미지 캐시를 미리 채운다
        # (renderer 는 렌더링 전용 분리 fitz.Document 를 사용하므로
        #  get_text() 에 의한 CID 폰트 오염이 렌더링에 영향을 주지 않는다)
        self._renderer.get(left, _BASE_RENDER_ZOOM)
        if right >= 0:
            self._renderer.get(right, _BASE_RENDER_ZOOM)

        if self._book_mode_visual:
            self._ensure_book_clips(left, right)
            # 두 페이지 크기 동기화: 한쪽이 좁거나 짧아도 항상 같은 크기로 표시
            if right >= 0:
                clip_l = self._book_page_clips.get(left)
                clip_r = self._book_page_clips.get(right)
                if clip_l is not None and clip_r is not None:
                    # x·y 모두 union → 두 페이지가 같은 가로/세로 크기
                    x0 = min(clip_l.x0, clip_r.x0)
                    y0 = min(clip_l.y0, clip_r.y0)
                    x1 = max(clip_l.x1, clip_r.x1)
                    y1 = max(clip_l.y1, clip_r.y1)
                    merged = fitz.Rect(x0, y0, x1, y1)
                    self._book_page_clips[left]  = merged
                    self._book_page_clips[right] = merged
        self._render_double(left, right)
        if self._book_mode_visual:
            self._refresh_visible_page_quality()
        self._schedule_hq_refresh()
        self.page_changed.emit(left)
        self._refresh_index_bars()   # 양면/책보기 → 좌우 양쪽 바

    def show_segment(self, index: int, segment_index: int = 0, segment_count: int = 2):
        if not self._doc.is_open:
            return
        index = max(0, min(index, self._doc.page_count() - 1))
        segment_count = max(1, int(segment_count))
        segment_index = max(0, min(segment_count - 1, int(segment_index)))
        self._cur_page = index
        self._double_mode = False
        self._scroll_mode = False
        self._segment_mode = True
        self._segment_count = segment_count
        self._segment_index = segment_index
        self._hq_text_page_cache.clear()
        self._render_segment(index, segment_index, segment_count)
        self._schedule_hq_refresh()
        self.page_changed.emit(index)
        self._refresh_index_bars()

    def step_segment(self, forward: bool) -> bool:
        if not self._doc.is_open or not self._segment_mode:
            return False
        last = max(0, self._doc.page_count() - 1)
        if forward:
            if self._cur_page < last:
                self.show_segment(self._cur_page + 1, 0, self._segment_count)
                return True
            return False
        if self._cur_page > 0:
            self.show_segment(self._cur_page - 1, 0, self._segment_count)
            return True
        return False

    def goto_in_scroll(self, index: int):
        """스크롤 모드를 유지한 채 특정 페이지로 스크롤 이동한다.

        show_page() 는 _scroll_mode=False 로 강제 전환하므로 스크롤 모드에서는
        이 메서드를 사용해야 한다.
        """
        if not self._scroll_mode or not self._doc.is_open:
            return
        index = max(0, min(index, self._doc.page_count() - 1))
        item = self._scroll_page_items.get(index)
        if item is not None:
            rect = item.sceneBoundingRect()
            viewport_scene_h = max(1.0, self.viewport().height() / max(0.05, self._zoom))
            target_center_y = rect.top() + viewport_scene_h * 0.5
            self.centerOn(rect.center().x(), target_center_y)
            self._cur_page = index
            self.page_changed.emit(index)

    def show_scroll(self):
        if not self._doc.is_open:
            return
        anchor_page = self._cur_page
        prev_zoom = self._zoom
        self._hq_text_page_cache.clear()
        self._scroll_mode = True
        self._double_mode = False
        self._segment_mode = False
        self._segment_count = 1
        self._segment_index = 0
        self._suppress_scroll_tracking = True
        self._render_scroll()

        def _restore_scroll_anchor():
            self._zoom = max(0.05, min(10.0, prev_zoom))
            self._apply_transform()
            hsb = self.horizontalScrollBar()
            hsb.setValue(hsb.minimum())
            item = self._scroll_page_items.get(anchor_page)
            if item is not None:
                rect = item.sceneBoundingRect()
                viewport_scene_h = max(1.0, self.viewport().height() / max(0.05, self._zoom))
                target_center_y = rect.top() + viewport_scene_h * 0.5
                self.centerOn(rect.center().x(), target_center_y)
                self._cur_page = anchor_page
                self.page_changed.emit(anchor_page)
            self._suppress_scroll_tracking = False
            self._schedule_hq_refresh()
            self._refresh_index_bars()   # 스크롤 모드 → 오른쪽 바만

        QTimer.singleShot(0, _restore_scroll_anchor)
    def refresh_page(self):
        """현재 페이지의 캐시를 무효화하고 다시 렌더링한다 (뷰 유지)."""
        self._hq_text_page_cache.clear()
        self._renderer.invalidate(self._cur_page)
        if self._segment_mode:
            self._render_segment(self._cur_page, self._segment_index, self._segment_count)
            self._schedule_hq_refresh()
        elif self._double_mode:
            right = self._right_page
            self._render_double(self._cur_page, right)
            self._schedule_hq_refresh()
        elif self._scroll_mode:
            self._render_scroll()
            self._schedule_hq_refresh()   # 스크롤 보기도 HQ로 올려준다
        else:
            self._render_single(self._cur_page)
            self._schedule_hq_refresh()


    # ── 내부 렌더링 ──────────────────────────────────────────────────

    def _clear_scene(self):
        """씬 초기화: 모든 아이템 제거 및 페이지 아이템 참조 리셋."""
        self.scene().clear()
        self._page_item = None
        self._page_item_r = None

    def _make_page_item(self, index: int, zoom: float,
                        book_side: str | None = None) -> QGraphicsPixmapItem:
        """페이지를 렌더링하여 QGraphicsPixmapItem 반환. zoom=0 이면 BASE_RENDER_ZOOM 사용."""
        render_zoom = zoom if zoom > 0 else _BASE_RENDER_ZOOM
        img = self._renderer.get(index, render_zoom)
        if self._book_mode_visual:
            clip = self._effective_book_clip(index)
            if clip is not None:
                img = self._crop_img_for_book(img, index, render_zoom, clip)
        pxm = QPixmap.fromImage(img)
        ratio = max(1.0, render_zoom / _BASE_RENDER_ZOOM)
        pxm.setDevicePixelRatio(ratio)
        if self._book_mode_visual and book_side in {'left', 'right'}:
            item = _BookPagePixmapItem(pxm, book_side)
        else:
            item = QGraphicsPixmapItem(pxm)
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        return item

    def _render_single(self, index: int):
        """단일 페이지 모드 렌더링."""
        self._clear_scene()
        self._scroll_page_items = {}
        self._page_offsets = {index: QPointF(0, 0)}
        item = self._make_page_item(index, _BASE_RENDER_ZOOM)
        self._page_item = item
        self._page_item_r = None
        self.scene().addItem(item)
        page_rect = item.mapRectToScene(item.boundingRect())
        self.scene().setSceneRect(page_rect.adjusted(-20, -20, 20, 20))
        self._apply_transform()
        # 페이지 이동 시 항상 맨 위로 스크롤 초기화
        self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())
        self._restore_pending([index])

    def _render_double(self, left: int, right: int):
        """양면 페이지 모드 렌더링. right=-1 이면 오른쪽 빈 페이지."""
        self._clear_scene()
        self._scroll_page_items = {}
        GAP = 4
        rz = _BASE_RENDER_ZOOM
        item_l = self._make_page_item(left, rz, 'left' if self._book_mode_visual else None)
        self._page_item = item_l
        self._page_item_r = None
        item_l.setPos(0, 0)
        self.scene().addItem(item_l)
        w_l = item_l.boundingRect().width()

        # 크롭 적용 시 어노테이션 offset 보정
        clip_l = self._effective_book_clip(left) if self._book_mode_visual else None
        if clip_l is not None:
            try:
                pr = self._doc.fitz_page(left).rect
                self._page_offsets = {left: QPointF(-(clip_l.x0 - pr.x0) * rz,
                                                    -(clip_l.y0 - pr.y0) * rz)}
            except Exception:
                self._page_offsets = {left: QPointF(0, 0)}
        else:
            self._page_offsets = {left: QPointF(0, 0)}

        visible = [left]
        if right >= 0:
            item_r = self._make_page_item(right, rz, 'right' if self._book_mode_visual else None)
            self._page_item_r = item_r
            x_r = w_l + GAP
            item_r.setPos(x_r, 0)
            self.scene().addItem(item_r)
            clip_r = self._effective_book_clip(right) if self._book_mode_visual else None
            if clip_r is not None:
                try:
                    pr = self._doc.fitz_page(right).rect
                    self._page_offsets[right] = QPointF(x_r - (clip_r.x0 - pr.x0) * rz,
                                                        -(clip_r.y0 - pr.y0) * rz)
                except Exception:
                    self._page_offsets[right] = QPointF(x_r, 0)
            else:
                self._page_offsets[right] = QPointF(x_r, 0)
            visible.append(right)

        if self._book_mode_visual:
            left_rect = item_l.mapRectToScene(item_l.boundingRect())
            self._add_book_texture(left_rect, 'left')
            self._add_book_frame(left_rect, 'left')
            self._add_book_stack(left_rect, 'left')
            self._add_book_corner_details(left_rect, 'left')
            if self._page_item_r is not None:
                right_rect = self._page_item_r.mapRectToScene(self._page_item_r.boundingRect())
                self._add_book_texture(right_rect, 'right')
                self._add_book_frame(right_rect, 'right')
                self._add_book_stack(right_rect, 'right')
                self._add_book_corner_details(right_rect, 'right')
                self._add_book_spine(left_rect, right_rect)

        self.scene().setSceneRect(
            self.scene().itemsBoundingRect().adjusted(-20, -20, 20, 20))
        self._apply_transform()
        self._restore_pending(visible)

    def _render_segment(self, index: int, segment_index: int, segment_count: int):
        """분할 보기 모드 렌더링. 페이지를 segment_count등분하여 segment_index번째 구간 표시."""
        self._clear_scene()
        self._scroll_page_items = {}
        img = self._renderer.get(index, _BASE_RENDER_ZOOM)
        h = img.height()
        seg_h = max(1, h // segment_count)
        y0 = segment_index * seg_h
        y1 = y0 + seg_h if segment_index < segment_count - 1 else h
        seg_img = img.copy(0, y0, img.width(), y1 - y0)
        pxm = QPixmap.fromImage(seg_img)
        item = QGraphicsPixmapItem(pxm)
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._page_item = item
        self._page_item_r = None
        # offset: 어노테이션 좌표 보정 (잘린 위쪽 영역만큼 y 보정)
        self._page_offsets = {index: QPointF(0, -float(y0))}
        self.scene().addItem(item)
        page_rect = item.mapRectToScene(item.boundingRect())
        self.scene().setSceneRect(page_rect.adjusted(-20, -20, 20, 20))
        self._apply_transform()
        self._restore_pending([index])

    def _add_page_mask(self, page_rects: list):
        """페이지 경계 주변 마스킹 (현재 배경색으로 커버). 스크롤 모드에서 사용."""
        pass

    def _on_scroll_bar_moved(self):
        # 인덱스 탭 바가 스크롤과 함께 떠내려가지 않도록 매 스크롤마다 재고정
        self._reposition_index_bar()
        if self._scroll_mode:
            if getattr(self, '_suppress_scroll_tracking', False):
                return
            if self._scroll_page_items:
                vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
                best_idx = None
                best_score = -1.0
                vp_center_y = vp_scene.center().y()
                for idx, item in self._scroll_page_items.items():
                    rect = item.sceneBoundingRect()
                    inter = vp_scene.intersected(rect)
                    if inter.isEmpty():
                        score = -abs(rect.center().y() - vp_center_y)
                    else:
                        score = inter.height() * inter.width()
                    if score > best_score:
                        best_score = score
                        best_idx = idx
                if best_idx is not None and best_idx != self._cur_page:
                    self._cur_page = best_idx
                    self.page_changed.emit(best_idx)
            self._schedule_hq_refresh()
            self._scroll_window_timer.start()   # 200ms 디바운스 후 윈도우 갱신

    def _schedule_hq_refresh(self):
        if not self._doc.is_open:
            self._hq_timer.stop()
            return
        self._hq_timer.start(_HQ_IDLE_DELAY_MS)

    def _page_has_extractable_text(self, index: int) -> bool:
        cached = self._hq_text_page_cache.get(index)
        if cached is not None:
            return cached
        ok = False
        try:
            words = self._doc.fitz_page(index).get_text('words')
            ok = len(words) >= 8
        except Exception:
            ok = False
        self._hq_text_page_cache[index] = ok
        return ok

    def _target_render_zoom(self, index: int) -> float:
        if not self._doc.is_open:
            return _BASE_RENDER_ZOOM
        if not self._page_has_extractable_text(index):
            # 스캔본(이미지 페이지): 화면에 실제로 필요한 픽셀 수에 맞춘다.
            # 고DPI(윈도우 배율 150%·200%) 화면에서는 논리 픽셀보다 실제 픽셀이
            # 많으므로 devicePixelRatio 를 반드시 곱해야 흐려지지 않는다.
            # (원본 해상도로 상한을 두면 확대 시 저해상도 픽스맵을 뷰가 다시
            #  늘리게 되어 오히려 뭉개진다. 메모리는 아래 픽셀/배율 상한으로 충분.)
            page = self._doc.fitz_page(index)
            dpr = max(1.0, self.devicePixelRatioF())
            base_target = _BASE_RENDER_ZOOM * max(1.0, self._zoom) * dpr
            max_by_pixels = (_HQ_RENDER_MAX_PIXELS
                             / max(1.0, page.rect.width * page.rect.height)) ** 0.5
            target = min(_HQ_RENDER_MAX_ZOOM, max_by_pixels, base_target)
            return max(_BASE_RENDER_ZOOM, target)
        page = self._doc.fitz_page(index)
        screen_dpr = max(1.0, self.devicePixelRatioF())
        base_target = max(
            _HQ_RENDER_MIN_ZOOM,
            _BASE_RENDER_ZOOM * max(1.0, self._zoom) * screen_dpr,
        )
        if self._double_mode or self._book_mode_visual:
            spread_boost = 1.35
            spread_floor = 4.2
            if self._book_mode_visual:
                spread_boost = 1.60
                spread_floor = 4.8
            base_target = max(base_target * spread_boost, spread_floor)
        max_by_pixels = (_HQ_RENDER_MAX_PIXELS / max(1.0, page.rect.width * page.rect.height)) ** 0.5
        target = min(_HQ_RENDER_MAX_ZOOM, max_by_pixels, base_target)
        return max(_BASE_RENDER_ZOOM, target)

    def _apply_render_zoom_to_item(self, item: QGraphicsPixmapItem | None,
                                   index: int, render_zoom: float):
        if item is None:
            return
        img = self._renderer.get(index, render_zoom)
        if self._book_mode_visual:
            clip = self._effective_book_clip(index)
            if clip is not None:
                img = self._crop_img_for_book(img, index, render_zoom, clip)
        pxm = QPixmap.fromImage(img)
        ratio = max(1.0, render_zoom / _BASE_RENDER_ZOOM)
        pxm.setDevicePixelRatio(ratio)
        item.setPixmap(pxm)
    def _refresh_visible_page_quality(self):
        if not self._doc.is_open:
            return
        if self._segment_mode:
            self._render_segment(self._cur_page, self._segment_index, self._segment_count)
            return
        if self._scroll_mode:
            self._refresh_scroll_page_quality()
            return
        left_zoom = self._target_render_zoom(self._cur_page)
        if left_zoom > _BASE_RENDER_ZOOM + 0.05:
            self._apply_render_zoom_to_item(self._page_item, self._cur_page, left_zoom)
        if self._double_mode and self._page_item_r is not None:
            right = self._right_page
            if right < 0:
                return
            right_zoom = self._target_render_zoom(right)
            if right_zoom > _BASE_RENDER_ZOOM + 0.05:
                self._apply_render_zoom_to_item(self._page_item_r, right, right_zoom)


    def _refresh_scroll_page_quality(self):
        """스크롤 모드에서 현재 뷰포트에 보이는 페이지를 HQ로 재렌더링."""
        if not self._scroll_page_items:
            return
        vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        for idx, item in self._scroll_page_items.items():
            rect = item.sceneBoundingRect()
            if not vp_scene.intersects(rect):
                continue
            target_zoom = self._target_render_zoom(idx)
            if target_zoom > _BASE_RENDER_ZOOM + 0.05:
                self._apply_render_zoom_to_item(item, idx, target_zoom)

    def _render_scroll(self):
        self._stop_scroll_worker()
        self._clear_scene()
        self._scroll_page_items = {}
        self._scroll_loaded = set()
        n   = self._doc.page_count()
        y   = 0.0
        GAP = 12
        self._page_offsets = {}
        visible_pages = []
        page_rects    = []

        # Phase 1: placeholder 배치
        # 4×4 픽셀 단색 pixmap + scale transform → 메모리 절약 (full-size 시 ~8MB/장 × 300 = 2.4GB)
        _PH = 4  # placeholder 크기(px)
        ph_pxm = QPixmap(_PH, _PH)
        ph_pxm.fill(QColor(230, 226, 218))
        vp = self.viewport()
        vp.setUpdatesEnabled(False)
        try:
            for i in range(n):
                try:
                    pr = self._doc.fitz_page(i).rect
                    w  = max(1, int(pr.width  * _BASE_RENDER_ZOOM))
                    h  = max(1, int(pr.height * _BASE_RENDER_ZOOM))
                except Exception:
                    w, h = int(595 * _BASE_RENDER_ZOOM), int(842 * _BASE_RENDER_ZOOM)
                item = QGraphicsPixmapItem(ph_pxm)
                item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
                from PySide6.QtGui import QTransform as _QT
                item.setTransform(_QT.fromScale(w / _PH, h / _PH))
                item.setPos(0, y)
                self.scene().addItem(item)
                logical_rect = item.mapRectToScene(item.boundingRect())
                self._page_offsets[i] = logical_rect.topLeft()
                visible_pages.append(i)
                self._scroll_page_items[i] = item
                if self._page_item is None:
                    self._page_item = item
                page_rects.append(logical_rect)
                y = logical_rect.bottom() + GAP
        finally:
            vp.setUpdatesEnabled(True)

        self.scene().setSceneRect(
            self.scene().itemsBoundingRect().adjusted(-20, -20, 20, 20))
        self._apply_transform()
        self._add_page_mask(page_rects)
        self._restore_pending(visible_pages)
        vp.update()

        # Phase 2: 백그라운드 워커로 실제 이미지 렌더링
        doc_path = getattr(self._doc, 'path', None)
        if doc_path:
            pw = getattr(self._doc, 'password', '') or ''
            worker = _ScrollRenderWorker(str(doc_path), _BASE_RENDER_ZOOM, self, password=pw)
            worker.page_ready.connect(self._on_scroll_page_ready)
            self._scroll_worker = worker
            worker.start()   # 빈 큐로 시작 — 80ms 후 visible window만 요청
            QTimer.singleShot(80, self._prioritize_visible_scroll_pages)
        else:
            # 경로 없는 경우(이미지 PDF 등) 기존 방식으로 폴백
            for i in range(n):
                item = self._scroll_page_items.get(i)
                if item is None:
                    continue
                img = self._renderer.get(i, _BASE_RENDER_ZOOM)
                item.setPixmap(QPixmap.fromImage(img))

    def release_file_handles(self):
        """문서 파일 핸들을 잡은 렌더 자원을 해제한다.

        같은 경로 저장은 os.replace()로 원자적 교체를 시도하는데, Windows는
        열린 핸들이 있으면 교체를 거부한다. 저장 직전에 호출할 것.
        렌더 문서는 다음 렌더링 때 자동 재동기화되고, 스크롤 워커는
        저장 후 refresh_page()로 재시작된다.
        """
        self._stop_scroll_worker(wait_for_finish=True)
        _wait_for_retired_scroll_workers()
        self._renderer.close()

    def _stop_scroll_worker(self, wait_for_finish=False):
        """기존 스크롤 워커를 중단하고 배치 큐도 정리한다."""
        self._scroll_batch_timer.stop()
        self._scroll_window_timer.stop()
        self._scroll_pending_updates.clear()
        worker = self._scroll_worker
        if worker is not None:
            worker.page_ready.disconnect()
            worker.stop()
            if not worker.wait(1500):
                if wait_for_finish:
                    worker.wait()
                    worker.deleteLater()
                else:
                    _retire_scroll_worker(worker)
            else:
                worker.deleteLater()
            self._scroll_worker = None

    def _on_scroll_page_ready(self, idx: int, img: QImage):
        """워커가 렌더링한 페이지를 배치 큐에 쌓는다 (40ms 타이머로 일괄 반영)."""
        if not self._scroll_mode:
            return
        self._scroll_pending_updates[idx] = img
        if not self._scroll_batch_timer.isActive():
            self._scroll_batch_timer.start()

    def _flush_scroll_page_updates(self):
        """배치 큐에 쌓인 페이지 이미지를 한 번에 씬에 반영한다."""
        if not self._scroll_pending_updates or not self._scroll_mode:
            self._scroll_batch_timer.stop()
            return
        updates, self._scroll_pending_updates = self._scroll_pending_updates, {}
        self.viewport().setUpdatesEnabled(False)
        for idx, img in updates.items():
            item = self._scroll_page_items.get(idx)
            if item is not None:
                from PySide6.QtGui import QTransform as _QT
                item.setTransform(_QT())          # placeholder scale 제거
                item.setPixmap(QPixmap.fromImage(img))
                self._scroll_loaded.add(idx)
        self.viewport().setUpdatesEnabled(True)
        self.viewport().update()
        if not self._scroll_pending_updates:
            self._scroll_batch_timer.stop()

    def _prioritize_visible_scroll_pages(self):
        """현재 뷰포트 기준으로 워커 윈도우를 visible ± buffer 로만 교체."""
        worker = self._scroll_worker
        if worker is None or not self._scroll_mode:
            return
        vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        visible = [idx for idx, item in self._scroll_page_items.items()
                   if vp_scene.intersects(item.sceneBoundingRect())]
        if not visible:
            visible = [0]
        first, last = min(visible), max(visible)
        n = self._doc.page_count()
        start = max(0, first - _SCROLL_PREFETCH_BUFFER)
        end   = min(n - 1, last + _SCROLL_PREFETCH_BUFFER)
        worker.set_window(list(range(start, end + 1)))

        # 보관 창(윈도우 ± 여유분)을 벗어난 페이지의 풀사이즈 픽스맵을
        # placeholder 로 되돌린다 — 한 장 ~8MB 라서 1000페이지급 문서를
        # 훑기만 해도 수 GB 가 쌓여 앱이 다운되던 문제 방지.
        keep_lo = start - _SCROLL_RETAIN_MARGIN
        keep_hi = end + _SCROLL_RETAIN_MARGIN
        evicted = [i for i in self._scroll_loaded if not (keep_lo <= i <= keep_hi)]
        if evicted:
            from PySide6.QtGui import QTransform as _QT
            ph = self._scroll_placeholder_pixmap()
            for i in evicted:
                item = self._scroll_page_items.get(i)
                if item is None:
                    continue
                # HQ 픽스맵은 DPR 스케일이 있으므로 논리 크기 기준으로 복원
                br = item.boundingRect()
                w = max(1.0, br.width())
                h = max(1.0, br.height())
                item.setPixmap(ph)
                item.setTransform(_QT.fromScale(w / ph.width(), h / ph.height()))
                self._scroll_loaded.discard(i)
            worker.forget(evicted)

    def _scroll_placeholder_pixmap(self) -> QPixmap:
        """스크롤 placeholder 픽스맵 (공유 인스턴스)."""
        ph = getattr(self, '_scroll_ph_pxm', None)
        if ph is None:
            ph = QPixmap(4, 4)
            ph.fill(QColor(230, 226, 218))
            self._scroll_ph_pxm = ph
        return ph

    def _restore_pending(self, page_indices: list[int]):
        """재렌더 후 pending 어노테이션의 q_item을 씬에 다시 추가."""
        for pa in self._pending.all():
            if pa.page_index not in page_indices:
                continue
            offset = self._page_offsets.get(pa.page_index, QPointF(0, 0))
            item   = _make_pending_item(pa, offset, _BASE_RENDER_ZOOM)
            if item is not None:
                item.setZValue(20)
                self.scene().addItem(item)
                pa.q_item = item

    def commit_all_pending(self):
        """모든 대기 어노테이션을 PDF에 커밋하고 화면을 갱신한다."""
        if self._pending.count() == 0:
            return True
        committed, failed = self._pending.commit_all(self._doc.fitz_doc())
        affected = {pa.page_index for pa in committed}
        if committed:
            self._doc.mark_dirty()
            # 커밋된 어노테이션을 페이지별로 undo 스택에 기록
            xrefs_by_page: dict[int, list[int]] = {}
            for pa in committed:
                xref = getattr(pa, 'committed_xref', None)
                if xref:
                    xrefs_by_page.setdefault(pa.page_index, []).append(xref)
                # 복합 화살표처럼 여러 어노테이션으로 커밋되는 항목도 함께
                # 되돌려야 한다 (몸통만 지워지고 화살촉이 남는 것 방지)
                for extra in getattr(pa, 'extra_xrefs', None) or []:
                    xrefs_by_page.setdefault(pa.page_index, []).append(extra)
            for pg, xrefs in xrefs_by_page.items():
                self._doc.push_undo(pg, xrefs)
            for pg in affected:
                self._renderer.invalidate(pg)
                # 책보기 마진 캐시도 무효화 — 어노테이션 후 다시 감지
                self._book_page_clips.pop(pg, None)
            self.annot_committed.emit()
        self.refresh_page()
        self.notify_pending_changed()
        return len(failed) == 0

    def discard_all_pending(self):
        """모든 미확정 어노테이션을 취소(씬 + 목록에서 제거)."""
        for pa in self._pending.all():
            pa.remove_from_scene()
        self._pending.remove_all_from_scene_and_clear()
        self.notify_pending_changed()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_zoom_hud') and self._zoom_hud.isVisible():
            self._reposition_zoom_hud()
        self._reposition_index_bar()

    # ── 줌 ──────────────────────────────────────────────────────────
    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor   = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            new_zoom = max(0.05, min(10.0, self._zoom * factor))
            if abs(new_zoom - self._zoom) > 0.001:
                self._zoom = new_zoom
                self._apply_transform()
                self._schedule_hq_refresh()
                self._show_hud_timed()
        elif self._double_mode:
            # 책보기: 휠 아래 → 다음 장, 휠 위 → 이전 장
            # 300 ms 쿨다운 — 휠 이벤트가 연속 발화해도 한 번만 처리
            import time
            now = time.monotonic()
            if now - getattr(self, '_book_wheel_ts', 0.0) < 0.30:
                event.accept()
                return
            self._book_wheel_ts = now

            delta = event.angleDelta().y()
            if delta == 0:
                event.accept()
                return
            cur  = self._cur_page
            last = max(0, self._doc.page_count() - 1)
            left = cur if cur % 2 == 0 else cur - 1
            if delta < 0:                                       # 아래 → 다음
                new_left = min(max(0, last - 1), left + 2)
            else:                                               # 위 → 이전
                new_left = max(0, left - 2)
            if new_left != left:
                self.show_double(new_left)
            event.accept()
        else:
            super().wheelEvent(event)

    def set_zoom(self, zoom: float):
        self._zoom = max(0.05, min(10.0, zoom))
        self._apply_transform()
        self._schedule_hq_refresh()

    def _current_page_scene_rect(self) -> QRectF:
        """현재 페이지 아이템의 scene rect 반환. 스크롤 모드에서도 단일 페이지 기준."""
        if self._scroll_mode:
            item = self._scroll_page_items.get(self._cur_page) or self._page_item
        else:
            item = self._page_item
        if item is None:
            return self.sceneRect()
        return item.mapRectToScene(item.boundingRect())

    def fit_page(self):
        if not self._page_item:
            return
        content = self._current_page_scene_rect()
        if content.width() <= 0 or content.height() <= 0:
            return
        # 책보기는 여백을 최소화해 화면에 꽉 차게 본다.
        m = 2 if self._book_mode_visual else 10
        vw = max(1, self.viewport().width()  - m)
        vh = max(1, self.viewport().height() - m)
        fit_scale = min(vw / content.width(), vh / content.height())
        self._zoom = max(0.05, min(10.0, fit_scale))
        self._apply_transform()
        self.centerOn(content.center())
        self._schedule_hq_refresh()

    def fit_width(self):
        if not self._page_item:
            return
        if self._scroll_mode:
            content = self._current_page_scene_rect()
        else:
            content = self.sceneRect()
        if content.width() <= 0:
            return
        m = 2 if self._book_mode_visual else 10
        vw = max(1, self.viewport().width() - m)
        fit_scale = vw / content.width()
        if self._book_mode_visual and content.height() > 0:
            vh = max(1, self.viewport().height() - m)
            fit_scale = min(fit_scale, vh / content.height())
        self._zoom = max(0.05, min(10.0, fit_scale))
        self._apply_transform()
        self.centerOn(content.center())
        self._schedule_hq_refresh()

    # ── 영역 캡처 ────────────────────────────────────────────────────
    def start_region_capture(self):
        """영역 선택 캡처 모드 진입. 사용자가 드래그로 영역을 선택한다."""
        from PySide6.QtWidgets import QRubberBand
        self._region_capture_mode = True
        self._region_rb_start = None
        if self._region_rubber_band is None:
            self._region_rubber_band = QRubberBand(
                QRubberBand.Shape.Rectangle, self.viewport())
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def cancel_region_capture(self):
        """영역 캡처 모드 취소."""
        self._region_capture_mode = False
        self._region_rb_start = None
        if self._region_rubber_band:
            self._region_rubber_band.hide()
        self.viewport().unsetCursor()
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag
                         if self._scroll_mode else QGraphicsView.DragMode.NoDrag)

    # ── 마우스 → 도구 위임 ──────────────────────────────────────────
    def mousePressEvent(self, event: QMouseEvent):
        # ── 영역 캡처 모드 처리 ──────────────────────────────────
        if self._region_capture_mode and event.button() == Qt.MouseButton.LeftButton:
            self._region_rb_start = event.pos()
            if self._region_rubber_band:
                self._region_rubber_band.setGeometry(
                    QRect(self._region_rb_start, self._region_rb_start))
                self._region_rubber_band.show()
            return

        # 클릭 시 키보드 포커스 획득 (화살키 등 사용 가능)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        pos = self.mapToScene(event.pos())
        # 본문 편집 모드: 한 번 클릭으로 바로 그 문단을 제자리에서 편집
        if (self._text_edit_mode and not getattr(self, '_edit_locked', False)
                and event.button() == Qt.MouseButton.LeftButton):
            self._dict_timer.stop()
            self._edit_text_block(pos, click_scene=pos)
            return
        # 좌클릭 시 사전 즉시 조회 (sticky 팝업)
        if (event.button() == Qt.MouseButton.LeftButton):
            self._dict_timer.stop()
            self._dict_lookup_at(pos, event.globalPosition().toPoint(), sticky=True)
        if self._tool_blocked():
            # 권한 제한 문서 — 도구 버튼을 꺼도 이미 골라 둔 도구나 단축키로는
            # 계속 그려졌다. 캔버스에서 직접 막는다 (선택 도구는 허용).
            self.status_message.emit(
                '🔒 이 문서는 주석/편집이 제한되어 있습니다 (관리자 암호로 열면 허용).')
            return
        try:
            self._tool.on_press(pos, event, self)
        except Exception as e:
            import logging
            logging.getLogger('pdf_editor').error(f'[Canvas] on_press error: {e}')
        if not isinstance(self._tool, SelectTool):
            return
        # 어노테이션이 선택된 경우 super() 생략 — Qt scene이 sel_item을
        # mouse grabber로 잡으면 드래그 중 이벤트 전달이 꼬임
        sel = self._tool
        if getattr(sel, '_sel_xref', None) is None and getattr(sel, '_sel_pending', None) is None:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        # ── 영역 캡처 모드: 고무줄 업데이트 ─────────────────────
        if self._region_capture_mode and self._region_rb_start is not None:
            if self._region_rubber_band:
                rect = QRect(self._region_rb_start, event.pos()).normalized()
                self._region_rubber_band.setGeometry(rect)
            return

        pos = self.mapToScene(event.pos())
        # 본문 편집 모드: 마우스 아래 문단에 편집 가능 사각형 표시 (Canva식)
        if (self._text_edit_mode and not getattr(self, '_edit_locked', False)
                and not event.buttons()):
            self._update_edit_hover(pos)
        try:
            if not self._tool_blocked():
                self._tool.on_move(pos, event, self)
        except Exception as e:
            import logging
            logging.getLogger('pdf_editor').error(f'[Canvas] on_move error: {e}')
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._dict_drag_anchor is not None:
            drag_rect = QRectF(self._dict_drag_anchor, pos).normalized()
            if drag_rect.width() > 6 or drag_rect.height() > 6:
                self._dict_selected_text = self._text_in_scene_rect(drag_rect)

        if not event.buttons():
            self._global_hover_tooltip(pos, event)
            self._dict_hover_pos  = pos
            self._dict_hover_gpos = event.globalPosition().toPoint()
            self._dict_timer.start(500)   # 500ms 대기 후 사전 조회
        else:
            self._dict_timer.stop()
            if self._dict_popup:
                self._dict_popup.dismiss()
        super().mouseMoveEvent(event)

    # ── 전역 hover 툴팁 ──────────────────────────────────────────────
    _ANNOT_TEXT      = 0   # 스티키 메모
    _ANNOT_FREE_TEXT = 2   # FreeText
    _HOVER_TOL       = 8   # fitz pt 오차

    def _global_hover_tooltip(self, scene_pos: QPointF, event: QMouseEvent):
        """모든 도구에서 메모/텍스트 어노테이션 위 hover 시 내용 툴팁."""
        if not self._doc.is_open:
            QToolTip.hideText()
            return
        # 문서 교체 직후 이벤트가 끼어들 수 있으므로 페이지 범위 방어 +
        # 스크롤/양면 모드에서 커서 아래 실제 페이지 기준으로 매핑
        from utils.annot_mapper import resolve_page_and_fitz_pt
        page_idx, fitz_pt = resolve_page_and_fitz_pt(self, scene_pos)
        if not (0 <= page_idx < self._doc.page_count()):
            QToolTip.hideText()
            return
        try:
            page = self._doc.fitz_page(page_idx)
        except Exception:
            # 문서가 닫히는 중이거나 암호화(미인증) 상태 — 조용히 무시
            QToolTip.hideText()
            return
        t = self._HOVER_TOL
        for annot in list(page.annots()):
            try:
                atype = annot.type[0]
            except Exception:
                continue
            if atype not in (self._ANNOT_TEXT, self._ANNOT_FREE_TEXT):
                continue
            r = annot.rect
            if r.x0 - t <= fitz_pt.x <= r.x1 + t and \
               r.y0 - t <= fitz_pt.y <= r.y1 + t:
                content = annot.info.get('content', '')
                if content:
                    QToolTip.showText(
                        self.mapToGlobal(event.pos()), content, self)
                    return
        QToolTip.hideText()

    # ── 롤오버 사전 ──────────────────────────────────────────────────────
    def _on_dict_hover(self):
        """500ms 정지 후 커서 아래 단어를 사전에서 조회 (자동 숨김)."""
        self._dict_lookup_at(self._dict_hover_pos, self._dict_hover_gpos,
                             sticky=False)

    def _dict_lookup_at(self, scene_pos: QPointF | None,
                        global_pos: QPoint | None, sticky: bool = False):
        """주어진 위치의 단어를 사전 조회 후 팝업 표시."""
        from utils.dict_manager import dict_manager
        dm = dict_manager()
        if not dm.enabled:
            return

        online_mode = getattr(self._settings, 'dict_online_mode', False)

        # 온라인 모드가 아닌데 사전 미로드 → 종료
        if not online_mode and not dm.is_loaded:
            return

        word = self._word_at(scene_pos)
        if not word:
            if not sticky and self._dict_popup:
                self._dict_popup.dismiss()
            if not sticky:
                self._dict_last_word = ''
            return

        # hover일 때 같은 단어면 팝업 유지
        if not sticky and word == self._dict_last_word:
            return
        self._dict_last_word = word

        if online_mode:
            # 온라인 모드: 네이버사전에서 뜻을 받아와 바로 표시.
            # 로컬 사전이 로드돼 있으면 그 결과를 우선 사용.
            defn = dm.lookup(word) if dm.is_loaded else ''
            fetch_needed = False
            if not defn:
                from utils.online_dict import get_cached
                cached = get_cached(word)
                if cached is not None:
                    defn = cached or self._DICT_NO_RESULT_MSG
                else:
                    defn = '🔍 네이버사전 조회 중…'
                    fetch_needed = True
            if self._dict_popup is None:
                from ui.dict_popup import DictPopup
                self._dict_popup = DictPopup(settings=self._settings)
            self._dict_popup.show_at(word, defn, global_pos, sticky=sticky)
            if fetch_needed:
                self._fetch_naver_brief(word)
        else:
            # 로컬 사전 모드
            defn = dm.lookup(word)
            if defn:
                if self._dict_popup is None:
                    from ui.dict_popup import DictPopup
                    self._dict_popup = DictPopup(settings=self._settings)
                self._dict_popup.show_at(word, defn, global_pos, sticky=sticky)
            else:
                if self._dict_popup:
                    self._dict_popup.dismiss()

    _DICT_NO_RESULT_MSG = ('네이버사전에 결과가 없습니다.\n'
                           '▶ 아래 버튼으로 웹에서 검색하세요.')

    def _fetch_naver_brief(self, word: str):
        """네이버사전 간이 뜻을 백그라운드로 조회해 팝업을 갱신한다."""
        from PySide6.QtCore import QThreadPool
        from utils.online_dict import NaverBriefWorker
        worker = NaverBriefWorker(word)
        worker.signals.finished.connect(self._on_naver_brief_done)
        # 시그널 객체가 GC 되지 않도록 참조 유지 (완료 시 해제)
        refs = getattr(self, '_naver_sig_refs', None)
        if refs is None:
            refs = self._naver_sig_refs = []
        sigs = worker.signals
        refs.append(sigs)
        sigs.finished.connect(lambda *_: refs.remove(sigs)
                              if sigs in refs else None)
        QThreadPool.globalInstance().start(worker)

    def _on_naver_brief_done(self, word: str, text: str):
        """조회 완료 — 같은 단어가 아직 팝업에 떠 있으면 뜻 교체."""
        if self._dict_popup is None:
            return
        self._dict_popup.update_definition(
            word, text or self._DICT_NO_RESULT_MSG)

    def word_at_scene(self, scene_pos) -> str | None:
        """외부에서 호출 가능한 단어 추출."""
        word = self._word_at(scene_pos)
        return word if self._dict_word_allowed(word) else None

    def _dict_word_allowed(self, word: str | None) -> bool:
        word = (word or '').strip()
        if not word:
            return False
        if not getattr(self._settings, 'dict_english_only', False):
            return True
        import re as _re
        return _re.fullmatch(r"[A-Za-z][A-Za-z0-9'_-]*", word) is not None

    def _word_at(self, scene_pos: QPointF | None) -> str | None:
        """마우스 위치의 단어를 fitz로 추출한다 (사전 검색용)."""
        if scene_pos is None or not self._doc.is_open:
            return None
        try:
            # 페이지 오프셋 보정 포함 매핑 — 스크롤/양면 모드에서
            # 커서 아래 실제 페이지 기준으로 계산해야 한다
            from utils.annot_mapper import resolve_page_and_fitz_pt
            page_idx, fitz_pt = resolve_page_and_fitz_pt(self, scene_pos)
            if not (0 <= page_idx < self._doc.page_count()):
                return None
            page = self._doc.fitz_page(page_idx)

            def _char_mode(ch: str) -> str:
                if not ch:
                    return 'other'
                code = ord(ch)
                if 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF:
                    return 'hangul'
                if ch.isalpha() or ch.isdigit() or ch in ("'", '-', '_'):
                    return 'latin'
                return 'other'

            def _gap_too_wide(prev_bbox, next_bbox) -> bool:
                gap = float(next_bbox[0]) - float(prev_bbox[2])
                prev_w = max(1.0, float(prev_bbox[2]) - float(prev_bbox[0]))
                next_w = max(1.0, float(next_bbox[2]) - float(next_bbox[0]))
                return gap > max(prev_w, next_w) * 0.45

            try:
                for block in page.get_text('rawdict').get('blocks', []):
                    for line in block.get('lines', []):
                        line_rect = None
                        line_chars: list[dict] = []
                        for span in line.get('spans', []):
                            bbox = span.get('bbox')
                            if bbox:
                                rect = fitz.Rect(bbox)
                                line_rect = rect if line_rect is None else (line_rect | rect)
                            for info in span.get('chars', []):
                                if info.get('c') and info.get('bbox'):
                                    line_chars.append(info)
                        if not line_rect or not line_chars:
                            continue
                        if not (line_rect.x0 - 2 <= fitz_pt.x <= line_rect.x1 + 2 and line_rect.y0 - 2 <= fitz_pt.y <= line_rect.y1 + 2):
                            continue

                        best_idx = -1
                        best_dist = float('inf')
                        for idx, info in enumerate(line_chars):
                            x0, y0, x1, y1 = info['bbox']
                            if x0 - 1 <= fitz_pt.x <= x1 + 1 and y0 - 1 <= fitz_pt.y <= y1 + 1:
                                best_idx = idx
                                break
                            cx = (x0 + x1) * 0.5
                            cy = (y0 + y1) * 0.5
                            dist = abs(cx - fitz_pt.x) + abs(cy - fitz_pt.y) * 1.8
                            if dist < best_dist:
                                best_dist = dist
                                best_idx = idx
                        if best_idx < 0:
                            continue

                        seed = line_chars[best_idx].get('c', '')
                        seed_mode = _char_mode(seed)
                        if seed_mode == 'other':
                            continue

                        left = best_idx
                        while left > 0:
                            prev_char = line_chars[left - 1].get('c', '')
                            if _char_mode(prev_char) != seed_mode:
                                break
                            if _gap_too_wide(line_chars[left - 1]['bbox'], line_chars[left]['bbox']):
                                break
                            left -= 1

                        right = best_idx
                        while right + 1 < len(line_chars):
                            next_char = line_chars[right + 1].get('c', '')
                            if _char_mode(next_char) != seed_mode:
                                break
                            if _gap_too_wide(line_chars[right]['bbox'], line_chars[right + 1]['bbox']):
                                break
                            right += 1

                        word = ''.join(info.get('c', '') for info in line_chars[left:right + 1]).strip()
                        word = word.strip(".,!?;:\"'()[]{}")
                        if word:
                            normalized = _normalize_lookup_word(word)
                            return normalized if self._dict_word_allowed(normalized) else None
            except Exception:
                swallowed()

            for w_info in page.get_text('words'):
                x0, y0, x1, y1, word = w_info[:5]
                if x0 - 3 <= fitz_pt.x <= x1 + 3 and y0 - 3 <= fitz_pt.y <= y1 + 3:
                    best = _best_lookup_word_at(word, fitz_pt.x, x0, x1)
                    normalized = _normalize_lookup_word(best or word.strip())
                    return normalized if self._dict_word_allowed(normalized) else None
        except Exception:
            swallowed()
        return None
    def selected_text_for_dict(self) -> str:
        text = (self._dict_selected_text or '').strip()
        return text if self._dict_word_allowed(text) else ''

    def _text_in_scene_rect(self, scene_rect: QRectF) -> str:
        if not self._doc.is_open or scene_rect.isNull():
            return ''
        try:
            from utils.annot_mapper import resolve_page_and_fitz_rect
            page_idx, sel = resolve_page_and_fitz_rect(self, scene_rect)
            if not (0 <= page_idx < self._doc.page_count()):
                return ''
            page = self._doc.fitz_page(page_idx)
            words = []
            for w in page.get_text('words'):
                x0, y0, x1, y1, token = w[:5]
                wr = fitz.Rect(x0, y0, x1, y1)
                if not token or not wr.intersects(sel):
                    continue
                words.append((round(y0, 1), x0, token.strip()))
            words.sort(key=lambda item: (item[0], item[1]))
            tokens = [token for _, _, token in words if token]
            return _normalize_lookup_word(_join_word_tokens(tokens)) if tokens else ''
        except Exception:
            return ''

    def mouseReleaseEvent(self, event: QMouseEvent):
        # ── 영역 캡처 모드: 선택 완료 → 캡처 ────────────────────
        if self._region_capture_mode and event.button() == Qt.MouseButton.LeftButton:
            if self._region_rubber_band:
                self._region_rubber_band.hide()
            if self._region_rb_start is not None:
                grab_rect = QRect(self._region_rb_start, event.pos()).normalized()
                if grab_rect.width() > 4 and grab_rect.height() > 4:
                    # 뷰포트 기준 좌표에서 실제 픽스맵 캡처
                    px = self.viewport().grab(grab_rect)
                    if not px.isNull():
                        self.region_captured.emit(px)
            self._region_capture_mode = False
            self._region_rb_start = None
            self.viewport().unsetCursor()
            return

        pos = self.mapToScene(event.pos())
        if event.button() == Qt.MouseButton.LeftButton and self._dict_drag_anchor is not None:
            drag_rect = QRectF(self._dict_drag_anchor, pos).normalized()
            self._dict_selected_text = self._text_in_scene_rect(drag_rect) if (drag_rect.width() > 6 or drag_rect.height() > 6) else ''
            self._dict_drag_anchor = None
        if not self._tool_blocked():
            try:
                self._tool.on_release(pos, event, self)
            except Exception as e:
                import logging
                logging.getLogger('pdf_editor').error(f'[Canvas] on_release error: {e}')
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        pos = self.mapToScene(event.pos())
        # 먼저 도구의 더블클릭 처리 시도 (어노테이션 편집 등)
        handled = False
        if hasattr(self._tool, 'on_double_click') and not self._tool_blocked():
            result = self._tool.on_double_click(pos, event, self)
            handled = bool(result)
        # 본문 편집은 '본문편집' 모드를 켠 뒤에만 동작한다. 모드를 켜지 않았는데
        # 더블클릭만으로 옛 한 줄 편집기가 떠서 의도치 않게 글자가 바뀌던 문제를
        # 막는다. 모드가 켜져 있으면 단일 클릭과 같은 문단 편집으로 연결한다.
        if not handled and isinstance(self._tool, SelectTool) \
                and self._text_edit_mode and not self._edit_locked:
            self._edit_text_block(pos, click_scene=pos)
        elif not handled:
            super().mouseDoubleClickEvent(event)

    def set_edit_locked(self, locked: bool):
        """권한 제한 문서에서 본문 편집과 주석 그리기를 잠근다."""
        self._edit_locked = bool(locked)
        if locked:
            self._text_edit_mode = False
            self._clear_edit_hover()
            # 이미 그리기 도구가 잡혀 있으면 선택 도구로 되돌린다
            if not isinstance(self._tool, SelectTool):
                self.set_tool(SelectTool())

    def _tool_blocked(self) -> bool:
        """지금 도구로 문서를 고칠 수 없는 상태인가 (권한 제한)."""
        if not getattr(self, '_edit_locked', False):
            return False
        return not isinstance(self._tool, SelectTool)

    def set_text_edit_mode(self, on: bool):
        """본문 편집 모드 토글. 켜면 클릭한 문단(블록) 전체를 여러 줄로 편집."""
        self._text_edit_mode = bool(on)
        if on:
            # 편집이 되려면 선택 도구가 활성이어야 함 + I-beam 커서
            if not isinstance(self._tool, SelectTool):
                self.set_tool(SelectTool())
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.viewport().unsetCursor()
            self._inline_ed._hide_all()
            self._inline_block_ed._hide_all()
            self._clear_edit_hover()

    # ── PDF 본문 텍스트 인라인 편집 ──────────────────────────────────
    def _try_inline_text_edit(self, scene_pos: QPointF):
        """더블클릭 위치의 PDF 텍스트 스팬을 찾아 인라인 에디터를 띄운다.
        본문 편집 모드면 문단(블록) 전체를 여러 줄로 편집한다."""
        if not self._doc.is_open or self._inline_ed is None:
            return
        if getattr(self, '_edit_locked', False):
            return   # 권한 제한 문서 — 본문 편집 금지
        if self._text_edit_mode:
            self._edit_text_block(scene_pos)
            return
        from utils.annot_mapper import scene_to_fitz_pt
        fitz_pt = scene_to_fitz_pt(scene_pos, self.zoom())
        page    = self._doc.fitz_page(self._cur_page)

        # 커서 위치의 텍스트 스팬 + 해당 줄(line) 전체 찾기
        target_span = None
        target_line_spans: list = []
        target_rect = None
        try:
            blocks = page.get_text('dict')['blocks']
            for b in blocks:
                for line in b.get('lines', []):
                    for span in line.get('spans', []):
                        r = fitz.Rect(span['bbox'])
                        if (r.x0 - 2 <= fitz_pt.x <= r.x1 + 2 and
                                r.y0 - 2 <= fitz_pt.y <= r.y1 + 2):
                            target_span = span
                            target_line_spans = line.get('spans', [span])
                            break
                    if target_span:
                        break
                if target_span:
                    break
        except Exception as e:
            print(f'[InlineEdit] 텍스트 감지 오류: {e}')
            return

        if target_span is None:
            return
        # 같은 줄의 모든 스팬을 합쳐 공백 포함 전체 라인 텍스트 재구성
        # 우선 words 추출로 단어 간 공백을 복원하고, 실패 시 스팬 gap 휴리스틱으로 폴백
        def _join_spans(spans: list) -> str:
            if not spans:
                return ''
            line_rect = fitz.Rect(spans[0]['bbox'])
            for span in spans[1:]:
                line_rect |= fitz.Rect(span['bbox'])

            try:
                words = []
                for w in page.get_text('words'):
                    x0, y0, x1, y1, token = w[:5]
                    wr = fitz.Rect(x0, y0, x1, y1)
                    if wr.y1 < line_rect.y0 - 1 or wr.y0 > line_rect.y1 + 1:
                        continue
                    if wr.x1 < line_rect.x0 - 2 or wr.x0 > line_rect.x1 + 2:
                        continue
                    token = (token or '').strip()
                    if token:
                        words.append((x0, token))
                words.sort(key=lambda item: item[0])
                if words:
                    return _join_word_tokens([token for _, token in words])
            except Exception:
                swallowed()

            parts = [spans[0].get('text', '')]
            for prev, curr in zip(spans, spans[1:]):
                gap = curr['bbox'][0] - prev['bbox'][2]
                txt_len = max(1, len(prev.get('text', 'x').strip()) or 1)
                char_w = max(1.0, (prev['bbox'][2] - prev['bbox'][0]) / txt_len)
                parts.append(' ' if gap >= char_w * 0.18 else '')
                parts.append(curr.get('text', ''))
            return ''.join(parts).strip()

        text = _join_spans(target_line_spans)

        text = _join_spans(target_line_spans)
        if not text:
            text = target_span.get('text', '').strip()
        if not text:
            return

        # 전체 라인의 bounding rect (리댁트/위치 기준으로 사용)
        if len(target_line_spans) > 1:
            all_bboxes = [fitz.Rect(s['bbox']) for s in target_line_spans]
            target_rect = all_bboxes[0]
            for br in all_bboxes[1:]:
                target_rect = target_rect | br
        else:
            target_rect = fitz.Rect(target_span['bbox'])

        fs = float(target_span.get('size', 11))

        # 스팬 rect → 뷰포트 좌표 변환
        zoom = self.zoom()   # BASE_RENDER_ZOOM (1.5)
        tl = self.mapFromScene(QPointF(target_rect.x0 * zoom,
                                       target_rect.y0 * zoom))
        br = self.mapFromScene(QPointF(target_rect.x1 * zoom,
                                       target_rect.y1 * zoom))

        w = max(120, int(br.x() - tl.x()) + 40)
        h = max(26,  int(br.y() - tl.y()) + 10)

        ed = self._inline_ed
        ed.fitz_rect     = fitz.Rect(target_rect)
        ed.fs            = fs
        ed.original_text = text
        ed._committed    = False
        # 첫 스팬의 origin (실제 베이스라인 좌표) 저장
        ed.origin = target_span.get('origin')
        # 색·글꼴 자동 감지
        ed.text_color = _span_color_rgb(target_span)
        ed.font_key   = _detect_inline_font_index(target_span)
        ed.orig_font  = target_span.get('font', '')

        # 깨진 텍스트 감지 (폰트 설정 전에 먼저 판단)
        garbled = _looks_garbled(text)

        # 글꼴: 한글 포함 시 또는 garbled(PDF 인코딩 문제) 시에도
        # Malgun Gothic 사용 → 한글 IME 입력이 에디터에서 바로 보임
        from PySide6.QtGui import QFont
        # 감지된 글꼴로 미리보기 (깨진 텍스트는 IME 입력이 보이도록 맑은 고딕)
        if garbled:
            fam = 'Malgun Gothic'
        else:
            fam = _INLINE_FONT_OPTIONS[ed.font_key][3]
        f = QFont(fam)
        f.setPointSizeF(max(6.0, fs * self._zoom))
        ed.setFont(f)

        ed.set_warning(garbled)
        display_text = '' if garbled else text

        # 글꼴 선택 바: 에디터 바로 위에 표시
        bar = self._inline_font_bar
        bar_w = max(w, 170)
        bar_y = max(0, int(tl.y()) - 30)
        bar.setFixedWidth(bar_w)
        bar.setGeometry(int(tl.x()), bar_y, bar_w, 28)
        bar._combo.blockSignals(True)
        bar._combo.setCurrentIndex(ed.font_key)
        bar._combo.blockSignals(False)
        bar.show()
        bar.raise_()

        ed.setGeometry(int(tl.x()), int(tl.y()), w, h)
        ed.setText(display_text)
        if not garbled:
            ed.selectAll()
        ed.setPlaceholderText('한글(또는 새 텍스트) 입력 후 Enter' if garbled else '')
        ed.show()
        ed.raise_()
        ed.setFocus()

    def _on_inline_committed(self, new_text: str):
        """인라인 에디터 확정 → redact + insert 적용."""
        ed = self._inline_ed
        if ed is None or ed.fitz_rect is None:
            return
        original = ed.original_text
        fitz_rect = ed.fitz_rect
        fs        = ed.fs

        # 변경 없으면 무시
        if new_text == original:
            return

        # 본문 편집은 콘텐츠 스트림을 직접 고치므로 어노테이션처럼 xref 하나를
        # 지워서 되돌릴 수 없다. 고치기 전 페이지를 통째로 떠 둔다 (Ctrl+Z)
        self._doc.push_page_snapshot(ed.page_idx)

        page = self._doc.fitz_page(self._cur_page)
        # fill=None → 지운 영역을 흰색으로 채우지 않고 투명(배경 유지)으로 처리
        # 흰 박스가 도드라져 보이는 현상 방지
        page.add_redact_annot(fitz_rect, fill=None)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        if new_text.strip():
            # origin[1] 은 fitz 가 저장한 실제 베이스라인 Y — 이것을 우선 사용
            origin = ed.origin
            if origin and len(origin) >= 2:
                x0, baseline_y = float(origin[0]), float(origin[1])
            else:
                x0 = fitz_rect.x0
                baseline_y = fitz_rect.y1 - max(1.0, (fitz_rect.height - fs) * 0.5)
            pt = fitz.Point(x0, baseline_y)
            try:
                color = getattr(ed, 'text_color', (0, 0, 0))
                # 원본 글꼴 계열 유지 (라틴=base-14, 한글=선택 폰트) → 크기 일치
                fpath, fname = _pick_insert_font(new_text, getattr(ed, 'orig_font', ''),
                                                 getattr(ed, 'font_key', 0))
                kw = dict(fontsize=fs, color=color, fontname=fname)
                if fpath:
                    kw['fontfile'] = fpath
                page.insert_text(pt, new_text, **kw)
            except Exception as e:
                print(f'[InlineEdit] insert 오류: {e}')
                try:
                    page.add_freetext_annot(fitz_rect, new_text,
                                            fontsize=fs, text_color=color)
                except Exception:
                    swallowed()

        self._doc.mark_dirty()
        self._renderer.invalidate(self._cur_page)
        self._para_rect_cache.pop(self._cur_page, None)
        # 에디터 참조 초기화 (scene 재렌더 전)
        ed.fitz_rect = None
        self.refresh_page()

    # ── 본문 텍스트 블록(문단) 여러 줄 편집 ──────────────────────────
    @staticmethod
    def _qt_family_for(orig_font: str, has_ko: bool) -> str:
        """원본 글꼴명 → 화면 표시용 Qt 글꼴 (문서와 비슷하게 보이도록)."""
        n = (orig_font or '').lower()
        if has_ko:
            if any(k in n for k in ('batang', 'myeongjo', 'mincho', '바탕', '명조', 'serif')):
                return '바탕'
            return 'Malgun Gothic'
        if any(k in n for k in ('times', 'serif', 'roman', 'georgia', 'minion', 'garamond', 'batang', 'myeongjo')):
            return 'Times New Roman'
        if any(k in n for k in ('courier', 'mono', 'consol')):
            return 'Consolas'
        return 'Arial'

    def _paragraph_rects(self, page_idx: int) -> list:
        """페이지의 문단 사각형 목록(fitz.Rect) — 인접 줄/블록을 문단으로 병합."""
        if page_idx in self._para_rect_cache:
            return self._para_rect_cache[page_idx]
        rects = []
        try:
            blocks = [b for b in self._doc.fitz_page(page_idx).get_text('dict')['blocks']
                      if b.get('type', 0) == 0 and b.get('lines')]
        except Exception:
            self._para_rect_cache[page_idx] = []
            return []

        def _lh(b):
            hs = [fitz.Rect(l['spans'][0]['bbox']).height
                  for l in b['lines'] if l.get('spans')]
            return (sum(hs) / len(hs)) if hs else 12.0

        blocks.sort(key=lambda b: b['bbox'][1])
        cur = None; prevb = None
        for b in blocks:
            bb = b['bbox']
            if cur is None:
                cur = fitz.Rect(bb); prevb = b; continue
            gap = bb[1] - prevb['bbox'][3]
            ov_w = min(bb[2], cur.x1) - max(bb[0], cur.x0)
            ov = ov_w / max(1.0, min(bb[2] - bb[0], cur.width))
            # '요 약' 같은 짧은 가운데 제목이 아래 본문과 한 문단으로 묶여 함께
            # 재배치되는 것을 막는다. 단, 폭이 좁아도 왼쪽이 문단과 맞으면
            # 본문의 마지막 줄이므로 그대로 병합한다.
            w_new = bb[2] - bb[0]
            w_ratio = min(w_new, cur.width) / max(1.0, max(w_new, cur.width))
            left_ok = abs(bb[0] - cur.x0) < max(3.0, _lh(prevb) * 0.8)
            if gap < _lh(prevb) * 0.7 and ov > 0.35 and (w_ratio > 0.5 or left_ok):
                cur |= fitz.Rect(bb); prevb = b
            else:
                rects.append(cur); cur = fitz.Rect(bb); prevb = b
        if cur is not None:
            rects.append(cur)
        self._para_rect_cache[page_idx] = rects
        return rects

    def _update_edit_hover(self, scene_pos: QPointF):
        """편집 모드에서 커서 아래 문단에 사각형 표시."""
        if not self._doc.is_open:
            return
        from utils.annot_mapper import resolve_page_and_fitz_pt
        page_idx, fitz_pt = resolve_page_and_fitz_pt(self, scene_pos)
        if not (0 <= page_idx < self._doc.page_count()):
            self._clear_edit_hover(); return
        hit = None
        for r in self._paragraph_rects(page_idx):
            if r.x0 - 2 <= fitz_pt.x <= r.x1 + 2 and r.y0 - 2 <= fitz_pt.y <= r.y1 + 2:
                hit = r; break
        if hit is None:
            self._clear_edit_hover(); return
        z = self.zoom(); off = self.page_offset(page_idx)
        srect = QRectF(hit.x0 * z + off.x(), hit.y0 * z + off.y(),
                       hit.width * z, hit.height * z).adjusted(-3, -3, 3, 3)
        from PySide6.QtWidgets import QGraphicsRectItem
        item = self._edit_hover_item
        try:
            if item is None:
                raise RuntimeError
            item.setRect(srect); item.show()
        except RuntimeError:
            item = QGraphicsRectItem()
            item.setPen(QPen(QColor(124, 92, 232, 220), 1.4))
            item.setBrush(QBrush(QColor(150, 120, 240, 26)))
            item.setZValue(50)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.scene().addItem(item)
            item.setRect(srect)
            self._edit_hover_item = item

    def _clear_edit_hover(self):
        it = self._edit_hover_item
        if it is not None:
            try:
                it.hide()
            except RuntimeError:
                self._edit_hover_item = None

    def _edit_text_block(self, scene_pos: QPointF, click_scene: QPointF = None):
        """클릭한 문단(블록) 전체를 제자리에서(WYSIWYG) 편집. 정렬 자동 감지."""
        from utils.annot_mapper import resolve_page_and_fitz_pt
        page_idx, fitz_pt = resolve_page_and_fitz_pt(self, scene_pos)
        try:
            page = self._doc.fitz_page(page_idx)
            blocks = page.get_text('dict')['blocks']
        except Exception:
            return
        # 호버가 보여주는 것과 똑같은 문단 사각형을 사용해 편집 영역을 일치시킨다.
        block_rect = None
        for pr in self._paragraph_rects(page_idx):
            if (pr.x0 - 2 <= fitz_pt.x <= pr.x1 + 2 and
                    pr.y0 - 2 <= fitz_pt.y <= pr.y1 + 2):
                block_rect = fitz.Rect(pr)
                break
        if block_rect is None:
            # 문단 캐시에 없으면 클릭한 단일 블록으로 폴백
            for b in blocks:
                if b.get('type', 0) != 0 or not b.get('lines'):
                    continue
                r = fitz.Rect(b['bbox'])
                if (r.x0 - 3 <= fitz_pt.x <= r.x1 + 3 and
                        r.y0 - 3 <= fitz_pt.y <= r.y1 + 3):
                    block_rect = r
                    break
        if block_rect is None:
            return

        # ── 텍스트: 글자 위치 기반으로 시각적 행을 복원(공백 없는 한글
        #    조판 PDF도 사람이 보는 대로) ──
        read_rect = block_rect + (-1, -1, 1, 1)
        # 이전 편집으로 흰 덮개에 가려진 옛 글자는 제외하고 읽는다
        # (그대로 두면 새 글자와 뒤섞여 편집창에 중첩되어 나타난다).
        rows = _para_visual_rows(page, read_rect,
                                 skip=self._ghost_skip_counts(page_idx))
        if rows:
            if self._reflow_mode:
                # 캔바식: 문단을 하나의 흐르는 글로 (자유 줄바꿈)
                _rm = max([r['x1'] for r in rows] + [block_rect.x1])
                text = _flow_text_from_rows(rows, _rm)
            else:
                text = '\n'.join(r['text'] for r in rows).strip()
        else:
            text = page.get_textbox(read_rect).rstrip('\n').rstrip()
        if not text.strip():
            return

        # 저장 시 각 줄을 원래 위치에 그대로 되돌리기 위해 행 기하를 보관한다.
        # (내어쓰기·각주·양쪽정렬 등 복잡한 배치도 그대로 보존)
        self._block_rows = rows
        # 정렬·줄간격(줄 수가 바뀐 편집에서만 쓰는 폴백용)
        align, lineheight = _detect_para_layout(rows, block_rect)

        # 스타일(글꼴/크기/색/굵기)용 첫 스팬 + 대표 크기 수집
        sizes, first_span = [], None
        for b in blocks:
            if b.get('type', 0) != 0:
                continue
            for line in b.get('lines', []):
                spans = [s for s in line.get('spans', [])
                         if fitz.Rect(s['bbox']).intersects(block_rect)]
                if not spans:
                    continue
                if first_span is None:
                    first_span = spans[0]
                sizes.extend(s.get('size', 11) for s in spans)
        if first_span is None:
            return
        fs = float(sorted(sizes)[len(sizes) // 2]) if sizes else 11.0

        ed = self._inline_block_ed
        ed.fitz_rect = block_rect
        ed.fs = fs
        ed.original_text = text
        ed.page_idx = page_idx
        ed.align = align
        ed.lineheight = lineheight
        ed.text_color = _span_color_rgb(first_span)
        ed.font_key = _detect_inline_font_index(first_span)
        ed.orig_font = first_span.get('font', '')
        _flags = int(first_span.get('flags', 0))
        ed.bold = bool(_flags & 16) or 'bold' in (ed.orig_font or '').lower()
        ed.italic = bool(_flags & 2)
        ed.underline = False

        # 위치/크기 (페이지 오프셋 보정)
        zoom = self.zoom()
        offset = self.page_offset(page_idx)
        tl = self.mapFromScene(QPointF(block_rect.x0 * zoom + offset.x(),
                                       block_rect.y0 * zoom + offset.y()))
        br = self.mapFromScene(QPointF(block_rect.x1 * zoom + offset.x(),
                                       block_rect.y1 * zoom + offset.y()))
        # 화면 픽셀 크기로 상자·글꼴을 맞춰 문서 글자와 똑같이 보이게 한다.
        # (씬은 _BASE_RENDER_ZOOM 로 렌더 후 뷰 트랜스폼 self._zoom 으로 표시)
        pad = 6
        w = max(60, int(br.x() - tl.x()) + pad * 2)
        h = max(24, int(br.y() - tl.y()) + pad * 2)

        ed.document().setDocumentMargin(1)
        self._refresh_block_font()   # 감지된 글꼴·크기·굵기·색으로 표시

        # 서식 툴바 채우기 + 위치
        bar = self._inline_font_bar
        for wdg, val in ((bar._combo, ed.font_key), (bar._size, int(round(fs))),
                         (bar._bold, ed.bold), (bar._italic, ed.italic),
                         (bar._underline, ed.underline)):
            wdg.blockSignals(True)
        bar._combo.setCurrentIndex(max(0, min(ed.font_key, len(_INLINE_FONT_OPTIONS) - 1)))
        bar._size.setValue(max(4, min(400, int(round(fs)))))
        bar._bold.setChecked(ed.bold)
        bar._italic.setChecked(ed.italic)
        bar._underline.setChecked(ed.underline)
        for wdg in (bar._combo, bar._size, bar._bold, bar._italic, bar._underline):
            wdg.blockSignals(False)
        _cc = QColor(int(ed.text_color[0]*255), int(ed.text_color[1]*255), int(ed.text_color[2]*255))
        bar._color.setStyleSheet(f'background:{_cc.name()}; border:1px solid #888; border-radius:3px;')
        for i, ab in enumerate(bar._align):
            ab.setChecked(i == ed.align)
        bar.adjustSize()
        bar.setGeometry(int(tl.x()) - pad, max(0, int(tl.y()) - pad - 34),
                        bar.sizeHint().width(), 30)
        bar._reflow.blockSignals(True)
        bar._reflow.setChecked(self._reflow_mode)
        bar._reflow.blockSignals(False)
        bar.show(); bar.raise_()
        self._notify_reflow_state()

        # 원본 글자를 정확히 덮도록 padding 만큼 위/왼쪽으로 당겨 배치
        ed.setGeometry(int(tl.x()) - pad, int(tl.y()) - pad, w, h)
        ed.setPlainText(text)
        ed.setToolTip('입력 후 다른 곳 클릭 또는 Ctrl+Enter=확정  ·  Esc=취소')
        ed.show(); ed.raise_(); ed.setFocus()
        # 클릭한 위치에 커서를 놓는다 (제자리 편집 느낌)
        try:
            cp = click_scene if click_scene is not None else scene_pos
            local = ed.mapFromGlobal(self.viewport().mapToGlobal(
                self.mapFromScene(cp)))
            ed.setTextCursor(ed.cursorForPosition(local))
        except Exception:
            cur = ed.textCursor(); cur.movePosition(cur.MoveOperation.End); ed.setTextCursor(cur)

    def _mark_covered(self, page_idx: int, band) -> None:
        """편집으로 흰 덮개를 씌운 영역을 기록한다.

        덮개 아래의 옛 글자는 화면에서 안 보이지만 텍스트층에는 남는다. 새로
        그린 글자도 같은 자리에 오므로 좌표만으로는 구분할 수 없다. 그래서
        '이 영역에서 덮개 시점까지 존재하던 글자 수'를 함께 남겨, 이후 읽을 때
        앞의 그만큼을 옛 글자로 보고 건너뛴다(그 뒤가 새로 그린 글자)."""
        d = getattr(self, '_covered_bands', None)
        if d is None:
            d = self._covered_bands = {}
        n_old = 0
        try:
            page = self._doc.fitz_page(page_idx)
            raw = page.get_text('rawdict', clip=fitz.Rect(band))
            for b in raw.get('blocks', []):
                if b.get('type', 0) != 0:
                    continue
                for ln in b.get('lines', []):
                    for sp in ln.get('spans', []):
                        n_old += len(sp.get('chars', []))
        except Exception:
            n_old = 0
        bands = d.setdefault(int(page_idx), [])
        bx0, by0 = float(band.x0), float(band.y0)
        bx1, by1 = float(band.x1), float(band.y1)
        # 같은 자리를 다시 편집하면 기록을 '갱신'한다. 누적하면 옛 글자 수가
        # 계속 늘어나 새로 그린 글자까지 건너뛰게 된다.
        for st in bands:
            if (abs(st[0] - bx0) < 2 and abs(st[1] - by0) < 2
                    and abs(st[2] - bx1) < 2 and abs(st[3] - by1) < 2):
                st[4] = n_old
                return
        bands.append([bx0, by0, bx1, by1, n_old])

    def _ghost_skip_counts(self, page_idx: int) -> list:
        """해당 페이지의 (덮개 영역, 건너뛸 옛 글자 수) 목록."""
        return (getattr(self, '_covered_bands', None) or {}).get(int(page_idx), [])


    def _place_rows_in_place(self, page, rows, new_lines, ed, right_limit=None):
        """편집된 각 줄을 원본 줄 위치(왼쪽 x·기준선)에 그대로 되돌린다.

        insert_text 로 줄바꿈 없이 배치하므로 내어쓰기·각주·양쪽정렬 등
        복잡한 배치도 형태가 보존된다. 줄마다 내용에 맞는 글꼴(라틴/한글)과
        굵기를 골라 'design'→글자깨짐 같은 대체 오류도 막는다."""
        import logging
        log = logging.getLogger('pdf_editor')
        for r, txt in zip(rows, new_lines):
            txt = txt.rstrip()
            if not txt:
                continue
            fpath, fname = _pick_insert_font(
                txt, r.get('font', '') or ed.orig_font, ed.font_key,
                bold=r.get('bold', False), italic=False)
            # 고른 글꼴이 못 그리는 글자(ü·é·— 등)가 있으면 한글+라틴을 모두
            # 갖춘 글꼴로 대체 → 조용히 □ 로 깨지는 것을 막는다.
            if not _font_covers(fpath, fname, txt):
                bp, bn = _broad_font_for(txt)
                if bp:
                    fpath, fname = bp, bn
            # ── 줄이 문단 오른쪽 여백을 넘지 않게 맞춘다 ──
            # insert_text 는 줄바꿈을 하지 않으므로, 글자를 보태면 그대로 상자
            # 밖으로 삐져나간다. 글자 크기가 줄면 주변 글자와 달라 보여 눈에
            # 띄므로, 크기는 되도록 유지하고 가로로만 살짝 조인다. 한 줄에 도저히
            # 안 들어갈 만큼 길 때만 최소한으로 크기를 줄인다.
            fs = float(r['fs'])
            sx = 1.0
            avail = (right_limit or r['x1']) - r['x0']
            fobj = _font_obj(fpath, fname)
            if fobj is not None and avail > 1:
                try:
                    w = fobj.text_length(txt, fontsize=fs)
                except Exception:
                    w = 0
                if w > avail > 0:
                    ratio = avail / w
                    if ratio >= _SQUEEZE_MIN:
                        sx = ratio              # 크기 유지 — 가로로만 조임
                    else:
                        # 압축만으로는 티가 날 만큼 길다 → 크기를 조금 줄이고
                        # 나머지는 압축으로 흡수(축소 폭을 최소화).
                        fs = max(fs * 0.72, fs * ratio / _SQUEEZE_MIN)
                        try:
                            w = fobj.text_length(txt, fontsize=fs)
                        except Exception:
                            swallowed()
                        if w > avail:
                            sx = max(_SQUEEZE_MIN, avail / w)
            kw = dict(fontsize=fs, color=ed.text_color, fontname=fname)
            if fpath:
                kw['fontfile'] = fpath
            if sx < 1.0:                        # 기준점(줄 시작)을 축으로 가로 압축
                kw['morph'] = (fitz.Point(r['x0'], r['baseline']),
                               fitz.Matrix(sx, 1))
            try:
                page.insert_text((r['x0'], r['baseline']), txt, **kw)
            except Exception as exc:
                log.warning('[BlockEdit place] %s', exc)

    def _hanging_items(self, rows):
        """내어쓰기 문단(각주)을 항목 단위로 나눈다.

        왼쪽 여백에서 시작하는 줄이 새 항목의 첫 줄이다('*', '**' …).
        반환: [[row, ...], ...]"""
        if not rows:
            return []
        import statistics as _st
        fs = _st.median(r['fs'] for r in rows) or 10.0
        tol = max(1.5, fs * 0.35)
        # 이어지는 줄(들여쓴 줄)이 가장 오른쪽에서 시작한다. 그보다 왼쪽에서
        # 시작하는 줄이 새 항목의 첫 줄('*', '**' 처럼 별표 수에 따라 위치가
        # 조금씩 다르다).
        cont_x = max(r['x0'] for r in rows)
        items, cur = [], []
        for r in rows:
            if cur and r['x0'] < cont_x - tol:
                items.append(cur)
                cur = []
            cur.append(r)
        if cur:
            items.append(cur)
        return items

    def _hanging_cont_x(self, rows) -> float:
        """내어쓰기 문단에서 '이어지는 줄'이 시작하는 x."""
        return max(r['x0'] for r in rows) if rows else 0.0

    def _reflow_hanging(self, page, rows, new_lines, ed, rect) -> bool:
        """각주처럼 내어쓰기 구조인 문단을 항목별로 다시 흘린다.

        편집된 항목만 줄을 다시 나누고, 줄 수가 늘면 아래 항목들을 그만큼
        내려 배치한다. 항목의 첫 줄은 원래 별표 위치에서, 이어지는 줄은 원래
        들여쓰기 위치에서 시작하므로 각주 모양이 그대로 유지된다.
        성공하면 True, 공간이 부족하는 등 처리하지 못하면 False.
        """
        from utils.pdf_text_edit import erase_text_area, wrap_text
        import statistics as _st

        items = self._hanging_items(rows)
        if not items or len(rows) != len(new_lines):
            return False
        # 편집된 텍스트를 항목별로 다시 모은다
        idx = 0
        item_texts = []
        for it in items:
            parts = new_lines[idx:idx + len(it)]
            idx += len(it)
            s = ''
            for t in parts:
                s = _join_seam(s, (t or '').strip())
            item_texts.append(s.strip())

        right = max([r['x1'] for r in rows] + [rect.x1])
        cont_x = self._hanging_cont_x(rows)
        fs = float(_st.median(r['fs'] for r in rows) or ed.fs)
        # 줄 간격: 원본 기준선 간격의 중앙값
        bases = sorted(r['baseline'] for r in rows)
        gaps = [b - a for a, b in zip(bases, bases[1:]) if b - a > fs * 0.4]
        step = _st.median(gaps) if gaps else fs * 1.4

        # 항목별로 줄을 다시 나눈다
        wrapped = []
        for it, txt in zip(items, item_texts):
            fpath, fname = _pick_insert_font(
                txt, it[0].get('font', '') or ed.orig_font, ed.font_key,
                bold=it[0].get('bold', False), italic=False)
            if not _font_covers(fpath, fname, txt):
                bp, bn = _broad_font_for(txt)
                if bp:
                    fpath, fname = bp, bn
            fobj = _font_obj(fpath, fname)
            if fobj is None:
                return False
            lines = wrap_text(txt, fobj, fs,
                              [right - it[0]['x0'], right - cont_x])
            wrapped.append((lines, fpath, fname, it))

        total = sum(len(w[0]) for w in wrapped)
        first_base = rows[0]['baseline']
        # 페이지 아래로 넘치면 처리하지 않는다(아래 내용을 침범하지 않도록)
        if first_base + (total - 1) * step > page.rect.y1 - 6:
            return False

        # 옛 글자를 지우고 새로 배치
        area = fitz.Rect(rect.x0, min(rect.y0, first_base - fs * 1.2),
                         max(rect.x1, right), rect.y1 + 1)
        if not erase_text_area(page, area):
            page.draw_rect(area, color=None, fill=(1, 1, 1))
            self._mark_covered(ed.page_idx, area)

        import logging
        log = logging.getLogger('pdf_editor')
        y = first_base
        for lines, fpath, fname, it in wrapped:
            for i, ln in enumerate(lines):
                x = it[0]['x0'] if i == 0 else cont_x
                kw = dict(fontsize=fs, color=ed.text_color, fontname=fname)
                if fpath:
                    kw['fontfile'] = fpath
                try:
                    page.insert_text((x, y), ln, **kw)
                except Exception as exc:
                    log.warning('[Hanging] %s', exc)
                y += step
        return True

    def _merge_lines_for_reflow(self, text: str, rows) -> str:
        """재흐름 전에 편집창의 줄들을 한 문단으로 합친다.

        빈 줄은 문단 구분으로 보아 유지하고, 나머지는 한국어 이음매 규칙으로
        이어 붙인다. 원본 문단이 첫 줄 들여쓰기였으면 그것도 살린다."""
        lines = (text or '').split('\n')
        paras, cur = [], ''
        for t in lines:
            t = t.strip()
            if not t:
                if cur:
                    paras.append(cur)
                    cur = ''
                continue
            cur = _join_seam(cur, t)
        if cur:
            paras.append(cur)
        if not paras:
            return text
        # 원본 첫 줄이 들여쓰기였으면 유지(문단 시작이 눈에 보이게)
        try:
            if rows and len(rows) >= 2:
                import statistics as _st
                body_left = min(r['x0'] for r in rows)
                fs_r = _st.median(r['fs'] for r in rows) or 10.0
                if rows[0]['x0'] - body_left > fs_r * 0.5:
                    paras[0] = '　' + paras[0]
        except Exception:
            swallowed()
        return '\n'.join(paras)

    def _lines_fit_in_place(self, rows, new_lines, ed, rect) -> bool:
        """편집한 줄들을 원래 자리에 그대로 넣을 수 있는지 판단한다.

        한 줄에 억지로 욱여넣으면 글자를 조이거나 크기를 줄여야 해서 주변과
        달라 보인다. 조임 한계를 넘을 만큼 길어졌으면 False 를 돌려주어, 문단
        전체를 다시 흘려(다음 줄로 자연스럽게 넘어가게) 배치하도록 한다."""
        # 각주처럼 내어쓰기 구조는 일반 재흐름(insert_textbox)으로는 항목 구분과
        # 들여쓰기가 무너진다. 대신 항목별 재흐름(_reflow_hanging)이 처리하므로
        # 여기서는 '제자리로 충분한지'만 따져 넘긴다.
        try:
            self._hanging_mode = _rows_have_hanging_indent(rows)
        except Exception:
            self._hanging_mode = False
        try:
            right_limit = max([r['x1'] for r in rows] + [rect.x1])
            for r, txt in zip(rows, new_lines):
                txt = (txt or '').rstrip()
                if not txt or txt == r['text'].rstrip():
                    continue
                avail = right_limit - r['x0']
                if avail <= 1:
                    continue
                fpath, fname = _pick_insert_font(
                    txt, r.get('font', '') or ed.orig_font, ed.font_key,
                    bold=r.get('bold', False), italic=False)
                if not _font_covers(fpath, fname, txt):
                    bp, bn = _broad_font_for(txt)
                    if bp:
                        fpath, fname = bp, bn
                fobj = _font_obj(fpath, fname)
                if fobj is None:
                    continue
                w = fobj.text_length(txt, fontsize=float(r['fs']))
                if w > avail / _SQUEEZE_MIN:      # 조임만으로 감당 안 되는 길이
                    return False
        except Exception:
            return True       # 판단 실패 시에는 기존(제자리) 방식을 유지
        return True

    def _on_block_committed(self, new_text: str):
        """블록 편집 확정 → 블록 영역 지우고 새 텍스트를 재삽입.

        줄 수가 원본과 같으면(대개의 소규모 수정) 각 줄을 원래 위치에 그대로
        되돌려 배치를 완벽히 보존한다. 줄 수가 달라진 편집만 문단 전체를
        다시 흐르게(양쪽정렬·줄간격 재현) 처리한다."""
        import os as _os
        ed = self._inline_block_ed
        if ed is None or ed.fitz_rect is None:
            return
        if new_text == ed.original_text:
            return
        # 고치기 전 페이지를 통째로 떠 둔다 — 콘텐츠 스트림을 직접 고치는
        # 편집이라 어노테이션처럼 xref 하나로 되돌릴 수 없다 (Ctrl+Z)
        self._doc.push_page_snapshot(ed.page_idx)
        page = self._doc.fitz_page(ed.page_idx)
        rect = fitz.Rect(ed.fitz_rect)
        rows = getattr(self, '_block_rows', None)
        new_lines = new_text.split('\n')

        # ① 줄 구조가 그대로면 '바뀐 줄만' 흰 사각형으로 덮고 그 위에 다시 그린다.
        #    apply_redactions 는 이런 HWP 조판 PDF에서 페이지 어딘가의 볼드 제목
        #    (텍스트로 추출 안 되는 글리프)까지 통째로 날려버리므로 쓰지 않는다.
        #    흰 덮개는 콘텐츠 스트림을 재작성하지 않아 손대지 않은 글자는 그대로.
        if (rows and new_text.strip() and len(rows) == len(new_lines)
                and not self._reflow_mode
                and self._lines_fit_in_place(rows, new_lines, ed, rect)):
            changed = [(r, t) for r, t in zip(rows, new_lines)
                       if t.rstrip() != r['text'].rstrip()]
            if changed:
                from utils.pdf_text_edit import erase_text_area
                for r, _t in changed:
                    band = fitz.Rect(rect.x0, r['y0'] - 1, rect.x1, r['y1'] + 1)
                    # 옛 글자를 콘텐츠 스트림에서 실제로 지운다(표준 방식).
                    # 지워지면 텍스트층에 흔적이 남지 않아 다시 편집해도 깨끗하다.
                    if erase_text_area(page, band):
                        continue
                    # 지우지 못한 문서는 흰 덮개로 가리고, 그 자리를 기록해
                    # 다음 편집 때 옛 글자가 겹쳐 읽히지 않게 한다.
                    page.draw_rect(band, color=None, fill=(1, 1, 1))
                    self._mark_covered(ed.page_idx, band)
                # 문단의 오른쪽 여백(원본 줄들이 닿는 최대 x) — 이 밖으로 나가지 않게
                right_limit = max([r['x1'] for r in rows] + [rect.x1])
                self._place_rows_in_place(page, [r for r, _ in changed],
                                          [t for _, t in changed], ed,
                                          right_limit=right_limit)
            self._doc.mark_dirty()
            self._renderer.invalidate(ed.page_idx)
            self._para_rect_cache.pop(ed.page_idx, None)
            ed.fitz_rect = None
            self._block_rows = None
            self.refresh_page()
            return

        # ①-b 내어쓰기(각주)는 항목별로 다시 흘린다. 일반 재흐름은 항목 구분과
        #     들여쓰기를 뭉개므로 쓰지 않는다.
        if (rows and new_text.strip() and len(rows) == len(new_lines)
                and not self._reflow_mode and getattr(self, '_hanging_mode', False)):
            if self._reflow_hanging(page, rows, new_lines, ed, rect):
                self._doc.mark_dirty()
                self._renderer.invalidate(ed.page_idx)
                self._para_rect_cache.pop(ed.page_idx, None)
                ed.fitz_rect = None
                self._block_rows = None
                self.refresh_page()
                return

        # ② 줄 수가 바뀐 편집 → 문단 전체를 비우고 다시 흐르게
        from utils.pdf_text_edit import erase_text_area
        if not erase_text_area(page, fitz.Rect(rect)):
            page.draw_rect(rect, color=None, fill=(1, 1, 1))
            self._mark_covered(ed.page_idx, fitz.Rect(rect))
        # 편집창의 줄 구분을 그대로 흘리면 안 된다. insert_textbox 는 '\n' 을
        # 강제 줄바꿈으로 처리하므로, 원본 줄이 상자 폭을 조금만 넘어도 뒷부분이
        # 짧은 조각으로 떨어져 나간다("엠", "Green", "사실을" …). 이음매 규칙으로
        # 한 문단으로 합친 뒤 흘려야 Word/Acrobat 처럼 자연스럽게 재배치된다.
        new_text = self._merge_lines_for_reflow(new_text, rows)
        if new_text.strip():
            # 원본 글꼴 계열·굵기·기울임 유지 → 글자 크기·모양이 원본과 일치
            fpath, fname = _pick_insert_font(new_text, ed.orig_font, ed.font_key,
                                             bold=ed.bold, italic=ed.italic)
            if not _font_covers(fpath, fname, new_text):
                _bp, _bn = _broad_font_for(new_text)
                if _bp:
                    fpath, fname = _bp, _bn
            fs = float(ed.fs)
            base_kw = dict(fontsize=fs, color=ed.text_color, align=ed.align, fontname=fname)
            if fpath:
                base_kw['fontfile'] = fpath
            # 원본 줄간격 재현(넉넉한 학술문서 줄간격 유지 → 이질감 제거)
            lh = getattr(ed, 'lineheight', None)
            if lh:
                base_kw['lineheight'] = lh
            # 원본 크기를 유지한 채, 상자가 모자라면 아래로 넓혀 삽입한다
            # (글자 크기를 줄이지 않아 원본과 어긋나지 않게). 넓혀도 안 들어갈
            # 만큼 길면 그때만 최소한으로 축소.
            # 첫 줄이 원본과 같은 높이에 오도록 상자 상단을 맞춘다.
            # insert_textbox 는 상자 상단에서 (글자크기 × ascender) 만큼 내려간
            # 곳에 첫 줄 기준선을 놓는다. 이를 빼 주지 않으면 문단 전체가 위로
            # 올라가 붙어 보인다.
            top = rect.y0
            try:
                if rows:
                    _fo = _font_obj(fpath, fname)
                    _asc = float(getattr(_fo, 'ascender', 0.86)) if _fo else 0.86
                    _want = rows[0]['baseline'] - fs * _asc
                    # 문단 사각형 상단은 줄 높이(여백 포함)라 첫 글자보다 위에
                    # 있다. 계산한 값을 그대로 써야 첫 줄이 원래 자리에 온다.
                    if abs(_want - rect.y0) < rect.height:
                        top = _want
            except Exception:
                top = rect.y0
            page_bottom = page.rect.y1 - 12
            inserted = False
            for bottom in (rect.y1,
                           min(page_bottom, rect.y1 + rect.height),
                           min(page_bottom, rect.y1 + rect.height * 3),
                           page_bottom):
                if bottom <= top + fs:
                    continue
                box = fitz.Rect(rect.x0, top, rect.x1, bottom)
                try:
                    rc = page.insert_textbox(box, new_text, **base_kw)
                except Exception as exc:
                    logging.getLogger('pdf_editor').warning('[BlockEdit] %s', exc)
                    break
                if rc >= 0:
                    inserted = True
                    break
            # 페이지 끝까지 넓혀도 안 들어가면 그때만 글자 크기 축소
            if not inserted:
                box = fitz.Rect(rect.x0, top, rect.x1, page_bottom)
                fs2 = fs
                for _ in range(8):
                    fs2 *= 0.9
                    if fs2 < 5:
                        break
                    kw = dict(base_kw); kw['fontsize'] = fs2
                    try:
                        if page.insert_textbox(box, new_text, **kw) >= 0:
                            inserted = True
                            break
                    except Exception:
                        break

        self._doc.mark_dirty()
        self._renderer.invalidate(ed.page_idx)
        self._para_rect_cache.pop(ed.page_idx, None)
        ed.fitz_rect = None
        self._block_rows = None
        self.refresh_page()

    def contextMenuEvent(self, event):
        """우클릭 → 도구가 먼저 처리, 미처리 시 main_window로 전달."""
        scene_pos = self.mapToScene(event.pos())
        if hasattr(self._tool, 'on_context_menu'):
            if self._tool.on_context_menu(scene_pos, event.globalPos(), self):
                return   # 도구가 소비한 경우 main_window 메뉴 억제
        self.context_menu_requested.emit(scene_pos, event.globalPos())

    # ── Ctrl+Z 실행취소 ──────────────────────────────────────────────
    def undo_last_annot(self):
        """마지막 작업 취소.
        우선순위: 미확정(pending) 어노테이션 → undo 스택(구조 변경·커밋된
        어노테이션, 시간순) → 현재 페이지의 마지막 확정 어노테이션.
        """
        # 1) 미확정 어노테이션 우선 취소
        if self._pending.count() > 0:
            all_pa = self._pending.all()
            if all_pa:
                last_pa = all_pa[-1]
                last_pa.remove_from_scene()
                self._pending.remove_uid(last_pa.uid)
                self.notify_pending_changed()
                return

        if not self._doc.is_open:
            return

        # 2) undo 스택: 페이지 회전/자르기/삭제/삽입/이동 + 커밋된 어노테이션
        if self._doc.can_undo():
            self._renderer.invalidate_all()
            if self._doc.undo_last():
                self._book_page_clips.clear()
                self.refresh_page()
                return

        # 3) 폴백: 현재 페이지의 마지막 어노테이션 삭제 (스택에 없는,
        #    파일에 원래 있던 어노테이션 등)
        idx   = self._cur_page
        page  = self._doc.fitz_page(idx)
        annots = list(page.annots())
        if annots:
            page.delete_annot(annots[-1])
            self._doc.mark_dirty()
            self._renderer.invalidate(idx)
            self.refresh_page()

    # ── 키보드 ──────────────────────────────────────────────────────
    def keyPressEvent(self, event: QKeyEvent):
        # Ctrl+Z: 실행취소
        if (event.key() == Qt.Key.Key_Z and
                event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.undo_last_annot()
            return

        if not self._tool.on_key(event, self):
            key = event.key()
            mw = self.window()
            book_mode = bool(getattr(mw, '_book_view_active', False))
            spread_mode = book_mode or self._double_mode
            segment_mode = self._segment_mode
            if key in (Qt.Key.Key_Right, Qt.Key.Key_PageDown):
                if segment_mode:
                    self.step_segment(True)
                elif spread_mode:
                    left = min(max(0, self._doc.page_count() - 2), self._cur_page + 2)
                    self.show_double(left)
                else:
                    self.show_page(self._cur_page + 1)
            elif key in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
                if segment_mode:
                    self.step_segment(False)
                elif spread_mode:
                    left = max(0, self._cur_page - 2)
                    self.show_double(left)
                else:
                    self.show_page(self._cur_page - 1)
            elif key == Qt.Key.Key_Home:
                if segment_mode:
                    self.show_segment(0, 0, self._segment_count)
                elif spread_mode:
                    self.show_double(0)
                else:
                    self.show_page(0)
            elif key == Qt.Key.Key_End:
                if segment_mode:
                    self.show_segment(self._doc.page_count() - 1, self._segment_count - 1, self._segment_count)
                elif spread_mode:
                    left = max(0, self._doc.page_count() - 2)
                    self.show_double(left)
                else:
                    self.show_page(self._doc.page_count() - 1)
            elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self._zoom_step(1)
            elif key == Qt.Key.Key_Minus:
                self._zoom_step(-1)
            elif key == Qt.Key.Key_0:
                self.fit_width()
            else:
                super().keyPressEvent(event)

    # ── 검색 결과 하이라이트 ──────────────────────────────────────────

    def set_search_hits(self, rects, page_idx: int):
        """(호환용) 한 페이지의 검색 결과를 표시한다."""
        rects = list(rects)
        self.set_search_highlights({page_idx: rects}, page_idx, rects[0] if rects else None)

    def _search_scene_rect(self, page_idx: int, r):
        """PDF 좌표 rect → 씬 좌표. 페이지가 화면에 없으면 None.

        씬 좌표는 'PDF 포인트 × _BASE_RENDER_ZOOM' 단위다. 표시 배율(self._zoom)은
        뷰 트랜스폼이 따로 곱한다. 예전 코드는 여기에 self._zoom 을 곱해서, 배율이
        200% 가 아니면 강조 상자가 단어와 엉뚱한 위치·크기에 그려졌다
        (100% 에서는 절반 위치·절반 크기).
        """
        from PySide6.QtCore import QRectF
        offset = self._page_offsets.get(page_idx)
        if offset is None or r is None:
            return None
        s = _BASE_RENDER_ZOOM
        return QRectF(r.x0 * s + offset.x(), r.y0 * s + offset.y(),
                      max(1.0, r.width * s), max(1.0, r.height * s))

    def set_search_highlights(self, hits_by_page: dict, current_page=None, current_rect=None):
        """검색 결과를 칠한다. 현재 결과는 진하게, 나머지는 옅게.

        hits_by_page: {페이지: [fitz.Rect, ...]} — 화면에 없는 페이지는 건너뛴다.
        페이지가 다시 그려지면 씬이 비워지므로 호출자가 page_changed 때 다시 부른다.
        """
        from PySide6.QtWidgets import QGraphicsRectItem
        from PySide6.QtGui import QPen, QBrush, QColor
        self.clear_search_hits()
        self._search_state = (hits_by_page, current_page, current_rect)
        for page_idx, rects in hits_by_page.items():
            for r in rects:
                sr = self._search_scene_rect(page_idx, r)
                if sr is None:
                    break
                is_current = (page_idx == current_page and current_rect is not None
                              and r == current_rect)
                item = QGraphicsRectItem(sr)
                if is_current:
                    item.setPen(QPen(QColor(230, 81, 0), 2.0))
                    item.setBrush(QBrush(QColor(255, 152, 0, 120)))
                    item.setZValue(251)
                else:
                    item.setPen(QPen(QColor(234, 179, 8, 170), 1.0))
                    item.setBrush(QBrush(QColor(255, 235, 59, 95)))
                    item.setZValue(250)
                self.scene().addItem(item)
                self._search_hit_items.append(item)
        # 현재 결과가 목록에 없더라도(OCR 등) 위치가 있으면 표시한다
        if current_rect is not None and current_rect not in hits_by_page.get(current_page, []):
            sr = self._search_scene_rect(current_page, current_rect)
            if sr is not None:
                item = QGraphicsRectItem(sr)
                item.setPen(QPen(QColor(230, 81, 0), 2.0))
                item.setBrush(QBrush(QColor(255, 152, 0, 120)))
                item.setZValue(251)
                self.scene().addItem(item)
                self._search_hit_items.append(item)

    def reveal_search_hit(self, page_idx: int, rect) -> bool:
        """검색 결과가 화면 안에 들어오도록 스크롤한다."""
        sr = self._search_scene_rect(page_idx, rect)
        if sr is None:
            return False
        self.ensureVisible(sr, 80, 120)
        return True

    def clear_search_state(self):
        """강조와 기억해 둔 검색 상태를 모두 지운다."""
        self._search_state = None
        self.clear_search_hits()

    def clear_search_hits(self):
        """검색 하이라이트 전부 제거."""
        for item in self._search_hit_items:
            try:
                sc = item.scene()
                if sc:
                    sc.removeItem(item)
            except RuntimeError:
                swallowed()
        self._search_hit_items.clear()

