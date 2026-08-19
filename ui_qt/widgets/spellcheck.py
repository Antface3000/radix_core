"""App-wide spellcheck for QPlainTextEdit / QTextEdit (pyenchant + QSyntaxHighlighter)."""

from __future__ import annotations

import os
import re
import weakref
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QEvent, Qt, QTimer
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QTextCursor, QKeyEvent
from PySide6.QtWidgets import (
    QPlainTextEdit, QTextEdit, QMenu, QWidget, QHBoxLayout, QLabel,
    QPushButton, QComboBox,
)

import config

_COMMON_TYPOS = {
    "teh": "the",
    "adn": "and",
    "recieve": "receive",
    "occured": "occurred",
    "seperate": "separate",
    "definately": "definitely",
    "untill": "until",
    "wich": "which",
}

try:
    import enchant
    ENCHANT_AVAILABLE = True
except ImportError:
    enchant = None
    ENCHANT_AVAILABLE = False

if TYPE_CHECKING:
    from PySide6.QtGui import QTextDocument

_SPELL_ATTR = "_radix_spellcheck_highlighter"
_SKIP_ATTR = "_radix_spellcheck_skip"


def _cpp_valid(obj) -> bool:
    """True if the Qt C++ backing object still exists."""
    if obj is None:
        return False
    try:
        from shiboken6 import isValid
        return isValid(obj)
    except ImportError:
        return True


class SpellCheckHighlighter(QSyntaxHighlighter):
    def __init__(self, document: "QTextDocument", language: str = "en_US",
                 shared_dict=None):
        super().__init__(document)
        self._enabled = ENCHANT_AVAILABLE
        self._dict = shared_dict
        if self._dict is None and ENCHANT_AVAILABLE:
            try:
                self._dict = enchant.Dict(language)
            except enchant.Error:
                self._enabled = False
        fmt = QTextCharFormat()
        fmt.setUnderlineColor(QColor("#E03A3A"))
        fmt.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
        self._miss_fmt = fmt
        self._ignore: set[str] = set()

    @property
    def available(self) -> bool:
        return self._enabled and self._dict is not None

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled and self._dict is not None
        if not _cpp_valid(self):
            return
        try:
            self.rehighlight()
        except RuntimeError:
            pass

    def suggest(self, word: str) -> list[str]:
        if not self._dict:
            return []
        try:
            return self._dict.suggest(word)
        except Exception:
            return []

    def highlightBlock(self, text: str) -> None:
        if not self._enabled or not self._dict:
            return
        for match in re.finditer(r"[A-Za-z']+", text):
            word = match.group()
            if len(word) < 2:
                continue
            if word.lower() in self._ignore:
                continue
            if not self._dict.check(word):
                self.setFormat(match.start(), match.end() - match.start(), self._miss_fmt)


