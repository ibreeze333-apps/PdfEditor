# ui/dialogs/image_pdf_merge_dialog.py — 이미지/PDF 통합 병합
# PDF 파일과 이미지 파일(JPG, PNG 등)을 순서대로 합쳐 단일 PDF로 저장
from __future__ import annotations
import os
import fitz
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QFileDialog, QDialogButtonBox, QMessageBox,
    QLabel, QComboBox, QCheckBox, QProgressDialog, QGroupBox,
)


_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.webp', '.gif'}
_PAGE_SIZES = {
    '원본 크기':  None,
    'A4':         (595, 842),
    'A3':         (842, 1191),
    'Letter':     (612, 792),
}


class ImagePdfMergeDialog(QDialog):
    """이미지와 PDF를 섞어서 순서대로 병합."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('이미지/PDF 통합 병합')
        self.setMinimumSize(540, 440)
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────
    def _build_ui(self):
        ly = QVBoxLayout(self)

        ly.addWidget(QLabel(
            'PDF·이미지 파일을 추가하고 순서를 조정한 뒤 병합하세요.\n'
            '이미지는 한 페이지씩, PDF는 전체 페이지가 삽입됩니다.'))

        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        ly.addWidget(self._list)

        # 파일 조작 버튼
        btn_row = QHBoxLayout()
        add_pdf = QPushButton('📄 PDF 추가')
        add_img = QPushButton('🖼 이미지 추가')
        rem_btn = QPushButton('🗑 삭제')
        up_btn  = QPushButton('⬆ 위로')
        dn_btn  = QPushButton('⬇ 아래로')
        add_pdf.clicked.connect(self._add_pdf)
        add_img.clicked.connect(self._add_img)
        rem_btn.clicked.connect(self._remove)
        up_btn.clicked.connect(self._move_up)
        dn_btn.clicked.connect(self._move_down)
        for b in (add_pdf, add_img, rem_btn, up_btn, dn_btn):
            btn_row.addWidget(b)
        ly.addLayout(btn_row)

        # 이미지 페이지 크기 옵션
        opt_grp = QGroupBox('이미지 페이지 옵션')
        opt_ly  = QHBoxLayout(opt_grp)
        opt_ly.addWidget(QLabel('페이지 크기:'))
        self._size_cb = QComboBox()
        self._size_cb.addItems(list(_PAGE_SIZES.keys()))
        opt_ly.addWidget(self._size_cb)
        self._fit_cb = QCheckBox('페이지에 맞게 비율 조정')
        self._fit_cb.setChecked(True)
        opt_ly.addWidget(self._fit_cb)
        opt_ly.addStretch()
        ly.addWidget(opt_grp)

        # 버튼
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('병합 & 저장…')
        btns.accepted.connect(self._merge)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)

    # ── 파일 관리 ────────────────────────────────────────────────────
    def _add_pdf(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, 'PDF 추가', '', 'PDF 파일 (*.pdf)')
        for p in paths:
            item = QListWidgetItem(f'📄  {Path(p).name}')
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self._list.addItem(item)

    def _add_img(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, '이미지 추가', '',
            '이미지 파일 (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp *.gif)')
        for p in paths:
            item = QListWidgetItem(f'🖼  {Path(p).name}')
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self._list.addItem(item)

    def _remove(self):
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

    # ── 병합 실행 ────────────────────────────────────────────────────
    def _merge(self):
        if self._list.count() == 0:
            QMessageBox.warning(self, '경고', '파일을 하나 이상 추가하세요.')
            return

        path, _ = QFileDialog.getSaveFileName(
            self, '저장 경로', 'merged.pdf', 'PDF (*.pdf)')
        if not path:
            return
        if not path.lower().endswith('.pdf'):
            path += '.pdf'

        page_size = _PAGE_SIZES[self._size_cb.currentText()]
        fit       = self._fit_cb.isChecked()
        n         = self._list.count()

        prog = QProgressDialog('병합 중…', '취소', 0, n, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.show()

        out = fitz.open()
        try:
            for i in range(n):
                prog.setValue(i)
                if prog.wasCanceled():
                    out.close()
                    return
                file_path = self._list.item(i).data(Qt.ItemDataRole.UserRole)
                ext       = Path(file_path).suffix.lower()
                prog.setLabelText(f'{Path(file_path).name} 처리 중…')

                if ext in _IMAGE_EXTS:
                    self._insert_image(out, file_path, page_size, fit)
                else:
                    src = fitz.open(file_path)
                    out.insert_pdf(src)
                    src.close()

            prog.setValue(n)
            out.save(path, garbage=4, deflate=True)
            QMessageBox.information(
                self, '완료',
                f'병합 완료!\n저장 위치: {path}\n총 페이지: {out.page_count}')
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, '오류', f'병합 실패:\n{e}')
        finally:
            out.close()
        prog.close()

    @staticmethod
    def _insert_image(out: fitz.Document, img_path: str,
                      page_size, fit: bool):
        src      = fitz.open(img_path)
        src_rect = src[0].rect
        src.close()

        if page_size and fit:
            pw, ph = page_size
            scale  = min(pw / src_rect.width, ph / src_rect.height)
            nw     = src_rect.width  * scale
            nh     = src_rect.height * scale
            x0     = (pw - nw) / 2
            y0     = (ph - nh) / 2
            dest   = fitz.Rect(x0, y0, x0 + nw, y0 + nh)
        elif page_size:
            pw, ph = page_size
            dest   = fitz.Rect(0, 0, pw, ph)
        else:
            pw, ph = src_rect.width, src_rect.height
            dest   = fitz.Rect(0, 0, pw, ph)

        page = out.new_page(width=pw, height=ph)
        page.insert_image(dest, filename=img_path)
