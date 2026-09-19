# ui/dialogs/calculator_dialog.py — 통합 계산기
# 기본 / 공학 / 생활 / 금융 / 법률
from __future__ import annotations
import math
from datetime import date, timedelta

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QStackedWidget, QWidget, QTabWidget, QFormLayout, QGroupBox,
    QLabel, QPushButton, QLineEdit, QTextEdit, QDoubleSpinBox, QSpinBox,
    QComboBox, QDateEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QGridLayout, QCheckBox, QSizePolicy, QScrollArea,
)
from utils.errlog import swallowed


# ── 안전한 수식 평가 ────────────────────────────────────────────────
_MATH_NS: dict = {k: getattr(math, k) for k in dir(math) if not k.startswith('_')}
_MATH_NS.update({'abs': abs, 'round': round, 'int': int, 'float': float})


def _safe_eval(expr: str) -> str:
    try:
        expr = expr.replace('×', '*').replace('÷', '/').replace('^', '**')
        result = eval(expr, {'__builtins__': {}}, _MATH_NS)
        if isinstance(result, float):
            if math.isnan(result) or math.isinf(result):
                return '계산불가'
            return f'{result:.10g}'
        return str(result)
    except ZeroDivisionError:
        return '0으로 나눌 수 없음'
    except Exception:
        return '오류'


# ── 공통 유틸 ────────────────────────────────────────────────────────
def _fmt_money(amount: float) -> str:
    won = round(amount)
    man = won // 10000
    rem = won % 10000
    if man > 0:
        return f'{won:,}원 ({man:,}만원)' if rem == 0 else f'{won:,}원 ({man:,}만 {rem:,}원)'
    return f'{won:,}원'


def _scroll_wrap(inner: QWidget) -> QScrollArea:
    """위젯을 세로 스크롤 영역으로 감싼다."""
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QScrollArea.Shape.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sa.setWidget(inner)
    return sa


def _result_box(height: int = 160) -> QTextEdit:
    t = QTextEdit()
    t.setReadOnly(True)
    t.setMaximumHeight(height)
    t.setFontFamily('Consolas')
    return t


def _money_spin(max_val: float = 999_999_999_999) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(0, max_val)
    s.setSuffix(' 원')
    s.setGroupSeparatorShown(True)
    s.setDecimals(0)
    return s


# ── 버튼 스타일 ──────────────────────────────────────────────────────
_S_NUM = ('QPushButton{font-size:16px;padding:10px;border:1px solid #bbb;'
          'border-radius:4px;background:#f5f5f5}'
          'QPushButton:pressed{background:#ddd}')
_S_OP  = ('QPushButton{font-size:16px;padding:10px;border:1px solid #90caf9;'
          'border-radius:4px;background:#e3f2fd;color:#1565c0}'
          'QPushButton:pressed{background:#bbdefb}')
_S_EQ  = ('QPushButton{font-size:16px;padding:10px;border:1px solid #1565c0;'
          'border-radius:4px;background:#1565c0;color:white;font-weight:bold}'
          'QPushButton:pressed{background:#0d47a1}')
_S_CLR = ('QPushButton{font-size:16px;padding:10px;border:1px solid #ef9a9a;'
          'border-radius:4px;background:#ffebee;color:#b71c1c}'
          'QPushButton:pressed{background:#ffcdd2}')
_S_FN  = ('QPushButton{font-size:12px;padding:6px;border:1px solid #ce93d8;'
          'border-radius:4px;background:#f3e5f5;color:#6a1b9a}'
          'QPushButton:pressed{background:#e1bee7}')
_S_MEM = ('QPushButton{font-size:12px;padding:6px;border:1px solid #a5d6a7;'
          'border-radius:4px;background:#e8f5e9;color:#1b5e20}'
          'QPushButton:pressed{background:#c8e6c9}')


# ══════════════════════════════════════════════════════════════════════
# 기본 계산기
# ══════════════════════════════════════════════════════════════════════
class _BasicCalcWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._expr = ''
        self._last_eq = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        self._display = QLineEdit('0')
        self._display.setReadOnly(True)
        self._display.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._display.setFont(QFont('Consolas', 22))
        self._display.setMinimumHeight(58)
        self._display.setStyleSheet(
            'QLineEdit{background:#1e1e2e;color:#cdd6f4;padding:8px;border-radius:6px}')
        lay.addWidget(self._display)

        grid = QGridLayout()
        grid.setSpacing(5)
        btns = [
            # (label, row, col, style, colspan)
            ('AC', 0, 0, _S_CLR, 1), ('←', 0, 1, _S_CLR, 1),
            ('%',  0, 2, _S_OP,  1), ('÷', 0, 3, _S_OP,  1),
            ('7',  1, 0, _S_NUM, 1), ('8', 1, 1, _S_NUM, 1),
            ('9',  1, 2, _S_NUM, 1), ('×', 1, 3, _S_OP,  1),
            ('4',  2, 0, _S_NUM, 1), ('5', 2, 1, _S_NUM, 1),
            ('6',  2, 2, _S_NUM, 1), ('-', 2, 3, _S_OP,  1),
            ('1',  3, 0, _S_NUM, 1), ('2', 3, 1, _S_NUM, 1),
            ('3',  3, 2, _S_NUM, 1), ('+', 3, 3, _S_OP,  1),
            ('±',  4, 0, _S_OP,  1), ('0', 4, 1, _S_NUM, 1),
            ('.',  4, 2, _S_NUM, 1), ('=', 4, 3, _S_EQ,  1),
        ]
        for label, row, col, style, cs in btns:
            self._add_btn(grid, label, row, col, style, cs)
        lay.addLayout(grid)

    def _add_btn(self, grid, label, row, col, style, colspan=1):
        btn = QPushButton(label)
        btn.setStyleSheet(style)
        btn.setMinimumHeight(50)
        btn.clicked.connect(lambda checked=False, l=label: self._on(l))
        grid.addWidget(btn, row, col, 1, colspan)

    def _on(self, label: str):
        if label == 'AC':
            self._expr = ''
            self._display.setText('0')
            self._last_eq = False
        elif label == '←':
            self._expr = self._expr[:-1]
            self._display.setText(self._expr or '0')
            self._last_eq = False
        elif label == '=':
            result = _safe_eval(self._expr) if self._expr else '0'
            self._display.setText(result)
            self._expr = result if 'error' not in result.lower() and '오류' not in result and '없음' not in result else ''
            self._last_eq = True
        elif label == '±':
            if self._expr.startswith('-'):
                self._expr = self._expr[1:]
            elif self._expr:
                self._expr = '-' + self._expr
            self._display.setText(self._expr or '0')
        elif label == '%':
            try:
                val = float(self._expr)
                self._expr = f'{val / 100:.10g}'
                self._display.setText(self._expr)
            except Exception:
                swallowed()
        else:
            if self._last_eq and label not in ('+', '-', '×', '÷'):
                self._expr = ''
            self._last_eq = False
            self._expr += label
            self._display.setText(self._expr)


# ══════════════════════════════════════════════════════════════════════
# 공학 계산기
# ══════════════════════════════════════════════════════════════════════
class _SciCalcWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._expr    = ''
        self._last_eq = False
        self._deg     = True      # True=도, False=라디안
        self._mem     = 0.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        # 디스플레이
        self._display = QLineEdit('0')
        self._display.setReadOnly(True)
        self._display.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._display.setFont(QFont('Consolas', 20))
        self._display.setMinimumHeight(54)
        self._display.setStyleSheet(
            'QLineEdit{background:#1e1e2e;color:#cdd6f4;padding:8px;border-radius:6px}')
        lay.addWidget(self._display)

        grid = QGridLayout()
        grid.setSpacing(4)

        # ── 함수 버튼 (행 0~2) ─────────────────────────────────────
        fn_row0 = [
            ('MC', _S_MEM), ('MR', _S_MEM), ('M+', _S_MEM), ('M-', _S_MEM),
            ('DEG', _S_FN), ('(', _S_OP), (')', _S_OP),
        ]
        fn_row1 = [
            ('sin', _S_FN), ('cos', _S_FN), ('tan', _S_FN),
            ('ln',  _S_FN), ('log', _S_FN), ('π',  _S_FN), ('e', _S_FN),
        ]
        fn_row2 = [
            ('asin', _S_FN), ('acos', _S_FN), ('atan', _S_FN),
            ('√',    _S_FN), ('x²',  _S_FN), ('^',   _S_OP), ('1/x', _S_FN),
        ]
        for ci, (lbl, sty) in enumerate(fn_row0):
            self._add_btn(grid, lbl, 0, ci, sty)
        for ci, (lbl, sty) in enumerate(fn_row1):
            self._add_btn(grid, lbl, 1, ci, sty)
        for ci, (lbl, sty) in enumerate(fn_row2):
            self._add_btn(grid, lbl, 2, ci, sty)

        # ── 숫자+연산 버튼 (행 3~7) — 7열 배치 ────────────────────
        num_btns = [
            ('AC', 3, 0, _S_CLR), ('←', 3, 1, _S_CLR), ('%', 3, 2, _S_OP),
            ('÷',  3, 3, _S_OP),
            ('7',  4, 0, _S_NUM), ('8', 4, 1, _S_NUM), ('9', 4, 2, _S_NUM),
            ('×',  4, 3, _S_OP),
            ('4',  5, 0, _S_NUM), ('5', 5, 1, _S_NUM), ('6', 5, 2, _S_NUM),
            ('-',  5, 3, _S_OP),
            ('1',  6, 0, _S_NUM), ('2', 6, 1, _S_NUM), ('3', 6, 2, _S_NUM),
            ('+',  6, 3, _S_OP),
            ('±',  7, 0, _S_OP),  ('0', 7, 1, _S_NUM), ('.', 7, 2, _S_NUM),
            ('=',  7, 3, _S_EQ),
        ]
        for lbl, row, col, sty in num_btns:
            self._add_btn(grid, lbl, row, col, sty)

        lay.addLayout(grid)

    def _add_btn(self, grid, label, row, col, style, colspan=1):
        btn = QPushButton(label)
        btn.setStyleSheet(style)
        btn.setMinimumHeight(42)
        btn.clicked.connect(lambda checked=False, l=label: self._on(l))
        grid.addWidget(btn, row, col, 1, colspan)
        if label == 'DEG':
            self._deg_btn = btn

    def _on(self, label: str):
        # ── 메모리 ────────────────────────────────────────────────
        if label == 'MC':
            self._mem = 0.0
            return
        if label == 'MR':
            self._expr += f'{self._mem:.10g}'
            self._display.setText(self._expr)
            return
        if label in ('M+', 'M-'):
            try:
                val = float(_safe_eval(self._expr))
                self._mem += val if label == 'M+' else -val
            except Exception:
                swallowed()
            return

        # ── DEG/RAD 토글 ─────────────────────────────────────────
        if label == 'DEG':
            self._deg = not self._deg
            self._deg_btn.setText('DEG' if self._deg else 'RAD')
            return

        # ── 일반 클리어/백스페이스/등호 ──────────────────────────
        if label == 'AC':
            self._expr = ''
            self._display.setText('0')
            self._last_eq = False
            return
        if label == '←':
            self._expr = self._expr[:-1]
            self._display.setText(self._expr or '0')
            self._last_eq = False
            return
        if label == '=':
            expr = self._expr
            if self._deg:
                # sin/cos/tan 을 도→라디안 변환 버전으로 교체
                for fn in ('sin', 'cos', 'tan'):
                    expr = expr.replace(f'{fn}(', f'{fn}(radians(')
                # radians 래핑: 각 여는 괄호 뒤 닫는 괄호를 하나 더
                # 위 방식은 복잡 — 대신 lambda로 대체
                ns = dict(_MATH_NS)
                if self._deg:
                    ns['sin']  = lambda x: math.sin(math.radians(x))
                    ns['cos']  = lambda x: math.cos(math.radians(x))
                    ns['tan']  = lambda x: math.tan(math.radians(x))
                    ns['asin'] = lambda x: math.degrees(math.asin(x))
                    ns['acos'] = lambda x: math.degrees(math.acos(x))
                    ns['atan'] = lambda x: math.degrees(math.atan(x))
                raw = self._expr.replace('×', '*').replace('÷', '/').replace('^', '**')
                try:
                    result_val = eval(raw, {'__builtins__': {}}, ns)
                    result = f'{result_val:.10g}' if isinstance(result_val, float) else str(result_val)
                except ZeroDivisionError:
                    result = '0으로 나눌 수 없음'
                except Exception:
                    result = '오류'
            else:
                result = _safe_eval(self._expr)
            self._display.setText(result)
            self._expr = result if '오류' not in result and '없음' not in result else ''
            self._last_eq = True
            return
        if label == '±':
            if self._expr.startswith('-'):
                self._expr = self._expr[1:]
            elif self._expr:
                self._expr = '-' + self._expr
            self._display.setText(self._expr or '0')
            return
        if label == '%':
            try:
                val = float(self._expr)
                self._expr = f'{val / 100:.10g}'
                self._display.setText(self._expr)
            except Exception:
                swallowed()
            return

        # ── 함수/상수 삽입 ────────────────────────────────────────
        insert_map = {
            'sin': 'sin(', 'cos': 'cos(', 'tan': 'tan(',
            'asin': 'asin(', 'acos': 'acos(', 'atan': 'atan(',
            'ln':  'log(', 'log': 'log10(',
            '√':   'sqrt(', 'x²': '**2',
            '1/x': '1/',
            'π':   f'{math.pi}', 'e': f'{math.e}',
        }
        if label in insert_map:
            if self._last_eq and label not in ('+', '-', '×', '÷', '^'):
                if label not in ('x²', '^', '1/x'):
                    self._expr = ''
            self._last_eq = False
            self._expr += insert_map[label]
            self._display.setText(self._expr)
            return

        # ── 숫자/연산자 ───────────────────────────────────────────
        if self._last_eq and label not in ('+', '-', '×', '÷', '^'):
            self._expr = ''
        self._last_eq = False
        self._expr += label
        self._display.setText(self._expr)


