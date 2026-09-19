"""PDF Editor build script — 무료 배포 버전 (Breeze333)
실행: py -3.11 build.py
"""
import os
import fnmatch
import sys
import shutil
import subprocess
import re

# 콘솔 기본 인코딩(cp949)으로 못 찍는 글자가 섞이면 빌드가 통째로
# 죽는다. 로그 한 줄 때문에 빌드를 날릴 이유가 없으니 대체 문자로 흘린다.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

SRC  = os.path.dirname(os.path.abspath(__file__))
PY   = [sys.executable]


JDK_CANDIDATES = [
    r'C:\Program Files\Eclipse Adoptium\jdk-25.0.2.10-hotspot',
    r'C:\Program Files\Eclipse Adoptium\jdk-21.0.7.6-hotspot',
    r'C:\Program Files\Eclipse Adoptium\jdk-21.0.6.7-hotspot',
    r'C:\Program Files\Microsoft\jdk-21.0.7.7-hotspot',
    r'C:\Program Files\Java\jdk-21',
    r'C:\Program Files\Java\jdk-17',
]
# Tesseract — 저장소 안의 vendor/tesseract 를 우선 쓴다.
#
# 시스템 설치본에 의존하면 빌드하는 PC 에 깔린 버전에 따라 결과가 달라진다.
# 실제로 winget 으로 깐 5.4.0 은 예전에 쓰던 5.5.0 보다 버전이 낮으면서
# 디버그 심볼이 남아 있어 DLL 하나가 3 MB → 101 MB 였다(인식 결과·속도는
# 동일). 그래서 검증된 5.5.0 을 저장소 옆에 두고 그것을 쓴다.
_VENDOR_TESSERACT = os.path.join(SRC, 'vendor', 'tesseract')
TESSERACT_DIR = (_VENDOR_TESSERACT
                 if os.path.exists(os.path.join(_VENDOR_TESSERACT, 'tesseract.exe'))
                 else r'C:\Program Files\Tesseract-OCR')
JRE_MODULES = (
    'java.base,java.logging,java.xml,java.desktop,java.instrument,'
    'java.management,java.naming,java.net.http,java.prefs,java.rmi,'
    'java.scripting,java.security.jgss,java.security.sasl,java.sql,'
    'java.sql.rowset,java.xml.crypto,jdk.crypto.cryptoki,jdk.crypto.ec,'
    'jdk.unsupported,jdk.zipfs'
)

STAGE_ROOT = os.path.join(SRC, 'build_stage')
STAGE_APP = os.path.join(STAGE_ROOT, 'app')

STAGE_SOURCE_DIRS = (
    'core',
    'ui',
    'tools',
    'utils',
    'workers',
    'tessdata',
    'stamp1',
)

STAGE_SOURCE_FILES = (
    'config.py',
    'logo.ico',
    'logo.png',
    'main.py',
)

STAGE_SKIP_DIR_NAMES = {
    '__pycache__',
    '.git',
    '.pytest_cache',
    'hf_models',
    'logs',
    'autosave',
}

STAGE_SKIP_FILE_PATTERNS = (
    # 백업·임시·로그·메모 — 앱은 읽지 않는데 배포본에 섞이면 개발 흔적이 나간다.
    # (예전에 '*.bak_*' 만 걸러서 'main_window.py.before_unflatten.bak' 가 새 나갔다)
    '*.bak',
    '*.orig',
    '*.tmp',
    '*.log',
    '*.md',
    '*.bak_*',
    '*.broken_*',
    '*.failed_*',
    '*.pre_*',
    '*.pre-*',
    '*.pyc',
    '*.pyo',
)

STAGE_SKIP_REL_PATHS = {
    'core/annex_parser.py',
    'core/ast_to_pdf.py',
    'core/doc_ast.py',
    'core/docx_reader.py',
    'core/hwp5_parser.py',
    'core/hwpx_parser.py',
    'ui/hwp_panel.py',
    'ui/setup_dialogs.py',
    'ui/text_translate_panel.py',
    'ui/translate_panel.py',
    'ui/dialogs/cuda_upgrade_dialog.py',
    'ui/dialogs/doc_viewer_dialog.py',
    'utils/cuda_upgrade.py',
    'utils/translator.py',
    'workers/pdf2zh_worker.py',
    'workers/translate_worker.py',
}


def _set_variant(variant: str):
    """config.py 의 BUILD_VARIANT 값을 변경."""
    cfg_path = os.path.join(SRC, 'config.py')
    with open(cfg_path, encoding='utf-8') as f:
        src = f.read()
    src = re.sub(
        r"^BUILD_VARIANT\s*=\s*'.*?'",
        f"BUILD_VARIANT = '{variant}'",
        src, flags=re.MULTILINE
    )
    with open(cfg_path, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f'[config] BUILD_VARIANT = {variant!r}')


