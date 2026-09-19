# tests/test_file_type.py — 위장 파일 검사 회귀 테스트
"""확장자를 .pdf 로 바꾼 위험 파일이 실제로 차단되는지 확인한다.

이 테스트가 있는 이유: _DANGEROUS_LABELS 에 'bat', 'ps1', 'js', 'cmd',
'vbs' 처럼 그럴듯하지만 Magika 가 절대 내놓지 않는 라벨이 적혀 있었다.
목록은 있는데 아무것도 걸리지 않는 상태로 오래 있었고, 겉으로는 멀쩡해
보여서 아무도 몰랐다. 라벨 이름은 사람이 눈으로 검증할 수 없으니 테스트로 묶는다.
"""
from __future__ import annotations

import zipfile

import pytest

from utils.file_type import (
    _DANGEROUS_LABELS,
    FileCheckResult,
    _get_magika,
    check_mismatch,
    detect,
)

pytestmark = pytest.mark.skipif(
    _get_magika() is None,
    reason='Magika 미설치 — 위장 파일 검사가 비활성 상태',
)


def test_dangerous_labels_are_real_magika_labels():
    """차단 목록의 모든 라벨이 Magika 가 실제로 내놓는 이름이어야 한다."""
    real = {str(t) for t in _get_magika().get_output_content_types()}
    unknown = sorted(l for l in _DANGEROUS_LABELS if l not in real)
    assert not unknown, (
        f'Magika 가 내지 않는 라벨이 차단 목록에 있습니다: {unknown}. '
        f'이 항목들은 영원히 걸리지 않습니다.'
    )


# ── 위장 샘플 만들기 ────────────────────────────────────────────────
def _write(tmp_path, name: str, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _make_jar(tmp_path, name: str):
    p = tmp_path / name
    with zipfile.ZipFile(p, 'w') as z:
        z.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\nMain-Class: Main\n')
        z.writestr('Main.class', b'\xca\xfe\xba\xbe\x00\x00\x00\x34' + b'\x00' * 200)
    return p


SAMPLES = {
    'batch': b'@echo off\r\ndir c:\\\r\npause\r\n',
    'powershell': b'Get-Process | Select-Object -First 5\r\nWrite-Host "hi"\r\n',
    'javascript': b'function f(){ return 1; }\nconsole.log(f());\n'
                  b'var x = [1,2,3].map(function(v){return v*2;});\n',
    'vba': b'Set o = CreateObject("WScript.Shell")\r\no.Run "calc.exe"\r\nMsgBox "hi"\r\n',
    'winregistry': b'Windows Registry Editor Version 5.00\r\n\r\n'
                   b'[HKEY_CURRENT_USER\\Software\\T]\r\n"a"="b"\r\n',
    'shell': b'#!/bin/sh\nls -la /tmp\nexit 0\n',
}


@pytest.mark.parametrize('label', sorted(SAMPLES))
def test_disguised_script_is_blocked(tmp_path, label):
    """스크립트를 .pdf 로 위장해도 차단되어야 한다."""
    p = _write(tmp_path, f'{label}_위장.pdf', SAMPLES[label])
    assert detect(p) == label, f'{label} 샘플이 다른 타입으로 인식됨: {detect(p)}'
    assert check_mismatch(p).severity == FileCheckResult.BLOCK


def test_disguised_jar_is_blocked(tmp_path):
    p = _make_jar(tmp_path, 'jar_위장.pdf')
    assert check_mismatch(p).severity == FileCheckResult.BLOCK


def test_disguised_exe_is_blocked(tmp_path):
    """실제 Windows 실행파일을 .pdf 로 위장한 경우."""
    import shutil
    src = r'C:\Windows\System32\find.exe'
    import os
    if not os.path.exists(src):
        pytest.skip('시스템 실행파일 샘플 없음')
    p = tmp_path / 'exe_위장.pdf'
    shutil.copy2(src, p)
    r = check_mismatch(p)
    assert r.label == 'pebin'
    assert r.severity == FileCheckResult.BLOCK


def test_real_pdf_passes(tmp_path):
    """정상 PDF 는 아무 경고 없이 통과해야 한다 (오탐 방지)."""
    import fitz
    p = tmp_path / '정상.pdf'
    doc = fitz.open()
    doc.new_page()
    doc.save(str(p))
    doc.close()
    assert check_mismatch(p).severity == FileCheckResult.SAFE


def test_real_png_passes(tmp_path):
    """정상 이미지도 통과해야 한다 (오탐 방지)."""
    from PIL import Image
    p = tmp_path / '정상.png'
    Image.new('RGBA', (32, 32), (255, 0, 0, 255)).save(p)
    assert check_mismatch(p).severity == FileCheckResult.SAFE
