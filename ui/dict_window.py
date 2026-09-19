from __future__ import annotations

import html
import re
from urllib.parse import quote as _url_quote

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFontComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    _WEBENGINE = True
except ImportError:
    _WEBENGINE = False


_WEB_SERVICES = [
    ('📖 네이버사전', '#03C75A', '#02a84c', lambda w: f'https://dict.naver.com/search.nhn?query={_url_quote(w)}'),
    ('漢 한자사전', '#8b5cf6', '#7c3aed', lambda w: f'https://hanja.dict.naver.com/#/search?query={_url_quote(w)}'),
    ('🌐 파파고', '#00C4C9', '#00a8ad', lambda w: f'https://papago.naver.com/?sk=auto&tk=ko&st={_url_quote(w)}'),
    ('🔤 구글번역', '#4285F4', '#2a6de0', lambda w: f'https://translate.google.com/?sl=auto&tl=ko&text={_url_quote(w)}&op=translate'),
]


class _LookupTextBrowser(QTextBrowser):
    lookup_requested = Signal(str)

    def mouseReleaseEvent(self, event):
        anchor = self.anchorAt(event.pos())
        if anchor.startswith('lookup:'):
            self.lookup_requested.emit(anchor.split(':', 1)[1])
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _FavoritesDialog(QDialog):
    lookup_requested = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle('사전 즐겨찾기')
        self.resize(420, 360)
        self._build_ui()
        self.reload()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self._status = QLabel(self)
        self._status.setStyleSheet('font-weight: bold;')
        root.addWidget(self._status)

        self._list = QListWidget(self)
        self._list.itemDoubleClicked.connect(self._open_selected)
        self._list.itemSelectionChanged.connect(self._preview_selected)
        root.addWidget(self._list, 1)

        self._preview = QTextBrowser(self)
        self._preview.setMaximumHeight(130)
        root.addWidget(self._preview)

        row = QHBoxLayout()
        open_btn = QPushButton('열기', self)
        open_btn.clicked.connect(self._open_selected)
        del_btn = QPushButton('삭제', self)
        del_btn.clicked.connect(self._delete_selected)
        close_btn = QPushButton('닫기', self)
        close_btn.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(open_btn)
        row.addWidget(del_btn)
        row.addWidget(close_btn)
        root.addLayout(row)

    def _entries(self):
        return list(getattr(self._settings, 'dict_favorites', []) or [])

    def reload(self):
        self._list.clear()
        entries = self._entries()
        for entry in entries:
            word = (entry.get('word') or '').strip()
            defn = ' '.join((entry.get('definition') or '').split())
            if len(defn) > 70:
                defn = defn[:69] + '...'
            item = QListWidgetItem(f'{word}  -  {defn}')
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._list.addItem(item)
        self._status.setText(f'즐겨찾기 {len(entries)}개')
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        else:
            self._preview.clear()

    def _preview_selected(self):
        item = self._list.currentItem()
        if item is None:
            self._preview.clear()
            return
        entry = item.data(Qt.ItemDataRole.UserRole) or {}
        word = html.escape(entry.get('word', ''))
        defn = html.escape(entry.get('definition', ''))
        self._preview.setHtml(f'<h3>{word}</h3><p style="white-space:pre-wrap;">{defn}</p>')

    def _open_selected(self, *_args):
        item = self._list.currentItem()
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole) or {}
        word = (entry.get('word') or '').strip()
        if word:
            self.lookup_requested.emit(word)

    def _delete_selected(self):
        item = self._list.currentItem()
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole) or {}
        word = entry.get('word')
        entries = [e for e in self._entries() if e.get('word') != word]
        self._settings.dict_favorites = entries
        self._settings.save()
        self.reload()