def find_jdk():
    """JDK 를 찾는다. 먼저 알려진 경로, 없으면 설치 폴더를 훑는다.

    JDK 는 업데이트되면 폴더 이름이 통째로 바뀐다(jdk-25.0.2.10 →
    jdk-25.0.3.9). 목록에만 의존하면 어느 날 조용히 못 찾고, Java 없이
    빌드돼서 HWP 기능만 죽은 exe 가 나간다. 실제로 그런 적이 있다.
    """
    import glob
    for p in JDK_CANDIDATES:
        if os.path.exists(os.path.join(p, 'bin', 'jlink.exe')):
            return p
    # 목록에 없으면 흔한 설치 위치를 훑어 가장 최신 버전을 쓴다
    found = []
    for pat in (r'C:\Program Files\Eclipse Adoptium\jdk-*',
                r'C:\Program Files\Microsoft\jdk-*',
                r'C:\Program Files\Java\jdk-*',
                r'C:\Program Files\Zulu\zulu-*',
                r'C:\Program Files\Amazon Corretto\jdk*'):
        for d in glob.glob(pat):
            if os.path.exists(os.path.join(d, 'bin', 'jlink.exe')):
                found.append(d)
    if found:
        found.sort()
        print('[JDK] 목록에 없어 자동 탐색: %s' % found[-1])
        return found[-1]
    return None


def make_jre(jdk_home):
    jre_dir = os.path.join(SRC, 'jre')
    if os.path.exists(jre_dir):
        shutil.rmtree(jre_dir)
    jlink = os.path.join(jdk_home, 'bin', 'jlink.exe')
    result = subprocess.run([
        jlink,
        '--add-modules', JRE_MODULES,
        '--output', jre_dir,
        '--strip-debug', '--no-header-files', '--no-man-pages',
    ])
    if result.returncode != 0:
        print('[WARNING] jlink failed — building without Java')
        return None
    print('JRE created.')
    return jre_dir


def clean(dist_dir):
    for d in [os.path.join(SRC, 'build'), os.path.join(SRC, 'dist'), dist_dir,
              os.path.join(SRC, 'jre'), STAGE_ROOT]:
        if os.path.exists(d):
            shutil.rmtree(d)
    spec = os.path.join(SRC, 'PDFEditor.spec')
    if os.path.exists(spec):
        os.remove(spec)



def _stage_rel(path: str) -> str:
    return os.path.relpath(path, SRC).replace(os.sep, '/')


def _should_skip_stage_file(path: str) -> bool:
    rel = _stage_rel(path)
    if rel in STAGE_SKIP_REL_PATHS:
        return True
    name = os.path.basename(path)
    return any(fnmatch.fnmatch(name, pattern) for pattern in STAGE_SKIP_FILE_PATTERNS)


def _copy_clean_dir(src: str, dst: str):
    def ignore(current_dir: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            full = os.path.join(current_dir, name)
            if os.path.isdir(full) and name in STAGE_SKIP_DIR_NAMES:
                ignored.add(name)
            elif os.path.isfile(full) and _should_skip_stage_file(full):
                ignored.add(name)
        return ignored

    shutil.copytree(src, dst, ignore=ignore)


def _prepare_stage():
    if os.path.exists(STAGE_ROOT):
        shutil.rmtree(STAGE_ROOT)
    os.makedirs(STAGE_APP, exist_ok=True)

    for filename in STAGE_SOURCE_FILES:
        src = os.path.join(SRC, filename)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(STAGE_APP, filename))

    for dirname in STAGE_SOURCE_DIRS:
        src = os.path.join(SRC, dirname)
        if os.path.exists(src):
            _copy_clean_dir(src, os.path.join(STAGE_APP, dirname))

    _strip_image_metadata(STAGE_APP)


# 이미지에서 지워도 보이는 모습이 바뀌지 않는 정보만 남긴다
_IMAGE_KEEP_INFO = ('icc_profile', 'dpi', 'transparency', 'gamma')
_IMAGE_SAFE_INFO = {'icc_profile', 'dpi', 'transparency', 'gamma',
                    'srgb', 'chromaticity', 'aspect', 'sizes'}


def _image_extra_info(im) -> list[str]:
    keys = sorted(k for k in im.info if k not in _IMAGE_SAFE_INFO)
    try:
        if len(im.getexif()):
            keys.append('exif')
    except Exception:
        pass
    return keys


