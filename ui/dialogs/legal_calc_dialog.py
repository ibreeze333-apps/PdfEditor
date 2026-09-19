# ui/dialogs/legal_calc_dialog.py — 법률 계산기 (날짜/판결이자/변호사보수/가압류/양육비/유류분/변제충당)
from __future__ import annotations
from datetime import date, timedelta

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QDoubleSpinBox, QSpinBox, QComboBox,
    QDateEdit, QTextEdit, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView,
)


class LegalCalcDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('법률 계산기')
        self.setMinimumSize(640, 560)

        tabs = QTabWidget()
        tabs.addTab(self._make_date_tab(),          '📅 날짜 계산')
        tabs.addTab(self._make_interest_tab(),      '⚖ 판결문 이자')
        tabs.addTab(self._make_attorney_fee_tab(),  '👔 변호사보수')
        tabs.addTab(self._make_attachment_tab(),    '🔒 가압류 비용')
        tabs.addTab(self._make_child_support_tab(), '👶 양육비')
        tabs.addTab(self._make_forced_share_tab(),  '🏠 유류분')
        tabs.addTab(self._make_payment_alloc_tab(), '💰 변제충당')

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        close_btn = QPushButton('닫기')
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn)

    # ── 공통 유틸 ──────────────────────────────────────────────────────────
    @staticmethod
    def _fmt_money(amount: float) -> str:
        won = round(amount)
        man = won // 10000
        rem = won % 10000
        if man > 0:
            return f'{won:,}원 ({man:,}만원)' if rem == 0 else f'{won:,}원 ({man:,}만 {rem:,}원)'
        return f'{won:,}원'

    @staticmethod
    def _result_box(height: int = 160) -> QTextEdit:
        t = QTextEdit()
        t.setReadOnly(True)
        t.setMaximumHeight(height)
        t.setFontFamily('Consolas')
        return t

    @staticmethod
    def _money_spin(max_val: float = 999_999_999_999) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(0, max_val)
        s.setSuffix(' 원')
        s.setGroupSeparatorShown(True)
        s.setDecimals(0)
        return s

    # ══════════════════════════════════════════════════════════════════════
    # 1. 날짜 계산
    # ══════════════════════════════════════════════════════════════════════
    def _make_date_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        # 기간 계산
        grp1 = QGroupBox('두 날짜 사이 기간')
        f1 = QFormLayout(grp1)
        self._d_from = QDateEdit(QDate.currentDate()); self._d_from.setCalendarPopup(True)
        self._d_to   = QDateEdit(QDate.currentDate()); self._d_to.setCalendarPopup(True)
        f1.addRow('시작일:', self._d_from)
        f1.addRow('종료일:', self._d_to)
        b1 = QPushButton('계산'); b1.clicked.connect(self._calc_date_diff)
        f1.addRow(b1)
        self._d_diff_res = self._result_box(90)
        lay.addWidget(grp1)
        lay.addWidget(self._d_diff_res)

        # 날짜 가산
        grp2 = QGroupBox('날짜 가산 / 감산')
        f2 = QFormLayout(grp2)
        self._d_base = QDateEdit(QDate.currentDate()); self._d_base.setCalendarPopup(True)
        self._d_add  = QSpinBox(); self._d_add.setRange(-36500, 36500); self._d_add.setSuffix(' 일')
        f2.addRow('기준일:', self._d_base)
        f2.addRow('가산일수 (음수=감산):', self._d_add)
        b2 = QPushButton('계산'); b2.clicked.connect(self._calc_date_add)
        f2.addRow(b2)
        self._d_add_res = self._result_box(70)
        lay.addWidget(grp2)
        lay.addWidget(self._d_add_res)
        lay.addStretch()
        return w

    def _calc_date_diff(self):
        s = self._d_from.date().toPython()
        e = self._d_to.date().toPython()
        if s > e: s, e = e, s
        days = (e - s).days
        months = (e.year - s.year) * 12 + (e.month - s.month)
        self._d_diff_res.setPlainText(
            f'총 일수:   {days:,}일\n'
            f'주수:      {days // 7}주 {days % 7}일\n'
            f'개월수:    {months}개월 (근사)\n'
            f'연수:      {months // 12}년 {months % 12}개월 (근사)')

    def _calc_date_add(self):
        base = self._d_base.date().toPython()
        days = self._d_add.value()
        res  = base + timedelta(days=days)
        verb = '더한' if days >= 0 else '뺀'
        self._d_add_res.setPlainText(
            f'{base}  {days:+}일  →  {res}\n'
            f'({abs(days)}일을 {verb} 날짜)')

    # ══════════════════════════════════════════════════════════════════════
    # 2. 판결문 이자 계산기
    # ══════════════════════════════════════════════════════════════════════
    def _make_interest_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._int_principal = self._money_spin()
        self._int_rate_type = QComboBox()
        self._int_rate_type.addItems([
            '민사법정이율  5%',
            '상사법정이율  6%',
            '소촉법 현행  12%  (2019.06.01~)',
            '소촉법 구법  15%  (2015.10~2019.05)',
            '소촉법 구구법 20% (~2015.09)',
            '직접 입력',
        ])
        self._int_rate_type.currentIndexChanged.connect(
            lambda i: self._int_custom_rate.setEnabled(i == 5))

        self._int_custom_rate = QDoubleSpinBox()
        self._int_custom_rate.setRange(0.01, 100.0)
        self._int_custom_rate.setValue(5.0)
        self._int_custom_rate.setSuffix(' %')
        self._int_custom_rate.setEnabled(False)

        self._int_start = QDateEdit(QDate.currentDate()); self._int_start.setCalendarPopup(True)
        self._int_end   = QDateEdit(QDate.currentDate()); self._int_end.setCalendarPopup(True)
        self._int_basis = QComboBox(); self._int_basis.addItems(['365일 기준', '360일 기준'])

        f.addRow('원금:', self._int_principal)
        f.addRow('이율 유형:', self._int_rate_type)
        f.addRow('직접입력 이율:', self._int_custom_rate)
        f.addRow('기산일:', self._int_start)
        f.addRow('종기일 (지급일):', self._int_end)
        f.addRow('연 기준:', self._int_basis)

        btn = QPushButton('이자 계산')
        btn.clicked.connect(self._calc_interest)
        self._int_res = self._result_box(150)

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._int_res)
        return w

    _INT_RATES = [5.0, 6.0, 12.0, 15.0, 20.0]

    def _calc_interest(self):
        p    = self._int_principal.value()
        idx  = self._int_rate_type.currentIndex()
        rate = self._int_custom_rate.value() if idx == 5 else self._INT_RATES[idx]
        s    = self._int_start.date().toPython()
        e    = self._int_end.date().toPython()
        if s > e: s, e = e, s
        days    = (e - s).days
        basis   = 365 if self._int_basis.currentIndex() == 0 else 360
        interest = p * rate / 100 * days / basis
        self._int_res.setPlainText(
            f'원금:       {self._fmt_money(p)}\n'
            f'이율:       연 {rate}%\n'
            f'기간:       {s} ~ {e}  ({days}일 / {basis}일 기준)\n'
            f'{"─"*45}\n'
            f'지연손해금: {self._fmt_money(interest)}\n'
            f'원금+이자:  {self._fmt_money(p + interest)}')

    # ══════════════════════════════════════════════════════════════════════
    # 3. 변호사보수 계산기
    # ══════════════════════════════════════════════════════════════════════
    def _make_attorney_fee_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._atty_amount = self._money_spin()
        f.addRow('소송목적물 가액:', self._atty_amount)

        btn = QPushButton('계산')
        btn.clicked.connect(self._calc_attorney_fee)
        self._atty_res = self._result_box(100)

        info = QLabel(
            '※ 민사소송비용 산입 변호사보수 (법원규칙 별표)\n'
            '  2천만 이하→10%  / 2천~5천만→8%  / 5천~1억→6%\n'
            '  1억~1.5억→4%   / 1.5억~2억→2%  / 2억~5억→1%  / 5억 초과→0.5%')
        info.setStyleSheet('color: gray; font-size: 11px;')

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._atty_res)
        lay.addWidget(info)
        lay.addStretch()
        return w

    @staticmethod
    def _attorney_fee_calc(amount: float) -> float:
        brackets = [
            (20_000_000,   0.10),
            (50_000_000,   0.08),
            (100_000_000,  0.06),
            (150_000_000,  0.04),
            (200_000_000,  0.02),
            (500_000_000,  0.01),
            (float('inf'), 0.005),
        ]
        fee, prev = 0.0, 0.0
        for limit, rate in brackets:
            if amount <= limit:
                fee += (amount - prev) * rate
                break
            fee += (limit - prev) * rate
            prev = limit
        return fee

    def _calc_attorney_fee(self):
        amt = self._atty_amount.value()
        fee = self._attorney_fee_calc(amt)
        self._atty_res.setPlainText(
            f'소송목적물 가액:        {self._fmt_money(amt)}\n'
            f'{"─"*45}\n'
            f'소송비용 산입 변호사보수: {self._fmt_money(fee)}')

    # ══════════════════════════════════════════════════════════════════════
    # 4. 가압류 비용 계산기
    # ══════════════════════════════════════════════════════════════════════
    def _make_attachment_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._att_amount  = self._money_spin()
        self._att_type    = QComboBox()
        self._att_type.addItems(['부동산 가압류', '채권 가압류', '동산 가압류'])
        self._att_parties = QSpinBox()
        self._att_parties.setRange(1, 10); self._att_parties.setValue(2)
        self._att_parties.setSuffix(' 명 (원고+피고)')

        f.addRow('청구채권 금액:', self._att_amount)
        f.addRow('가압류 유형:', self._att_type)
        f.addRow('당사자 수:', self._att_parties)

        btn = QPushButton('계산')
        btn.clicked.connect(self._calc_attachment)
        self._att_res = self._result_box(200)

        info = QLabel('※ 예상치입니다. 법원 접수 전 확인하세요.')
        info.setStyleSheet('color: gray; font-size: 11px;')

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._att_res)
        lay.addWidget(info)
        lay.addStretch()
        return w

    def _calc_attachment(self):
        amt      = self._att_amount.value()
        att_type = self._att_type.currentText()
        parties  = self._att_parties.value()

        # 인지대: 소송목적물가액 × 0.45% ÷ 10, 최소 1,000원, 최대 100,000원
        stamp    = max(1_000, min(100_000, amt * 0.0045 / 10))
        # 송달료: 3,700원 × 5회 × 당사자 수  (2024 기준)
        delivery = 3_700 * 5 * parties
        # 등록면허세 (부동산 가압류): 채권금액의 0.2%, 최소 3,000원
        reg_tax  = max(3_000, amt * 0.002) if att_type == '부동산 가압류' else 0
        edu_tax  = reg_tax * 0.2
        # 법원보관금(담보): 청구금액의 1/10
        deposit  = amt / 10

        total_cost = stamp + delivery + reg_tax + edu_tax
        lines = [
            f'청구채권액:    {self._fmt_money(amt)}',
            f'{"─"*45}',
            f'[신청 비용]',
            f'인지대:        {self._fmt_money(stamp)}',
            f'송달료:        {self._fmt_money(delivery)}  ({parties}명 × 5회)',
        ]
        if att_type == '부동산 가압류':
            lines += [
                f'등록면허세:    {self._fmt_money(reg_tax)}  (채권액 × 0.2%)',
                f'지방교육세:    {self._fmt_money(edu_tax)}  (등록면허세 × 20%)',
            ]
        lines += [
            f'{"─"*45}',
            f'소계 (실비용): {self._fmt_money(total_cost)}',
            f'{"─"*45}',
            f'[담보 제공]',
            f'법원보관금:    {self._fmt_money(deposit)}  (청구액의 약 1/10)',
            f'  ※ 현금공탁 기준. 지급보증보험 이용 시 보험료만 납부',
        ]
        self._att_res.setPlainText('\n'.join(lines))

    # ══════════════════════════════════════════════════════════════════════
    # 5. 양육비 계산기
    # ══════════════════════════════════════════════════════════════════════
    def _make_child_support_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._cs_income_total = QDoubleSpinBox()
        self._cs_income_total.setRange(0, 100_000); self._cs_income_total.setValue(400)
        self._cs_income_total.setSuffix(' 만원/월')

        self._cs_income_nc = QDoubleSpinBox()
        self._cs_income_nc.setRange(0, 100_000); self._cs_income_nc.setValue(200)
        self._cs_income_nc.setSuffix(' 만원/월')

        self._cs_age      = QComboBox()
        self._cs_age.addItems(['0-2세', '3-5세', '6-8세', '9-11세', '12-14세', '15-17세'])
        self._cs_children = QSpinBox()
        self._cs_children.setRange(1, 10); self._cs_children.setValue(1)
        self._cs_children.setSuffix(' 명')

        f.addRow('부모 합산 월소득:', self._cs_income_total)
        f.addRow('비양육자 월소득:', self._cs_income_nc)
        f.addRow('자녀 연령:', self._cs_age)
        f.addRow('자녀 수:', self._cs_children)

        btn = QPushButton('양육비 산정')
        btn.clicked.connect(self._calc_child_support)
        self._cs_res = self._result_box(150)

        info = QLabel('※ 서울가정법원 양육비 산정기준표 (2021) 기준\n   실제 법원 결정과 다를 수 있습니다.')
        info.setStyleSheet('color: gray; font-size: 11px;')

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._cs_res)
        lay.addWidget(info)
        lay.addStretch()
        return w

    # 서울가정법원 양육비 산정기준표 2021 (단위: 만원/월, 자녀 1인 기준)
    # 행: 부모 합산 소득 상한(만원)  열: [0-2, 3-5, 6-8, 9-11, 12-14, 15-17]
    _CS_TABLE = [
        (199,  [ 68,  73,  79,  84,  91, 104]),
        (299,  [ 82,  88,  97, 101, 110, 125]),
        (399,  [ 96, 103, 113, 118, 128, 146]),
        (499,  [111, 119, 131, 136, 148, 169]),
        (599,  [126, 135, 148, 154, 168, 191]),
        (699,  [141, 151, 166, 172, 188, 213]),
        (799,  [156, 167, 184, 191, 208, 235]),
        (899,  [171, 183, 202, 209, 228, 258]),
        (999,  [186, 199, 219, 227, 248, 280]),
        (9999, [201, 215, 237, 246, 268, 303]),
    ]

    def _calc_child_support(self):
        income_total = self._cs_income_total.value()
        income_nc    = self._cs_income_nc.value()
        age_idx      = self._cs_age.currentIndex()
        n_children   = self._cs_children.value()

        std = 0
        for limit, row in self._CS_TABLE:
            if income_total <= limit:
                std = row[age_idx]
                break

        nc_ratio    = income_nc / income_total if income_total > 0 else 0.5
        nc_per_child = std * nc_ratio
        nc_total    = nc_per_child * n_children

        self._cs_res.setPlainText(
            f'부모 합산 소득: {income_total:.0f}만원/월\n'
            f'비양육자 소득:  {income_nc:.0f}만원/월  (분담비율 {nc_ratio*100:.1f}%)\n'
            f'자녀:           {self._cs_age.currentText()} × {n_children}명\n'
            f'{"─"*45}\n'
            f'표준 양육비:    {std}만원/월 (1인 기준)\n'
            f'비양육자 부담:  {nc_per_child:.1f}만원/인/월\n'
            f'합계 ({n_children}명):     {nc_total:.1f}만원/월  ({nc_total*10000:,.0f}원/월)')

    # ══════════════════════════════════════════════════════════════════════
    # 6. 유류분 계산기
    # ══════════════════════════════════════════════════════════════════════
    def _make_forced_share_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._fs_estate  = self._money_spin()
        self._fs_gift    = self._money_spin()
        self._fs_debt    = self._money_spin()
        self._fs_spouse  = QComboBox(); self._fs_spouse.addItems(['없음', '배우자 있음'])
        self._fs_children = QSpinBox(); self._fs_children.setRange(0, 20); self._fs_children.setValue(2)
        self._fs_parents  = QSpinBox(); self._fs_parents.setRange(0, 2)
        self._fs_siblings = QSpinBox(); self._fs_siblings.setRange(0, 20)
        for s in (self._fs_children, self._fs_parents, self._fs_siblings):
            s.setSuffix(' 명')

        f.addRow('상속재산:', self._fs_estate)
        f.addRow('증여재산 (10년 이내):', self._fs_gift)
        f.addRow('상속채무:', self._fs_debt)
        f.addRow('배우자:', self._fs_spouse)
        f.addRow('직계비속 (자녀) 수:', self._fs_children)
        f.addRow('직계존속 (부모) 수:', self._fs_parents)
        f.addRow('형제자매 수:', self._fs_siblings)

        btn = QPushButton('유류분 계산')
        btn.clicked.connect(self._calc_forced_share)
        self._fs_res = self._result_box(220)

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._fs_res)
        return w

    def _calc_forced_share(self):
        estate  = self._fs_estate.value()
        gift    = self._fs_gift.value()
        debt    = self._fs_debt.value()
        has_sp  = self._fs_spouse.currentIndex() == 1
        n_child = self._fs_children.value()
        n_par   = self._fs_parents.value()
        n_sib   = self._fs_siblings.value()

        base = estate + gift - debt
        if base <= 0:
            self._fs_res.setPlainText('유류분 산정 기초재산이 0 이하입니다.')
            return

        lines = [
            f'유류분 기초재산: {self._fmt_money(base)}',
            f'  = 상속 {self._fmt_money(estate)} + 증여 {self._fmt_money(gift)} - 채무 {self._fmt_money(debt)}',
            f'{"─"*45}',
        ]

        # (이름, 법정상속분율, 유류분비율, 인원수)
        heirs = []
        if n_child > 0:
            total_parts = n_child + (1.5 if has_sp else 0)
            heirs.append(('자녀 (각)', 1.0 / total_parts, 0.5, n_child))
            if has_sp:
                heirs.append(('배우자', 1.5 / total_parts, 0.5, 1))
        elif n_par > 0:
            total_parts = n_par + (1.5 if has_sp else 0)
            heirs.append(('부모 (각)', 1.0 / total_parts, 1/3, n_par))
            if has_sp:
                heirs.append(('배우자', 1.5 / total_parts, 0.5, 1))
        elif n_sib > 0:
            lines.append('※ 형제자매는 유류분권 없음 (헌법재판소 2024년 결정).')
            if has_sp:
                heirs.append(('배우자', 1.0, 0.5, 1))
        elif has_sp:
            heirs.append(('배우자', 1.0, 0.5, 1))

        for name, legal_share, forced_ratio, count in heirs:
            each = base * legal_share * forced_ratio
            total = each * count
            lines.append(
                f'{name}:  법정상속분 {legal_share*100:.2f}%  ×  유류분비율 {forced_ratio*100:.0f}%')
            lines.append(f'  유류분액 (1인): {self._fmt_money(each)}')
            if count > 1:
                lines.append(f'  합계 ({count}명):     {self._fmt_money(total)}')

        self._fs_res.setPlainText('\n'.join(lines))

    # ══════════════════════════════════════════════════════════════════════
    # 7. 변제충당 계산기
    # ══════════════════════════════════════════════════════════════════════
    def _make_payment_alloc_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._pa_principal = self._money_spin()
        self._pa_rate      = QDoubleSpinBox()
        self._pa_rate.setRange(0.01, 100.0); self._pa_rate.setValue(12.0)
        self._pa_rate.setSuffix(' %/년')
        self._pa_start = QDateEdit(QDate.currentDate()); self._pa_start.setCalendarPopup(True)
        self._pa_cost  = self._money_spin(999_999_999)
        self._pa_cost.setSuffix(' 원 (부대비용)')

        f.addRow('원금:', self._pa_principal)
        f.addRow('연이율:', self._pa_rate)
        f.addRow('채무 발생일:', self._pa_start)
        f.addRow('부대비용:', self._pa_cost)

        # 변제 내역 테이블
        pay_grp = QGroupBox('변제 내역')
        pg = QVBoxLayout(pay_grp)
        self._pa_tbl = QTableWidget(0, 2)
        self._pa_tbl.setHorizontalHeaderLabels(['변제일 (YYYY-MM-DD)', '변제액 (원)'])
        self._pa_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._pa_tbl.setMinimumHeight(110)
        add_btn = QPushButton('+ 추가'); add_btn.clicked.connect(self._pa_add_row)
        del_btn = QPushButton('- 삭제'); del_btn.clicked.connect(self._pa_del_row)
        btn_row = QHBoxLayout()
        btn_row.addWidget(add_btn); btn_row.addWidget(del_btn); btn_row.addStretch()
        pg.addWidget(self._pa_tbl); pg.addLayout(btn_row)

        calc_btn = QPushButton('변제충당 계산  (비용 → 이자 → 원금)')
        calc_btn.clicked.connect(self._calc_payment_alloc)
        self._pa_res = self._result_box(200)

        lay.addLayout(f)
        lay.addWidget(pay_grp)
        lay.addWidget(calc_btn)
        lay.addWidget(self._pa_res)
        return w

    def _pa_add_row(self):
        r = self._pa_tbl.rowCount()
        self._pa_tbl.insertRow(r)
        self._pa_tbl.setItem(r, 0, QTableWidgetItem(QDate.currentDate().toString('yyyy-MM-dd')))
        self._pa_tbl.setItem(r, 1, QTableWidgetItem('0'))

    def _pa_del_row(self):
        rows = {i.row() for i in self._pa_tbl.selectedIndexes()}
        for r in sorted(rows, reverse=True):
            self._pa_tbl.removeRow(r)

    def _calc_payment_alloc(self):
        principal = self._pa_principal.value()
        daily_rate = self._pa_rate.value() / 100 / 365
        start_dt   = self._pa_start.date().toPython()
        cost_rem   = self._pa_cost.value()

        payments = []
        for r in range(self._pa_tbl.rowCount()):
            try:
                yr, mo, day = map(int, self._pa_tbl.item(r, 0).text().split('-'))
                amt = float(self._pa_tbl.item(r, 1).text().replace(',', ''))
                payments.append((date(yr, mo, day), amt))
            except Exception:
                continue
        payments.sort()

        rem_prin = principal
        lines = [
            f'원금: {self._fmt_money(principal)}  이율: {self._pa_rate.value()}%/년',
            f'발생일: {start_dt}  부대비용: {self._fmt_money(cost_rem)}',
            f'{"─"*50}',
        ]

        prev_dt = start_dt
        total_cost_paid = total_int_paid = total_prin_paid = 0.0

        for pay_dt, pay_amt in payments:
            if rem_prin <= 0:
                break
            days    = (pay_dt - prev_dt).days
            accrued = rem_prin * daily_rate * days
            lines.append(f'\n[{pay_dt}] 변제액: {self._fmt_money(pay_amt)}  (경과 {days}일, 발생이자: {self._fmt_money(accrued)})')
            rem = pay_amt

            if cost_rem > 0 and rem > 0:
                paid = min(cost_rem, rem); cost_rem -= paid; rem -= paid; total_cost_paid += paid
                lines.append(f'  → 비용 충당:  {self._fmt_money(paid)}  (잔여비용: {self._fmt_money(cost_rem)})')

            if accrued > 0 and rem > 0:
                paid = min(accrued, rem); rem -= paid; total_int_paid += paid
                lines.append(f'  → 이자 충당:  {self._fmt_money(paid)}  (미충당이자: {self._fmt_money(accrued - paid)})')

            if rem > 0 and rem_prin > 0:
                paid = min(rem_prin, rem); rem_prin -= paid; total_prin_paid += paid
                lines.append(f'  → 원금 충당:  {self._fmt_money(paid)}  (잔여원금: {self._fmt_money(rem_prin)})')

            prev_dt = pay_dt

        lines += [
            f'\n{"─"*50}',
            f'[최종 잔액]',
            f'잔여 원금:  {self._fmt_money(rem_prin)}',
            f'잔여 비용:  {self._fmt_money(cost_rem)}',
            f'충당 합계:  원금 {self._fmt_money(total_prin_paid)} + 이자 {self._fmt_money(total_int_paid)} + 비용 {self._fmt_money(total_cost_paid)}',
        ]
        self._pa_res.setPlainText('\n'.join(lines))
