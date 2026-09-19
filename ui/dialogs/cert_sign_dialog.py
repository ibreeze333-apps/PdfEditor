# ui/dialogs/cert_sign_dialog.py — 표준 인증서 기반 디지털 서명 설정
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QRadioButton, QCheckBox, QComboBox, QSpinBox, QPushButton, QFileDialog,
    QDialogButtonBox, QGroupBox, QWidget,
)


class CertSignDialog(QDialog):
    """인증서(.p12/.pfx)로 PDF에 표준 디지털 서명을 넣기 위한 설정."""

    _POSITIONS = [('오른쪽 아래', 'br'), ('왼쪽 아래', 'bl'),
                  ('오른쪽 위', 'tr'), ('왼쪽 위', 'tl')]

    def __init__(self, parent=None, default_name: str = ''):
        super().__init__(parent)
        self.setWindowTitle('✒ 디지털 서명 (인증서)')
        self.setMinimumWidth(480)
        ly = QVBoxLayout(self)

        info = QLabel(
            '표준 PKCS#7 디지털 서명을 넣습니다. 서명 후 문서가 바뀌면 다른 '
            'PDF 뷰어(Acrobat 등)에서 "변조됨"으로 표시되어 위·변조를 확인할 수 '
            '있습니다. 서명된 <b>사본</b>이 새로 저장됩니다.')
        info.setWordWrap(True); info.setStyleSheet('color:#444;')
        ly.addWidget(info)

        # ── 인증서 선택 ───────────────────────────────────────────
        src_box = QGroupBox('인증서')
        sg = QGridLayout(src_box)
        self._rb_file = QRadioButton('기존 인증서 파일(.p12/.pfx)')
        self._rb_new = QRadioButton('새 자체 서명 인증서 만들기')
        self._rb_file.setChecked(True)
        self._rb_file.toggled.connect(self._sync)
        sg.addWidget(self._rb_file, 0, 0, 1, 3)
        # 파일
        self._file_ed = QLineEdit()
        self._file_btn = QPushButton('찾아보기')
        self._file_btn.clicked.connect(self._pick_p12)
        sg.addWidget(QLabel('   파일'), 1, 0)
        sg.addWidget(self._file_ed, 1, 1)
        sg.addWidget(self._file_btn, 1, 2)
        # 새 인증서
        sg.addWidget(self._rb_new, 2, 0, 1, 3)
        self._name_ed = QLineEdit(default_name)
        self._org_ed = QLineEdit()
        sg.addWidget(QLabel('   이름'), 3, 0); sg.addWidget(self._name_ed, 3, 1, 1, 2)
        sg.addWidget(QLabel('   소속'), 4, 0); sg.addWidget(self._org_ed, 4, 1, 1, 2)
        # 암호 (공통)
        self._pw_ed = QLineEdit(); self._pw_ed.setEchoMode(QLineEdit.EchoMode.Password)
        sg.addWidget(QLabel('인증서 암호'), 5, 0); sg.addWidget(self._pw_ed, 5, 1, 1, 2)

        # ── 다른 프로그램과의 호환 ────────────────────────────────
        # 알PDF·Acrobat 등은 서명용 ID 를 파일이 아니라 Windows 인증서
        # 저장소에서 가져오고, 받는 쪽이 서명을 '유효'로 보려면 개인키가
        # 빠진 공개 인증서를 따로 줘야 한다. 둘 다 여기서 처리한다.
        self._install_cb = QCheckBox(
            'Windows 인증서 저장소에 설치 — 알PDF·Acrobat 등에서도 이 인증서로 서명')
        self._install_cb.setToolTip(
            '현재 사용자의 [개인] 저장소에 넣습니다.\n'
            '다른 PDF 프로그램의 "디지털 ID 목록"에 이 인증서가 나타납니다.')
        self._export_cb = QCheckBox(
            '배포용 공개 인증서(.p7b) 함께 저장 — 받는 쪽이 서명을 신뢰하려면 필요')
        self._export_cb.setToolTip(
            '개인키가 빠진 인증서만 들어 있어 안전하게 건넬 수 있습니다.\n'
            '상대가 이 파일을 인증서 관리에 등록하면 서명이 "유효"로 바뀝니다.\n'
            '※ .p12 파일 자체는 개인키가 들어 있으므로 절대 남에게 주지 마세요.')
        sg.addWidget(self._install_cb, 6, 0, 1, 3)
        sg.addWidget(self._export_cb, 7, 0, 1, 3)
        ly.addWidget(src_box)

        # ── 서명 정보 ─────────────────────────────────────────────
        meta_box = QGroupBox('서명 정보 (선택)')
        mg = QGridLayout(meta_box)
        self._reason_ed = QLineEdit()
        self._reason_ed.setPlaceholderText('예: 계약 승인')
        self._loc_ed = QLineEdit()
        mg.addWidget(QLabel('사유'), 0, 0); mg.addWidget(self._reason_ed, 0, 1)
        mg.addWidget(QLabel('위치'), 1, 0); mg.addWidget(self._loc_ed, 1, 1)
        ly.addWidget(meta_box)

        # ── 보이는 서명 ───────────────────────────────────────────
        vis_row = QHBoxLayout()
        self._vis_cb = QCheckBox('현재 페이지에 서명 도장 표시')
        self._vis_cb.setChecked(True)
        self._vis_cb.toggled.connect(self._sync)
        vis_row.addWidget(self._vis_cb)
        vis_row.addWidget(QLabel('위치'))
        self._pos_cb = QComboBox()
        for label, _ in self._POSITIONS:
            self._pos_cb.addItem(label)
        vis_row.addWidget(self._pos_cb)
        vis_row.addStretch(1)
        ly.addLayout(vis_row)

        # 도장 크기·투명도 — 기본 크기가 본문을 가리는 일이 잦아서 조절 가능하게.
        size_row = QHBoxLayout()
        size_row.addSpacing(20)
        size_row.addWidget(QLabel('도장 크기'))
        self._size_sb = QSpinBox()
        self._size_sb.setRange(40, 400); self._size_sb.setValue(130)
        self._size_sb.setSuffix(' pt')
        self._size_sb.setToolTip('가로 너비 기준. 세로는 비율에 맞춰 정해집니다.')
        size_row.addWidget(self._size_sb)
        size_row.addSpacing(12)
        size_row.addWidget(QLabel('투명도'))
        self._opacity_sb = QSpinBox()
        self._opacity_sb.setRange(10, 100); self._opacity_sb.setValue(100)
        self._opacity_sb.setSuffix(' %')
        self._opacity_sb.setToolTip('낮출수록 도장이 비쳐서 가려진 본문이 보입니다.')
        size_row.addWidget(self._opacity_sb)
        size_row.addStretch(1)
        ly.addLayout(size_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('서명하고 저장…')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)
        self._sync()

    def _sync(self):
        use_file = self._rb_file.isChecked()
        self._file_ed.setEnabled(use_file)
        self._file_btn.setEnabled(use_file)
        self._name_ed.setEnabled(not use_file)
        self._org_ed.setEnabled(not use_file)
        vis = self._vis_cb.isChecked()
        self._pos_cb.setEnabled(vis)
        self._size_sb.setEnabled(vis)
        self._opacity_sb.setEnabled(vis)

    def _pick_p12(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '인증서 파일 선택', '',
            'PKCS#12 인증서 (*.p12 *.pfx)')
        if path:
            self._file_ed.setText(path)

    # 접근자
    def use_existing(self) -> bool:
        return self._rb_file.isChecked()

    def p12_path(self) -> str:
        return self._file_ed.text().strip()

    def new_name(self) -> str:
        return self._name_ed.text().strip()

    def new_org(self) -> str:
        return self._org_ed.text().strip()

    def password(self) -> str:
        return self._pw_ed.text()

    def reason(self) -> str:
        return self._reason_ed.text().strip()

    def location(self) -> str:
        return self._loc_ed.text().strip()

    def visible(self) -> bool:
        return self._vis_cb.isChecked()

    def position(self) -> str:
        return self._POSITIONS[self._pos_cb.currentIndex()][1]

    def stamp_width(self) -> float:
        """도장 가로 너비(pt). 세로는 190:60 비율을 유지한다."""
        return float(self._size_sb.value())

    def stamp_opacity(self) -> float:
        """0.1 ~ 1.0"""
        return max(0.1, min(1.0, self._opacity_sb.value() / 100.0))

    def install_to_store(self) -> bool:
        return self._install_cb.isChecked()

    def export_public(self) -> bool:
        return self._export_cb.isChecked()
