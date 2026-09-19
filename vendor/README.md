# vendor/

빌드에 쓰는 외부 바이너리를 둔다. 용량이 커서 저장소에는 넣지 않는다(.gitignore).

## tesseract/

`build.py` 가 OCR 엔진을 번들할 때 **여기를 먼저 본다**. 없으면
`C:\Program Files\Tesseract-OCR`(시스템 설치본)로 넘어간다.

현재 넣어 둔 것: **Tesseract 5.5.0.20241111 / leptonica 1.85.0** (UB-Mannheim 빌드)

시스템 설치본에 의존하면 빌드하는 PC 사정에 따라 결과가 달라진다. 실제로 winget
(`UB-Mannheim.TesseractOCR`)이 주는 패키지는 5.4.0 으로 **버전이 더 낮으면서**
디버그 심볼이 남아 있어 `libtesseract-5.dll` 하나가 3.3 MB → 101.5 MB 였다.
같은 이미지로 비교했을 때 인식 결과는 바이트 단위로 동일했고 속도 차이도 1% 미만,
즉 용량만 159 MB 더 먹는다.

새 PC 에서 빌드해야 하는데 이 폴더가 비어 있다면:

1. 기존 배포본(`PDFEditor.exe` 가 있는 폴더)의 `_internal\tesseract` 를 통째로
   복사해 온다. 가장 확실하다.
2. 아니면 <https://github.com/UB-Mannheim/tesseract/releases> 에서 5.5.0 을 받아
   설치한 뒤 설치 폴더를 복사한다.

`tessdata` 는 저장소 루트의 `tessdata/`(kor·jpn·chi_sim 포함)를 쓰므로 여기에
있어도 번들에서 제외된다. 학습용 실행파일(`lstmtraining` 등)과 man 페이지도 뺀다.
