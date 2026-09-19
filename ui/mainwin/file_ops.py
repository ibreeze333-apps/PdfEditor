# ui/mainwin/file_ops.py — MainWindow 열기/저장/내보내기/인쇄 믹스인
# main_window.py에서 순수 이동(behavior 변경 없음)으로 분리됨.
from __future__ import annotations
import os
import sys
from pathlib import Path

from PySide6.QtGui import (
    QAction, QKeySequence, QShortcut, QIcon, QClipboard, QColor,
    QPainter, QPen, QLinearGradient, QRadialGradient, QPainterPath, QPixmap
)
from PySide6.QtCore import Qt, QSize, QTimer, QPointF, QRectF, QRect
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QFileDialog, QMessageBox,
    QStatusBar, QToolBar, QLabel, QComboBox, QSlider,
    QWidget, QHBoxLayout, QDockWidget, QApplication, QPushButton, QSizePolicy,
    QWidgetAction, QStyle, QSpinBox, QStackedWidget, QGraphicsDropShadowEffect,
    QTabWidget, QTabBar,
)

import config as _cfg

from ui.glass_button import GlassButton
from core.document  import PdfDocument
from core.renderer  import PageRenderer
from core.exporter  import Exporter
from ui.canvas_view import PdfCanvasView
from ui.thumbnail_panel import ThumbnailPanel
from ui.clipboard_panel import ClipboardPanel
from ui.note_panel import NotePanel
from ui.text_draft_editor import TextDraftEditor
from ui.reflow_read_view import ReflowReadView
from ui.texts import UI
from utils.settings import AppSettings
from utils.annot_style import apply_settings_defaults
from utils.errlog import swallowed


