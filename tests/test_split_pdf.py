from pathlib import Path

import fitz
import pytest

from ui.dialogs.split_pdf_dialog import SplitPdfDialog, QFileDialog, QMessageBox
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest


@pytest.fixture
def split_env(qapp, tmp_path, monkeypatch):
    source = fitz.open()
    for i in range(3):
        source.new_page().insert_text((72, 72), f'Page {i + 1}')
    dlg = SplitPdfDialog(3)
    dlg._mode_cb.setCurrentIndex(1)
    dlg._range_ed.setText('1-2,3')
    messages = []
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *a: str(tmp_path))
    for method in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, method,
                            lambda *a, kind=method: messages.append((kind, a[-1])))
    yield dlg, source, tmp_path, messages
    source.close()


def test_repeat_numbered_keeps_previous_results(split_env, monkeypatch):
    dlg, source, folder, messages = split_env
    dlg.split(source)
    original = (folder / 'split_001.pdf').read_bytes()
    (folder / 'split_001_2.pdf').write_bytes(b'keep this too')
    monkeypatch.setattr(dlg, '_ask_collision', lambda *a: 'number')
    dlg.split(source)
    assert (folder / 'split_001.pdf').read_bytes() == original
    assert (folder / 'split_001_2.pdf').read_bytes() == b'keep this too'
    with fitz.open(folder / 'split_001_3.pdf') as doc:
        assert doc.page_count == 2
        assert 'Page 2' in doc[1].get_text()
    assert (folder / 'split_002_2.pdf').exists()


def test_explicit_overwrite(split_env, monkeypatch):
    dlg, source, folder, _ = split_env
    path = folder / 'split_001.pdf'
    path.write_bytes(b'previous')
    monkeypatch.setattr(dlg, '_ask_collision', lambda *a: 'overwrite')
    dlg.split(source)
    with fitz.open(path) as doc:
        assert doc.page_count == 2


def test_cancel_later_conflict_writes_nothing(split_env, monkeypatch):
    dlg, source, folder, messages = split_env
    path = folder / 'split_002.pdf'
    path.write_bytes(b'previous')
    monkeypatch.setattr(dlg, '_ask_collision', lambda *a: None)
    dlg.split(source)
    assert path.read_bytes() == b'previous'
    assert not (folder / 'split_001.pdf').exists()
    assert not messages


def test_rename_existing_name_is_checked_again(split_env, monkeypatch):
    dlg, source, folder, _ = split_env
    first, renamed = folder / 'split_001.pdf', folder / 'custom.pdf'
    first.write_bytes(b'first'); renamed.write_bytes(b'second')
    choices = iter(['rename', 'number'])
    monkeypatch.setattr(dlg, '_ask_collision', lambda *a: next(choices))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(renamed), ''))
    dlg.split(source)
    assert first.read_bytes() == b'first'
    assert renamed.read_bytes() == b'second'
    assert (folder / 'custom_2.pdf').exists()


def test_per_page_mode_also_protected(split_env, monkeypatch):
    dlg, source, folder, _ = split_env
    dlg._mode_cb.setCurrentIndex(0)
    path = folder / 'page_0001.pdf'; path.write_bytes(b'keep')
    monkeypatch.setattr(dlg, '_ask_collision', lambda *a: 'number')
    dlg.split(source)
    assert path.read_bytes() == b'keep'
    with fitz.open(folder / 'page_0001_2.pdf') as doc:
        assert doc.page_count == 1


def test_late_collision_cannot_overwrite(split_env):
    dlg, source, folder, _ = split_env
    path = folder / 'late.pdf'
    assert dlg._choose_output(path, set(), '') == (path, False)
    path.write_bytes(b'arrived after planning')
    with pytest.raises(FileExistsError):
        dlg._save_output(source, path, False)
    assert path.read_bytes() == b'arrived after planning'
    assert not list(folder.glob('.pdf-split-*'))


def test_failed_render_keeps_existing_pdf(split_env):
    dlg, _, folder, _ = split_env
    path = folder / 'keep.pdf'; path.write_bytes(b'original')
    class Broken:
        def save(self, path):
            Path(path).write_bytes(b'incomplete')
            raise OSError('disk error')
    with pytest.raises(OSError):
        dlg._save_output(Broken(), path, True)
    assert path.read_bytes() == b'original'
    assert not list(folder.glob('.pdf-split-*'))


def test_source_cannot_be_overwritten(split_env, monkeypatch):
    dlg, _, folder, _ = split_env
    path = folder / 'source.pdf'; path.write_bytes(b'original')
    def choose(path, allowed):
        assert not allowed
        return 'number'
    monkeypatch.setattr(dlg, '_ask_collision', choose)
    assert dlg._choose_output(path, set(), str(path)) == (folder / 'source_2.pdf', False)


@pytest.mark.parametrize('ranges', ['', '0', '4', '3-1', 'a', '1,,2'])
def test_bad_ranges_do_not_create_files(split_env, ranges):
    dlg, source, folder, messages = split_env
    dlg._range_ed.setText(ranges)
    dlg.split(source)
    assert messages[0][0] == 'warning'
    assert not list(folder.iterdir())


def test_filesystem_without_hard_links(split_env, monkeypatch):
    dlg, source, folder, _ = split_env
    def unsupported(*a):
        raise OSError('hard links unsupported')
    monkeypatch.setattr('ui.dialogs.split_pdf_dialog.os.link', unsupported)
    path = folder / 'usb.pdf'
    dlg._save_output(source, path, False)
    with fitz.open(path) as doc:
        assert doc.page_count == 3
    with pytest.raises(FileExistsError):
        dlg._save_output(source, path, False)


@pytest.mark.parametrize('key,expected', [(Qt.Key.Key_Return, 'number'),
                                         (Qt.Key.Key_Escape, None)])
def test_real_collision_prompt_safe_default_and_escape(qapp, tmp_path, key, expected):
    dlg = SplitPdfDialog(1)
    observed = []
    def respond():
        box = qapp.activeModalWidget()
        observed.append(box.defaultButton().text())
        QTest.keyClick(box, key)
    QTimer.singleShot(50, respond)
    assert dlg._ask_collision(tmp_path / 'split_001.pdf', True) == expected
    assert observed == ['순번 붙여 저장']
