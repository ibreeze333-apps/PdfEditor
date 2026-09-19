# utils/ollama_client.py — Ollama 로컬 API 클라이언트
from __future__ import annotations
import base64
import logging
from utils.errlog import swallowed

logger = logging.getLogger(__name__)

OLLAMA_BASE = 'http://localhost:11434'

# Vision 기능이 있다고 알려진 모델 키워드 (소문자 매칭) — 드롭다운 상단 정렬용
_VISION_KEYWORDS = (
    'llava', 'minicpm', 'moondream', 'bakllava',
    'vision', '-vl', ':vl', 'phi3-v',
    'llama3.2:11b', 'llama3.2:90b',
    'gemma3', 'gemma4',
)


def is_running() -> bool:
    """Ollama 서버가 localhost:11434 에서 응답하는지 확인 (타임아웃 2초)."""
    try:
        import requests
        return requests.get(f'{OLLAMA_BASE}/api/tags', timeout=2).ok
    except Exception:
        return False


def get_models() -> list[str]:
    """설치된 Ollama 모델 이름 목록. 실패 시 빈 리스트."""
    try:
        import requests
        r = requests.get(f'{OLLAMA_BASE}/api/tags', timeout=3)
        if r.ok:
            return [m['name'] for m in r.json().get('models', [])]
    except Exception:
        swallowed()
    return []


# 번역 품질이 좋은 것으로 알려진 모델 키워드 — 드롭다운 상단 정렬용
_TRANSLATE_KEYWORDS = (
    'qwen', 'gemma', 'llama', 'mistral', 'phi',
    'deepseek', 'eeve', 'solar', 'exaone', 'command',
)


def get_text_models() -> list[str]:
    """번역용 모델 목록.

    번역에 적합한 것으로 알려진 모델을 상단에, 나머지도 모두 포함.
    (임베딩 전용 모델만 제외)
    """
    all_models = [m for m in get_models() if 'embed' not in m.lower()]
    known   = [m for m in all_models if any(kw in m.lower() for kw in _TRANSLATE_KEYWORDS)]
    unknown = [m for m in all_models if m not in known]
    return known + (['──────────'] if known and unknown else []) + unknown


def get_vision_models() -> list[str]:
    """Vision OCR용 모델 목록.

    키워드로 알려진 Vision 모델을 상단에 정렬하고,
    나머지 모델도 모두 포함한다 — 새 모델이 키워드 목록에 없어도 선택 가능.
    (임베딩 전용 모델만 제외)
    """
    all_models = [m for m in get_models() if 'embed' not in m.lower()]
    known   = [m for m in all_models if any(kw in m.lower() for kw in _VISION_KEYWORDS)]
    unknown = [m for m in all_models if m not in known]
    return known + (['──────────'] if known and unknown else []) + unknown


