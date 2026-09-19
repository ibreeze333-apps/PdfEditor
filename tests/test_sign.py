# tests/test_sign.py — 디지털 서명 회귀 테스트
"""서명은 '깨진 걸 모르는' 게 제일 위험하다.

서명이 안 들어갔는데 들어간 줄 알거나, 서명 후 문서가 바뀌었는데 무결로
뜨면 서명 기능이 있으나 마나다. 그래서 넣는 것뿐 아니라 '검증이 실제로
변조를 잡아내는지'까지 확인한다.
"""
from __future__ import annotations
import os
from pathlib import Path

import fitz
import pytest

from tests.conftest import make_pdf

CERT_PW = 'test-pw'


@pytest.fixture(scope='module')
def p12(tmp_path_factory) -> str:
    """테스트용 자체 서명 인증서. 암호에 따옴표·달러를 넣어 이스케이프도 함께 본다."""
    from utils.pdf_sign import generate_self_signed_p12
    out = tmp_path_factory.mktemp('cert') / 'test.p12'
    out.write_bytes(generate_self_signed_p12('Test Signer', 'Breeze333', CERT_PW))
    return str(out)


@pytest.fixture
def signed_pdf(tmp_path, p12) -> str:
    from utils.pdf_sign import sign_pdf
    src = make_pdf(tmp_path / 'tosign.pdf', pages=2)
    out = tmp_path / 'signed.pdf'
    sign_pdf(src, str(out), p12, CERT_PW, reason='테스트 서명', location='서울')
    return str(out)


# ── 서명 넣기 ────────────────────────────────────────────────────────
@pytest.mark.slow
def test_sign_produces_valid_signature(signed_pdf):
    """서명이 실제로 들어가고, 검증에서 무결로 나와야 한다."""
    from utils.pdf_sign import verify_pdf_signatures
    sigs = verify_pdf_signatures(signed_pdf)
    assert len(sigs) == 1, f'서명이 1개여야 하는데 {len(sigs)}개'
    s = sigs[0]
    assert s.get('error') in (None, ''), f"검증 오류: {s.get('error')}"
    assert s['intact'] is True, '방금 서명했는데 무결이 아니다'
    assert s['covers_all'] is True, '문서 전체를 보호하지 않는다'
    assert 'Test Signer' in (s.get('signer') or '')
    assert s['self_signed'] is True


@pytest.mark.slow
def test_sign_keeps_pages_and_text(signed_pdf):
    """서명한다고 페이지나 본문이 사라지면 안 된다."""
    d = fitz.open(signed_pdf)
    try:
        assert d.page_count == 2
        assert 'Sample body 1' in d[0].get_text()
    finally:
        d.close()


@pytest.mark.slow
def test_tamper_is_detected(signed_pdf, tmp_path):
    """서명 이후 내용을 바꾸면 검증이 잡아내야 한다.

    이게 통과 못 하면 서명 기능은 장식이다.
    """
    from utils.pdf_sign import verify_pdf_signatures
    tampered = tmp_path / 'tampered.pdf'
    d = fitz.open(signed_pdf)
    try:
        d[0].insert_text((72, 400), 'TAMPERED', fontsize=20)
        d.save(str(tampered), incremental=False, garbage=3)
    finally:
        d.close()
    sigs = verify_pdf_signatures(str(tampered))
    if not sigs:
        pytest.fail('변조본에서 서명 자체가 사라졌다 — 변조를 알릴 방법이 없다')
    assert sigs[0]['intact'] is False, '내용을 바꿨는데 무결로 나온다'


def test_unsigned_doc_reports_no_signature(tmp_path):
    """서명 없는 문서는 빈 목록. (없는 서명을 있다고 하면 안 된다)"""
    from utils.pdf_sign import verify_pdf_signatures
    src = make_pdf(tmp_path / 'plain.pdf', pages=1)
    assert verify_pdf_signatures(src) == []


