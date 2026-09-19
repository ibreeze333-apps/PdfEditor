from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSlider, QWidget

_BLUR_MODE_ITEMS = [
    ('\uac15\ud55c \ube14\ub7ec', 'gaussian'),
    ('\ud53d\uc140\ud654', 'pixelate'),
    ('\ub178\uc774\uc988 \uc11e\uae30', 'noise'),
    ('\ucd95\uc18c \ud6c4 \uc7ac\ud655\ub300', 'downscale'),
]


class MosaicPanel(QWidget):
    """Toolbar options for the non-destructive blur tool."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tool = None
        self._build_ui()
        self.hide()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(8)

        layout.addWidget(QLabel('\ube14\ub7ec \ubc29\uc2dd:'))
        self._mode_combo = QComboBox()
        for label, value in _BLUR_MODE_ITEMS:
            self._mode_combo.addItem(label, value)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self._mode_combo)

        self._param_label = QLabel('\uac15\ub3c4:')
        layout.addWidget(self._param_label)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(6, 36)
        self._slider.setValue(12)
        self._slider.setFixedWidth(140)
        self._slider.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self._slider)

        self._val_label = QLabel('12')
        self._val_label.setFixedWidth(28)
        layout.addWidget(self._val_label)

        layout.addStretch()

    def _update_settings(self):
        settings = getattr(self._tool, '_settings_ref', None) if self._tool is not None else None
        if settings is None:
            return
        settings.blur_mode = getattr(self._tool, 'blur_mode', 'gaussian')
        settings.blur_strength = int(getattr(self._tool, 'blur_radius', 12))

    def _on_mode_changed(self, index: int):
        if self._tool is None:
            return
        self._tool.blur_mode = self._mode_combo.itemData(index) or 'gaussian'
        self._update_settings()

    def _on_value_changed(self, value: int):
        self._val_label.setText(str(value))
        if self._tool is None:
            return
        self._tool.blur_radius = value
        self._update_settings()

    def tool_changed(self, tool):
        is_blur_tool = getattr(tool, 'mode', '') == 'blur' and hasattr(tool, 'blur_radius')
        if is_blur_tool:
            self._tool = tool
            mode = getattr(tool, 'blur_mode', 'gaussian') or 'gaussian'
            strength = int(getattr(tool, 'blur_radius', 12) or 12)
            self._mode_combo.blockSignals(True)
            idx = max(0, self._mode_combo.findData(mode))
            self._mode_combo.setCurrentIndex(idx)
            self._mode_combo.blockSignals(False)
            self._slider.blockSignals(True)
            self._slider.setValue(max(self._slider.minimum(), min(self._slider.maximum(), strength)))
            self._slider.blockSignals(False)
            self._val_label.setText(str(self._slider.value()))
            self.show()
            self.raise_()
        else:
            self._tool = None
            self.hide()
