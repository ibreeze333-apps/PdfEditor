from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QTextEdit,
)


class NotePanel(QWidget):
    note_activated = Signal(int)
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        top = QHBoxLayout()
        self._status = QLabel('메모 0개')
        self._status.setStyleSheet('font-weight: bold;')
        top.addWidget(self._status)
        top.addStretch()

        refresh_btn = QPushButton('새로고침')
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        top.addWidget(refresh_btn)
        root.addLayout(top)

        self._list = QListWidget(self)
        self._list.itemSelectionChanged.connect(self._show_selected)
        self._list.itemDoubleClicked.connect(self._activate_item)
        root.addWidget(self._list, 2)

        hint = QLabel('항목을 더블클릭하면 해당 페이지로 이동합니다.')
        hint.setStyleSheet('color: #666; font-size: 11px;')
        root.addWidget(hint)

        self._preview = QTextEdit(self)
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText('선택한 메모 내용이 여기에 보입니다.')
        root.addWidget(self._preview, 1)

    def set_notes(self, entries: list[dict]):
        self._entries = list(entries)
        self._list.clear()
        for entry in self._entries:
            prefix = '[PENDING]' if entry.get('source') == 'pending' else '[PDF]'
            page_no = entry.get('page_index', 0) + 1
            text = (entry.get('text') or '').strip() or '(empty memo)'
            one_line = ' '.join(text.split())
            if len(one_line) > 72:
                one_line = one_line[:71] + '...'
            item = QListWidgetItem(f'{prefix} {page_no}페이지  {one_line}')
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._list.addItem(item)
        self._status.setText(f'메모 {len(self._entries)}개')
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        else:
            self._preview.clear()

    def clear(self):
        self.set_notes([])

    def _show_selected(self):
        item = self._list.currentItem()
        if item is None:
            self._preview.clear()
            return
        entry = item.data(Qt.ItemDataRole.UserRole) or {}
        page_no = entry.get('page_index', 0) + 1
        source = '미확정 메모' if entry.get('source') == 'pending' else 'PDF 메모'
        text = (entry.get('text') or '').strip() or '(empty memo)'
        self._preview.setPlainText(f'{source} | {page_no}페이지\n\n{text}')

    def _activate_item(self, item: QListWidgetItem):
        entry = item.data(Qt.ItemDataRole.UserRole) or {}
        self.note_activated.emit(int(entry.get('page_index', 0)))
