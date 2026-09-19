# core/renderer.py — PageRenderer: fitz → QImage, LRU 캐시
from __future__ import annotations
from collections import OrderedDict
import os
import logging
import fitz
from PySide6.QtGui import QImage
from utils.fitz_qt_bridge import render_page
from utils.errlog import swallowed

logger = logging.getLogger('pdf_editor')


class PageRenderer:
    """
    fitz 페이지를 QImage로 렌더링하고 LRU 캐시로 관리.
    캐시 키: (page_index, zoom_100)  → zoom을 정수 %로 정규화

    ── CID 폰트 깨짐 방지 ──
    get_text() 호출은 MuPDF 내부 CID 폰트 상태를 문서 레벨에서 오염시킨다.
    오염된 Document로 get_pixmap()을 호출하면 한글 등이 □로 렌더링된다.

    해결: 렌더링 전용 분리 Document(_render_doc)를 유지한다.
      - _render_doc 에는 절대 get_text()를 호출하지 않는다.
      - 어노테이션 반영 후 invalidate() 시 메인 doc을 tobytes()로 직렬화해
        _render_doc을 새로 연다 → 오염 전 깨끗한 상태로 렌더링 가능.
    """

    # 캐시 메모리 예산 — 대형 페이지 × 고배율에서 QImage 캐시가
    # 수백 MB로 커지는 것을 방지 (항목 수 제한과 함께 적용)
    CACHE_BYTE_BUDGET = 256 * 1024 * 1024

    # 더티 문서용 페이지 스냅샷 캐시 상한 (스냅샷 = 단일 페이지 문서)
    SNAP_CAP = 12

    def __init__(self, doc, cache_size: int = 12):
        self._doc        = doc        # PdfDocument
        self._cache_size = cache_size
        self._cache: OrderedDict[tuple, QImage] = OrderedDict()
        self._cache_bytes = 0
        self._render_doc: fitz.Document | None = None   # 렌더링 전용 (clean 파일)
        self._render_doc_stale = False   # invalidate 후 지연 동기화 플래그
        # 더티 문서용: 페이지별 단일 페이지 스냅샷 문서 (LRU)
        self._page_snaps: OrderedDict[int, fitz.Document] = OrderedDict()

    # ── 렌더링 전용 문서 관리 ────────────────────────────────────────
    #
    # clean 파일: 원본 경로에서 lazy 로딩 (전체 메모리 적재 없음).
    # dirty/무경로 문서: 필요한 페이지만 insert_pdf 로 떼어낸 단일 페이지
    #   스냅샷을 렌더링 — 예전처럼 문서 전체를 tobytes() 하면 1000페이지급
    #   문서에서 편집 후 페이지를 넘길 때마다 GUI 가 멈춘다.
    # 두 경로 모두 스냅샷/파일을 새로 열므로 get_text() CID 오염과 무관.

    def _sync_render_doc(self):
        """clean 파일용 렌더링 문서를 원본 경로에서 다시 연다."""
        try:
            if self._render_doc is not None:
                try:
                    self._render_doc.close()
                except Exception:
                    swallowed()
                self._render_doc = None

            path = getattr(self._doc, 'path', '')
            is_clean_file = (
                path
                and os.path.exists(path)
                and not getattr(self._doc, 'dirty', False)
                and not getattr(self._doc, 'is_image_doc', False)
            )
            if is_clean_file:
                try:
                    # 파일에서 lazy 로딩 — 대용량 PDF도 전체를 메모리에
                    # 올리지 않는다. 이 핸들은 같은 경로 저장(os.replace)을
                    # 막으므로 저장 직전에 canvas.release_file_handles()가
                    # close()를 호출해 해제한다.
                    rd = fitz.open(path)
                    if rd.needs_pass:   # 암호화 문서면 같은 암호로 인증
                        pw = getattr(self._doc, 'password', '') or ''
                        if pw:
                            rd.authenticate(pw)
                    self._render_doc = rd
                except Exception as e:
                    logger.warning('[Renderer] 원본 파일 렌더링 문서 열기 실패: %s', e)
        except Exception as e:
            logger.warning('[Renderer] render_doc 동기화 실패: %s', e)
            self._render_doc = None
        finally:
            self._render_doc_stale = False

    def _page_snapshot(self, index: int) -> 'fitz.Page | None':
        """더티 문서의 페이지 하나를 스냅샷 문서로 떼어내 반환 (LRU 캐시)."""
        snap = self._page_snaps.get(index)
        if snap is not None and not snap.is_closed:
            self._page_snaps.move_to_end(index)
            return snap[0]
        main = self._doc.fitz_doc()
        if main is None:
            return None
        try:
            s = fitz.open()
            s.insert_pdf(main, from_page=index, to_page=index)
            data = s.tobytes(garbage=0, deflate=False)
            s.close()
            snap = fitz.open('pdf', data)
        except Exception as e:
            logger.warning('[Renderer] 페이지 %d 스냅샷 실패: %s', index, e)
            return None
        self._page_snaps[index] = snap
        while len(self._page_snaps) > self.SNAP_CAP:
            _, old = self._page_snaps.popitem(last=False)
            try:
                old.close()
            except Exception:
                swallowed()
        return snap[0]

    def _drop_snaps(self, index: int | None = None):
        """페이지 스냅샷 제거 (index=None 이면 전체)."""
        if index is None:
            for s in self._page_snaps.values():
                try:
                    s.close()
                except Exception:
                    swallowed()
            self._page_snaps.clear()
        else:
            s = self._page_snaps.pop(index, None)
            if s is not None:
                try:
                    s.close()
                except Exception:
                    swallowed()

    def _render_page_obj(self, index: int) -> fitz.Page:
        """렌더링용 페이지 객체를 반환한다 (clean=파일, dirty=페이지 스냅샷)."""
        main = self._doc.fitz_doc()
        path = getattr(self._doc, 'path', '')
        is_clean_file = (
            path
            and os.path.exists(path)
            and not getattr(self._doc, 'dirty', False)
            and not getattr(self._doc, 'is_image_doc', False)
        )

        if is_clean_file:
            need_sync = (
                self._render_doc_stale
                or self._render_doc is None
                or self._render_doc.is_closed
                or self._render_doc.page_count != main.page_count
            )
            if need_sync:
                self._sync_render_doc()
            if self._render_doc is not None:
                return self._render_doc[index]

        page = self._page_snapshot(index)
        if page is not None:
            return page
        # 스냅샷 실패 시 메인 doc 폴백 (오염 위험 있지만 최후 수단)
        return self._doc.fitz_page(index)

    def close(self):
        """렌더링 전용 문서/스냅샷을 닫는다 (앱 종료·문서 닫기·저장 직전)."""
        if self._render_doc is not None:
            try:
                self._render_doc.close()
            except Exception:
                swallowed()
            self._render_doc = None
        self._drop_snaps()

    # ── 공개 API ─────────────────────────────────────────────────────

    def _key(self, index: int, zoom: float) -> tuple:
        return (index, round(zoom * 100))

    def get(self, index: int, zoom: float = 1.0) -> QImage:
        """캐시 우선 조회 후 렌더링."""
        k = self._key(index, zoom)
        if k in self._cache:
            self._cache.move_to_end(k)
            return self._cache[k]

        try:
            img = self._render(index, zoom)
        except MemoryError:
            logger.error('[Renderer] 페이지 %d 렌더 메모리 부족', index)
            img = self._blank_image(index, zoom)
        except Exception as e:
            logger.error('[Renderer] 페이지 %d 렌더 실패: %s', index, e)
            img = self._blank_image(index, zoom)
        self._cache[k] = img
        self._cache_bytes += img.sizeInBytes()
        # 항목 수와 메모리 예산 동시 적용 (마지막 1개는 항상 유지)
        while len(self._cache) > 1 and (
                len(self._cache) > self._cache_size
                or self._cache_bytes > self.CACHE_BYTE_BUDGET):
            _, old = self._cache.popitem(last=False)
            self._cache_bytes -= old.sizeInBytes()
        return img

    def _render(self, index: int, zoom: float) -> QImage:
        page = self._render_page_obj(index)
        return render_page(page, zoom=zoom)

    def _blank_image(self, index: int, zoom: float) -> QImage:
        """렌더 실패 시 반환할 빈(연회색) 이미지."""
        try:
            page = self._render_page_obj(index)
            w = max(100, int(page.rect.width  * zoom))
            h = max(100, int(page.rect.height * zoom))
        except Exception:
            w, h = 595, 842
        img = QImage(w, h, QImage.Format.Format_RGB888)
        img.fill(0xEEEEEE)
        return img

    def invalidate(self, index: int):
        """특정 페이지 캐시 무효화 + 렌더링 문서 stale 표시.

        어노테이션 변경 후 반드시 호출해야 한다.
        get_text() 오염을 차단하기 위해 render_doc을 새로 열어야 하는데,
        즉시 재직렬화하지 않고 다음 렌더링 시점까지 지연시킨다 —
        여러 페이지를 연속 invalidate 해도 동기화(tobytes)는 1회만 수행.
        """
        to_del = [k for k in self._cache if k[0] == index]
        for k in to_del:
            self._cache_bytes -= self._cache[k].sizeInBytes()
            del self._cache[k]
        self._render_doc_stale = True
        self._drop_snaps(index)

    def invalidate_all(self):
        """전체 캐시 무효화 + 렌더링 문서 stale 표시 (지연 동기화)."""
        self._cache.clear()
        self._cache_bytes = 0
        self._render_doc_stale = True
        self._drop_snaps()

    def thumb(self, index: int, width: int = 120) -> QImage:
        """썸네일용 소형 렌더링."""
        page = self._render_page_obj(index)
        pw   = page.rect.width
        zoom = width / pw if pw > 0 else 1.0
        return self.get(index, zoom)
