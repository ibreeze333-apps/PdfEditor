# 오픈소스 고지 (Third-party notices)

PdfEditor 는 아래 오픈소스 구성 요소를 사용합니다. 각 구성 요소의 저작권은 해당
저작자에게 있으며, 각자의 라이선스를 따릅니다.

| 구성 요소 | 버전 | 라이선스 | 출처 |
|---|---|---|---|
| PyMuPDF | 1.27.2 | Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial Lic | https://pymupdf.readthedocs.io/ |
| PySide6 | 6.10.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| numpy | 2.4.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| opencv-contrib-python | 4.10.0.84 | Apache 2.0 | https://github.com/opencv/opencv-python |
| paddleocr | 3.4.0 | Apache License 2.0 | https://github.com/PaddlePaddle/PaddleOCR |
| paddlepaddle | 3.3.0 | Apache Software License | UNKNOWN |
| paddlex | 3.4.2 | Apache-2.0 |  |
| pillow | 12.3.0 | MIT-CMU | https://pillow.readthedocs.io/en/stable/releasenotes/index.html |
| pytesseract | 0.3.13 | Apache License 2.0 | https://github.com/madmaze/pytesseract |
| pyclipper | 1.4.0 | MIT | https://github.com/fonttools/pyclipper |
| requests | 2.34.2 | Apache-2.0 | https://requests.readthedocs.io |
| shapely | 2.1.2 | BSD 3-Clause | https://shapely.readthedocs.io/ |
| soundfile | 0.13.1 | BSD 3-Clause License | https://github.com/bastibe/python-soundfile |
| tqdm | 4.67.3 | MPL-2.0 AND MIT | https://tqdm.github.io |
| magika | 1.0.3 | Apache-2.0 | https://securityresearch.google/magika |
| pyhanko | 0.36.2 | MIT | https://github.com/MatthiasValvekens/pyHanko |
| markdown-it-py | 4.0.0 | MIT License | https://markdown-it-py.readthedocs.io |
| pywin32 | 312 | PSF | https://github.com/mhammond/pywin32 |
| keyboard | 0.13.5 | MIT | https://github.com/boppreh/keyboard |
| pdfminer.six | 20260107 | MIT | https://github.com/pdfminer/pdfminer.six |
| pdfplumber | 0.11.10 | MIT License | https://github.com/jsvine/pdfplumber |
| python-docx | 1.2.0 | MIT | https://github.com/python-openxml/python-docx/blob/master/HISTORY.rst |
| opendataloader-pdf | 2.5.2 | Apache-2.0 | https://github.com/opendataloader-project/opendataloader-pdf |
| kiwipiepy | 0.23.2 | LGPL v3 License | https://github.com/bab2min/kiwipiepy |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| python-bidi | 0.6.11 | GNU Library or Lesser General Public License (LGPL) | https://github.com/MeirKriheli/python-bidi/blob/master/CHANGELOG.rst |
| Tesseract OCR (UB-Mannheim 빌드) | 5.5.0.20241111 | Apache-2.0 | https://github.com/tesseract-ocr/tesseract |
| tessdata (kor·eng·jpn·chi_sim·osd) | — | Apache-2.0 | https://github.com/tesseract-ocr/tessdata |
| Qt 6 (PySide6 에 포함) | — | LGPL-3.0 | https://www.qt.io/licensing |
| Python 3.11 런타임 | 3.11 | PSF-2.0 | https://www.python.org |

## 이 프로그램의 라이선스

PDF 처리 엔진 **PyMuPDF / MuPDF 가 GNU AGPL-3.0** 이므로, 이 프로그램 전체를
**GNU AGPL-3.0** 으로 배포합니다(LICENSE 참고). 배포본을 받은 누구나 이 저장소에서
전체 소스를 받을 수 있습니다.

## LGPL 구성 요소 (Qt·PySide6, kiwipiepy, python-bidi)

배포본은 PyInstaller `--onedir` 방식이라 이 라이브러리들이 `_internal` 폴더에 별도
파일(DLL·모듈)로 들어 있습니다. 사용자는 같은 인터페이스의 다른 버전으로 교체할
수 있습니다.

각 라이선스 전문은 해당 프로젝트의 출처 링크에서 볼 수 있습니다.