def translate(text: str, src: str, tgt: str, model: str) -> str:
    """Ollama 모델로 텍스트 번역. 오류 시 예외 발생."""
    import requests

    _LANG = {'en': '영어', 'ko': '한국어', 'ja': '일본어', 'zh': '중국어(간체)'}
    src_name = _LANG.get(src, src)
    tgt_name = _LANG.get(tgt, tgt)

    prompt = (
        f"아래 {src_name} 텍스트를 {tgt_name}로 번역하세요.\n"
        "번역문만 출력하고, 원문·설명·주석은 포함하지 마세요.\n\n"
        f"{text}"
    )
    r = requests.post(
        f'{OLLAMA_BASE}/api/generate',
        json={'model': model, 'prompt': prompt, 'stream': False},
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get('response', '').strip()


def translate_long(text: str, src: str, tgt: str, model: str) -> str:
    """긴 텍스트를 정리→청크 분할→순차 번역해 합친다 (Ollama 패널 번역 탭용)."""
    from utils.translate_text_utils import clean_pdf_text, chunk_paragraphs
    cleaned = clean_pdf_text(text)
    chunks = chunk_paragraphs(cleaned, max_chars=1500)
    if not chunks:
        raise ValueError('번역할 텍스트가 없습니다.')
    results = []
    for chunk in chunks:
        results.append(translate(chunk, src, tgt, model))
    return '\n\n'.join(results)


# ── 내부 헬퍼 ────────────────────────────────────────────────────────

def _generate(prompt: str, model: str, timeout: int = 120) -> str:
    """범용 generate API 호출."""
    import requests
    r = requests.post(
        f'{OLLAMA_BASE}/api/generate',
        json={'model': model, 'prompt': prompt, 'stream': False},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get('response', '').strip()


def _chat(messages: list[dict], model: str, timeout: int = 120) -> str:
    """chat API 호출 (대화 히스토리 지원)."""
    import requests
    r = requests.post(
        f'{OLLAMA_BASE}/api/chat',
        json={'model': model, 'messages': messages, 'stream': False},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get('message', {}).get('content', '').strip()


# ── 분석 함수 ────────────────────────────────────────────────────────

def summarize(text: str, model: str, length: str = 'medium') -> str:
    """문서 요약 — 반드시 한국어로 출력."""
    hints = {'short': '3줄 이내로', 'medium': '5~10줄로', 'long': '상세하게'}
    hint = hints.get(length, '5~10줄로')
    messages = [
        {
            'role': 'system',
            'content': (
                '당신은 문서 요약 전문가입니다. '
                '반드시 한국어로만 답변하세요. '
                'Do not respond in English. Always use Korean.'
            ),
        },
        {
            'role': 'user',
            'content': (
                f'다음 문서를 {hint} 한국어로 요약하세요. '
                '요약문만 출력하고 다른 설명은 하지 마세요.\n\n'
                f'{text}'
            ),
        },
    ]
    return _chat(messages, model)


def qa(context: str, question: str, model: str,
       history: list[dict] | None = None) -> str:
    """문서 기반 질문 답변."""
    messages = [{'role': 'system',
                 'content': f'다음 문서를 참고하여 질문에 답하세요.\n\n---\n{context}\n---'}]
    if history:
        messages.extend(history)
    messages.append({'role': 'user', 'content': question})
    return _chat(messages, model)


def extract_terms(text: str, model: str, mode: str = 'all') -> str:
    """핵심 용어/인명/날짜 추출."""
    mode_hints = {
        'technical': '전문 용어와 기술 용어',
        'entities':  '인명, 기관명, 지명',
        'numbers':   '날짜, 수치, 통계',
        'all':       '전문 용어, 인명/기관명, 날짜/수치 등 주요 정보',
    }
    hint = mode_hints.get(mode, mode_hints['all'])
    return _generate(
        f"다음 문서에서 {hint}를 추출하세요.\n"
        f"카테고리별로 분류하여 목록 형태로 출력하세요.\n\n{text}",
        model, timeout=90,
    )


def correct_ocr(text: str, model: str) -> str:
    """OCR 오류 보정."""
    return _generate(
        "다음은 OCR로 추출된 텍스트입니다. "
        "오인식된 글자, 잘못된 띄어쓰기, 의미가 맞지 않는 부분을 수정하세요. "
        "수정된 텍스트만 출력하세요.\n\n" + text,
        model,
    )


def improve_translation(text: str, tgt_lang: str, model: str) -> str:
    """번역문 자연스럽게 다듬기."""
    lang_names = {'ko': '한국어', 'en': '영어', 'ja': '일본어', 'zh': '중국어'}
    lang_name = lang_names.get(tgt_lang, tgt_lang)
    return _generate(
        f"다음 {lang_name} 번역문을 자연스럽게 다듬으세요. "
        "의미를 유지하면서 어색한 표현을 수정하세요. "
        "수정된 번역문만 출력하세요.\n\n" + text,
        model,
    )


def generate_annotation(text: str, model: str, style: str = 'explain') -> str:
    """텍스트에 대한 어노테이션 생성."""
    style_hints = {
        'explain':  '이 내용을 쉽게 설명하는 주석',
        'summary':  '이 내용의 핵심을 정리한 요약',
        'critique': '이 내용에 대한 비판적 분석',
    }
    hint = style_hints.get(style, style_hints['explain'])
    return _generate(
        f"다음 텍스트에 대해 {hint}을 2~4문장으로 작성하세요.\n\n" + text,
        model,
    )


def structure_table(text: str, model: str) -> str:
    """표 데이터를 마크다운 표로 구조화."""
    return _generate(
        "다음 텍스트에 포함된 표나 데이터를 마크다운 표 형식으로 정리하세요. "
        "데이터가 없으면 '표 데이터 없음'이라고 답하세요. "
        "마크다운 표만 출력하세요.\n\n" + text,
        model,
    )


def free_chat(question: str, model: str,
              history: list[dict] | None = None) -> str:
    """PDF 컨텍스트 없는 자유 대화."""
    messages = list(history) if history else []
    messages.append({'role': 'user', 'content': question})
    return _chat(messages, model)


def ocr_image_bytes(image_bytes: bytes, model: str, lang: str = 'ko') -> str:
    """Ollama Vision 모델로 이미지에서 텍스트 추출. 오류 시 예외 발생."""
    import requests

    _LANG = {'ko': '한국어', 'en': '영어', 'ja': '일본어', 'zh': '중국어'}
    lang_name = _LANG.get(lang[:2], '한국어')

    img_b64 = base64.b64encode(image_bytes).decode()
    prompt = (
        f"이 이미지의 {lang_name} 텍스트를 모두 추출하세요. "
        "원본 텍스트만 출력하고, 설명·주석은 포함하지 마세요. "
        "단락·줄 구조를 최대한 보존하세요."
    )
    r = requests.post(
        f'{OLLAMA_BASE}/api/generate',
        json={
            'model': model,
            'prompt': prompt,
            'images': [img_b64],
            'stream': False,
        },
        timeout=180,
    )
    r.raise_for_status()
    return r.json().get('response', '').strip()