# ══════════════════════════════════════════════════════════════════════
# 생활 계산기
# ══════════════════════════════════════════════════════════════════════
class _LifeCalcWidget(QWidget):
    def __init__(self):
        super().__init__()
        tabs = QTabWidget()
        tabs.addTab(self._unit_tab(),     '📐 단위 변환')
        tabs.addTab(self._bmi_tab(),      '🏃 BMI')
        tabs.addTab(self._date_tab(),     '📅 날짜/D-day')
        tabs.addTab(self._discount_tab(), '🏷 할인 계산기')
        tabs.addTab(self._percent_tab(),  '% 퍼센트 계산기')
        tabs.addTab(self._tip_tab(),      '🍽 팁/더치')
        tabs.addTab(self._fuel_tab(),     '⛽ 연비/주유비')
        tabs.addTab(self._calorie_tab(),  '🥗 칼로리(BMR)')
        tabs.addTab(self._exchange_tab(), '💱 환율')
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)

    # ── 단위 변환 ────────────────────────────────────────────────
    def _unit_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._u_val = QDoubleSpinBox()
        self._u_val.setRange(-1e15, 1e15)
        self._u_val.setDecimals(6)
        self._u_val.setGroupSeparatorShown(True)

        self._u_cat = QComboBox()
        self._u_cat.addItems(['길이', '무게', '온도', '넓이', '부피', '속도', '데이터'])
        self._u_cat.currentIndexChanged.connect(self._u_update_units)

        self._u_from = QComboBox()
        self._u_to   = QComboBox()
        self._u_update_units(0)

        f.addRow('값:', self._u_val)
        f.addRow('분류:', self._u_cat)
        f.addRow('변환 전:', self._u_from)
        f.addRow('변환 후:', self._u_to)

        btn = QPushButton('변환')
        btn.clicked.connect(self._u_calc)
        self._u_res = _result_box(70)

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._u_res)
        lay.addStretch()
        return w

    _UNIT_DEFS = {
        '길이':  [('m', 1), ('km', 1000), ('cm', 0.01), ('mm', 0.001),
                  ('inch', 0.0254), ('ft', 0.3048), ('yard', 0.9144), ('mile', 1609.344)],
        '무게':  [('kg', 1), ('g', 0.001), ('ton', 1000), ('lb', 0.453592),
                  ('oz', 0.0283495), ('근(600g)', 0.6)],
        '온도':  [('℃', None), ('℉', None), ('K', None)],
        '넓이':  [('m²', 1), ('km²', 1e6), ('cm²', 1e-4), ('평', 3.30579),
                  ('ha', 1e4), ('acre', 4046.86)],
        '부피':  [('L', 1), ('mL', 0.001), ('m³', 1000), ('갤런(US)', 3.78541),
                  ('fl oz', 0.0295735)],
        '속도':  [('m/s', 1), ('km/h', 1/3.6), ('mph', 0.44704), ('knot', 0.514444)],
        '데이터':[('Byte', 1), ('KB', 1024), ('MB', 1048576), ('GB', 1073741824),
                  ('TB', 1099511627776)],
    }

    def _u_update_units(self, idx: int):
        cat  = self._u_cat.currentText()
        keys = [u[0] for u in self._UNIT_DEFS[cat]]
        for cb in (self._u_from, self._u_to):
            cb.clear()
            cb.addItems(keys)
        if len(keys) > 1:
            self._u_to.setCurrentIndex(1)

    def _u_calc(self):
        val  = self._u_val.value()
        cat  = self._u_cat.currentText()
        fr   = self._u_from.currentText()
        to   = self._u_to.currentText()
        defs = dict(self._UNIT_DEFS[cat])

        if cat == '온도':
            c = {'℃': val, '℉': (val - 32) * 5/9, 'K': val - 273.15}.get(fr, 0)
            result = {'℃': c, '℉': c * 9/5 + 32, 'K': c + 273.15}.get(to, 0)
            self._u_res.setPlainText(f'{val} {fr}  →  {result:.6g} {to}')
        else:
            base   = val * defs[fr]
            result = base / defs[to]
            self._u_res.setPlainText(f'{val} {fr}  →  {result:.6g} {to}')

    # ── BMI ──────────────────────────────────────────────────────
    def _bmi_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._bmi_h = QDoubleSpinBox()
        self._bmi_h.setRange(50, 250)
        self._bmi_h.setValue(180)
        self._bmi_h.setSuffix(' cm')

        self._bmi_w = QDoubleSpinBox()
        self._bmi_w.setRange(10, 300)
        self._bmi_w.setValue(78)
        self._bmi_w.setSuffix(' kg')

        f.addRow('키:', self._bmi_h)
        f.addRow('몸무게:', self._bmi_w)

        btn = QPushButton('BMI 계산')
        btn.clicked.connect(self._bmi_calc)
        self._bmi_res = _result_box(120)

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._bmi_res)
        lay.addStretch()
        return w

    def _bmi_calc(self):
        h = self._bmi_h.value() / 100
        wt = self._bmi_w.value()
        bmi = wt / (h * h)
        if bmi < 18.5:
            cat = '저체중'
        elif bmi < 23:
            cat = '정상'
        elif bmi < 25:
            cat = '과체중'
        elif bmi < 30:
            cat = '비만 1단계'
        else:
            cat = '비만 2단계'
        ideal_min = 18.5 * h * h
        ideal_max = 22.9 * h * h
        self._bmi_res.setPlainText(
            f'BMI:    {bmi:.1f}  ({cat})\n'
            f'정상 체중 범위:  {ideal_min:.1f} ~ {ideal_max:.1f} kg')

    # ── 날짜/D-day ───────────────────────────────────────────────
    def _date_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        grp1 = QGroupBox('두 날짜 사이 기간')
        f1 = QFormLayout(grp1)
        self._ld_from = QDateEdit(QDate.currentDate()); self._ld_from.setCalendarPopup(True)
        self._ld_to   = QDateEdit(QDate.currentDate()); self._ld_to.setCalendarPopup(True)
        f1.addRow('시작일:', self._ld_from)
        f1.addRow('종료일:', self._ld_to)
        b1 = QPushButton('계산'); b1.clicked.connect(self._ld_diff)
        f1.addRow(b1)
        self._ld_diff_res = _result_box(90)

        grp2 = QGroupBox('D-day / 날짜 가산')
        f2 = QFormLayout(grp2)
        self._ld_base = QDateEdit(QDate.currentDate()); self._ld_base.setCalendarPopup(True)
        self._ld_days = QSpinBox(); self._ld_days.setRange(-36500, 36500); self._ld_days.setSuffix(' 일')
        f2.addRow('기준일:', self._ld_base)
        f2.addRow('가산일수 (음수=감산):', self._ld_days)
        b2 = QPushButton('계산'); b2.clicked.connect(self._ld_add)
        f2.addRow(b2)
        self._ld_add_res = _result_box(70)

        lay.addWidget(grp1)
        lay.addWidget(self._ld_diff_res)
        lay.addWidget(grp2)
        lay.addWidget(self._ld_add_res)
        lay.addStretch()
        return w

    def _ld_diff(self):
        s = self._ld_from.date().toPython()
        e = self._ld_to.date().toPython()
        if s > e: s, e = e, s
        today = date.today()
        days  = (e - s).days
        months = (e.year - s.year) * 12 + (e.month - s.month)
        d_from_today = (e - today).days
        self._ld_diff_res.setPlainText(
            f'총 일수:  {days:,}일\n'
            f'주수:     {days // 7}주 {days % 7}일\n'
            f'개월수:   약 {months}개월\n'
            f'D-day (종료일까지): {d_from_today:+}일')

    def _ld_add(self):
        base = self._ld_base.date().toPython()
        d    = self._ld_days.value()
        res  = base + timedelta(days=d)
        verb = '더한' if d >= 0 else '뺀'
        today = date.today()
        dday  = (res - today).days
        self._ld_add_res.setPlainText(
            f'{base}  {d:+}일  →  {res}\n'
            f'({abs(d)}일을 {verb} 날짜)  D-day: {dday:+}일')

    # ── 할인 계산기 ───────────────────────────────────────────────
    def _discount_tab(self) -> QScrollArea:
        w = QWidget()
        lay = QVBoxLayout(w)

        grp1 = QGroupBox('할인율로 할인가 계산')
        f1 = QFormLayout(grp1)
        self._dc_price = QDoubleSpinBox()
        self._dc_price.setRange(0, 1e12); self._dc_price.setGroupSeparatorShown(True); self._dc_price.setSuffix(' 원')
        self._dc_rate  = QDoubleSpinBox()
        self._dc_rate.setRange(0, 100); self._dc_rate.setValue(10); self._dc_rate.setSuffix(' %')
        f1.addRow('정가:', self._dc_price)
        f1.addRow('할인율:', self._dc_rate)
        b1 = QPushButton('할인가 계산'); b1.clicked.connect(self._dc_calc)
        f1.addRow(b1)
        self._dc_res = _result_box(80)

        grp2 = QGroupBox('할인율 역산 (정가 → 할인가)')
        f2 = QFormLayout(grp2)
        self._dc_orig = QDoubleSpinBox()
        self._dc_orig.setRange(0, 1e12); self._dc_orig.setGroupSeparatorShown(True); self._dc_orig.setSuffix(' 원 (정가)')
        self._dc_sale = QDoubleSpinBox()
        self._dc_sale.setRange(0, 1e12); self._dc_sale.setGroupSeparatorShown(True); self._dc_sale.setSuffix(' 원 (할인가)')
        f2.addRow('정가:', self._dc_orig)
        f2.addRow('할인가:', self._dc_sale)
        b2 = QPushButton('할인율 계산'); b2.clicked.connect(self._dc_rev_calc)
        f2.addRow(b2)
        self._dc_rev_res = _result_box(70)

        grp3 = QGroupBox('복수 할인 (쿠폰+카드 중복)')
        f3 = QFormLayout(grp3)
        self._dc_p3   = QDoubleSpinBox()
        self._dc_p3.setRange(0, 1e12); self._dc_p3.setGroupSeparatorShown(True); self._dc_p3.setSuffix(' 원')
        self._dc_r3a  = QDoubleSpinBox(); self._dc_r3a.setRange(0, 100); self._dc_r3a.setValue(10); self._dc_r3a.setSuffix(' % (1차)')
        self._dc_r3b  = QDoubleSpinBox(); self._dc_r3b.setRange(0, 100); self._dc_r3b.setValue(5);  self._dc_r3b.setSuffix(' % (2차)')
        f3.addRow('정가:', self._dc_p3)
        f3.addRow('1차 할인율:', self._dc_r3a)
        f3.addRow('2차 할인율:', self._dc_r3b)
        b3 = QPushButton('중복 할인 계산'); b3.clicked.connect(self._dc_multi_calc)
        f3.addRow(b3)
        self._dc_multi_res = _result_box(80)

        lay.addWidget(grp1); lay.addWidget(self._dc_res)
        lay.addWidget(grp2); lay.addWidget(self._dc_rev_res)
        lay.addWidget(grp3); lay.addWidget(self._dc_multi_res)
        lay.addStretch()
        return _scroll_wrap(w)

    def _dc_calc(self):
        p = self._dc_price.value()
        r = self._dc_rate.value()
        sale  = p * (1 - r / 100)
        saved = p - sale
        self._dc_res.setPlainText(
            f'정가:   {p:,.0f}원\n'
            f'할인가: {sale:,.0f}원\n'
            f'절약액: {saved:,.0f}원  ({r}% 할인)')

    def _dc_rev_calc(self):
        orig = self._dc_orig.value()
        sale = self._dc_sale.value()
        if orig == 0:
            self._dc_rev_res.setPlainText('정가를 입력하세요.')
            return
        rate = (1 - sale / orig) * 100
        saved = orig - sale
        self._dc_rev_res.setPlainText(
            f'할인율: {rate:.2f}%\n절약액: {saved:,.0f}원')

    def _dc_multi_calc(self):
        p  = self._dc_p3.value()
        r1 = self._dc_r3a.value() / 100
        r2 = self._dc_r3b.value() / 100
        after1  = p * (1 - r1)
        after2  = after1 * (1 - r2)
        saved   = p - after2
        eff_r   = saved / p * 100 if p else 0
        self._dc_multi_res.setPlainText(
            f'정가:      {p:,.0f}원\n'
            f'1차 할인 후: {after1:,.0f}원  (-{r1*100:.0f}%)\n'
            f'2차 할인 후: {after2:,.0f}원  (-{r2*100:.0f}%)\n'
            f'총 절약:   {saved:,.0f}원  (실효 {eff_r:.2f}% 할인)')

    # ── 퍼센트 계산기 ─────────────────────────────────────────────
    def _percent_tab(self) -> QScrollArea:
        w = QWidget()
        lay = QVBoxLayout(w)

        grp1 = QGroupBox('① X의 Y% 는?')
        f1 = QFormLayout(grp1)
        self._pc_x1 = QDoubleSpinBox(); self._pc_x1.setRange(-1e15, 1e15); self._pc_x1.setGroupSeparatorShown(True); self._pc_x1.setDecimals(2)
        self._pc_y1 = QDoubleSpinBox(); self._pc_y1.setRange(-1e9, 1e9);   self._pc_y1.setValue(10); self._pc_y1.setSuffix(' %')
        f1.addRow('X:', self._pc_x1); f1.addRow('Y:', self._pc_y1)
        b1 = QPushButton('계산'); b1.clicked.connect(self._pc_calc1); f1.addRow(b1)
        self._pc_res1 = _result_box(50)

        grp2 = QGroupBox('② X는 Y의 몇%?')
        f2 = QFormLayout(grp2)
        self._pc_x2 = QDoubleSpinBox(); self._pc_x2.setRange(-1e15, 1e15); self._pc_x2.setGroupSeparatorShown(True); self._pc_x2.setDecimals(2)
        self._pc_y2 = QDoubleSpinBox(); self._pc_y2.setRange(-1e15, 1e15); self._pc_y2.setGroupSeparatorShown(True); self._pc_y2.setDecimals(2)
        f2.addRow('X (부분):', self._pc_x2); f2.addRow('Y (전체):', self._pc_y2)
        b2 = QPushButton('계산'); b2.clicked.connect(self._pc_calc2); f2.addRow(b2)
        self._pc_res2 = _result_box(50)

        grp3 = QGroupBox('③ X에서 Y% 증가/감소하면?')
        f3 = QFormLayout(grp3)
        self._pc_x3  = QDoubleSpinBox(); self._pc_x3.setRange(-1e15, 1e15); self._pc_x3.setGroupSeparatorShown(True); self._pc_x3.setDecimals(2)
        self._pc_y3  = QDoubleSpinBox(); self._pc_y3.setRange(-1e9, 1e9);   self._pc_y3.setDecimals(2); self._pc_y3.setValue(10); self._pc_y3.setSuffix(' %')
        self._pc_dir = QComboBox(); self._pc_dir.addItems(['증가 (+)', '감소 (-)'])
        f3.addRow('기준값 X:', self._pc_x3); f3.addRow('변화율 Y:', self._pc_y3); f3.addRow('방향:', self._pc_dir)
        b3 = QPushButton('계산'); b3.clicked.connect(self._pc_calc3); f3.addRow(b3)
        self._pc_res3 = _result_box(60)

        grp4 = QGroupBox('④ X → Y 변화율은?')
        f4 = QFormLayout(grp4)
        self._pc_x4 = QDoubleSpinBox(); self._pc_x4.setRange(-1e15, 1e15); self._pc_x4.setGroupSeparatorShown(True); self._pc_x4.setDecimals(2)
        self._pc_y4 = QDoubleSpinBox(); self._pc_y4.setRange(-1e15, 1e15); self._pc_y4.setGroupSeparatorShown(True); self._pc_y4.setDecimals(2)
        f4.addRow('이전값 X:', self._pc_x4); f4.addRow('이후값 Y:', self._pc_y4)
        b4 = QPushButton('계산'); b4.clicked.connect(self._pc_calc4); f4.addRow(b4)
        self._pc_res4 = _result_box(60)

        lay.addWidget(grp1); lay.addWidget(self._pc_res1)
        lay.addWidget(grp2); lay.addWidget(self._pc_res2)
        lay.addWidget(grp3); lay.addWidget(self._pc_res3)
        lay.addWidget(grp4); lay.addWidget(self._pc_res4)
        lay.addStretch()
        return _scroll_wrap(w)

    def _pc_calc1(self):
        x = self._pc_x1.value(); y = self._pc_y1.value()
        res = x * y / 100
        self._pc_res1.setPlainText(f'{x:,.2g}의 {y}%  =  {res:,.4g}')

    def _pc_calc2(self):
        x = self._pc_x2.value(); y = self._pc_y2.value()
        if y == 0:
            self._pc_res2.setPlainText('Y(전체)가 0입니다.')
            return
        pct = x / y * 100
        self._pc_res2.setPlainText(f'{x:,.4g}는 {y:,.4g}의  {pct:.4g}%')

    def _pc_calc3(self):
        x = self._pc_x3.value(); y = self._pc_y3.value()
        sign = 1 if self._pc_dir.currentIndex() == 0 else -1
        res  = x * (1 + sign * y / 100)
        diff = res - x
        self._pc_res3.setPlainText(
            f'기준: {x:,.4g}  →  결과: {res:,.4g}\n변화량: {diff:+,.4g}')

    def _pc_calc4(self):
        x = self._pc_x4.value(); y = self._pc_y4.value()
        if x == 0:
            self._pc_res4.setPlainText('이전값 X가 0입니다.')
            return
        pct  = (y - x) / x * 100
        diff = y - x
        self._pc_res4.setPlainText(
            f'{x:,.4g}  →  {y:,.4g}\n변화율: {pct:+.4g}%  (변화량 {diff:+,.4g})')

    # ── 팁/더치 ───────────────────────────────────────────────────
    def _tip_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._tip_total = QDoubleSpinBox()
        self._tip_total.setRange(0, 1e10); self._tip_total.setGroupSeparatorShown(True); self._tip_total.setSuffix(' 원')
        self._tip_pct   = QDoubleSpinBox()
        self._tip_pct.setRange(0, 100); self._tip_pct.setValue(10); self._tip_pct.setSuffix(' %')
        self._tip_n     = QSpinBox()
        self._tip_n.setRange(1, 100); self._tip_n.setValue(2); self._tip_n.setSuffix(' 명')

        f.addRow('총금액:', self._tip_total)
        f.addRow('팁 비율:', self._tip_pct)
        f.addRow('인원:', self._tip_n)

        btn = QPushButton('계산')
        btn.clicked.connect(self._tip_calc)
        self._tip_res = _result_box(120)

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._tip_res)
        lay.addStretch()
        return w

    def _tip_calc(self):
        total = self._tip_total.value()
        pct   = self._tip_pct.value()
        n     = self._tip_n.value()
        tip   = total * pct / 100
        grand = total + tip
        per   = grand / n
        self._tip_res.setPlainText(
            f'음식값:     {total:,.0f}원\n'
            f'팁({pct}%):  {tip:,.0f}원\n'
            f'합계:       {grand:,.0f}원\n'
            f'1인 부담:   {per:,.0f}원  ({n}명)')

    # ── 연비/주유비 ───────────────────────────────────────────────
    def _fuel_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        grp1 = QGroupBox('연비 계산')
        f1 = QFormLayout(grp1)
        self._fe_dist = QDoubleSpinBox(); self._fe_dist.setRange(0, 1e6); self._fe_dist.setSuffix(' km')
        self._fe_fuel = QDoubleSpinBox(); self._fe_fuel.setRange(0, 1e6); self._fe_fuel.setSuffix(' L')
        f1.addRow('주행 거리:', self._fe_dist)
        f1.addRow('연료 소모량:', self._fe_fuel)
        b1 = QPushButton('계산'); b1.clicked.connect(self._fe_calc)
        f1.addRow(b1)
        self._fe_res = _result_box(70)

        grp2 = QGroupBox('주유비 계산')
        f2 = QFormLayout(grp2)
        self._fp_dist  = QDoubleSpinBox(); self._fp_dist.setRange(0, 1e6); self._fp_dist.setSuffix(' km')
        self._fp_eff   = QDoubleSpinBox(); self._fp_eff.setRange(0.1, 100); self._fp_eff.setValue(12); self._fp_eff.setSuffix(' km/L')
        self._fp_price = QDoubleSpinBox(); self._fp_price.setRange(0, 10000); self._fp_price.setValue(1700); self._fp_price.setSuffix(' 원/L')
        f2.addRow('주행 거리:', self._fp_dist)
        f2.addRow('연비:', self._fp_eff)
        f2.addRow('유가:', self._fp_price)
        b2 = QPushButton('계산'); b2.clicked.connect(self._fp_calc)
        f2.addRow(b2)
        self._fp_res = _result_box(70)

        lay.addWidget(grp1); lay.addWidget(self._fe_res)
        lay.addWidget(grp2); lay.addWidget(self._fp_res)
        lay.addStretch()
        return w

    def _fe_calc(self):
        d = self._fe_dist.value(); f = self._fe_fuel.value()
        if f == 0:
            self._fe_res.setPlainText('연료량을 입력하세요.')
            return
        eff = d / f
        self._fe_res.setPlainText(f'연비: {eff:.2f} km/L  ({1000/eff:.2f} L/100km)')

    def _fp_calc(self):
        d = self._fp_dist.value(); e = self._fp_eff.value(); p = self._fp_price.value()
        if e == 0:
            return
        liters = d / e
        cost   = liters * p
        self._fp_res.setPlainText(
            f'필요 연료: {liters:.2f} L\n주유비:    {cost:,.0f}원')

    # ── 칼로리/BMR ────────────────────────────────────────────────
    def _calorie_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._cal_h    = QDoubleSpinBox(); self._cal_h.setRange(50, 250); self._cal_h.setValue(180); self._cal_h.setSuffix(' cm')
        self._cal_w    = QDoubleSpinBox(); self._cal_w.setRange(10, 300); self._cal_w.setValue(78);  self._cal_w.setSuffix(' kg')
        self._cal_age  = QSpinBox();       self._cal_age.setRange(1, 120); self._cal_age.setValue(35); self._cal_age.setSuffix(' 세')
        self._cal_sex  = QComboBox();      self._cal_sex.addItems(['남성', '여성'])
        self._cal_act  = QComboBox()
        self._cal_act.addItems([
            '비활동적 (운동 거의 없음) ×1.2',
            '가벼운 활동 (주 1-3회) ×1.375',
            '보통 활동 (주 3-5회) ×1.55',
            '활동적 (주 6-7회) ×1.725',
            '매우 활동적 (격한 운동+노동) ×1.9',
        ])

        f.addRow('키:', self._cal_h)
        f.addRow('몸무게:', self._cal_w)
        f.addRow('나이:', self._cal_age)
        f.addRow('성별:', self._cal_sex)
        f.addRow('활동량:', self._cal_act)

        btn = QPushButton('BMR / 권장 칼로리 계산')
        btn.clicked.connect(self._cal_calc)
        self._cal_res = _result_box(140)

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._cal_res)
        lay.addStretch()
        return w

    def _cal_calc(self):
        h   = self._cal_h.value()
        wt  = self._cal_w.value()
        age = self._cal_age.value()
        act_factors = [1.2, 1.375, 1.55, 1.725, 1.9]
        act = act_factors[self._cal_act.currentIndex()]

        if self._cal_sex.currentIndex() == 0:  # 남
            bmr = 10 * wt + 6.25 * h - 5 * age + 5
        else:
            bmr = 10 * wt + 6.25 * h - 5 * age - 161

        tdee = bmr * act
        self._cal_res.setPlainText(
            f'기초대사량 (BMR): {bmr:.0f} kcal/일\n'
            f'유지 칼로리 (TDEE): {tdee:.0f} kcal/일\n'
            f'─────────────────────────────\n'
            f'감량 목표 (-500kcal): {tdee-500:.0f} kcal/일\n'
            f'증량 목표 (+300kcal): {tdee+300:.0f} kcal/일')

    # ── 환율 ─────────────────────────────────────────────────────
    def _exchange_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._ex_amount = QDoubleSpinBox()
        self._ex_amount.setRange(0, 1e15); self._ex_amount.setGroupSeparatorShown(True); self._ex_amount.setValue(1)
        self._ex_from   = QComboBox()
        self._ex_from.addItems(['USD', 'EUR', 'JPY(100)', 'CNY', 'KRW', '직접입력'])
        self._ex_rate   = QDoubleSpinBox()
        self._ex_rate.setRange(0, 1e10); self._ex_rate.setDecimals(4); self._ex_rate.setValue(1350)
        self._ex_rate.setSuffix(' 원')

        info = QLabel('※ 환율을 직접 입력하세요. (1 외화 = ? 원)')
        info.setStyleSheet('color: gray; font-size: 11px;')

        f.addRow('금액:', self._ex_amount)
        f.addRow('통화:', self._ex_from)
        f.addRow('환율 (원/외화):', self._ex_rate)

        btn = QPushButton('환산')
        btn.clicked.connect(self._ex_calc)
        self._ex_res = _result_box(80)

        self._ex_from.currentIndexChanged.connect(self._ex_preset)
        self._ex_preset(0)

        lay.addLayout(f)
        lay.addWidget(info)
        lay.addWidget(btn)
        lay.addWidget(self._ex_res)
        lay.addStretch()
        return w

    _EX_PRESETS = {'USD': 1350, 'EUR': 1480, 'JPY(100)': 900, 'CNY': 187, 'KRW': 1}

    def _ex_preset(self, idx: int):
        cur = self._ex_from.currentText()
        if cur in self._EX_PRESETS:
            self._ex_rate.setValue(self._EX_PRESETS[cur])

    def _ex_calc(self):
        amt  = self._ex_amount.value()
        cur  = self._ex_from.currentText()
        rate = self._ex_rate.value()
        won  = amt * rate
        self._ex_res.setPlainText(
            f'{amt:,.4g} {cur}  →  {won:,.0f} 원\n'
            f'(환율: 1 {cur} = {rate:.4g} 원)')


