"""Zone gauche : liste des conversations avec recherche par nom et tri."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QRect, QSize, QSortFilterProxyModel, Qt, Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListView, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from app.styles import sender_color
from database.models import ConversationSummary

from .formatting import plural, short_date

ROLE_CONV = Qt.UserRole + 1
ROLE_SORT_DATE = Qt.UserRole + 2


class ConversationModel(QAbstractListModel):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[ConversationSummary] = []

    def set_items(self, items: list[ConversationSummary]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        c = self.items[index.row()]
        if role == Qt.DisplayRole:
            return c.name
        if role == ROLE_CONV:
            return c
        if role == ROLE_SORT_DATE:
            return c.last_date or ""
        if role == Qt.ToolTipRole:
            return f"{c.name}\n{plural(c.message_count, 'message')}\nArchive(s) : {', '.join(c.archives)}"
        return None

    def row_of(self, conv_id: str) -> int:
        return next((i for i, c in enumerate(self.items) if c.id == conv_id), -1)


class ConversationFilter(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.setSortLocaleAware(True)
        self.mode = "date"

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode == "date":
            self.setSortRole(ROLE_SORT_DATE)
            self.sort(0, Qt.DescendingOrder)
        else:
            self.setSortRole(Qt.DisplayRole)
            self.sort(0, Qt.AscendingOrder)


class ConversationDelegate(QStyledItemDelegate):
    HEIGHT = 64

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(200, self.HEIGHT)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        c: ConversationSummary = index.data(ROLE_CONV)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        pal = option.palette
        r = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            p.fillRect(r, pal.color(QPalette.Highlight))
        elif option.state & QStyle.State_MouseOver:
            p.fillRect(r, pal.color(QPalette.AlternateBase))
        fg = QColor("#ffffff") if selected else pal.color(QPalette.Text)
        muted = QColor(255, 255, 255, 200) if selected else pal.color(QPalette.PlaceholderText)

        # Avatar
        d = 46
        av = QRect(r.left() + 10, r.top() + (r.height() - d) // 2, d, d)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(sender_color(None, c.name)))
        p.drawEllipse(av)
        f = QFont(option.font)
        f.setBold(True)
        f.setPointSizeF(option.font.pointSizeF() * 1.25)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(av, Qt.AlignCenter, (c.name[:1] or "?").upper())

        x = av.right() + 12
        right = r.right() - 10
        # Date
        fsmall = QFont(option.font)
        fsmall.setPointSizeF(option.font.pointSizeF() * 0.85)
        p.setFont(fsmall)
        date_txt = short_date(c.last_date)
        dw = QFontMetrics(fsmall).horizontalAdvance(date_txt)
        p.setPen(muted)
        p.drawText(QRect(right - dw, r.top() + 10, dw, 20), Qt.AlignRight | Qt.AlignVCenter, date_txt)
        # Nom
        fb = QFont(option.font)
        fb.setBold(True)
        p.setFont(fb)
        p.setPen(fg)
        name_rect = QRect(x, r.top() + 10, right - dw - 8 - x, 20)
        p.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(fb).elidedText(c.name, Qt.ElideRight, name_rect.width()))
        # Compteur
        p.setFont(fsmall)
        count = f"{c.message_count:,}".replace(",", " ")
        cw = QFontMetrics(fsmall).horizontalAdvance(count) + 12
        badge = QRect(right - cw, r.top() + 34, cw, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 60) if selected else pal.color(QPalette.AlternateBase))
        p.drawRoundedRect(badge, 9, 9)
        p.setPen(muted)
        p.drawText(badge, Qt.AlignCenter, count)
        # Aperçu
        prev = (c.last_preview or "").replace("\n", " ")
        if c.last_sender:
            prev = f"{c.last_sender} : {prev}"
        p.setFont(option.font)
        p.setPen(muted)
        prev_rect = QRect(x, r.top() + 34, badge.left() - 8 - x, 18)
        p.drawText(prev_rect, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(option.font).elidedText(prev, Qt.ElideRight, prev_rect.width()))
        p.restore()


class ConversationList(QWidget):
    conversation_selected = Signal(str)
    sort_changed = Signal(str)
    archive_filter_changed = Signal(object)      # id d'archive ou None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setMinimumWidth(280)
        self.model = ConversationModel()
        self.proxy = ConversationFilter()
        self.proxy.setSourceModel(self.model)

        self.search = QLineEdit(placeholderText="Rechercher une conversation…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)

        self.sort = QComboBox()
        self.sort.addItem("Plus récentes", "date")
        self.sort.addItem("Alphabétique", "name")
        self.sort.currentIndexChanged.connect(self._on_sort)

        self.archive_filter = QComboBox()
        self.archive_filter.setToolTip("Afficher les conversations d'une seule archive")
        self.archive_filter.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.archive_filter.setMinimumContentsLength(10)
        self.archive_filter.currentIndexChanged.connect(
            lambda: self.archive_filter_changed.emit(self.archive_filter.currentData()))
        self.archive_filter.hide()

        self.view = QListView()
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(ConversationDelegate(self.view))
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.selectionModel().currentChanged.connect(self._on_current)

        self.count_label = QLabel(objectName="Muted")

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.sort)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 0, 4)
        lay.addLayout(top)
        lay.addWidget(self.archive_filter)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.count_label)
        self.proxy.set_mode("date")

    def set_conversations(self, items: list[ConversationSummary]) -> None:
        current = self.current_id()
        self.view.selectionModel().blockSignals(True)
        self.model.set_items(items)
        self.proxy.set_mode(self.proxy.mode)
        self.view.selectionModel().blockSignals(False)
        self.count_label.setText(plural(len(items), "conversation"))
        if current:
            self.select(current, emit=False)

    def set_archives(self, archives: list[tuple[int, str]]) -> None:
        """Renseigne le filtre par archive (masqué s'il n'y a qu'une archive)."""
        current = self.archive_filter.currentData()
        self.archive_filter.blockSignals(True)
        self.archive_filter.clear()
        self.archive_filter.addItem("Toutes les archives", None)
        for aid, name in archives:
            self.archive_filter.addItem(name, aid)
        i = self.archive_filter.findData(current)
        self.archive_filter.setCurrentIndex(i if i >= 0 else 0)
        self.archive_filter.blockSignals(False)
        self.archive_filter.setVisible(len(archives) > 1)
        if i < 0 and current is not None:
            self.archive_filter_changed.emit(None)

    def set_sort_mode(self, mode: str) -> None:
        i = self.sort.findData(mode)
        if i >= 0:
            self.sort.setCurrentIndex(i)

    def current_id(self) -> str | None:
        idx = self.view.currentIndex()
        c = idx.data(ROLE_CONV) if idx.isValid() else None
        return c.id if c else None

    def select(self, conv_id: str, emit: bool = True) -> bool:
        row = self.model.row_of(conv_id)
        if row < 0:
            return False
        idx = self.proxy.mapFromSource(self.model.index(row))
        if not idx.isValid():
            self.search.clear()
            idx = self.proxy.mapFromSource(self.model.index(row))
        self.view.selectionModel().blockSignals(not emit)
        self.view.setCurrentIndex(idx)
        self.view.selectionModel().blockSignals(False)
        self.view.scrollTo(idx)
        return True

    def _on_current(self, idx: QModelIndex, _prev: QModelIndex) -> None:
        c = idx.data(ROLE_CONV) if idx.isValid() else None
        if c:
            self.conversation_selected.emit(c.id)

    def _on_sort(self) -> None:
        mode = self.sort.currentData()
        self.proxy.set_mode(mode)
        self.sort_changed.emit(mode)
