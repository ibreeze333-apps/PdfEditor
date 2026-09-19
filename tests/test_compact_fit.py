# tests/test_compact_fit.py — 좁은 화면 대응 회귀 테스트
"""1920×1080 노트북을 150% 로 쓰면 앱이 보는 크기는 1280×680 이다.

- 툴바가 4줄로 넘쳐 문서 영역이 창의 절반밖에 안 됐다 → 넘칠 때만 아이콘만
  보이는 '컴팩트' 표시로 바꿔 줄 수를 줄인다(ui/glass_button.py, ui/flow_bar.py).
- 대화상자 여러 개가 화면보다 큰 크기/최소 크기를 박아 두어 아래쪽 버튼이
  화면 밖으로 나갔다 → 뜰 때 화면 작업 영역에 맞춘다(ui/screen_fit.py).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QDialog, QWidget

ICON_LABELS = ['🖱 선택', '🖌 형광펜', '📏 밑줄', '✏ 연필', '➖ 직선', '➡ 화살표',
               '⬛ 도형', '🔖 스탬프', '🖼 이미지', '💧 블러', '🔤 텍스트', '📌 메모',
               '🔖 인덱스', '📷 찍기', '✂ 영역']


# ── 버튼 ──────────────────────────────────────────────────────────────
def test_compact_label_only_for_icon_buttons(qapp):
    from ui.glass_button import GlassButton
    assert GlassButton('🖌 형광펜').compact_label() == '🖌'
    assert GlassButton('\U0001F58D 마커').compact_label() == '\U0001F58D'
    for text in ('PDF 저장', 'OCR', '~~취소선~~', '책 보기', '‹', '이동'):
        assert not GlassButton(text).can_compact(), text


def test_set_compact_keeps_text_and_moves_name_to_tooltip(qapp):
    from ui.glass_button import GlassButton
    b = GlassButton('🖌 형광펜')
    wide = b.sizeHint().width()
    b.set_compact(True)
    assert b.display_text() == '🖌'
    assert b.text() == '🖌 형광펜'            # 다른 코드가 읽는 이름은 그대로
    assert b.toolTip() == '🖌 형광펜'
    assert b.sizeHint().width() < wide
    b.set_compact(False)
    assert b.display_text() == '🖌 형광펜'
    assert b.toolTip() == ''                   # 자동으로 넣은 툴팁만 치운다


def test_existing_tooltip_is_kept(qapp):
    from ui.glass_button import GlassButton
    b = GlassButton('📖 사전')
    b.setToolTip('사전 창 열기 (Ctrl+D)')
    b.set_compact(True)
    b.set_compact(False)
    assert b.toolTip() == '사전 창 열기 (Ctrl+D)'


# ── 줄바꿈 컨테이너 ───────────────────────────────────────────────────
def _flow_with_buttons(qapp):
    from ui.flow_bar import FlowBar
    from ui.glass_button import GlassButton
    host = QWidget()
    bar = FlowBar(host)
    for text in ICON_LABELS:
        bar.add_widget(GlassButton(text))
    return host, bar


def test_wide_bar_keeps_text(qapp):
    host, bar = _flow_with_buttons(qapp)
    bar.resize(4000, 100)
    bar._fit()
    assert bar.compact is False
    assert bar.rows() == 1


def test_narrow_bar_goes_compact_only_when_it_saves_rows(qapp):
    host, bar = _flow_with_buttons(qapp)
    width = 900
    bar.resize(width, 100)
    # 컴팩트 없이 몇 줄이 되는지 먼저 잰다
    buttons = bar._compactable()
    bar._set_compact_all(buttons, False)
    normal_rows = bar._rows_at(bar._best_scale(width), width)
    assert normal_rows > 1, '테스트 폭이 너무 넓다'

    bar._fit()
    assert bar.compact is True
    assert bar.rows() < normal_rows
    assert all(b.is_compact() for b in buttons)


# ── 화면 맞춤 ─────────────────────────────────────────────────────────
SMALL = QRect(0, 0, 1280, 680)


def test_big_dialog_is_fitted_to_screen(qapp):
    from ui.screen_fit import fit_to_screen
    dlg = QDialog()
    dlg.setMinimumSize(760, 820)       # 페이지 자르기 대화상자와 같은 최소 크기
    dlg.resize(760, 820)
    dlg.move(300, 200)
    assert fit_to_screen(dlg, avail=SMALL) is True
    assert dlg.height() <= SMALL.height()
    assert dlg.minimumHeight() <= SMALL.height()
    assert SMALL.contains(dlg.frameGeometry())


def test_small_dialog_is_left_alone(qapp):
    from ui.screen_fit import fit_to_screen
    dlg = QDialog()
    dlg.resize(400, 300)
    dlg.move(50, 50)
    assert fit_to_screen(dlg, avail=SMALL) is False
    assert (dlg.width(), dlg.height()) == (400, 300)


def test_offscreen_dialog_is_moved_back(qapp):
    from ui.screen_fit import fit_to_screen
    dlg = QDialog()
    dlg.resize(400, 300)
    dlg.move(1200, 600)                # 오른쪽 아래로 삐져나감
    assert fit_to_screen(dlg, avail=SMALL) is True
    assert SMALL.contains(dlg.frameGeometry())
