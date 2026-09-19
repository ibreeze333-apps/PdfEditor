"""Failures found during the September runtime audit; no live services used."""
from pathlib import Path
from types import SimpleNamespace
import sys
import fitz
import pytest


@pytest.mark.parametrize('kind', ['pdf', 'image', 'password'])
def test_failed_open_preserves_current_document(doc, tmp_path, kind):
    doc.rotate_page(0, 90)
    old = doc.fitz_doc()
    old_path = doc.path
    if kind == 'password':
        path = tmp_path / 'locked.pdf'
        with fitz.open() as locked:
            locked.new_page()
            locked.save(path, encryption=fitz.PDF_ENCRYPT_AES_256,
                        owner_pw='owner', user_pw='reader')
        assert not doc.open(str(path), 'wrong')
        assert doc.needs_password
    elif kind == 'image':
        assert not doc.open_image(str(tmp_path / 'missing.png'))
    else:
        assert not doc.open(str(tmp_path / 'missing.pdf'))
    assert doc.is_open and doc.fitz_doc() is old
    assert doc.path == old_path and doc.dirty
    assert doc.fitz_page(0).rotation == 90


@pytest.mark.parametrize('next_doc', ['new', 'image'])
def test_new_document_does_not_inherit_previous_password_restrictions(doc, tmp_path, next_doc):
    path = tmp_path / 'locked.pdf'
    with fitz.open() as locked:
        locked.new_page()
        locked.save(path, encryption=fitz.PDF_ENCRYPT_AES_256,
                    owner_pw='owner', user_pw='reader', permissions=0)
    assert doc.open(str(path), 'reader')
    assert not doc.opened_as_owner
    if next_doc == 'new':
        doc.new_empty()
    else:
        from PySide6.QtGui import QImage
        image = QImage(10, 10, QImage.Format.Format_RGB32)
        image.fill(0xffffffff)
        image.save(str(tmp_path / 'test.png'))
        assert doc.open_image(str(tmp_path / 'test.png'))
    assert doc.opened_as_owner
    assert not doc.was_encrypted and not doc.password and not doc.needs_password


def test_markdown_export_includes_unsaved_edits(doc, tmp_path, monkeypatch):
    from core.exporter import Exporter
    doc.fitz_page(0).insert_text((72, 500), 'UNSAVED EDIT')
    def convert(path):
        with fitz.open(path) as current:
            return SimpleNamespace(text_content=current[0].get_text())
    monkeypatch.setitem(sys.modules, 'markitdown',
                        SimpleNamespace(MarkItDown=lambda: SimpleNamespace(convert=convert)))
    out = tmp_path / 'export.md'
    assert Exporter()._to_markdown_via_markitdown(doc.fitz_doc(), str(out))
    assert 'UNSAVED EDIT' in out.read_text(encoding='utf-8')


def test_exit_checks_background_dirty_tab(qapp, monkeypatch):
    from ui.main_window import MainWindow
    from PySide6.QtGui import QCloseEvent
    clean = SimpleNamespace(doc=SimpleNamespace(is_open=True, dirty=False, path='clean.pdf'),
                            canvas=SimpleNamespace(pending_layer=lambda: SimpleNamespace(count=lambda: 0)))
    dirty = SimpleNamespace(doc=SimpleNamespace(is_open=True, dirty=True, path='dirty.pdf'), canvas=clean.canvas)
    checked = []
    fake = SimpleNamespace(_app_close_requested=True, _text_draft_active=False,
        _tabs=[clean,dirty], _doc=clean.doc, _canvas=clean.canvas, _current_tab_idx=0,
        _settings=SimpleNamespace(save=lambda: None), width=lambda:1280, height=lambda:900,
        _clear_autosave=lambda:None, _emergency_save=lambda:None)
    def select(idx):
        fake._current_tab_idx=idx;fake._doc=fake._tabs[idx].doc;fake._canvas=fake._tabs[idx].canvas
    fake._tab_widget=SimpleNamespace(currentIndex=lambda:fake._current_tab_idx,setCurrentIndex=select)
    fake._confirm_discard=lambda: checked.append(fake._doc.path) or not fake._doc.dirty
    if hasattr(MainWindow, '_confirm_all_tabs_for_close'):
        fake._confirm_all_tabs_for_close=lambda:MainWindow._confirm_all_tabs_for_close(fake)
    event=QCloseEvent()
    MainWindow.closeEvent(fake,event)
    assert not event.isAccepted()
    assert checked == ['dirty.pdf']
    assert fake._current_tab_idx == 0


