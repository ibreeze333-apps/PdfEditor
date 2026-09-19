# utils/secure_store.py — Windows DPAPI 기반 비밀값 암호화
"""API 키 등 비밀값을 Windows DPAPI 로 암호화/복호화한다.

DPAPI(CryptProtectData)는 현재 로그인한 Windows 사용자 계정 키로
암호화하므로:
  - 설정 파일을 통째로 복사해 가도 다른 PC/다른 계정에서는 복호화 불가
  - 마스터 비밀번호를 따로 관리할 필요 없음 (Chrome 비밀번호 저장과 동일 방식)

표준 라이브러리(ctypes)만 사용 — 추가 의존성 없음.
Windows 가 아니거나 DPAPI 호출이 실패하면 None 을 반환해
호출부가 평문 저장으로 폴백할 수 있게 한다 (앱은 Windows 전용).
"""
from __future__ import annotations

import base64
import logging
import sys

logger = logging.getLogger('pdf_editor')

# 암호화된 값임을 표시하는 접두사 (설정 JSON 안에서 구분용)
ENC_PREFIX = 'dpapi:'


def _dpapi_call(data: bytes, protect: bool) -> bytes | None:
    """CryptProtectData / CryptUnprotectData 호출. 실패 시 None."""
    if sys.platform != 'win32':
        return None
    import ctypes
    import ctypes.wintypes as wt

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wt.DWORD),
                    ('pbData', ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    blob_in = DATA_BLOB(len(data), ctypes.cast(
        ctypes.create_string_buffer(data, len(data)),
        ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()

    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect(secret: str) -> str:
    """비밀값을 암호화해 'dpapi:<base64>' 형태로 반환.

    DPAPI 를 쓸 수 없으면 평문을 그대로 반환한다 (호출부 동작 유지).
    """
    if not secret:
        return ''
    raw = _dpapi_call(secret.encode('utf-8'), protect=True)
    if raw is None:
        logger.warning('[secure_store] DPAPI 사용 불가 — 평문으로 저장됩니다.')
        return secret
    return ENC_PREFIX + base64.b64encode(raw).decode('ascii')


def unprotect(value: str) -> str:
    """저장된 값을 복호화한다.

    - 'dpapi:' 접두사가 있으면 DPAPI 복호화 (실패 시 빈 문자열 + 경고)
    - 접두사가 없으면 과거 평문 저장분 — 그대로 반환 (다음 저장 때 암호화됨)
    """
    if not value:
        return ''
    if not value.startswith(ENC_PREFIX):
        return value   # 레거시 평문 — 마이그레이션은 다음 save() 에서
    try:
        raw = base64.b64decode(value[len(ENC_PREFIX):])
    except Exception:
        logger.warning('[secure_store] 암호화 값 형식 오류 — 키를 다시 입력하세요.')
        return ''
    out = _dpapi_call(raw, protect=False)
    if out is None:
        logger.warning(
            '[secure_store] API 키 복호화 실패 — 다른 PC/계정에서 복사된 '
            '설정이거나 값이 손상됐습니다. 키를 다시 입력하세요.')
        return ''
    try:
        return out.decode('utf-8')
    except UnicodeDecodeError:
        return ''