def _strip_image_metadata(root: str):
    """스테이징한 PNG/JPEG 에서 글자 메타데이터(XMP·EXIF·tEXt)를 지운다.

    디자인 도구가 넣는 정보가 그대로 배포됐다. 실제로 logo.png 에 Canva
    사용자·문서·브랜드 ID 와 Facebook 연동 ID 가 들어 있었다. 원본을 고쳐도
    나중에 이미지를 바꾸면 다시 들어오므로 빌드할 때마다 지운다.
    픽셀은 그대로다.
    """
    try:
        from PIL import Image
    except ImportError:
        print('[WARNING] Pillow 없음 — 이미지 메타데이터 제거를 건너뜀')
        return
    cleaned = 0
    for r, _, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue
            path = os.path.join(r, name)
            try:
                with Image.open(path) as im:
                    if not _image_extra_info(im):
                        continue
                    im.load()
                    keep = {k: im.info[k] for k in _IMAGE_KEEP_INFO if k in im.info}
                    fmt = im.format
                    data = im.copy()
                if fmt == 'JPEG':
                    data.save(path, format='JPEG', quality=95, **keep)
                else:
                    data.save(path, format='PNG', optimize=True, **keep)
                cleaned += 1
            except Exception as e:
                print(f'[WARNING] 메타데이터 제거 실패: {path} ({e})')
    print(f'이미지 메타데이터 제거: {cleaned}개')


# 앱이 실행 중에 자기 폴더에 만드는 것들 — 빌드 결과에는 있으면 안 된다
_DIST_FORBIDDEN_DIRS = {'logs', 'autosave'}


def _audit_dist(dist_dir: str) -> list[str]:
    """배포 직전 점검. 문제 목록을 돌려준다(없으면 빈 목록).

    앱이 소유한 파일(STAGE_SOURCE_DIRS/FILES)만 본다 — 라이브러리 안의
    개발자 이메일 같은 남의 흔적까지 잡으면 경고가 무의미해진다.

    - exe 를 배포 폴더에서 직접 실행하면 _internal/logs, autosave 가 생긴다
    - 백업·메모·로그 파일
    - 이미지 글자 메타데이터
    - 이 PC 의 윈도우 사용자 이름이 앱 파일에 박힌 경우
    """
    problems: list[str] = []
    internal = os.path.join(dist_dir, '_internal')
    if not os.path.isdir(internal):
        return [f'_internal 폴더가 없음: {internal}']

    for r, dirs, _ in os.walk(dist_dir):
        for d in dirs:
            if d in _DIST_FORBIDDEN_DIRS:
                problems.append(f'실행 흔적 폴더: {os.path.relpath(os.path.join(r, d), dist_dir)}')

    app_paths = [os.path.join(internal, d) for d in STAGE_SOURCE_DIRS]
    app_files = []
    for p in app_paths:
        for r, _, files in os.walk(p):
            app_files += [os.path.join(r, f) for f in files]
    app_files += [os.path.join(internal, f) for f in STAGE_SOURCE_FILES
                  if os.path.isfile(os.path.join(internal, f))]

    user = (os.environ.get('USERNAME') or '').strip()
    needles = []
    if len(user) >= 3:
        needles = [user.encode('utf-8'), user.encode('utf-16-le')]

    try:
        from PIL import Image
    except ImportError:
        Image = None

    for path in app_files:
        rel = os.path.relpath(path, dist_dir)
        name = os.path.basename(path)
        if any(fnmatch.fnmatch(name, pat) for pat in STAGE_SKIP_FILE_PATTERNS
               if pat not in ('*.pyc', '*.pyo')):
            problems.append(f'백업/메모/로그 파일: {rel}')
            continue
        low = name.lower()
        if Image is not None and low.endswith(('.png', '.jpg', '.jpeg')):
            try:
                with Image.open(path) as im:
                    extra = _image_extra_info(im)
                if extra:
                    problems.append(f'이미지 메타데이터 {extra}: {rel}')
            except Exception:
                pass
        if needles and low.endswith(('.py', '.json', '.txt', '.ini', '.cfg', '.xml', '.html')):
            try:
                data = open(path, 'rb').read()
            except OSError:
                continue
            if any(n.lower() in data.lower() for n in needles):
                problems.append(f'사용자 이름({user}) 포함: {rel}')
    return problems

