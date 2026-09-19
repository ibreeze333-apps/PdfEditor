# core/document.py — PdfDocument: fitz.Document 래퍼
from __future__ import annotations
import logging
import os
from pathlib import Path
import fitz
from PySide6.QtCore import QObject, Signal
from utils.errlog import swallowed

logger = logging.getLogger('pdf_editor')


def _subset_fonts(doc: fitz.Document, enabled: bool = True) -> None:
    """문서에 박힌 글꼴에서 실제로 쓰인 글자만 남긴다.

    본문 편집·텍스트 삽입에 시스템 글꼴(맑은 고딕 등)을 쓰면 PyMuPDF 가
    글꼴 파일을 통째로 끼워 넣는다. 한글 글꼴은 7MB 가 넘어서 몇 줄만
    고쳐도 1MB 문서가 8MB 가 됐다. 서브셋하면 원본 크기로 돌아온다.
    (페이지 수와 무관하게 ~25ms — 크기와 상관없이 항상 걸 만하다.)

    저장용 사본에만 적용한다 — 열려 있는 문서의 xref 를 건드리면 undo
    스택에 기록해 둔 xref 가 어긋난다.

    enabled=False 면 글꼴을 통째로 남긴다 — 글꼴이 깔려 있지 않은 컴퓨터의
    다른 프로그램에서 그 글꼴로 새 글자를 타이핑해야 할 때만 쓴다
    (환경설정 → 저장 옵션).
    """
    if not enabled:
        return
    try:
        doc.subset_fonts()
    except Exception:
        # 서브셋에 실패해도 저장 자체는 계속돼야 한다 (파일이 커질 뿐)
        logger.warning('[PdfDocument] 글꼴 서브셋 실패 — 원본 글꼴 유지', exc_info=True)


