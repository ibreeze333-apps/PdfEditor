# ui/dialogs/split_pdf_dialog.py — PDF 분할
from __future__ import annotations
import os
import tempfile
import shutil
from pathlib import Path
import fitz
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QSpinBox, QDialogButtonBox, QFileDialog, QMessageBox,
)


class SplitOutputMixin:
    @staticmethod
    def _path_key(path):
        return os.path.normcase(str(Path(path).resolve()))

    def _choose_output(self, path, reserved, source):
        while True:
            key = self._path_key(path)
            is_source = bool(source) and (key == self._path_key(source) or
                (path.exists() and Path(source).exists() and os.path.samefile(path, source)))
            occupied = path.exists() or path.is_symlink() or key in reserved or is_source
            if not occupied:
                return path, False
            overwrite_allowed = path.is_file() and key not in reserved and not is_source
            choice = self._ask_collision(path, overwrite_allowed)
            if choice == 'overwrite' and overwrite_allowed:
                return path, True
            if choice == 'number':
                base = path
                number = 2
                while True:
                    path = base.with_name(f'{base.stem}_{number}{base.suffix}')
                    if (not path.exists() and not path.is_symlink()
                            and self._path_key(path) not in reserved
                            and (not source or self._path_key(path) != self._path_key(source))):
                        return path, False
                    number += 1
            elif choice == 'rename':
                name, _ = QFileDialog.getSaveFileName(
                    self, '분할 PDF를 다른 이름으로 저장', str(path), 'PDF 파일 (*.pdf)',
                    options=QFileDialog.Option.DontConfirmOverwrite)
                if not name:
                    return None
                path = Path(name)
                if path.suffix.lower() != '.pdf':
                    path = Path(str(path) + '.pdf')
                # Recheck even after Save As; choosing another existing file is not consent.
            else:
                return None

    def _ask_collision(self, path, overwrite_allowed):
        box = QMessageBox(self)
        box.setWindowTitle('분할 PDF 이름 중복')
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText('같은 이름의 파일이 있거나 이미 사용 중인 저장 경로입니다.')
        box.setInformativeText(str(path) + '\n\n저장 방법을 선택해 주세요.' +
            ('' if overwrite_allowed else '\n원본 문서나 이번 분할의 다른 결과는 덮어쓸 수 없습니다.'))
        overwrite = box.addButton('덮어쓰기', QMessageBox.ButtonRole.DestructiveRole)
        overwrite.setEnabled(overwrite_allowed)
        rename = box.addButton('다른 이름으로 저장', QMessageBox.ButtonRole.ActionRole)
        number = box.addButton('순번 붙여 저장', QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton('취소', QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(number)
        box.setEscapeButton(cancel)
        box.exec()
        return {overwrite: 'overwrite', rename: 'rename', number: 'number'}.get(box.clickedButton())

    @staticmethod
    def _save_output(doc, path, overwrite, **save_options):
        fd, temporary = tempfile.mkstemp(prefix='.pdf-split-', suffix='.pdf', dir=path.parent)
        os.close(fd)
        try:
            doc.save(temporary, **save_options)
            if overwrite:
                os.replace(temporary, path)
            else:
                # Atomic no-clobber publication, including a file created after the dialog.
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    raise
                except OSError:
                    # FAT/exFAT and some network shares do not support hard links.
                    # Exclusive creation still protects a file appearing meanwhile.
                    with open(path, 'xb') as target:
                        try:
                            with open(temporary, 'rb') as source:
                                shutil.copyfileobj(source, target)
                        except Exception:
                            target.close()
                            path.unlink()
                            raise
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)



class SplitPdfDialog(SplitOutputMixin, QDialog):
    def __init__(self, page_count: int, parent=None):
        super().__init__(parent)
        self._page_count = page_count
        self.setWindowTitle('PDF 분할')
        self.setMinimumWidth(380)

        ly = QVBoxLayout(self)

        mode_ly = QHBoxLayout()
        mode_ly.addWidget(QLabel('분할 방식:'))
        self._mode_cb = QComboBox()
        self._mode_cb.addItems(['페이지마다 1개', '범위 지정'])
        self._mode_cb.currentIndexChanged.connect(self._on_mode)
        mode_ly.addWidget(self._mode_cb)
        ly.addLayout(mode_ly)

        # 범위 지정 입력 (예: 1-3, 4-6, 7)
        self._range_lbl = QLabel('범위 (예: 1-3,4-6,7):')
        self._range_ed  = QLineEdit()
        self._range_lbl.setVisible(False)
        self._range_ed.setVisible(False)
        ly.addWidget(self._range_lbl)
        ly.addWidget(self._range_ed)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)

    def _on_mode(self, idx: int):
        show = idx == 1
        self._range_lbl.setVisible(show)
        self._range_ed.setVisible(show)

    def split(self, src_doc: fitz.Document):
        try:
            groups = ([[i] for i in range(self._page_count)]
                      if self._mode_cb.currentIndex() == 0
                      else self._parse_ranges(self._range_ed.text().strip()))
            if not groups or any(not g or min(g) < 0 or max(g) >= src_doc.page_count
                                 for g in groups):
                raise ValueError('문서의 페이지 범위 안에서 입력해 주세요.')
        except ValueError as error:
            QMessageBox.warning(self, '범위 확인', str(error))
            return

        folder = QFileDialog.getExistingDirectory(self, '저장 폴더')
        if not folder:
            return
        # Resolve the complete batch before writing: cancel never saves half a batch.
        planned = []
        reserved = set()
        for i, pages in enumerate(groups, 1):
            name = (f'page_{i:04d}.pdf' if self._mode_cb.currentIndex() == 0
                    else f'split_{i:03d}.pdf')
            choice = self._choose_output(Path(folder) / name, reserved, src_doc.name)
            if choice is None:
                return
            path, overwrite = choice
            reserved.add(self._path_key(path))
            planned.append((pages, path, overwrite))

        saved = []
        try:
            for pages, path, overwrite in planned:
                # Render first; never truncate an existing PDF during generation.
                with fitz.open() as new_doc:
                    for p in pages:
                        new_doc.insert_pdf(src_doc, from_page=p, to_page=p)
                    self._save_output(new_doc, path, overwrite, garbage=4,
                                      deflate=True, deflate_images=True,
                                      deflate_fonts=True)
                saved.append(str(path))
        except Exception as error:
            detail = '\n'.join(saved) or '없음'
            QMessageBox.critical(self, '분할 저장 실패',
                                 f'저장하지 못했습니다:\n{error}\n\n이미 저장된 파일:\n{detail}')
            return
        QMessageBox.information(self, '완료',
                                f'분할 완료: {len(saved)}개 파일\n\n' + '\n'.join(saved))

    @staticmethod
    def _parse_ranges(raw: str) -> list[list[int]]:
        result = []
        for part in raw.split(','):
            part = part.strip()
            if '-' in part:
                a, b = part.split('-', 1)
                result.append(list(range(int(a) - 1, int(b))))
            elif part.isdigit():
                result.append([int(part) - 1])
            else:
                raise ValueError('범위를 1-3,4-6,7 형식으로 입력해 주세요.')
        return result