# ══════════════════════════════════════════════════════════════════════
# 금융 계산기
# ══════════════════════════════════════════════════════════════════════
class _FinanceCalcWidget(QWidget):
    def __init__(self):
        super().__init__()
        tabs = QTabWidget()
        tabs.addTab(self._loan_tab(),     '🏦 대출 계산기')
        tabs.addTab(self._savings_tab(),  '💰 예적금 계산기')
        tabs.addTab(self._vat_tab(),      '🧾 부가세 계산기')
        tabs.addTab(self._compound_tab(), '📈 복리/단리')
        tabs.addTab(self._realestate_tab(), '🏠 부동산 취득세')
        tabs.addTab(self._return_tab(),   '📊 세후 수익률')
        tabs.addTab(self._pv_tab(),       '⏳ 현재/미래가치')
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)

    # ── 대출 ─────────────────────────────────────────────────────
    def _loan_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._ln_amt   = _money_spin()
        self._ln_rate  = QDoubleSpinBox(); self._ln_rate.setRange(0, 100); self._ln_rate.setValue(4.5); self._ln_rate.setSuffix(' %/년')
        self._ln_months = QSpinBox(); self._ln_months.setRange(1, 600); self._ln_months.setValue(360); self._ln_months.setSuffix(' 개월')
        self._ln_type  = QComboBox(); self._ln_type.addItems(['원리금균등', '원금균등', '만기일시상환'])

        f.addRow('대출금액:', self._ln_amt)
        f.addRow('연이율:', self._ln_rate)
        f.addRow('대출기간:', self._ln_months)
        f.addRow('상환방식:', self._ln_type)

        btn = QPushButton('계산')
        btn.clicked.connect(self._ln_calc)
        self._ln_res = _result_box(200)

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._ln_res)
        return w

    def _ln_calc(self):
        P = self._ln_amt.value()
        annual_r = self._ln_rate.value() / 100
        n = self._ln_months.value()
        t = self._ln_type.currentIndex()
        r = annual_r / 12  # 월이율

        if t == 0:  # 원리금균등
            if r == 0:
                monthly = P / n
            else:
                monthly = P * r * (1 + r)**n / ((1 + r)**n - 1)
            total = monthly * n
            interest = total - P
            self._ln_res.setPlainText(
                f'[원리금균등]\n'
                f'월 납입액:    {monthly:,.0f}원\n'
                f'총 상환액:    {total:,.0f}원\n'
                f'총 이자:      {interest:,.0f}원\n'
                f'원금:         {P:,.0f}원')
        elif t == 1:  # 원금균등
            principal_payment = P / n
            first = principal_payment + P * r
            last  = principal_payment + principal_payment * r
            total_int = sum(
                (P - principal_payment * i) * r for i in range(n))
            self._ln_res.setPlainText(
                f'[원금균등]\n'
                f'월 원금:      {principal_payment:,.0f}원\n'
                f'1회차 납입:   {first:,.0f}원\n'
                f'마지막 납입:  {last:,.0f}원\n'
                f'총 이자:      {total_int:,.0f}원\n'
                f'총 상환액:    {P + total_int:,.0f}원')
        else:  # 만기일시상환
            monthly_int = P * r
            total_int   = monthly_int * n
            self._ln_res.setPlainText(
                f'[만기일시상환]\n'
                f'월 이자:      {monthly_int:,.0f}원\n'
                f'총 이자:      {total_int:,.0f}원\n'
                f'만기 상환:    {P:,.0f}원\n'
                f'총 납입:      {P + total_int:,.0f}원')

    # ── 적금/예금 ─────────────────────────────────────────────────
    def _savings_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        grp1 = QGroupBox('적금 (매월 납입)')
        f1 = QFormLayout(grp1)
        self._sv_monthly = _money_spin(1e10); self._sv_monthly.setSuffix(' 원/월')
        self._sv_rate    = QDoubleSpinBox(); self._sv_rate.setRange(0, 100); self._sv_rate.setValue(4); self._sv_rate.setSuffix(' %/년')
        self._sv_months  = QSpinBox(); self._sv_months.setRange(1, 600); self._sv_months.setValue(12); self._sv_months.setSuffix(' 개월')
        self._sv_tax     = QCheckBox('이자소득세 15.4% 적용')
        f1.addRow('월 납입액:', self._sv_monthly); f1.addRow('연이율:', self._sv_rate)
        f1.addRow('기간:', self._sv_months); f1.addRow('', self._sv_tax)
        b1 = QPushButton('계산'); b1.clicked.connect(self._sv_calc); f1.addRow(b1)
        self._sv_res = _result_box(120)

        grp2 = QGroupBox('예금 (일시 예치)')
        f2 = QFormLayout(grp2)
        self._dep_amt    = _money_spin()
        self._dep_rate   = QDoubleSpinBox(); self._dep_rate.setRange(0, 100); self._dep_rate.setValue(4); self._dep_rate.setSuffix(' %/년')
        self._dep_months = QSpinBox(); self._dep_months.setRange(1, 600); self._dep_months.setValue(12); self._dep_months.setSuffix(' 개월')
        self._dep_tax    = QCheckBox('이자소득세 15.4% 적용')
        f2.addRow('예치금:', self._dep_amt); f2.addRow('연이율:', self._dep_rate)
        f2.addRow('기간:', self._dep_months); f2.addRow('', self._dep_tax)
        b2 = QPushButton('계산'); b2.clicked.connect(self._dep_calc); f2.addRow(b2)
        self._dep_res = _result_box(100)

        lay.addWidget(grp1); lay.addWidget(self._sv_res)
        lay.addWidget(grp2); lay.addWidget(self._dep_res)
        return w

    def _sv_calc(self):
        m = self._sv_monthly.value()
        r = self._sv_rate.value() / 100 / 12
        n = self._sv_months.value()
        total_principal = m * n
        if r == 0:
            interest = 0.0
        else:
            fv = m * ((1 + r)**n - 1) / r
            interest = fv - total_principal
        if self._sv_tax.isChecked():
            tax = interest * 0.154
            net = interest - tax
        else:
            tax = 0; net = interest
        self._sv_res.setPlainText(
            f'납입 원금: {total_principal:,.0f}원\n'
            f'세전 이자: {interest:,.0f}원\n'
            f'이자소득세: {tax:,.0f}원\n'
            f'세후 이자: {net:,.0f}원\n'
            f'만기 수령: {total_principal + net:,.0f}원')

    def _dep_calc(self):
        p = self._dep_amt.value()
        r = self._dep_rate.value() / 100
        n = self._dep_months.value() / 12
        interest = p * r * n
        if self._dep_tax.isChecked():
            tax = interest * 0.154
            net = interest - tax
        else:
            tax = 0; net = interest
        self._dep_res.setPlainText(
            f'원금:     {p:,.0f}원\n'
            f'세전이자: {interest:,.0f}원\n'
            f'세후이자: {net:,.0f}원\n'
            f'만기수령: {p + net:,.0f}원')

    # ── 부가세 계산기 ─────────────────────────────────────────────
    def _vat_tab(self) -> QScrollArea:
        w = QWidget()
        lay = QVBoxLayout(w)

        grp1 = QGroupBox('일반과세자 (세율 10%)')
        f1 = QFormLayout(grp1)
        self._fv_price = QDoubleSpinBox()
        self._fv_price.setRange(0, 1e12); self._fv_price.setGroupSeparatorShown(True); self._fv_price.setDecimals(0); self._fv_price.setSuffix(' 원')
        self._fv_mode  = QComboBox()
        self._fv_mode.addItems([
            '공급가액 입력  →  부가세 / 합계 계산',
            '합계금액 입력  →  공급가액 / 부가세 역산',
            '부가세 입력    →  공급가액 / 합계 역산',
        ])
        f1.addRow('금액:', self._fv_price)
        f1.addRow('계산 방향:', self._fv_mode)
        b1 = QPushButton('계산'); b1.clicked.connect(self._fv_calc); f1.addRow(b1)
        self._fv_res = _result_box(100)

        grp2 = QGroupBox('간이과세자 (업종별 부가가치율)')
        f2 = QFormLayout(grp2)
        self._fv_simple_supply = QDoubleSpinBox()
        self._fv_simple_supply.setRange(0, 1e12); self._fv_simple_supply.setGroupSeparatorShown(True); self._fv_simple_supply.setDecimals(0); self._fv_simple_supply.setSuffix(' 원 (공급가액)')
        self._fv_simple_type = QComboBox()
        self._fv_simple_type.addItems([
            '소매업/재생용자재수집 15%',
            '음식점업 25%',
            '제조업/농업/어업/임업 25%',
            '숙박업 30%',
            '건설업/운수/창고업 30%',
            '서비스업/기타 40%',
            '부동산임대업 40%',
        ])
        f2.addRow('공급가액:', self._fv_simple_supply)
        f2.addRow('업종:', self._fv_simple_type)
        b2 = QPushButton('간이과세 세액 계산'); b2.clicked.connect(self._fv_simple_calc); f2.addRow(b2)
        self._fv_simple_res = _result_box(80)

        grp3 = QGroupBox('매입/매출 부가세 차감 (납부세액)')
        f3 = QFormLayout(grp3)
        self._fv_out = QDoubleSpinBox()
        self._fv_out.setRange(0, 1e12); self._fv_out.setGroupSeparatorShown(True); self._fv_out.setDecimals(0); self._fv_out.setSuffix(' 원 (매출세액)')
        self._fv_in  = QDoubleSpinBox()
        self._fv_in.setRange(0, 1e12);  self._fv_in.setGroupSeparatorShown(True);  self._fv_in.setDecimals(0);  self._fv_in.setSuffix(' 원 (매입세액)')
        f3.addRow('매출 부가세:', self._fv_out)
        f3.addRow('매입 부가세:', self._fv_in)
        b3 = QPushButton('납부(환급)세액 계산'); b3.clicked.connect(self._fv_diff_calc); f3.addRow(b3)
        self._fv_diff_res = _result_box(70)

        lay.addWidget(grp1); lay.addWidget(self._fv_res)
        lay.addWidget(grp2); lay.addWidget(self._fv_simple_res)
        lay.addWidget(grp3); lay.addWidget(self._fv_diff_res)
        lay.addStretch()
        return _scroll_wrap(w)

    def _fv_calc(self):
        p   = self._fv_price.value()
        idx = self._fv_mode.currentIndex()
        if idx == 0:   # 공급가액 → 부가세, 합계
            vat   = p * 0.1
            total = p + vat
            self._fv_res.setPlainText(
                f'공급가액:    {p:,.0f}원\n'
                f'부가세(10%): {vat:,.0f}원\n'
                f'합  계:      {total:,.0f}원')
        elif idx == 1:  # 합계 → 공급가액, 부가세
            supply = p / 1.1
            vat    = p - supply
            self._fv_res.setPlainText(
                f'합계금액:  {p:,.0f}원\n'
                f'공급가액:  {supply:,.0f}원\n'
                f'부가세:    {vat:,.0f}원')
        else:           # 부가세 → 공급가액, 합계
            supply = p * 10
            total  = supply + p
            self._fv_res.setPlainText(
                f'부가세:    {p:,.0f}원\n'
                f'공급가액:  {supply:,.0f}원\n'
                f'합  계:    {total:,.0f}원')

    _SIMPLE_RATES = [0.15, 0.25, 0.25, 0.30, 0.30, 0.40, 0.40]

    def _fv_simple_calc(self):
        supply = self._fv_simple_supply.value()
        rate   = self._SIMPLE_RATES[self._fv_simple_type.currentIndex()]
        # 간이과세 납부세액 = 공급가액 × 부가가치율 × 10%
        tax    = supply * rate * 0.1
        self._fv_simple_res.setPlainText(
            f'공급가액:    {supply:,.0f}원\n'
            f'부가가치율:  {rate*100:.0f}%\n'
            f'납부세액:    {tax:,.0f}원  (= {supply:,.0f} × {rate*100:.0f}% × 10%)')

    def _fv_diff_calc(self):
        out = self._fv_out.value()
        inp = self._fv_in.value()
        diff = out - inp
        if diff >= 0:
            self._fv_diff_res.setPlainText(
                f'매출 부가세: {out:,.0f}원\n'
                f'매입 부가세: {inp:,.0f}원\n'
                f'납부세액:    {diff:,.0f}원')
        else:
            self._fv_diff_res.setPlainText(
                f'매출 부가세: {out:,.0f}원\n'
                f'매입 부가세: {inp:,.0f}원\n'
                f'환급세액:    {abs(diff):,.0f}원')

    # ── 복리/단리 ─────────────────────────────────────────────────
    def _compound_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._cp_principal = _money_spin()
        self._cp_rate      = QDoubleSpinBox(); self._cp_rate.setRange(0, 1000); self._cp_rate.setValue(5); self._cp_rate.setSuffix(' %/년')
        self._cp_years     = QDoubleSpinBox(); self._cp_years.setRange(0, 100); self._cp_years.setValue(10); self._cp_years.setSuffix(' 년')
        self._cp_freq      = QComboBox()
        self._cp_freq.addItems(['연복리 (1회)', '반기복리 (2회)', '분기복리 (4회)', '월복리 (12회)', '단리'])

        f.addRow('원금:', self._cp_principal)
        f.addRow('연이율:', self._cp_rate)
        f.addRow('기간:', self._cp_years)
        f.addRow('이자 방식:', self._cp_freq)

        btn = QPushButton('계산')
        btn.clicked.connect(self._cp_calc)
        self._cp_res = _result_box(100)

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._cp_res)
        lay.addStretch()
        return w

    def _cp_calc(self):
        P = self._cp_principal.value()
        r = self._cp_rate.value() / 100
        t = self._cp_years.value()
        idx = self._cp_freq.currentIndex()
        freq_map = [1, 2, 4, 12]
        if idx == 4:  # 단리
            fv = P * (1 + r * t)
        else:
            n = freq_map[idx]
            fv = P * (1 + r / n) ** (n * t)
        self._cp_res.setPlainText(
            f'원금:       {P:,.0f}원\n'
            f'기간:       {t}년\n'
            f'최종 금액:  {fv:,.0f}원\n'
            f'수익:       {fv - P:,.0f}원  ({(fv/P - 1)*100:.2f}%)')

    # ── 부동산 취득세 ─────────────────────────────────────────────
    def _realestate_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._re_price = _money_spin()
        self._re_type  = QComboBox()
        self._re_type.addItems([
            '주택 (1주택, 6억 이하)',
            '주택 (1주택, 6~9억)',
            '주택 (1주택, 9억 초과)',
            '주택 (2주택, 조정지역)',
            '주택 (3주택 이상)',
            '토지/건물 (주택 외)',
        ])

        f.addRow('취득가액:', self._re_price)
        f.addRow('유형:', self._re_type)

        btn = QPushButton('취득세 계산')
        btn.clicked.connect(self._re_calc)
        self._re_res = _result_box(160)

        info = QLabel('※ 2024년 기준 예상치. 실제 세액은 관할 지자체에서 확인하세요.')
        info.setStyleSheet('color: gray; font-size: 11px;')

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._re_res)
        lay.addWidget(info)
        lay.addStretch()
        return w

    def _re_calc(self):
        p   = self._re_price.value()
        idx = self._re_type.currentIndex()

        # 취득세율 결정
        rate_map = [
            # (취득세율, 농특세율, 지방교육세율)
            (0.01,  0,      0.001),   # 1주택 6억 이하
            (None,  0,      None),    # 1주택 6~9억 (구간 계산)
            (0.03,  0.002,  0.003),   # 1주택 9억 초과
            (0.08,  0.006,  0.004),   # 2주택 조정
            (0.12,  0.01,   0.004),   # 3주택 이상
            (0.04,  0.002,  0.004),   # 토지/건물
        ]

        if idx == 1:  # 6억~9억 구간 세율 계산
            rate = (p / 100_000_000 * 2 - 3) / 100
            rate = max(0.01, min(0.03, rate))
            edu  = rate / 10
            agr  = 0
            tax      = p * rate
            edu_tax  = p * edu
            agr_tax  = 0
        else:
            r, agr_r, edu_r = rate_map[idx]
            tax     = p * r
            agr_tax = p * agr_r
            edu_tax = p * edu_r

        total = tax + agr_tax + edu_tax
        self._re_res.setPlainText(
            f'취득가액:   {_fmt_money(p)}\n'
            f'{"─"*40}\n'
            f'취득세:     {_fmt_money(tax)}\n'
            f'농어촌특별세: {_fmt_money(agr_tax)}\n'
            f'지방교육세:  {_fmt_money(edu_tax)}\n'
            f'{"─"*40}\n'
            f'합계:       {_fmt_money(total)}')

    # ── 세후 수익률 ───────────────────────────────────────────────
    def _return_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()

        self._rt_buy  = _money_spin(); self._rt_buy.setSuffix(' 원 (매수)')
        self._rt_sell = _money_spin(); self._rt_sell.setSuffix(' 원 (매도)')
        self._rt_fee  = QDoubleSpinBox(); self._rt_fee.setRange(0, 10); self._rt_fee.setValue(0.015); self._rt_fee.setSuffix(' % (수수료)')
        self._rt_tax  = QComboBox()
        self._rt_tax.addItems(['양도세 없음 (소액주주 국내주식)', '양도세 22% (해외주식/금융소득)', '양도세 직접입력'])
        self._rt_taxr = QDoubleSpinBox(); self._rt_taxr.setRange(0, 100); self._rt_taxr.setValue(22); self._rt_taxr.setSuffix(' %')
        self._rt_tax.currentIndexChanged.connect(lambda i: self._rt_taxr.setEnabled(i == 2))
        self._rt_taxr.setEnabled(False)

        f.addRow('매수금액:', self._rt_buy)
        f.addRow('매도금액:', self._rt_sell)
        f.addRow('거래 수수료:', self._rt_fee)
        f.addRow('세금 유형:', self._rt_tax)
        f.addRow('세율 (직접입력):', self._rt_taxr)

        btn = QPushButton('수익률 계산')
        btn.clicked.connect(self._rt_calc)
        self._rt_res = _result_box(140)

        lay.addLayout(f)
        lay.addWidget(btn)
        lay.addWidget(self._rt_res)
        lay.addStretch()
        return w

    def _rt_calc(self):
        buy  = self._rt_buy.value()
        sell = self._rt_sell.value()
        fee_r = self._rt_fee.value() / 100
        gain = sell - buy
        fee  = (buy + sell) * fee_r
        tax_idx = self._rt_tax.currentIndex()
        tax_rate = [0, 0.22, self._rt_taxr.value() / 100][tax_idx]
        tax  = max(0, gain) * tax_rate
        net  = gain - fee - tax
        roi  = net / buy * 100 if buy else 0
        self._rt_res.setPlainText(
            f'매수:   {buy:,.0f}원\n'
            f'매도:   {sell:,.0f}원\n'
            f'차익:   {gain:,.0f}원\n'
            f'수수료: {fee:,.0f}원\n'
            f'세금:   {tax:,.0f}원  ({tax_rate*100:.1f}%)\n'
            f'{"─"*35}\n'
            f'순수익: {net:,.0f}원\n'
            f'세후 수익률: {roi:.2f}%')

    # ── 현재/미래가치 ─────────────────────────────────────────────
    def _pv_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        grp1 = QGroupBox('미래가치 계산 (현재 → 미래)')
        f1 = QFormLayout(grp1)
        self._pv_present = _money_spin()
        self._pv_rate    = QDoubleSpinBox(); self._pv_rate.setRange(0, 100); self._pv_rate.setValue(5); self._pv_rate.setSuffix(' %/년')
        self._pv_years   = QSpinBox(); self._pv_years.setRange(1, 100); self._pv_years.setValue(10); self._pv_years.setSuffix(' 년')
        f1.addRow('현재가치:', self._pv_present)
        f1.addRow('연이율:', self._pv_rate)
        f1.addRow('기간:', self._pv_years)
        b1 = QPushButton('계산'); b1.clicked.connect(self._pv_calc); f1.addRow(b1)
        self._pv_res = _result_box(80)

        grp2 = QGroupBox('현재가치 계산 (미래 → 현재)')
        f2 = QFormLayout(grp2)
        self._fv_future = _money_spin()
        self._fv_rate   = QDoubleSpinBox(); self._fv_rate.setRange(0.01, 100); self._fv_rate.setValue(5); self._fv_rate.setSuffix(' %/년')
        self._fv_years  = QSpinBox(); self._fv_years.setRange(1, 100); self._fv_years.setValue(10); self._fv_years.setSuffix(' 년')
        f2.addRow('미래가치:', self._fv_future)
        f2.addRow('할인율:', self._fv_rate)
        f2.addRow('기간:', self._fv_years)
        b2 = QPushButton('계산'); b2.clicked.connect(self._fv_calc); f2.addRow(b2)
        self._fv_res = _result_box(80)

        lay.addWidget(grp1); lay.addWidget(self._pv_res)
        lay.addWidget(grp2); lay.addWidget(self._fv_res)
        return w

    def _pv_calc(self):
        pv = self._pv_present.value()
        r  = self._pv_rate.value() / 100
        n  = self._pv_years.value()
        fv = pv * (1 + r) ** n
        self._pv_res.setPlainText(
            f'현재 {_fmt_money(pv)}  →  {n}년 후  {_fmt_money(fv)}\n'
            f'수익: {_fmt_money(fv - pv)}  ({(fv/pv - 1)*100:.2f}%)')

    def _fv_calc(self):
        fv = self._fv_future.value()
        r  = self._fv_rate.value() / 100
        n  = self._fv_years.value()
        pv = fv / (1 + r) ** n
        self._fv_res.setPlainText(
            f'{n}년 후 {_fmt_money(fv)}의 현재가치:  {_fmt_money(pv)}\n'
            f'할인액: {_fmt_money(fv - pv)}')


