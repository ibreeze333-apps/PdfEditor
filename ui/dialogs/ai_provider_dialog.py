# ui/dialogs/ai_provider_dialog.py — AI 번역 제공자(API 키) 관리 다이얼로그
"""사용자가 직접 API 키·주소·모델을 입력/관리한다.

- 키는 입력 필드에서 가려서 표시(👁 버튼으로 확인 가능)
- 설정 파일(JSON)에 저장되므로 공용 PC에서는 주의하라는 안내를 표시
- '연결 테스트'로 짧은 번역을 실제 호출해 즉시 검증
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QListWidget, QListWidgetItem, QLineEdit, QComboBox, QPushButton,
    QLabel, QDialogButtonBox, QMessageBox, QSplitter, QWidget,
)


_PROTOCOL_LABELS = {
    'openai':    'OpenAI 호환 (ChatGPT·Groq·DeepSeek 등)',
    'anthropic': 'Anthropic (Claude)',
}


class _TestThread(QThread):
    done = Signal(bool, str)

    def __init__(self, provider: dict, parent=None):
        super().__init__(parent)
        self._provider = provider

    def run(self):
        from utils.ai_translate import test_provider
        ok, msg = test_provider(self._provider)
        self.done.emit(ok, msg)


class AiProviderDialog(QDialog):
    """제공자 목록 편집. exec() 후 providers() 로 결과를 얻는다."""

    def __init__(self, providers: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle('AI 번역 제공자 설정')
        self.setMinimumSize(720, 420)
        import copy
        self._providers: list[dict] = copy.deepcopy(providers)
        self._current = -1
        self._test_thread: _TestThread | None = None
        self._build_ui()
        self._reload_list()
        if self._providers:
            self._list.setCurrentRow(0)

    # ── UI ───────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)

        info = QLabel(
            '🔒 API 키는 Windows 계정 키로 암호화(DPAPI)되어 저장됩니다 — '
            '설정 파일을 복사해 가도 다른 PC/계정에서는 읽을 수 없습니다. '
            '같은 PC를 계정 없이 공유하는 환경에서는 사용 후 키 삭제를 권장합니다.')
        info.setWordWrap(True)
        info.setStyleSheet('color:#6b7280;')
        root.addWidget(info)

        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, stretch=1)

        # 왼쪽: 제공자 목록 + 추가/삭제
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        lv.addWidget(self._list, stretch=1)
        btn_row = QHBoxLayout()
        add_btn = QPushButton('＋ 추가')
        add_btn.clicked.connect(self._add_provider)
        del_btn = QPushButton('－ 삭제')
        del_btn.clicked.connect(self._delete_provider)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        lv.addLayout(btn_row)
        split.addWidget(left)

        # 오른쪽: 편집 폼
        right = QWidget()
        form = QFormLayout(right)
        self._name_ed = QLineEdit()
        self._name_ed.textEdited.connect(self._save_form)
        form.addRow('이름', self._name_ed)

        self._proto_cb = QComboBox()
        for key, label in _PROTOCOL_LABELS.items():
            self._proto_cb.addItem(label, key)
        self._proto_cb.currentIndexChanged.connect(self._save_form)
        form.addRow('프로토콜', self._proto_cb)

        self._url_ed = QLineEdit()
        self._url_ed.setPlaceholderText('예: https://api.openai.com/v1')
        self._url_ed.textEdited.connect(self._save_form)
        form.addRow('API 주소', self._url_ed)

        self._model_ed = QLineEdit()
        self._model_ed.setPlaceholderText('예: gpt-4o-mini')
        self._model_ed.textEdited.connect(self._save_form)
        form.addRow('모델', self._model_ed)

        key_row = QHBoxLayout()
        self._key_ed = QLineEdit()
        self._key_ed.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_ed.setPlaceholderText('API 키를 입력하세요')
        self._key_ed.textEdited.connect(self._save_form)
        key_row.addWidget(self._key_ed, stretch=1)
        self._key_show_btn = QPushButton('👁')
        self._key_show_btn.setFixedWidth(34)
        self._key_show_btn.setCheckable(True)
        self._key_show_btn.setToolTip('키 보기/가리기')
        self._key_show_btn.toggled.connect(
            lambda on: self._key_ed.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        key_row.addWidget(self._key_show_btn)
        form.addRow('API 키', key_row)

        self._test_btn = QPushButton('🔌 연결 테스트')
        self._test_btn.clicked.connect(self._run_test)
        self._test_lbl = QLabel(' ')
        self._test_lbl.setWordWrap(True)
        form.addRow(self._test_btn, self._test_lbl)

        hint = QLabel(
            '무료/저가 API 팁: OpenAI 호환 프로토콜을 쓰는 서비스라면 주소만 바꿔서 '
            '쓸 수 있습니다 (Groq, DeepSeek, OpenRouter, 로컬 LM Studio 등).')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#6b7280; font-size:11px;')
        form.addRow(hint)

        split.addWidget(right)
        split.setSizes([220, 480])

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    # ── 목록 관리 ────────────────────────────────────────────────────
    def _reload_list(self):
        self._list.blockSignals(True)
        self._list.clear()
        for p in self._providers:
            has_key = '🔑 ' if (p.get('api_key') or '').strip() else '· '
            self._list.addItem(QListWidgetItem(has_key + p.get('name', '(이름 없음)')))
        self._list.blockSignals(False)

    def _on_row_changed(self, row: int):
        self._current = row
        if not (0 <= row < len(self._providers)):
            return
        p = self._providers[row]
        for w in (self._name_ed, self._url_ed, self._model_ed, self._key_ed):
            w.blockSignals(True)
        self._proto_cb.blockSignals(True)
        self._name_ed.setText(p.get('name', ''))
        idx = self._proto_cb.findData(p.get('protocol', 'openai'))
        self._proto_cb.setCurrentIndex(max(0, idx))
        self._url_ed.setText(p.get('base_url', ''))
        self._model_ed.setText(p.get('model', ''))
        self._key_ed.setText(p.get('api_key', ''))
        for w in (self._name_ed, self._url_ed, self._model_ed, self._key_ed):
            w.blockSignals(False)
        self._proto_cb.blockSignals(False)
        self._test_lbl.setText(' ')

    def _save_form(self, *_args):
        row = self._current
        if not (0 <= row < len(self._providers)):
            return
        p = self._providers[row]
        p['name']     = self._name_ed.text().strip()
        p['protocol'] = self._proto_cb.currentData()
        p['base_url'] = self._url_ed.text().strip()
        p['model']    = self._model_ed.text().strip()
        p['api_key']  = self._key_ed.text().strip()
        # 목록 라벨 갱신 (선택 유지)
        item = self._list.item(row)
        if item is not None:
            has_key = '🔑 ' if p['api_key'] else '· '
            item.setText(has_key + (p['name'] or '(이름 없음)'))

    def _add_provider(self):
        self._providers.append({
            'name': '새 제공자',
            'protocol': 'openai',
            'base_url': '',
            'api_key': '',
            'model': '',
        })
        self._reload_list()
        self._list.setCurrentRow(len(self._providers) - 1)

    def _delete_provider(self):
        row = self._current
        if not (0 <= row < len(self._providers)):
            return
        name = self._providers[row].get('name', '')
        ans = QMessageBox.question(
            self, '제공자 삭제',
            f"'{name}' 을(를) 삭제하시겠습니까?\n저장된 API 키도 함께 삭제됩니다.")
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._providers.pop(row)
        self._reload_list()
        if self._providers:
            self._list.setCurrentRow(min(row, len(self._providers) - 1))
        else:
            self._current = -1

    # ── 연결 테스트 ──────────────────────────────────────────────────
    def _run_test(self):
        row = self._current
        if not (0 <= row < len(self._providers)):
            return
        self._save_form()
        self._test_btn.setEnabled(False)
        self._test_lbl.setText('⏳ 테스트 중…')
        self._test_thread = _TestThread(dict(self._providers[row]), self)
        self._test_thread.done.connect(self._on_test_done)
        self._test_thread.start()

    def _on_test_done(self, ok: bool, msg: str):
        self._test_btn.setEnabled(True)
        icon = '✅' if ok else '⚠'
        self._test_lbl.setText(f'{icon} {msg[:200]}')

    # ── 결과 ─────────────────────────────────────────────────────────
    def providers(self) -> list[dict]:
        return self._providers
