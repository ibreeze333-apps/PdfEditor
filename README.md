# PdfEditor

무료 PDF 편집기 — Windows 용. Made by **Breeze333**

주석(형광펜·밑줄·도형·스탬프·책갈피 포스트잇), 찾기·고급 검색, OCR(스캔 문서 글자
인식), 번역 허브(Ollama·API·웹 AI), 디지털 서명·서명 확인, 문서 암호·워터마크·
개인정보 가리기, 페이지 편집 등을 한 프로그램에서 할 수 있습니다.

## 내려받기

[Releases](../../releases) 에서 최신 `PDFEditor-*.zip` 을 받아 압축을 풀고
`PDFEditor.exe` 를 실행하세요. 설치 과정은 없습니다.

**공식 배포처는 이 저장소의 Releases 뿐입니다.** 다른 곳에서 받은 파일은 변조됐을
수 있습니다. 받은 파일이 진짜인지는 Releases 에 적힌 SHA-256 값과 비교해 확인할 수
있습니다 (PowerShell):

```powershell
Get-FileHash .\PDFEditor-3.5.zip -Algorithm SHA256
```

## 개인정보

- 번역·AI 기능을 쓸 때만 문서 내용이 해당 서비스(구글 번역, 파파고, OpenAI 등)로
  전송됩니다. 쓰지 않으면 문서는 PC 밖으로 나가지 않습니다.
- API 키는 사용자가 직접 입력하며, Windows 계정 암호화(DPAPI)로 PC 에만 저장됩니다.

## 직접 빌드하기

1. Python 3.11 (Windows 64bit)
2. 가상환경과 패키지

   ```bat
   py -3.11 -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```

3. `vendor\tesseract\` 를 채웁니다 (방법은 `vendor/README.md`).
4. 빌드 — 결과는 `release\PDFEditor\` 에 생깁니다.

   ```bat
   .venv\Scripts\python build.py
   ```

실행만 해 보려면 `run.bat`, 테스트는 `.venv\Scripts\python -m pytest`.

## 라이선스

GNU AGPL-3.0 — `LICENSE` 참고. 사용한 오픈소스 목록은 `THIRD_PARTY_NOTICES.md`.

## 문의·제보

GitHub Issues 또는 ibreeze333@gmail.com
