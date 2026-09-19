# ui/dialogs/text_editor_dialog.py — PDF 텍스트 블록 에디터
# 페이지 텍스트를 블록 단위로 추출 → 직접 편집 → 변경분을 redact+insert로 적용
from __future__ import annotations
import fitz


def _has_cjk(text: str) -> bool:
    for c in text:
        cp = ord(c)
        if (0xAC00 <= cp <= 0xD7A3 or 0x1100 <= cp <= 0x11FF or
                0x3000 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF):
            return True
    return False
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QHeaderView, QGroupBox, QCheckBox, QMessageBox,
    QAbstractItemView, QSplitter, QTextEdit,
)
from PySide6.QtGui import QColor, QFont


class _TextBlockModel(QAbstractTableModel):
    """PDF 텍스트 블록을 테이블로 표시. 텍스트 셀 직접 편집 가능."""

    HEADERS = ['페이지', '원본 텍스트', '수정 텍스트', '글자 크기']

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []   # {page, orig, edited, fs, rect}

    def load(self, fitz_doc: fitz.Document, page_range: range):
        self.beginResetModel()
        self._rows.clear()
        for idx in page_range:
            page = fitz_doc.load_page(idx)
            blocks = page.get_text('dict')['blocks']
            for b in blocks:
                for line in b.get('lines', []):
                    for span in line.get('spans', []):
                        text = span.get('text', '').strip()
                        if not text:
                            continue
                        self._rows.append({
                            'page':   idx,
                            'orig':   text,
                            'edited': text,
                            'fs':     span.get('size', 11),
                            'rect':   fitz.Rect(span['bbox']),
                        })
        self.endResetModel()

    def changed_rows(self) -> list[dict]:
        return [r for r in self._rows if r['orig'] != r['edited']]

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and \
                orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole or \
                role == Qt.ItemDataRole.EditRole:
            if col == 0: return str(row['page'] + 1)
            if col == 1: return row['orig']
            if col == 2: return row['edited']
            if col == 3: return f"{row['fs']:.1f}pt"
        if role == Qt.ItemDataRole.BackgroundRole:
            if row['orig'] != row['edited']:
                return QColor('#fff9c4')  # 변경된 행 노란 배경
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 1:
                return QColor('#888888')
        return None

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 2:
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.column() == 2 and role == Qt.ItemDataRole.EditRole:
            self._rows[index.row()]['edited'] = value
            self.dataChanged.emit(index, index)
            return True
        return False


class TextEditorDialog(QDialog):
    """PDF 텍스트 블록 직접 편집 다이얼로그."""

    def __init__(self, fitz_doc: fitz.Document, current_page: int, parent=None):
        super().__init__(parent)
        self._doc          = fitz_doc
        self._current_page = current_page
        self._applied      = False
        self._model        = _TextBlockModel(self)
        self._setui()
        self._load()
        self.setWindowTitle('PDF 텍스트 편집기')
        self.resize(820, 560)

    def _setui(self):
        lay = QVBoxLayout(self)

        # ── 안내 ──────────────────────────────────────────────────────
        info = QLabel(
            '수정 텍스트 열을 더블클릭하여 편집하세요. '
            '변경된 행은 노란색으로 표시됩니다. '
            '적용 시 원본 텍스트는 흰색으로 덮이고 수정 텍스트가 같은 위치에 삽입됩니다.')
        info.setWordWrap(True)
        info.setStyleSheet('color: #555; font-size: 12px; padding: 4px;')
        lay.addWidget(info)

        # ── 범위 ──────────────────────────────────────────────────────
        scope_grp = QGroupBox('편집 범위')
        scope_lay = QHBoxLayout(scope_grp)
        self._rb_current = QCheckBox('현재 페이지만')
        self._rb_current.setChecked(True)
        self._rb_all = QCheckBox('전체 페이지')
        self._rb_current.toggled.connect(
            lambda c: (self._rb_all.setChecked(not c), self._load()))
        self._rb_all.toggled.connect(
            lambda c: (self._rb_current.setChecked(not c), self._load()))
        scope_lay.addWidget(self._rb_current)
        scope_lay.addWidget(self._rb_all)
        scope_lay.addStretch()
        self._count_lbl = QLabel('')
        scope_lay.addWidget(self._count_lbl)
        lay.addWidget(scope_grp)

        # ── 테이블 ──────────────────────────────────────────────────────
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 55)
        self._table.setColumnWidth(3, 70)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed)
        self._table.setAlternatingRowColors(True)
        lay.addWidget(self._table)

        # ── 결과 ──────────────────────────────────────────────────────
        self._result_lbl = QLabel('')
        self._result_lbl.setWordWrap(True)
        lay.addWidget(self._result_lbl)

        # ── 버튼 ──────────────────────────────────────────────────────
        btn_lay = QHBoxLayout()
        reset_btn = QPushButton('↺ 변경 초기화')
        reset_btn.clicked.connect(self._reset)
        self._apply_btn = QPushButton('✅ 변경 적용')
        self._apply_btn.setDefault(True)
        self._apply_btn.clicked.connect(self._apply)
        close_btn = QPushButton('닫기')
        close_btn.clicked.connect(self._close_result)
        btn_lay.addWidget(reset_btn)
        btn_lay.addStretch()
        btn_lay.addWidget(self._apply_btn)
        btn_lay.addWidget(close_btn)
        lay.addLayout(btn_lay)

    def _page_range(self) -> range:
        if self._rb_all.isChecked():
            return range(self._doc.page_count)
        return range(self._current_page, self._current_page + 1)

    def _load(self):
        self._model.load(self._doc, self._page_range())
        n = self._model.rowCount()
        self._count_lbl.setText(f'총 {n}개 텍스트 스팬')

    def _reset(self):
        self._load()
        self._result_lbl.setText('')

    def _apply(self):
        changed = self._model.changed_rows()
        if not changed:
            self._result_lbl.setStyleSheet('color: #cc6600;')
            self._result_lbl.setText('변경된 내용이 없습니다.')
            return

        count = 0
        for row in changed:
            page = self._doc.load_page(row['page'])
            rect = row['rect']
            fs   = row['fs']
            repl = row['edited']

            page.add_redact_annot(rect, fill=(1, 1, 1))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

            if repl.strip():
                baseline_y = rect.y1 - max(1.0, (rect.height - fs) * 0.5)
                pt = fitz.Point(rect.x0, baseline_y)
                try:
                    fontname = 'cjk' if _has_cjk(repl) else 'helv'
                    page.insert_text(pt, repl, fontsize=fs,
                                     color=(0, 0, 0), fontname=fontname)
                except Exception as e:
                    print(f'[TextEditor] insert_text 오류: {e}')
            count += 1

        self._applied = True
        self._result_lbl.setStyleSheet('color: #1a7f1a; font-weight: bold;')
        self._result_lbl.setText(
            f'✅ {count}군데 적용 완료. 저장해야 반영됩니다.')
        # 적용 후 다시 로드 (원본 업데이트)
        self._load()

    def _close_result(self):
        if self._applied:
            self.accept()
        else:
            self.reject()

    def was_applied(self) -> bool:
        return self._applied
