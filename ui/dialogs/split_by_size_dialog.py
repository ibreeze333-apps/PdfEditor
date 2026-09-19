# ui/dialogs/split_by_size_dialog.py — 파일 크기별 PDF 분할
from __future__ import annotations
import io
import os
import fitz
from pathlib import Path
from ui.dialogs.split_pdf_dialog import SplitOutputMixin
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox,
    QDialogButtonBox, QFileDialog, QMessageBox, QProgressDialog,
    QCheckBox, QGroupBox,
)


class SplitBySizeDialog(SplitOutputMixin, QDialog):
    """지정한 파일 크기(MB)를 초과하지 않도록 PDF를 여러 파트로 분할.

    알고리즘:
        1단계: 각 페이지를 개별로 저장해 압축 크기를 측정.
        2단계: 누적 크기가 목표치를 넘기 직전에 파트를 끊고 저장.
    """

    def __init__(self, fitz_doc: fitz.Document, orig_path: str = '', parent=None):
        super().__init__(parent)
        self._doc       = fitz_doc
        self._orig_path = orig_path
        self.setWindowTitle('크기별 PDF 분할')
        self.setMinimumWidth(400)
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────
    def _build_ui(self):
        ly = QVBoxLayout(self)

        n = self._doc.page_count
        size_info = ''
        if self._orig_path and os.path.exists(self._orig_path):
            total_mb = os.path.getsize(self._orig_path) / 1048576
            size_info = f'  (현재 {total_mb:.1f} MB)'
        ly.addWidget(QLabel(f'현재 문서: {n}페이지{size_info}'))

        # 목표 크기
        grp = QGroupBox('분할 크기 설정')
        g_ly = QVBoxLayout(grp)

        row = QHBoxLayout()
        row.addWidget(QLabel('파트당 최대 크기:'))
        self._size_sb = QDoubleSpinBox()
        self._size_sb.setRange(0.5, 2000.0)
        self._size_sb.setValue(20.0)
        self._size_sb.setSingleStep(5.0)
        self._size_sb.setDecimals(1)
        self._size_sb.setSuffix(' MB')
        row.addWidget(self._size_sb)
        row.addStretch()
        g_ly.addLayout(row)

        self._compress_cb = QCheckBox('저장 시 압축 적용 (권장)')
        self._compress_cb.setChecked(True)
        g_ly.addWidget(self._compress_cb)
        ly.addWidget(grp)

        note = QLabel(
            '※ 측정 방식: 각 페이지의 압축 크기를 개별 측정 후 누적합산.\n'
            '   공유 폰트/리소스로 인해 실제 크기와 약간 차이가 날 수 있습니다.')
        note.setWordWrap(True)
        note.setStyleSheet('color: gray; font-size: 11px;')
        ly.addWidget(note)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('크기 측정 후 분할…')
        btns.accepted.connect(self._run)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)

    # ── 실행 ─────────────────────────────────────────────────────────
    def _run(self):
        folder = QFileDialog.getExistingDirectory(self, '분할 파일 저장 폴더')
        if not folder:
            return

        target_bytes = int(self._size_sb.value() * 1048576)
        n            = self._doc.page_count
        compress     = self._compress_cb.isChecked()
        save_kw      = dict(garbage=4, deflate=True, deflate_images=True,
                            deflate_fonts=True) if compress else {}

        # ── 1단계: 페이지별 크기 측정 ─────────────────────────────
        prog = QProgressDialog('페이지 크기 측정 중…', '취소', 0, n * 2, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.show()

        page_sizes: list[int] = []
        try:
            for i in range(n):
                prog.setValue(i)
                prog.setLabelText(f'[1/2] 페이지 {i + 1}/{n} 크기 측정 중…')
                if prog.wasCanceled():
                    return
                tmp = fitz.open()
                tmp.insert_pdf(self._doc, from_page=i, to_page=i)
                buf = io.BytesIO()
                tmp.save(buf, **save_kw)
                page_sizes.append(len(buf.getvalue()))
                tmp.close()
        except Exception as e:
            QMessageBox.critical(self, '오류', f'크기 측정 실패:\n{e}')
            return
        finally:
            prog.close()

        # ── 2단계: 그리디 그룹핑 ──────────────────────────────────
        groups: list[list[int]] = []
        current: list[int]      = []
        current_size            = 0

        for i, sz in enumerate(page_sizes):
            if sz > target_bytes:
                # 단일 페이지가 목표치 초과 → 경고 후 단독 파트
                if current:
                    groups.append(current)
                    current      = []
                    current_size = 0
                groups.append([i])
            elif current_size + sz > target_bytes and current:
                groups.append(current)
                current      = [i]
                current_size = sz
            else:
                current.append(i)
                current_size += sz

        if current:
            groups.append(current)

        outputs = []
        reserved = set()
        for i in range(len(groups)):
            choice = self._choose_output(Path(folder) / f'part_{i + 1:03d}.pdf',
                                         reserved, self._orig_path or self._doc.name)
            if choice is None:
                return
            outputs.append(choice)
            reserved.add(self._path_key(choice[0]))

        # ── 3단계: 파트 저장 ───────────────────────────────────────
        total_parts = len(groups)
        prog2 = QProgressDialog('파트 저장 중…', '취소', 0, total_parts, self)
        prog2.setWindowModality(Qt.WindowModality.WindowModal)
        prog2.setMinimumDuration(0)
        prog2.show()

        saved_paths = []
        try:
            for pi, pages in enumerate(groups):
                prog2.setValue(pi)
                prog2.setLabelText(
                    f'[2/2] 파트 {pi + 1}/{total_parts} 저장 중…\n'
                    f'(페이지 {pages[0]+1}~{pages[-1]+1})')
                if prog2.wasCanceled():
                    break

                out_path, overwrite = outputs[pi]
                with fitz.open() as out:
                    for p in pages:
                        out.insert_pdf(self._doc, from_page=p, to_page=p)
                    self._save_output(out, out_path, overwrite, **save_kw)
                actual_mb = os.path.getsize(out_path) / 1048576
                saved_paths.append((str(out_path), actual_mb))

            prog2.setValue(total_parts)
        except Exception as e:
            QMessageBox.critical(self, '오류', f'저장 실패:\n{e}')
            return
        finally:
            prog2.close()

        # 결과 요약
        summary = '\n'.join(
            f'  파트 {i+1}: {os.path.basename(p)}  ({mb:.1f} MB)'
            for i, (p, mb) in enumerate(saved_paths))
        QMessageBox.information(
            self, '완료',
            f'분할 완료! {len(saved_paths)}개 파트\n\n{summary}\n\n저장 폴더: {folder}')
        self.accept()
