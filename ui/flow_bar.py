# ui/flow_bar.py — 폭이 모자라면 다음 줄로 넘기는 툴바 컨테이너
"""화면 배율(고DPI)이 올라가면 창의 '논리 폭'이 그만큼 줄어들어, 예전에
한 줄에 들어가던 툴바 버튼들이 오른쪽 끝에서 잘려 나갔다. 여기서는

  1) 먼저 버튼 글꼴을 조금(최대 85%까지) 줄여 한 줄에 맞춰 보고,
  2) 그래도 넘치면 다음 줄로 자동 줄바꿈

하는 컨테이너를 만든다. QToolBar 안에 QWidgetAction 하나로 넣어 쓰며,
줄 수에 맞춰 스스로 높이를 바꾸므로 툴바 높이도 따라 늘어난다.
"""
from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, QTimer
from PySide6.QtWidgets import (
    QFrame, QLayout, QSizePolicy, QWidget, QWidgetItem,
)


def _enforced_min(w: QWidget) -> QSize:
    """위젯이 실제로 가지게 될 최소 크기.

    setFixedWidth 로 좁혀 놔도 전역 스타일시트의 padding/min-height 때문에
    Qt 가 minimumSizeHint 를 더 크게 잡고, 그 크기로 그려 버리는 경우가
    있다. 레이아웃은 그 '실제' 크기를 기준으로 자리를 잡아야 한다.
    """
    msh = w.minimumSizeHint()
    return QSize(max(w.minimumWidth(), msh.width() if msh.width() > 0 else 0),
                 max(w.minimumHeight(), msh.height() if msh.height() > 0 else 0))


class FlowLayout(QLayout):
    """왼쪽부터 채우다 폭이 모자라면 다음 줄로 내리는 레이아웃."""

    def __init__(self, parent=None, margin: int = 0,
                 hspace: int = 4, vspace: int = 3):
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self._hspace = hspace
        self._vspace = vspace
        self.setContentsMargins(margin, margin, margin, margin)

    # ── QLayout 필수 구현 ────────────────────────────────────────
    def addItem(self, item):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), test_only=True)[0]

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        need, _ = self._arrange(rect, test_only=False)
        # 글꼴을 바꾼 뒤 자식 크기가 뒤늦게 커지면 컨테이너 높이가 모자랄
        # 수 있다 — 그 때는 다음 이벤트 루프에서 높이를 다시 맞춘다.
        parent = self.parentWidget()
        if parent is not None and need > rect.height() and hasattr(parent, '_fit'):
            QTimer.singleShot(0, parent._fit)

    def sizeHint(self) -> QSize:
        """한 줄로 다 펼쳤을 때의 크기 — 툴바가 넉넉한 폭을 요청하게 한다."""
        m: QMargins = self.contentsMargins()
        w = m.left() + m.right()
        h = 0
        for i, item in enumerate(self._items):
            sh = item.sizeHint()
            w += sh.width() + (self._hspace if i else 0)
            h = max(h, sh.height())
        return QSize(w, h + m.top() + m.bottom())

    def minimumSize(self) -> QSize:
        """가장 넓은 항목 하나만 들어가면 된다 — 창 최소 폭을 키우지 않게."""
        m: QMargins = self.contentsMargins()
        w = h = 0
        for item in self._items:
            ms = item.minimumSize()
            w = max(w, ms.width())
            h = max(h, ms.height())
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    # ── 배치 계산 ────────────────────────────────────────────────
    def _arrange(self, rect: QRect, test_only: bool) -> tuple[int, int]:
        """(전체 높이, 줄 수)를 돌려준다. test_only 면 위젯을 옮기지 않는다."""
        m: QMargins = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = eff.x(), eff.y()
        line: list = []          # 현재 줄에 담긴 (item, x, size)
        line_h = 0
        rows = 0

        bottom = eff.y()

        def flush(cur_y: int, cur_h: int):
            """한 줄을 확정한다 — 줄 안에서 세로 가운데 정렬.

            실제로 놓은 위치의 아래끝을 그대로 기록해 두었다가 전체 높이로
            쓴다 — 계산식과 배치가 어긋나 마지막 줄이 잘리는 일이 없게.
            """
            nonlocal bottom
            for it, ix, sz in line:
                iy = cur_y + (cur_h - sz.height()) // 2
                bottom = max(bottom, iy + sz.height())
                if not test_only:
                    it.setGeometry(QRect(QPoint(ix, iy), sz))

        for item in self._items:
            # 실제로 위젯이 가지게 될 크기로 계산한다.
            # 앱 전역 스타일시트의 min-height 가 setFixedSize 보다 커서
            # (예: 페이지 이동 버튼) Qt 가 최소치를 우선하는 경우가 있는데,
            # sizeHint 만 믿고 자리를 잡으면 그만큼 아래로 삐져나가 잘린다.
            sh = item.sizeHint()
            wid = item.widget()
            if wid is not None:
                sh = sh.expandedTo(_enforced_min(wid))
            nx = x + sh.width()
            if line and nx > eff.right() + 1:
                # 줄바꿈
                flush(y, line_h)
                line = []
                x = eff.x()
                y += line_h + self._vspace
                line_h = 0
                rows += 1
                nx = x + sh.width()
            line.append((item, x, sh))
            x = nx + self._hspace
            line_h = max(line_h, sh.height())

        if line:
            flush(y, line_h)
            rows += 1

        total_h = bottom - rect.y() + m.bottom()
        return max(total_h, 0), rows