def _make_version_file(config) -> str:
    """exe 속성 창에 표시될 Windows 버전 리소스를 생성한다.

    config.APP_VERSION 에서 자동 생성하므로 버전이 어긋나지 않는다.
    ('2.5' → 2.5.0.0)
    """
    parts = [int(x) for x in re.findall(r'\d+', config.APP_VERSION)][:4]
    while len(parts) < 4:
        parts.append(0)
    vers = tuple(parts)
    ver_str = '.'.join(str(v) for v in vers)

    # 041204B0 = 한국어(1042) + Unicode(1200)
    content = f'''# build.py 가 config.APP_VERSION 에서 자동 생성 — 직접 수정하지 마세요.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vers},
    prodvers={vers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '041204B0',
        [StringStruct('CompanyName', {config.APP_ORG!r}),
         StringStruct('FileDescription', 'PDF 편집기'),
         StringStruct('FileVersion', {ver_str!r}),
         StringStruct('InternalName', {config.APP_EXE_NAME!r}),
         StringStruct('LegalCopyright', {f'© {config.APP_ORG}'!r}),
         StringStruct('OriginalFilename', {f'{config.APP_EXE_NAME}.exe'!r}),
         StringStruct('ProductName', 'PDF 편집기'),
         StringStruct('ProductVersion', {ver_str!r})])
    ]),
    VarFileInfo([VarStruct('Translation', [1042, 1200])])
  ]
)
'''
    os.makedirs(STAGE_ROOT, exist_ok=True)
    path = os.path.join(STAGE_ROOT, 'version_info.txt')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'버전 리소스 생성: {ver_str}')
    return path


# 앱이 쓰지 않는 Tesseract 학습용 실행파일 — 번들에서 뺀다.
_TRAINING_TOOL_PREFIXES = (
    'lstm', 'text2image', 'set_unicharset', 'unicharset_extractor',
    'combine_', 'cntraining', 'mftraining', 'shapeclustering',
    'wordlist2dawg', 'dawg2wordlist', 'ambiguous_words',
    'classifier_tester', 'merge_unicharsets',
)


