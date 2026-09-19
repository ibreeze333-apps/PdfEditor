from __future__ import annotations

import json
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class _OpenAiSendWorker(QThread):
    status = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, api_key: str, model: str, pdf_path: str, prompt: str, parent=None):
        super().__init__(parent)
        self._api_key = api_key.strip()
        self._model = model.strip() or "gpt-4o"
        self._pdf_path = pdf_path
        self._prompt = prompt.strip()

    def run(self) -> None:
        try:
            pdf_path = Path(self._pdf_path)
            if not pdf_path.exists():
                raise RuntimeError(f"파일을 찾을 수 없습니다: {pdf_path}")

            headers = {
                "Authorization": f"Bearer {self._api_key}",
            }

            self.status.emit("PDF 업로드 중…")
            with pdf_path.open("rb") as fh:
                upload_resp = requests.post(
                    "https://api.openai.com/v1/files",
                    headers=headers,
                    data={"purpose": "user_data"},
                    files={"file": (pdf_path.name, fh, "application/pdf")},
                    timeout=180,
                )
            if upload_resp.status_code >= 400:
                raise RuntimeError(self._format_http_error("파일 업로드 실패", upload_resp))

            file_id = upload_resp.json().get("id", "")
            if not file_id:
                raise RuntimeError("업로드 응답에서 file_id를 찾지 못했습니다.")

            self.status.emit("AI 응답 생성 중…")
            payload = {
                "model": self._model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_file",
                                "file_id": file_id,
                            },
                            {
                                "type": "input_text",
                                "text": self._prompt,
                            },
                        ],
                    }
                ],
            }
            resp = requests.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=300,
            )
            if resp.status_code >= 400:
                raise RuntimeError(self._format_http_error("응답 생성 실패", resp))

            text = self._extract_text(resp.json())
            if not text:
                raise RuntimeError("응답 텍스트를 찾지 못했습니다.")
            self.finished_ok.emit(text)
        except Exception as exc:
            self.failed.emit(str(exc))

    @staticmethod
    def _format_http_error(prefix: str, resp: requests.Response) -> str:
        try:
            data = resp.json()
            err = data.get("error", {})
            msg = err.get("message") or json.dumps(data, ensure_ascii=False)
        except Exception:
            msg = resp.text[:1000]
        return f"{prefix}\nHTTP {resp.status_code}\n{msg}"

    @staticmethod
    def _extract_text(data: dict) -> str:
        text = data.get("output_text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        parts: list[str] = []
        for item in data.get("output", []) or []:
            for content in item.get("content", []) or []:
                if content.get("type") == "output_text":
                    value = content.get("text", "")
                    if value:
                        parts.append(value)
        return "\n\n".join(parts).strip()


class OpenAiSendDialog(QDialog):
    def __init__(self, api_key: str, model: str, pdf_path: str, prompt: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OpenAI로 PDF 보내기")
        self.resize(760, 620)
        self._worker: _OpenAiSendWorker | None = None

        layout = QVBoxLayout(self)
        info = QLabel(
            f"파일: {Path(pdf_path).name}\n"
            f"모델: {model or 'gpt-4o'}"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._status = QLabel("준비")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("모델 응답이 여기에 표시됩니다.")
        layout.addWidget(self._output, stretch=1)

        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("▶ 전송 시작")
        self._copy_btn = QPushButton("📋 결과 복사")
        self._close_btn = QPushButton("닫기")
        self._copy_btn.setEnabled(False)
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._copy_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

        self._run_btn.clicked.connect(lambda: self._start(api_key, model, pdf_path, prompt))
        self._copy_btn.clicked.connect(self._copy_output)
        self._close_btn.clicked.connect(self.accept)

    def _start(self, api_key: str, model: str, pdf_path: str, prompt: str) -> None:
        if not api_key.strip():
            QMessageBox.warning(self, "API 키 필요", "OpenAI API 키를 입력해주세요.")
            return
        if not prompt.strip():
            QMessageBox.warning(self, "프롬프트 필요", "요청 내용을 입력해주세요.")
            return

        self._run_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)
        self._output.clear()
        self._status.setText("작업 시작…")

        self._worker = _OpenAiSendWorker(api_key, model, pdf_path, prompt, self)
        self._worker.status.connect(self._status.setText)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _on_done(self, text: str) -> None:
        self._output.setPlainText(text)
        self._copy_btn.setEnabled(True)
        self._run_btn.setEnabled(True)
        self._status.setText("완료")

    def _on_error(self, err: str) -> None:
        self._run_btn.setEnabled(True)
        self._status.setText("오류")
        QMessageBox.warning(self, "OpenAI 전송 실패", err)

    def _copy_output(self) -> None:
        text = self._output.toPlainText().strip()
        if not text:
            return
        self._output.selectAll()
        self._output.copy()