class SpellCheckService:
    """Shared dictionary + registry of highlighters across the app."""

    _instance: "SpellCheckService | None" = None

    def __init__(self, language: str = "en_US"):
        self._language = language
        self._dict = None
        self._global_enabled = True
        self._highlighters: list[weakref.ref] = []
        self._ignore: set[str] = set()
        if ENCHANT_AVAILABLE:
            try:
                self._dict = enchant.Dict(language)
            except enchant.Error:
                self._dict = None
        self._load_user_words()

    @classmethod
    def instance(cls) -> "SpellCheckService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def available(self) -> bool:
        return self._dict is not None

    def suggest(self, word: str) -> list[str]:
        if not self._dict:
            return []
        try:
            return self._dict.suggest(word)
        except Exception:
            return []

    def _prune(self) -> None:
        alive: list[weakref.ref] = []
        for ref in self._highlighters:
            hl = ref()
            if hl is not None and _cpp_valid(hl):
                alive.append(ref)
        self._highlighters = alive

    def _register(self, hl: SpellCheckHighlighter) -> None:
        self._prune()
        if _cpp_valid(hl):
            self._highlighters.append(weakref.ref(hl))

    def set_enabled(self, enabled: bool) -> None:
        self._global_enabled = bool(enabled)
        self._prune()
        for ref in self._highlighters:
            hl = ref()
            if hl is None or not _cpp_valid(hl):
                continue
            try:
                hl.set_enabled(self._global_enabled)
            except RuntimeError:
                pass
        self._prune()

    def _user_words_path(self) -> str:
        return os.path.join(config.DATA_DIR, "user_dictionary.txt")

    def _load_user_words(self) -> None:
        path = self._user_words_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                words = [w.strip() for w in fh if w.strip()]
        except OSError:
            words = []
        if self._dict:
            for w in words:
                try:
                    self._dict.add(w)
                except Exception:
                    pass

    def add_to_dictionary(self, word: str) -> None:
        word = (word or "").strip()
        if not word or not self._dict:
            return
        try:
            self._dict.add(word)
        except Exception:
            pass
        os.makedirs(config.DATA_DIR, exist_ok=True)
        path = self._user_words_path()
        existing = set()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                existing = {ln.strip() for ln in fh}
        except OSError:
            pass
        if word not in existing:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(word + "\n")
        self._rehighlight_all()

    def ignore_word(self, word: str) -> None:
        word = (word or "").strip().lower()
        if not word:
            return
        self._ignore.add(word)
        self._prune()
        for ref in self._highlighters:
            hl = ref()
            if hl is not None and _cpp_valid(hl):
                hl._ignore.add(word)
                try:
                    hl.rehighlight()
                except RuntimeError:
                    pass

    def _rehighlight_all(self) -> None:
        self._prune()
        for ref in self._highlighters:
            hl = ref()
            if hl is None or not _cpp_valid(hl):
                continue
            try:
                hl.rehighlight()
            except RuntimeError:
                pass

    def word_at_cursor(self, widget: QPlainTextEdit | QTextEdit) -> tuple[str, QTextCursor]:
        cursor = widget.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        return cursor.selectedText(), cursor

    def is_misspelled(self, word: str) -> bool:
        if not word or not self._dict or len(word) < 2:
            return False
        if word.lower() in self._ignore:
            return False
        try:
            return not self._dict.check(word)
        except Exception:
            return False

    def autocorrect_candidate(self, word: str) -> str | None:
        key = (word or "").lower()
        if key in _COMMON_TYPOS:
            repl = _COMMON_TYPOS[key]
            return repl if word[:1].isupper() else repl
        if not self.is_misspelled(word):
            return None
        suggestions = self.suggest(word)
        if len(suggestions) == 1:
            return suggestions[0]
        return None

    def highlighter_for(self, widget: QWidget) -> SpellCheckHighlighter | None:
        return getattr(widget, _SPELL_ATTR, None)

    def attach(self, widget: QPlainTextEdit | QTextEdit) -> SpellCheckHighlighter | None:
        if getattr(widget, _SKIP_ATTR, False):
            return None
        if widget.isReadOnly():
            return None
        existing = getattr(widget, _SPELL_ATTR, None)
        if existing and _cpp_valid(existing):
            existing.set_enabled(self._global_enabled)
            return existing
        if existing is not None:
            try:
                delattr(widget, _SPELL_ATTR)
            except AttributeError:
                pass
        hl = SpellCheckHighlighter(widget.document(), self._language, self._dict)
        hl._ignore = set(self._ignore)
        hl.set_enabled(self._global_enabled)
        setattr(widget, _SPELL_ATTR, hl)
        self._register(hl)
        if widget.contextMenuPolicy() == Qt.ContextMenuPolicy.DefaultContextMenu:
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(
                lambda pos, w=widget: self._context_menu(w, pos))
        return hl

    def attach_subtree(self, root: QWidget | None) -> None:
        if root is None:
            return
        for widget in root.findChildren(QPlainTextEdit):
            self.attach(widget)
        for widget in root.findChildren(QTextEdit):
            self.attach(widget)

    def _context_menu(self, widget: QPlainTextEdit | QTextEdit, pos) -> None:
        hl = getattr(widget, _SPELL_ATTR, None)
        if hl is not None and not _cpp_valid(hl):
            hl = None
        menu = widget.createStandardContextMenu()
        cursor = widget.cursorForPosition(pos)
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText()
        if word and hl and hl.available and self.is_misspelled(word):
            suggestions = hl.suggest(word)
            sub = QMenu("Spelling", widget)
            for suggestion in suggestions[:8]:
                act = sub.addAction(suggestion)
                act.triggered.connect(
                    lambda _checked=False, w=suggestion, c=cursor: self._replace_word(c, w))
            ign = sub.addAction("Ignore")
            ign.triggered.connect(lambda _c=False, w=word: self.ignore_word(w))
            add = sub.addAction("Add to dictionary")
            add.triggered.connect(lambda _c=False, w=word: self.add_to_dictionary(w))
            menu.addSeparator()
            menu.addMenu(sub)
        menu.exec(widget.mapToGlobal(pos))

    @staticmethod
    def _replace_word(cursor: QTextCursor, word: str) -> None:
        cursor.insertText(word)