def test_closing_pending_save_prompt_does_not_save(qapp, monkeypatch):
    from ui.mainwin.file_ops import FileOpsMixin
    import ui.mainwin.file_ops as module
    calls=[]
    class Prompt:
        ButtonRole=module.QMessageBox.ButtonRole
        def __init__(self,*a):pass
        def setWindowTitle(self,*a):pass
        def setText(self,*a):pass
        def addButton(self,*a):return object()
        def setDefaultButton(self,*a):pass
        def exec(self):pass
        def clickedButton(self):return None
    monkeypatch.setattr(module,'QMessageBox',Prompt)
    fake=SimpleNamespace(_write_permission_ok=lambda what:True,
        _confirm_save_over_signature=lambda:True,_confirm_save_over_encryption=lambda:True,
        _canvas=SimpleNamespace(pending_layer=lambda:SimpleNamespace(count=lambda:1)),
        _doc=SimpleNamespace(path='document.pdf'))
    assert FileOpsMixin._do_save(fake) is False


def test_invalid_settings_types_cannot_break_startup(tmp_path, monkeypatch):
    import json
    import utils.settings as settings
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'window_w':'wide', 'window_h':None, 'recent_files':42,
                               'zoom':float('nan'), 'tool_defaults':'bad', 'dict_enabled':True}))
    monkeypatch.setattr(settings,'_SETTINGS_PATH',path)
    loaded=settings.AppSettings.load()
    assert isinstance(loaded.window_w,int) and isinstance(loaded.window_h,int)
    assert isinstance(loaded.recent_files,list) and isinstance(loaded.tool_defaults,dict)
    assert loaded.zoom == 1.0 and loaded.dict_enabled is True


def test_failed_settings_save_preserves_previous_settings(tmp_path, monkeypatch):
    import utils.settings as settings
    path=tmp_path/'settings.json';path.write_text('{"window_w":1234}')
    monkeypatch.setattr(settings,'_SETTINGS_PATH',path)
    def fail(*args):raise OSError('disk full')
    monkeypatch.setattr('os.replace',fail)
    assert settings.AppSettings().save() is False
    assert path.read_text() == '{"window_w":1234}'


def test_size_split_does_not_overwrite_silently(qapp,tmp_path,monkeypatch):
    from ui.dialogs.split_by_size_dialog import SplitBySizeDialog, QFileDialog, QMessageBox
    path=tmp_path/'part_001.pdf';path.write_bytes(b'keep existing')
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args:str(tmp_path))
    monkeypatch.setattr(QMessageBox,'information',lambda *args:None)
    with fitz.open() as source:
        source.new_page()
        dlg=SplitBySizeDialog(source)
        monkeypatch.setattr(dlg,'_ask_collision',lambda *args:'number',raising=False)
        dlg._run()
    assert path.read_bytes()==b'keep existing'
    with fitz.open(tmp_path/'part_001_2.pdf') as result:assert result.page_count==1


def test_slow_render_thread_is_not_destroyed_with_closed_canvas(doc, qapp):
    import threading
    from PySide6.QtCore import QThread, Signal
    from PySide6.QtGui import QImage
    from ui.canvas_view import PdfCanvasView
    from core.renderer import PageRenderer
    release=threading.Event()
    class SlowWorker(QThread):
        page_ready=Signal(int,QImage)
        def run(self):release.wait(5)
        def stop(self):pass  # already rendering a page; cannot interrupt native work
        def wait(self,*args):return False  # simulate the 1500ms timeout immediately
    renderer=PageRenderer(doc)
    canvas=PdfCanvasView(doc,renderer)
    worker=SlowWorker(canvas)
    worker.page_ready.connect(canvas._on_scroll_page_ready)
    canvas._scroll_worker=worker
    worker.start()
    try:
        canvas._stop_scroll_worker()
        assert worker.parent() is None, 'A closed canvas would destroy a still-running QThread'
    finally:
        release.set()
        QThread.wait(worker,2000)
        renderer.close()
        canvas.deleteLater()
        qapp.processEvents()
