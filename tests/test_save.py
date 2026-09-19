# tests/test_save.py — 저장 회귀 테스트
"""저장이 깨지면 사용자 문서가 날아간다. 가장 먼저 지켜야 할 것.

여기 있는 테스트는 대부분 과거에 실제로 났던 사고를 다시 못 나게 막는 것이다.
함수 이름은 ASCII 로 둔다 — Windows 콘솔(cp949)에서 한글 이름이 깨져 나와
어느 테스트가 실패했는지 못 읽는다. 무엇을 지키는지는 docstring 에 적는다.
"""
from __future__ import annotations
import os
from pathlib import Path

import fitz
import pytest

from tests.conftest import make_pdf


def _pages_and_text(path: str) -> tuple[int, str]:
    d = fitz.open(path)
    try:
        return d.page_count, '\n'.join(p.get_text() for p in d)
    finally:
        d.close()


def test_save_copy_keeps_content(doc, tmp_path):
    """다른 이름으로 저장해도 페이지 수와 본문이 그대로여야 한다."""
    out = tmp_path / 'copy.pdf'
    doc.save_copy(str(out))
    assert out.exists()
    pages, text = _pages_and_text(str(out))
    assert pages == doc.page_count() == 3
    assert 'Sample body 1' in text
    assert 'Sample body 3' in text


def test_doc_usable_after_inplace_save(doc):
    """제자리 저장 뒤에도 열린 문서를 계속 쓸 수 있어야 한다.

    저장하면서 원본 핸들을 놓고 메모리 사본으로 갈아타는데, 여기가
    어긋나면 저장 직후 페이지 접근이 깨진다.
    """
    doc.save()
    assert doc.page_count() == 3
    assert 'Sample body 2' in doc.fitz_page(1).get_text()
    assert doc.dirty is False


def test_saved_file_not_empty(doc, tmp_path):
    """내용이 빈 파일로 덮여 저장되던 사고 방지 (_verify_saved_file)."""
    out = tmp_path / 'notempty.pdf'
    doc.save_copy(str(out))
    assert out.stat().st_size > 500


def test_failed_save_keeps_original(doc, tmp_path, monkeypatch):
    """임시본 검증에 걸리면 예외를 내고 원본 파일은 그대로여야 한다."""
    original = Path(doc.path)
    before = original.read_bytes()

    def boom(tmp, expected_pages):
        raise RuntimeError('검증 실패 (테스트)')

    monkeypatch.setattr(type(doc), '_verify_saved_file', staticmethod(boom))
    with pytest.raises(RuntimeError):
        doc.save()
    assert original.read_bytes() == before, '저장 실패인데 원본이 바뀌었다'
    leftovers = list(original.parent.glob('*.saving.tmp'))
    assert not leftovers, f'망가진 임시본이 남았다: {leftovers}'


def test_repeated_save_does_not_grow_file(qapp, tmp_path):
    """반복 저장으로 파일이 부풀지 않아야 한다.

    글꼴 서브셋이 저장할 때마다 폰트를 다시 심어 파일이 6배가 되던 문제
    (커밋 0db49a1) 회귀 방지.
    """
    from core.document import PdfDocument
    src = make_pdf(tmp_path / 'grow.pdf', pages=2)
    d = PdfDocument()
    assert d.open(src)
    try:
        d.save()
        first = os.path.getsize(src)
        for _ in range(3):
            d.mark_dirty()
            d.save()
        last = os.path.getsize(src)
    finally:
        d.close()
    assert last <= first * 1.5, f'저장을 반복하니 {first} → {last} 바이트로 커졌다'


def test_rotation_persists(doc, tmp_path):
    """페이지 회전이 저장본에 반영되고, 다른 페이지는 안 건드려야 한다."""
    doc.rotate_page(0, 90)
    out = tmp_path / 'rot.pdf'
    doc.save_copy(str(out))
    d = fitz.open(str(out))
    try:
        assert d[0].rotation == 90
        assert d[1].rotation == 0
    finally:
        d.close()


def test_page_delete_persists(doc, tmp_path):
    """페이지 삭제가 저장본에 반영돼야 한다."""
    doc.delete_page(1)
    out = tmp_path / 'del.pdf'
    doc.save_copy(str(out))
    pages, text = _pages_and_text(str(out))
    assert pages == 2
    assert 'Sample body 2' not in text