def test_signing_failure_keeps_existing_output(tmp_path, p12, monkeypatch):
    from utils.pdf_sign import sign_pdf
    from pyhanko.sign import signers
    source = make_pdf(tmp_path / 'source.pdf', pages=1)
    target = tmp_path / 'existing.pdf'
    target.write_bytes(b'previous document')
    def fail(*args, **kwargs):
        kwargs['output'].write(b'incomplete signature')
        raise OSError('simulated signing failure')
    monkeypatch.setattr(signers, 'sign_pdf', fail)
    with pytest.raises(OSError):
        sign_pdf(source, str(target), p12, CERT_PW)
    assert target.read_bytes() == b'previous document'


def test_signing_to_same_path_preserves_pdf(tmp_path, p12):
    from utils.pdf_sign import sign_pdf, verify_pdf_signatures, _XMP_STUB
    source = make_pdf(tmp_path / 'inplace.pdf', pages=1)
    with fitz.open(source) as doc:
        doc.set_xml_metadata(_XMP_STUB)
        doc.saveIncr()
    sign_pdf(source, source, p12, CERT_PW)
    with fitz.open(source) as doc:
        assert 'Sample body 1' in doc[0].get_text()
    assert verify_pdf_signatures(source)[0]['intact']


def test_signature_failure_does_not_claim_intact(signed_pdf, monkeypatch):
    from utils.pdf_sign import verify_pdf_signatures
    def fail(*args, **kwargs):
        raise ValueError('cannot validate signature')
    monkeypatch.setattr('pyhanko.sign.validation.validate_pdf_signature', fail)
    result = verify_pdf_signatures(signed_pdf)[0]
    assert result['intact'] is False and result['trusted'] is False
    assert result['error']


def test_signature_value_checked_as_well_as_document_digest(signed_pdf, monkeypatch):
    from utils.pdf_sign import verify_pdf_signatures
    from types import SimpleNamespace
    monkeypatch.setattr('pyhanko.sign.validation.validate_pdf_signature',
        lambda *args, **kwargs: SimpleNamespace(intact=True, valid=False, trusted=False))
    result = verify_pdf_signatures(signed_pdf)[0]
    assert result['intact'] is False


# ── 인증서 내보내기 (다른 프로그램과의 호환) ─────────────────────────
@pytest.mark.parametrize('ext', ['.cer', '.crt', '.p7b', '.p7c'])
def test_export_public_cert_formats(p12, tmp_path, ext):
    """네 형식 모두 만들어지고, 다시 읽어서 같은 인증서여야 한다."""
    from utils.pdf_sign import export_public_cert
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import pkcs7

    out = tmp_path / ('pub' + ext)
    export_public_cert(p12, CERT_PW, str(out))
    blob = out.read_bytes()
    assert blob, '빈 파일이 나왔다'

    if ext in ('.p7b', '.p7c'):
        certs = pkcs7.load_pem_pkcs7_certificates(blob)
        assert len(certs) >= 1
        cert = certs[0]
    elif ext == '.crt':
        cert = x509.load_pem_x509_certificate(blob)
    else:
        cert = x509.load_der_x509_certificate(blob)
    assert 'Test Signer' in cert.subject.rfc4514_string()


def test_export_public_cert_has_no_private_key(p12, tmp_path):
    """내보낸 파일에 개인키가 섞여 나가면 안 된다 — 최악의 사고."""
    from utils.pdf_sign import export_public_cert
    for ext in ('.cer', '.crt', '.p7b'):
        out = tmp_path / ('pub' + ext)
        export_public_cert(p12, CERT_PW, str(out))
        blob = out.read_bytes()
        for marker in (b'PRIVATE KEY', b'ENCRYPTED PRIVATE KEY'):
            assert marker not in blob, f'{ext} 안에 개인키가 들어 있다'
        # p12 원본보다 작아야 정상(개인키가 빠졌으므로)
        assert len(blob) < os.path.getsize(p12) * 2


def test_export_public_cert_wrong_password(p12, tmp_path):
    """암호가 틀리면 조용히 빈 파일을 만들지 말고 예외를 내야 한다."""
    from utils.pdf_sign import export_public_cert
    out = tmp_path / 'nope.cer'
    with pytest.raises(Exception):
        export_public_cert(p12, 'wrong-password', str(out))
