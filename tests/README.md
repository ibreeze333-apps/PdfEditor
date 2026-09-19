# 회귀 테스트

```bash
python -m pytest tests/
```

느린 것(서명)을 빼고 빠르게:

```bash
python -m pytest tests/ -m "not slow"
```

## 무엇을 지키고 있나

| 파일 | 지키는 것 | 안 지키면 |
|---|---|---|
| `test_save.py` | 저장·회전·삭제, 실패 시 원본 보존, 반복 저장 시 파일 크기 | 사용자 문서가 날아간다 |
| `test_encryption.py` | 열람/관리자 암호 구분, 권한 비트 | 권한 제한이 통째로 우회된다 |
| `test_sign.py` | 서명 생성·검증·변조 탐지, 인증서 내보내기에 개인키가 안 섞이는지 | 서명이 장식이 된다 |
| `test_annot_coords.py` | 화면↔문서 좌표 왕복, 주석 위치 보존 | 주석이 엉뚱한 데 찍힌다 |

## 규칙

- **버그를 고칠 때는 먼저 그 버그를 재현하는 테스트를 여기 추가한다.**
  그래야 같은 버그가 두 번 나지 않는다. 지금까지 커밋 로그를 보면
  같은 영역(화살표·연필·암호)을 연속으로 다시 고친 적이 있다.
- 함수 이름은 ASCII 로. Windows 콘솔(cp949)에서 한글 이름이 깨져 나와
  어느 테스트가 실패했는지 못 읽는다. 설명은 docstring 에 한글로 쓴다.
- GUI 는 띄우지 않는다. `conftest.py` 가 `QT_QPA_PLATFORM=offscreen` 을
  설정하므로 PySide6 를 import 하는 모듈도 그대로 테스트할 수 있다.
- 픽스처 PDF 의 본문은 ASCII 로 쓴다. 내장 기본 글꼴(Helvetica)에
  한글 글리프가 없어서, 한글을 넣으면 깨진 글자가 들어간다.

## PyMuPDF 함정 (실제로 겪은 것)

- `list(doc[0].annots())` 처럼 페이지를 임시로만 쓰고 주석을 꺼내면,
  나중에 `annot.rect` 를 읽을 때 **네이티브 크래시**가 난다.
  파이썬 예외가 아니라 프로세스가 통째로 죽어서 `try/except` 로도 못 잡는다.
  반드시 `page = doc[0]` 로 붙잡아 둘 것.
- 하이라이트 주석의 `rect` 는 실제로 덮는 영역보다 바깥으로 부풀어 있다.
  위치를 확인하려면 `annot.vertices`(quadpoints)를 봐야 한다.
- `Document.needs_pass` 는 bool 이 아니라 int(0/1) 다. `is True` 로 비교하면 실패한다.
