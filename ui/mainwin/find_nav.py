# ui/mainwin/find_nav.py — MainWindow 검색(find bar)과 페이지 이동/줌 프리셋 믹스인
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
from PySide6.QtCore import QObject, Signal
import time
import fitz
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
from core.search import (
    Hit, SearchOptions, find_in_page, page_has_text, search_page_advanced,
)
from ui.find_bar import FindBar
from ui.search_panel import SCOPE_ALL, SearchPanel


class _SearchJob(QObject):
    """문서 페이지를 이벤트 루프를 막지 않게 조금씩 검색한다.

    예전에는 글자를 칠 때마다 전체 페이지를 한 번에 훑어서, 수백 쪽짜리
    문서에서는 입력할 때마다 화면이 몇 초씩 멈췄다. 한 번에 약 25 ms 만
    일하고 이벤트 루프에 양보한다. (fitz 문서 객체는 스레드에 안전하지 않아
    별도 스레드 대신 GUI 스레드에서 쪼개 돌린다.)
    """
    hits_found = Signal(int, object)   # (탭 번호, [Hit])
    progress = Signal(int, int)        # (끝낸 페이지 수, 전체 페이지 수)
    finished = Signal(bool)            # 중지됐으면 True

    _SLICE_SEC = 0.025

    def __init__(self, targets, page_fn, parent=None):
        super().__init__(parent)
        self._targets = list(targets)   # [(탭 번호, PdfDocument), ...]
        self._page_fn = page_fn         # (탭 번호, 문서, 페이지) -> [Hit]
        total = 0
        for _k, doc in self._targets:
            try:
                total += doc.page_count() if doc.is_open else 0
            except Exception:
                pass
        self._total = total
        self._done = 0
        self._ti = 0
        self._pi = 0
        self._running = False
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._running = True
        self._timer.start()

    def is_running(self) -> bool:
        return self._running

    def cancel(self):
        if self._running:
            self._running = False
            self._timer.stop()
            self.finished.emit(True)

    def _tick(self):
        deadline = time.perf_counter() + self._SLICE_SEC
        while self._running and time.perf_counter() < deadline:
            if self._ti >= len(self._targets):
                self._running = False
                self._timer.stop()
                self.progress.emit(self._done, self._total)
                self.finished.emit(False)
                return
            tab_key, doc = self._targets[self._ti]
            try:
                n = doc.page_count() if doc.is_open else 0
            except Exception:
                n = 0
            if self._pi >= n:
                self._ti += 1
                self._pi = 0
                continue
            try:
                hits = self._page_fn(tab_key, doc, self._pi)
            except Exception:
                hits = []
            self._pi += 1
            self._done += 1
            if hits:
                self.hits_found.emit(tab_key, hits)
        if self._running:
            self.progress.emit(self._done, self._total)


