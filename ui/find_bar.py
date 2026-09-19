# ui/find_bar.py — 문서 위에 떠 있는 찾기 막대
"""찾기 메뉴(Ctrl+F)로 여는 찾기 막대. 문서 영역 오른쪽 위에 겹쳐 뜬다.

예전 막대는 창 아래 도크에 붙어 있었고, 버튼을 setFixedSize(28, 26) 로
박아 둔 탓에 전역 스타일시트(QPushButton 의 min-height 30px + padding)와
충돌했다. Qt 는 최소치를 우선해 버튼을 44px 로 그렸고, 38px 짜리 막대
밖으로 삐져나가 잘려서 버튼이 아예 안 보였다.
여기서는 QToolButton 에 막대 전용 스타일을 걸어 전역 규칙과 부딪히지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QToolButton,
)

_HISTORY_MAX = 15

_STYLE = """
#FindBar { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px; }
#FindBar QToolButton { border: none; border-radius: 6px; padding: 0px;
    min-width: 0px; min-height: 0px; font-size: 17px; color: #334155;
    background: transparent; }
#FindBar QToolButton:hover { background: #e0e7ff; color: #3730a3; }
#FindBar QToolButton:pressed { background: #c7d2fe; }
#FindBar QToolButton::menu-indicator { image: none; width: 0px; }
#FindBar QComboBox { padding: 2px 6px; min-height: 0px; border: 1.5px solid #cbd5e1;
    border-radius: 6px; background: #ffffff; font-size: 14px; }