class _WebPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cur_service = 0
        self._cur_word = ''
        self._cur_url = ''
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tab_bar = QWidget(self)
        tab_bar.setStyleSheet('background:#f0f0f0; border-bottom:1px solid #ccc;')
        row = QHBoxLayout(tab_bar)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(4)

        self._tab_btns: list[QPushButton] = []
        for idx, (label, bg, hover, _fn) in enumerate(_WEB_SERVICES):
            btn = QPushButton(label, tab_bar)
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setStyleSheet(
                f'QPushButton {{ background:{bg}; color:white; border-radius:4px; padding:0 12px; font-size:12px; border:none; }}'
                f'QPushButton:hover {{ background:{hover}; }}'
                f'QPushButton:checked {{ background:#333; }}'
            )
            btn.clicked.connect(lambda _=False, i=idx: self._on_tab(i))
            row.addWidget(btn)
            self._tab_btns.append(btn)

        row.addStretch(1)
        ext_btn = QPushButton('웹 브라우저로 열기', tab_bar)
        ext_btn.setFixedHeight(30)
        ext_btn.setStyleSheet(
            'QPushButton { background:#777; color:white; border-radius:4px; padding:0 10px; font-size:11px; border:none; }'
            'QPushButton:hover { background:#555; }'
        )
        ext_btn.clicked.connect(self._open_in_browser)
        row.addWidget(ext_btn)
        layout.addWidget(tab_bar)

        if _WEBENGINE:
            self._web = QWebEngineView(self)
            self._web.setUrl(QUrl('about:blank'))
            layout.addWidget(self._web, 1)
        else:
            lbl = QLabel('PySide6 WebEngine을 찾을 수 없습니다.\n웹 브라우저로 열기 버튼을 이용해 주세요.', self)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet('color:#888; font-size:13px;')
            layout.addWidget(lbl, 1)
            self._web = None

    def load(self, word: str, service_idx: int):
        self._cur_service = service_idx
        self._cur_word = word
        url = _WEB_SERVICES[service_idx][3](word)
        self._cur_url = url
        for i, btn in enumerate(self._tab_btns):
            btn.setChecked(i == service_idx)
        if self._web is not None:
            self._web.setUrl(QUrl(url))

    def _on_tab(self, idx: int):
        if self._cur_word:
            self.load(self._cur_word, idx)
        else:
            for i, btn in enumerate(self._tab_btns):
                btn.setChecked(i == idx)
            self._cur_service = idx

    def _open_in_browser(self):
        if self._cur_url:
            QDesktopServices.openUrl(QUrl(self._cur_url))

    def current_service(self) -> int:
        return self._cur_service


