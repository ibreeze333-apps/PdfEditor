# ui/dialogs/merge_pdf_dialog.py — PDF 병합
from __future__ import annotations
import fitz
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
    QFileDialog, QDialogButtonBox, QMessageBox, QLabel,
)
from PySide6.QtCore import Qt


class MergePdfDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('PDF 병합')
        self.setMinimumSize(480, 360)

        ly = QVBoxLayout(self)
        ly.addWidget(QLabel('병합할 PDF 파일들 (순서 조정 가능):'))

        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        ly.addWidget(self._list)

        btn_ly = QHBoxLayout()
        add_btn = QPushButton('파일 추가')
        add_btn.clicked.connect(self._add_files)
        rem_btn = QPushButton('선택 제거')
        rem_btn.clicked.connect(self._remove_selected)
        up_btn  = QPushButton('↑ 위로')
        up_btn.clicked.connect(self._move_up)
        dn_btn  = QPushButton('↓ 아래로')
        dn_btn.clicked.connect(self._move_down)
        for b in (add_btn, rem_btn, up_btn, dn_btn):
            btn_ly.addWidget(b)
        ly.addLayout(btn_ly)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('병합 & 저장')
        btns.accepted.connect(self._merge)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, 'PDF 추가', '', 'PDF (*.pdf)')
        for p in paths:
            self._list.addItem(p)

    def _remove_selected(self):
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))

    def _move_up(self):
        row = self._list.currentRow()
        if row > 0:
            item = self._list.takeItem(row)
            self._list.insertItem(row - 1, item)
            self._list.setCurrentRow(row - 1)

    def _move_down(self):
        row = self._list.currentRow()
        if row < self._list.count() - 1:
            item = self._list.takeItem(row)
            self._list.insertItem(row + 1, item)
            self._list.setCurrentRow(row + 1)

    def _merge(self):
        if self._list.count() < 2:
            QMessageBox.warning(self, '경고', '파일을 2개 이상 추가하세요.')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '저장 경로', 'merged.pdf', 'PDF (*.pdf)')
        if not path:
            return
        merged = fitz.open()
        for i in range(self._list.count()):
            src = fitz.open(self._list.item(i).text())
            merged.insert_pdf(src)
            src.close()
        merged.save(path, garbage=4, deflate=True,
                    deflate_images=True, deflate_fonts=True)
        merged.close()
        QMessageBox.information(self, '완료', f'병합 완료:\n{path}')
        self.accept()