class FindNavMixin:
    """MainWindow 검색(find bar)과 페이지 이동/줌 프리셋."""


    # ── 찾기 ─────────────────────────────────────────────────────────
    #
    # 찾기 메뉴 → 찾기(Ctrl+F): 문서 오른쪽 위에 뜨는 찾기 막대. 입력하는 대로
    #   찾고 결과를 하나씩 넘긴다(F3 / Shift+F3).
    # 찾기 메뉴 → 고급 검색(Ctrl+Shift+F): 오른쪽 '검색' 패널. 결과를 목록으로
    #   보고 검색 방식·제외 단어·열린 모든 문서 범위를 고른다.
    # 화면 강조(_hl_*)는 둘이 함께 쓴다 — 마지막으로 이동한 쪽의 결과가 칠해진다.

    def _init_find(self):
        """찾기 막대와 검색 결과 패널을 만든다 (MainWindow.__init__ 에서 호출)."""
        self._find_bar = FindBar(self._central_stack)
        self._find_bar.top_offset = self._find_bar_top_offset
        self._find_bar.query_changed.connect(self._on_find_query_changed)
        self._find_bar.next_requested.connect(lambda: self._nav_hit(1))
        self._find_bar.prev_requested.connect(lambda: self._nav_hit(-1))
        self._find_bar.close_requested.connect(self._close_find_bar)
        self._find_bar.options_changed.connect(self._on_find_options_changed)
        self._find_bar.panel_requested.connect(self._open_search_panel)

        # 글자를 칠 때마다 바로 찾지 않고 잠깐 멈췄을 때 찾는다
        self._find_debounce = QTimer(self)
        self._find_debounce.setSingleShot(True)
        self._find_debounce.setInterval(220)
        self._find_debounce.timeout.connect(self._run_bar_search)

        self._find_job = None
        self._find_hits: list[Hit] = []
        self._find_cursor = -1
        self._find_query = ''
        self._find_doc = None

        self._hl_tab = -1
        self._hl_by_page: dict = {}
        self._hl_current = (None, None)
        self._hl_canvas = None

        self._search_panel = SearchPanel(self)
        self._search_panel.search_requested.connect(self._on_panel_search)
        self._search_panel.stop_requested.connect(self._stop_panel_search)
        self._search_panel.hit_activated.connect(self._on_panel_hit_activated)
        self._panel_job = None
        self._panel_hits: dict[int, list[Hit]] = {}
        self._search_dock = QDockWidget('검색', self)
        self._search_dock.setObjectName('search_results_dock')
        self._search_dock.setWidget(self._search_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._search_dock)
        self._search_dock.hide()

        # 탭 전환은 alias(_doc/_canvas) 갱신이 끝난 뒤에 처리한다
        self._tab_widget.currentChanged.connect(
            lambda _i: QTimer.singleShot(0, self._on_find_tab_changed))

    def _build_find_menu(self, mb):
        """메뉴 막대의 '찾기' 메뉴."""
        menu = mb.addMenu(UI.MENU_FIND)
        self._add_action(menu, UI.ACT_FIND, self._open_find_bar, 'Ctrl+F')
        self._add_action(menu, UI.ACT_FIND_NEXT, lambda: self._nav_hit(1), 'F3')
        self._add_action(menu, UI.ACT_FIND_PREV, lambda: self._nav_hit(-1), 'Shift+F3')
        menu.addSeparator()
        menu.addAction(self._find_bar.case_action)
        menu.addAction(self._find_bar.word_action)
        menu.addSeparator()
        self._add_action(menu, UI.ACT_FIND_ADVANCED, self._open_search_panel, 'Ctrl+Shift+F')
        self._add_action(menu, UI.ACT_FIND_CLEAR, self._clear_find_highlights)
        menu.addSeparator()
        self._add_action(menu, UI.ACT_TEXT_REPLACE, self._text_replace, 'Ctrl+H')
        return menu

    def _find_bar_top_offset(self) -> int:
        bar = self._tab_widget.tabBar()
        return (bar.height() if bar.isVisible() else 0) + 10

    def _current_tab_key(self) -> int:
        """self._tabs 안에서 현재 문서의 위치 (탭을 끌어 옮겨도 문서로 찾는다)."""
        for k, tab in enumerate(getattr(self, '_tabs', [])):
            if tab.doc is self._doc:
                return k
        return -1

    def _tab_title(self, tab_key: int) -> str:
        title = ''
        try:
            tab = self._tabs[tab_key]
            i = self._tab_widget.indexOf(tab.splitter)
            title = self._tab_widget.tabText(i) if i >= 0 else ''
        except Exception:
            pass
        return title or f'문서 {tab_key + 1}'

    def _ocr_text_for_page(self, page_idx: int) -> str:
        if self._ocr_panel is None:
            return ''
        return getattr(self._ocr_panel, 'pages_text', {}).get(page_idx, '')

    # ── 찾기 막대 ─────────────────────────────────────────────────────
    def _open_find_bar(self):
        was_visible = self._find_bar.isVisible()
        self._find_bar.open()
        if was_visible:
            return
        query = self._find_bar.query().strip()
        if query and (query != self._find_query or self._find_doc is not self._doc):
            self._run_bar_search()
        elif query and self._find_hits and 0 <= self._find_cursor < len(self._find_hits):
            self._hl_set(self._current_tab_key(), self._find_hits,
                         self._find_hits[self._find_cursor])
            self._apply_find_highlights(reveal=False)

    def _close_find_bar(self):
        self._find_debounce.stop()
        self._cancel_find_job()
        self._find_bar.hide()
        self._clear_find_highlights()
        self._find_hits = []
        self._find_cursor = -1
        self._find_query = ''
        self._find_bar.set_status('')
        try:
            self._canvas.setFocus()
        except RuntimeError:
            pass

    def _on_find_query_changed(self, _text: str):
        self._find_debounce.start()

    def _on_find_options_changed(self):
        if self._find_bar.query().strip():
            self._run_bar_search()

    def _find_opts(self) -> SearchOptions:
        return SearchOptions(self._find_bar.case_sensitive(), self._find_bar.whole_word())

    def _cancel_find_job(self):
        job, self._find_job = self._find_job, None
        if job is None:
            return
        for sig in (job.hits_found, job.progress, job.finished):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass
        job.cancel()
        job.deleteLater()

    def _run_bar_search(self):
        self._find_debounce.stop()
        self._cancel_find_job()
        query = self._find_bar.query().strip()
        self._find_hits = []
        self._find_cursor = -1
        self._find_query = query
        self._find_doc = self._doc
        self._clear_find_highlights()
        if not query:
            self._find_bar.set_status('')
            return
        if not self._doc.is_open:
            self._find_bar.set_status('열린 문서 없음', 'error')
            return
        opts = self._find_opts()
        tab_key = self._current_tab_key()

        def page_fn(_tab, doc, i, q=query, o=opts):
            return find_in_page(doc.fitz_page(i), i, q, o,
                                ocr_text=self._ocr_text_for_page(i))

        job = _SearchJob([(tab_key, self._doc)], page_fn, self)
        job.hits_found.connect(self._on_bar_hits)
        job.progress.connect(self._on_bar_progress)
        job.finished.connect(self._on_bar_finished)
        self._find_job = job
        self._find_bar.set_status('검색 중…', 'busy')
        job.start()

    def _on_bar_hits(self, _tab, hits):
        first = not self._find_hits
        self._find_hits.extend(hits)
        if first:
            # 첫 결과가 나오면 끝까지 기다리지 않고 바로 보여 준다
            self._find_cursor = 0
            self._go_to_hit(0)
            return
        if self._hl_tab == self._current_tab_key() and 0 <= self._find_cursor < len(self._find_hits):
            self._hl_set(self._hl_tab, self._find_hits, self._find_hits[self._find_cursor])
        self._update_find_status()

    def _on_bar_progress(self, done: int, total: int):
        self._update_find_status(done, total)

    def _on_bar_finished(self, cancelled: bool):
        self._find_job = None
        if cancelled:
            return
        if not self._find_hits:
            if self._doc.is_open and not self._doc_has_text():
                self._find_bar.set_status('결과 없음 · 스캔본', 'error')
                self._find_bar.set_status_tip(
                    '이 문서에는 검색할 수 있는 글자가 없습니다(이미지로 된 스캔본).\n'
                    'OCR(Ctrl+Shift+O)로 본문을 인식한 뒤 다시 검색하세요.')
            else:
                self._find_bar.set_status('결과 없음', 'error')
            return
        self._update_find_status()
        # 결과가 모두 모였으니 전체 목록으로 다시 칠한다
        self._apply_find_highlights(reveal=False)

    def _doc_has_text(self, sample: int = 8) -> bool:
        try:
            n = self._doc.page_count()
        except Exception:
            return False
        for i in range(min(n, sample)):
            try:
                if page_has_text(self._doc.fitz_page(i)):
                    return True
            except Exception:
                pass
        return False

    def _update_find_status(self, done=None, total=None):
        n = len(self._find_hits)
        running = self._find_job is not None and self._find_job.is_running()
        if n == 0:
            if running and total:
                self._find_bar.set_status(f'검색 중… {done}/{total}쪽', 'busy')
            return
        hit = self._find_hits[self._find_cursor] if 0 <= self._find_cursor < n else None
        text = f'{self._find_cursor + 1} / {n}{"+" if running else ""}'
        if hit is not None and hit.rect is None:
            self._find_bar.set_status(text + ' · OCR')
            self._find_bar.set_status_tip(
                'OCR 로 인식한 글자에서 찾았습니다.\n화면상 위치 정보가 없어 페이지로만 이동합니다.')
        else:
            self._find_bar.set_status(text)

    def _nav_hit(self, direction: int):
        query = self._find_bar.query().strip()
        if not query:
            self._open_find_bar()
            return
        stale = (self._find_debounce.isActive() or self._find_doc is not self._doc
                 or self._find_query != query)
        if stale:
            # 입력을 방금 바꿨거나 문서가 바뀌었으면 먼저 새로 찾는다
            self._run_bar_search()
            return
        if not self._find_hits:
            if self._find_job is None:
                self._run_bar_search()
            return
        self._find_cursor = (self._find_cursor + direction) % len(self._find_hits)
        self._go_to_hit(self._find_cursor)

    def _go_to_hit(self, idx: int):
        if not (0 <= idx < len(self._find_hits)):
            return
        hit = self._find_hits[idx]
        if hit.page >= self._doc.page_count():
            self._run_bar_search()    # 페이지가 지워졌다 — 다시 찾는다
            return
        self._hl_set(self._current_tab_key(), self._find_hits, hit)
        self._navigate_to_page(hit.page, hit.rect)
        QTimer.singleShot(0, lambda: self._apply_find_highlights(reveal=True))
        self._update_find_status()

    def _navigate_to_page(self, page: int, rect=None):
        """검색 결과 페이지로 이동. 입력칸 포커스는 건드리지 않는다.

        (_go_to_page_from_nav 는 캔버스로 포커스를 옮겨서, 입력하는 동안 쓰면
         다음 글자가 문서로 들어가 버린다.)
        """
        if not self._doc.is_open:
            return
        if hasattr(self, '_page_spin'):
            self._page_spin.blockSignals(True)
            self._page_spin.setValue(page + 1)
            self._page_spin.blockSignals(False)
        if self._reflow_active:
            self._reflow_view.go_to_page(page)
            return
        c = self._canvas
        view_mode = getattr(self, '_view_mode', UI.VIEW_SINGLE)
        if view_mode == UI.VIEW_SEGMENT:
            seg = 0
            if rect is not None:
                try:
                    if rect.y0 >= self._doc.fitz_page(page).rect.height / 2:
                        seg = 1
                except Exception:
                    pass
            if (c.current_page() != page or not getattr(c, '_segment_mode', False)
                    or getattr(c, '_segment_index', -1) != seg):
                c.show_segment(page, seg, 2)
        elif view_mode in (UI.VIEW_BOOK, UI.VIEW_DOUBLE):
            left = page if page % 2 == 0 else page - 1
            if c.current_page() not in (left, left + 1) or page not in c._page_offsets:
                c.show_double(max(0, left))
        elif view_mode == UI.VIEW_SCROLL:
            # 위치가 있으면 reveal_search_hit 가 그 자리로 스크롤한다
            if rect is None or page not in c._page_offsets:
                c.goto_in_scroll(page)
        elif c.current_page() != page or page not in c._page_offsets:
            c.show_page(page)

    # ── 화면 강조 ─────────────────────────────────────────────────────
    def _hl_set(self, tab_key: int, hits, current):
        by_page: dict = {}
        for h in hits:
            if h.rect is not None:
                by_page.setdefault(h.page, []).append(h.rect)
        self._hl_tab = tab_key
        self._hl_by_page = by_page
        self._hl_current = (current.page, current.rect) if current is not None else (None, None)

    def _apply_find_highlights(self, reveal: bool = False):
        if self._hl_tab < 0 or self._hl_tab != self._current_tab_key():
            return
        c = self._canvas
        self._hook_canvas_for_highlights(c)
        if self._hl_canvas is not None and self._hl_canvas is not c:
            try:
                self._hl_canvas.clear_search_state()
            except RuntimeError:
                pass
        self._hl_canvas = c
        page, rect = self._hl_current
        c.set_search_highlights(self._hl_by_page, page, rect)
        if reveal and rect is not None:
            c.reveal_search_hit(page, rect)

    def _hook_canvas_for_highlights(self, canvas):
        """페이지가 다시 그려지면 씬이 비워지므로 강조를 다시 칠하게 연결한다."""
        if getattr(canvas, '_find_hl_hooked', False):
            return
        canvas._find_hl_hooked = True
        canvas.page_changed.connect(
            lambda _p, c=canvas: QTimer.singleShot(0, lambda: self._reapply_highlights_for(c)))

    def _reapply_highlights_for(self, canvas):
        if canvas is not self._canvas or canvas is not self._hl_canvas:
            return
        if self._hl_tab != self._current_tab_key():
            return
        page, rect = self._hl_current
        try:
            canvas.set_search_highlights(self._hl_by_page, page, rect)
        except RuntimeError:
            pass

    def _clear_find_highlights(self):
        self._hl_tab = -1
        self._hl_by_page = {}
        self._hl_current = (None, None)
        seen = set()
        for c in (self._hl_canvas, getattr(self, '_canvas', None)):
            if c is None or id(c) in seen:
                continue
            seen.add(id(c))
            try:
                c.clear_search_state()
            except RuntimeError:
                pass
        self._hl_canvas = None

    def _on_find_tab_changed(self):
        key = self._current_tab_key()
        if self._hl_canvas is not None and self._hl_canvas is not self._canvas:
            try:
                self._hl_canvas.clear_search_state()
            except RuntimeError:
                pass
            self._hl_canvas = None
        if self._hl_tab >= 0 and self._hl_tab == key:
            # 결과 패널에서 다른 문서의 항목을 눌러 넘어온 경우
            self._apply_find_highlights(reveal=False)
            return
        # 찾기 막대의 결과는 문서마다 다르므로 새 문서에서 다시 찾는다
        self._cancel_find_job()
        self._find_hits = []
        self._find_cursor = -1
        if self._find_bar.isVisible() and self._find_bar.query().strip():
            self._run_bar_search()
        else:
            self._find_query = ''
            self._find_bar.set_status('')

    # ── 검색 결과 패널 ────────────────────────────────────────────────
    def _open_search_panel(self):
        self._search_dock.show()
        self._search_dock.raise_()
        query = self._find_bar.query().strip()
        if query and not self._search_panel.query().strip():
            self._search_panel.set_query(query)
        self._search_panel.focus_query()

    def _on_panel_search(self, req):
        self._stop_panel_search(silent=True)
        opts = SearchOptions(req.case_sensitive, req.whole_word)
        cur_key = self._current_tab_key()
        if req.scope == SCOPE_ALL:
            targets = [(k, t.doc) for k, t in enumerate(self._tabs) if t.doc.is_open]
        else:
            targets = [(cur_key, self._doc)] if cur_key >= 0 and self._doc.is_open else []
        self._panel_hits = {}
        self._search_panel.begin()
        if not targets:
            self._search_panel.finish()
            self._search_panel.set_message('열린 문서가 없습니다.')
            return

        def page_fn(tab_key, doc, i, r=req, o=opts):
            # OCR 결과는 현재 문서 것만 들고 있다
            ocr = self._ocr_text_for_page(i) if tab_key == cur_key else ''
            return search_page_advanced(doc.fitz_page(i), i, r.query, r.mode,
                                        r.exclude, o, ocr_text=ocr)

        job = _SearchJob(targets, page_fn, self)
        job.hits_found.connect(self._on_panel_hits)
        job.progress.connect(self._search_panel.set_progress)
        job.finished.connect(self._on_panel_finished)
        self._panel_job = job
        job.start()

    def _on_panel_hits(self, tab_key: int, hits):
        self._panel_hits.setdefault(tab_key, []).extend(hits)
        self._search_panel.add_hits(tab_key, self._tab_title(tab_key), hits)

    def _on_panel_finished(self, cancelled: bool):
        self._panel_job = None
        self._search_panel.finish(cancelled)

    def _stop_panel_search(self, silent: bool = False):
        job, self._panel_job = self._panel_job, None
        if job is None:
            return
        for sig in (job.hits_found, job.progress, job.finished):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass
        job.cancel()
        job.deleteLater()
        if not silent:
            self._search_panel.finish(cancelled=True)

    def _on_panel_hit_activated(self, tab_key: int, page: int, rect):
        if not (0 <= tab_key < len(self._tabs)):
            return
        tab = self._tabs[tab_key]
        if not tab.doc.is_open or page >= tab.doc.page_count():
            return
        r = fitz.Rect(rect) if rect is not None else None
        hits = self._panel_hits.get(tab_key, [])
        current = next((h for h in hits if h.page == page
                        and (h.rect == r if r is not None else h.rect is None)), None)
        if current is None:
            current = Hit(page, r, '')
        self._hl_set(tab_key, hits, current)
        if tab.doc is not self._doc:
            self._tab_widget.setCurrentWidget(tab.splitter)
        self._navigate_to_page(page, r)
        QTimer.singleShot(0, lambda: self._apply_find_highlights(reveal=True))


    def _go_prev_page(self):
        if not self._doc.is_open:
            return
        if self._reflow_active:
            self._reflow_view.prev_page()
            return
        cur = self._canvas.current_page()
        view_mode = getattr(self, '_view_mode', UI.VIEW_SINGLE)
        if view_mode == UI.VIEW_SEGMENT:
            self._canvas.step_segment(False)
        elif view_mode in (UI.VIEW_BOOK, UI.VIEW_DOUBLE):
            left = cur if cur % 2 == 0 else cur - 1
            self._canvas.show_double(max(0, left - 2))
        elif view_mode == UI.VIEW_SCROLL:
            self._canvas.goto_in_scroll(max(0, cur - 1))
        else:
            self._canvas.show_page(max(0, cur - 1))


    def _go_next_page(self):
        if not self._doc.is_open:
            return
        if self._reflow_active:
            self._reflow_view.next_page()
            return
        cur = self._canvas.current_page()
        last = max(0, self._doc.page_count() - 1)
        view_mode = getattr(self, '_view_mode', UI.VIEW_SINGLE)
        if view_mode == UI.VIEW_SEGMENT:
            self._canvas.step_segment(True)
        elif view_mode in (UI.VIEW_BOOK, UI.VIEW_DOUBLE):
            left = cur if cur % 2 == 0 else cur - 1
            self._canvas.show_double(min(max(0, last - 1), left + 2))
        elif view_mode == UI.VIEW_SCROLL:
            self._canvas.goto_in_scroll(min(last, cur + 1))
        else:
            self._canvas.show_page(min(last, cur + 1))


    def _go_to_page_from_nav(self):
        if not self._doc.is_open or not hasattr(self, '_page_spin'):
            return
        target = max(0, min(self._doc.page_count() - 1, self._page_spin.value() - 1))
        # 이동 후 방향키가 바로 페이지 넘김으로 동작하도록 포커스 복귀
        self._canvas.setFocus()
        if self._reflow_active:
            self._reflow_view.go_to_page(target)
            return
        view_mode = getattr(self, '_view_mode', UI.VIEW_SINGLE)
        if view_mode == UI.VIEW_SEGMENT:
            self._canvas.show_segment(target, 0, 2)
        elif view_mode in (UI.VIEW_BOOK, UI.VIEW_DOUBLE):
            left = target if target % 2 == 0 else target - 1
            self._canvas.show_double(max(0, left))
        elif view_mode == UI.VIEW_SCROLL:
            self._canvas.goto_in_scroll(target)
        else:
            self._canvas.show_page(target)


    def _fit_width(self):
        if self._reflow_active:
            return
        self._canvas.fit_width()


    def _actual_size(self):
        if self._reflow_active:
            return
        self._canvas.set_zoom(1.0)


    def _on_thumbnail_page_selected(self, page_index: int):
        if self._text_draft_active or not self._doc.is_open:
            return
        if self._reflow_active:
            self._reflow_view.go_to_page(page_index)
            return
        view_mode = getattr(self, '_view_mode', UI.VIEW_SINGLE)
        if view_mode == UI.VIEW_SEGMENT:
            self._canvas.show_segment(page_index, 0, 2)
        elif view_mode in (UI.VIEW_DOUBLE, UI.VIEW_BOOK):
            left = page_index if page_index % 2 == 0 else page_index - 1
            self._canvas.show_double(max(0, left))
        else:
            self._canvas.show_page(page_index)

