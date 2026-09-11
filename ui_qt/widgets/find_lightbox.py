"""Compact Find lightbox for the manuscript editor."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class FindLightbox(QWidget):
    """Small tool window: query, options, previous/next."""

    def __init__(self, editor):
        # Tool window stays above the editor without stealing the whole app.
        super().__init__(
            editor.window(),
            Qt.WindowType.Tool
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint,
        )
        self.editor = editor
        self.setObjectName("FindLightbox")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle("Find in chapter")
        self.setFixedWidth(360)
        self.setMinimumHeight(150)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Find")
        title.setObjectName("FindLightboxTitle")
        header.addWidget(title, 1)
        close_btn = QPushButton("×")
        close_btn.setObjectName("FeatureCloseButton")
        close_btn.setFixedSize(30, 30)
        close_btn.setToolTip("Close (Esc)")
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn)
        root.addLayout(header)

        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Find in this chapter…")
        self.entry.returnPressed.connect(self.editor._find_next)
        root.addWidget(self.entry)

        opts = QHBoxLayout()
        self.case = QCheckBox("Match case")
        self.case.setToolTip("Aa — case sensitive")
        self.case.toggled.connect(self.editor._sync_find_settings)
        opts.addWidget(self.case)
        self.whole = QCheckBox("Whole word")
        self.whole.setToolTip("Match whole words only")
        self.whole.toggled.connect(self.editor._sync_find_settings)
        opts.addWidget(self.whole)
        self.regex = QCheckBox("Regex")
        self.regex.setToolTip("Regular expression")
        self.regex.toggled.connect(self.editor._sync_find_settings)
        opts.addWidget(self.regex)
        opts.addStretch()
        root.addLayout(opts)

        row = QHBoxLayout()
        prev = QPushButton("Previous")
        prev.setProperty("secondary", True)
        prev.setToolTip("Previous match (Shift+Enter)")
        prev.clicked.connect(self.editor._find_prev)
        next_btn = QPushButton("Next")
        next_btn.setToolTip("Next match (Enter)")
        next_btn.clicked.connect(self.editor._find_next)
        row.addWidget(prev)
        row.addWidget(next_btn)
        root.addLayout(row)

        tip = QLabel("Enter · next    Shift+Enter · previous    Esc · close")
        tip.setProperty("muted", True)
        tip.setWordWrap(True)
        root.addWidget(tip)

        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        QShortcut(QKeySequence("Shift+Return"), self, activated=self.editor._find_prev)
        QShortcut(QKeySequence("Shift+Enter"), self, activated=self.editor._find_prev)

    def present(self):
        """Show near the editor, seed from selection, focus the field."""
        ed = self.editor.editor
        sel = ed.textCursor().selectedText().replace("\u2029", "\n").strip()
        if sel and "\n" not in sel and len(sel) < 200:
            self.entry.setText(sel)
            self.entry.selectAll()
        self.editor._load_find_settings()

        parent = self.editor.window()
        self.show()
        if parent is not None:
            geo = parent.geometry()
            self.adjustSize()
            x = geo.x() + geo.width() - self.width() - 40
            y = geo.y() + 80
            from ui_qt.window_geom import fit_widget
            fit_widget(self, width=self.width(), height=self.height(), x=x, y=y)
        self.raise_()
        self.activateWindow()
        self.entry.setFocus()
        self.entry.selectAll()
