# ui/font_combo.py — 드롭다운 화살표가 항상 보이고, 어디를 눌러도 목록이 열리는 글꼴 선택 콤보
from __future__ import annotations
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QFontComboBox

# 드롭다운 버튼(화살표)을 또렷하게 보이도록 강제하는 스타일.
# 전역 Fusion 스타일에서 화살표가 사라져 '글꼴 글자를 눌러야만' 열리던 문제 해결.
_FONT_COMBO_QSS = (
    "QFontComboBox { padding-right: 26px; min-height: 26px; }"
    "QFontComboBox::drop-down {"
    " subcontrol-origin: padding; subcontrol-position: center right;"
    " width: 24px; border-left: 1px solid #c4ccd8; background: #eef2f8; }"
    "QFontComboBox::down-arrow {"
    " image: none; width: 0; height: 0;"
    " border-left: 5px solid transparent; border-right: 5px solid transparent;"
    " border-top: 6px solid #3a4a63; margin-right: 7px; }"
)


class FontPickerCombo(QFontComboBox):
    """글꼴 선택 콤보 — 화살표가 항상 보이고 입력창을 클릭해도 목록이 열린다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_FONT_COMBO_QSS)
        self.setMinimumWidth(160)
        # editable 유지(글꼴명 타이핑 검색 가능) + 입력창 클릭 시 목록 팝업
        le = self.lineEdit()
        if le is not None:
            le.installEventFilter(self)
            le.setClearButtonEnabled(False)

    def eventFilter(self, obj, ev):
        if obj is self.lineEdit() and ev.type() == QEvent.Type.MouseButtonPress:
            # 텍스트를 클릭해도 드롭다운이 열리게
            if not self.view().isVisible():
                self.showPopup()
            return True
        return super().eventFilter(obj, ev)
