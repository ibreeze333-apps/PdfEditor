# utils/pdf_sign.py — 표준 인증서 기반 PDF 디지털 서명
"""pyHanko 를 이용한 PKCS#7(표준) 디지털 서명.

무거운 라이브러리(pyHanko/cryptography)는 모두 함수 안에서 지연 import 한다.
서명 기능을 실제로 쓸 때만 로딩되므로 앱 시작·평소 사용 속도에는 영향이 없다.
"""
from __future__ import annotations
import datetime
import logging
import tempfile
from utils.errlog import swallowed

logger = logging.getLogger('pdf_editor')


def generate_self_signed_p12(common_name: str, org: str, password: str,
                             days: int = 3650) -> bytes:
    """자체 서명 인증서 + 개인키를 PKCS#12(.p12/.pfx) 바이트로 생성."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, common_name or 'PDF Signer')]
    if org:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, org))
    name = x509.Name(attrs)
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True,
            key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=False, decipher_only=False), critical=True)
        .sign(key, hashes.SHA256())
    )
    enc = (serialization.BestAvailableEncryption(password.encode('utf-8'))
           if password else serialization.NoEncryption())
    return pkcs12.serialize_key_and_certificates(
        (common_name or 'signer').encode('utf-8'), key, cert, None, enc)


_XMP_STUB = (
    "<?xpacket begin=\"\xef\xbb\xbf\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>\n"
    "<x:xmpmeta xmlns:x='adobe:ns:meta/'>\n"
    " <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>\n"
    "  <rdf:Description rdf:about=''"
    " xmlns:pdf='http://ns.adobe.com/pdf/1.3/'/>\n"
    " </rdf:RDF>\n</x:xmpmeta>\n<?xpacket end='w'?>"
)


def _prepare_for_signing(in_path: str) -> str:
    """서명 전에 PDF를 pyHanko 가 다룰 수 있는 형태로 보정한다.

    - XMP 메타데이터(/Metadata)가 없으면 넣는다. 없으면 pyHanko 가 서명 도중
      root['/Metadata'] 에 그대로 접근해 KeyError('/Metadata') 로 실패한다.
    - hybrid xref(구형 호환 이중 상호참조)·손상된 xref 는 다시 저장하며 정리한다.
    보정이 필요 없으면 원본 경로를 그대로 반환하고, 필요하면 임시 파일 경로를
    반환한다(임시 파일은 OS 임시 폴더에 남으며 재부팅 시 정리된다)."""
    import os
    import tempfile
    try:
        import fitz
    except Exception:
        return in_path
    doc = None
    try:
        doc = fitz.open(in_path)
        if doc.needs_pass:            # 암호 문서는 호출부에서 이미 처리
            return in_path
        has_xmp = False
        try:
            has_xmp = bool(doc.xref_xml_metadata())
        except Exception:
            has_xmp = bool(doc.xref_get_key(doc.pdf_catalog(), 'Metadata')[0]
                           not in ('null', None))
        if has_xmp:
            return in_path
        doc.set_xml_metadata(_XMP_STUB)
        fd, tmp = tempfile.mkstemp(suffix='.pdf', prefix='sign_prep_')
        os.close(fd)
        # garbage=3 로 다시 쓰면 hybrid/손상 xref 도 정상 구조로 정리된다.
        doc.save(tmp, garbage=3, deflate=True)
        return tmp
    except Exception:
        return in_path
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                swallowed()


def verify_pdf_signatures(path: str) -> list[dict]:
    """PDF 안의 디지털 서명을 검사해 결과 목록을 돌려준다.

    각 항목: {
      'field'      : 서명 필드 이름
      'signer'     : 서명자 이름(인증서 CN)
      'organization': 서명자 소속(인증서 O / OU)
      'issuer'     : 발급자 이름
      'self_signed': 자체 서명 인증서인가
      'reason'/'location' : 서명 사유·위치
      'when'       : 서명 시각(문자열)
      'intact'     : 서명 이후 내용이 그대로인가 (위변조 없음)
      'covers_all' : 문서 전체를 보호하는가
      'modified'   : 서명 이후 변경 요약(없으면 '')
      'trusted'    : 인증서 신뢰 사슬 검증 통과 여부
      'error'      : 검사 실패 사유(있을 때만)
    }
    서명이 없으면 빈 목록.
    """
    from pyhanko.pdf_utils.reader import PdfFileReader

    out: list[dict] = []
    with open(path, 'rb') as fh:
        reader = PdfFileReader(fh, strict=False)
        try:
            sigs = list(reader.embedded_signatures)
        except Exception:
            sigs = []
        for sig in sigs:
            item = {'field': getattr(sig, 'field_name', '') or '',
                    'signer': '', 'organization': '', 'issuer': '',
                    'self_signed': False,
                    'reason': '', 'location': '', 'when': '',
                    'intact': False, 'covers_all': False,
                    'modified': '', 'trusted': False, 'error': '', 'trust_warning': ''}
            try:
                cert = sig.signer_cert
                item['signer'] = (cert.subject.native.get('common_name')
                                  or cert.subject.native.get('organization_name') or '')
                item['organization'] = (cert.subject.native.get('organization_name')
                                        or cert.subject.native.get('organizational_unit_name') or '')
                item['issuer'] = (cert.issuer.native.get('common_name')
                                  or cert.issuer.native.get('organization_name') or '')
                item['self_signed'] = (cert.subject.native == cert.issuer.native)
            except Exception:
                swallowed()
            try:
                so = sig.sig_object
                item['reason'] = str(so.get('/Reason') or '')
                item['location'] = str(so.get('/Location') or '')
                item['when'] = _fmt_pdf_date(str(so.get('/M') or ''))
            except Exception:
                swallowed()
            try:
                sig.compute_integrity_info()
                item['covers_all'] = (str(sig.coverage).endswith('ENTIRE_FILE'))
            except Exception:
                swallowed()
            # 서명값 자체(해시·서명) 검증 — 신뢰 사슬은 별도로 본다.
            # 자체 서명 인증서면 신뢰 검증이 반드시 실패하며 라이브러리가 예외
            # 로그를 남기므로, 그 구간 로깅을 잠시 낮춘다.
            import logging as _lg
            _quiet = [_lg.getLogger(n) for n in
                      ('pyhanko', 'pyhanko_certvalidator',
                       'pyhanko.sign.diff_analysis',
                       'pyhanko.sign.diff_analysis.policies')]
            _prev_levels = [(g, g.level) for g in _quiet]
            for g in _quiet:
                g.setLevel(_lg.CRITICAL)
            # pyHanko 는 진단 내용을 traceback 으로 stderr 에 직접 찍기도 한다.
            # 검사 중에는 콘솔이 지저분해지지 않게 잠시 돌려 둔다.
            import contextlib as _ctx
            import io as _io
            _null = _io.StringIO()
            try:
                from pyhanko.sign.validation import validate_pdf_signature
                from pyhanko_certvalidator import ValidationContext
                try:
                    context = ValidationContext(allow_fetching=False)
                except OSError:
                    # A locked-down Windows certificate store must not prevent
                    # cryptographic validation. No roots means no claimed trust.
                    context = ValidationContext(trust_roots=[], allow_fetching=False)
                    item['trust_warning'] = 'Windows 인증서 저장소에 접근하지 못해 인증서 신뢰 여부는 확인하지 못했습니다.'
                with _ctx.redirect_stderr(_null):
                    status = validate_pdf_signature(sig, context)
                item['intact'] = bool(status.intact and status.valid)
                item['trusted'] = bool(getattr(status, 'trusted', False))
                mods = getattr(status, 'modification_level', None)
                if mods is not None and not str(mods).endswith('NONE'):
                    item['modified'] = str(mods).rsplit('.', 1)[-1]
            except Exception as exc:
                # Failed validation is unknown, never a digest-only success.
                item['trusted'] = False
                item['intact'] = False
                item['error'] = str(exc)[:120]
            finally:
                for g, lvl in _prev_levels:
                    g.setLevel(lvl)
            out.append(item)
    return out


def _fmt_pdf_date(raw: str) -> str:
    """PDF 날짜(D:YYYYMMDDHHmmSS+09'00') → '2026-07-26 09:02' 로."""
    s = (raw or '').strip()
    if s.startswith('D:'):
        s = s[2:]
    if len(s) < 14 or not s[:14].isdigit():
        return raw or ''
    return (f'{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}')


def _build_stamp_pdf(width: float, height: float, lines: list[str],
                     opacity: float) -> str:
    """서명 도장 겉모습을 담은 1페이지 PDF를 만들어 경로를 돌려준다.

    pyHanko 기본 도장은 크기·투명도를 조절할 수 없어서, 도장 그림을 직접
    그린 뒤 StaticStampStyle 로 넘긴다. 투명도를 낮추면 도장 밑의 본문이
    비쳐 보인다.
    """
    import tempfile
    import fitz as _fitz

    op = max(0.05, min(1.0, float(opacity)))
    doc = _fitz.open()
    page = doc.new_page(width=width, height=height)
    box = _fitz.Rect(0, 0, width, height)
    ink = (0.15, 0.25, 0.6)
    page.draw_rect(box + (0.8, 0.8, -0.8, -0.8), color=ink, width=1.2,
                   stroke_opacity=op, radius=0.08)

    body = [ln for ln in lines if ln]
    if body:
        # 줄 수에 맞춰 글자 크기를 정하고, 넘치면 들어갈 때까지 줄인다.
        fs = max(5.0, min(11.0, (height - 8.0) / max(1, len(body)) * 0.72))
        inner = box + (5, 4, -5, -4)
        text = '\n'.join(body)
        korean = any(0xAC00 <= ord(c) <= 0xD7A3 for c in text)
        fontname = 'korea' if korean else 'helv'
        for _ in range(8):
            rc = page.insert_textbox(inner, text, fontname=fontname, fontsize=fs,
                                     color=ink, align=_fitz.TEXT_ALIGN_LEFT,
                                     stroke_opacity=op, fill_opacity=op)
            if rc >= 0:
                break
            fs *= 0.85
            if fs < 4.0:
                break

    tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    tmp.close()
    doc.save(tmp.name, garbage=4, deflate=True,
             deflate_images=True, deflate_fonts=True)
    doc.close()
    return tmp.name


def sign_pdf(in_path: str, out_path: str, p12_path: str, passphrase: str,
             reason: str = '', location: str = '', contact: str = '',
             field_name: str = 'Signature1',
             visible_box=None, page: int = 0, page_height: float = 0.0,
             stamp_opacity: float = 1.0, signer_label: str = '') -> None:
    """PKCS#12 인증서로 PDF에 표준 디지털 서명을 넣어 out_path 로 저장.

    visible_box: (x0, y0, x1, y1) — fitz 좌표(좌상단 원점, pt). None 이면
    보이지 않는 서명(문서 전체 무결성만 보장).
    page_height: visible_box 사용 시 해당 페이지 높이(pt) — 좌표 변환용.
    stamp_opacity: 보이는 도장의 불투명도(0.1~1.0). 1 미만이면 도장 겉모습을
    직접 그려 넣는다 — 본문을 가리지 않게 하기 위함.
    signer_label: 도장에 적을 서명자 이름(비우면 인증서 CN 을 쓴다).
    """
    import datetime
    import os as _os

    from pyhanko.sign import signers, fields
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    signer = signers.SimpleSigner.load_pkcs12(
        pfx_file=p12_path,
        passphrase=(passphrase.encode('utf-8') if passphrase else None))
    if signer is None:
        raise ValueError('인증서를 불러오지 못했습니다. 암호를 확인하세요.')

    original_input = in_path
    in_path = _prepare_for_signing(in_path)
    stamp_pdf = ''
    temporary_output = ''

    try:
        with open(in_path, 'rb') as inf:
            w = IncrementalPdfFileWriter(inf, strict=False)

            visible = visible_box is not None and page_height > 0
            if visible:
                # fitz(top-left) → PDF(bottom-left) 좌표 변환
                x0, y0, x1, y1 = visible_box
                pdf_box = (x0, page_height - y1, x1, page_height - y0)
                fields.append_signature_field(
                    w, fields.SigFieldSpec(sig_field_name=field_name,
                                           on_page=page, box=pdf_box))

            meta = signers.PdfSignatureMetadata(
                field_name=field_name,
                reason=reason or None,
                location=location or None,
                contact_info=contact or None,
            )

            stamp_style = None
            if visible:
                # 투명도와 무관하게 도장을 직접 그린다 — pyHanko 기본 도장은
                # 크기·투명도를 조절할 수 없고 한글도 나오지 않는다.
                name = signer_label
                if not name:
                    try:
                        name = (signer.signing_cert.subject.native
                                .get('common_name') or '')
                    except Exception:
                        name = ''
                lines = ['디지털 서명']
                if name:
                    lines.append(name)
                lines.append(datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))
                if reason:
                    lines.append(f'사유: {reason}')
                if location:
                    lines.append(f'위치: {location}')
                try:
                    from pyhanko.stamp import StaticStampStyle
                    stamp_pdf = _build_stamp_pdf(
                        abs(pdf_box[2] - pdf_box[0]),
                        abs(pdf_box[3] - pdf_box[1]),
                        lines, stamp_opacity)
                    # 기본 테두리(검은 3pt)는 우리가 그린 반투명 테두리를
                    # 덮어 불투명한 검은 상자로 보이게 한다 — 끈다.
                    stamp_style = StaticStampStyle.from_pdf_file(
                        stamp_pdf, border_width=0)
                except Exception:
                    logger.exception('[pdf_sign] 반투명 도장 생성 실패 — 기본 도장 사용')
                    stamp_style = None

            fd, temporary_output = tempfile.mkstemp(
                prefix='.signed-', suffix='.pdf', dir=_os.path.dirname(_os.path.abspath(out_path)))
            with _os.fdopen(fd, 'wb') as outf:
                if stamp_style is not None:
                    pdf_signer = signers.PdfSigner(meta, signer=signer,
                                                   stamp_style=stamp_style)
                    pdf_signer.sign_pdf(w, output=outf)
                else:
                    signers.sign_pdf(w, meta, signer=signer, output=outf)
        # Release the input handle first, including when signing in place.
        _os.replace(temporary_output, out_path)
        temporary_output = ''
    finally:
        for temporary in (stamp_pdf, temporary_output,
                          in_path if in_path != original_input else ''):
            if not temporary:
                continue
            try:
                _os.unlink(temporary)
            except OSError:
                swallowed()


# ── 인증서 배포용 내보내기 / Windows 저장소 설치 ─────────────────────────
# 자체 서명 인증서로 서명한 PDF 는 받는 쪽에서 "신뢰할 수 없는 서명"으로
# 뜬다. 상대가 우리 인증서를 신뢰 목록에 넣어야 유효로 바뀌는데, 그때
# 필요한 건 개인키가 빠진 '공개 인증서'다. .p12 를 그대로 건네면 개인키까지
# 넘어가므로 절대 그러면 안 된다.

def export_public_cert(p12_path: str, password: str, out_path: str) -> str:
    """.p12/.pfx 에서 공개 인증서만 뽑아 저장한다.

    확장자로 형식을 정한다.
      .cer / .der  — DER 인증서 한 장
      .crt / .pem  — PEM 인증서 한 장
      .p7b / .p7c  — PKCS#7 인증서 묶음(체인 포함). 알PDF·Acrobat 의
                     '인증서 관리'가 받는 형식.
    반환값은 실제로 쓴 경로.
    """
    import os
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12, pkcs7

    with open(p12_path, 'rb') as f:
        blob = f.read()
    pw = password.encode('utf-8') if password else None
    key, cert, extra = pkcs12.load_key_and_certificates(blob, pw)
    if cert is None:
        raise ValueError('인증서를 읽지 못했습니다 (암호가 맞는지 확인하세요).')

    ext = os.path.splitext(out_path)[1].lower()
    if ext in ('.p7b', '.p7c'):
        chain = [cert] + list(extra or [])
        # .p7b 는 Base64(PEM) 로 배포하는 게 관례라 그대로 따른다.
        data = pkcs7.serialize_certificates(chain, serialization.Encoding.PEM)
    elif ext in ('.crt', '.pem'):
        data = cert.public_bytes(serialization.Encoding.PEM)
    else:
        data = cert.public_bytes(serialization.Encoding.DER)
    with open(out_path, 'wb') as f:
        f.write(data)
    return out_path


def install_p12_to_windows_store(p12_path: str, password: str) -> None:
    """.p12 를 현재 사용자의 '개인' 인증서 저장소에 넣는다.

    알PDF·Acrobat·한컴 등은 서명용 ID 를 파일이 아니라 Windows 인증서
    저장소에서 가져온다. 여기에 넣어야 그 프로그램들의 '디지털 ID 목록'에
    우리 인증서가 보인다.

    실패하면 예외를 올린다(호출 쪽에서 안내만 하고 서명은 계속 진행하면 된다).
    """
    import os
    import subprocess
    if os.name != 'nt':
        raise RuntimeError('Windows 에서만 쓸 수 있습니다.')

    # 경로·암호를 명령 문자열에 끼워 넣으면 따옴표나 '$' 가 든 값에서 깨진다.
    # 둘 다 환경 변수로 넘겨 이스케이프 문제를 아예 없앤다.
    env = dict(os.environ)
    env['PDFED_P12_PW'] = password or ''
    env['PDFED_P12_PATH'] = os.path.abspath(p12_path)
    script = (
        r"$ErrorActionPreference='Stop';"
        r"$pw = ConvertTo-SecureString -String $env:PDFED_P12_PW"
        r" -AsPlainText -Force;"
        r"Import-PfxCertificate -FilePath $env:PDFED_P12_PATH"
        r" -CertStoreLocation Cert:\CurrentUser\My -Password $pw"
        r" | Out-Null"
    )
    proc = subprocess.run(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True, text=True, env=env,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or '').strip()
                           or 'Import-PfxCertificate 실패')