def _stage_tesseract() -> str | None:
    """Tesseract 설치본을 스테이징하되 중복 tessdata 는 제외한다.

    앱은 자체 tessdata/(kor·jpn·chi_sim 포함)를 먼저 찾으므로
    (workers/ocr_worker.py:_resolve_tessdata_dir) Tesseract 가 들고 오는
    eng/osd 전용 tessdata(~15 MB)는 번들에 넣지 않는다.
    """
    if not os.path.exists(os.path.join(TESSERACT_DIR, 'tesseract.exe')):
        print('[WARNING] Tesseract not found — skipping')
        return None

    dst = os.path.join(STAGE_ROOT, 'tesseract')
    if os.path.exists(dst):
        shutil.rmtree(dst)

    def ignore(current_dir: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            full = os.path.join(current_dir, name)
            # 중복 tessdata + Java GUI 도구(jar) 제외 — CLI OCR 에 불필요
            if os.path.isdir(full) and name == 'tessdata':
                ignored.add(name)
            elif os.path.isfile(full) and (
                    name.lower().endswith(('.jar', '.html'))
                    or any(name.lower().startswith(pre) for pre in _TRAINING_TOOL_PREFIXES)):
                ignored.add(name)
        return ignored

    shutil.copytree(TESSERACT_DIR, dst, ignore=ignore)
    print(f'Tesseract staged (tessdata·jar 제외): {dst}')
    return dst


# 빌드 후 dist 에서 제거할 파일 — 앱이 절대 로드하지 않는 GPU 전용 바이너리.
#
# 앱의 유일한 onnxruntime 사용처인 magika 는
# providers=['CPUExecutionProvider'] 만 요청한다(magika/magika.py:
# _init_onnx_session). 따라서 GPU 프로바이더는 로드되지 않는다.
#
# 문제는 PyInstaller 가 프로바이더 DLL 의 의존성을 따라가 torch/lib 의
# CUDA 수학 라이브러리(cublas·cufft ≈ 825 MB)까지 함께 번들한다는 점이다.
# 프로바이더를 지우면 이들은 전부 고아가 되므로 같이 제거한다.
# (torch 자체는 --exclude-module 로 이미 빠져 있어 다른 사용처가 없다.)
PRUNE_DIST_PATTERNS = (
    # Qt6Core uses Windows ICU's unversioned exports. A foreign ICU 78
    # found on PATH shadows it but exports *_78, preventing Qt from loading.
    # Only Qt6Core imports icuuc.dll in this bundle; Tesseract uses libicuuc75.
    'icuuc.dll',
    'icudt78.dll',
    'onnxruntime_providers_cuda.dll',      # ~319 MB
    'onnxruntime_providers_tensorrt.dll',
    'cublas*.dll',                         # ~546 MB (cublas64, cublasLt64)
    'cufft*.dll',                          # ~278 MB
    'cudart*.dll',
    'cudnn*.dll',
    'curand*.dll',
    'cusolver*.dll',
    'cusparse*.dll',
    'nvrtc*.dll',
)


def _prune_dist(dist_dir: str):
    """사용하지 않는 GPU 라이브러리와 Windows ICU를 가리는 DLL을 제거한다."""
    removed_mb = 0.0
    count = 0
    for root, _, files in os.walk(dist_dir):
        for name in files:
            if not any(fnmatch.fnmatch(name.lower(), pat)
                       for pat in PRUNE_DIST_PATTERNS):
                continue
            full = os.path.join(root, name)
            mb = os.path.getsize(full) / 1024 / 1024
            os.remove(full)
            removed_mb += mb
            count += 1
            print(f'  [prune] {name}  ({mb:.1f} MB)')
    if removed_mb:
        print(f'  프루닝 합계: {removed_mb:.1f} MB 제거 ({count}개 파일)')
    return removed_mb


def _clean_hf_models(src_dir: str) -> str:
    """
    hf_models 에서 실제 필요한 파일만 임시 디렉터리로 복사한다.
    - pytorch_model.bin 과 model.safetensors 둘 다 있으면 safetensors 만 유지
    - .no_exist / xet / logs 등 불필요 디렉터리 제외
    - 여러 snapshot 중 최신 1개만 유지
    반환: 정리된 임시 디렉터리 경로
    """
    import tempfile, json
    dst_dir = os.path.join(SRC, 'hf_models_clean')
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir)

    hub_src = os.path.join(src_dir, 'hub')
    hub_dst = os.path.join(dst_dir, 'hub')
    if not os.path.isdir(hub_src):
        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
        return dst_dir

    for model_dir in os.listdir(hub_src):
        if not model_dir.startswith('models--'):
            continue
        model_src = os.path.join(hub_src, model_dir)
        model_dst = os.path.join(hub_dst, model_dir)

        # refs/main 에서 최신 snapshot hash 읽기
        refs_main = os.path.join(model_src, 'refs', 'main')
        if os.path.exists(refs_main):
            with open(refs_main, encoding='utf-8') as f:
                snap_hash = f.read().strip()
        else:
            snaps = os.listdir(os.path.join(model_src, 'snapshots'))
            snap_hash = snaps[0] if snaps else None

        if not snap_hash:
            continue

        snap_src = os.path.join(model_src, 'snapshots', snap_hash)
        snap_dst = os.path.join(model_dst, 'snapshots', snap_hash)
        os.makedirs(snap_dst, exist_ok=True)

        # refs 복사
        refs_dst = os.path.join(model_dst, 'refs')
        os.makedirs(refs_dst, exist_ok=True)
        shutil.copy2(refs_main, os.path.join(refs_dst, 'main'))

        # snapshot 파일 복사 — 중복 모델 파일 정리
        has_safetensors = any(
            f.endswith('.safetensors') for f in os.listdir(snap_src)
        )
        for fname in os.listdir(snap_src):
            # pytorch_model.bin 은 safetensors 있으면 제외
            if fname == 'pytorch_model.bin' and has_safetensors:
                print(f'  [skip] {model_dir}/{fname} (safetensors 있음)')
                continue
            shutil.copy2(
                os.path.join(snap_src, fname),
                os.path.join(snap_dst, fname),
            )

        print(f'  [hf] {model_dir} → snapshot {snap_hash[:8]}…')

    # 정리 전/후 크기 비교
    def _dir_mb(d):
        total = 0
        for root, _, files in os.walk(d):
            for f in files:
                try: total += os.path.getsize(os.path.join(root, f))
                except: pass
        return total / 1024 / 1024

    before = _dir_mb(src_dir)
    after  = _dir_mb(dst_dir)
    print(f'hf_models 정리: {before:.0f} MB → {after:.0f} MB')
    return dst_dir