# ══════════════════════════════════════════════════════════════════════
# 법률 계산기 (기존 7탭 + 소송비용 + 소멸시효)
# ══════════════════════════════════════════════════════════════════════
class _LegalCalcWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._tabs = QTabWidget()
        self._tabs.addTab(self._make_date_tab(),          '📅 날짜 계산')
        self._tabs.addTab(self._make_interest_tab(),      '⚖ 지연손해금')
        self._tabs.addTab(self._make_lawsuit_cost_tab(),  '🧾 소송비용')
        self._tabs.addTab(self._make_prescription_tab(),  '⏰ 소멸시효')
        self._tabs.addTab(self._make_attorney_fee_tab(),  '👔 변호사보수')
        self._tabs.addTab(self._make_attachment_tab(),    '🔒 가압류 비용')
        self._tabs.addTab(self._make_child_support_tab(), '👶 양육비')
        self._tabs.addTab(self._make_forced_share_tab(),  '🏠 유류분')
        self._tabs.addTab(self._make_payment_alloc_tab(), '💰 변제충당')
        lay = QVBoxLayout(self)
        lay.addWidget(self._tabs)

    def set_tab(self, idx: int):
        self._tabs.setCurrentIndex(idx)

    # ── 공통 ─────────────────────────────────────────────────────
    @staticmethod
    def _money_spin(max_val=999_999_999_999):  return _money_spin(max_val)

    # ── 날짜 계산 ─────────────────────────────────────────────────
    def _make_date_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        grp1 = QGroupBox('두 날짜 사이 기간')
        f1 = QFormLayout(grp1)
        self._d_from = QDateEdit(QDate.currentDate()); self._d_from.setCalendarPopup(True)
        self._d_to   = QDateEdit(QDate.currentDate()); self._d_to.setCalendarPopup(True)
        f1.addRow('시작일:', self._d_from); f1.addRow('종료일:', self._d_to)
        b1 = QPushButton('계산'); b1.clicked.connect(self._calc_date_diff); f1.addRow(b1)
        self._d_diff_res = _result_box(100)

        grp2 = QGroupBox('날짜 가산 / 감산')
        f2 = QFormLayout(grp2)
        self._d_base = QDateEdit(QDate.currentDate()); self._d_base.setCalendarPopup(True)
        self._d_add  = QSpinBox(); self._d_add.setRange(-36500, 36500); self._d_add.setSuffix(' 일')
        f2.addRow('기준일:', self._d_base); f2.addRow('가산일수 (음수=감산):', self._d_add)
        b2 = QPushButton('계산'); b2.clicked.connect(self._calc_date_add); f2.addRow(b2)
        self._d_add_res = _result_box(70)

        lay.addWidget(grp1); lay.addWidget(self._d_diff_res)
        lay.addWidget(grp2); lay.addWidget(self._d_add_res)
        lay.addStretch()
        return w

    def _calc_date_diff(self):
        s = self._d_from.date().toPython(); e = self._d_to.date().toPython()
        if s > e: s, e = e, s
        days   = (e - s).days
        months = (e.year - s.year) * 12 + (e.month - s.month)
        today  = date.today()
        self._d_diff_res.setPlainText(
            f'총 일수:  {days:,}일\n주수:     {days // 7}주 {days % 7}일\n'
            f'개월수:   약 {months}개월\n연수:     약 {months // 12}년 {months % 12}개월\n'
            f'D-day (종료일): {(e - today).days:+}일')

    def _calc_date_add(self):
        base = self._d_base.date().toPython(); d = self._d_add.value()
        res  = base + timedelta(days=d)
        self._d_add_res.setPlainText(
            f'{base}  {d:+}일  →  {res}\n'
            f'D-day: {(res - date.today()).days:+}일')

    # ── 지연손해금 ────────────────────────────────────────────────
    def _make_interest_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        f = QFormLayout()
        self._int_principal = _money_spin()
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
        self._int_custom_rate.setRange(0.01, 100); self._int_custom_rate.setValue(5); self._int_custom_rate.setSuffix(' %')
        self._int_custom_rate.setEnabled(False)
        self._int_start = QDateEdit(QDate.currentDate()); self._int_start.setCalendarPopup(True)
        self._int_end   = QDateEdit(QDate.currentDate()); self._int_end.setCalendarPopup(True)
        self._int_basis = QComboBox(); self._int_basis.addItems(['365일 기준', '360일 기준'])
        f.addRow('원금:', self._int_principal)
        f.addRow('이율 유형:', self._int_rate_type)
        f.addRow('직접입력 이율:', self._int_custom_rate)
        f.addRow('기산일:', self._int_start)
        f.addRow('종기일:', self._int_end)
        f.addRow('연 기준:', self._int_basis)
        btn = QPushButton('이자 계산'); btn.clicked.connect(self._calc_interest)
        self._int_res = _result_box(160)
        lay.addLayout(f); lay.addWidget(btn); lay.addWidget(self._int_res)
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
            f'원금:       {_fmt_money(p)}\n이율:       연 {rate}%\n'
            f'기간:       {s} ~ {e}  ({days}일 / {basis}일 기준)\n'
            f'{"─"*45}\n'
            f'지연손해금: {_fmt_money(interest)}\n원금+이자:  {_fmt_money(p + interest)}')

    # ── 소송비용 (인지대 + 송달료) ────────────────────────────────
    def _make_lawsuit_cost_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        f = QFormLayout()
        self._lc_soga    = _money_spin()
        self._lc_court   = QComboBox()
        self._lc_court.addItems(['민사 (1심)', '민사 (항소심)', '민사 (상고심)',
                                 '가사 (1심)', '행정 (1심)'])
        self._lc_parties = QSpinBox(); self._lc_parties.setRange(2, 20); self._lc_parties.setValue(2); self._lc_parties.setSuffix(' 명 (원고+피고)')
        self._lc_rounds  = QSpinBox(); self._lc_rounds.setRange(1, 30); self._lc_rounds.setValue(12); self._lc_rounds.setSuffix(' 회 (송달 횟수)')
        f.addRow('소가 (청구금액):', self._lc_soga)
        f.addRow('법원/심급:', self._lc_court)
        f.addRow('당사자 수:', self._lc_parties)
        f.addRow('송달 횟수:', self._lc_rounds)
        btn = QPushButton('계산'); btn.clicked.connect(self._lc_calc)
        self._lc_res = _result_box(200)
        info = QLabel('※ 송달료 단가: 5,200원 (2024 기준). 예상치이므로 실제와 다를 수 있습니다.')
        info.setStyleSheet('color: gray; font-size: 11px;')
        lay.addLayout(f); lay.addWidget(btn); lay.addWidget(self._lc_res); lay.addWidget(info)
        lay.addStretch()
        return w

    @staticmethod
    def _calc_stamp(soga: float) -> float:
        import math as _m
        if soga <= 10_000_000:
            stamp = soga * 5 / 1000
        elif soga <= 100_000_000:
            stamp = 50_000 + (soga - 10_000_000) * 45 / 100_000
        elif soga <= 1_000_000_000:
            stamp = 455_000 + (soga - 100_000_000) * 40 / 1_000_000
        else:
            stamp = 3_655_000 + (soga - 1_000_000_000) * 35 / 10_000_000
        stamp = max(1_000, stamp)
        return _m.ceil(stamp / 100) * 100  # 100원 단위 올림

    def _lc_calc(self):
        soga    = self._lc_soga.value()
        court   = self._lc_court.currentIndex()
        parties = self._lc_parties.value()
        rounds  = self._lc_rounds.value()

        stamp1 = self._calc_stamp(soga)
        multipliers = [1.0, 1.5, 2.0, 1.0, 1.0]
        stamp = stamp1 * multipliers[court]
        stamp = math.ceil(stamp / 100) * 100

        delivery_unit = 5200
        delivery = delivery_unit * parties * rounds

        lines = [
            f'소가:      {_fmt_money(soga)}',
            f'{"─"*45}',
            f'[인지대]',
            f'기본 인지액: {_fmt_money(stamp1)}',
        ]
        if court in (1, 2):
            m = multipliers[court]
            lines.append(f'심급 배수:   × {m}배  →  {_fmt_money(stamp)}')
        lines += [
            f'납부 인지액: {_fmt_money(stamp)}',
            f'{"─"*45}',
            f'[송달료]',
            f'송달료:    {delivery_unit:,}원 × {parties}명 × {rounds}회',
            f'         = {_fmt_money(delivery)}',
            f'{"─"*45}',
            f'합계:      {_fmt_money(stamp + delivery)}',
        ]
        self._lc_res.setPlainText('\n'.join(lines))

    # ── 소멸시효 ─────────────────────────────────────────────────
    def _make_prescription_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        f = QFormLayout()
        self._pr_type = QComboBox()
        self._pr_type.addItems([
            '일반 채권 (민법)               10년',
            '상사 채권 (상법)                5년',
            '의료비 채권                     3년',
            '임금/퇴직금 채권               3년',
            '공사대금 채권                   3년',
            '불법행위 손해배상 (사실인지)    3년',
            '불법행위 손해배상 (행위시)     10년',
            '판결 확정 채권 (확정판결)      10년',
            '단기채권 – 여관/음식점 등       1년',
            '단기채권 – 생산자/도매 등       3년',
        ])
        self._pr_start = QDateEdit(QDate.currentDate()); self._pr_start.setCalendarPopup(True)

        f.addRow('채권 유형:', self._pr_type)
        f.addRow('기산일 (채권 발생일):', self._pr_start)

        btn = QPushButton('소멸시효 계산')
        btn.clicked.connect(self._pr_calc)
        self._pr_res = _result_box(140)

        info = QLabel('※ 시효 중단(승인·청구·압류)이 있으면 기산일이 리셋됩니다.\n   실제 법률 판단은 변호사에게 확인하세요.')
        info.setStyleSheet('color: gray; font-size: 11px;')

        lay.addLayout(f); lay.addWidget(btn); lay.addWidget(self._pr_res); lay.addWidget(info)
        lay.addStretch()
        return w

    _PR_YEARS = [10, 5, 3, 3, 3, 3, 10, 10, 1, 3]

    def _pr_calc(self):
        idx    = self._pr_type.currentIndex()
        years  = self._PR_YEARS[idx]
        start  = self._pr_start.date().toPython()
        today  = date.today()

        # 소멸시효 완성일 계산 (년 단위)
        try:
            expiry = start.replace(year=start.year + years)
        except ValueError:
            expiry = start.replace(year=start.year + years, day=28)

        days_left = (expiry - today).days

        if days_left < 0:
            status = f'⚠ 소멸시효 완성  ({abs(days_left)}일 경과)'
        elif days_left == 0:
            status = '⚠ 오늘 소멸시효 완성'
        elif days_left <= 90:
            status = f'⚠ {days_left}일 남음  (주의!)'
        else:
            status = f'✔ {days_left}일 남음'

        self._pr_res.setPlainText(
            f'채권 유형:    {self._pr_type.currentText().strip()}\n'
            f'기산일:       {start}\n'
            f'시효 기간:    {years}년\n'
            f'{"─"*45}\n'
            f'소멸시효 완성일:  {expiry}\n'
            f'상태:         {status}')

    # ── 변호사보수 ────────────────────────────────────────────────
    def _make_attorney_fee_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        f = QFormLayout()
        self._atty_amount = _money_spin()
        f.addRow('소송목적물 가액:', self._atty_amount)
        btn = QPushButton('계산'); btn.clicked.connect(self._calc_attorney_fee)
        self._atty_res = _result_box(100)
        info = QLabel('※ 민사소송비용 산입 변호사보수 (법원규칙 별표)\n'
                      '  2천만 이하→10%  / 2천~5천만→8%  / 5천~1억→6%\n'
                      '  1억~1.5억→4%   / 1.5억~2억→2%  / 2억~5억→1%  / 5억 초과→0.5%')
        info.setStyleSheet('color: gray; font-size: 11px;')
        lay.addLayout(f); lay.addWidget(btn); lay.addWidget(self._atty_res); lay.addWidget(info)
        lay.addStretch(); return w

    @staticmethod
    def _attorney_fee_calc(amount: float) -> float:
        brackets = [(20_000_000,0.10),(50_000_000,0.08),(100_000_000,0.06),
                    (150_000_000,0.04),(200_000_000,0.02),(500_000_000,0.01),(float('inf'),0.005)]
        fee, prev = 0.0, 0.0
        for limit, rate in brackets:
            if amount <= limit:
                fee += (amount - prev) * rate; break
            fee += (limit - prev) * rate; prev = limit
        return fee

    def _calc_attorney_fee(self):
        amt = self._atty_amount.value()
        fee = self._attorney_fee_calc(amt)
        self._atty_res.setPlainText(
            f'소송목적물 가액:         {_fmt_money(amt)}\n'
            f'{"─"*45}\n'
            f'소송비용 산입 변호사보수: {_fmt_money(fee)}')

    # ── 가압류 비용 ───────────────────────────────────────────────
    def _make_attachment_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        f = QFormLayout()
        self._att_amount  = _money_spin()
        self._att_type    = QComboBox(); self._att_type.addItems(['부동산 가압류', '채권 가압류', '동산 가압류'])
        self._att_parties = QSpinBox(); self._att_parties.setRange(1, 10); self._att_parties.setValue(2); self._att_parties.setSuffix(' 명')
        f.addRow('청구채권 금액:', self._att_amount)
        f.addRow('가압류 유형:', self._att_type)
        f.addRow('당사자 수:', self._att_parties)
        btn = QPushButton('계산'); btn.clicked.connect(self._calc_attachment)
        self._att_res = _result_box(200)
        info = QLabel('※ 예상치입니다. 법원 접수 전 확인하세요.')
        info.setStyleSheet('color: gray; font-size: 11px;')
        lay.addLayout(f); lay.addWidget(btn); lay.addWidget(self._att_res); lay.addWidget(info)
        lay.addStretch(); return w

    def _calc_attachment(self):
        amt      = self._att_amount.value()
        att_type = self._att_type.currentText()
        parties  = self._att_parties.value()
        stamp    = max(1_000, min(100_000, amt * 0.0045 / 10))
        delivery = 5_200 * 5 * parties
        reg_tax  = max(3_000, amt * 0.002) if att_type == '부동산 가압류' else 0
        edu_tax  = reg_tax * 0.2
        deposit  = amt / 10
        total_cost = stamp + delivery + reg_tax + edu_tax
        lines = [f'청구채권액:    {_fmt_money(amt)}', f'{"─"*45}', '[신청 비용]',
                 f'인지대:        {_fmt_money(stamp)}', f'송달료:        {_fmt_money(delivery)}  ({parties}명 × 5회)']
        if att_type == '부동산 가압류':
            lines += [f'등록면허세:    {_fmt_money(reg_tax)}', f'지방교육세:    {_fmt_money(edu_tax)}']
        lines += [f'{"─"*45}', f'소계 (실비용): {_fmt_money(total_cost)}',
                  f'{"─"*45}', '[담보 제공]',
                  f'법원보관금:    {_fmt_money(deposit)}  (청구액의 약 1/10)',
                  '  ※ 현금공탁 기준. 지급보증보험 이용 시 보험료만 납부']
        self._att_res.setPlainText('\n'.join(lines))

    # ── 양육비 ───────────────────────────────────────────────────
    def _make_child_support_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        f = QFormLayout()
        self._cs_income_total = QDoubleSpinBox(); self._cs_income_total.setRange(0, 100_000); self._cs_income_total.setValue(400); self._cs_income_total.setSuffix(' 만원/월')
        self._cs_income_nc    = QDoubleSpinBox(); self._cs_income_nc.setRange(0, 100_000); self._cs_income_nc.setValue(200);    self._cs_income_nc.setSuffix(' 만원/월')
        self._cs_age      = QComboBox(); self._cs_age.addItems(['0-2세','3-5세','6-8세','9-11세','12-14세','15-17세'])
        self._cs_children = QSpinBox(); self._cs_children.setRange(1, 10); self._cs_children.setValue(1); self._cs_children.setSuffix(' 명')
        f.addRow('부모 합산 월소득:', self._cs_income_total); f.addRow('비양육자 월소득:', self._cs_income_nc)
        f.addRow('자녀 연령:', self._cs_age); f.addRow('자녀 수:', self._cs_children)
        btn = QPushButton('양육비 산정'); btn.clicked.connect(self._calc_child_support)
        self._cs_res = _result_box(150)
        info = QLabel('※ 서울가정법원 양육비 산정기준표 (2021) 기준')
        info.setStyleSheet('color: gray; font-size: 11px;')
        lay.addLayout(f); lay.addWidget(btn); lay.addWidget(self._cs_res); lay.addWidget(info)
        lay.addStretch(); return w

    _CS_TABLE = [
        (199,  [68,73,79,84,91,104]),(299,  [82,88,97,101,110,125]),
        (399,  [96,103,113,118,128,146]),(499,  [111,119,131,136,148,169]),
        (599,  [126,135,148,154,168,191]),(699,  [141,151,166,172,188,213]),
        (799,  [156,167,184,191,208,235]),(899,  [171,183,202,209,228,258]),
        (999,  [186,199,219,227,248,280]),(9999, [201,215,237,246,268,303]),
    ]

    def _calc_child_support(self):
        it = self._cs_income_total.value(); nc = self._cs_income_nc.value()
        ai = self._cs_age.currentIndex(); n = self._cs_children.value()
        std = 0
        for limit, row in self._CS_TABLE:
            if it <= limit: std = row[ai]; break
        ratio = nc / it if it > 0 else 0.5
        self._cs_res.setPlainText(
            f'부모 합산 소득: {it:.0f}만원/월\n비양육자 소득:  {nc:.0f}만원/월  ({ratio*100:.1f}%)\n'
            f'자녀: {self._cs_age.currentText()} × {n}명\n{"─"*45}\n'
            f'표준 양육비:    {std}만원/월 (1인)\n'
            f'비양육자 부담:  {std*ratio:.1f}만원/인/월\n'
            f'합계 ({n}명):     {std*ratio*n:.1f}만원/월')

    # ── 유류분 ───────────────────────────────────────────────────
    def _make_forced_share_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        f = QFormLayout()
        self._fs_estate   = _money_spin(); self._fs_gift = _money_spin(); self._fs_debt = _money_spin()
        self._fs_spouse   = QComboBox(); self._fs_spouse.addItems(['없음', '배우자 있음'])
        self._fs_children = QSpinBox(); self._fs_children.setRange(0, 20); self._fs_children.setValue(2); self._fs_children.setSuffix(' 명')
        self._fs_parents  = QSpinBox(); self._fs_parents.setRange(0, 2); self._fs_parents.setSuffix(' 명')
        self._fs_siblings = QSpinBox(); self._fs_siblings.setRange(0, 20); self._fs_siblings.setSuffix(' 명')
        f.addRow('상속재산:', self._fs_estate); f.addRow('증여재산 (10년 이내):', self._fs_gift)
        f.addRow('상속채무:', self._fs_debt);   f.addRow('배우자:', self._fs_spouse)
        f.addRow('직계비속 (자녀):', self._fs_children); f.addRow('직계존속 (부모):', self._fs_parents)
        f.addRow('형제자매:', self._fs_siblings)
        btn = QPushButton('유류분 계산'); btn.clicked.connect(self._calc_forced_share)
        self._fs_res = _result_box(220)
        lay.addLayout(f); lay.addWidget(btn); lay.addWidget(self._fs_res); return w

    def _calc_forced_share(self):
        estate = self._fs_estate.value(); gift = self._fs_gift.value(); debt = self._fs_debt.value()
        has_sp = self._fs_spouse.currentIndex() == 1
        n_child = self._fs_children.value(); n_par = self._fs_parents.value(); n_sib = self._fs_siblings.value()
        base = estate + gift - debt
        if base <= 0:
            self._fs_res.setPlainText('유류분 산정 기초재산이 0 이하입니다.'); return
        lines = [f'유류분 기초재산: {_fmt_money(base)}',
                 f'  = 상속 {_fmt_money(estate)} + 증여 {_fmt_money(gift)} - 채무 {_fmt_money(debt)}', f'{"─"*45}']
        heirs = []
        if n_child > 0:
            tp = n_child + (1.5 if has_sp else 0)
            heirs.append(('자녀 (각)', 1.0/tp, 0.5, n_child))
            if has_sp: heirs.append(('배우자', 1.5/tp, 0.5, 1))
        elif n_par > 0:
            tp = n_par + (1.5 if has_sp else 0)
            heirs.append(('부모 (각)', 1.0/tp, 1/3, n_par))
            if has_sp: heirs.append(('배우자', 1.5/tp, 0.5, 1))
        elif n_sib > 0:
            lines.append('※ 형제자매는 유류분권 없음 (헌재 2024년 결정).')
            if has_sp: heirs.append(('배우자', 1.0, 0.5, 1))
        elif has_sp:
            heirs.append(('배우자', 1.0, 0.5, 1))
        for name, ls, fr, cnt in heirs:
            each = base * ls * fr
            lines.append(f'{name}: 법정{ls*100:.2f}% × 유류분{fr*100:.0f}%')
            lines.append(f'  유류분액(1인): {_fmt_money(each)}')
            if cnt > 1: lines.append(f'  합계({cnt}명): {_fmt_money(each*cnt)}')
        self._fs_res.setPlainText('\n'.join(lines))

    # ── 변제충당 ─────────────────────────────────────────────────
    def _make_payment_alloc_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        f = QFormLayout()
        self._pa_principal = _money_spin()
        self._pa_rate = QDoubleSpinBox(); self._pa_rate.setRange(0.01, 100); self._pa_rate.setValue(12); self._pa_rate.setSuffix(' %/년')
        self._pa_start = QDateEdit(QDate.currentDate()); self._pa_start.setCalendarPopup(True)
        self._pa_cost = _money_spin(999_999_999); self._pa_cost.setSuffix(' 원 (부대비용)')
        f.addRow('원금:', self._pa_principal); f.addRow('연이율:', self._pa_rate)
        f.addRow('채무 발생일:', self._pa_start); f.addRow('부대비용:', self._pa_cost)
        pay_grp = QGroupBox('변제 내역')
        pg = QVBoxLayout(pay_grp)
        self._pa_tbl = QTableWidget(0, 2)
        self._pa_tbl.setHorizontalHeaderLabels(['변제일 (YYYY-MM-DD)', '변제액 (원)'])
        self._pa_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._pa_tbl.setMinimumHeight(110)
        add_btn = QPushButton('+ 추가'); add_btn.clicked.connect(self._pa_add_row)
        del_btn = QPushButton('- 삭제'); del_btn.clicked.connect(self._pa_del_row)
        br = QHBoxLayout(); br.addWidget(add_btn); br.addWidget(del_btn); br.addStretch()
        pg.addWidget(self._pa_tbl); pg.addLayout(br)
        calc_btn = QPushButton('변제충당 계산  (비용 → 이자 → 원금)')
        calc_btn.clicked.connect(self._calc_payment_alloc)
        self._pa_res = _result_box(200)
        lay.addLayout(f); lay.addWidget(pay_grp); lay.addWidget(calc_btn); lay.addWidget(self._pa_res)
        return w

    def _pa_add_row(self):
        r = self._pa_tbl.rowCount(); self._pa_tbl.insertRow(r)
        self._pa_tbl.setItem(r, 0, QTableWidgetItem(QDate.currentDate().toString('yyyy-MM-dd')))
        self._pa_tbl.setItem(r, 1, QTableWidgetItem('0'))

    def _pa_del_row(self):
        rows = {i.row() for i in self._pa_tbl.selectedIndexes()}
        for r in sorted(rows, reverse=True): self._pa_tbl.removeRow(r)

    def _calc_payment_alloc(self):
        principal  = self._pa_principal.value()
        daily_rate = self._pa_rate.value() / 100 / 365
        start_dt   = self._pa_start.date().toPython()
        cost_rem   = self._pa_cost.value()
        payments = []
        for r in range(self._pa_tbl.rowCount()):
            try:
                yr, mo, day = map(int, self._pa_tbl.item(r, 0).text().split('-'))
                amt = float(self._pa_tbl.item(r, 1).text().replace(',', ''))
                payments.append((date(yr, mo, day), amt))
            except Exception: continue
        payments.sort()
        rem_prin = principal
        lines = [f'원금: {_fmt_money(principal)}  이율: {self._pa_rate.value()}%/년',
                 f'발생일: {start_dt}  부대비용: {_fmt_money(cost_rem)}', f'{"─"*50}']
        prev_dt = start_dt
        total_cost_paid = total_int_paid = total_prin_paid = 0.0
        for pay_dt, pay_amt in payments:
            if rem_prin <= 0: break
            days    = (pay_dt - prev_dt).days
            accrued = rem_prin * daily_rate * days
            lines.append(f'\n[{pay_dt}] 변제액: {_fmt_money(pay_amt)}  (경과 {days}일, 발생이자: {_fmt_money(accrued)})')
            rem = pay_amt
            if cost_rem > 0 and rem > 0:
                paid = min(cost_rem, rem); cost_rem -= paid; rem -= paid; total_cost_paid += paid
                lines.append(f'  → 비용 충당: {_fmt_money(paid)}  (잔여: {_fmt_money(cost_rem)})')
            if accrued > 0 and rem > 0:
                paid = min(accrued, rem); rem -= paid; total_int_paid += paid
                lines.append(f'  → 이자 충당: {_fmt_money(paid)}  (미충당: {_fmt_money(accrued - paid)})')
            if rem > 0 and rem_prin > 0:
                paid = min(rem_prin, rem); rem_prin -= paid; total_prin_paid += paid
                lines.append(f'  → 원금 충당: {_fmt_money(paid)}  (잔여원금: {_fmt_money(rem_prin)})')
            prev_dt = pay_dt
        lines += [f'\n{"─"*50}', '[최종 잔액]',
                  f'잔여 원금: {_fmt_money(rem_prin)}', f'잔여 비용: {_fmt_money(cost_rem)}',
                  f'충당 합계: 원금 {_fmt_money(total_prin_paid)} + 이자 {_fmt_money(total_int_paid)} + 비용 {_fmt_money(total_cost_paid)}']
        self._pa_res.setPlainText('\n'.join(lines))


