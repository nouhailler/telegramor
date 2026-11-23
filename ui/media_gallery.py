"""Galerie de médias d'une conversation (miniatures chargées à la demande)."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QListView

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
        self.clicked.connect(lambda i: self.media_selected.emit(i.data(Qt.UserRole)))
        self.doubleClicked.connect(lambda i: self.media_activated.emit(i.data(Qt.UserRole)))

    def set_items(self, items: list[MediaRow]) -> None:
        self.model_.set_items(items)
