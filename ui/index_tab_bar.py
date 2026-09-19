# ui/index_tab_bar.py — 인덱스 포스트잇(책갈피) 사이드 탭 바
"""페이지(문서) 가장자리에 붙는 색 탭 목록. 모든 페이지에서 항상 보이며,
클릭하면 그 책갈피 페이지로 즉시 이동한다.

- 한쪽(오른쪽/왼쪽) 가장자리에 붙는다. side='right'|'left'
- 책보기/양면보기에서는 좌우 두 개의 바로 책의 양 가장자리에 붙는다
- 실제 인덱스 포스트잇처럼 바깥쪽 모서리는 둥글고, 페이지에 닿는 안쪽은
  각지게 그려 종이가 페이지에서 튀어나온 느낌을 준다
- 좌클릭 = 이동, 우클릭 = 편집/삭제 메뉴
"""
from __future__ import annotations

from PySide6.QtCore import (
    Qt, QRectF, QRect, QPoint, QTimer, Signal, QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QLinearGradient, QPainterPath,
    QRegion,
)
from PySide6.QtWidgets import QWidget, QMenu, QToolTip

_TAB_H = 30          # 탭 높이(px)
_TAB_GAP = 5         # 탭 간격
_TAB_W = 118         # 탭 너비(px)
_OVERLAP = 9         # 탭이 페이지 위로 겹치는 양(붙어있는 느낌)
_EXTRA = 8           # 위젯 여백(그림자 공간)
_CUR_POP = 7         # 현재 페이지 탭이 바깥으로 더 튀어나오는 양
_PEEK_STRIP = 20     # peek(숨김) 모드에서 가장자리에 보이는 폭


class IndexFilterButton(QWidget):
    """인덱스 표시 필터를 순환시키는 작은 떠 있는 버튼.
    전체 → 내 인덱스만 → 목차만. 문서에 두 종류가 다 있을 때만 나타난다."""
    clicked_cycle = Signal()
    move_toc_side = Signal(str)     # 목차 인덱스 일괄 이동 'left'|'right'
    move_mine_side = Signal(str)    # 내 인덱스 일괄 이동

    _LABEL = {'all': '🔖 전체', 'mine': '🔖 내 인덱스', 'toc': '🔖 목차',
              'off': '🔖 숨김'}

    def __init__(self, canvas):
        super().__init__(canvas.viewport())
        self._canvas = canvas
        self._mode = 'all'
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('클릭: 인덱스 표시 전환 (전체 → 내 인덱스만 → 문서 목차만)\n'
                        '우클릭: 목차/내 인덱스를 좌·우로 한꺼번에 이동')
        f = QFont('Malgun Gothic'); f.setPixelSize(12); f.setBold(True)
        self.setFont(f)
        self._resize_to_text()
        self.hide()

    def set_mode(self, mode: str):
        if mode != self._mode:
            self._mode = mode
            self._resize_to_text()
            self.update()

    def _resize_to_text(self):
        from PySide6.QtGui import QFontMetrics
        w = QFontMetrics(self.font()).horizontalAdvance(
            self._LABEL.get(self._mode, '전체')) + 22
        self.resize(max(74, w), 26)

    def reposition(self):
        vp = self._canvas.viewport()
        self.move(vp.width() - self.width() - 12, 8)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rr = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        # 모드별 옅은 배경색
        bg = {'all': QColor(70, 70, 78, 235),
              'mine': QColor(38, 120, 190, 240),
              'toc': QColor(120, 96, 60, 240),
              'off': QColor(90, 90, 96, 200)}.get(self._mode, QColor(70, 70, 78, 235))
        path = QPainterPath(); path.addRoundedRect(rr, 13, 13)
        p.fillPath(path, bg)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1)); p.drawPath(path)
        p.setPen(QColor(250, 250, 250))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                   self._LABEL.get(self._mode, '전체'))
        p.end()

    def mousePressEvent(self, e):
        e.accept()
        if e.button() == Qt.MouseButton.RightButton:
            gp = (e.globalPosition().toPoint() if hasattr(e, 'globalPosition')
                  else e.globalPos())
            self._show_menu(gp)

    def mouseReleaseEvent(self, e):
        e.accept()
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self.rect().contains(e.position().toPoint()
                                if hasattr(e, 'position') else e.pos()):
            self.clicked_cycle.emit()

    def _show_menu(self, gpos):
        m = QMenu(self)
        m.addAction('◀ 목차 인덱스 모두 왼쪽으로').triggered.connect(
            lambda: self.move_toc_side.emit('left'))
        m.addAction('목차 인덱스 모두 오른쪽으로 ▶').triggered.connect(
            lambda: self.move_toc_side.emit('right'))
        m.addSeparator()
        m.addAction('◀ 내 인덱스 모두 왼쪽으로').triggered.connect(
            lambda: self.move_mine_side.emit('left'))
        m.addAction('내 인덱스 모두 오른쪽으로 ▶').triggered.connect(
            lambda: self.move_mine_side.emit('right'))
        m.exec(gpos)


