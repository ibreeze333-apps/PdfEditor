"""Exercise real save paths using shared, uncompressed image resources."""
import fitz
import pytest

from core.document import PdfDocument
from ui.dialogs.split_pdf_dialog import SplitPdfDialog, QFileDialog, QMessageBox
from ui.dialogs.merge_pdf_dialog import MergePdfDialog


@pytest.fixture
def image_pdf(tmp_path, monkeypatch, qapp):
    path = tmp_path / 'source.pdf'
    with fitz.open() as doc:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 600), False)
        pix.clear_with(180)
        for i in range(3):
            page = doc.new_page(width=300, height=300)
            page.insert_image(page.rect, pixmap=pix)
            page.insert_text((20, 20), f'Page {i + 1}')
        doc.save(path)
    for method in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, method, lambda *a: None)
    return path


def assert_preserved(source, output, indices):
    with fitz.open(source) as src, fitz.open(output) as out:
        assert out.page_count == len(indices)
        for page, index in zip(out, indices):
            assert page.get_text() == src[index].get_text()
            assert page.get_pixmap().samples == src[index].get_pixmap().samples
        assert output.stat().st_size < source.stat().st_size / 10


@pytest.mark.parametrize('per_page', [False, True])
def test_split_lossless_compression(image_pdf, tmp_path, monkeypatch, per_page):
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *a: str(tmp_path))
    dlg = SplitPdfDialog(3)
    dlg._mode_cb.setCurrentIndex(0 if per_page else 1)
    dlg._range_ed.setText('1-3')
    with fitz.open(image_pdf) as src:
        dlg.split(src)
    output = tmp_path / ('page_0001.pdf' if per_page else 'split_001.pdf')
    assert_preserved(image_pdf, output, [0] if per_page else [0, 1, 2])


def test_merge_lossless_compression(image_pdf, tmp_path, monkeypatch):
    output = tmp_path / 'merged.pdf'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(output), ''))
    dlg = MergePdfDialog()
    dlg._list.addItems([str(image_pdf), str(image_pdf)])
    dlg._merge()
    assert_preserved(image_pdf, output, [0, 1, 2, 0, 1, 2])


@pytest.mark.parametrize('method', ['save', 'save_copy'])
def test_document_lossless_compression(image_pdf, tmp_path, method):
    output = tmp_path / f'{method}.pdf'
    doc = PdfDocument()
    doc.open(str(image_pdf))
    try:
        getattr(doc, method)(str(output))
        assert_preserved(image_pdf, output, [0, 1, 2])
    finally:
        doc.close()


def test_split_already_compressed_shared_resources(image_pdf, tmp_path, monkeypatch):
    compressed = tmp_path / 'compressed.pdf'
    with fitz.open(image_pdf) as src:
        src.save(compressed, garbage=4, deflate=True)
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *a: str(tmp_path))
    dlg = SplitPdfDialog(3)
    dlg._mode_cb.setCurrentIndex(1)
    dlg._range_ed.setText('1-3')
    with fitz.open(compressed) as src:
        dlg.split(src)
    output = tmp_path / 'split_001.pdf'
    assert output.stat().st_size <= compressed.stat().st_size * 1.1
    assert_preserved(image_pdf, output, [0, 1, 2])
