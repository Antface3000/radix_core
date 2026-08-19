"""Before/after diff viewer for the Editor Write pipeline stages."""

from __future__ import annotations

import difflib
import html

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
)

_INS_STYLE = "background-color:#2A3D10; color:#D6F55A;"
_DEL_STYLE = "background-color:#3A1414; color:#E08A8A; text-decoration:line-through;"


def _tokenize(text: str) -> list[str]:
    """Split into words + trailing whitespace so joins reproduce the text."""
    import re
    return re.findall(r"\S+\s*", text or "")

def build_inline_diff_html(before: str, after: str) -> str:
    """Word-level inline diff as HTML."""
    a, b = _tokenize(before), _tokenize(after)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    parts: list[str] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            parts.append(html.escape("".join(a[i1:i2])))
        elif op == "delete":
            parts.append(
                f'<span style="{_DEL_STYLE}">{html.escape("".join(a[i1:i2]))}</span>')
        elif op == "insert":
            parts.append(
                f'<span style="{_INS_STYLE}">{html.escape("".join(b[j1:j2]))}</span>')
        else:  # replace
            parts.append(
                f'<span style="{_DEL_STYLE}">{html.escape("".join(a[i1:i2]))}</span>'
                f'<span style="{_INS_STYLE}">{html.escape("".join(b[j1:j2]))}</span>')
    body = "".join(parts).replace("\n", "<br>")
    return (
        '<div style="font-family:Segoe UI, sans-serif; font-size:13px; '
        f'line-height:1.5;">{body}</div>')


class DraftDiffDialog(QDialog):
    """Shows what each critic pass changed, stage by stage."""

    def __init__(self, parent, stages: list[tuple[str, str]]):
        """stages: ordered list of (persona display name, draft text)."""
        super().__init__(parent)
        self.setWindowTitle("Write pipeline — what changed")
        self.resize(720, 520)
        self._stages = stages

        v = QVBoxLayout(self)
        hint = QLabel(
            "Additions are highlighted lime; removals are struck through red.")
        hint.setProperty("muted", True)
        v.addWidget(hint)

        self.pair_combo = QComboBox()
        for i in range(1, len(stages)):
            self.pair_combo.addItem(
                f"{stages[i - 1][0]}  →  {stages[i][0]}", i)
        self.pair_combo.currentIndexChanged.connect(self._render)
        v.addWidget(self.pair_combo)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        v.addWidget(self.view, 1)

        if len(stages) >= 2:
            self._render()
        else:
            self.view.setHtml(
                "<i>Only one stage ran — no critic revisions to compare.</i>")

    def _render(self, _index: int = 0):
        idx = self.pair_combo.currentData()
        if not idx:
            return
        before = self._stages[idx - 1][1]
        after = self._stages[idx][1]
        self.view.setHtml(build_inline_diff_html(before, after))
