"""Recherche globale : résultats paginés de toutes les conversations et archives."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAbstractTextDocumentLayout, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPalette, QTextDocument,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListView, QScrollArea, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QToolButton, QVBoxLayout, QWidget,
)

from app import design, icons
from app.design import name_color
from app.styles import Theme
from database.repositories import media_label
from database.search_engine import SearchEngine, SearchError, SearchHit, SearchQuery

from .advanced_search import SearchFilters
from .formatting import parse_iso, plural, short_date

PAGE_SIZE = 50
ROLE_HIT = Qt.UserRole + 1


class SearchResultsModel(QAbstractListModel):
    """Modèle paginé : la page suivante est chargée quand la liste arrive en bas."""

    error = Signal(str)

    def __init__(self, engine: SearchEngine) -> None:
        super().__init__()
        self.engine = engine
        self.query: SearchQuery | None = None
        self.hits: list[SearchHit] = []
        self.total = 0
        self.terms: list[str] = []
        self.elapsed_ms = 0.0

    def run(self, query: SearchQuery | None) -> None:
        self.beginResetModel()
        self.query = query
        self.hits, self.total, self.terms = [], 0, []
        if query is not None and not query.is_empty():
            try:
                page = self.engine.search(query, 0, PAGE_SIZE)
                self.hits, self.total, self.terms, self.elapsed_ms = page.hits, page.total, page.terms, page.elapsed_ms
            except SearchError as exc:
                self.error.emit(str(exc))
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.hits)

    def canFetchMore(self, parent=QModelIndex()) -> bool:  # noqa: N802
        return not parent.isValid() and self.query is not None and len(self.hits) < self.total

    def fetchMore(self, parent=QModelIndex()) -> None:  # noqa: N802
        if not self.canFetchMore(parent):
            return
        page = self.engine.search(self.query, len(self.hits), PAGE_SIZE)
        if not page.hits:
            self.total = len(self.hits)
            return
        self.beginInsertRows(QModelIndex(), len(self.hits), len(self.hits) + len(page.hits) - 1)
        self.hits.extend(page.hits)
        self.endInsertRows()

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        h = self.hits[index.row()]
        if role == ROLE_HIT:
            return h
        if role == Qt.DisplayRole:
            return f"{h.conversation_name} — {h.sender or ''}"
        if role == Qt.ToolTipRole:
            dt = parse_iso(h.date_local)
            return (f"{h.conversation_name}\n{h.sender or ''} · {dt.strftime('%d/%m/%Y %H:%M') if dt else ''}\n"
                    f"Archive : {h.archive_name}")
        return None


def _type_label(h: SearchHit) -> str:
    if h.kind == "service":
        return "Événement"
    if h.media_types:
        return ", ".join(dict.fromkeys(media_label(t) or t for t in h.media_types))
    return "Lien" if h.has_link else "Texte"


class SearchResultDelegate(QStyledItemDelegate):
    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        fm = QFontMetrics(option.font)
        return QSize(200, fm.height() * 4 + 30)

    def paint(self, p, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        h: SearchHit = index.data(ROLE_HIT)
        p.save()
        th = design.current()
        r = option.rect
        pal = option.palette
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        p.setRenderHint(QPainter.Antialiasing)
        card = QRectF(r.adjusted(8, 3, -8, -3))
        path = QPainterPath()
        path.addRoundedRect(card, 10, 10)
        if selected:
            p.fillPath(path, QColor(th.accent_soft))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(th.accent))
            p.drawRoundedRect(QRectF(card.left(), card.top() + 12, 3, card.height() - 24), 1.5, 1.5)
        elif hovered:
            p.fillPath(path, QColor(th.hover))
        else:
            p.setPen(QColor(th.border))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        fg = QColor(th.text)
        muted = QColor(th.muted)
        fm = QFontMetrics(option.font)
        lh = fm.height()
        x, right = int(card.left()) + 14, int(card.right()) - 12
        y = int(card.top()) + 8

        # Ligne 1 : conversation + date
        bold = QFont(option.font)
        bold.setBold(True)
        small = QFont(option.font)
        small.setPointSizeF(option.font.pointSizeF() * 0.85)
        date_txt = short_date(h.date_local)
        p.setFont(small)
        dw = QFontMetrics(small).horizontalAdvance(date_txt)
        p.setPen(muted)
        p.drawText(right - dw, y, dw, lh, Qt.AlignRight | Qt.AlignVCenter, date_txt)
        p.setFont(bold)
        p.setPen(fg)
        p.drawText(x, y, right - dw - 8 - x, lh, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(bold).elidedText(h.conversation_name, Qt.ElideRight, right - dw - 8 - x))
        y += lh + 1

        # Ligne 2 : expéditeur · type · archive
        p.setFont(small)
        sender = h.sender or "—"
        p.setPen(QColor(name_color(None, h.sender, th)))
        sw = QFontMetrics(small).horizontalAdvance(sender)
        p.drawText(x, y, sw, lh, Qt.AlignLeft | Qt.AlignVCenter, sender)
        p.setPen(muted)
        meta = f"  ·  {_type_label(h)}  ·  {h.archive_name}"
        p.drawText(x + sw, y, right - x - sw, lh, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(small).elidedText(meta, Qt.ElideRight, right - x - sw))
        y += lh + 2

        # Lignes 3-4 : extrait avec termes surlignés
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDocumentMargin(0)
        mark_bg = th.highlight
        color = th.text
        doc.setDefaultStyleSheet(f"body {{ color: {color}; }} mark {{ background-color: {mark_bg}; color: {color}; }}")
        doc.setHtml(f"<body>{h.snippet_html.replace(chr(10), ' ')}</body>")
        doc.setTextWidth(right - x)
        p.translate(x, y)
        clip = QRectF(0, 0, right - x, lh * 2 + 2)
        p.setClipRect(clip)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.clip = clip
        ctx.palette.setColor(QPalette.Text, fg)
        doc.documentLayout().draw(p, ctx)
        p.restore()


class GlobalSearchPanel(QWidget):
    """Panneau de résultats (remplace la liste des conversations pendant une recherche)."""

    hit_selected = Signal(object, list)      # SearchHit, termes à surligner
    closed = Signal()

    def __init__(self, engine: SearchEngine, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setMinimumWidth(design.CONV_LIST_MIN)
        self.engine = engine
        self.text = ""

        title = QLabel("Résultats")
        title.setProperty("role", "section")
        self.filters_btn = QToolButton(text="Filtres", toolTip="Afficher les filtres de recherche avancée")
        self.filters_btn.setCheckable(True)
        self.filters_btn.setProperty("variant", "secondary")
        self.filters_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        icons.bind(self.filters_btn, "filters", "muted", 16)
        close = QToolButton(toolTip="Fermer la recherche (Échap)")
        close.setAccessibleName("Fermer la recherche")
        icons.bind(close, "close", "muted", 16)
        close.clicked.connect(self.closed)
        head = QHBoxLayout()
        head.setContentsMargins(14, 0, 10, 0)
        head.addWidget(title, 1)
        head.addWidget(self.filters_btn)
        head.addWidget(close)

        self.filters = SearchFilters()
        self.filters_area = QScrollArea()
        self.filters_area.setWidget(self.filters)
        self.filters_area.setWidgetResizable(True)
        self.filters_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.filters_area.setMaximumHeight(500)
        self.filters_area.setVisible(False)
        self.filters_btn.toggled.connect(self.filters_area.setVisible)
        self.filters.changed.connect(self._schedule)

        self.status = QLabel()
        self.status.setProperty("role", "caption")
        self.status.setWordWrap(True)
        self.status.setContentsMargins(14, 0, 14, 0)

        self.model = SearchResultsModel(engine)
        self.model.error.connect(lambda e: self.status.setText(f"Recherche impossible : {e}"))
        self.view = QListView()
        self.view.setModel(self.model)
        self.delegate = SearchResultDelegate(theme, self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.selectionModel().currentChanged.connect(self._on_current)
        self.view.clicked.connect(self._emit_index)

        self._timer = QTimer(self, singleShot=True, interval=300, timeout=self.run)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 6)
        lay.setSpacing(8)
        lay.addLayout(head)
        lay.addWidget(self.filters_area)
        lay.addWidget(self.status)
        lay.addWidget(self.view, 1)

    def set_theme(self, theme: Theme) -> None:
        self.delegate.theme = theme
        self.view.viewport().update()

    def set_text(self, text: str, immediate: bool = False) -> None:
        self.text = text
        if immediate:
            self.run()
        else:
            self._schedule()

    def _schedule(self) -> None:
        n = self.filters.active_count()
        self.filters_btn.setText(f"Filtres ({n})" if n else "Filtres")
        self._timer.start()

    def current_query(self) -> SearchQuery:
        return self.filters.to_query(self.text)

    def run(self) -> None:
        self._timer.stop()
        q = self.current_query()
        if q.is_empty():
            self.model.run(None)
            self.status.setText("Saisissez des mots ou choisissez des filtres. "
                                "Astuces : \"expression exacte\", -mot pour exclure.")
            return
        self.model.run(q)
        if self.model.total == 0:
            self.status.setText("Aucun résultat.")
        else:
            self.status.setText(f"{plural(self.model.total, 'résultat')} "
                                f"({self.model.elapsed_ms:.0f} ms)")

    @property
    def terms(self) -> list[str]:
        return self.model.terms

    def _on_current(self, idx: QModelIndex, _prev: QModelIndex) -> None:
        self._emit_index(idx)

    def _emit_index(self, idx: QModelIndex) -> None:
        if idx.isValid():
            self.hit_selected.emit(idx.data(ROLE_HIT), self.model.terms)

    def focus_results(self) -> None:
        if self.model.rowCount():
            self.view.setFocus()
            if not self.view.currentIndex().isValid():
                self.view.setCurrentIndex(self.model.index(0))
