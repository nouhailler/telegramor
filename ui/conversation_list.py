"""Zone gauche : liste des conversations avec recherche par nom et tri."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QRect, QRectF, QSize, QSortFilterProxyModel, Qt, Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListView, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from app import design, icons
from app.design import sender_color
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
    """Ligne de conversation : avatar, nom, extrait, date, indicateurs discrets."""

    HEIGHT = 68

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(200, self.HEIGHT)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        c: ConversationSummary = index.data(ROLE_CONV)
        t = design.current()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        card = QRectF(r.adjusted(8, 2, -8, -2))
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected or hovered:
            path = QPainterPath()
            path.addRoundedRect(card, 10, 10)
            p.fillPath(path, QColor(t.accent_soft if selected else t.hover))
        if selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.accent))
            p.drawRoundedRect(QRectF(card.left(), card.top() + 14, 3, card.height() - 28), 1.5, 1.5)
        if option.state & QStyle.State_HasFocus and option.state & QStyle.State_KeyboardFocusChange:
            p.setPen(QPen(QColor(t.accent), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        fg = QColor(t.text)
        muted = QColor(t.muted)

        # Avatar
        d = 42
        av = QRect(int(card.left()) + 10, r.top() + (r.height() - d) // 2, d, d)
        base = QColor(sender_color(None, c.name))
        grad = QLinearGradient(av.topLeft(), av.bottomRight())
        grad.setColorAt(0, base.lighter(112))
        grad.setColorAt(1, base.darker(106))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawEllipse(av)
        f = QFont(option.font)
        f.setBold(True)
        f.setPointSizeF(option.font.pointSizeF() * 1.15)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(av, Qt.AlignCenter, (c.name[:1] or "?").upper())

        x = av.right() + 12
        right = int(card.right()) - 12
        top = r.top() + 13
        # Date
        fsmall = QFont(option.font)
        fsmall.setPointSizeF(option.font.pointSizeF() * 0.84)
        p.setFont(fsmall)
        date_txt = short_date(c.last_date)
        fms = QFontMetrics(fsmall)
        dw = fms.horizontalAdvance(date_txt)
        p.setPen(QColor(t.accent_text) if selected else QColor(t.faint))
        p.drawText(QRect(right - dw, top, dw, 20), Qt.AlignRight | Qt.AlignVCenter, date_txt)
        # Nom
        fb = QFont(option.font)
        fb.setWeight(QFont.DemiBold)
        p.setFont(fb)
        p.setPen(fg)
        name_rect = QRect(x, top, right - dw - 10 - x, 20)
        p.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(fb).elidedText(c.name, Qt.ElideRight, name_rect.width()))
        # Indicateurs discrets : médias, archives multiples, nombre de messages
        y2 = top + 22
        badges = []
        if c.media_count:
            badges.append(("image", f"{c.media_count:,}".replace(",", " ")))
        if len(c.archives) > 1:
            badges.append(("archive", str(len(c.archives))))
        bx = right
        p.setFont(fsmall)
        for icon_name, label in reversed(badges):
            tw = fms.horizontalAdvance(label)
            bx -= tw
            p.setPen(muted)
            p.drawText(QRect(bx, y2, tw, 18), Qt.AlignVCenter | Qt.AlignRight, label)
            bx -= 15
            p.drawPixmap(bx, y2 + 3, icons.pixmap(icon_name, t.faint, 12))
            bx -= 8
        # Aperçu du dernier message
        prev = (c.last_preview or "").replace("\n", " ")
        if c.last_sender:
            prev = f"{c.last_sender} : {prev}"
        p.setFont(option.font)
        p.setPen(muted)
        prev_rect = QRect(x, y2, bx - 6 - x, 18)
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
        self.setMinimumWidth(design.CONV_LIST_MIN)
        self.model = ConversationModel()
        self.proxy = ConversationFilter()
        self.proxy.setSourceModel(self.model)

        self.search = QLineEdit(placeholderText="Filtrer les conversations…")
        self.search.setProperty("variant", "search")
        self.search.setAccessibleName("Filtrer les conversations par nom")
        self.search.setToolTip("Filtrer la liste par nom de conversation (Ctrl+K)")
        self._search_icon = self.search.addAction(icons.icon("search", design.current().muted, 16),
                                                  QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)

        self.sort = QComboBox()
        self.sort.setProperty("variant", "ghost")
        self.sort.setToolTip("Ordre des conversations")
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
        self.view.setAccessibleName("Liste des conversations")
        self.view.selectionModel().currentChanged.connect(self._on_current)

        self.count_label = QLabel(objectName="Muted")
        self.count_label.setProperty("role", "caption")

        meta = QHBoxLayout()
        meta.setContentsMargins(4, 0, 0, 0)
        meta.addWidget(self.count_label)
        meta.addStretch(1)
        meta.addWidget(self.sort)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 6)
        lay.setSpacing(6)
        head = QVBoxLayout()
        head.setContentsMargins(14, 0, 14, 0)
        head.setSpacing(6)
        head.addWidget(self.search)
        head.addWidget(self.archive_filter)
        head.addLayout(meta)
        lay.addLayout(head)
        lay.addWidget(self.view, 1)
        self.proxy.set_mode("date")

    def retheme(self) -> None:
        self._search_icon.setIcon(icons.icon("search", design.current().muted, 16))
        self.view.viewport().update()

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
