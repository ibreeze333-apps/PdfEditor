# utils/settings.py — 앱 설정 (JSON 저장)
from __future__ import annotations
import json
import os
import math
import tempfile
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import get_type_hints, get_origin, get_args
from utils.errlog import swallowed

_SETTINGS_PATH = Path.home() / '.pdf_editor_settings.json'


@dataclass
class AppSettings:
    zoom:            float     = 1.0
    view_mode:       str       = 'single'     # single | double | scroll
    recent_files:    list[str] = None
    window_w:        int       = 1280
    window_h:        int       = 900
    thumb_width:     int       = 180
    ocr_engine:      str       = 'fast'
    ocr_gpu:         bool      = True
    ocr_lang:        str       = 'ko+en'
    save_dual_copy:  bool      = False   # 저장 시 원본 백업본 자동 생성
    # 저장할 때 글꼴에서 실제 쓴 글자만 남긴다(서브셋). PDF 표준 방식이고
    # 끄면 글꼴 파일이 통째로 들어가 파일이 몇 배로 커진다. 다른 프로그램에서
    # 그 글꼴로 '새 글자'를 타이핑할 일이 있고 그 컴퓨터에 글꼴이 없다면 끈다.
    subset_fonts:    bool      = True
    tool_defaults:   dict      = None    # {tool_name: {color, opacity, width}}
    dict_path:         str       = ''              # 롤오버 사전 파일 경로
    dict_paths:        list[str] = None            # multiple offline dictionary paths
    dict_active_path:  str       = ''              # active offline dictionary path
    dict_enabled:      bool      = False           # 롤오버 사전 활성화
    dict_online_mode:  bool      = False           # 온라인 사전으로 대체 (네이버/파파고/구글)
    dict_english_only: bool      = False           # limit rollover lookup candidates to English
    dict_popup_font_size: int      = 12            # 팝업 글자 크기
    dict_favorites:    list[dict] = None           # 즐겨찾기
    dict_win_font:     str       = 'Malgun Gothic' # 사전 창 폰트
    dict_win_font_size: int      = 13              # 사전 창 폰트 크기
    book_bg_color:       str       = '#e7dcc5'       # 책 배경 색상
    book_texture_strength: int     = 18              # 책 배경 질감 강도(0-40)
    book_preset:         str       = 'classic'      # 책 보기 프리셋
    blur_mode:          str       = 'gaussian'
    blur_strength:      int       = 12
    blur_first_warning_seen: bool = False
    blur_export_warning_enabled: bool = True
    tabs_enabled:       bool      = True   # 탭 바 표시 여부
    menu_button_style:  str       = 'liquid'  # liquid | classic
    translate_model:    str       = 'Ollama — 로컬 번역'      # 번역 모델 선택
    translate_lang:     str       = '영어 → 한국어'    # 번역 방향 콤보 기본값
    # ── 번역 허브 (AI 제공자) ────────────────────────────────
    # [{name, protocol('openai'|'anthropic'), base_url, api_key, model}]
    # api_key 는 사용자가 직접 입력 — 코드/기본값에 키를 넣지 않는다
    ai_providers:        list[dict] = None
    ai_provider_active:  str        = ''    # 마지막 선택한 제공자 이름
    hub_ollama_model:    str        = ''    # 허브에서 마지막 선택한 Ollama 모델
    hub_web_service:     str        = 'ChatGPT'  # 웹 AI 마지막 선택 서비스
    hub_custom_web_url:  str        = ''    # 사용자 지정 웹 번역 주소


    def __post_init__(self):
        if self.recent_files is None:
            self.recent_files = []
        if self.ai_providers is None:
            from utils.ai_translate import DEFAULT_PROVIDERS
            import copy
            self.ai_providers = copy.deepcopy(DEFAULT_PROVIDERS)
        else:
            # 저장된 API 키 복호화 (DPAPI). 과거 평문 저장분은 그대로 통과
            # → 다음 save() 때 자동으로 암호화 마이그레이션된다.
            from utils.secure_store import unprotect
            for p in self.ai_providers:
                if isinstance(p, dict) and p.get('api_key'):
                    p['api_key'] = unprotect(p['api_key'])
        if self.tool_defaults is None:
            self.tool_defaults = {}
        if self.dict_favorites is None:
            self.dict_favorites = []
        if self.dict_paths is None:
            self.dict_paths = [self.dict_path] if self.dict_path else []
        else:
            seen = set()
            cleaned = []
            for item in self.dict_paths:
                p = str(item or '').strip()
                if p and p not in seen:
                    cleaned.append(p)
                    seen.add(p)
            self.dict_paths = cleaned
        if not self.dict_path and self.dict_paths:
            self.dict_path = self.dict_paths[0]
        if self.dict_active_path and self.dict_active_path not in self.dict_paths:
            self.dict_active_path = ''
        if not self.dict_active_path and self.dict_paths:
            self.dict_active_path = self.dict_paths[0]

    def add_recent(self, path: str):
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        self.recent_files = self.recent_files[:10]

    def save(self):
        data = asdict(self)
        # API 키는 평문으로 디스크에 쓰지 않는다 — Windows DPAPI 로
        # 사용자 계정 바인딩 암호화 (메모리의 self 는 평문 유지)
        from utils.secure_store import protect
        for p in data.get('ai_providers') or []:
            if isinstance(p, dict) and p.get('api_key'):
                p['api_key'] = protect(p['api_key'])
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix='.pdf-settings-', suffix='.json',
                                              dir=_SETTINGS_PATH.parent)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
            os.replace(temporary, _SETTINGS_PATH)
            return True
        except (OSError, ValueError):
            logging.getLogger('pdf_editor').exception('설정을 저장하지 못했습니다. 이전 설정은 보존됩니다.')
            return False
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    logging.getLogger('pdf_editor').warning('설정 임시 파일을 정리하지 못했습니다: %s', temporary)

    @classmethod
    def load(cls) -> 'AppSettings':
        if _SETTINGS_PATH.exists():
            try:
                data = json.loads(_SETTINGS_PATH.read_text(encoding='utf-8'))
                def valid(value, annotation):
                    origin = get_origin(annotation)
                    if origin is list:
                        return isinstance(value, list) and all(valid(v, get_args(annotation)[0]) for v in value)
                    if annotation is float:
                        return type(value) in (int, float) and math.isfinite(value)
                    return type(value) is annotation
                types = get_type_hints(cls)
                cleaned = {k: v for k, v in data.items() if k in types and valid(v, types[k])}
                for name in ('window_w', 'window_h', 'thumb_width', 'zoom'):
                    if name in cleaned and cleaned[name] <= 0:
                        cleaned.pop(name)
                if cleaned.get('menu_button_style') not in ('liquid', 'classic'):
                    cleaned.pop('menu_button_style', None)
                return cls(**cleaned)
            except Exception:
                swallowed()
        return cls()
