"""Floating feature panel window (lightbox) with optional stay-open pin."""

from __future__ import annotations

import config
from PySide6.QtCore import (
    Qt, Signal, QEasingCurve, QPropertyAnimation,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QGraphicsDropShadowEffect, QPushButton, QSizePolicy,
)
from ui_qt.window_geom import fit_widget, max_window_size


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
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(340, 400)
        mw, mh = max_window_size(self)
        if self.minimumWidth() > mw or self.minimumHeight() > mh:
            self.setMinimumSize(min(340, mw), min(400, mh))
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
        close_btn.setObjectName("FeatureCloseButton")
        close_btn.setFixedSize(30, 30)
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
        fit_widget(self)
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
        mw, mh = max_window_size(self)
        return max(self.minimumWidth(), min(w, mw)), max(self.minimumHeight(), min(h, mh))

    def _on_stay_open(self, checked: bool):
        self.stay_open_changed.emit(self.feature_name, checked)

    def restore_geometry(self, geo: dict | None):
        dw, dh = self._default_size()
        if not geo:
            fit_widget(self, width=dw, height=dh, center=True)
            return
        try:
            w = max(self.minimumWidth(), int(geo.get("width", dw)))
            h = max(self.minimumHeight(), int(geo.get("height", dh)))
            x = int(geo.get("x", 100))
            y = int(geo.get("y", 80))
            fit_widget(self, width=w, height=h, x=x, y=y)
        except (TypeError, ValueError):
            fit_widget(self, width=dw, height=dh, center=True)

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
        widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._body_layout.addWidget(widget, 1)

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
