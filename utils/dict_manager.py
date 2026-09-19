from __future__ import annotations

import re
import struct
from pathlib import Path
from utils.errlog import swallowed

_MDX = None


def _ensure_readmdict() -> tuple[bool, str]:
    global _MDX
    if _MDX is not None:
        return True, ''
    try:
        from readmdict import MDX as _M
        _MDX = _M
        return True, ''
    except ImportError:
        swallowed()

    import subprocess
    import sys

    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', 'readmdict'],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
        )
        if result.returncode != 0:
            return False, f'readmdict 설치 실패:\n{result.stderr[:300]}'
        from readmdict import MDX as _M
        _MDX = _M
        return True, 'readmdict 자동 설치 완료'
    except Exception as e:
        return False, f'readmdict 설치 오류: {e}'


_HTML_TAG = re.compile(r'<[^>]+>')
_HTML_ENT = [
    ('&nbsp;', ' '),
    ('&lt;', '<'),
    ('&gt;', '>'),
    ('&amp;', '&'),
    ('&quot;', '"'),
    ('&#13;', '\n'),
]


def _strip_html(text: str) -> str:
    for ent, rep in _HTML_ENT:
        text = text.replace(ent, rep)
    text = _HTML_TAG.sub('', text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return '  /  '.join(lines[:6])


class DictManager:
    def __init__(self):
        self._data: dict[str, str] = {}
        self._path: str = ''
        self._active_path: str = ''
        self._sources: list[dict] = []
        self.enabled: bool = False

    @property
    def is_loaded(self) -> bool:
        return bool(self._sources)

    @property
    def word_count(self) -> int:
        if self._sources:
            return sum(int(src.get('word_count', 0)) for src in self._sources)
        return len(self._data)

    @property
    def path(self) -> str:
        return self._active_path or self._path

    @property
    def active_path(self) -> str:
        return self._active_path

    @property
    def source_count(self) -> int:
        return len(self._sources)

    def source_infos(self) -> list[dict[str, str | int]]:
        return [
            {
                'path': str(src['path']),
                'name': str(src['name']),
                'word_count': int(src['word_count']),
            }
            for src in self._sources
        ]

    def set_active(self, path: str | None):
        candidate = str(path or '').strip()
        if candidate and any(src['path'] == candidate for src in self._sources):
            self._active_path = candidate
        elif not candidate:
            self._active_path = ''
        elif self._sources:
            self._active_path = str(self._sources[0]['path'])
        else:
            self._active_path = ''

    def lookup(self, word: str, source_path: str | None = None) -> str | None:
        w = (word or '').strip()
        if not w:
            return None
        if source_path is None:
            source_path = self._active_path
        source_path = str(source_path or '').strip()

        if source_path:
            src = self._source_by_path(source_path)
            if src is not None:
                return self._lookup_map(src['data'], w)
            return None

        for src in self._sources:
            found = self._lookup_map(src['data'], w)
            if found:
                return found
        return self._lookup_map(self._data, w)

    def load(self, path: str) -> tuple[bool, str]:
        return self.load_many([path])

    def load_many(self, paths: list[str]) -> tuple[bool, str]:
        norm_paths: list[str] = []
        seen = set()
        for item in paths or []:
            p = str(item or '').strip()
            if not p or p in seen:
                continue
            seen.add(p)
            norm_paths.append(p)

        if not norm_paths:
            self.unload()
            return False, '사전 파일이 없습니다.'

        loaded: list[dict] = []
        errors: list[str] = []
        merged: dict[str, str] = {}

        for path in norm_paths:
            ok, msg, data = self._load_single_data(path)
            if not ok:
                errors.append(f'{Path(path).name}: {msg}')
                continue
            name = Path(path).stem
            entry_count = self._estimate_word_count(data)
            loaded.append({
                'path': path,
                'name': name,
                'data': data,
                'word_count': entry_count,
            })
            for key, value in data.items():
                merged.setdefault(key, value)

        if not loaded:
            self.unload()
            return False, '\n'.join(errors) if errors else '사전 로드 실패'

        self._sources = loaded
        self._data = merged
        self._path = str(loaded[0]['path'])
        if not any(src['path'] == self._active_path for src in self._sources):
            self._active_path = self._path

        names = ', '.join(src['name'] for src in loaded[:3])
        if len(loaded) > 3:
            names += ' ...'
        msg = f'{len(loaded)}개 사전 로드: {names}'
        if errors:
            msg += f'  (실패 {len(errors)}개)'
        return True, msg

    def add_path(self, path: str) -> tuple[bool, str]:
        paths = [str(src['path']) for src in self._sources]
        p = str(path or '').strip()
        if p and p not in paths:
            paths.append(p)
        return self.load_many(paths)

    def remove_path(self, path: str) -> tuple[bool, str]:
        target = str(path or '').strip()
        paths = [str(src['path']) for src in self._sources if str(src['path']) != target]
        if not paths:
            self.unload()
            return True, '사전을 모두 제거했습니다.'
        ok, msg = self.load_many(paths)
        return ok, msg

    def unload(self):
        self._data.clear()
        self._path = ''
        self._active_path = ''
        self._sources.clear()

    def _source_by_path(self, path: str) -> dict | None:
        for src in self._sources:
            if src['path'] == path:
                return src
        return None

    def _lookup_map(self, data: dict[str, str], word: str) -> str | None:
        w = word.strip()
        result = data.get(w) or data.get(w.lower())
        if result:
            return result
        w2 = w.strip('.,!?;:\'"()[]{}')
        return data.get(w2) or data.get(w2.lower())

    def _estimate_word_count(self, data: dict[str, str]) -> int:
        keys = set()
        for key in data:
            if not key:
                continue
            keys.add(key.casefold())
        return len(keys)

    def _load_single_data(self, path: str) -> tuple[bool, str, dict[str, str]]:
        p = Path(path)
        if not p.exists():
            return False, f'파일을 찾을 수 없습니다: {path}', {}

        ext = p.suffix.lower()
        if ext in ('.mdx', '.mdict'):
            return self._load_mdx(path)

        if ext in ('.dict', '.dz', '.ifo'):
            ok, msg, data = self._load_stardict(path)
            if ok:
                return True, msg, data

        try:
            raw = p.read_bytes()
        except Exception as e:
            return False, str(e), {}

        if ext == '.mdic':
            ok, msg, data = self._parse_mdic_binary(raw)
            if ok:
                return True, msg, data
            ok, msg, data = self._parse_text(raw, path)
            if ok:
                return True, msg, data
            return False, f'MDIC 파싱 실패: {msg}', {}

        ok, msg, data = self._parse_text(raw, path)
        if ok:
            return True, msg, data
        return False, msg, {}

    def _parse_mdic_binary(self, raw: bytes) -> tuple[bool, str, dict[str, str]]:
        try:
            idx = raw.find(b'MDIC')
            if idx < 0:
                return False, 'MDIC 매직 바이트가 없습니다.', {}
            raw = raw[idx:]
            if len(raw) < 12:
                return False, '헤더가 너무 짧습니다.', {}

            count = struct.unpack_from('<I', raw, 8)[0]
            if count == 0 or count > 5_000_000:
                return False, f'항목 수가 비정상입니다: {count}', {}

            pos = 12
            data: dict[str, str] = {}
            for _ in range(count):
                if pos + 2 > len(raw):
                    break
                wlen = struct.unpack_from('<H', raw, pos)[0]
                pos += 2
                if pos + wlen > len(raw):
                    break
                word_b = raw[pos:pos + wlen]
                pos += wlen
                if pos + 4 > len(raw):
                    break
                dlen = struct.unpack_from('<I', raw, pos)[0]
                pos += 4
                if pos + dlen > len(raw):
                    break
                def_b = raw[pos:pos + dlen]
                pos += dlen

                for enc in ('utf-8', 'euc-kr', 'cp949'):
                    try:
                        word = word_b.decode(enc).strip()
                        defn = def_b.decode(enc).strip()
                        if word:
                            data[word] = defn
                            data[word.lower()] = defn
                        break
                    except UnicodeDecodeError:
                        continue

            if len(data) < max(1, count * 0.05):
                return False, f'파싱 성공률이 너무 낮습니다: {len(data)}/{count}', {}
            return True, f'MDIC 사전: {self._estimate_word_count(data):,}개 단어', data
        except Exception as e:
            return False, str(e), {}

    def _load_stardict(self, path: str) -> tuple[bool, str, dict[str, str]]:
        import gzip

        p = Path(path)
        name = p.name
        if name.endswith('.dict.dz'):
            base = p.with_name(name[:-8])
        elif p.suffix.lower() in ('.dict', '.ifo', '.idx'):
            base = p.with_suffix('')
        else:
            base = p

        ifo_path = base.with_suffix('.ifo')
        idx_path = base.with_suffix('.idx')
        dict_plain = base.with_suffix('.dict')
        dict_gz = Path(str(dict_plain) + '.dz')

        if not ifo_path.exists():
            return False, f'.ifo 파일이 없습니다: {ifo_path.name}', {}
        if not idx_path.exists():
            return False, f'.idx 파일이 없습니다: {idx_path.name}', {}

        if dict_plain.exists():
            dict_data = dict_plain.read_bytes()
        elif dict_gz.exists():
            try:
                with gzip.open(dict_gz, 'rb') as fp:
                    dict_data = fp.read()
            except Exception as e:
                return False, f'.dict.dz 해제 실패: {e}', {}
        else:
            return False, f'.dict 파일이 없습니다: {dict_plain.name}', {}

        try:
            ifo_text = ifo_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            ifo_text = ''
        same_type = ''
        for line in ifo_text.splitlines():
            if line.startswith('sametypesequence='):
                same_type = line.split('=', 1)[1].strip()
                break

        idx_raw = idx_path.read_bytes()
        data: dict[str, str] = {}
        pos = 0
        while pos < len(idx_raw):
            null = idx_raw.find(b'\x00', pos)
            if null < 0 or null + 9 > len(idx_raw):
                break
            word = idx_raw[pos:null].decode('utf-8', errors='ignore').strip()
            pos = null + 1
            offset = struct.unpack('>I', idx_raw[pos:pos + 4])[0]
            pos += 4
            size = struct.unpack('>I', idx_raw[pos:pos + 4])[0]
            pos += 4
            if not word or offset + size > len(dict_data):
                continue
            raw_def = dict_data[offset:offset + size]

            if same_type and same_type[0] in ('d', 'm', 'x', 'h'):
                defn = raw_def.decode('utf-8', errors='ignore')
            else:
                if raw_def and raw_def[0] in (ord('m'), ord('d'), ord('h'), ord('x')):
                    raw_def = raw_def[1:]
                defn = raw_def.decode('utf-8', errors='ignore')

            defn = _strip_html(defn).strip()
            if defn:
                data[word] = defn
                data[word.lower()] = defn

        if not data:
            return False, 'StarDict 항목을 읽지 못했습니다.', {}
        return True, f'StarDict 사전: {self._estimate_word_count(data):,}개 단어', data

    def _load_mdx(self, path: str) -> tuple[bool, str, dict[str, str]]:
        ok, install_msg = _ensure_readmdict()
        if not ok:
            return False, install_msg, {}
        try:
            mdx = _MDX(path)
            data: dict[str, str] = {}
            for key_b, val_b in mdx.items():
                word = key_b.decode('utf-8', errors='ignore').strip()
                defn = _strip_html(val_b.decode('utf-8', errors='ignore').strip())
                if word and defn:
                    data[word] = defn
                    data[word.lower()] = defn
            suffix = f' ({install_msg})' if install_msg else ''
            return True, f'MDX 사전: {self._estimate_word_count(data):,}개 단어{suffix}', data
        except Exception as e:
            return False, f'MDX 파싱 오류: {e}', {}

    def _parse_text(self, raw: bytes, path: str) -> tuple[bool, str, dict[str, str]]:
        text = None
        for enc in ('utf-8-sig', 'utf-8', 'euc-kr', 'cp949'):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            return False, '텍스트 인코딩 해석에 실패했습니다.', {}

        ext = Path(path).suffix.lower()
        if ext == '.json':
            import json as _json
            try:
                obj = _json.loads(text)
                if isinstance(obj, dict):
                    data = {str(k): str(v) for k, v in obj.items() if str(k).strip()}
                    for k, v in list(data.items()):
                        data.setdefault(k.lower(), v)
                    return True, f'JSON 사전: {self._estimate_word_count(data):,}개 단어', data
                if isinstance(obj, list):
                    data: dict[str, str] = {}
                    for item in obj:
                        if not isinstance(item, dict):
                            continue
                        word = (item.get('word') or item.get('headword') or item.get('w') or '').strip()
                        defn = (item.get('def') or item.get('definition') or item.get('d') or '').strip()
                        if word and defn:
                            data[word] = defn
                            data[word.lower()] = defn
                    if data:
                        return True, f'JSON 사전: {self._estimate_word_count(data):,}개 단어', data
            except Exception as e:
                return False, f'JSON 오류: {e}', {}

        lines = text.splitlines()
        sample = lines[:200] or ['']

        if sum(1 for line in sample if '\t' in line) > len(sample) * 0.4:
            data: dict[str, str] = {}
            for line in lines:
                if '\t' not in line:
                    continue
                word, defn = line.split('\t', 1)
                word = word.strip()
                defn = defn.strip()
                if word:
                    data[word] = defn
                    data[word.lower()] = defn
            if data:
                return True, f'TSV 사전: {self._estimate_word_count(data):,}개 단어', data

        if sum(1 for line in sample if ':' in line and not line.startswith('#')) > len(sample) * 0.5:
            data: dict[str, str] = {}
            for line in lines:
                if ':' not in line or line.startswith('#'):
                    continue
                word, defn = line.split(':', 1)
                word = word.strip()
                defn = defn.strip()
                if word:
                    data[word] = defn
                    data[word.lower()] = defn
            if data:
                return True, f'콜론 구분 사전: {self._estimate_word_count(data):,}개 단어', data

        data: dict[str, str] = {}
        i = 0
        while i < len(lines):
            word = lines[i].strip()
            if word and not word.startswith('#') and i + 1 < len(lines):
                defs = []
                i += 1
                while i < len(lines) and lines[i].strip():
                    defs.append(lines[i].strip())
                    i += 1
                if defs:
                    defn = '  /  '.join(defs[:4])
                    data[word] = defn
                    data[word.lower()] = defn
            i += 1
        if data:
            return True, f'블록형 사전: {self._estimate_word_count(data):,}개 단어', data

        return False, '지원하는 사전 형식을 찾지 못했습니다.', {}


_manager = DictManager()


def dict_manager() -> DictManager:
    return _manager
