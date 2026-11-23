"""Galerie de médias d'une conversation (miniatures chargées à la demande)."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListView, QStyle, QStyledItemDelegate

from database.models import MediaRow
from services.media_service import ThumbnailLoader

from .formatting import full_datetime

THUMB = QSize(96, 96)


def _placeholder(text: str, missing: bool) -> QPixmap:
    pm = QPixmap(THUMB)
    pm.fill(QColor("#3b4a59") if not missing else QColor("#5c2b29"))
    p = QPainter(pm)
    p.setPen(QColor("white"))
    p.drawText(pm.rect(), Qt.AlignCenter | Qt.TextWordWrap, text)
    p.end()
    return pm


ACCENT = QColor("#3390ec")


class ThumbnailDelegate(QStyledItemDelegate):
    """Miniature carrée ; sélection bien visible (voile, cadre et coche)."""

    def paint(self, p: QPainter, option, index) -> None:
        view = self.parent()
        size = view.iconSize()
        r = option.rect
        box = QRect(r.x() + (r.width() - size.width()) // 2, r.y() + (r.height() - size.height()) // 2,
                    size.width(), size.height())
        icon = index.data(Qt.DecorationRole)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if isinstance(icon, QIcon):
            clip = QPainterPath()
            clip.addRoundedRect(box, 4, 4)
            p.setClipPath(clip)
            p.drawPixmap(box, icon.pixmap(size))
            p.setClipping(False)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected:
            veil = QColor(ACCENT)
            veil.setAlpha(70)
            p.fillRect(box, veil)
            p.setPen(QPen(ACCENT, 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(1, 1, -2, -2), 4, 4)
        elif hovered:
            p.setPen(QPen(QColor(255, 255, 255, 170), 2))
            p.drawRoundedRect(box.adjusted(1, 1, -1, -1), 4, 4)
        if selected or hovered:
            d = max(18, min(26, size.width() // 6))
            c = QRect(box.right() - d - 5, box.top() + 5, d, d)
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(ACCENT if selected else QColor(0, 0, 0, 90))
            p.drawEllipse(c)
            if selected:
                path = QPainterPath(QPointF(c.left() + d * 0.27, c.top() + d * 0.52))
                path.lineTo(c.left() + d * 0.44, c.top() + d * 0.68)
                path.lineTo(c.left() + d * 0.74, c.top() + d * 0.34)
                p.setPen(QPen(QColor("white"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)
        p.restore()

    def sizeHint(self, option, index) -> QSize:
        view = self.parent()
        return view.gridSize() if view.gridSize().isValid() else view.iconSize()


class MediaGalleryModel(QAbstractListModel):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[MediaRow] = []
        self._keys: dict[str, int] = {}
        self._icons: dict[int, QIcon] = {}
        ThumbnailLoader.instance().loaded.connect(self._on_loaded)

    def set_items(self, items: list[MediaRow]) -> None:
        self.beginResetModel()
        self.items = items
        self._keys.clear()
        self._icons.clear()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        m = self.items[index.row()]
        if role == Qt.DecorationRole:
            return self._icon(index.row(), m)
        if role == Qt.ToolTipRole:
            state = "" if m.file_available else "\n⚠ fichier introuvable"
            return f"{m.message_sender or ''}\n{full_datetime(m.message_date)}\n{m.file_path or ''}{state}"
        if role == Qt.UserRole:
            return m
        return None

    def _icon(self, row: int, m: MediaRow) -> QIcon:
        if row in self._icons:
            return self._icons[row]
        src = m.abs_thumbnail if m.thumbnail_available else (m.abs_file if m.file_available and m.media_type == "photo" else None)
        label = {"video": "▶ Vidéo", "animation": "GIF", "video_message": "▶", "sticker": "Autocollant"}.get(m.media_type, "Photo")
        if src is None:
            icon = QIcon(_placeholder(label + "\nintrouvable" if not m.file_available else label, not m.file_available))
            self._icons[row] = icon
            return icon
        key, pm = ThumbnailLoader.instance().request(src, THUMB * 2)
        if pm is not None:
            icon = QIcon(self._decorate(pm, m))
            self._icons[row] = icon
            return icon
        self._keys[key] = row
        return QIcon(_placeholder("…", False))

    def _decorate(self, pm: QPixmap, m: MediaRow) -> QPixmap:
        # Recadrage carré centré + pictogramme pour les vidéos
        side = min(pm.width(), pm.height())
        sq = pm.copy((pm.width() - side) // 2, (pm.height() - side) // 2, side, side).scaled(
            THUMB, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        if m.media_type in ("video", "animation", "video_message") or not m.file_available:
            p = QPainter(sq)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QColor(0, 0, 0, 150))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(4, THUMB.height() - 22, 40 if m.file_available else 70, 18, 5, 5)
            p.setPen(QColor("white") if m.file_available else QColor("#ff8a80"))
            p.drawText(8, THUMB.height() - 9, "▶" if m.file_available and m.media_type != "animation"
                       else ("GIF" if m.file_available else "⚠ absent"))
            p.end()
        return sq

    def _on_loaded(self, key: str, pm: QPixmap) -> None:
        row = self._keys.pop(key, None)
        if row is None or row >= len(self.items):
            return
        m = self.items[row]
        self._icons[row] = QIcon(self._decorate(pm, m)) if not pm.isNull() else QIcon(_placeholder("illisible", True))
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [Qt.DecorationRole])


class MediaGallery(QListView):
    media_activated = Signal(MediaRow)       # double-clic : ouvrir
    media_selected = Signal(MediaRow)        # clic : aller au message
    copy_requested = Signal(list)            # clic droit : copier vers un dossier

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model_ = MediaGalleryModel()
        self.setModel(self.model_)
        self.setViewMode(QListView.IconMode)
        self.setIconSize(THUMB)
        self.setGridSize(THUMB + QSize(6, 6))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setItemDelegate(ThumbnailDelegate(self))
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.clicked.connect(self._clicked)
        self.doubleClicked.connect(lambda i: self.media_activated.emit(i.data(Qt.UserRole)))

    def _clicked(self, index) -> None:
        # Ctrl/Maj + clic : on construit une sélection, sans sauter au message
        if QApplication.keyboardModifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            return
        self.media_selected.emit(index.data(Qt.UserRole))

    def selected_medias(self) -> list[MediaRow]:
        rows = sorted(i.row() for i in self.selectionModel().selectedIndexes())
        return [self.model_.items[r] for r in rows if r < len(self.model_.items)]

    def _menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        idx = self.indexAt(pos)
        selected = self.selected_medias()
        if idx.isValid() and idx.data(Qt.UserRole) not in selected:
            selected = [idx.data(Qt.UserRole)]
        menu = QMenu(self)
        n = len(selected)
        label = "Copier vers un dossier…" if n <= 1 else f"Copier les {n} médias sélectionnés vers un dossier…"
        menu.addAction(label, lambda: self.copy_requested.emit(selected)).setEnabled(n > 0)
        menu.addAction("Copier tous les médias de la conversation…",
                       lambda: self.copy_requested.emit(list(self.model_.items))).setEnabled(bool(self.model_.items))
        menu.exec(self.viewport().mapToGlobal(pos))

    def set_items(self, items: list[MediaRow]) -> None:
        self.model_.set_items(items)
