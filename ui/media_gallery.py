"""Galerie de médias d'une conversation (miniatures chargées à la demande)."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListView, QStyle, QStyledItemDelegate

from app import design, icons
from database.models import MediaRow
from services.media_service import ThumbnailLoader

from .formatting import full_datetime, short_date

THUMB = QSize(96, 96)

TYPE_LABELS = {"video": "Vidéo", "animation": "GIF", "video_message": "Vidéo", "sticker": "Autocollant",
               "photo": "Photo"}


def thumb_placeholder(m: MediaRow, size: QSize, loading: bool = False) -> QPixmap:
    """Vignette d'attente ou de fichier absent : pictogramme du type, fond du thème."""
    t = design.current()
    missing = not m.file_available and not loading and not m.not_included
    ratio = 2
    pm = QPixmap(size * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(QColor(t.danger_soft if missing else t.panel))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    ic = max(18, min(34, size.width() // 4))
    name = "alert" if missing else icons.MEDIA_ICONS.get(m.media_type, "image")
    color = t.danger if missing else (t.faint if loading else t.muted)
    y = size.height() // 2 - ic + (0 if size.height() > 70 else 6)
    p.drawPixmap((size.width() - ic) // 2, y, icons.pixmap(name, color, ic))
    if not loading and size.height() > 70:
        f = p.font()
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(QColor(color))
        label = "Introuvable" if missing else ("Non inclus" if m.not_included else TYPE_LABELS.get(m.media_type, ""))
        p.drawText(QRect(4, size.height() // 2 + 4, size.width() - 8, 20), Qt.AlignCenter, label)
    p.end()
    return pm


def thumb_decorate(pm: QPixmap, m: MediaRow, size: QSize) -> QPixmap:
    """Recadrage carré centré, badge de type (vidéo, GIF) ou d'absence en haut à gauche."""
    side = min(pm.width(), pm.height())
    sq = pm.copy((pm.width() - side) // 2, (pm.height() - side) // 2, side, side).scaled(
        size * 2, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    sq.setDevicePixelRatio(2)
    badge = None
    if m.media_type in ("video", "video_message"):
        badge = ("play", m.duration_raw or "")
    elif m.media_type == "animation":
        badge = (None, "GIF")
    if not m.file_available and not m.not_included:
        badge = ("alert", "absent")
    if badge:
        p = QPainter(sq)
        p.setRenderHint(QPainter.Antialiasing)
        f = p.font()
        f.setPointSizeF(7.6)
        f.setBold(True)
        p.setFont(f)
        icon_name, text = badge
        tw = p.fontMetrics().horizontalAdvance(text) if text else 0
        w = 10 + (12 if icon_name else 0) + (tw + (4 if icon_name and text else 0)) + 4
        r = QRect(6, 6, max(w, 22), 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 16, 28, 170))
        p.drawRoundedRect(r, 10, 10)
        x = r.left() + 7
        warn = icon_name == "alert"
        if icon_name:
            p.drawPixmap(x, r.top() + 4, icons.pixmap(icon_name, "#FF9A94" if warn else "#FFFFFF", 12))
            x += 15
        if text:
            p.setPen(QColor("#FF9A94") if warn else QColor("white"))
            p.drawText(QRect(x, r.top(), tw + 2, r.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()
    return sq


class ThumbnailDelegate(QStyledItemDelegate):
    """Miniature carrée arrondie ; survol (date, expéditeur) et sélection bien visibles."""

    RADIUS = 10

    def paint(self, p: QPainter, option, index) -> None:
        view = self.parent()
        t = design.current()
        size = view.iconSize()
        r = option.rect
        box = QRect(r.x() + (r.width() - size.width()) // 2, r.y() + (r.height() - size.height()) // 2,
                    size.width(), size.height())
        icon = index.data(Qt.DecorationRole)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(box), self.RADIUS, self.RADIUS)
        p.setClipPath(clip)
        if isinstance(icon, QIcon):
            p.drawPixmap(box, icon.pixmap(size))
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        m = index.data(Qt.UserRole)
        if hovered and m is not None and box.height() >= 90:
            grad = QLinearGradient(0, box.bottom() - 46, 0, box.bottom())
            grad.setColorAt(0, QColor(10, 16, 28, 0))
            grad.setColorAt(1, QColor(10, 16, 28, 190))
            p.fillRect(QRect(box.left(), box.bottom() - 46, box.width(), 47), grad)
            f = QFont(option.font)
            f.setPointSizeF(max(7.5, option.font.pointSizeF() * 0.8))
            p.setFont(f)
            p.setPen(QColor("white"))
            info = " · ".join(x for x in (short_date(m.message_date), m.message_sender or "") if x)
            p.drawText(box.adjusted(8, 0, -8, -6), Qt.AlignBottom | Qt.AlignLeft,
                       p.fontMetrics().elidedText(info, Qt.ElideRight, box.width() - 16))
        if selected:
            veil = QColor(t.accent)
            veil.setAlpha(60)
            p.fillRect(box, veil)
        p.setClipping(False)
        if selected:
            p.setPen(QPen(QColor(t.accent), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(box).adjusted(1.5, 1.5, -1.5, -1.5), self.RADIUS - 1, self.RADIUS - 1)
        elif hovered:
            p.setPen(QPen(QColor(t.accent), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(box).adjusted(0.75, 0.75, -0.75, -0.75), self.RADIUS, self.RADIUS)
        if option.state & QStyle.State_HasFocus and not selected and view.hasFocus():
            p.setPen(QPen(QColor(t.accent), 1, Qt.DashLine))
            p.drawRoundedRect(QRectF(box).adjusted(1, 1, -1, -1), self.RADIUS, self.RADIUS)
        if selected or hovered:
            d = max(18, min(24, size.width() // 6))
            c = QRect(box.right() - d - 6, box.top() + 6, d, d)
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(QColor(t.accent) if selected else QColor(10, 16, 28, 90))
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
        self.size = QSize(THUMB)
        ThumbnailLoader.instance().loaded.connect(self._on_loaded)

    def set_size(self, size: QSize) -> None:
        if size != self.size:
            self.beginResetModel()
            self.size = QSize(size)
            self._icons.clear()
            self._keys.clear()
            self.endResetModel()

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
        src = m.abs_thumbnail if m.thumbnail_available else (
            m.abs_file if m.file_available and m.media_type in ("photo", "sticker") else None)
        if src is None:
            icon = QIcon(thumb_placeholder(m, self.size))
            self._icons[row] = icon
            return icon
        key, pm = ThumbnailLoader.instance().request(src, self.size * 2)
        if pm is not None:
            icon = QIcon(thumb_decorate(pm, m, self.size))
            self._icons[row] = icon
            return icon
        self._keys[key] = row
        return QIcon(thumb_placeholder(m, self.size, loading=True))

    def _on_loaded(self, key: str, pm: QPixmap) -> None:
        row = self._keys.pop(key, None)
        if row is None or row >= len(self.items):
            return
        m = self.items[row]
        self._icons[row] = QIcon(thumb_decorate(pm, m, self.size) if not pm.isNull() else thumb_placeholder(m, self.size))
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
        self.setGridSize(THUMB + QSize(8, 8))
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

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        # 3 colonnes (ou plus) qui occupent toute la largeur du panneau
        # largeur utile en réservant la barre de défilement (qui peut apparaître ensuite)
        w = self.width() - self.verticalScrollBar().sizeHint().width() - 8
        cols = max(3, w // 120)
        side = max(56, (w - cols * 8) // cols - 1)
        size = QSize(side, side)
        if size != self.iconSize():
            self.setIconSize(size)
            self.setGridSize(size + QSize(8, 8))
            self.model_.set_size(size)
