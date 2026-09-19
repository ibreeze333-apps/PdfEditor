# ui/mainwin/security.py — MainWindow 보안 기능 믹스인
# 암호/권한, 워터마크(재사용), 개인정보 교정(redaction), 전자 서명
from __future__ import annotations
import os
import logging
import fitz
from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QMessageBox
from utils.errlog import swallowed

logger = logging.getLogger('pdf_editor')


class SecurityMixin:
    """상단 '보안' 메뉴 기능."""

    # ── 1) 암호 / 권한 ───────────────────────────────────────────────
    def _open_encrypt_dialog(self):
        if not self._doc.is_open:
            QMessageBox.information(self, '보안', '문서를 먼저 여세요.')
            return
        from ui.dialogs.security_dialog import EncryptDialog
        dlg = EncryptDialog(self)
        if not dlg.exec():
            return
        user_pw, owner_pw = dlg.user_pw(), dlg.owner_pw()
        if not user_pw and not owner_pw:
            QMessageBox.warning(self, '보안', '열람 암호 또는 관리자 암호를 하나 이상 입력하세요.')
            return
        if user_pw and owner_pw and user_pw == owner_pw:
            QMessageBox.warning(
                self, '보안',
                '열람 암호와 관리자 암호가 같으면 권한 제한이 걸리지 않습니다.\n'
                '두 암호를 서로 다르게 지정하세요.\n\n'
                '(PDF 규격상 관리자 암호로 열면 모든 권한이 허용됩니다.)')
            return
        perms = dlg.permissions()
        # 관리자 암호를 비워 두면 권한 제한이 무의미해진다 — PDF 규격상 권한
        # 검사를 우회하는 열쇠가 관리자 암호이기 때문이다. 예전에는 빈칸일 때
        # 열람 암호를 그대로 관리자 암호로 썼는데, 그러면 문서를 연 사람이
        # 곧 권한 소유자가 되어 체크한 제한이 전부 풀렸다.
        if not owner_pw:
            if perms != dlg.all_permissions():
                ans = QMessageBox.question(
                    self, '관리자 암호 필요',
                    '권한을 제한하려면 관리자 암호가 필요합니다.\n'
                    'PDF 규격상 관리자 암호를 아는 사람은 모든 제한을 무시할 수 있고,\n'
                    '관리자 암호가 없으면 제한을 걸 대상 자체가 없기 때문입니다.\n\n'
                    '임의의 관리자 암호를 자동 생성해서 제한을 걸까요?\n'
                    '(아니오를 고르면 제한 없이 열람 암호만 겁니다.)',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes)
                if ans == QMessageBox.StandardButton.Yes:
                    import secrets
                    owner_pw = secrets.token_urlsafe(24)   # 아무도 모르는 값
                else:
                    owner_pw = user_pw
                    perms = dlg.all_permissions()   # 제한 없음을 정직하게 기록
            else:
                owner_pw = user_pw
        # 미확정 주석 먼저 반영
        try:
            self._canvas.commit_all_pending()
        except Exception:
            swallowed()

        base = self._doc.path or 'document.pdf'
        suggested = str(Path(base).with_name(Path(base).stem + '_encrypted.pdf'))
        path, _ = QFileDialog.getSaveFileName(
            self, '암호화 사본 저장', suggested, 'PDF (*.pdf)')
        if not path:
            return
        try:
            self._canvas.release_file_handles()
        except Exception:
            swallowed()
        try:
            # 열려 있는 원본과 같은 경로면 PyMuPDF 가 직접 저장을 거부한다
            # ("save to original must be incremental"). 임시 파일에 쓴 뒤
            # 원자적으로 바꿔치운다.
            tmp_out = path + '.encrypting.tmp'
            self._doc.fitz_doc().save(
                tmp_out,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw=owner_pw,
                user_pw=user_pw,
                permissions=perms,
                garbage=3, deflate=True,
            )
            same_as_open = os.path.abspath(path) == os.path.abspath(self._doc.path or '')
            if same_as_open:
                # 원본 파일을 갈아치우기 전에 문서가 그 파일을 놓게 한다
                self._doc.detach_from_file()
            try:
                os.replace(tmp_out, path)
            except BaseException:
                try:
                    os.remove(tmp_out)
                except OSError:
                    swallowed()
                raise
        except Exception as exc:
            logger.exception('[Security] 암호화 저장 실패')
            QMessageBox.critical(self, '보안', f'암호화 저장에 실패했습니다.\n{exc}')
            return
        finally:
            try:
                self._canvas.refresh_page()
            except Exception:
                swallowed()
        self._status_lbl.setText(f'암호화 사본 저장 완료: {path}')
        if QMessageBox.question(
                self, '완료',
                f'암호화된 사본을 저장했습니다.\n{path}\n\n새 탭에서 열어볼까요?') \
                == QMessageBox.StandardButton.Yes:
            try:
                self._new_tab(path)
            except Exception:
                swallowed()

    # ── 2) 개인정보 교정 (redaction) ─────────────────────────────────
    def _open_redact_dialog(self):
        if not self._doc.is_open:
            QMessageBox.information(self, '보안', '문서를 먼저 여세요.')
            return
        from ui.dialogs.security_dialog import RedactDialog
        dlg = RedactDialog(self)
        if not dlg.exec():
            return
        patterns, literals = dlg.patterns(), dlg.literals()
        if not patterns and not literals:
            QMessageBox.warning(self, '보안', '검색할 유형이나 문구를 하나 이상 지정하세요.')
            return
        try:
            self._canvas.commit_all_pending()
        except Exception:
            swallowed()
        fitz_doc = self._doc.fitz_doc()
        pages = (list(range(fitz_doc.page_count))
                 if dlg.all_pages() else [self._canvas.current_page()])
        try:
            count = RedactDialog.apply(fitz_doc, pages, patterns, literals, dlg.show_label())
        except Exception as exc:
            logger.exception('[Security] 교정 실패')
            QMessageBox.critical(self, '보안', f'교정 처리에 실패했습니다.\n{exc}')
            return
        self._doc.mark_dirty()
        self._renderer.invalidate_all()
        self._canvas.refresh_page()
        if count:
            self._status_lbl.setText(f'개인정보 교정 완료: {count}건 삭제')
            QMessageBox.information(
                self, '교정 완료',
                f'{count}건을 영구 삭제했습니다.\n변경을 보존하려면 저장(Ctrl+S)하세요.')
        else:
            QMessageBox.information(self, '교정', '해당하는 내용을 찾지 못했습니다. '
                                    '(스캔 이미지 PDF는 먼저 OCR이 필요합니다.)')

    # ── 3) 전자 서명 (가시 서명) ─────────────────────────────────────
    def _open_signature_dialog(self):
        if not self._doc.is_open:
            QMessageBox.information(self, '보안', '문서를 먼저 여세요.')
            return
        from ui.dialogs.security_dialog import SignatureDialog
        default_name = ''
        try:
            default_name = (self._doc.fitz_doc().metadata or {}).get('author', '') or ''
        except Exception:
            swallowed()
        dlg = SignatureDialog(self, default_name=default_name)
        if not dlg.exec():
            return
        if dlg.is_image() and not dlg.image_path():
            QMessageBox.warning(self, '보안', '서명 이미지를 먼저 선택하세요.')
            return
        if not dlg.is_image() and not dlg.name():
            QMessageBox.warning(self, '보안', '서명자 이름을 입력하세요.')
            return
        try:
            self._canvas.commit_all_pending()
        except Exception:
            swallowed()
        fitz_doc = self._doc.fitz_doc()
        pages = (list(range(fitz_doc.page_count))
                 if dlg.all_pages() else [self._canvas.current_page()])
        try:
            ok = SignatureDialog.apply(
                fitz_doc, pages,
                is_image=dlg.is_image(), image_path=dlg.image_path(),
                name=dlg.name(), with_date=dlg.with_date(),
                pos=dlg.position(), size_px=dlg.size_px(),
                opacity=dlg.opacity())
        except Exception as exc:
            logger.exception('[Security] 서명 삽입 실패')
            QMessageBox.critical(self, '보안', f'서명 삽입에 실패했습니다.\n{exc}')
            return
        if not ok:
            QMessageBox.warning(self, '보안', '서명을 삽입하지 못했습니다.')
            return
        self._doc.mark_dirty()
        self._renderer.invalidate_all()
        self._canvas.refresh_page()
        self._status_lbl.setText('전자 서명 삽입 완료')

    # ── 3-1) 인증서 배포용 내보내기 ──────────────────────────────────
    def _export_public_cert(self):
        """.p12 에서 개인키를 뺀 공개 인증서만 뽑아 저장한다.

        자체 서명 인증서로 서명한 PDF 는 받는 쪽에서 "신뢰할 수 없는 서명"으로
        뜬다. 이 파일을 함께 건네고 상대가 인증서 관리에 등록하면 "유효"가 된다.
        .p12 를 그대로 주면 개인키까지 넘어가므로 절대 그러면 안 된다.
        """
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        p12, _ = QFileDialog.getOpenFileName(
            self, '내보낼 인증서 선택', '', 'PKCS#12 인증서 (*.p12 *.pfx)')
        if not p12:
            return
        pw, ok = QInputDialog.getText(
            self, '인증서 암호', f'{os.path.basename(p12)} 의 암호',
            QLineEdit.EchoMode.Password)
        if not ok:
            return
        out, _ = QFileDialog.getSaveFileName(
            self, '공개 인증서 저장', str(Path(p12).with_suffix('.p7b')),
            'PKCS#7 인증서 묶음 (*.p7b *.p7c);;'
            'DER 인증서 (*.cer);;PEM 인증서 (*.crt)')
        if not out:
            return
        try:
            from utils.pdf_sign import export_public_cert
            export_public_cert(p12, pw, out)
        except Exception as exc:
            logger.exception('[Security] 공개 인증서 내보내기 실패')
            QMessageBox.critical(self, '보안', f'내보내지 못했습니다:\n{exc}')
            return
        self._status_lbl.setText(f'공개 인증서 저장: {out}')
        QMessageBox.information(
            self, '보안',
            f'공개 인증서를 저장했습니다.\n{out}\n\n'
            f'이 파일은 개인키가 없어 안전하게 건넬 수 있습니다.\n'
            f'받는 쪽이 PDF 프로그램의 [인증서 관리]에 등록하면\n'
            f'우리 서명이 "유효"로 표시됩니다.')

    # ── 4) 표준 디지털 서명 (인증서, pyHanko) ────────────────────────
    def _open_cert_sign_dialog(self):
        if not self._doc.is_open:
            QMessageBox.information(self, '보안', '문서를 먼저 여세요.')
            return
        from ui.dialogs.cert_sign_dialog import CertSignDialog
        default_name = ''
        try:
            default_name = (self._doc.fitz_doc().metadata or {}).get('author', '') or ''
        except Exception:
            swallowed()
        # 서명은 문서를 통째로 다시 쓰므로 암호·권한이 유지되지 않는다.
        # 서명된 파일을 그대로 배포하면 누구나 편집할 수 있게 되므로 미리 알린다.
        if getattr(self._doc, 'was_encrypted', False):
            ans = QMessageBox.warning(
                self, '암호가 풀립니다',
                '이 문서는 암호로 보호되어 있습니다.\n\n'
                '서명하면 서명된 사본에서 <b>암호와 권한 제한이 사라집니다</b>.\n'
                '서명은 문서를 다시 쓰는 작업이라 보호가 유지되지 않고,\n'
                '원래 관리자 암호를 알 수 없어 프로그램이 되살릴 수도 없습니다.\n\n'
                '계속할까요?\n'
                '※ 서명한 뒤 [보안 → 문서 암호/권한 설정]으로 다시 걸 수 있습니다.\n'
                '   (단, 암호를 걸면 서명은 무효가 됩니다 — 둘 중 하나만 됩니다.)',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return

        dlg = CertSignDialog(self, default_name=default_name)
        if not dlg.exec():
            return
        if not dlg.password():
            QMessageBox.warning(self, '보안', '인증서 암호를 입력하세요.')
            return

        import os, tempfile
        # 인증서 준비 (기존 파일 or 새로 생성)
        p12_path = dlg.p12_path()
        if not dlg.use_existing():
            if not dlg.new_name():
                QMessageBox.warning(self, '보안', '인증서에 넣을 이름을 입력하세요.')
                return
            save_p12, _ = QFileDialog.getSaveFileName(
                self, '새 인증서 저장 (.p12)',
                str(Path(self._doc.path or 'signer').with_name(
                    (dlg.new_name() or 'signer') + '.p12')),
                'PKCS#12 인증서 (*.p12)')
            if not save_p12:
                return
            try:
                from utils.pdf_sign import generate_self_signed_p12
                data = generate_self_signed_p12(dlg.new_name(), dlg.new_org(), dlg.password())
                with open(save_p12, 'wb') as f:
                    f.write(data)
            except Exception as exc:
                logger.exception('[Security] 인증서 생성 실패')
                QMessageBox.critical(self, '보안', f'인증서 생성 실패:\n{exc}')
                return
            p12_path = save_p12
        elif not (p12_path and os.path.exists(p12_path)):
            QMessageBox.warning(self, '보안', '인증서 파일을 선택하세요.')
            return

        # ── 다른 프로그램과의 호환 처리 (실패해도 서명은 계속한다) ──
        if dlg.install_to_store():
            try:
                from utils.pdf_sign import install_p12_to_windows_store
                install_p12_to_windows_store(p12_path, dlg.password())
                self._status_lbl.setText('인증서를 Windows 저장소에 설치했습니다')
            except Exception as exc:
                logger.exception('[Security] 인증서 저장소 설치 실패')
                QMessageBox.warning(
                    self, '보안',
                    f'Windows 인증서 저장소에 설치하지 못했습니다:\n{exc}\n\n'
                    f'서명은 그대로 진행합니다.\n'
                    f'수동으로 하려면 {os.path.basename(p12_path)} 파일을 더블클릭해\n'
                    f'[현재 사용자] → [개인] 저장소로 가져오세요.')
        if dlg.export_public():
            pub_default = str(Path(p12_path).with_suffix('.p7b'))
            pub, _ = QFileDialog.getSaveFileName(
                self, '배포용 공개 인증서 저장', pub_default,
                'PKCS#7 인증서 묶음 (*.p7b *.p7c);;'
                'DER 인증서 (*.cer);;PEM 인증서 (*.crt)')
            if pub:
                try:
                    from utils.pdf_sign import export_public_cert
                    export_public_cert(p12_path, dlg.password(), pub)
                except Exception as exc:
                    logger.exception('[Security] 공개 인증서 내보내기 실패')
                    QMessageBox.warning(
                        self, '보안', f'공개 인증서를 내보내지 못했습니다:\n{exc}')

        # 현재 문서 상태를 임시 파일로 (미확정 주석 반영)
        try:
            self._canvas.commit_all_pending()
        except Exception:
            swallowed()
        try:
            self._canvas.release_file_handles()
        except Exception:
            swallowed()
        tmp_in = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        tmp_in.close()
        try:
            self._doc.save_copy(tmp_in.name, garbage=3)
        except Exception as exc:
            QMessageBox.critical(self, '보안', f'서명 준비 실패:\n{exc}')
            return

        # 보이는 서명 박스 (현재 페이지)
        visible_box = None
        page_h = 0.0
        page_idx = self._canvas.current_page()
        if dlg.visible():
            try:
                pr = self._doc.fitz_page(page_idx).rect
                page_h = pr.height
                w = dlg.stamp_width()
                h, m = w * (60.0 / 190.0), 24.0
                pos = dlg.position()
                if pos == 'br':
                    x0, y0 = pr.width - m - w, pr.height - m - h
                elif pos == 'bl':
                    x0, y0 = m, pr.height - m - h
                elif pos == 'tr':
                    x0, y0 = pr.width - m - w, m
                else:
                    x0, y0 = m, m
                visible_box = (x0, y0, x0 + w, y0 + h)
            except Exception:
                visible_box = None

        out, _ = QFileDialog.getSaveFileName(
            self, '서명된 PDF 저장',
            str(Path(self._doc.path or 'document.pdf').with_name(
                Path(self._doc.path or 'document.pdf').stem + '_signed.pdf')),
            'PDF (*.pdf)')
        if not out:
            try: os.unlink(tmp_in.name)
            except Exception: pass
            return
        try:
            from utils.pdf_sign import sign_pdf
            sign_pdf(tmp_in.name, out, p12_path, dlg.password(),
                     reason=dlg.reason(), location=dlg.location(),
                     visible_box=visible_box, page=page_idx, page_height=page_h,
                     stamp_opacity=dlg.stamp_opacity(),
                     signer_label=dlg.new_name() or default_name)
        except Exception as exc:
            logger.exception('[Security] 서명 실패')
            QMessageBox.critical(self, '보안',
                                 f'서명에 실패했습니다.\n{exc}\n\n'
                                 '인증서 암호가 맞는지 확인하세요.')
            return
        finally:
            try: os.unlink(tmp_in.name)
            except Exception: pass
            try: self._canvas.refresh_page()
            except Exception: pass

        self._status_lbl.setText(f'디지털 서명 완료: {out}')
        if QMessageBox.question(
                self, '완료',
                f'표준 디지털 서명을 완료했습니다.\n{out}\n\n새 탭에서 열어볼까요?') \
                == QMessageBox.StandardButton.Yes:
            try:
                self._new_tab(out)
            except Exception:
                swallowed()

    # ── 5) 서명 확인 ────────────────────────────────────────────────
    def _auto_verify_signatures_on_open(self):
        """서명이 든 문서를 열면 검증 결과를 자동으로 띄운다.

        서명 도장(그림)이 없어도 서명 여부와 위·변조 여부를 바로 알 수 있게
        하는 것이 목적이다. 서명이 없는 문서에서는 아무것도 하지 않는다.
        """
        try:
            if not self._doc.is_open or not self._doc.has_signatures():
                return
        except Exception:
            return
        path = self._doc.path or ''
        if not path or not os.path.exists(path):
            return
        # 창이 뜨는 것을 막지 않도록 이벤트 루프가 한 바퀴 돈 뒤에 검사한다.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._verify_signatures(auto=True))

    def _verify_signatures(self, auto: bool = False):
        """현재 문서의 디지털 서명을 검사해 결과를 보여 준다.

        auto=True 는 문서를 연 직후의 자동 알림 — 서명이 없거나 확인에
        실패하면 조용히 넘어간다(메뉴로 부른 경우에는 이유를 알려 준다).
        """
        if not self._doc.is_open:
            if not auto:
                QMessageBox.information(self, '보안', '문서를 먼저 여세요.')
            return

        # 저장되지 않은 편집이 있으면 디스크의 파일과 다르므로 알려 준다.
        dirty = bool(getattr(self._doc, 'dirty', False))
        path = self._doc.path or ''
        if not path or not os.path.exists(path):
            if not auto:
                QMessageBox.information(
                    self, '서명 확인',
                    '이 문서는 아직 파일로 저장되지 않아 서명을 확인할 수 없습니다.')
            return

        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt as _Qt
        QApplication.setOverrideCursor(_Qt.CursorShape.WaitCursor)
        try:
            from utils.pdf_sign import verify_pdf_signatures
            sigs = verify_pdf_signatures(path)
        except Exception as exc:
            logger.exception('[Security] 서명 확인 실패')
            if not auto:
                QMessageBox.warning(self, '서명 확인',
                                    f'서명을 확인하지 못했습니다.\n{exc}')
            return
        finally:
            QApplication.restoreOverrideCursor()

        if auto and not sigs:
            return   # 자동 알림은 서명이 있을 때만 뜬다

        if not sigs:
            # 서명 데이터는 없는데 서명란(도장)만 남은 경우가 있다 — 서명 후
            # 편집·저장하면 봉인은 사라지고 도장 그림만 남기 때문. 그대로
            # "서명 없음"이라고만 하면 도장을 본 사용자가 혼란스럽다.
            if self._has_signature_widget():
                QMessageBox.warning(
                    self, '서명 확인',
                    '서명란(도장)은 남아 있지만 서명 데이터가 없습니다.\n\n'
                    '서명한 뒤 문서를 편집·저장하면 서명이 제거됩니다\n'
                    '(PDF 표준 동작 — 봉인은 서명 당시의 내용만 보증합니다).\n\n'
                    '이 도장은 그림일 뿐 아무것도 보증하지 않습니다.\n'
                    '편집을 모두 마친 뒤 다시 서명하세요.')
            else:
                QMessageBox.information(
                    self, '서명 확인',
                    '이 문서에는 디지털 서명이 없습니다.\n\n'
                    '보안 메뉴의 "디지털 서명"으로 서명을 넣을 수 있습니다.')
            return

        lines = []
        all_ok = True
        for i, s in enumerate(sigs, 1):
            ok = s['intact'] and s['covers_all'] and not s['modified'] and not s['error']
            all_ok = all_ok and ok
            head = '✅ 유효' if ok else '⚠ 주의'
            lines.append(f'<b>{head} — 서명 {i}</b>')
            lines.append(f"&nbsp;&nbsp;서명자: <b>{s['signer'] or '(이름 없음)'}</b>")
            if s.get('organization'):
                lines.append(f"&nbsp;&nbsp;소속: {s['organization']}")
            if s['when']:
                lines.append(f"&nbsp;&nbsp;서명 날짜·시간: {s['when']}")
            if s['reason']:
                lines.append(f"&nbsp;&nbsp;사유: {s['reason']}")
            if s['location']:
                lines.append(f"&nbsp;&nbsp;위치: {s['location']}")
            if ok:
                lines.append('&nbsp;&nbsp;내용: 서명 이후 <b>변경되지 않았습니다</b>.')
            elif s['error']:
                lines.append('&nbsp;&nbsp;내용: 검증을 완료하지 못해 변경 여부를 판단할 수 없습니다.')
            elif not s['intact']:
                lines.append('&nbsp;&nbsp;<span style="color:#c00">'
                             '서명 당시 내용이 위·변조되었습니다.</span>')
            else:
                # 서명 자체는 유효하고, 그 뒤에 내용이 덧붙여진 상태
                # (Adobe 등 표준 뷰어도 이렇게 구분해 표시한다)
                lines.append('&nbsp;&nbsp;<span style="color:#a60">'
                             '서명 당시 내용은 <b>무결</b>하지만, '
                             '그 뒤에 문서가 변경되었습니다.</span>')
            if s['self_signed']:
                lines.append('&nbsp;&nbsp;인증서: 자체 서명 — '
                             '<i>내용 보호는 되지만 서명자 신원은 보증되지 않습니다.</i>')
            elif s['trusted']:
                lines.append('&nbsp;&nbsp;인증서: 신뢰할 수 있는 기관에서 발급.')
            else:
                lines.append('&nbsp;&nbsp;인증서: 신뢰 여부를 확인하지 못했습니다.')
            if s['error']:
                lines.append(f"&nbsp;&nbsp;<small>({s['error']})</small>")
            if s.get('trust_warning'):
                lines.append(f"&nbsp;&nbsp;<small>{s['trust_warning']}</small>")
            lines.append('')

        if dirty:
            lines.append('<span style="color:#a60">※ 저장하지 않은 편집이 있습니다. '
                         '위 결과는 <b>디스크에 저장된 파일</b> 기준입니다.</span>')
            lines.append('')

        # 맨 마지막 한 줄로 결론 — 변조는 붉게, 원본은 푸르게.
        if all_ok:
            lines.append('<div style="font-size:15px; color:#0b57d0;"><b>'
                         '✔ 서명 후 문서가 변경되지 않았습니다 — 원본입니다.'
                         '</b></div>')
        elif any(s['error'] for s in sigs):
            lines.append('<div style="font-size:15px; color:#a60;"><b>'
                         '⚠ 검증을 완료하지 못한 서명이 있습니다. 오류 내용을 확인하세요.'
                         '</b></div>')
        else:
            lines.append('<div style="font-size:15px; color:#c00000;"><b>'
                         '⚠ 서명 후 문서가 변경되었습니다 — 변조됨.'
                         '</b></div>')

        box = QMessageBox(self)
        box.setWindowTitle('서명 확인')
        box.setIcon(QMessageBox.Icon.Information if all_ok
                    else QMessageBox.Icon.Warning)
        box.setTextFormat(_Qt.TextFormat.RichText)
        title = f'서명 {len(sigs)}개를 찾았습니다.'
        if auto:
            title = f'이 문서에는 디지털 서명이 {len(sigs)}개 있습니다.'
        box.setText(title)
        box.setInformativeText('<br>'.join(lines))
        box.exec()

    def _has_signature_widget(self) -> bool:
        """문서에 서명란(도장) 흔적이 남아 있는가 — 서명 데이터와는 별개."""
        try:
            doc = self._doc.fitz_doc()
            for page in doc:
                widgets = page.widgets()
                if widgets is None:
                    continue
                for w in widgets:
                    if getattr(w, 'field_type', None) == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                        return True
        except Exception:
            swallowed()
        return False
