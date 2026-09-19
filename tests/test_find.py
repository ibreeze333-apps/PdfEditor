# tests/test_find.py — 찾기 기능 회귀 테스트
"""찾기가 '열리긴 하는데 버튼도 없고 찾아지지도 않던' 문제를 막는다.

실제로 겹쳐 있던 원인:
- 막대 버튼을 setFixedSize(28, 26) 로 박아 전역 QSS(min-height 30px + padding)와
  충돌 → 44px 로 그려져 38px 막대 밖으로 잘림 → 버튼이 안 보임.
- 강조 상자 좌표에 표시 배율(_zoom)을 곱함 → 씬은 PDF pt × _BASE_RENDER_ZOOM
  단위라, 배율 100% 에서는 단어의 절반 위치·절반 크기에 칠해짐.
- 글자마다 전체 페이지를 한 번에 훑음 → 큰 문서에서 입력할 때마다 멈춤.
"""
from __future__ import annotations

import os
import time

import fitz
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QToolButton

from core.search import (
    MODE_ALL, MODE_ANY, MODE_PHRASE, SearchOptions,
    find_in_page, page_has_text, search_page_advanced,
)

FONT = r'C:\Windows\Fonts\malgun.ttf'
needs_korean_font = pytest.mark.skipif(not os.path.exists(FONT), reason='맑은 고딕 없음')


# ── 검색 엔진 ─────────────────────────────────────────────────────────
def _korean_doc(lines_per_page):
    doc = fitz.open()
    for lines in lines_per_page:
        page = doc.new_page(width=595, height=842)
        page.insert_font(fontname='mg', fontfile=FONT)
        for i, text in enumerate(lines):
            page.insert_text((72, 100 + 30 * i), text, fontname='mg', fontsize=14)
    return doc


@pytest.fixture
def kdoc():
    doc = _korean_doc([[
        '상법 제64조 5년입니다.',
        '제64조의2 는 다른 조문입니다.',
        'Hello hello HELLO helloworld',
    ]])
    yield doc
    doc.close()


@needs_korean_font
def test_finds_korean(kdoc):
    assert len(find_in_page(kdoc[0], 0, '제64조')) == 2


@needs_korean_font
def test_whole_word_excludes_longer_korean_word(kdoc):
    hits = find_in_page(kdoc[0], 0, '제64조', SearchOptions(whole_word=True))
    assert len(hits) == 1
    assert hits[0].rect.y0 < 110          # 첫 줄의 '제64조'만


@needs_korean_font
def test_case_insensitive_by_default(kdoc):
    assert len(find_in_page(kdoc[0], 0, 'hello')) == 4


@needs_korean_font
def test_case_sensitive(kdoc):
    assert len(find_in_page(kdoc[0], 0, 'hello', SearchOptions(case_sensitive=True))) == 2


@needs_korean_font
def test_case_sensitive_and_whole_word(kdoc):
    opts = SearchOptions(case_sensitive=True, whole_word=True)
    assert len(find_in_page(kdoc[0], 0, 'hello', opts)) == 1


@needs_korean_font
def test_context_snippet(kdoc):
    hits = find_in_page(kdoc[0], 0, '제64조', want_context=True)
    assert any('5년입니다' in h.context for h in hits)


@needs_korean_font
def test_advanced_modes():
    doc = _korean_doc([
        ['소멸시효 3년', '상법 규정'],      # 0: 둘 다
        ['소멸시효만 있음'],               # 1: 소멸시효만
        ['상법만 있음'],                   # 2: 상법만
    ])
    try:
        def pages(mode, q, exclude=''):
            return sorted({h.page for i in range(doc.page_count)
                           for h in search_page_advanced(doc[i], i, q, mode, exclude)})
        assert pages(MODE_ALL, '소멸시효 상법') == [0]
        assert pages(MODE_ANY, '소멸시효 상법') == [0, 1, 2]
        assert pages(MODE_PHRASE, '상법 규정') == [0]
        assert pages(MODE_ANY, '소멸시효 상법', exclude='3년') == [1, 2]
    finally:
        doc.close()


def test_scanned_page_uses_ocr_text():
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(50, 50, 200, 200))    # 글자 없는 페이지 (스캔본 흉내)
    try:
        assert not page_has_text(page)
        assert find_in_page(page, 0, 'abc') == []
        hits = find_in_page(page, 0, 'abc', ocr_text='first line\nxx abc yy')
        assert len(hits) == 1 and hits[0].rect is None and 'abc' in hits[0].context
    finally:
        doc.close()


# ── 메인 창 ───────────────────────────────────────────────────────────
def _ascii_pdf(path, pages=3, text='Sample body'):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100 + 200 * i), f'{text} {i + 1}', fontsize=14)
    doc.save(str(path))
    doc.close()
    return str(path)


def _pump(qapp, until=None, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.005)
    return until is None


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    import utils.settings as settings
    from ui.main_window import MainWindow
    monkeypatch.setattr(settings, '_SETTINGS_PATH', tmp_path / 'settings.json')
    monkeypatch.setattr(MainWindow, '_check_recovery', lambda self: None)
    monkeypatch.setattr(MainWindow, '_clear_autosave', lambda self: None)
    monkeypatch.setattr(MainWindow, '_emergency_save', lambda self: None)
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    qapp.processEvents()
    yield win
    win._app_close_requested = True
    win.close()
    for tab in win._tabs:
        tab.renderer.close()
        tab.doc.close()
    win.deleteLater()
    qapp.processEvents()