# ══════════════════════════════════════════════════════════════════════
# 메인 다이얼로그
# ══════════════════════════════════════════════════════════════════════
class CalculatorDialog(QDialog):
    MODE_BASIC   = 0
    MODE_SCI     = 1
    MODE_LIFE    = 2
    MODE_FINANCE = 3
    MODE_LEGAL   = 4

    def __init__(self, mode: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle('계산기')
        self.setMinimumSize(860, 660)

        # ── 좌측 사이드바 ───────────────────────────────────────
        self._list = QListWidget()
        self._list.setFixedWidth(110)
        self._list.setStyleSheet(
            'QListWidget { border: none; background: #f0f4f8; }'
            'QListWidget::item { padding: 14px 8px; font-size: 13px; border-bottom: 1px solid #dde3ea; }'
            'QListWidget::item:selected { background: #1565c0; color: white; font-weight: bold; }')
        for label in ['🧮 기본', '📐 공학', '🏠 생활', '💰 금융', '⚖ 법률']:
            item = QListWidgetItem(label)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list.addItem(item)

        # ── 우측 스택 ────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.addWidget(_BasicCalcWidget())
        self._stack.addWidget(_SciCalcWidget())
        self._stack.addWidget(_LifeCalcWidget())
        self._stack.addWidget(_FinanceCalcWidget())
        self._stack.addWidget(_LegalCalcWidget())

        self._list.currentRowChanged.connect(self._stack.setCurrentIndex)

        # ── 레이아웃 ─────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self._list)
        body.addWidget(self._stack, 1)

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 8)
        main.addLayout(body, 1)

        close_btn = QPushButton('닫기')
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept)
        br = QHBoxLayout()
        br.setContentsMargins(8, 0, 8, 0)
        br.addStretch()
        br.addWidget(close_btn)
        main.addLayout(br)

        self._list.setCurrentRow(mode)

    def switch_to(self, mode: int):
        self._list.setCurrentRow(mode)

    def legal_widget(self) -> _LegalCalcWidget | None:
        w = self._stack.widget(self.MODE_LEGAL)
        return w if isinstance(w, _LegalCalcWidget) else None