def skip_spellcheck(widget: QWidget) -> None:
    """Mark a text widget as excluded from app-wide spellcheck."""
    setattr(widget, _SKIP_ATTR, True)


def install_spellcheck_subtree(root: QWidget | None) -> None:
    SpellCheckService.instance().attach_subtree(root)


def set_spellcheck_enabled(enabled: bool) -> None:
    SpellCheckService.instance().set_enabled(enabled)


class SpellCheckWatcher(QObject):
    """Attach spellcheck to text widgets as they are added anywhere under a root."""

    def __init__(self, root: QWidget, parent: QObject | None = None):
        super().__init__(parent)
        self._svc = SpellCheckService.instance()
        self._watching: set[int] = set()
        self._watch_tree(root)

    def _watch_tree(self, root: QWidget) -> None:
        self._svc.attach_subtree(root)
        for widget in [root, *root.findChildren(QWidget)]:
            wid = id(widget)
            if wid in self._watching:
                continue
            self._watching.add(wid)
            widget.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QWidget):
                self._watch_tree(child)
            elif isinstance(child, (QPlainTextEdit, QTextEdit)):
                self._svc.attach(child)
        return False


class SpellReplaceBar(QWidget):
    """Inline accept / ignore / add-to-dictionary bar for the word under the cursor."""

    def __init__(self, editor: QPlainTextEdit, parent=None):
        super().__init__(parent)
        self._editor = editor
        self._cursor: QTextCursor | None = None
        self._word = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        self._label = QLabel("")
        row.addWidget(self._label)
        self._more = QComboBox()
        self._more.setMinimumWidth(140)
        self._more.activated.connect(self._apply_combo)
        row.addWidget(self._more)
        self._accept = QPushButton("Replace")
        self._accept.clicked.connect(self._apply_first)
        row.addWidget(self._accept)
        ign = QPushButton("Ignore")
        ign.clicked.connect(self._ignore)
        row.addWidget(ign)
        add = QPushButton("Add to dictionary")
        add.clicked.connect(self._add)
        row.addWidget(add)
        self._grammar = QLabel("")
        self._grammar.setProperty("muted", True)
        row.addWidget(self._grammar, 1)
        self.hide()

    def refresh(self, settings=None):
        svc = SpellCheckService.instance()
        word, cursor = svc.word_at_cursor(self._editor)
        self._word = word
        self._cursor = cursor
        grammar_note = ""
        if settings is not None:
            try:
                from src.plugins.grammar import load_checker
                checker = load_checker(settings)
                if checker:
                    pos = self._editor.textCursor().position()
                    for issue in checker(self._editor.toPlainText())[:20]:
                        start = int(issue.get("offset") or 0)
                        length = int(issue.get("length") or 0)
                        if start <= pos <= start + max(length, 1):
                            grammar_note = issue.get("message") or ""
                            reps = issue.get("replacements") or []
                            if reps and not svc.is_misspelled(word):
                                self._more.clear()
                                self._more.addItems([str(r) for r in reps[:8]])
                                self._label.setText(grammar_note)
                                self._grammar.setText("Grammar plugin")
                                self.show()
                                return
            except Exception:
                grammar_note = ""
        if not svc.available or not svc.is_misspelled(word):
            self.hide()
            return
        suggestions = svc.suggest(word)
        self._label.setText(word)
        self._more.clear()
        self._more.addItems(suggestions[:8] or ["(no suggestions)"])
        self._grammar.setText(grammar_note)
        self.show()

    def _apply_combo(self, index: int):
        text = self._more.itemText(index)
        if text and text != "(no suggestions)" and self._cursor:
            SpellCheckService._replace_word(self._cursor, text)
            self.hide()

    def _apply_first(self):
        if self._more.count() and self._more.itemText(0) != "(no suggestions)":
            self._apply_combo(0)

    def _ignore(self):
        SpellCheckService.instance().ignore_word(self._word)
        self.hide()

    def _add(self):
        SpellCheckService.instance().add_to_dictionary(self._word)
        self.hide()