def _search(window, qapp, query):
    window._open_find_bar()
    window._find_bar.set_query(query)
    assert _pump(qapp, lambda: window._find_job is None and window._find_query == query
                 and not window._find_debounce.isActive(), timeout=5)
    _pump(qapp, timeout=0.2)


def test_find_has_its_own_menu(window):
    from ui.texts import UI
    # QAction 목록을 붙잡아 둔 채로 menu() 를 부른다. 임시 래퍼에서 꺼낸 QMenu 를
    # dict 에 모아 두면 PySide 래퍼가 무효가 돼 'already deleted' 가 난다(앱 문제 아님).
    actions = window._menubar.actions()
    by_text = {a.text(): a for a in actions}
    edit_menu = by_text[UI.MENU_EDIT].menu()
    assert not any('찾기' in a.text() for a in edit_menu.actions())
    find_menu = by_text[UI.MENU_FIND].menu()
    found = {a.text(): a.shortcut().toString()
             for a in find_menu.actions() if not a.isSeparator()}
    assert found[UI.ACT_FIND] == 'Ctrl+F'
    assert found[UI.ACT_FIND_NEXT] == 'F3'
    assert found[UI.ACT_FIND_PREV] == 'Shift+F3'
    assert found[UI.ACT_FIND_ADVANCED] == 'Ctrl+Shift+F'
    assert found[UI.ACT_TEXT_REPLACE] == 'Ctrl+H'


def test_find_bar_buttons_are_visible(window, qapp, tmp_path):
    window.open_path_checked(_ascii_pdf(tmp_path / 'a.pdf'))
    _pump(qapp, timeout=0.3)
    window._open_find_bar()
    _pump(qapp, timeout=0.2)
    bar = window._find_bar
    assert bar.isVisible()
    assert bar.parentWidget().rect().contains(bar.geometry())
    # (입력칸의 지우기 ×도 QToolButton 이라 이름으로 집어 검사한다)
    buttons = [bar._prev_btn, bar._next_btn, bar._opt_btn, bar._close_btn]
    for b in buttons:
        assert b.isVisible() and bar.rect().contains(b.geometry()), b.toolTip()


def test_typing_finds_and_f3_cycles(window, qapp, tmp_path):
    window.open_path_checked(_ascii_pdf(tmp_path / 'a.pdf'))
    _pump(qapp, timeout=0.3)
    _search(window, qapp, 'body')
    assert len(window._find_hits) == 3
    assert window._find_bar.status_text() == '1 / 3'
    window._nav_hit(1)
    assert window._find_bar.status_text() == '2 / 3'
    window._nav_hit(-1)
    window._nav_hit(-1)
    assert window._find_bar.status_text() == '3 / 3'     # 처음에서 뒤로 가면 끝으로


def test_no_result_and_scanned_hint(window, qapp, tmp_path):
    window.open_path_checked(_ascii_pdf(tmp_path / 'a.pdf'))
    _pump(qapp, timeout=0.3)
    _search(window, qapp, 'nothing-here')
    assert window._find_bar.status_text() == '결과 없음'

    doc = fitz.open()
    doc.new_page().draw_rect(fitz.Rect(50, 50, 200, 200))
    scan = tmp_path / 'scan.pdf'
    doc.save(str(scan))
    doc.close()
    window.open_path_checked(str(scan))
    _pump(qapp, timeout=0.3)
    _search(window, qapp, 'anything')
    assert '스캔본' in window._find_bar.status_text()


def test_highlight_lands_on_the_word(window, qapp, tmp_path):
    import ui.canvas_view as cv
    window.open_path_checked(_ascii_pdf(tmp_path / 'a.pdf'))
    _pump(qapp, timeout=0.3)
    _search(window, qapp, 'body')
    canvas = window._canvas
    hit = window._find_hits[window._find_cursor]
    offset = canvas._page_offsets[hit.page]
    s = cv._BASE_RENDER_ZOOM
    expected = QRectF(hit.rect.x0 * s + offset.x(), hit.rect.y0 * s + offset.y(),
                      hit.rect.width * s, hit.rect.height * s)
    drawn = [item.rect() for item in canvas._search_hit_items]
    assert drawn, '강조 상자가 없습니다'
    assert any(abs(r.x() - expected.x()) < 0.5 and abs(r.y() - expected.y()) < 0.5
               and abs(r.width() - expected.width()) < 0.5 for r in drawn), (drawn, expected)


def test_results_panel_lists_and_navigates(window, qapp, tmp_path):
    window.open_path_checked(_ascii_pdf(tmp_path / 'a.pdf'))
    _pump(qapp, timeout=0.3)
    window._open_search_panel()
    panel = window._search_panel
    panel.set_query('body')
    panel._emit_search()
    assert _pump(qapp, lambda: window._panel_job is None and panel.result_count() == 3, timeout=5)
    node = panel._tree.topLevelItem(0)
    assert node.childCount() == 3
    panel._on_item(node.child(2))
    _pump(qapp, timeout=0.3)
    assert window._hl_current[0] == 2
    assert window._canvas._search_hit_items