#FindBar QComboBox:focus { border-color: #6366f1; }
#FindBar QLineEdit[notFound="true"] { background: #fee2e2; }
#FindBar QLabel#FindStatus { color: #475569; font-size: 12px; padding: 0px 4px; }
#FindBar QLabel#FindStatus[kind="error"] { color: #b91c1c; }
#FindBar QLabel#FindStatus[kind="busy"] { color: #4f46e5; }
"""


class _ImeLineEdit(QLineEdit):
    """한글 조합 중인 글자까지 포함한 '지금 보이는 글자'를 알려 주는 입력칸.

    QLineEdit.textChanged 는 조합이 끝난 글자만 반영해서 '제64조'를 치는 동안
    마지막 음절이 빠진 채로 검색된다. 조합 중 글자(preedit)를 끼워 넣어
    입력하는 대로 바로 찾게 한다.
    """
    live_text = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.textChanged.connect(self.live_text.emit)

    def inputMethodEvent(self, event):
        super().inputMethodEvent(event)
        pre = event.preeditString()
        if pre:
            text, pos = self.text(), self.cursorPosition()
            self.live_text.emit(text[:pos] + pre + text[pos:])


class FindBar(QFrame):
    query_changed = Signal(str)     # 입력이 바뀜 (조합 중 글자 포함)
    next_requested = Signal()       # › / Enter / F3
    prev_requested = Signal()       # ‹ / Shift+Enter / Shift+F3
    close_requested = Signal()      # ✕ / Esc
    options_changed = Signal()      # 대소문자 구분 / 단어 단위로
    panel_requested = Signal()      # 검색 결과 목록 보기

    def __init__(self, host=None):
        super().__init__(host)
        self.setObjectName('FindBar')
        self.setStyleSheet(_STYLE)
        self.top_offset = lambda: 10    # 문서 영역 위쪽 여백 (호출자가 바꿔 끼운다)
        self._host = host
        if host is not None:
            host.installEventFilter(self)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 6, 6)
        lay.setSpacing(4)

        self._combo = QComboBox(self)
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._combo.setMaxVisibleItems(_HISTORY_MAX)
        self._combo.setMinimumWidth(250)
        self._edit = _ImeLineEdit(self._combo)
        self._combo.setLineEdit(self._edit)
        self._edit.setPlaceholderText('찾기…')
        self._edit.setClearButtonEnabled(True)
        self._edit.live_text.connect(self.query_changed.emit)
        self._edit.installEventFilter(self)
        lay.addWidget(self._combo)

        self._prev_btn = self._tool('‹', '이전 결과 (Shift+F3, Shift+Enter)', self.prev_requested)
        self._next_btn = self._tool('›', '다음 결과 (F3, Enter)', self.next_requested)
        lay.addWidget(self._prev_btn)
        lay.addWidget(self._next_btn)

        self._status = QLabel('', self)
        self._status.setObjectName('FindStatus')
        self._status.setMinimumWidth(64)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._status)

        # 찾기 메뉴에서도 같은 QAction 을 쓴다 → 체크 상태가 늘 일치한다
        self.case_action = QAction('대소문자 구분', self)
        self.case_action.setCheckable(True)
        self.word_action = QAction('단어 단위로', self)
        self.word_action.setCheckable(True)
        self.case_action.toggled.connect(lambda _c: self.options_changed.emit())
        self.word_action.toggled.connect(lambda _c: self.options_changed.emit())
        menu = QMenu(self)
        menu.addAction(self.case_action)
        menu.addAction(self.word_action)
        menu.addSeparator()
        menu.addAction('검색 결과 목록 보기…').triggered.connect(
            lambda _c=False: self.panel_requested.emit())
        self._opt_btn = self._tool('⋮', '찾기 옵션', None)
        self._opt_btn.setMenu(menu)
        self._opt_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        lay.addWidget(self._opt_btn)

        self._close_btn = self._tool('✕', '닫기 (Esc)', self.close_requested)
        lay.addWidget(self._close_btn)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(15, 23, 42, 60))
        self.setGraphicsEffect(shadow)
        self.adjustSize()
        self.hide()

    def _tool(self, text: str, tip: str, signal) -> QToolButton:
        b = QToolButton(self)
        b.setText(text)
        b.setToolTip(tip)
        b.setFixedSize(30, 30)
        # 눌러도 입력칸 포커스를 빼앗지 않는다 — 계속 타이핑할 수 있게
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if signal is not None:
            b.clicked.connect(lambda _c=False, s=signal: s.emit())
        return b

    # ── 공개 API ──────────────────────────────────────────────────────
    def open(self):
        self._reposition()
        self.show()
        self.raise_()
        self._edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._edit.selectAll()

    def query(self) -> str:
        return self._edit.text()

    def set_query(self, text: str):
        self._edit.setText(text)

    def case_sensitive(self) -> bool:
        return self.case_action.isChecked()

    def whole_word(self) -> bool:
        return self.word_action.isChecked()

    def set_status(self, text: str, kind: str = 'normal'):
        self._status.setText(text)
        self._status.setToolTip('')
        self._status.setProperty('kind', kind)
        self._edit.setProperty('notFound', kind == 'error')
        for w in (self._status, self._edit):
            w.style().unpolish(w)
            w.style().polish(w)
        self._reposition()

    def set_status_tip(self, tip: str):
        self._status.setToolTip(tip)

    def status_text(self) -> str:
        return self._status.text()

    def add_history(self, query: str):
        query = (query or '').strip()
        if not query:
            return
        # 목록을 고치면 편집 글자가 바뀌며 검색이 다시 돌 수 있어 신호를 막는다
        current = self._edit.text()
        self._edit.blockSignals(True)
        try:
            i = self._combo.findText(query)
            if i >= 0:
                self._combo.removeItem(i)
            self._combo.insertItem(0, query)
            while self._combo.count() > _HISTORY_MAX:
                self._combo.removeItem(self._combo.count() - 1)
            self._edit.setText(current)
        finally:
            self._edit.blockSignals(False)

    # ── 배치 / 키 입력 ────────────────────────────────────────────────
    def _reposition(self):
        host = self._host or self.parentWidget()
        if host is None:
            return
        self.adjustSize()
        x = max(8, host.width() - self.width() - 24)   # 세로 스크롤바를 가리지 않게
        try:
            y = int(self.top_offset())
        except Exception:
            y = 10
        self.move(x, y)
        self.raise_()

    def eventFilter(self, obj, ev):
        if obj is self._edit and ev.type() == QEvent.Type.KeyPress:
            key = ev.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.add_history(self.query())
                if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.prev_requested.emit()
                else:
                    self.next_requested.emit()
                return True
            if key == Qt.Key.Key_Escape:
                self.close_requested.emit()
                return True
        elif obj is self._host and ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            if self.isVisible():
                self._reposition()
        return super().eventFilter(obj, ev)