class FileOpsMixin:
    def _security_gate(self, path: str) -> bool:
        """파일을 열기 전 위장 파일 검사. 열어도 되면 True.

        파일 대화상자뿐 아니라 드래그앤드롭·명령줄 등 모든 열기 경로에서
        호출해야 한다 — 한 곳이라도 빠지면 위장 실행파일이 그대로 통과한다.
        """
        import logging
        try:
            from utils.file_type import check_mismatch, FileCheckResult
            result = check_mismatch(path)
        except Exception:
            logging.getLogger('pdf_editor').warning(
                '[security] 파일 검사 실패 — 검사 없이 진행: %s', path, exc_info=True)
            return True

        if result.severity == FileCheckResult.BLOCK:
            logging.getLogger('pdf_editor').warning(
                '[security] 열기 차단: %s (탐지=%s)', path, result.label)
            QMessageBox.critical(self, '파일 열기 차단', result.message)
            return False
        if result.severity in (FileCheckResult.WARN, FileCheckResult.ASK):
            logging.getLogger('pdf_editor').info(
                '[security] 형식 불일치 경고: %s (탐지=%s)', path, result.label)
            QMessageBox.warning(self, '파일 형식 경고', result.message)
        return True

    def open_path_checked(self, path: str) -> bool:
        """보안 검사를 거쳐 파일을 연다 (드래그앤드롭·명령줄 진입점)."""
        if not self._security_gate(path):
            return False
        ext = Path(path).suffix.lower()
        if ext in getattr(self, '_IMAGE_EXTS', set()):
            return self._doc.open_image(path)
        return self._doc_open_pw(path)

    def _doc_open_pw(self, path: str) -> bool:
        """PDF 열기 — 암호화 문서면 열람 암호를 물어 인증 후 연다."""
        if self._doc.open(path):
            return True
        if not self._doc.needs_password:
            return False
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        for _ in range(3):
            pw, ok = QInputDialog.getText(
                self, '암호 필요',
                f'이 PDF는 암호로 보호되어 있습니다.\n열람 암호를 입력하세요:\n{Path(path).name}',
                QLineEdit.EchoMode.Password)
            if not ok:
                return False
            if self._doc.open(path, pw):
                return True
            QMessageBox.warning(self, '암호 오류', '암호가 올바르지 않습니다.')
        return False

    """MainWindow 열기/저장/내보내기/인쇄."""


    def _new(self):
        if not self._confirm_discard():
            return
        self._enter_text_draft_mode()
    _IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.webp', '.gif'}


    def _open(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, '파일 열기', '',
            '지원 파일 (*.pdf *.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp *.gif);;'
            'PDF 파일 (*.pdf);;'
            '이미지 파일 (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp *.gif)')
        if not path:
            return
        ext = Path(path).suffix.lower()
        # ── Magika 파일 타입 검증 ────────────────────────────────
        try:
            from utils.file_type import check_mismatch, FileCheckResult
            result = check_mismatch(path)
            if result.severity == FileCheckResult.BLOCK:
                QMessageBox.critical(self, '파일 열기 차단', result.message)
                return   # 완전 차단 — 열지 않음
            elif result.severity == FileCheckResult.ASK:
                btn = QMessageBox.question(self, '파일 형식 불일치', result.message,
                                           QMessageBox.StandardButton.Yes |
                                           QMessageBox.StandardButton.No)
                if btn == QMessageBox.StandardButton.Yes:
                    ok = self._doc_open_pw(path)
                    if not ok:
                        QMessageBox.critical(self, '오류', f'PDF를 열 수 없습니다:\n{path}')
                        return
                    self._settings.add_recent(path)
                    self._settings.save()
                    return
                # No → 이미지로 그냥 열기 (아래 흐름 계속)
            elif result.severity == FileCheckResult.WARN:
                QMessageBox.warning(self, '파일 형식 경고', result.message)
        except Exception:
            pass   # Magika 미설치 또는 오류 → 무시하고 계속

        if ext in self._IMAGE_EXTS:
            ok = self._doc.open_image(path)
            if not ok:
                QMessageBox.critical(self, '오류', f'이미지를 열 수 없습니다:\n{path}')
                return
        else:
            # ── PDF 내부 악성 콘텐츠 스캔 ────────────────────────────
            try:
                from utils.pdf_scanner import scan as _pdf_scan
                scan_result = _pdf_scan(path)
                if not scan_result.is_clean:
                    btn = QMessageBox.warning(
                        self, 'PDF 보안 경고',
                        scan_result.summary(),
                        QMessageBox.StandardButton.Yes |
                        QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if btn != QMessageBox.StandardButton.Yes:
                        return
            except Exception:
                pass  # 스캔 실패해도 열기는 계속

            ok = self._doc_open_pw(path)
            if not ok:
                QMessageBox.critical(self, '오류', f'PDF 파일을 열 수 없습니다:\n{path}')
                return
        self._settings.add_recent(path)
        self._settings.save()


    def _open_in_new_tab(self):
        """새 탭에서 파일을 열기."""
        path, _ = QFileDialog.getOpenFileName(
            self, '새 탭에서 열기', '',
            'PDF 파일 (*.pdf);;이미지 파일 (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp *.gif)')
        if not path:
            return
        # 위장 파일 검사는 _new_tab() 안의 _security_gate() 가 수행한다
        # ── PDF 내부 악성 콘텐츠 스캔 ───────────────────────────────
        ext = Path(path).suffix.lower()
        if ext not in self._IMAGE_EXTS:
            try:
                from utils.pdf_scanner import scan as _pdf_scan
                scan_result = _pdf_scan(path)
                if not scan_result.is_clean:
                    btn = QMessageBox.warning(
                        self, 'PDF 보안 경고',
                        scan_result.summary(),
                        QMessageBox.StandardButton.Yes |
                        QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if btn != QMessageBox.StandardButton.Yes:
                        return
            except Exception:
                swallowed()
        self._new_tab(path)


    def _open_pdf_from_bytes(self, pdf_bytes: bytes, source_path: str = ''):
        """DocViewerDialog에서 변환된 PDF 바이트를 에디터에 새 문서로 열기."""
        import tempfile, os
        # 임시 파일에 쓴 뒤 fitz로 열기 (메모리 스트림 직접 지원은 document.py 수정 불필요)
        suffix = Path(source_path).stem if source_path else 'document'
        tmp = tempfile.NamedTemporaryFile(
            suffix='.pdf', prefix=f'{suffix}_', delete=False
        )
        try:
            tmp.write(pdf_bytes)
            tmp.flush()
            tmp.close()
            ok = self._doc.open(tmp.name)
            if ok:
                self._settings.add_recent(tmp.name)
                self._settings.save()
                self._status_lbl.setText(f'PDF 변환 완료: {Path(source_path).name}')
            else:
                QMessageBox.critical(self, '열기 오류', 'PDF를 열 수 없습니다.')
                os.unlink(tmp.name)
        except Exception as e:
            QMessageBox.critical(self, '열기 오류', f'오류:\n{e}')
            try:
                os.unlink(tmp.name)
            except Exception:
                swallowed()


    def _save(self):
        if self._text_draft_active:
            self._save_text_draft(None)
            return
        if not self._doc.is_open:
            return
        if not self._doc.path:
            self._save_as()
        else:
            self._do_save(None)

    def _confirm_save_over_signature(self) -> bool:
        """서명된 문서를 저장하면 서명이 깨진다는 사실을 미리 알린다.

        PDF 표준상 서명은 '그 시점의 바이트'를 보증하므로, 내용을 고쳐 저장하면
        서명이 무효가 되는 것이 정상이다. 모르고 저장했다가 '서명이 없다'고
        당황하지 않도록 저장 전에 확인받는다."""
        import os as _os
        doc = getattr(self, '_doc', None)
        path = getattr(doc, 'path', '') if doc else ''
        if not path or not _os.path.exists(path):
            return True
        if not getattr(doc, 'dirty', False):
            return True
        try:
            from utils.pdf_sign import verify_pdf_signatures
            sigs = verify_pdf_signatures(path)
        except Exception:
            return True
        if not sigs:
            return True
        ans = QMessageBox.warning(
            self, '서명된 문서',
            f'이 문서에는 디지털 서명이 {len(sigs)}개 있습니다.\n\n'
            '변경분만 덧붙여 저장하므로 서명 자체는 유효하게 남지만,\n'
            '뷰어에는 "서명 이후 문서가 변경됨"으로 표시됩니다\n'
            '(Adobe 등 표준 뷰어와 동일한 동작).\n\n'
            '그래도 저장할까요?\n'
            '※ 서명 당시 상태를 그대로 남기려면 "다른 이름으로 저장"을 쓰세요.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return ans == QMessageBox.StandardButton.Yes

    def _write_permission_ok(self, what: str = '저장') -> bool:
        """열람 암호로만 연 제한 문서의 저장·내보내기를 막는다.

        저장은 복호화된 내용을 다시 쓰는 것이라, 허용하면 열람 암호만 아는
        사람이 '열기 → 저장' 두 번으로 암호도 권한 제한도 없는 사본을 만들 수
        있다. 그러면 권한 설정이 아무 의미가 없어진다.
        관리자 암호로 연 경우에는 소유자이므로 막지 않는다.
        """
        doc = self._doc
        if not getattr(doc, 'was_encrypted', False):
            return True
        if getattr(doc, 'opened_as_owner', True):
            return True
        QMessageBox.warning(
            self, f'{what} 불가',
            f'이 문서는 열람 암호로 열려 있어 {what}할 수 없습니다.\n\n'
            f'{what}하면 암호와 권한 제한이 없는 사본이 만들어져\n'
            '문서에 걸어 둔 제한이 모두 풀리기 때문입니다.\n\n'
            '관리자 암호로 열면 제한 없이 사용할 수 있습니다.')
        self._status_lbl.setText(f'🔒 열람 암호로 연 문서 — {what} 불가')
        return False

    def _confirm_save_over_encryption(self) -> bool:
        """암호로 보호된 문서를 저장하면 암호가 풀린다는 사실을 미리 알린다.

        전체 저장은 복호화된 내용을 다시 쓰는 것이라 암호가 사라진다. 원래
        관리자 암호를 알 수 없으니(열람 암호로 열었을 수 있다) 앱이 되살릴 수도
        없다. 모르고 저장했다가 보호가 풀린 파일이 남는 사고를 막는다.
        """
        if not getattr(self._doc, 'was_encrypted', False):
            return True
        ans = QMessageBox.warning(
            self, '암호가 풀립니다',
            '이 문서는 암호로 보호되어 있습니다.\n\n'
            '저장하면 <b>암호와 권한 제한이 사라진 파일</b>이 됩니다.\n'
            '저장은 내용을 다시 쓰는 작업이라 보호가 유지되지 않고,\n'
            '원래 관리자 암호를 알 수 없어 프로그램이 되살릴 수도 없습니다.\n\n'
            '그래도 저장할까요?\n'
            '※ 저장한 뒤 [보안 → 문서 암호/권한 설정]으로 다시 걸 수 있습니다.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return ans == QMessageBox.StandardButton.Yes

    def _do_save(self, override_path=None):
        """실제 저장 처리. dual copy 옵션 + 미확정 어노테이션 처리."""
        import shutil
        if not self._write_permission_ok('저장'):
            return False
        if not self._confirm_save_over_signature():
            return False
        if not self._confirm_save_over_encryption():
            return False
        n = self._canvas.pending_layer().count()
        if n > 0:
            # 주의: 함수 내 QMessageBox 재import 금지 — 지역 변수로 바뀌어
            # 아래 except 경로에서 UnboundLocalError가 난다 (모듈 import 사용).
            msg = QMessageBox(self)
            msg.setWindowTitle('미확정 어노테이션')
            msg.setText(
                f'미확정 어노테이션이 {n}개 있습니다.\n'
                '저장 시 PDF에 포함할지 선택하세요.')
            btn_apply = msg.addButton('PDF에 적용 후 저장', QMessageBox.ButtonRole.AcceptRole)
            btn_without = msg.addButton('그대로 저장 (미포함)', QMessageBox.ButtonRole.DestructiveRole)
            btn_cancel = msg.addButton('취소', QMessageBox.ButtonRole.RejectRole)
            msg.setDefaultButton(btn_apply)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked not in (btn_apply, btn_without):
                return False
            if clicked == btn_apply and not self._canvas.commit_all_pending():
                QMessageBox.warning(
                    self,
                    '적용 오류',
                    '일부 미확정 어노테이션을 PDF에 적용하지 못했습니다. 문제 항목을 확인한 뒤 다시 저장하세요.',
                )
                return False

        target = override_path or self._doc.path
        if self._settings.save_dual_copy and target:
            src = Path(target)
            if src.exists():
                backup = src.with_stem(src.stem + '_original')
                try:
                    shutil.copy2(src, backup)
                    self._status_lbl.setText(f'백업 생성: {backup.name}')
                except Exception as e:
                    print(f'[MainWindow] 백업 오류: {e}')
        try:
            # 원자적 교체(os.replace)를 위해 파일 핸들을 잡은 렌더 자원 해제
            self._canvas.release_file_handles()
            self._doc.save(override_path)
            self._clear_autosave()
            self._status_lbl.setText(f'저장 완료: {self._doc.path}')
            if self._canvas.is_scroll_mode():
                self._canvas.refresh_page()   # 스크롤 워커 재시작
            return True
        except Exception as e:
            QMessageBox.critical(self, '저장 오류', f'저장에 실패했습니다:\n{e}')
            return False


    def _save_as(self):
        if self._text_draft_active:
            self._save_text_draft(None)
            return
        if not self._doc.is_open:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '다른 이름으로 저장', '', 'PDF 파일 (*.pdf)')
        if path:
            if not path.lower().endswith('.pdf'):
                path += '.pdf'
            self._do_save(path)

    def _is_text_pdf(self) -> bool:
        """PDF에 내장 텍스트가 있는지 확인 (최대 5페이지 샘플링)."""
        fitz_doc = self._doc.fitz_doc()
        n = min(5, fitz_doc.page_count)
        for i in range(n):
            if fitz_doc[i].get_text('text').strip():
                return True
        return False


    def _export_md(self):
        if not self._write_permission_ok('내보내기'):
            return
        if not self._doc.is_open:
            return
        if self._doc.is_image_doc or not self._is_text_pdf():
            msg = (
                '스캔 이미지(JPG/PNG 기반)와 같은 문서\n'
                'Markdown으로 바로 내보낼 수 없습니다.\n\n'
                '‘OCR 텍스트 추출’(Ctrl+Shift+O)을 먼저 실행한 뒤\n'
                '다시 Markdown으로 내보내 주세요.'
                if self._doc.is_image_doc else
                '이 PDF는 텍스트 층이 없습니다 (스캔 문서 가능성).\n'
                'Markdown으로 바로 내보낼 수 없어 내용이 비어 있을 수 있습니다.\n\n'
                '‘OCR 텍스트 추출’(Ctrl+Shift+O)을 먼저 실행한 뒤\n'
                '다시 Markdown으로 내보내 주세요.'
            )
            QMessageBox.information(self, 'Markdown 내보내기 안내', msg)
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Markdown으로 내보내기', '', 'Markdown (*.md)')
        if path:
            self._exporter.to_markdown(self._doc.fitz_doc(), path)
            self._status_lbl.setText(f'MD 내보냄: {path}')


    def _export_md_with_tables(self):
        if not self._write_permission_ok('내보내기'):
            return
        if not self._doc.is_open:
            return
        if self._doc.is_image_doc or not self._is_text_pdf():
            QMessageBox.information(
                self, 'Markdown (테이블 포함) 내보내기 안내',
                '텍스트 층이 없는 문서입니다.\nOCR 텍스트 추출을 먼저 실행한 뒤 다시 시도해 주세요.'
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Markdown (테이블 포함)으로 내보내기', '', 'Markdown (*.md)')
        if path:
            self._exporter.to_markdown_with_tables(self._doc.fitz_doc(), path)
            self._status_lbl.setText(f'MD(테이블) 내보냄: {path}')


    def _img_to_pdf(self):
        from ui.dialogs.image_to_pdf_dialog import ImageToPdfDialog
        dlg = ImageToPdfDialog(self)
        if dlg.exec() and dlg.image_paths():
            path, _ = QFileDialog.getSaveFileName(
                self, '저장 경로', '', 'PDF 파일 (*.pdf)')
            if path:
                if not path.lower().endswith('.pdf'):
                    path += '.pdf'
                ImageToPdfDialog.convert(
                    dlg.image_paths(), path,
                    dlg.page_size(), dlg.fit_to_page())
                self._status_lbl.setText(f'변환 완료: {path}')
                if QMessageBox.question(
                        self, '열기', '변환된 PDF를 여시겠습니까?',
                        QMessageBox.StandardButton.Yes |
                        QMessageBox.StandardButton.No)                         == QMessageBox.StandardButton.Yes:
                    self._doc.open(path)


    def _export_image(self):
        if not self._write_permission_ok('내보내기'):
            return
        if not self._doc.is_open:
            return
        from ui.dialogs.export_image_dialog import ExportImageDialog
        dlg = ExportImageDialog(self._doc, self._canvas.current_page(), self)
        if dlg.exec():
            dlg.export()
            self._status_lbl.setText('이미지 내보내기 완료')


    # ── PDF 유틸리티 ─────────────────────────────────────────────────

    def _export_flattened_image_pdf(self):
        if not self._write_permission_ok('내보내기'):
            return
        if not self._doc.is_open:
            return
        default_name = 'flattened_export.pdf'
        if self._doc.path:
            src = Path(self._doc.path)
            default_name = f'{src.stem}_flattened.pdf'
        path, _ = QFileDialog.getSaveFileName(
            self,
            '플래튼하고 이미지 PDF로 내보내기',
            default_name,
            'PDF 파일 (*.pdf)',
        )
        if not path:
            return
        if not path.lower().endswith('.pdf'):
            path += '.pdf'
        try:
            if self._doc.path and Path(path).resolve() == Path(self._doc.path).resolve():
                raise ValueError('원본 PDF와 같은 경로로는 이미지 PDF를 내보낼 수 없습니다.')
            self._write_flattened_image_pdf(path)
        except Exception as e:
            QMessageBox.critical(
                self,
                '이미지 PDF 내보내기 오류',
                f'이미지 PDF를 만들지 못했습니다:\n{e}',
            )
            return
        self._status_lbl.setText(f'이미지 PDF 내보내기 완료: {path}')
        QMessageBox.information(
            self,
            '이미지 PDF 내보내기 완료',
            '현재 보이는 상태 그대로 새 이미지 PDF를 만들었습니다.\n'
            '텍스트 선택이나 검색은 원본 PDF와 다를 수 있습니다.',
        )


    def _write_flattened_image_pdf(self, path: str):
        import fitz

        out_doc = fitz.open()
        try:
            try:
                out_doc.set_metadata({
                    'title': '',
                    'author': '',
                    'subject': '',
                    'keywords': '',
                    'creator': '',
                    'producer': '',
                    'creationDate': '',
                    'modDate': '',
                    'trapped': '',
                })
            except Exception:
                swallowed()
            export_zoom = 3.0
            for page_index in range(self._doc.page_count()):
                source_page = self._doc.fitz_page(page_index)
                image = self._render_flattened_page_image(page_index, export_zoom)
                image_bytes = self._qimage_to_png_bytes(image)
                out_page = out_doc.new_page(width=source_page.rect.width, height=source_page.rect.height)
                out_page.insert_image(source_page.rect, stream=image_bytes)
            out_doc.save(path, garbage=4, deflate=True, deflate_images=True)
        finally:
            out_doc.close()


    def _render_flattened_page_image(self, page_index: int, zoom: float):
        import fitz
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene
        from ui.canvas_view import _make_pending_item
        from utils.fitz_qt_bridge import pixmap_to_qimage

        page = self._doc.fitz_page(page_index)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, annots=True)
        base_image = pixmap_to_qimage(pix)
        del pix

        pending_items = list(self._canvas.pending_layer().for_page(page_index))
        if not pending_items:
            return base_image

        scene = QGraphicsScene()
        bg_item = QGraphicsPixmapItem(QPixmap.fromImage(base_image))
        scene.addItem(bg_item)
        scene.setSceneRect(0, 0, base_image.width(), base_image.height())

        for pending in pending_items:
            item = _make_pending_item(pending, QPointF(0, 0), zoom)
            if item is None:
                continue
            item.setZValue(20)
            scene.addItem(item)

        out = base_image.copy()
        painter = QPainter(out)
        try:
            scene.render(painter)
        finally:
            painter.end()
        return out


    def _qimage_to_png_bytes(self, image) -> bytes:
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice

        buffer = QByteArray()
        device = QBuffer(buffer)
        if not device.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError('이미지를 PNG 버퍼로 열지 못했습니다.')
        try:
            if not image.save(device, 'PNG'):
                raise RuntimeError('이미지를 PNG로 저장하지 못했습니다.')
        finally:
            device.close()
        return bytes(buffer)


    def _prepare_annots_export(self) -> bool:
        if not self._doc.is_open:
            return False
        pending_n = self._canvas.pending_layer().count()
        if pending_n <= 0:
            return True
        msg = QMessageBox(self)
        msg.setWindowTitle('미확정 어노테이션')
        msg.setText(
            f'미확정 어노테이션 {pending_n}개가 있습니다.\n'
            '저장 시 PDF에 포함할지 선택하세요.')
        btn_apply = msg.addButton('PDF에 적용 후 저장', QMessageBox.ButtonRole.AcceptRole)
        msg.addButton('그대로 저장 (미포함)', QMessageBox.ButtonRole.ActionRole)
        btn_cancel = msg.addButton('취소', QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(btn_apply)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == btn_cancel:
            return False
        if clicked == btn_apply and not self._canvas.commit_all_pending():
            QMessageBox.warning(
                self,
                '적용 오류',
                '일부 미확정 어노테이션을 PDF에 적용하지 못했습니다. 문제 항목을 확인한 뒤 다시 시도하세요.',
            )
            return False
        return True


    def _export_fdf(self):
        if not self._write_permission_ok('내보내기'):
            return
        if not self._prepare_annots_export():
            return
        path, _ = QFileDialog.getSaveFileName(self, 'FDF ', '', 'FDF  (*.fdf)')
        if not path:
            return
        if not path.lower().endswith('.fdf'):
            path += '.fdf'
        self._exporter.export_fdf(self._doc.fitz_doc(), path)
        self._status_lbl.setText(f'FDF 저장: {path}')


    def _export_xfdf(self):
        if not self._write_permission_ok('내보내기'):
            return
        if not self._prepare_annots_export():
            return
        path, _ = QFileDialog.getSaveFileName(self, 'XFDF ', '', 'XFDF  (*.xfdf)')
        if not path:
            return
        if not path.lower().endswith('.xfdf'):
            path += '.xfdf'
        self._exporter.export_xfdf(self._doc.fitz_doc(), path)
        self._status_lbl.setText(f'XFDF 저장: {path}')


    def _compress_pdf(self):
        if not self._write_permission_ok('용량 줄이기'):
            return
        if not self._doc.is_open:
            return
        from ui.dialogs.compress_pdf_dialog import CompressPdfDialog
        dlg = CompressPdfDialog(
            self._doc.fitz_doc(), self._doc.path, self)
        dlg.exec()


    def _image_pdf_merge(self):
        from ui.dialogs.image_pdf_merge_dialog import ImagePdfMergeDialog
        ImagePdfMergeDialog(self).exec()


    def _split_by_size(self):
        if not self._write_permission_ok('분할'):
            return
        if not self._doc.is_open:
            return
        from ui.dialogs.split_by_size_dialog import SplitBySizeDialog
        dlg = SplitBySizeDialog(
            self._doc.fitz_doc(), self._doc.path, self)
        dlg.exec()


    def _print_windows(self):
        """프린터 대화상자를 띄우고 페이지를 직접 그려서 인쇄한다.

        예전에는 os.startfile(path, 'print') 로 Windows 에 떠넘겼는데, 그 방식은
        레지스트리에 .pdf 용 'print' 동사가 등록된 PDF 앱이 있어야만 동작한다.
        Edge 등 요즘 기본 뷰어는 등록하지 않아 WinError 1155 로 실패했다.
        (게다가 성공해도 대화상자 없이 기본 프린터로 바로 나가버려서 프린터
        선택·매수·페이지 범위를 고를 수 없었다.)
        """
        if not self._doc.is_open:
            return
        import tempfile
        from pathlib import Path as _Path
        from PySide6.QtWidgets import QMessageBox, QDialog, QProgressDialog
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        from PySide6.QtGui import QImage, QPainter, QPageLayout
        from PySide6.QtCore import QRectF

        if not getattr(self, '_perm_print_ok', True):
            QMessageBox.warning(self, '권한 제한',
                                '이 문서는 인쇄가 제한되어 있습니다.\n'
                                '권한(소유자) 암호로 열면 인쇄할 수 있습니다.')
            return
        if not self._prepare_annots_export():
            return

        target = self._doc.path
        if not target or self._doc.dirty:
            temp_dir = _Path(tempfile.gettempdir()) / 'pdf_editor_print'
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_path = temp_dir / 'print_temp.pdf'
            self._doc.save(str(temp_path))
            target = str(temp_path)

        import fitz
        try:
            src = fitz.open(target)
        except Exception as e:
            QMessageBox.critical(self, '인쇄 오류', f'인쇄할 파일을 열지 못했습니다:\n{e}')
            return

        try:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setDocName(_Path(target).stem)
            printer.setFromTo(1, src.page_count)
            # 첫 쪽이 가로면 가로 용지를 기본값으로 — 사용자가 대화상자에서 바꿀 수 있다
            first_rect = src[0].rect
            if first_rect.width > first_rect.height:
                printer.setPageOrientation(QPageLayout.Orientation.Landscape)

            dlg = QPrintDialog(printer, self)
            dlg.setWindowTitle('인쇄')
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self._status_lbl.setText('인쇄 취소됨')
                return

            rng = printer.printRange()
            if rng == QPrinter.PrintRange.PageRange:
                pages = list(range(max(0, printer.fromPage() - 1),
                                   min(src.page_count, printer.toPage())))
            elif rng == QPrinter.PrintRange.CurrentPage:
                pages = [self._canvas.current_page()]
            else:
                pages = list(range(src.page_count))
            if not pages:
                QMessageBox.warning(self, '인쇄', '인쇄할 페이지가 없습니다.')
                return

            # 프린터는 1200dpi 를 보고하기도 한다. 그 해상도로 그리면 A4 한 장이
            # 9500px 를 넘어 장당 400MB 에 가까운 그림이 되므로 300dpi 로 막는다.
            # (용지에 채우는 일은 drawImage 가 확대해서 해 준다.)
            res = printer.resolution() or 300
            render_dpi = min(res, 300)

            prog = QProgressDialog('인쇄 중…', '취소', 0, len(pages), self)
            prog.setWindowTitle('인쇄')
            prog.setMinimumDuration(400)

            painter = QPainter()
            if not painter.begin(printer):
                QMessageBox.critical(self, '인쇄 오류',
                                     '프린터를 시작하지 못했습니다.\n'
                                     '프린터가 연결되어 있는지 확인해 주세요.')
                return
            try:
                for n, idx in enumerate(pages):
                    if prog.wasCanceled():
                        printer.abort()
                        self._status_lbl.setText('인쇄 취소됨')
                        return
                    prog.setValue(n)
                    if n:
                        printer.newPage()

                    page = src[idx]
                    pw, ph = page.rect.width, page.rect.height
                    if pw <= 0 or ph <= 0:
                        continue
                    area = printer.pageRect(QPrinter.Unit.DevicePixel)
                    # 비율을 지키며 인쇄 가능 영역에 맞춘다(장치 픽셀 기준)
                    fit = min(area.width() / (pw / 72.0 * res),
                              area.height() / (ph / 72.0 * res))
                    dw, dh = pw / 72.0 * res * fit, ph / 72.0 * res * fit
                    # 그림은 300dpi 로만 만들고, 용지 크기까지는 drawImage 가 늘린다
                    zoom = render_dpi / 72.0 * fit
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                    img = QImage(pix.samples, pix.width, pix.height,
                                 pix.stride, QImage.Format.Format_RGB888)
                    x = area.x() + (area.width() - dw) / 2.0
                    y = area.y() + (area.height() - dh) / 2.0
                    painter.drawImage(QRectF(x, y, dw, dh), img)
                    del pix
                prog.setValue(len(pages))
            finally:
                painter.end()

            self._status_lbl.setText(
                f'인쇄 요청 완료: {len(pages)}쪽 → {printer.printerName()}')
        except Exception as e:
            QMessageBox.critical(self, '인쇄 오류', f'인쇄에 실패했습니다:\n{e}')
        finally:
            src.close()

