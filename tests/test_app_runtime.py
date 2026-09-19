"""Main-window regressions using isolated settings and no user documents."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QShortcut
from PySide6.QtWidgets import QPushButton
from PySide6.QtTest import QTest
from ui.main_window import MainWindow
import utils.settings as settings


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, '_SETTINGS_PATH', tmp_path / 'settings.json')
    monkeypatch.setattr(MainWindow, '_check_recovery', lambda self: None)
    monkeypatch.setattr(MainWindow, '_clear_autosave', lambda self: None)
    monkeypatch.setattr(MainWindow, '_emergency_save', lambda self: None)
    win = MainWindow()
    win.resize(1100, 700)
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


def test_ctrl_w_closes_tab_once(window, qapp):
    window._new_tab()
    assert len(window._tabs) == 2
    qapp.setActiveWindow(window)
    QTest.keyClick(window, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()
    assert len(window._tabs) == 1


def test_no_duplicate_main_window_shortcuts(window):
    keys = []
    for action in window.findChildren(QAction):
        keys.extend(s.toString() for s in action.shortcuts() if not s.isEmpty())
    keys.extend(b.shortcut().toString() for b in window.findChildren(QPushButton)
                if not b.shortcut().isEmpty())
    keys.extend(s.key().toString() for s in window.findChildren(QShortcut) if not s.key().isEmpty())
    assert len(keys) == len(set(keys))


def test_style_switch_keeps_selection_and_persists(window, qapp):
    from ui.glass_button import GlassButton
    button = window._annot_bar._glass_btns[2]
    button.click()
    for style in ('classic', 'liquid', 'classic'):
        window._menu_style_actions[style].trigger()
        for _ in range(4):
            qapp.processEvents()
        assert button.isChecked()
        assert window._menubar.property('menuButtonStyle') == style
        assert settings.AppSettings.load().menu_button_style == style
        assert window._page_prev_btn.width() >= 20
        assert window._page_next_btn.width() >= 20
        for bar in (window._annot_bar, window._doc_toolbar):
            for b in bar.findChildren(GlassButton):
                assert b.parentWidget().rect().contains(b.geometry())
    loaded = MainWindow()
    assert loaded._menubar.property('menuButtonStyle') == 'classic'
    loaded._app_close_requested = True
    loaded.close()
    loaded.deleteLater()