def build():
    # ── config 로드 (variant 설정 후) ──────────────────────────────
    _set_variant('free')
    sys.path.insert(0, SRC)
    import importlib
    import config
    importlib.reload(config)

    exe_name = config.APP_EXE_NAME
    dist_dir = os.path.abspath(os.environ.get('PDF_EDITOR_DIST_DIR', config.APP_DIST_DIR))
    version  = config.APP_VERSION
    print(f'빌드: {exe_name}  v{version}  (무료 배포)')

    clean(dist_dir)
    _prepare_stage()   # 소스를 build_stage/app 으로 복사 (PyInstaller 입력)

    jre_dir = None

    args = [
        '-m', 'PyInstaller',
        '--onedir',
        '--windowed',
        '--name', exe_name,
        '--icon',              os.path.join(STAGE_APP, 'logo.ico'),
        '--version-file',      _make_version_file(config),
        '--add-data',          f'{os.path.join(STAGE_APP, "logo.png")};.',
        '--add-data',          f'{os.path.join(STAGE_APP, "logo.ico")};.',
        '--add-data',          f'{os.path.join(STAGE_APP, "config.py")};.',
        '--add-data',          f'{os.path.join(STAGE_APP, "core")};core',
        '--add-data',          f'{os.path.join(STAGE_APP, "ui")};ui',
        '--add-data',          f'{os.path.join(STAGE_APP, "tools")};tools',
        '--add-data',          f'{os.path.join(STAGE_APP, "utils")};utils',
        '--add-data',          f'{os.path.join(STAGE_APP, "workers")};workers',
        '--add-data',          f'{os.path.join(STAGE_APP, "tessdata")};tessdata',
        '--add-data',          f'{os.path.join(STAGE_APP, "stamp1")};stamp1',
        '--collect-all',       'fitz',
        '--collect-all',       'PIL',
        '--collect-all',       'pytesseract',
        # magika(파일 위장 탐지) — onnx 모델 파일 포함.
        # onnxruntime 자체는 --collect-all 하지 않는다: quantization/tools/
        # transformers 서브모듈이 torch(1 GB)를 끌고 들어온다. PyInstaller
        # 번들 훅(hook-onnxruntime.py)이 capi/*.dll 을 수집해 주므로 충분하고,
        # CPU 추론만 쓰므로 GPU 프로바이더 DLL(~319 MB)은 빌드 후
        # _prune_dist() 에서 제거한다 (PRUNE_DIST_FILES 참고).
        '--collect-all',       'magika',
        # 표준 디지털 서명 (pyHanko) — 서명 기능 사용 시에만 지연 로딩되지만
        # 번들에는 포함돼야 한다. 서브모듈/메타데이터가 많아 collect-all 사용.
        '--collect-all',       'pyhanko',
        '--collect-all',       'pyhanko_certvalidator',
        '--collect-all',       'asn1crypto',
        '--collect-all',       'oscrypto',
        '--collect-submodules', 'cryptography',
        '--exclude-module',    'onnxruntime.quantization',
        '--exclude-module',    'onnxruntime.tools',
        '--exclude-module',    'onnxruntime.transformers',
        '--exclude-module',    'onnxruntime.training',
        '--copy-metadata',     'imagesize',
        '--copy-metadata',     'pyclipper',
        '--copy-metadata',     'python-bidi',
        '--copy-metadata',     'shapely',
        '--copy-metadata',     'pypdfium2',
        # PySide6 — 실제로 쓰는 모듈만 명시, 나머지 제외
        '--hidden-import',     'PySide6.QtCore',
        '--hidden-import',     'PySide6.QtGui',
        '--hidden-import',     'PySide6.QtWidgets',
        '--hidden-import',     'PySide6.QtPrintSupport',
        '--hidden-import',     'PySide6.QtSvg',
        '--hidden-import',     'PySide6.QtNetwork',
        '--hidden-import',     'PySide6.QtOpenGL',
        '--exclude-module',    'PySide6.Qt3DAnimation',
        '--exclude-module',    'PySide6.Qt3DCore',
        '--exclude-module',    'PySide6.Qt3DExtras',
        '--exclude-module',    'PySide6.Qt3DInput',
        '--exclude-module',    'PySide6.Qt3DLogic',
        '--exclude-module',    'PySide6.Qt3DRender',
        '--exclude-module',    'PySide6.QtBluetooth',
        '--exclude-module',    'PySide6.QtCharts',
        '--exclude-module',    'PySide6.QtDataVisualization',
        '--exclude-module',    'PySide6.QtLocation',
        '--exclude-module',    'PySide6.QtMultimedia',
        '--exclude-module',    'PySide6.QtMultimediaWidgets',
        '--exclude-module',    'PySide6.QtNfc',
        '--exclude-module',    'PySide6.QtPositioning',
        '--exclude-module',    'PySide6.QtQuick',
        '--exclude-module',    'PySide6.QtQuick3D',
        '--exclude-module',    'PySide6.QtQuickWidgets',
        '--exclude-module',    'PySide6.QtRemoteObjects',
        '--exclude-module',    'PySide6.QtSensors',
        '--exclude-module',    'PySide6.QtSerialPort',
        '--exclude-module',    'PySide6.QtSpatialAudio',
        '--exclude-module',    'PySide6.QtTextToSpeech',
        '--exclude-module',    'PySide6.QtVirtualKeyboard',
        # WebEngine — HWP 편집기(rhwp WASM)에서 사용
        '--exclude-module',    'PySide6.QtWebChannel',
        '--exclude-module',    'PySide6.QtWebEngineCore',
        '--exclude-module',    'PySide6.QtWebEngineWidgets',
        '--exclude-module',    'PySide6.QtWebSockets',
        # PIL — 쓰지 않는 이미지 포맷 플러그인 제외
        '--hidden-import',     'PIL.Image',
        '--hidden-import',     'PIL.ImageDraw',
        '--hidden-import',     'PIL.ImageFont',
        '--exclude-module',    'PIL.SgiImagePlugin',
        '--exclude-module',    'PIL.FpxImagePlugin',
        '--exclude-module',    'PIL.WmfImagePlugin',
        '--exclude-module',    'PIL.XVThumbImagePlugin',
        '--exclude-module',    'PIL.DdsImagePlugin',
        '--exclude-module',    'PIL.IcnsImagePlugin',
        # 기타 불필요 모듈
        '--exclude-module',    'unittest',
        '--exclude-module',    'xmlrpc',
        '--exclude-module',    'ftplib',
        '--exclude-module',    'imaplib',
        '--exclude-module',    'mailbox',
        '--exclude-module',    'antigravity',
        '--exclude-module',    'turtledemo',
        '--exclude-module',    'tkinter',
        # 앱에서 직접 사용하지 않는 무거운 패키지
        # cv2(133 MB): 앱 코드 어디에서도 import 하지 않음
        '--exclude-module',    'cv2',
        # paddle 계열(380 MB): requirements 에는 있으나 OCR 은 tesseract 만 사용
        '--exclude-module',    'paddle',
        '--exclude-module',    'paddleocr',
        '--exclude-module',    'paddlex',
        '--exclude-module',    'llvmlite',
        '--exclude-module',    'numba',
        '--exclude-module',    'av',
        '--exclude-module',    'scipy',
        '--exclude-module',    'pandas',
        '--exclude-module',    'sklearn',
        '--exclude-module',    'matplotlib',
        '--exclude-module',    'IPython',
        '--exclude-module',    'jupyter',
        '--exclude-module',    'notebook',
        '--distpath',          os.path.join(SRC, 'dist'),
        '--workpath',          os.path.join(SRC, 'build'),
        '--noconfirm',
    ]


    staged_tesseract = _stage_tesseract()
    if staged_tesseract:
        args += ['--add-data', f'{staged_tesseract};tesseract']

    # ── 번역 모델 번들 (선택) ─────────────────────────────────────────
    # 번들 방식 결정:
    #   BUNDLE_TRANSLATION = False  → 번역 기능 제외 (torch 제외, 빌드 용량 최소)
    #   BUNDLE_TRANSLATION = True   → torch + transformers + 모델 파일 포함
    #                                 (사전에 py -3.11 download_models.py 실행 필요)
    BUNDLE_TRANSLATION = False


    if BUNDLE_TRANSLATION:
        hf_models_dir = os.path.join(SRC, 'hf_models')
        # hf_models 중복 파일 정리 후 번들
        clean_hf_models = _clean_hf_models(hf_models_dir)
        print(f'번역 모델 번들: {clean_hf_models}')
        args += [
            # torch: collect-all 대신 필요한 서브모듈만 지정 (용량 대폭 절감)
            '--collect-submodules', 'torch',
            '--exclude-module',     'torch.distributed',
            '--exclude-module',     'torch.testing',
            '--exclude-module',     'torch.ao',
            '--exclude-module',     'torch.cuda.amp',
            '--exclude-module',     'caffe2',
            # transformers: 전체 대신 필요한 모델만
            '--collect-submodules', 'transformers',
            '--hidden-import',      'transformers.models.nllb',
            '--hidden-import',      'transformers.models.marian',
            '--hidden-import',      'transformers.models.auto',
            '--hidden-import',      'transformers.tokenization_utils',
            '--hidden-import',      'transformers.tokenization_utils_fast',
            '--collect-all',        'sentencepiece',
            '--collect-all',        'tokenizers',
            '--hidden-import',      'sentencepiece',
            '--add-data',           f'{clean_hf_models};hf_models',
        ]
        # copy-metadata (transformers 런타임 요구)
        for pkg in ('transformers', 'tokenizers', 'huggingface-hub',
                    'filelock', 'packaging', 'regex', 'requests',
                    'safetensors', 'tqdm'):
            args += ['--copy-metadata', pkg]
    else:
        # torch 제외 (번역 없는 경량 빌드)
        print('[번역] hf_models/ 없음 → torch 제외, 번역 기능 비활성')
        args += [
            '--exclude-module', 'torch',
            '--exclude-module', 'torchvision',
            '--exclude-module', 'core.annex_parser',
            '--exclude-module', 'core.ast_to_pdf',
            '--exclude-module', 'core.doc_ast',
            '--exclude-module', 'core.docx_reader',
            '--exclude-module', 'core.hwp5_parser',
            '--exclude-module', 'core.hwpx_parser',
            '--exclude-module', 'ui.hwp_panel',
            '--exclude-module', 'ui.setup_dialogs',
            '--exclude-module', 'ui.text_translate_panel',
            '--exclude-module', 'ui.translate_panel',
            '--exclude-module', 'utils.cuda_upgrade',
            '--exclude-module', 'utils.translator',
            '--exclude-module', 'workers.pdf2zh_worker',
            '--exclude-module', 'workers.translate_worker',
            '--exclude-module', 'torchaudio',
            '--exclude-module', 'transformers',
            '--exclude-module', 'sentencepiece',
            '--exclude-module', 'tokenizers',
            '--exclude-module', 'pdf2zh',
            '--exclude-module', 'opendataloader_pdf',
            '--exclude-module', 'docx',
            '--exclude-module', 'pdf2docx',
            '--exclude-module', 'olefile',
        ]

    args.append(os.path.join(STAGE_APP, 'main.py'))
    print('Running PyInstaller...')
    result = subprocess.run(PY + args)
    if result.returncode != 0:
        print('\n[ERROR] Build failed!')
        shutil.rmtree(STAGE_ROOT, ignore_errors=True)
        if jre_dir and os.path.exists(jre_dir):
            shutil.rmtree(jre_dir)
        sys.exit(1)

    # 결과물 이동
    out_dir = os.path.join(SRC, 'dist', exe_name)
    if os.path.exists(out_dir):
        shutil.move(out_dir, dist_dir)

    # 쓰이지 않는 대용량 파일 제거 (GPU 프로바이더 등)
    print('\n[프루닝]')
    _prune_dist(dist_dir)

    shutil.rmtree(STAGE_ROOT,     ignore_errors=True)
    shutil.rmtree(os.path.join(SRC, 'build'),        ignore_errors=True)
    shutil.rmtree(os.path.join(SRC, 'dist'),         ignore_errors=True)
    shutil.rmtree(os.path.join(SRC, 'hf_models_clean'), ignore_errors=True)
    if jre_dir and os.path.exists(jre_dir):
        shutil.rmtree(jre_dir)
    spec = os.path.join(SRC, f'{exe_name}.spec')
    if os.path.exists(spec):
        os.remove(spec)

    # ── 배포 점검 ────────────────────────────────────────────────────
    print('\n[배포 점검]')
    problems = _audit_dist(dist_dir)
    if problems:
        for p in problems:
            print(f'  ✗ {p}')
        print(f'\n[ERROR] 배포본에 넣으면 안 되는 것 {len(problems)}건 — 위 목록을 정리한 뒤 다시 빌드하세요.')
        sys.exit(1)
    print('  이상 없음 (실행 흔적·백업/메모·이미지 메타데이터·사용자 이름)')

    # ── 용량 분석 ────────────────────────────────────────────────────
    print('\n[용량 분석]')
    def _folder_mb(path):
        total = 0
        if not os.path.exists(path):
            return 0
        for r, _, files in os.walk(path):
            for f in files:
                try: total += os.path.getsize(os.path.join(r, f))
                except: pass
        return total / 1024 / 1024

    top = dist_dir
    entries = []
    if os.path.exists(top):
        for name in os.listdir(top):
            full = os.path.join(top, name)
            mb = _folder_mb(full) if os.path.isdir(full) else os.path.getsize(full)/1024/1024
            entries.append((mb, name))
        entries.sort(reverse=True)
        for mb, name in entries[:20]:
            print(f'  {mb:7.1f} MB  {name}')
        total_mb = sum(mb for mb, _ in entries)
        print(f'  {"─"*25}')
        print(f'  {total_mb:7.1f} MB  합계')

    print()
    print('=' * 50)
    print(f'완료!  v{version}  {"(with Java)" if jre_dir else "(no Java)"}')
    print(f'출력:  {dist_dir}')
    print(f'실행:  {exe_name}.exe')
    print('=' * 50)


if __name__ == '__main__':
    build()
