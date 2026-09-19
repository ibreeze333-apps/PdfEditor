# tests/conftest.py — 공통 픽스처
"""회귀 테스트 공통 준비.

GUI 를 띄우지 않고 돌린다(QT_QPA_PLATFORM=offscreen). PySide6 를 import 하는
모듈도 그대로 테스트할 수 있고, CI 나 원격 접속 환경에서도 돌아간다.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# PySide6 를 import 하기 전에 설정해야 한다.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz          # noqa: E402
import pytest        # noqa: E402


@pytest.fixture(scope='session')
def qapp():
    """QApplication 하나를 세션 내내 재사용한다(두 번 만들면 죽는다)."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def make_pdf(path: str | Path, pages: int = 3, text: str = 'Sample body') -> str:
    """테스트용 PDF 를 만든다. 페이지마다 번호가 들어가 순서를 확인할 수 있다.

    본문은 ASCII 로 쓴다 — 내장 기본 글꼴(Helvetica)에는 한글 글리프가 없어서
    한글을 넣으면 깨진 글자가 들어가고, 테스트가 글꼴 설치 여부에 좌우된다.
    """
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)      # A4
        page.insert_text((72, 100), f'{text} {i + 1}', fontsize=14)
        page.draw_rect(fitz.Rect(72, 200, 300, 300))
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def sample_pdf(tmp_path) -> str:
    return make_pdf(tmp_path / 'sample.pdf')


@pytest.fixture
def doc(qapp, sample_pdf):
    """열려 있는 PdfDocument. 테스트가 끝나면 닫는다."""
    from core.document import PdfDocument
    d = PdfDocument()
    assert d.open(sample_pdf), '테스트 PDF 를 열지 못했습니다'
    yield d
    d.close()