class FlowBar(QWidget):
    """FlowLayout 컨테이너 + 글꼴 자동 축소.

    폭이 모자라면 _SCALES 순서대로 글꼴을 줄여 보고, 줄 수가 가장 적어지는
    값을 쓴다. 같은 줄 수라면 글씨가 큰 쪽(먼저 시도한 쪽)을 고른다.
    85%까지 줄여도 한 줄에 안 들어가면 그냥 다음 줄로 넘긴다 — 읽을 수
    없을 만큼 작아지는 것보다 두 줄이 낫다.
    """

    MIN_SCALE = 0.72      # 이보다 작아지면 읽기 힘들다 — 그 아래는 줄바꿈
    _STEP = 0.01          # 탐색 정밀도

    def __init__(self, parent=None, margin: int = 0,
                 hspace: int = 4, vspace: int = 3):
        super().__init__(parent)
        self._flow = FlowLayout(self, margin=margin, hspace=hspace, vspace=vspace)
        self.setLayout(self._flow)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._fitting = False
        self.compact = False       # 아이콘만 표시 중인지 (_choose_layout 이 정한다)
        self._scale = 1.0
        self._base_pts: dict = {}     # 위젯별 원래 글꼴 크기(pt)
        self._base_widths: dict = {}  # 폭 고정 위젯의 원래 폭(px)

    # ── 항목 추가 ────────────────────────────────────────────────
    def add_widget(self, w: QWidget) -> QWidget:
        self._flow.addWidget(w)
        return w

    def add_separator(self, height: int = 26) -> QWidget:
        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setFixedWidth(1)
        sep.setMinimumHeight(height)
        sep.setStyleSheet('QFrame { color: #d6dbe6; margin: 4px 3px; }')
        self._flow.addWidget(sep)
        return sep

    def rows(self) -> int:
        return self._flow._arrange(QRect(0, 0, max(1, self.width()), 0),
                                   test_only=True)[1]

    # ── 크기 맞춤 ────────────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def _apply_scale(self, scale: float):
        """자식 위젯 글꼴을 각자의 원래 크기 대비 scale 배로 맞춘다.

        부모에 setFont 해서 물려주는 방식은 못 쓴다 — 스타일시트가 걸린
        위젯(GlassButton)은 글꼴이 이미 '직접 지정됨'으로 표시돼 상속을
        받지 않기 때문이다. 그래서 위젯마다 직접 지정한다.
        """
        for i in range(self._flow.count()):
            it = self._flow.itemAt(i)
            w = it.widget() if it is not None else None
            if w is None:
                continue
            base = self._base_pts.get(w)
            if base is None:
                f0 = w.font()
                base = f0.pointSizeF() if f0.pointSizeF() > 0 else 13.0
                self._base_pts[w] = base
            f = w.font()
            pt = max(7.0, base * scale)
            if abs(f.pointSizeF() - pt) > 0.01:
                f.setPointSizeF(pt)
                w.setFont(f)
                w.updateGeometry()
            self._scale_fixed_width(w, scale)
        self._scale = scale
        self._flow.invalidate()

    def _rows_at(self, scale: float, width: int) -> int:
        self._apply_scale(scale)
        return self._flow._arrange(QRect(0, 0, width, 0), test_only=True)[1]

    def _best_scale(self, width: int) -> float:
        """한 줄에 담기는 가장 큰 글꼴 배율을 찾는다.

        고정된 몇 단계만 시도하면 "조금만 더 줄이면 들어가는데" 하는
        경우를 놓쳐 한 줄이 통째로 비어 버린다. 그래서 필요한 만큼만
        줄이도록 이분 탐색한다.
        MIN_SCALE 까지 줄여도 안 들어가면 원래 크기로 두고 줄바꿈한다 —
        읽지도 못할 글씨로 한 줄에 우겨넣는 것보다 두 줄이 낫다.
        """
        if self._rows_at(1.0, width) <= 1:
            return 1.0
        if self._rows_at(self.MIN_SCALE, width) > 1:
            return 1.0
        lo, hi = self.MIN_SCALE, 1.0      # lo 는 들어감, hi 는 안 들어감
        while hi - lo > self._STEP:
            mid = (lo + hi) / 2.0
            if self._rows_at(mid, width) <= 1:
                lo = mid
            else:
                hi = mid
        return lo

    def _scale_fixed_width(self, w: QWidget, scale: float):
        """폭이 고정된 위젯(setFixedWidth)도 배율만큼 좁힌다.

        글꼴만 줄이면 이런 위젯은 그대로라, 한 줄에 못 담는 원인이 된다.
        (페이지 이동 버튼/쪽 번호 입력칸 등)
        """
        if w.minimumWidth() <= 0 or w.minimumWidth() != w.maximumWidth():
            base = self._base_widths.get(w)
            if base is None:
                return          # 애초에 고정폭이 아니면 건드리지 않는다
        else:
            base = self._base_widths.setdefault(w, w.minimumWidth())
        # 스타일시트가 강제하는 최소폭보다 좁게는 못 만든다 — 억지로 좁히면
        # 위젯이 제 최소폭으로 그려지면서 오른쪽 끝이 삐져나가 잘린다.
        target = max(20, int(round(base * scale)), _enforced_min(w).width())
        if w.minimumWidth() != target or w.maximumWidth() != target:
            w.setFixedWidth(target)
            w.updateGeometry()

    def _compactable(self) -> list:
        out = []
        for i in range(self._flow.count()):
            it = self._flow.itemAt(i)
            wd = it.widget() if it is not None else None
            if wd is not None and hasattr(wd, 'set_compact') and wd.can_compact():
                out.append(wd)
        return out

    def _set_compact_all(self, widgets, on: bool):
        for wd in widgets:
            wd.set_compact(on)
        self._flow.invalidate()

    def _choose_layout(self, width: int) -> float:
        """글자 크기와 아이콘만 표시(컴팩트) 여부를 정하고 쓸 배율을 돌려준다.

        1) 글자를 필요한 만큼만 줄여 한 줄에 맞춰 본다(_best_scale).
        2) 그래도 여러 줄이면 아이콘이 있는 버튼을 아이콘만 보이게 하고 다시 맞춘다.
           줄 수가 실제로 줄어들 때만 컴팩트를 쓴다 — 같으면 글자가 보이는 쪽이 낫다.

        화면 배율 150% 인 1920×1080 노트북(논리 폭 1280)에서 툴바가 4줄이 되어
        문서 영역이 창의 절반밖에 안 되던 문제 때문에 넣었다.
        """
        widgets = self._compactable()
        self._set_compact_all(widgets, False)
        scale = self._best_scale(width)
        rows = self._rows_at(scale, width)
        self.compact = False
        if rows > 1 and widgets:
            self._set_compact_all(widgets, True)
            c_scale = self._best_scale(width)
            c_rows = self._rows_at(c_scale, width)
            if c_rows < rows:
                self.compact = True
                return c_scale
            self._set_compact_all(widgets, False)
        return scale

    def _fit(self):
        w = self.width()
        if self._fitting or w <= 1:
            return
        self._fitting = True
        try:
            # 스타일시트 적용(polish)을 먼저 끝내 둔다 — 전역 QSS 의
            # min-height 가 나중에 반영되면 이미 잡아 둔 자리보다 위젯이
            # 커져서 아래쪽이 잘린다.
            for i in range(self._flow.count()):
                it = self._flow.itemAt(i)
                w_ = it.widget() if it is not None else None
                if w_ is not None:
                    w_.ensurePolished()
            self._apply_scale(self._choose_layout(w))
            h = self._flow.heightForWidth(w)
            if h > 0 and (self.minimumHeight() != h or self.maximumHeight() != h):
                self.setFixedHeight(h)
        finally:
            self._fitting = False
