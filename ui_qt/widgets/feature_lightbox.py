"""Floating feature panel window (lightbox) with optional stay-open pin."""

from __future__ import annotations

import config
from PySide6.QtCore import (
    Qt, Signal, QEasingCurve, QPoint, QPropertyAnimation, QSize,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QGraphicsDropShadowEffect, QPushButton, QSizePolicy,
)


class FeatureLightbox(QWidget):
    """Movable, resizable pop-out hosting one feature panel."""

    closed = Signal(str)
    stay_open_changed = Signal(str, bool)
    geometry_saved = Signal(str, dict)

    def __init__(self, feature_name: str, app, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.feature_name = feature_name
        self.app = app
        self._content: QWidget | None = None

        self.setWindowTitle(feature_name)
        self.setObjectName("FeatureLightbox")
        self.setMinimumSize(340, 400)
        w, h = self._default_size()
        self.resize(w, h)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("FeatureLightboxHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 6, 8, 6)
        self._title = QLabel(feature_name)
        self._title.setObjectName("FeatureLightboxTitle")
        hl.addWidget(self._title, 1)
        self.stay_open = QCheckBox("Stay open")
        self.stay_open.setToolTip(
            "Keep this panel open when opening other panels or switching projects")
        self.stay_open.toggled.connect(self._on_stay_open)
        hl.addWidget(self.stay_open)
        close_btn = QPushButton("×")
        close_btn.setFixedSize(28, 28)
        close_btn.setProperty("secondary", True)
        close_btn.setToolTip("Close panel")
        close_btn.clicked.connect(self.close)
        hl.addWidget(close_btn)
        root.addWidget(header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(8, 8, 8, 8)
        self._body_layout.setSpacing(6)
        root.addWidget(self._body, 1)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)

        shadow = QGraphicsDropShadowEffect(self._body)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 140))
        self._body.setGraphicsEffect(shadow)

        self._fade: QPropertyAnimation | None = None

    def showEvent(self, event):
        super().showEvent(event)
        # Quick fade-in on every open (~120ms).
        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(120)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.start()

    def _default_size(self) -> tuple[int, int]:
        s = self.app.settings
        w = int(s.get("ui.lightbox_default_width", config.LIGHTBOX_DEFAULT_WIDTH))
        h = int(s.get("ui.lightbox_default_height", config.LIGHTBOX_DEFAULT_HEIGHT))
        return max(340, w), max(400, h)

    def set_content(self, widget: QWidget):
        if self._content is widget:
            return
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._content = widget
        if widget.parent() is not self._body:
            widget.setParent(self._body)
        self._body_layout.addWidget(widget)

    def _on_stay_open(self, checked: bool):
        self.stay_open_changed.emit(self.feature_name, checked)

    def restore_geometry(self, geo: dict | None):
        dw, dh = self._default_size()
        if not geo:
            self.resize(dw, dh)
            return
        try:
            w = max(dw, int(geo.get("width", dw)))
            h = max(400, int(geo.get("height", dh)))
            x = int(geo.get("x", 100))
            y = int(geo.get("y", 80))
            self.resize(QSize(w, h))
            self.move(QPoint(x, y))
        except (TypeError, ValueError):
            self.resize(dw, dh)

    def geometry_dict(self) -> dict:
        g = self.geometry()
        return {"x": g.x(), "y": g.y(), "width": g.width(), "height": g.height()}

    def closeEvent(self, event):
        self.geometry_saved.emit(self.feature_name, self.geometry_dict())
        self.closed.emit(self.feature_name)
        super().closeEvent(event)

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.isVisible():
            self.geometry_saved.emit(self.feature_name, self.geometry_dict())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self.geometry_saved.emit(self.feature_name, self.geometry_dict())
