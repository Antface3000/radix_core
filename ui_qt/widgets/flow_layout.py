"""Flow layout — wraps child widgets onto new lines when width is tight."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget, QWidgetItem


class FlowLayout(QLayout):
    """Horizontal flow that wraps to the next line (Qt cookbook pattern)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        margin: int = 0,
        hspacing: int = 6,
        vspacing: int = 6,
    ):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._hspace = hspacing
        self._vspace = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def addWidget(self, widget: QWidget) -> None:
        self.addChildWidget(widget)
        self.addItem(QWidgetItem(widget))
        widget.installEventFilter(self)
        self.invalidate()

    def eventFilter(self, watched, event):
        if event.type() in (
                QEvent.Type.Show, QEvent.Type.Hide,
                QEvent.Type.ShowToParent, QEvent.Type.HideToParent):
            self.invalidate()
            parent = self.parentWidget()
            if parent is not None:
                parent.updateGeometry()
        return False

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _hspace_for(self, item: QLayoutItem) -> int:
        if self._hspace >= 0:
            return self._hspace
        wid = item.widget()
        if wid is not None:
            return wid.style().layoutSpacing(
                QSizePolicy.ControlType.PushButton,
                QSizePolicy.ControlType.PushButton,
                Qt.Orientation.Horizontal,
            )
        return 6

    def _vspace_for(self, item: QLayoutItem) -> int:
        if self._vspace >= 0:
            return self._vspace
        wid = item.widget()
        if wid is not None:
            return wid.style().layoutSpacing(
                QSizePolicy.ControlType.PushButton,
                QSizePolicy.ControlType.PushButton,
                Qt.Orientation.Vertical,
            )
        return 6

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            wid = item.widget()
            if wid is not None and not wid.isVisible():
                continue
            space_x = self._hspace_for(item)
            space_y = self._vspace_for(item)
            hint = item.sizeHint()
            next_x = x + hint.width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + hint.width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + m.bottom()


def make_flow_row(
    *widgets: QWidget,
    parent: QWidget | None = None,
    margin: int = 0,
    hspacing: int = 6,
    vspacing: int = 6,
) -> QWidget:
    """Wrap widgets in a flow container ready to add to a parent layout."""
    host = QWidget(parent)
    flow = FlowLayout(host, margin=margin, hspacing=hspacing, vspacing=vspacing)
    for w in widgets:
        if w is not None:
            flow.addWidget(w)
    return host
