# tests/test_encryption.py — 암호 / 권한 회귀 테스트
"""여기가 깨지면 문서 보호가 통째로 우회된다.

핵심 규칙:
  - 열람 암호로 연 문서는 소유자가 아니다 → 저장·내보내기를 막아야 한다.
    (안 막으면 암호·권한이 없는 사본을 만들어 제한을 전부 푸는 셈)
  - 관리자 암호로 열면 소유자다 → 막지 않는다.
커밋 c42b4b7 회귀 방지.
"""
from __future__ import annotations

import fitz
import pytest

from tests.conftest import make_pdf


USER_PW = 'user-pw'
OWNER_PW = 'owner-pw'
# 인쇄만 허용하고 나머지는 막은 문서
PERMS = int(fitz.PDF_PERM_PRINT)


@pytest.fixture
def encrypted_pdf(tmp_path) -> str:
    """열람 암호 + 관리자 암호 + 권한 제한이 걸린 PDF."""
    src = make_pdf(tmp_path / 'plain.pdf', pages=2)
    out = tmp_path / 'enc.pdf'
    d = fitz.open(src)
    try:
        d.save(str(out), encryption=fitz.PDF_ENCRYPT_AES_256,
               owner_pw=OWNER_PW, user_pw=USER_PW, permissions=PERMS)
    finally:
        d.close()
    return str(out)


def _open(path: str, pw: str = ''):
    from core.document import PdfDocument
    d = PdfDocument()
    ok = d.open(path, pw)
    return d, ok


def test_wrong_password_is_rejected(qapp, encrypted_pdf):
    """틀린 암호로는 열리면 안 되고, 암호가 필요하다고 알려야 한다."""
    d, ok = _open(encrypted_pdf, 'nope')
    try:
        assert ok is False
        assert d.needs_password is True
        assert d.is_open is False
    finally:
        d.close()


def test_no_password_is_rejected(qapp, encrypted_pdf):
    """암호 없이 열려서는 안 된다."""
    d, ok = _open(encrypted_pdf)
    try:
        assert ok is False
        assert d.needs_password is True
    finally:
        d.close()


def test_user_password_is_not_owner(qapp, encrypted_pdf):
    """열람 암호로 열면 소유자가 아니다 — 저장·내보내기 차단의 근거."""
    d, ok = _open(encrypted_pdf, USER_PW)
    try:
        assert ok is True
        assert d.was_encrypted is True
        assert d.opened_as_owner is False, \
            '열람 암호로 열었는데 소유자로 판정됐다 — 권한 우회가 열린다'
    finally:
        d.close()


def test_owner_password_is_owner(qapp, encrypted_pdf):
    """관리자 암호로 열면 소유자다 — 막지 않아야 한다."""
    d, ok = _open(encrypted_pdf, OWNER_PW)
    try:
        assert ok is True
        assert d.was_encrypted is True
        assert d.opened_as_owner is True
    finally:
        d.close()


def test_plain_doc_is_always_owner(doc):
    """암호가 없는 문서는 항상 소유자 — 멀쩡한 문서 저장을 막으면 안 된다."""
    assert doc.was_encrypted is False
    assert doc.opened_as_owner is True


def test_permissions_restricted_for_user(qapp, encrypted_pdf):
    """열람 암호로 열면 문서에 걸린 권한 비트만 유효해야 한다."""
    d, ok = _open(encrypted_pdf, USER_PW)
    try:
        assert ok is True
        assert d.can(fitz.PDF_PERM_PRINT) is True
        assert d.can(fitz.PDF_PERM_COPY) is False, '금지한 복사가 허용됐다'
        assert d.can(fitz.PDF_PERM_MODIFY) is False, '금지한 편집이 허용됐다'
    finally:
        d.close()


def test_encrypted_copy_still_needs_password(qapp, tmp_path):
    """암호화 사본을 만들면 그 사본도 암호를 요구해야 한다.

    (암호화 저장이 조용히 실패해 무방비 파일이 나오는 사고 방지)
    """
    src = make_pdf(tmp_path / 'p.pdf', pages=1)
    out = tmp_path / 'e.pdf'
    d = fitz.open(src)
    try:
        d.save(str(out), encryption=fitz.PDF_ENCRYPT_AES_256,
               owner_pw=OWNER_PW, user_pw=USER_PW, permissions=PERMS)
    finally:
        d.close()
    check = fitz.open(str(out))
    try:
        assert bool(check.needs_pass) is True   # needs_pass 는 int(0/1) 이다
    finally:
        check.close()