class IndexTabBar(QWidget):
    navigate = Signal(int)        # 대상 페이지(0-based)
    edit_requested = Signal(int)  # 탭 idx(TOC 위치)
    delete_requested = Signal(int)
    move_y_requested = Signal(int, float)     # (idx, y_fraction 0~1) — 자유 수직 배치
    side_change_requested = Signal(int, str)  # (idx, 'left'|'right')

    def __init__(self, canvas, side: str = 'right'):
        super().__init__(canvas.viewport())
        self._canvas = canvas
        self._side = side               # 'right' | 'left'
        self._tabs: list[dict] = []
        self._cur_page = 0
        self._scroll = 0
        self._overflow = False
        self._max_scroll = 0
        self._peek = False           # 책보기: 가장자리에 숨었다 hover 시 나옴
        self._peek_open = False
        self._peek_anim = QPropertyAnimation(self, b'pos', self)
        self._peek_anim.setDuration(520)     # 천천히 미끄러져 나옴
        self._peek_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # 마우스가 잠깐 벗어나도 바로 닫지 않도록 유예 시간을 둔다.
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(650)
        self._close_timer.timeout.connect(self._do_peek_close)
        self._hover = -1
        # 드래그(순서 변경/좌우 이동) 상태
        self._press_idx = -1
        self._press_pos = None
        self._dragging = False
        self._drag_dy = 0
        self._drag_switch = None
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    # ── 데이터 ───────────────────────────────────────────────────────
    def set_tabs(self, tabs: list[dict]):
        # 수동(TOC) 순서 그대로 유지 — 사용자가 드래그로 정한 순서를 존중
        prev_n = len(self._tabs)
        self._tabs = list(tabs)
        if len(self._tabs) != prev_n:
            self._scroll = 0      # 목록이 바뀌면(필터 전환 등) 맨 위로
        if not self._tabs:
            self.hide()
            return
        self._reposition()
        self.show()
        self.raise_()
        self.update()

    def set_current_page(self, page: int):
        if page != self._cur_page:
            self._cur_page = page
            self.update()
        if self.isVisible():
            self._reposition()

    def set_peek(self, on: bool):
        """책보기 등 전체화면 모드에서 가장자리 숨김(peek) 켜기/끄기."""
        on = bool(on)
        if on == self._peek:
            return
        self._peek = on
        self._peek_open = False
        if self.isVisible():
            self._reposition()
            self.update()

    # ── 배치 ─────────────────────────────────────────────────────────
    def _reposition(self):
        # 바 위젯은 페이지 세로 전체를 덮고, 각 탭은 자기 y위치(비율)에 자유롭게
        # 배치된다. 실제 클릭은 마스크로 '탭이 있는 곳'에서만 받아, 페이지
        # 가장자리 클릭이 막히지 않게 한다.
        vp = self._canvas.viewport()
        w = _TAB_W + _CUR_POP + 2 * _EXTRA
        # 세로 범위는 페이지 높이에 맞춘다. 책보기처럼 페이지가 뷰포트보다
        # 짧을 때 바가 페이지 밖으로 삐져나가지 않게(단, 뷰포트 안으로 클램프).
        top_y = 6
        h = max(_TAB_H + 2 * _EXTRA, vp.height() - 12)
        span = None
        get_span = getattr(self._canvas, 'page_vspan_in_viewport', None)
        if callable(get_span):
            span = get_span(self._side)
        if span is not None:
            p_top, p_bot = span
            # 책보기에서는 페이지 높이보다 살짝 안쪽으로(위아래 여백) — 딱 맞으면
            # 답답해 보여서 책보다 조금 작게 둔다.
            inset = (p_bot - p_top) * 0.04 if getattr(
                self._canvas, '_book_mode_visual', False) else 0.0
            p_top = max(2.0, p_top + inset)
            p_bot = min(vp.height() - 2.0, p_bot - inset)
            if p_bot - p_top >= _TAB_H + 2 * _EXTRA:
                top_y = int(p_top)
                h = int(p_bot - p_top)
        if self._peek:
            # 책보기 등 전체화면 모드: 평소엔 화면 가장자리에 얇게 숨고(peek),
            # 마우스를 대면(_peek_open) 쓱 나온다. 뷰포트 바깥 가장자리에 붙는다.
            if self._side == 'right':
                x = (vp.width() - w) if self._peek_open \
                    else (vp.width() - _PEEK_STRIP - _EXTRA)
            else:
                x = 0 if self._peek_open \
                    else (_PEEK_STRIP - _EXTRA - _CUR_POP - _TAB_W)
        else:
            edge = self._canvas.page_edge_in_viewport(self._side)
            if edge is None:
                x = (vp.width() - w) if self._side == 'right' else 0
            elif self._side == 'right':
                x = int(edge) - _OVERLAP - _EXTRA
                x = max(0, min(x, vp.width() - w))
            else:
                x = int(edge) + _OVERLAP - _TAB_W - _CUR_POP - _EXTRA
                x = max(0, min(x, vp.width() - w))
        self.setGeometry(x, top_y, w, h)
        self._recalc_scroll()
        self._update_mask()

    def _usable_h(self) -> float:
        return max(1.0, self.height() - 2 * _EXTRA - _TAB_H)

    def _content_h(self) -> float:
        """모든 탭을 순차로 쌓았을 때의 총 높이."""
        return len(self._tabs) * (_TAB_H + _TAB_GAP)

    def _recalc_scroll(self):
        """탭이 보이는 높이를 넘치면 순차 스크롤 모드로 전환하고 스크롤 범위를
        다시 계산한다. 넘치지 않으면 자유 수직 배치(드래그 위치)를 그대로 쓴다."""
        visible = max(1.0, self.height() - 2 * _EXTRA)
        self._overflow = self._content_h() > visible
        self._max_scroll = max(0, int(self._content_h() - visible)) if self._overflow else 0
        self._scroll = max(0, min(self._scroll, self._max_scroll))

    def _tab_y(self, i: int) -> float:
        """탭 상단 y (위젯 좌표).
        넘칠 때: 순차 배치 - 스크롤. 아닐 때: 자유 위치(비율) 또는 계단식."""
        if getattr(self, '_overflow', False):
            return _EXTRA + i * (_TAB_H + _TAB_GAP) - self._scroll
        yf = self._tabs[i].get('y')
        if yf is None:
            step = (_TAB_H + _TAB_GAP) / max(1.0, self._usable_h())
            yf = min(0.92, 0.02 + i * step)
        return _EXTRA + float(yf) * self._usable_h()

    def _tab_rect(self, i: int) -> QRect:
        y = int(self._tab_y(i))
        x = _EXTRA if self._side == 'right' else _EXTRA + _CUR_POP
        return QRect(x, y, _TAB_W, _TAB_H)

    def _tab_at(self, pos) -> int:
        # 위에 그려진(뒤 인덱스) 탭 우선
        for i in reversed(range(len(self._tabs))):
            if self._tab_rect(i).adjusted(-_CUR_POP, 0, _CUR_POP, 0).contains(pos):
                return i
        return -1

    def _update_mask(self):
        """탭이 있는 영역만 마스크 — 나머지 가장자리 클릭은 페이지로 통과."""
        reg = QRegion()
        for i in range(len(self._tabs)):
            reg = reg.united(QRegion(self._tab_rect(i).adjusted(-_CUR_POP - 2, -2, _CUR_POP + 2, 2)))
        # 드래그 중인 탭은 이동 위치까지 포함
        if self._dragging and 0 <= self._press_idx < len(self._tabs):
            r = self._tab_rect(self._press_idx).translated(0, self._drag_dy)
            reg = reg.united(QRegion(r.adjusted(-_CUR_POP - 2, -2, _CUR_POP + 2, 2)))
        self.setMask(reg)

    # ── 그리기 ───────────────────────────────────────────────────────
    def _tab_path(self, rr: QRectF, radius: float, fold: float = 0.0) -> QPainterPath:
        """종이 탭 모양. 바깥 위 모서리는 살짝 둥글고, 바깥 아래 모서리는
        접힌 종이처럼 대각선으로 잘린다. 안쪽(페이지에 붙는 쪽)은 각짐."""
        p = QPainterPath()
        r = radius
        if self._side == 'right':
            p.moveTo(rr.left(), rr.top())
            p.lineTo(rr.right() - r, rr.top())
            p.quadTo(rr.right(), rr.top(), rr.right(), rr.top() + r)
            p.lineTo(rr.right(), rr.bottom() - fold)      # 접힘 시작
            p.lineTo(rr.right() - fold, rr.bottom())      # 대각선(접힌 자리)
            p.lineTo(rr.left(), rr.bottom())
            p.closeSubpath()
        else:
            p.moveTo(rr.right(), rr.top())
            p.lineTo(rr.left() + r, rr.top())
            p.quadTo(rr.left(), rr.top(), rr.left(), rr.top() + r)
            p.lineTo(rr.left(), rr.bottom() - fold)
            p.lineTo(rr.left() + fold, rr.bottom())
            p.lineTo(rr.right(), rr.bottom())
            p.closeSubpath()
        return p

    def _fold_path(self, rr: QRectF, fold: float) -> QPainterPath:
        """접힌 모서리 삼각형 (바깥 아래)."""
        p = QPainterPath()
        if fold <= 0:
            return p
        if self._side == 'right':
            p.moveTo(rr.right() - fold, rr.bottom())
            p.lineTo(rr.right(), rr.bottom() - fold)
            p.lineTo(rr.right() - fold, rr.bottom() - fold)
        else:
            p.moveTo(rr.left() + fold, rr.bottom())
            p.lineTo(rr.left(), rr.bottom() - fold)
            p.lineTo(rr.left() + fold, rr.bottom() - fold)
        p.closeSubpath()
        return p

    def paintEvent(self, _e):
        if not self._tabs:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        for i, tab in enumerate(self._tabs):
            r = self._tab_rect(i)
            if r.bottom() < 0 or r.top() > self.height():
                continue
            is_cur = (tab['page'] == self._cur_page)
            is_hover = (i == self._hover)
            is_drag = (self._dragging and i == self._press_idx)
            pop = _CUR_POP if is_cur else (3 if is_hover else 0)
            # 바깥쪽으로 pop 만큼 더 내민다
            if self._side == 'right':
                rr = QRectF(r.left(), r.top(), r.width() + pop, r.height())
            else:
                rr = QRectF(r.left() - pop, r.top(), r.width() + pop, r.height())
            if is_drag:
                # 드래그 중인 탭은 커서를 따라 위/아래로, 살짝 들린 느낌
                rr = rr.translated(0, self._drag_dy)

            # 문서 기본 목차는 회색으로 눈에 덜 띄게, 내 인덱스는 지정색으로.
            if tab.get('origin') == 'toc':
                rgb = (0.64, 0.64, 0.66)
            else:
                rgb = tab.get('color') or (0.36, 0.68, 0.94)
            base = QColor(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
            # 종이 느낌: 원색을 크림톤과 살짝 섞어 채도를 낮춘 매트 색
            def _paper(c, wr):
                return QColor(int(c.red()*(1-wr)+252*wr),
                              int(c.green()*(1-wr)+250*wr),
                              int(c.blue()*(1-wr)+238*wr))
            paper = _paper(base, 0.30)
            paper_top = _paper(base, 0.40)      # 위쪽 살짝 더 밝게(은은한 종이 결)
            radius = 4.0
            fold = min(13.0, rr.height() * 0.42, rr.width() * 0.20)
            path = self._tab_path(rr, radius, fold)

            # 부드러운 종이 그림자 (매트, 흐릿하게 두 겹)
            sh = 2.0 if self._side == 'right' else -2.0
            p.fillPath(self._tab_path(rr.translated(sh, 2.6), radius, fold),
                       QColor(40, 35, 20, 34))
            p.fillPath(self._tab_path(rr.translated(sh*0.5, 1.2), radius, fold),
                       QColor(40, 35, 20, 30))

            # 매트 종이 본체 (아주 은은한 세로 그라디언트, 광택 없음)
            grad = QLinearGradient(rr.topLeft(), rr.bottomLeft())
            grad.setColorAt(0.0, paper_top)
            grad.setColorAt(1.0, paper)
            p.fillPath(path, QBrush(grad))

            # 접힌 모서리 (뒤로 접힌 종이 — 살짝 어둡게)
            if fold > 0:
                p.fillPath(self._fold_path(rr, fold), QColor(base.darker(112).red(),
                           base.darker(112).green(), base.darker(112).blue(), 150))

            # 페이지에 붙는 안쪽 얇은 색 띠 (분류 색 표시, 매트)
            band_w = 6.0
            p.save()
            p.setClipPath(path)
            if self._side == 'right':
                bandr = QRectF(rr.left(), rr.top(), band_w, rr.height())
            else:
                bandr = QRectF(rr.right()-band_w, rr.top(), band_w, rr.height())
            p.fillRect(bandr, base)
            p.restore()

            # 얇은 테두리 (종이 가장자리)
            p.setPen(QPen(base.darker(118), 1.2 if is_cur else 0.9))
            p.drawPath(path)

            # 라벨 (매트 종이 위, 진한 글씨)
            lum = 0.299*paper.red() + 0.587*paper.green() + 0.114*paper.blue()
            p.setPen(QColor(40, 36, 28) if lum > 130 else QColor(250, 250, 250))
            f = QFont('Malgun Gothic')
            f.setPixelSize(13)
            f.setBold(is_cur)
            p.setFont(f)
            if self._side == 'right':
                trect = QRectF(rr.left()+band_w+7, rr.top(), rr.width()-band_w-14, rr.height()).toRect()
                align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            else:
                trect = QRectF(rr.left()+7, rr.top(), rr.width()-band_w-14, rr.height()).toRect()
                align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
            fm = p.fontMetrics()
            label = tab.get('label') or f"{tab['page']+1}쪽"
            elided = fm.elidedText(label, Qt.TextElideMode.ElideRight, trect.width())
            p.drawText(trect, align, elided)
        # 스크롤 힌트 ▲▼ — 넘칠 때, 위/아래로 더 있으면 표시
        if getattr(self, '_overflow', False):
            self._paint_scroll_hints(p)
        p.end()

    def _paint_scroll_hints(self, p: QPainter):
        cx = self.width() // 2
        f = QFont('Malgun Gothic'); f.setPixelSize(12); f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(90, 90, 90, 200))
        if self._scroll > 2:
            p.drawText(QRect(cx - 14, 0, 28, _EXTRA + 4),
                       Qt.AlignmentFlag.AlignCenter, '▲')
        if self._scroll < self._max_scroll - 2:
            p.drawText(QRect(cx - 14, self.height() - _EXTRA - 6, 28, _EXTRA + 6),
                       Qt.AlignmentFlag.AlignCenter, '▼')

    # ── 상호작용 ─────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        e.accept()
        pos = e.position().toPoint() if hasattr(e, 'position') else e.pos()
        i = self._tab_at(pos)
        self._press_idx = i
        self._press_pos = pos
        self._dragging = False
        self._drag_dy = 0
        self._drag_switch = None
        if i >= 0 and e.button() == Qt.MouseButton.RightButton:
            gp = e.globalPosition().toPoint() if hasattr(e, 'globalPosition') else e.globalPos()
            self._press_idx = -1
            self._show_menu(i, gp)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint() if hasattr(e, 'position') else e.pos()
        if self._press_idx >= 0 and (e.buttons() & Qt.MouseButton.LeftButton):
            dy = pos.y() - self._press_pos.y()
            dx = pos.x() - self._press_pos.x()
            if not self._dragging and (abs(dy) > 4 or abs(dx) > 8):
                self._dragging = True
            if self._dragging:
                self._drag_dy = dy
                # 반대쪽 가장자리로 끌면 side 변경
                if self._side == 'right' and pos.x() < -18:
                    self._drag_switch = 'left'
                elif self._side == 'left' and pos.x() > self.width() + 18:
                    self._drag_switch = 'right'
                else:
                    self._drag_switch = None
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self._update_mask()   # 드래그 위치까지 클릭영역 확장
                self.update()
            return
        # 호버 — 제목 전체를 툴팁으로 표시 (라벨이 잘려 보일 때 유용)
        i = self._tab_at(pos)
        if i != self._hover:
            self._hover = i
            if 0 <= i < len(self._tabs):
                t = self._tabs[i]
                label = t.get('label') or f"{t['page']+1}쪽"
                gp = e.globalPosition().toPoint() if hasattr(e, 'globalPosition') else e.globalPos()
                QToolTip.showText(gp, f"{label}  ({t['page']+1}쪽)", self)
            else:
                QToolTip.hideText()
            self.update()

    def mouseReleaseEvent(self, e):
        e.accept()   # 캔버스(인덱스 도구)로 전파 방지
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        i = self._press_idx
        self._press_idx = -1
        if i < 0 or i >= len(self._tabs):
            self._dragging = False
            return
        if not self._dragging:
            if e.button() == Qt.MouseButton.LeftButton:
                self.navigate.emit(self._tabs[i]['page'])
            return
        self._dragging = False
        tab = self._tabs[i]
        idx = tab.get('idx', i)
        if self._drag_switch:
            self.side_change_requested.emit(idx, self._drag_switch)
        elif not getattr(self, '_overflow', False):
            # 자유 수직 배치는 넘치지 않을 때만(넘칠 땐 순차+스크롤 모드).
            new_top = self._tab_y(i) + self._drag_dy
            yf = (new_top - _EXTRA) / max(1.0, self._usable_h())
            yf = max(0.001, min(1.0, yf))
            self.move_y_requested.emit(idx, yf)
        self._drag_dy = 0
        self._drag_switch = None
        self.update()

    def mouseDoubleClickEvent(self, e):
        e.accept()
        pos = e.position().toPoint() if hasattr(e, 'position') else e.pos()
        i = self._tab_at(pos)
        if i >= 0:
            self.navigate.emit(self._tabs[i]['page'])

    def _peek_target_x(self) -> int:
        """현재 peek 상태(열림/닫힘)에서 바가 있어야 할 x."""
        vp = self._canvas.viewport()
        w = self.width()
        if self._side == 'right':
            return (vp.width() - w) if self._peek_open \
                else (vp.width() - _PEEK_STRIP - _EXTRA)
        return 0 if self._peek_open else (_PEEK_STRIP - _EXTRA - _CUR_POP - _TAB_W)

    def _animate_peek(self):
        """peek 열림/닫힘을 부드럽게 슬라이드."""
        self._peek_anim.stop()
        self._peek_anim.setStartValue(self.pos())
        self._peek_anim.setEndValue(QPoint(int(self._peek_target_x()), self.y()))
        self._peek_anim.start()

    def enterEvent(self, _e):
        # peek 모드: 마우스가 가장자리 띠에 닿으면 쓱 펼친다.
        self._close_timer.stop()   # 닫기 예약 취소
        if self._peek and not self._peek_open:
            self._peek_open = True
            self._animate_peek()

    def leaveEvent(self, _e):
        if self._hover != -1:
            self._hover = -1
            self.update()
        # peek 모드: 바로 닫지 않고 유예 시간 뒤에 닫는다(마우스가 되돌아오면 취소).
        if self._peek and self._peek_open and not self._dragging:
            self._close_timer.start()

    def _do_peek_close(self):
        if self._peek and self._peek_open and not self._dragging \
                and not self.underMouse():
            self._peek_open = False
            self._animate_peek()

    def wheelEvent(self, e):
        self._recalc_scroll()
        if not self._overflow:
            e.ignore()
            return
        delta = e.angleDelta().y()
        new = max(0, min(self._max_scroll, self._scroll - delta))
        if new != self._scroll:
            self._scroll = new
            self._update_mask()
            self.update()
        e.accept()

    def _show_menu(self, i: int, gpos):
        menu = QMenu(self)
        idx = self._tabs[i].get('idx', i)
        menu.addAction('📄 이 페이지로 이동').triggered.connect(
            lambda: self.navigate.emit(self._tabs[i]['page']))
        menu.addSeparator()
        other = 'left' if self._side == 'right' else 'right'
        other_label = '◀ 왼쪽으로 옮기기' if other == 'left' else '오른쪽으로 옮기기 ▶'
        menu.addAction(other_label).triggered.connect(
            lambda: self.side_change_requested.emit(idx, other))
        menu.addAction('✏ 라벨/색/위치 편집').triggered.connect(
            lambda: self.edit_requested.emit(idx))
        menu.addAction('🗑 이 인덱스 삭제').triggered.connect(
            lambda: self.delete_requested.emit(idx))
        menu.exec(gpos)
