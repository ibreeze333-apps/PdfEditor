# ui/mainwin/toolbar_autohide.py — 상단 툴바 자동 숨김(peek) 믹스인
"""어노테이션·보기·문서 툴바 3개를 자동으로 숨겨 문서를 더 넓게 본다.
평소엔 숨고, 마우스를 창 맨 위 끝(메뉴바 포함 상단 영역)에 갖다 대면 나타난다.
마우스가 툴바 밖으로 충분히 내려가면 잠시 뒤 다시 숨는다. 우클릭 메뉴 또는
보기 메뉴(F11)의 '상단 툴바 자동 숨김'으로 켠다."""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer, QPoint
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu


class ToolbarAutoHideMixin:
    """상단 3개 툴바 자동 숨김 + 상단 끝 hover 노출."""

    _TB_HIDE_GRACE = 1.5     # 마우스가 툴바 밖으로 나간 뒤 이만큼(초) 지나면 숨김

    def _init_toolbar_autohide(self):
        self._toolbar_autohide = False
        self._toolbar_revealed = False
        self._tb_last_over = 0.0
        self._tb_watch = QTimer(self)
        self._tb_watch.setInterval(120)      # 마우스 위치 폴링
        self._tb_watch.timeout.connect(self._tb_watch_tick)

    # QMainWindow 가 툴바/도크 영역 우클릭 시 부르는 팝업 — 자동숨김 토글로 대체
    def createPopupMenu(self):
        m = QMenu(self)
        act = m.addAction('🔻 상단 툴바 자동 숨김 (문서 넓게 보기)')
        act.setCheckable(True)
        act.setChecked(getattr(self, '_toolbar_autohide', False))
        act.toggled.connect(self.set_toolbar_autohide)
        return m

    def _top_toolbars(self):
        return [b for b in (getattr(self, '_annot_bar', None),
                            getattr(self, '_view_toolbar', None),
                            getattr(self, '_doc_toolbar', None)) if b is not None]

    def set_toolbar_autohide(self, on: bool):
        on = bool(on)
        self._toolbar_autohide = on
        if on:
            for b in self._top_toolbars():
                b.hide()
            self._toolbar_revealed = False
            self._tb_watch.start()
        else:
            self._tb_watch.stop()
            self._toolbar_revealed = True
            for b in self._top_toolbars():
                b.show()
        act = getattr(self, '_toolbar_autohide_action', None)
        if act is not None and act.isChecked() != on:
            act.blockSignals(True); act.setChecked(on); act.blockSignals(False)
        if hasattr(self, '_status_lbl'):
            self._status_lbl.setText(
                '상단 툴바 자동 숨김 — 화면 맨 위 끝에 마우스를 대면 나타납니다. '
                '(끄기: 보기 메뉴 또는 F11)'
                if on else '상단 툴바 항상 표시.')

    # ── 마우스 위치 폴링(노출/재숨김 판단) ──────────────────────────────
    def _tb_watch_tick(self):
        if not self._toolbar_autohide:
            self._tb_watch.stop()
            return
        gp = QCursor.pos()
        win_tl = self.mapToGlobal(QPoint(0, 0))
        in_x = win_tl.x() <= gp.x() <= win_tl.x() + self.width()
        # 창 맨 위 끝의 넉넉한 영역(메뉴바 높이 + 여유) — 여기 닿으면 노출
        mb = self.menuBar()
        top_zone = (mb.height() if mb is not None else 0) + 10
        at_top = in_x and win_tl.y() - 2 <= gp.y() <= win_tl.y() + top_zone

        if not self._toolbar_revealed:
            if at_top:
                self._toolbar_revealed = True
                self._tb_last_over = time.monotonic()
                for b in self._top_toolbars():
                    b.show()
            return

        # 노출 상태: 마우스가 상단 영역/툴바 위에 있으면 유지
        over = at_top
        if not over:
            for b in self._top_toolbars():
                if b.isVisible():
                    tl = b.mapToGlobal(b.rect().topLeft())
                    br = b.mapToGlobal(b.rect().bottomRight())
                    if tl.x() - 40 <= gp.x() <= br.x() + 40 \
                            and tl.y() - 8 <= gp.y() <= br.y() + 28:
                        over = True; break
        if over:
            self._tb_last_over = time.monotonic()
            return
        if time.monotonic() - self._tb_last_over < self._TB_HIDE_GRACE:
            return
        self._toolbar_revealed = False
        for b in self._top_toolbars():
            b.hide()
