# ui/dialogs/compress_pdf_dialog.py — PDF 용량 줄이기
from __future__ import annotations
import io
import os
import fitz
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QSpinBox, QDialogButtonBox, QFileDialog,
    QMessageBox, QProgressDialog, QGroupBox, QRadioButton,
)


class CompressPdfDialog(QDialog):
    """PDF 파일 용량 줄이기.

    방식 1 – 구조 최적화(빠름, 텍스트 보존):
        fitz 저장 옵션만으로 중복 리소스 제거·스트림 압축.

    방식 2 – 이미지 재렌더링(느림, 최대 압축):
        각 페이지를 지정 DPI/품질의 JPEG 이미지로 다시 렌더링.
        텍스트 레이어는 사라지지만 스캔본에는 적합.
    """

    def __init__(self, fitz_doc: fitz.Document, orig_path: str = '', parent=None):
        super().__init__(parent)
        self._doc       = fitz_doc
        self._orig_path = orig_path
        self.setWindowTitle('PDF 용량 줄이기')
        self.setMinimumWidth(420)
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────────────────
    def _build_ui(self):
        ly = QVBoxLayout(self)

        # 파일 정보
        n = self._doc.page_count
        size_mb = ''
        if self._orig_path and os.path.exists(self._orig_path):
            size_mb = f'  ({os.path.getsize(self._orig_path) / 1048576:.1f} MB)'
        ly.addWidget(QLabel(f'현재 문서: {n}페이지{size_mb}'))

        # ── 방식 선택 ─────────────────────────────────────────────────
        grp = QGroupBox('압축 방식')
        grp_ly = QVBoxLayout(grp)
        self._rb_struct = QRadioButton(
            '구조 최적화  (빠름 · 텍스트/벡터 보존 · 중간 압축)')
        self._rb_raster = QRadioButton(
            '이미지 재렌더링  (느림 · 텍스트 레이어 삭제 · 최대 압축)')
        self._rb_struct.setChecked(True)
        grp_ly.addWidget(self._rb_struct)
        grp_ly.addWidget(self._rb_raster)
        ly.addWidget(grp)

        # ── 이미지 옵션 (재렌더링 모드에서만 활성화) ──────────────────
        img_grp = QGroupBox('이미지 재렌더링 옵션')
        img_ly  = QVBoxLayout(img_grp)

        dpi_row = QHBoxLayout()
        dpi_row.addWidget(QLabel('출력 DPI:'))
        self._dpi_sb = QSpinBox()
        self._dpi_sb.setRange(72, 300)
        self._dpi_sb.setValue(120)
        self._dpi_sb.setSuffix(' DPI')
        dpi_row.addWidget(self._dpi_sb)
        dpi_row.addStretch()
        img_ly.addLayout(dpi_row)

        q_row = QHBoxLayout()
        q_row.addWidget(QLabel('JPEG 품질:'))
        self._qual_cb = QComboBox()
        self._qual_cb.addItems(['최고 (95)', '높음 (80)', '보통 (60)', '낮음 (40)', '최저 (20)'])
        self._qual_cb.setCurrentIndex(2)
        q_row.addWidget(self._qual_cb)
        q_row.addStretch()
        img_ly.addLayout(q_row)

        self._gray_cb = QCheckBox('흑백으로 변환  (추가 50~60% 감소)')
        img_ly.addWidget(self._gray_cb)
        ly.addWidget(img_grp)

        # 공통 옵션
        self._meta_cb = QCheckBox('메타데이터 제거')
        self._meta_cb.setChecked(True)
        ly.addWidget(self._meta_cb)

        # 라디오 → 옵션 그룹 활성화 토글
        self._rb_raster.toggled.connect(img_grp.setEnabled)
        img_grp.setEnabled(False)

        # 버튼
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('압축 & 저장…')
        btns.accepted.connect(self._run)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)

    # ── 실행 ─────────────────────────────────────────────────────────
    def _quality_value(self) -> int:
        return [95, 80, 60, 40, 20][self._qual_cb.currentIndex()]

    def _run(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '압축 파일 저장', 'compressed.pdf', 'PDF (*.pdf)')
        if not path:
            return
        if not path.lower().endswith('.pdf'):
            path += '.pdf'

        try:
            if self._rb_raster.isChecked():
                self._run_raster(path)
            else:
                self._run_struct(path)
        except Exception as e:
            QMessageBox.critical(self, '오류', f'압축 실패:\n{e}')
            return

        new_mb = os.path.getsize(path) / 1048576
        QMessageBox.information(
            self, '완료',
            f'압축 완료!\n저장 위치: {path}\n새 크기: {new_mb:.1f} MB')
        self.accept()

    def _run_struct(self, path: str):
        """구조 최적화: fitz save 옵션만 사용."""
        out = fitz.open()
        out.insert_pdf(self._doc)
        if self._meta_cb.isChecked():
            out.set_metadata({})
        out.save(path, garbage=4, deflate=True,
                 deflate_images=True, deflate_fonts=True, clean=True)
        out.close()

    def _run_raster(self, path: str):
        """이미지 재렌더링: 각 페이지를 JPEG 이미지로 다시 그림."""
        n       = self._doc.page_count
        dpi     = self._dpi_sb.value()
        quality = self._quality_value()
        gray    = self._gray_cb.isChecked()
        mat     = fitz.Matrix(dpi / 72, dpi / 72)
        cs      = fitz.csGRAY if gray else fitz.csRGB

        prog = QProgressDialog('페이지 렌더링 중…', '취소', 0, n, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.show()

        out = fitz.open()
        try:
            for i in range(n):
                prog.setValue(i)
                prog.setLabelText(f'페이지 {i + 1} / {n} 렌더링 중…')
                if prog.wasCanceled():
                    out.close()
                    return

                page = self._doc[i]
                pix  = page.get_pixmap(matrix=mat, alpha=False, colorspace=cs)
                jpg  = pix.tobytes('jpeg', jpg_quality=quality)

                new_page = out.new_page(width=page.rect.width,
                                         height=page.rect.height)
                new_page.insert_image(new_page.rect, stream=jpg)
                pix = None   # free memory

            prog.setValue(n)
            if self._meta_cb.isChecked():
                out.set_metadata({})
            out.save(path, garbage=4, deflate=True, deflate_images=True)
        finally:
            out.close()
        prog.close()
