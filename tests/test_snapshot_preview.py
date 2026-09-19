from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtTest import QTest
from ui.clipboard_panel import ClipboardPanel


def test_click_opens_full_resolution_and_view_reopens(qapp):
    panel = ClipboardPanel()
    image = QPixmap(1200, 800)
    image.fill(QColor('red'))
    image.setDevicePixelRatio(2)
    panel.add_snapshot(image)
    panel.resize(400, 500)
    panel.show()
    qapp.processEvents()
    item = panel._snapshot_list.item(0)
    QTest.mouseClick(panel._snapshot_list.viewport(), Qt.MouseButton.LeftButton,
                     pos=panel._snapshot_list.visualItemRect(item).center())
    qapp.processEvents()
    viewer = panel._preview
    assert viewer.isVisible() and not viewer.isModal()
    displayed = viewer._view.scene().items()[0].pixmap()
    assert displayed.width() == 1200 and displayed.height() == 800
    assert image.devicePixelRatio() == 2
    viewer.close()
    QTest.mouseClick(panel._btn_view, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert panel._preview is viewer and viewer.isVisible()
    viewer._view.original_size()
    assert viewer._view.transform().m11() == 1
    assert viewer._view.horizontalScrollBar().maximum() > 0
    viewer._view.fit_image()
    assert viewer._view.transform().m11() < 1
    for button in (panel._btn_view, panel._btn_region, panel._btn_save,
                   panel._btn_insert, panel._btn_compare):
        assert button.parentWidget().rect().contains(button.geometry())
    viewer.close(); panel.close()


def test_clicked_snapshot_is_used_even_with_multiple_selection(qapp):
    panel = ClipboardPanel()
    for colour in ('red', 'blue'):
        image = QPixmap(200, 100); image.fill(QColor(colour)); panel.add_snapshot(image)
    panel._snapshot_list.item(0).setSelected(True)
    item = panel._snapshot_list.item(1)
    panel._preview_item(item)
    pixel = panel._preview._view.scene().items()[0].pixmap().toImage().pixelColor(0, 0)
    assert pixel == QColor('red')
    restored = []
    panel.restore_image_requested.connect(restored.append)
    panel._restore_item(item)
    assert len(restored) == 1
    panel._preview.close(); panel.close()


def test_view_empty_shows_help(qapp, monkeypatch):
    panel = ClipboardPanel()
    messages = []
    monkeypatch.setattr('ui.clipboard_panel.QMessageBox.information',
                        lambda *args: messages.append(args[-1]))
    panel._on_view_snapshot()
    assert messages and panel._preview is None
