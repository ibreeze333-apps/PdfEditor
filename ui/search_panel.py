# ui/search_panel.py — 고급 검색 / 검색 결과 목록 패널
"""찾기 메뉴 → '고급 검색 (결과 목록)'(Ctrl+Shift+F)으로 여는 오른쪽 패널.

찾기 막대가 결과를 하나씩 넘겨 보는 도구라면, 이 패널은 결과를 한눈에
목록으로 본다. 검색 방식(정확한 문구 / 모든 단어 / 하나라도), 제외할 단어,
열린 모든 문서에서 찾기를 지원한다. 항목을 누르면 그 위치로 이동한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.search import MODE_ALL, MODE_ANY, MODE_PHRASE

SCOPE_CURRENT = 'current'
SCOPE_ALL = 'all'


@dataclass
class SearchRequest:
    query: str
    mode: str = MODE_PHRASE
    exclude: str = ''
    case_sensitive: bool = False
    whole_word: bool = False
    scope: str = SCOPE_CURRENT


class SearchPanel(QWidget):
    search_requested = Signal(object)          # SearchRequest
    stop_requested = Signal()
    hit_activated = Signal(int, int, object)   # (탭 번호, 페이지, rect 튜플 또는 None)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)

        root.addWidget(self._title('무엇을 검색하시겠습니까?'))
        self._query = QLineEdit(self)
        self._query.setPlaceholderText('단어 또는 문구 입력…')
        self._query.setClearButtonEnabled(True)
        self._query.returnPressed.connect(self._emit_search)
        root.addWidget(self._query)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel('검색 방식', self))
        self._mode = QComboBox(self)
        for label, mode in (('정확한 문구', MODE_PHRASE),
                            ('모든 단어 포함', MODE_ALL),
                            ('하나라도 포함', MODE_ANY)):
            self._mode.addItem(label, mode)
        self._mode.setToolTip('모든 단어 포함: 입력한 단어가 전부 있는 페이지만\n'
                              '하나라도 포함: 단어 중 하나라도 있는 페이지')
        row.addWidget(self._mode, 1)
        root.addLayout(row)

        self._exclude = QLineEdit(self)
        self._exclude.setPlaceholderText('제외할 단어 (공백으로 구분, 선택)')
        self._exclude.setToolTip('이 단어가 하나라도 있는 페이지는 결과에서 뺍니다.')
        self._exclude.returnPressed.connect(self._emit_search)
        root.addWidget(self._exclude)

        opts = QHBoxLayout()
        self._case = QCheckBox('대소문자 구분', self)
        self._word = QCheckBox('단어 단위로', self)
        opts.addWidget(self._case)
        opts.addWidget(self._word)
        opts.addStretch(1)
        root.addLayout(opts)

        root.addWidget(self._title('어디에서 검색하시겠습니까?'))
        self._scope = QComboBox(self)
        self._scope.addItem('현재 문서', SCOPE_CURRENT)
        self._scope.addItem('열린 모든 문서', SCOPE_ALL)
        root.addWidget(self._scope)

        btns = QHBoxLayout()
        self._search_btn = QPushButton('검색', self)
        self._search_btn.clicked.connect(lambda _c=False: self._emit_search())
        self._stop_btn = QPushButton('중지', self)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(lambda _c=False: self.stop_requested.emit())
        btns.addWidget(self._search_btn, 1)
        btns.addWidget(self._stop_btn, 1)
        root.addLayout(btns)

        self._progress = QProgressBar(self)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.hide()
        root.addWidget(self._progress)

        self._status = QLabel('발견: 0 문서, 0 항목', self)
        root.addWidget(self._status)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(2)
        self._tree.setUniformRowHeights(True)
        self._tree.setRootIsDecorated(True)
        header = self._tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.itemActivated.connect(self._on_item)
        self._tree.itemClicked.connect(self._on_item)
        root.addWidget(self._tree, 1)

        self._doc_nodes: dict[int, QTreeWidgetItem] = {}
        self._doc_names: dict[int, str] = {}
        self._n_hits = 0

    def _title(self, text: str) -> QLabel:
        lbl = QLabel(text, self)
        lbl.setStyleSheet('font-weight: 600; color: #1e293b;')
        return lbl

    # ── 요청 ──────────────────────────────────────────────────────────
    def build_request(self) -> SearchRequest:
        return SearchRequest(
            query=self._query.text().strip(),
            mode=self._mode.currentData(),
            exclude=self._exclude.text().strip(),
            case_sensitive=self._case.isChecked(),
            whole_word=self._word.isChecked(),
            scope=self._scope.currentData(),
        )

    def _emit_search(self):
        req = self.build_request()
        if not req.query:
            self._status.setText('검색어를 입력하세요.')
            self._query.setFocus()
            return
        self.search_requested.emit(req)

    def query(self) -> str:
        return self._query.text()

    def set_query(self, text: str):
        self._query.setText(text)

    def focus_query(self):
        self._query.setFocus()
        self._query.selectAll()

    def set_message(self, text: str):
        self._status.setText(text)

    # ── 결과 ──────────────────────────────────────────────────────────
    def begin(self):
        self._tree.clear()
        self._doc_nodes.clear()
        self._doc_names.clear()
        self._n_hits = 0
        self._progress.setRange(0, 0)
        self._progress.show()
        self._search_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._update_status(busy=True)

    def set_progress(self, done: int, total: int):
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(done)
        self._update_status(busy=True)

    def add_hits(self, tab_index: int, doc_name: str, hits):
        node = self._doc_nodes.get(tab_index)
        if node is None:
            node = QTreeWidgetItem(self._tree, [doc_name, ''])
            node.setFirstColumnSpanned(True)
            font = node.font(0)
            font.setBold(True)
            node.setFont(0, font)
            node.setExpanded(True)
            self._doc_nodes[tab_index] = node
            self._doc_names[tab_index] = doc_name
        for h in hits:
            rect = tuple(h.rect) if h.rect is not None else None
            text = h.context or ('(OCR 인식 글자 — 화면 위치 없음)' if rect is None else '')
            child = QTreeWidgetItem(node, [f'{h.page + 1}쪽', text])
            child.setData(0, Qt.ItemDataRole.UserRole, (tab_index, h.page, rect))
            child.setToolTip(1, text)
        self._n_hits += len(hits)
        node.setText(0, f'{self._doc_names[tab_index]}  ({node.childCount()})')
        self._update_status(busy=True)

    def finish(self, cancelled: bool = False):
        self._progress.hide()
        self._search_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._update_status(busy=False, cancelled=cancelled)

    def result_count(self) -> int:
        return self._n_hits

    def _update_status(self, busy: bool, cancelled: bool = False):
        text = f'발견: {len(self._doc_nodes)} 문서, {self._n_hits} 항목'
        if busy:
            text += '  · 검색 중…'
        elif cancelled:
            text += '  · 중지됨'
        self._status.setText(text)

    def _on_item(self, item, _column=0):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        tab_index, page, rect = data
        self.hit_activated.emit(tab_index, page, rect)
