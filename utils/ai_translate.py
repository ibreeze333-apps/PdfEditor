# utils/ai_translate.py — 외부 AI API 번역 클라이언트
"""ChatGPT(OpenAI)·Claude(Anthropic)·사용자 정의 엔드포인트로 텍스트를 번역한다.

보안 원칙:
  - API 키는 코드에 절대 넣지 않는다. 사용자가 설정 화면에서 입력하며
    AppSettings(JSON)에 저장된다. 로그에도 키를 남기지 않는다.

프로토콜 2종을 지원한다:
  - 'openai'    : OpenAI 호환 chat/completions (ChatGPT, Groq, DeepSeek,
                  OpenRouter, LM Studio 등 대부분의 무료/유료 API가 이 형식)
  - 'anthropic' : Anthropic Messages API (Claude)

requests 만 사용한다 — 여러 제공자를 하나의 얇은 인터페이스로 다루기 위한
의도적 선택 (전용 SDK를 쓰면 제공자마다 의존성이 늘어 빌드가 무거워진다).
"""
from __future__ import annotations

import logging

logger = logging.getLogger('pdf_editor')

_LANG_NAMES = {'en': '영어', 'ko': '한국어', 'ja': '일본어', 'zh': '중국어(간체)'}

# 기본 제공자 프리셋 — api_key 는 반드시 비워 둔다 (사용자 입력)
DEFAULT_PROVIDERS: list[dict] = [
    {
        'name': 'ChatGPT (OpenAI)',
        'protocol': 'openai',
        'base_url': 'https://api.openai.com/v1',
        'api_key': '',
        'model': 'gpt-4o-mini',
    },
    {
        'name': 'Claude (Anthropic)',
        'protocol': 'anthropic',
        'base_url': 'https://api.anthropic.com',
        'api_key': '',
        'model': 'claude-haiku-4-5',
    },
]


def _build_prompt(text: str, src: str, tgt: str) -> tuple[str, str]:
    """(system, user) 프롬프트 생성 — ollama_client.translate 와 동일 규칙."""
    src_name = _LANG_NAMES.get(src, src)
    tgt_name = _LANG_NAMES.get(tgt, tgt)
    system = (
        f'당신은 전문 번역가입니다. 사용자가 준 {src_name} 텍스트를 '
        f'{tgt_name}로 번역하세요. 번역문만 출력하고 원문·설명·주석은 '
        f'포함하지 마세요. 단락 구조를 유지하세요.'
    )
    return system, text


def translate_via_provider(provider: dict, text: str, src: str, tgt: str,
                           timeout: int = 90) -> str:
    """제공자 설정(dict)으로 텍스트를 번역한다. 실패 시 예외 발생.

    provider 형식: {name, protocol, base_url, api_key, model}
    """
    protocol = (provider.get('protocol') or 'openai').strip().lower()
    api_key  = (provider.get('api_key') or '').strip()
    base_url = (provider.get('base_url') or '').strip().rstrip('/')
    model    = (provider.get('model') or '').strip()

    if not base_url:
        raise ValueError('제공자의 API 주소(base_url)가 비어 있습니다.')
    if not model:
        raise ValueError('제공자의 모델명이 비어 있습니다.')
    if not api_key:
        raise ValueError(
            f"'{provider.get('name', '?')}' 의 API 키가 설정되지 않았습니다.\n"
            '번역 메뉴 → AI 제공자 설정에서 키를 입력하세요.')

    if protocol == 'anthropic':
        return _translate_anthropic(base_url, api_key, model, text, src, tgt, timeout)
    return _translate_openai(base_url, api_key, model, text, src, tgt, timeout)


def _translate_openai(base_url: str, api_key: str, model: str,
                      text: str, src: str, tgt: str, timeout: int) -> str:
    """OpenAI 호환 chat/completions 호출."""
    import requests

    system, user = _build_prompt(text, src, tgt)
    url = f'{base_url}/chat/completions'
    r = requests.post(
        url,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        json={
            'model': model,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
        },
        timeout=timeout,
    )
    _raise_for_api_error(r)
    data = r.json()
    try:
        return (data['choices'][0]['message']['content'] or '').strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f'API 응답 형식이 예상과 다릅니다: {str(data)[:200]}') from exc


def _translate_anthropic(base_url: str, api_key: str, model: str,
                         text: str, src: str, tgt: str, timeout: int) -> str:
    """Anthropic Messages API 호출."""
    import requests

    system, user = _build_prompt(text, src, tgt)
    url = f'{base_url}/v1/messages'
    r = requests.post(
        url,
        headers={
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json',
        },
        json={
            'model': model,
            'max_tokens': 8192,
            'system': system,
            'messages': [{'role': 'user', 'content': user}],
        },
        timeout=timeout,
    )
    _raise_for_api_error(r)
    data = r.json()
    try:
        parts = [b.get('text', '') for b in data.get('content', [])
                 if b.get('type') == 'text']
        result = '\n'.join(p for p in parts if p).strip()
        if not result and data.get('stop_reason') == 'refusal':
            raise RuntimeError('모델이 요청을 거절했습니다 (refusal).')
        return result
    except AttributeError as exc:
        raise RuntimeError(f'API 응답 형식이 예상과 다릅니다: {str(data)[:200]}') from exc


def _raise_for_api_error(r) -> None:
    """HTTP 오류를 사용자가 이해할 수 있는 메시지로 변환한다. 키는 노출 금지."""
    if r.ok:
        return
    detail = ''
    try:
        body = r.json()
        # OpenAI: {error:{message}} / Anthropic: {error:{message}}
        detail = (body.get('error') or {}).get('message', '') or str(body)[:200]
    except Exception:
        detail = (r.text or '')[:200]

    hints = {
        401: 'API 키가 잘못되었거나 만료되었습니다.',
        403: 'API 키에 권한이 없습니다.',
        404: '주소 또는 모델명이 잘못되었습니다.',
        429: '요청 한도 초과 — 잠시 후 다시 시도하세요.',
        529: '서비스가 혼잡합니다 — 잠시 후 다시 시도하세요.',
    }
    hint = hints.get(r.status_code, '')
    raise RuntimeError(f'API 오류 {r.status_code}: {hint or detail}'.strip()
                       + (f'\n{detail}' if hint and detail else ''))


def test_provider(provider: dict) -> tuple[bool, str]:
    """제공자 연결 테스트 — 짧은 텍스트를 실제로 번역해 본다."""
    try:
        out = translate_via_provider(provider, 'Hello', 'en', 'ko', timeout=30)
        if out:
            return True, f'연결 성공 — 응답: {out[:40]}'
        return False, '응답이 비어 있습니다.'
    except Exception as e:
        return False, str(e)