class DictWindow(QWidget):
    def __init__(self, settings=None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self._settings = settings
        self._history: list[tuple[str, str]] = []
        self._hist_idx = -1
        self._navigating = False
        self._cur_word = ''
        self._cur_defn = ''
        self._favorites_dlg = None
        self._child_windows: list[DictWindow] = []
        self._web_visible = False
        self._setup_ui()
        self.setWindowTitle('사전')
        self.resize(980, 560)
        fam = getattr(settings, 'dict_win_font', 'Malgun Gothic') if settings else 'Malgun Gothic'
        sz = getattr(settings, 'dict_win_font_size', 13) if settings else 13
        self._font_cb.setCurrentFont(QFont(fam))
        self._size_sb.setValue(sz)
        self.reload_sources()
        self._apply_font()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QVBoxLayout()
        top.setContentsMargins(10, 8, 10, 8)
        top.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self._btn_back = QPushButton('◀', self)
        self._btn_back.setFixedSize(28, 28)
        self._btn_back.setToolTip('이전')
        self._btn_back.setEnabled(False)
        self._btn_back.clicked.connect(self._go_back)
        row1.addWidget(self._btn_back)

        self._btn_fwd = QPushButton('▶', self)
        self._btn_fwd.setFixedSize(28, 28)
        self._btn_fwd.setToolTip('다음')
        self._btn_fwd.setEnabled(False)
        self._btn_fwd.clicked.connect(self._go_forward)
        row1.addWidget(self._btn_fwd)

        self._search_ed = QLineEdit(self)
        self._search_ed.setPlaceholderText('단어를 입력하세요')
        self._search_ed.setMinimumHeight(38)
        self._search_ed.setMinimumWidth(220)
        self._search_ed.returnPressed.connect(self._do_search)
        row1.addWidget(self._search_ed, 3)

        search_btn = QPushButton('검색', self)
        search_btn.setMinimumHeight(38)
        search_btn.clicked.connect(self._do_search)
        row1.addWidget(search_btn)

        row1.addWidget(QLabel('사전:', self))
        self._source_cb = QComboBox(self)
        self._source_cb.setMinimumHeight(36)
        self._source_cb.setMinimumWidth(200)
        self._source_cb.currentIndexChanged.connect(self._on_source_changed)
        row1.addWidget(self._source_cb)

        add_btn = QPushButton('사전 추가', self)
        add_btn.setMinimumHeight(38)
        add_btn.clicked.connect(self._add_dict_files)
        row1.addWidget(add_btn)

        self._remove_btn = QPushButton('사전 제거', self)
        self._remove_btn.setMinimumHeight(38)
        self._remove_btn.clicked.connect(self._remove_current_dict)
        row1.addWidget(self._remove_btn)

        fav_add_btn = QPushButton('즐겨찾기 추가', self)
        fav_add_btn.setMinimumHeight(38)
        fav_add_btn.clicked.connect(self._add_current_favorite)
        row1.addWidget(fav_add_btn)

        fav_list_btn = QPushButton('즐겨찾기 목록', self)
        fav_list_btn.setMinimumHeight(38)
        fav_list_btn.clicked.connect(self._open_favorites)
        row1.addWidget(fav_list_btn)

        top.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        web_style = (
            'QPushButton {{ min-height:34px; padding:0 10px; border-radius:5px; font-size:12px; background:{bg}; color:white; border:none; }}'
            'QPushButton:hover {{ background:{hv}; }}'
        )
        for idx, (label, bg, hv, _url_fn) in enumerate(_WEB_SERVICES):
            btn = QPushButton(label, self)
            btn.setStyleSheet(web_style.format(bg=bg, hv=hv))
            btn.clicked.connect(lambda _=False, i=idx: self._open_web(i))
            row2.addWidget(btn)

        self._btn_inwin = QPushButton('창 안에서 보기', self)
        self._btn_inwin.setCheckable(True)
        self._btn_inwin.setMinimumHeight(34)
        self._btn_inwin.setStyleSheet(
            'QPushButton { min-height:34px; padding:0 10px; border-radius:5px; font-size:12px; background:#555; color:white; border:none; }'
            'QPushButton:hover { background:#333; }'
            'QPushButton:checked { background:#1a5fa8; }'
        )
        self._btn_inwin.clicked.connect(self._toggle_web_panel)
        row2.addWidget(self._btn_inwin)

        row2.addStretch(1)
        row2.addWidget(QLabel('글꼴:', self))
        self._font_cb = QFontComboBox(self)
        self._font_cb.setFixedHeight(34)
        self._font_cb.setMaximumWidth(180)
        self._font_cb.currentFontChanged.connect(self._apply_font)
        row2.addWidget(self._font_cb)

        row2.addWidget(QLabel('크기:', self))
        self._size_sb = QSpinBox(self)
        self._size_sb.setRange(8, 40)
        self._size_sb.setValue(13)
        self._size_sb.setFixedSize(68, 34)
        self._size_sb.valueChanged.connect(self._apply_font)
        row2.addWidget(self._size_sb)
        top.addLayout(row2)

        root.addLayout(top)

        sep = QWidget(self)
        sep.setFixedHeight(1)
        sep.setStyleSheet('background:#ccc;')
        root.addWidget(sep)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._browser = _LookupTextBrowser(self)
        self._browser.setOpenExternalLinks(False)
        self._browser.lookup_requested.connect(self._open_related_lookup)
        self._browser.setStyleSheet('padding: 10px; background: #fff;')
        self._splitter.addWidget(self._browser)

        self._web_panel = _WebPanel(self)
        self._web_panel.hide()
        self._splitter.addWidget(self._web_panel)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 1)
        root.addWidget(self._splitter, 1)

        self._status = QLabel(self)
        self._status.setStyleSheet('padding: 2px 10px; font-size: 11px; color: #555; background: #f4f4f4; border-top: 1px solid #ddd;')
        root.addWidget(self._status)
        self._refresh_status()

    def reload_sources(self):
        from utils.dict_manager import dict_manager
        dm = dict_manager()
        active = getattr(self._settings, 'dict_active_path', '') if self._settings else ''
        previous = self._source_cb.currentData()
        self._source_cb.blockSignals(True)
        self._source_cb.clear()
        self._source_cb.addItem('전체 검색', '')
        infos = dm.source_infos()
        for info in infos:
            label = f"{info['name']} ({info['word_count']:,})"
            self._source_cb.addItem(label, info['path'])
        target = previous or active
        if not target and infos:
            target = infos[0]['path']
        idx = self._source_cb.findData(target)
        if idx < 0:
            idx = 0
        self._source_cb.setCurrentIndex(idx)
        self._source_cb.blockSignals(False)
        self._on_source_changed(self._source_cb.currentIndex())
        self._remove_btn.setEnabled(bool(self._current_source_path()))
        self._refresh_status()

    def _favorite_entries(self):
        if self._settings is None:
            return []
        entries = getattr(self._settings, 'dict_favorites', None)
        if entries is None:
            self._settings.dict_favorites = []
            return self._settings.dict_favorites
        return entries

    def _apply_font(self):
        fam = self._font_cb.currentFont().family()
        sz = self._size_sb.value()
        if self._settings:
            self._settings.dict_win_font = fam
            self._settings.dict_win_font_size = sz
            self._settings.save()
        if self._cur_word:
            self._render(self._cur_word, self._cur_defn)

    def _refresh_status(self):
        from utils.dict_manager import dict_manager
        dm = dict_manager()
        fav_n = len(self._favorite_entries())
        if dm.is_loaded:
            source_label = self._source_cb.currentText() if self._source_cb.count() else '전체 검색'
            nav = f'   [{self._hist_idx + 1} / {len(self._history)}]' if self._history else ''
            self._status.setText(f'오프라인 사전 {dm.source_count}개 | 총 {dm.word_count:,}단어 | 현재: {source_label} | 즐겨찾기 {fav_n}개{nav}')
        else:
            self._status.setText(f'오프라인 사전 미로드 | 즐겨찾기 {fav_n}개')

    def _update_nav(self):
        self._btn_back.setEnabled(self._hist_idx > 0)
        self._btn_fwd.setEnabled(self._hist_idx < len(self._history) - 1)

    def _current_source_path(self) -> str:
        return str(self._source_cb.currentData() or '')

    def _current_source_label(self) -> str:
        return self._source_cb.currentText() or '전체 검색'

    def _on_source_changed(self, _index: int):
        from utils.dict_manager import dict_manager
        path = self._current_source_path()
        dict_manager().set_active(path)
        if self._settings is not None:
            self._settings.dict_active_path = path
            if path and path not in getattr(self._settings, 'dict_paths', []):
                self._settings.dict_paths = [path] + list(getattr(self._settings, 'dict_paths', []) or [])
            self._settings.save()
        self._remove_btn.setEnabled(bool(path))
        self._refresh_status()

    def _do_search(self):
        word = self._search_ed.text().strip()
        if word:
            self.lookup(word, self._current_source_path())

    def lookup(self, word: str, source_path: str | None = None):
        from utils.dict_manager import dict_manager
        dm = dict_manager()
        source_path = str(source_path or self._current_source_path() or '')

        if not self._navigating:
            self._history = self._history[:self._hist_idx + 1]
            self._history.append((word, source_path))
            self._hist_idx = len(self._history) - 1

        self._search_ed.setText(word)
        if source_path:
            idx = self._source_cb.findData(source_path)
            if idx >= 0:
                self._source_cb.setCurrentIndex(idx)
        self._update_nav()
        self._refresh_status()

        if not dm.is_loaded:
            self._cur_word = word
            self._cur_defn = ''
            self._browser.setHtml(
                '<p style="color:#999;font-size:13px;">오프라인 사전이 로드되지 않았습니다.<br><b>사전 추가</b> 버튼으로 파일을 등록해 주세요.</p>'
            )
        else:
            defn = dm.lookup(word, source_path=source_path)
            if defn:
                self._render(word, defn)
            else:
                self._cur_word = word
                self._cur_defn = ''
                self._browser.setHtml(
                    f'<p style="font-size:14px;"><b style="color:#c33;">{html.escape(word)}</b></p>'
                    f'<p style="color:#888;">{html.escape(self._current_source_label())}에서 단어를 찾을 수 없습니다.</p>'
                )

        if self._web_visible:
            self._web_panel.load(word, self._web_panel.current_service())

        self.show()
        self.raise_()
        self.activateWindow()

    def _open_related_lookup(self, word: str):
        word = (word or '').strip()
        if not word:
            return
        child = DictWindow(settings=self._settings, parent=None)
        child.lookup(word, self._current_source_path())
        child.show()
        self._child_windows.append(child)

    def _linkify_plain_text(self, text: str) -> str:
        escaped = html.escape(text)

        def repl(match):
            token = match.group(0)
            return f'<a href="lookup:{token}" style="color:#1565C0;text-decoration:none;">{token}</a>'

        return re.sub(r"[A-Za-z][A-Za-z'-]{1,}|[가-힣]{2,}", repl, escaped)

    def _render(self, word: str, defn: str):
        self._cur_word = word
        self._cur_defn = defn
        fam = self._font_cb.currentFont().family()
        sz = self._size_sb.value()
        head = f'<h3 style="color:#1565C0;margin:0 0 8px 0;font-family:{html.escape(fam)};font-size:{sz + 3}px;">{html.escape(word)}</h3>'
        body_style = f'font-family:{html.escape(fam)};font-size:{sz}px;'

        if '<' in defn and '>' in defn:
            body = f'<div style="{body_style}">{defn}</div>'
        else:
            parts = [p.strip() for p in defn.split('  /  ') if p.strip()]
            if len(parts) <= 1:
                body = f'<p style="{body_style}margin:4px 0;">{self._linkify_plain_text(parts[0] if parts else defn)}</p>'
            else:
                items = ''.join(
                    f'<li style="margin-bottom:4px;{body_style}">{self._linkify_plain_text(p)}</li>'
                    for p in parts
                )
                body = f'<ol style="margin:0;padding-left:20px;">{items}</ol>'
        self._browser.setHtml(head + body)

    def _add_current_favorite(self):
        word = (self._cur_word or '').strip()
        defn = (self._cur_defn or '').strip()
        if not word:
            self._status.setText('즐겨찾기에 추가할 단어가 없습니다.')
            return
        entries = [e for e in self._favorite_entries() if e.get('word') != word]
        entries.insert(0, {'word': word, 'definition': defn})
        if self._settings is not None:
            self._settings.dict_favorites = entries[:200]
            self._settings.save()
        self._refresh_status()
        self._status.setText(f'즐겨찾기에 추가: {word}')
        if self._favorites_dlg is not None:
            self._favorites_dlg.reload()

    def _open_favorites(self):
        if self._favorites_dlg is None:
            self._favorites_dlg = _FavoritesDialog(self._settings, self)
            self._favorites_dlg.lookup_requested.connect(lambda word: self.lookup(word, self._current_source_path()))
        self._favorites_dlg.reload()
        self._favorites_dlg.show()
        self._favorites_dlg.raise_()
        self._favorites_dlg.activateWindow()

    def _toggle_web_panel(self):
        self._web_visible = self._btn_inwin.isChecked()
        if self._web_visible:
            self._web_panel.show()
            self.resize(max(self.width(), 1180), self.height())
            word = self._web_word()
            if word:
                self._web_panel.load(word, self._web_panel.current_service())
        else:
            self._web_panel.hide()

    def _open_web(self, service_idx: int):
        word = self._web_word()
        if not word:
            return
        if self._web_visible:
            self._web_panel.show()
            self._web_panel.load(word, service_idx)
        else:
            url = _WEB_SERVICES[service_idx][3](word)
            QDesktopServices.openUrl(QUrl(url))

    def _web_word(self) -> str:
        return (self._search_ed.text().strip() or self._cur_word or '').strip()

    def _add_dict_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            '사전 파일 추가',
            '',
            '사전 파일 (*.mdic *.mdict *.mdx *.dict *.ifo *.tsv *.txt *.json);;모든 파일 (*)',
        )
        if not paths:
            return
        from utils.dict_manager import dict_manager
        dm = dict_manager()
        current = list(getattr(self._settings, 'dict_paths', []) or []) if self._settings else []
        changed = False
        for path in paths:
            if path not in current:
                current.append(path)
                changed = True
        if not changed:
            self._status.setText('이미 등록된 사전입니다.')
            return
        ok, msg = dm.load_many(current)
        self._status.setText(msg)
        if ok and self._settings is not None:
            self._settings.dict_enabled = True
            self._settings.dict_paths = [info['path'] for info in dm.source_infos()]
            self._settings.dict_path = self._settings.dict_paths[0] if self._settings.dict_paths else ''
            self._settings.dict_active_path = paths[-1] if paths[-1] in self._settings.dict_paths else (dm.active_path or '')
            self._settings.save()
            self.reload_sources()
            idx = self._source_cb.findData(self._settings.dict_active_path)
            if idx >= 0:
                self._source_cb.setCurrentIndex(idx)

    def _remove_current_dict(self):
        target = self._current_source_path()
        if not target:
            self._status.setText('제거할 오프라인 사전을 먼저 선택해 주세요.')
            return
        from utils.dict_manager import dict_manager
        dm = dict_manager()
        ok, msg = dm.remove_path(target)
        self._status.setText(msg)
        if self._settings is not None:
            self._settings.dict_paths = [info['path'] for info in dm.source_infos()]
            self._settings.dict_path = self._settings.dict_paths[0] if self._settings.dict_paths else ''
            self._settings.dict_active_path = dm.active_path or ''
            self._settings.save()
        self.reload_sources()

    def _go_back(self):
        if self._hist_idx > 0:
            self._hist_idx -= 1
            self._navigating = True
            word, source_path = self._history[self._hist_idx]
            self.lookup(word, source_path)
            self._navigating = False

    def _go_forward(self):
        if self._hist_idx < len(self._history) - 1:
            self._hist_idx += 1
            self._navigating = True
            word, source_path = self._history[self._hist_idx]
            self.lookup(word, source_path)
            self._navigating = False

    def closeEvent(self, event):
        if self._settings:
            self._settings.save()
        super().closeEvent(event)