class PdfDocument(QObject):
    # ── 시그널 ──────────────────────────────────────────────────────
    opened          = Signal(str)       # 파일 경로
    closed          = Signal()
    page_modified   = Signal(int)       # 변경된 페이지 인덱스
    structure_changed = Signal()        # 페이지 수/순서 변경
    saved           = Signal(str)       # 저장 경로
    index_tabs_changed = Signal()       # 인덱스 포스트잇(책갈피) 목록 변경

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc:  fitz.Document | None = None
        self._path: str = ''
        self._dirty: bool = False
        self._is_image: bool = False   # open_image()로 열린 경우 True
        self._password: str = ''       # 암호화 PDF 인증에 쓴 암호 (렌더러 공유용)
        self._needs_password: bool = False   # 마지막 open 이 암호를 요구했는가
        self._was_encrypted: bool = False    # 연 파일이 암호로 보호돼 있었는가
        self._auth_level: int = 1            # 0 실패 / 1 불필요 / 2 열람 / 4 권한
        # 저장 시 글꼴 서브셋 여부 — MainWindow 가 설정값으로 갱신한다
        self.subset_fonts_enabled: bool = True
        # undo 스택 — 시간순 작업 기록 (최대 50개). 항목 형식:
        #   ('annots',      page_idx, [xref, ...])   커밋된 어노테이션 배치
        #   ('rotate',      page_idx, degrees)       페이지 회전
        #   ('rotate_many', [page_idx, ...], degrees) 여러 페이지 회전(한 번에 되돌림)
        #   ('crop',        page_idx, old_cropbox)   페이지 자르기
        #   ('page_content',page_idx, pdf_bytes)     본문 글자 편집 전 페이지
        #   ('delete_page', page_idx, pdf_bytes)     페이지 삭제 (단일 페이지 스냅샷)
        #   ('insert_page', page_idx)                페이지 삽입 (빈/이미지/PDF)
        #   ('move_page',   from_idx, to_idx)        페이지 이동
        self._undo_stack: list[tuple] = []

    def push_undo(self, page_idx: int, xrefs: list[int]):
        """커밋된 어노테이션 배치를 undo 스택에 등록."""
        self._push_op(('annots', page_idx, list(xrefs)))

    def push_page_snapshot(self, page_idx: int) -> bool:
        """페이지를 통째로 스냅샷해 undo 스택에 등록한다.

        본문 글자 편집은 페이지 콘텐츠 스트림을 직접 고치기 때문에 어노테이션
        처럼 xref 하나를 지워서 되돌릴 수가 없다. 고치기 '전'의 페이지를
        통째로 떠 두었다가 되돌릴 때 그 페이지로 교체한다
        (페이지 삭제 undo 와 같은 방식).
        편집을 시작하기 직전에 부를 것.
        """
        if not self._doc or not (0 <= page_idx < self._doc.page_count):
            return False
        try:
            snap = fitz.open()
            snap.insert_pdf(self._doc, from_page=page_idx, to_page=page_idx,
                            annots=True)
            data = snap.tobytes(garbage=0, deflate=True)
            snap.close()
        except Exception:
            logger.exception('[Document] 페이지 스냅샷 실패: %d', page_idx)
            return False
        self._push_op(('page_content', page_idx, data))
        return True

    def _push_op(self, op: tuple):
        self._undo_stack.append(op)
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)

    def pop_undo(self) -> tuple | None:
        """undo 스택에서 꺼냄. 없으면 None."""
        return self._undo_stack.pop() if self._undo_stack else None

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def clear_undo(self):
        self._undo_stack.clear()

    def undo_last(self) -> bool:
        """undo 스택 최상단 작업을 되돌린다. 되돌렸으면 True.

        LIFO 순서로만 호출되므로 각 항목의 페이지 인덱스는
        해당 작업 직전 상태 기준으로 유효하다.
        """
        if not self._doc or not self._undo_stack:
            return False
        op = self._undo_stack.pop()
        try:
            kind = op[0]
            if kind == 'annots':
                _, idx, xrefs = op
                page = self._doc[idx]
                for annot in list(page.annots() or []):
                    if annot.xref in xrefs:
                        page.delete_annot(annot)
                self._dirty = True
                self.page_modified.emit(idx)
            elif kind == 'rotate_many':
                _, idxs, degrees = op
                for i in idxs:
                    if 0 <= i < self._doc.page_count:
                        page = self._doc[i]
                        page.set_rotation((page.rotation - degrees) % 360)
                self._dirty = True
                for i in idxs:
                    self.page_modified.emit(i)
            elif kind == 'rotate':
                _, idx, degrees = op
                page = self._doc[idx]
                page.set_rotation((page.rotation - degrees) % 360)
                self._dirty = True
                self.page_modified.emit(idx)
            elif kind == 'crop':
                _, idx, old_box = op
                self._doc[idx].set_cropbox(old_box)
                self._dirty = True
                self.page_modified.emit(idx)
            elif kind == 'page_content':
                # 편집 전 페이지로 교체 — 원래 자리에 끼운 뒤 고친 쪽을 뺀다
                _, idx, data = op
                src = fitz.open('pdf', data)
                try:
                    self._doc.insert_pdf(src, start_at=idx)
                finally:
                    src.close()
                self._doc.delete_page(idx + 1)
                self._dirty = True
                self.page_modified.emit(idx)
                self.structure_changed.emit()
            elif kind == 'delete_page':
                _, idx, data = op
                src = fitz.open('pdf', data)
                try:
                    self._doc.insert_pdf(src, start_at=idx)
                finally:
                    src.close()
                self._dirty = True
                self.structure_changed.emit()
            elif kind == 'insert_page':
                _, idx = op
                self._doc.delete_page(idx)
                self._dirty = True
                self.structure_changed.emit()
            elif kind == 'move_page':
                _, f_idx, t_idx = op
                # move_page(f, t)는 "원래 t 위치 앞에 삽입"이므로 역연산은
                # f < t → move(t-1, f), f > t → move(t, f+1)
                # (f+1이 문서 끝이면 PyMuPDF는 -1(맨 뒤)만 허용)
                if f_idx < t_idx:
                    self._doc.move_page(t_idx - 1, f_idx)
                else:
                    dest = f_idx + 1
                    if dest >= self._doc.page_count:
                        dest = -1
                    self._doc.move_page(t_idx, dest)
                self._dirty = True
                self.structure_changed.emit()
            else:
                logger.warning('[Document] 알 수 없는 undo 항목: %r', kind)
                return False
            return True
        except Exception:
            logger.exception('[Document] undo 실패: %r', op[0])
            return False

    # ── 기본 프로퍼티 ────────────────────────────────────────────────
    @property
    def is_open(self) -> bool:
        return self._doc is not None

    @property
    def is_image_doc(self) -> bool:
        """open_image()로 열린 이미지→PDF 문서 여부."""
        return self._is_image

    @property
    def path(self) -> str:
        return self._path

    @property
    def dirty(self) -> bool:
        return self._dirty

    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    def fitz_doc(self) -> fitz.Document:
        return self._doc

    def fitz_page(self, index: int) -> fitz.Page:
        return self._doc[index]

    # ── 열기 / 닫기 ──────────────────────────────────────────────────
    def open(self, path: str, password: str = '') -> bool:
        self._needs_password = False
        doc = None
        try:
            doc = fitz.open(path)
            # 암호화 문서: 인증 필요
            was_encrypted = bool(doc.needs_pass)
            auth_level = 1
            if doc.needs_pass:
                # authenticate() 반환값이 곧 접근 수준이다.
                #   0 실패 / 1 암호 불필요 / 2 열람 암호 / 4 관리자 암호 / 6 둘 다
                code = doc.authenticate(password) if password else 0
                if not code:
                    self._needs_password = True
                    doc.close()
                    return False
                auth_level = int(code)
            # Only replace the working document after opening/authentication succeeds.
            if self._doc:
                self._doc.close()
            self._doc  = doc
            self._was_encrypted = was_encrypted
            self._auth_level = auth_level
            self._path = path
            self._password = password
            self._dirty = False
            self._is_image = False
            # 서명 문서라면 서명 필드 목록을 열자마자 기록해 둔다. 편집·저장 중
            # 이 목록이 비워지면 서명 데이터가 파일에 남아 있어도 뷰어가 서명을
            # 찾지 못하므로, 저장할 때 이 값으로 되돌린다.
            self._sig_fields_snapshot = None
            if self.has_signatures():
                axref, raw = self._acroform_fields_raw()
                if axref and raw:
                    self._sig_fields_snapshot = (axref, raw)
            self.clear_undo()
            self.opened.emit(path)
            return True
        except Exception:
            logger.exception('[Document] open error: %s', path)
            if doc is not None and doc is not self._doc and not doc.is_closed:
                doc.close()
            return False

    @property
    def opened_as_owner(self) -> bool:
        """관리자 암호(소유자)로 열었는가.

        열람 암호로 연 제한 문서를 그대로 저장하면 암호가 풀린 사본이 되어
        권한 제한을 통째로 우회할 수 있다. 저장·내보내기를 막을 판단 기준.
        암호가 걸려 있지 않은 문서는 항상 True.
        """
        if not self._was_encrypted:
            return True
        return bool(int(getattr(self, '_auth_level', 1)) & 4)

    @property
    def was_encrypted(self) -> bool:
        """연 파일이 암호로 보호돼 있었는가.

        전체 저장은 복호화된 바이트를 다시 쓰기 때문에 암호가 사라진다.
        원래 관리자 암호를 알 수 없어 되살릴 수도 없으므로, 저장 전에
        사용자에게 알리는 데 쓴다.
        """
        return self._was_encrypted

    @property
    def needs_password(self) -> bool:
        """마지막 open() 이 암호를 요구했는지 (인증 실패/미입력)."""
        return self._needs_password

    @property
    def password(self) -> str:
        return self._password

    @property
    def permissions(self) -> int:
        """현재 인증 상태의 유효 권한 비트. 암호화가 아니거나 관리자 암호로
        열면 전체 허용. 열람 암호로 연 제한 문서는 제한된 비트만 반환."""
        try:
            return int(self._doc.permissions) if self._doc else -1
        except Exception:
            return -1

    def can(self, perm_bit: int) -> bool:
        """해당 작업(인쇄/복사/편집/주석 등)이 허용되는지."""
        return bool(self.permissions & perm_bit)

    def open_image(self, path: str) -> bool:
        """이미지 파일(PNG/JPG 등)을 단일 페이지 PDF로 변환하여 로드.

        매우 긴 스크린샷도 페이지 크기 그대로 한 장으로 처리.
        저장 시 '다른 이름으로 저장'을 통해 PDF로 내보낼 수 있음.
        """
        try:
            # fitz로 이미지를 열면 래스터 이미지 Document로 취급됨
            with fitz.open(path) as img_doc:
                pdf_bytes = img_doc.convert_to_pdf()   # bytes 변환
            # bytes 로 PDF 열기 (파일 없이 메모리 내 운영)
            candidate = fitz.open('pdf', pdf_bytes)
            if self._doc:
                self._doc.close()
            self._doc = candidate
            self._reset_access_state()
            # 경로를 비워 두면 저장 시 _save_as()로 분기됨
            self._path  = ''
            self._dirty = False   # 아무 편집 안 한 상태 → 닫을 때 경고 없음
            self._is_image = True
            self.clear_undo()
            # opened 시그널에는 원본 이미지 경로 전달 (제목 표시용)
            self.opened.emit(path)
            return True
        except Exception:
            logger.exception('[Document] open_image error: %s', path)
            return False

    def _reset_access_state(self):
        self._password = ''
        self._needs_password = False
        self._was_encrypted = False
        self._auth_level = 1
        self._sig_fields_snapshot = None

    def new_empty(self):
        """빈 새 문서 생성"""
        if self._doc:
            self._doc.close()
        self._doc   = fitz.open()
        self._doc.new_page()
        self._path  = ''
        self._dirty = True
        self._is_image = False
        self._reset_access_state()
        self.clear_undo()
        self.opened.emit('')

    def close(self):
        if self._doc:
            self._doc.close()
            self._doc  = None
            self._path = ''
            self._dirty = False
            self._is_image = False
            self._reset_access_state()
            self.clear_undo()
            self.closed.emit()

    # ── 저장 ─────────────────────────────────────────────────────────
    # garbage=4(스트림 중복 검사)는 페이지 수에 비례해 폭증한다 —
    # 1200페이지 문서에서 ~8초 (garbage=3은 동일한 파일 크기에 ~0.1초).
    def save(self, path: str = '', garbage: int = 4,
             deflate: bool = True):
        """가능한 한 원자적으로 저장한다.

        1) tobytes(garbage=0)로 메모리에 완전 직렬화 — 실패해도 기존 파일
           무손상. garbage 옵션은 열린 문서의 xref를 메모리에서도
           재번호화해 undo 스택의 xref 기록을 무효화하므로 원본 문서에는
           적용하지 않는다. (같은 경로 doc.save()의 "can't save to input
           file" 제약 우회도 겸한다.)
        2) 직렬화 사본을 별도 문서로 열어 같은 디렉터리의 임시 파일에
           압축(garbage/deflate) 저장 + fsync — 디스크 공간 검증.
        3) os.replace()로 원자적 교체. 자기 자신이 원본 파일 핸들을 잡고
           있어 교체가 거부되면(Windows), 문서를 메모리 사본으로 재오픈해
           핸들을 놓은 뒤 다시 교체한다 — 열린 문서의 원본 파일을 in-place로
           덮어쓰면 lazy-loading 중인 메모리 문서가 오염되기 때문에
           덮어쓰기 폴백은 쓰지 않는다.
        """
        if not self._doc:
            return
        out = path or self._path
        if not out:
            raise ValueError('저장 경로를 지정하세요.')
        # 서명된 문서를 같은 파일에 저장할 때는 증분 저장을 쓴다(Adobe 방식).
        # 파일 전체를 다시 쓰면 서명이 해시한 원본 바이트가 사라져 서명이
        # 깨지지만, 뒤에 변경분만 덧붙이면 서명은 유효한 채로 '서명 이후
        # 변경됨'으로 정확히 표시된다.
        if out == self._path and self.has_signatures():
            if self._save_incremental(out):
                return
            logger.warning('[PdfDocument] 증분 저장 실패 — 전체 저장으로 대체'
                           ' (서명이 무효가 될 수 있음)')
        out_p = Path(out)
        expected_pages = self._doc.page_count
        raw = self._doc.tobytes(garbage=0, deflate=False)
        tmp = out_p.with_name(out_p.name + '.saving.tmp')
        copy_doc = fitz.open('pdf', raw)
        try:
            _subset_fonts(copy_doc, self.subset_fonts_enabled)
            copy_doc.save(str(tmp), garbage=garbage, deflate=deflate,
                          deflate_images=deflate, deflate_fonts=deflate)
        finally:
            copy_doc.close()
        with open(tmp, 'rb+') as f:
            os.fsync(f.fileno())
        # 임시본이 온전한지 확인한 뒤에만 원본을 갈아치운다. 검증에 걸리면
        # 예외를 내고 원본은 손대지 않는다 — 내용이 빈 파일로 덮여
        # 저장되던 사고를 막는다.
        try:
            self._verify_saved_file(tmp, expected_pages)
        except BaseException:
            logger.exception('[PdfDocument] 저장본 검증 실패 — 원본 유지: %s', out_p)
            try:
                os.remove(tmp)      # 망가진 임시본은 남길 가치가 없다
            except OSError:
                swallowed()
            raise
        try:
            # 자기 자신이 원본 파일을 lazy 로딩 중이면, 교체 후 그 문서로
            # 읽는 내용은 신뢰할 수 없다. 같은 경로 저장은 교체 전에 미리
            # 메모리 사본으로 갈아탄다 (raw 는 garbage=0 직렬화라 xref
            # 번호가 보존돼 undo 스택이 그대로 유효하다).
            if out_p == Path(self._path or ''):
                self._rebind_to_memory(raw)
            try:
                os.replace(tmp, out_p)
            except PermissionError:
                # 아직 핸들이 남아 있으면(다른 경로 저장 등) 한 번 더 정리 후 재시도
                self._rebind_to_memory(raw)
                os.replace(tmp, out_p)
        except BaseException:
            logger.error('저장 실패 — 완전한 임시본이 남아 있습니다: %s', tmp)
            raise
        self._path  = out
        self._dirty = False
        self.saved.emit(out)

    @staticmethod
    def _verify_saved_file(tmp: Path, expected_pages: int):
        """방금 쓴 임시본을 열어 페이지가 온전히 들어 있는지 확인한다."""
        size = 0
        try:
            size = os.path.getsize(tmp)
        except OSError:
            swallowed()
        if size <= 0:
            raise IOError(f'저장본이 비어 있습니다 (0바이트): {tmp}')
        check = None
        try:
            check = fitz.open(str(tmp))
            got = check.page_count
            if got != expected_pages:
                raise IOError(
                    f'저장본의 페이지 수가 다릅니다 (원본 {expected_pages}쪽 → '
                    f'저장본 {got}쪽). 원본을 덮어쓰지 않았습니다.')
            # 첫·마지막 페이지를 실제로 읽어 본다 (구조만 멀쩡한 경우 걸러냄)
            for idx in {0, max(0, got - 1)}:
                check.load_page(idx).get_text('text')
        except IOError:
            raise
        except Exception as exc:
            raise IOError(f'저장본을 다시 열지 못했습니다: {exc}') from exc
        finally:
            if check is not None:
                try:
                    check.close()
                except Exception:
                    swallowed()

    def detach_from_file(self) -> bool:
        """열려 있는 문서를 메모리 사본으로 옮겨 원본 파일 핸들을 놓는다.

        원본 경로를 덮어써야 하는 작업(암호화 사본을 같은 이름으로 저장 등)
        직전에 부른다. 실패해도 문서는 그대로 쓸 수 있다.
        """
        if not self._doc:
            return False
        try:
            raw = self._doc.tobytes(garbage=0, deflate=False)
        except Exception:
            logger.exception('[PdfDocument] detach 직렬화 실패')
            return False
        self._rebind_to_memory(raw)
        return True

    def _rebind_to_memory(self, raw: bytes):
        """열려 있는 문서를 메모리 사본으로 갈아타 파일 핸들을 놓는다."""
        if self._doc is None:
            return
        try:
            reopened = fitz.open('pdf', raw)
        except Exception:
            logger.exception('[PdfDocument] 메모리 사본 재오픈 실패')
            return
        old_doc, self._doc = self._doc, reopened
        try:
            old_doc.close()
        except Exception:
            swallowed()

    def has_signatures(self) -> bool:
        """문서에 디지털 서명이 들어 있는가 (빠른 판정)."""
        if not self._doc:
            return False
        try:
            return int(self._doc.get_sigflags()) > 0
        except Exception:
            return False

    def _acroform_fields_raw(self):
        """(AcroForm xref, '/Fields [...]' 원문) — 서명 필드 보존 검사용."""
        try:
            root = self._doc.pdf_catalog()
            kind, val = self._doc.xref_get_key(root, 'AcroForm')
            if kind != 'xref':
                return None, ''
            axref = int(str(val).split()[0])
            obj = self._doc.xref_object(axref)
            import re
            m = re.search(r'/Fields\s*\[([^\]]*)\]', obj or '')
            return axref, (m.group(1).strip() if m else '')
        except Exception:
            return None, ''

    def _restore_acroform_fields(self, axref: int, fields_raw: str) -> bool:
        """저장 과정에서 비워진 서명 필드 목록을 원래대로 되돌린다."""
        if not axref or not fields_raw:
            return False
        try:
            self._doc.xref_set_key(axref, 'Fields', f'[{fields_raw}]')
            return True
        except Exception:
            logger.exception('[PdfDocument] AcroForm Fields 복원 실패')
            return False

    def _save_incremental(self, out: str) -> bool:
        """변경분만 파일 끝에 덧붙여 저장한다(서명 보존). 성공하면 True.

        원본 바이트를 건드리지 않으므로 기존 서명이 유효한 상태로 남고, 뷰어는
        '서명 이후 변경됨'으로 표시한다. 페이지 구조가 바뀐 경우 등 증분 저장이
        불가능하면 False 를 돌려주어 호출부가 일반 저장으로 넘어가게 한다.
        """
        import shutil
        bak = out + '.sigbak.tmp'
        try:
            shutil.copy2(out, bak)
        except Exception:
            return False
        # 편집 중 또는 저장 과정에서 AcroForm 의 서명 필드 목록이 비워지는
        # 경우가 있다. 그러면 서명 데이터가 파일에 남아도 뷰어가 서명을 찾지
        # 못한다. 문서를 열 때 기록해 둔 값으로 되돌린다.
        snap = getattr(self, '_sig_fields_snapshot', None)
        axref, fields_raw = self._acroform_fields_raw()
        if snap and not fields_raw:
            logger.warning('[PdfDocument] 서명 필드 목록이 비워짐 — 저장 전 복원')
            self._restore_acroform_fields(axref or snap[0], snap[1])
        try:
            self._doc.saveIncr()
            # 저장 과정에서 다시 비워졌으면 되돌리고 한 번 더 덧붙인다.
            _ax, _now = self._acroform_fields_raw()
            if snap and not _now:
                logger.warning('[PdfDocument] 저장 후에도 비워짐 — 재복원')
                if self._restore_acroform_fields(_ax or snap[0], snap[1]):
                    self._doc.saveIncr()
        except Exception:
            logger.exception('[PdfDocument] 증분 저장 실패 — 원본 복구')
            try:
                shutil.copy2(bak, out)      # 덧붙이다 만 파일을 되돌린다
            except Exception:
                logger.error('[PdfDocument] 원본 복구 실패 — 백업: %s', bak)
                return False
            finally:
                try:
                    os.remove(bak)
                except OSError:
                    swallowed()
            return False
        try:
            os.remove(bak)
        except OSError:
            swallowed()
        self._path = out
        self._dirty = False
        self.saved.emit(out)
        return True

    def save_copy(self, path: str, garbage: int = 4, deflate: bool = True):
        """현재 경로 변경 없이 사본 저장 (임시 파일 경유로 원자적).

        자동저장처럼 속도가 중요한 곳은 garbage=0, deflate=False 로 호출.
        """
        if not self._doc:
            return
        out_p = Path(path)
        tmp = out_p.with_name(out_p.name + '.saving.tmp')
        try:
            if garbage > 0:
                # 사본을 떠서 글꼴 서브셋 후 저장 — 열려 있는 문서의 xref 를
                # 건드리지 않아야 undo 스택이 유효하다. (자동저장은 garbage=0
                # 으로 불러 이 경로를 타지 않는다 — 속도가 우선)
                copy_doc = fitz.open('pdf', self._doc.tobytes(garbage=0, deflate=False))
                try:
                    _subset_fonts(copy_doc, self.subset_fonts_enabled)
                    copy_doc.save(str(tmp), garbage=garbage, deflate=deflate,
                                  deflate_images=deflate, deflate_fonts=deflate)
                finally:
                    copy_doc.close()
            else:
                self._doc.save(str(tmp), garbage=garbage, deflate=deflate)
            os.replace(tmp, out_p)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                swallowed()
            raise

    # ── 페이지 관리 ──────────────────────────────────────────────────
    def insert_blank_page(self, at: int,
                          width: float = 595, height: float = 842):
        self._doc.new_page(pno=at, width=width, height=height)
        self._push_op(('insert_page', at))
        self._dirty = True
        self.structure_changed.emit()

    def insert_page_from_pdf(self, at: int, src_path: str,
                              src_page: int = 0):
        src = fitz.open(src_path)
        self._doc.insert_pdf(src, from_page=src_page,
                              to_page=src_page, start_at=at)
        src.close()
        self._push_op(('insert_page', at))
        self._dirty = True
        self.structure_changed.emit()

    def insert_image_as_page(self, at: int, img_path: str):
        """이미지 한 장 → 새 페이지로 삽입 (긴 스크린샷 지원)"""
        img = fitz.open(img_path)
        img_rect = img[0].rect
        page = self._doc.new_page(pno=at,
                                   width=img_rect.width,
                                   height=img_rect.height)
        page.insert_image(img_rect, filename=img_path)
        img.close()
        self._push_op(('insert_page', at))
        self._dirty = True
        self.structure_changed.emit()

    def delete_page(self, index: int):
        # undo용 단일 페이지 스냅샷 (실패해도 삭제는 진행)
        try:
            snap = fitz.open()
            snap.insert_pdf(self._doc, from_page=index, to_page=index)
            data = snap.tobytes()
            snap.close()
            self._push_op(('delete_page', index, data))
        except Exception:
            logger.exception('[Document] 페이지 %d 스냅샷 실패 — undo 불가', index)
        self._doc.delete_page(index)
        self._dirty = True
        self.structure_changed.emit()

    def move_page(self, from_idx: int, to_idx: int):
        self._doc.move_page(from_idx, to_idx)
        self._push_op(('move_page', from_idx, to_idx))
        self._dirty = True
        self.structure_changed.emit()

    def rotate_page(self, index: int, degrees: int):
        page = self._doc[index]
        page.set_rotation((page.rotation + degrees) % 360)
        self._push_op(('rotate', index, degrees))
        self._dirty = True
        self.page_modified.emit(index)

    def rotate_pages(self, indices, degrees: int) -> int:
        """여러 페이지를 한꺼번에 회전하고 회전한 페이지 수를 반환.

        Ctrl+Z 한 번으로 전체가 되돌아가도록 undo 스택에는 하나로 기록한다.
        """
        if not self._doc:
            return 0
        n = self._doc.page_count
        seen, targets = set(), []
        for i in indices:
            i = int(i)
            if 0 <= i < n and i not in seen:
                seen.add(i)
                targets.append(i)
        if not targets:
            return 0
        for i in targets:
            page = self._doc[i]
            page.set_rotation((page.rotation + degrees) % 360)
        self._push_op(('rotate_many', list(targets), degrees))
        self._dirty = True
        for i in targets:
            self.page_modified.emit(i)
        return len(targets)

    def crop_page(self, index: int, rect: fitz.Rect):
        page = self._doc[index]
        old_box = fitz.Rect(page.cropbox)
        page.set_cropbox(rect)
        self._push_op(('crop', index, old_box))
        self._dirty = True
        self.page_modified.emit(index)

    def mark_dirty(self):
        """어노테이션 직접 수정 후 dirty 플래그 설정."""
        self._dirty = True

    # ── 인덱스 포스트잇 = PDF 표준 책갈피(TOC/북마크) ────────────────
    # 인덱스 탭은 색깔 있는 책갈피로 PDF TOC에 저장된다. 모든 페이지에서
    # 사이드 바에 표시되며, 클릭하면 해당 페이지로 이동한다. 표준 뷰어의
    # 북마크 패널에도 그대로 나타난다.
    def get_index_tabs(self) -> list[dict]:
        """현재 문서의 책갈피를 인덱스 탭 목록으로 반환 (TOC 원래 순서).
        각 항목: {'idx': TOC 위치, 'page': 0-based, 'label', 'color', 'level'}
        기존 계층형 목차를 파괴하지 않도록 level/순서를 그대로 보존한다."""
        if not self._doc:
            return []
        tabs = []
        try:
            for i, entry in enumerate(self._doc.get_toc(simple=False)):
                lvl, title, page = entry[0], entry[1], entry[2]
                dest = entry[3] if len(entry) > 3 else {}
                color = dest.get('color') if isinstance(dest, dict) else None
                pg0 = (page - 1) if page and page > 0 else max(0, dest.get('page', 0) if isinstance(dest, dict) else 0)
                # italic 플래그를 '왼쪽 탭' 표식으로 재활용 (TOC dest 에 보존됨)
                side = 'left' if (isinstance(dest, dict) and dest.get('italic')) else 'right'
                # 자유 수직 위치(비율 0~1)는 dest['to'].y 에 저장 (우리 탭 = color 있음)
                yv = None
                to = dest.get('to') if isinstance(dest, dict) else None
                if color and to is not None:
                    try:
                        ty = float(to.y)
                        if 0.0 < ty <= 1.0:
                            yv = ty
                    except Exception:
                        yv = None
                # 출처 구분: 사용자가 만든 인덱스 vs PDF 기본 목차.
                # 새 탭은 bold 플래그로 명시 표식, 옛 탭은 color 유무로 추정.
                is_bold = bool(dest.get('bold')) if isinstance(dest, dict) else False
                origin = 'mine' if (is_bold or color) else 'toc'
                # 기본 목차의 원래 목적지·zoom 을 보존해 두었다가 다시 쓸 때 복원
                # (인덱스 추가로 TOC 전체를 재기록해도 다른 뷰어에서 스크롤
                #  위치가 어긋나지 않게).
                dest_to = None
                if to is not None:
                    try:
                        dest_to = (float(to.x), float(to.y))
                    except Exception:
                        dest_to = None
                dest_zoom = dest.get('zoom', 0) if isinstance(dest, dict) else 0
                tabs.append({
                    'idx': i,
                    'page': max(0, pg0),
                    'label': title or '',
                    'color': tuple(color) if color else None,
                    'level': lvl,
                    'side': side,
                    'y': yv,
                    'origin': origin,
                    '_dest_to': dest_to,
                    '_dest_zoom': dest_zoom,
                })
        except Exception:
            logger.exception('[PdfDocument] get_index_tabs 실패')
        return tabs

    def _write_index_tabs(self, tabs: list[dict]):
        """탭 목록을 TOC로 기록. level/순서를 그대로 유지 (계층 보존)."""
        if not self._doc:
            return
        n = self._doc.page_count
        toc = []
        for t in tabs:
            pg0 = max(0, min(int(t['page']), n - 1))
            origin = t.get('origin', 'mine' if t.get('color') else 'toc')
            if origin == 'mine':
                # 내 인덱스: 자유 수직 위치 비율을 to.y 에 저장 (0 이면 자동 배치)
                yv = t.get('y')
                to_y = float(yv) if (yv is not None and 0.0 < yv <= 1.0) else 0.0
                dest = {'kind': fitz.LINK_GOTO, 'page': pg0,
                        'to': fitz.Point(0, to_y), 'bold': True}
            else:
                # 기본 목차: 원래 목적지·zoom 을 그대로 복원(뷰어 호환 보존)
                ot = t.get('_dest_to')
                to_pt = fitz.Point(ot[0], ot[1]) if ot else fitz.Point(0, 0)
                dest = {'kind': fitz.LINK_GOTO, 'page': pg0, 'to': to_pt}
                if t.get('_dest_zoom'):
                    dest['zoom'] = t['_dest_zoom']
            if t.get('color'):
                dest['color'] = tuple(t['color'])
            if t.get('side') == 'left':
                dest['italic'] = True   # 왼쪽 탭 표식
            toc.append([int(t.get('level', 1)), t.get('label') or f'{pg0 + 1}쪽',
                        pg0 + 1, dest])
        try:
            self._doc.set_toc(toc)
            self._dirty = True
            self.index_tabs_changed.emit()
        except Exception:
            logger.exception('[PdfDocument] set_toc 실패')

    def add_index_tab(self, page: int, label: str, color=None, side: str = 'right'):
        """새 인덱스 탭을 최상위(level 1) 책갈피로 추가. side='right'|'left'.
        같은 쪽 기존 탭 수에 따라 초기 수직 위치를 살짝 계단식으로 배치한다."""
        tabs = self.get_index_tabs()
        # 계단식 초기 위치는 '내 인덱스'끼리만 센다(기본 목차 수에 밀리지 않게).
        n_side = sum(1 for t in tabs
                     if t.get('side', 'right') == side and t.get('origin') == 'mine')
        y = min(0.90, 0.04 + 0.075 * n_side)
        tabs.append({'page': int(page), 'label': label or '', 'color': color,
                     'level': 1, 'side': side, 'y': y, 'origin': 'mine'})
        self._write_index_tabs(tabs)

    def update_index_tab(self, tab_index: int, label: str = None,
                         color=None, page: int = None, side: str = None,
                         y: float = None):
        tabs = self.get_index_tabs()
        pos = next((k for k, t in enumerate(tabs) if t['idx'] == tab_index), None)
        if pos is None:
            return
        if label is not None:
            tabs[pos]['label'] = label
        if color is not None:
            tabs[pos]['color'] = color
        if page is not None:
            tabs[pos]['page'] = int(page)
        if side is not None:
            tabs[pos]['side'] = side
        if y is not None:
            tabs[pos]['y'] = max(0.001, min(1.0, float(y)))
        self._write_index_tabs(tabs)

    def remove_index_tab(self, tab_index: int):
        tabs = self.get_index_tabs()
        tabs = [t for t in tabs if t['idx'] != tab_index]
        self._write_index_tabs(tabs)

    def set_side_bulk(self, side: str, origin: str = 'toc'):
        """특정 출처(origin)의 인덱스 탭을 한꺼번에 왼/오른쪽으로 옮긴다.
        origin='toc' 이면 문서 기본 목차 전체, 'mine' 이면 내 인덱스 전체."""
        if side not in ('left', 'right'):
            return
        tabs = self.get_index_tabs()
        changed = False
        for t in tabs:
            if t.get('origin', 'toc') == origin and t.get('side') != side:
                t['side'] = side
                changed = True
        if changed:
            self._write_index_tabs(tabs)

    def move_index_tab(self, tab_index: int, before_index):
        """탭을 목록에서 before_index 앞으로 이동 (None 이면 맨 끝).
        사용자가 드래그로 정한 상하 순서를 저장한다."""
        tabs = self.get_index_tabs()
        moving = next((t for t in tabs if t['idx'] == tab_index), None)
        if moving is None:
            return
        rest = [t for t in tabs if t['idx'] != tab_index]
        if before_index is None:
            rest.append(moving)
        else:
            pos = next((k for k, t in enumerate(rest) if t['idx'] == before_index), len(rest))
            rest.insert(pos, moving)
        self._write_index_tabs(rest)

    def delete_annotation(self, page_idx: int, annot: fitz.Annot):
        page = self._doc[page_idx]
        page.delete_annot(annot)
        self._dirty = True
        self.page_modified.emit(page_idx)
