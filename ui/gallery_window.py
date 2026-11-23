"""Galerie multimédia complète : photos, vidéos, GIF, fichiers, audio et liens de toute la bibliothèque."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QListView, QMenu, QSlider,
    QStackedWidget, QTabBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from database.models import MediaRow
from database.repositories import LibraryRepository, media_label
from services.media_service import ThumbnailLoader, human_size, open_url, open_with_system, show_in_folder

from .formatting import full_datetime, month_label, plural, short_date
from .media_viewer import ImageViewer, play_video

PAGE = 200
TABS = [
    ("Photos", ("photo",)),
    ("Vidéos", ("video", "video_message")),
    ("GIF et autocollants", ("animation", "sticker")),
    ("Fichiers", ("file",)),
    ("Audio et vocaux", ("audio", "voice")),
    ("Liens", ()),
]
VISUAL_TABS = {0, 1, 2}


class GalleryModel(QAbstractListModel):
    """Grille de miniatures paginée ; les miniatures se chargent à l'affichage."""

    def __init__(self, repo: LibraryRepository) -> None:
        super().__init__()
        self.repo = repo
        self.items: list[MediaRow] = []
        self.total = 0
        self.args: dict = {}
        self.size = QSize(128, 128)
        self._icons: dict[int, QIcon] = {}
        self._keys: dict[str, int] = {}
        ThumbnailLoader.instance().loaded.connect(self._on_loaded)

    def load(self, **args) -> None:
        self.beginResetModel()
        self.args = args
        self.total = self.repo.gallery_count(args["types"], args.get("conversation_id"), args.get("sender"),
                                             args.get("year"), args.get("archive_id"))
        self.items = self.repo.gallery_page(offset=0, limit=PAGE, **args)
        self._icons.clear()
        self._keys.clear()
        self.endResetModel()

    def set_icon_size(self, size: QSize) -> None:
        self.beginResetModel()
        self.size = size
        self._icons.clear()
        self._keys.clear()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.items)

    def canFetchMore(self, parent=QModelIndex()) -> bool:  # noqa: N802
        return not parent.isValid() and len(self.items) < self.total

    def fetchMore(self, parent=QModelIndex()) -> None:  # noqa: N802
        more = self.repo.gallery_page(offset=len(self.items), limit=PAGE, **self.args)
        if not more:
            self.total = len(self.items)
            return
        self.beginInsertRows(QModelIndex(), len(self.items), len(self.items) + len(more) - 1)
        self.items.extend(more)
        self.endInsertRows()

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        m = self.items[index.row()]
        if role == Qt.DecorationRole:
            return self._icon(index.row(), m)
        if role == Qt.ToolTipRole:
            state = "" if m.file_available else ("\n(non inclus dans l'export)" if m.not_included
                                                  else "\n⚠ fichier introuvable")
            return (f"{m.conversation_name} · {m.message_sender or ''}\n{full_datetime(m.message_date)}\n"
                    f"{m.file_path or m.thumbnail_path or ''}{state}")
        if role == Qt.UserRole:
            return m
        return None

    def _icon(self, row: int, m: MediaRow) -> QIcon:
        if row in self._icons:
            return self._icons[row]
        src = m.abs_thumbnail if m.thumbnail_available else (
            m.abs_file if m.file_available and m.media_type in ("photo", "sticker") else None)
        if src is None:
            icon = QIcon(self._placeholder(m))
            self._icons[row] = icon
            return icon
        # image demandée deux fois plus grande : recadrée en carré sans être agrandie (pas de flou)
        key, pm = ThumbnailLoader.instance().request(src, self.size * 2)
        if pm is not None:
            self._icons[row] = QIcon(self._decorate(pm, m))
            return self._icons[row]
        self._keys[key] = row
        return QIcon(self._placeholder(m, loading=True))

    def _placeholder(self, m: MediaRow, loading: bool = False) -> QPixmap:
        pm = QPixmap(self.size)
        missing = not m.file_available and not loading
        pm.fill(QColor("#5c2b29") if missing else QColor("#3b4a59"))
        p = QPainter(pm)
        p.setPen(QColor("white"))
        label = "…" if loading else (media_label(m.media_type) or "") + ("\nintrouvable" if missing else "")
        p.drawText(pm.rect(), Qt.AlignCenter | Qt.TextWordWrap, label)
        p.end()
        return pm

    def _decorate(self, pm: QPixmap, m: MediaRow) -> QPixmap:
        side = min(pm.width(), pm.height())
        sq = pm.copy((pm.width() - side) // 2, (pm.height() - side) // 2, side, side).scaled(
            self.size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        badge = {"video": m.duration_raw or "▶", "video_message": "▶", "animation": "GIF"}.get(m.media_type)
        if not m.file_available and not m.not_included:
            badge = "⚠ absent"
        if badge:
            p = QPainter(sq)
            p.setRenderHint(QPainter.Antialiasing)
            w = p.fontMetrics().horizontalAdvance(badge) + 10
            p.setBrush(QColor(0, 0, 0, 160))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(4, self.size.height() - 22, w, 18, 5, 5)
            p.setPen(QColor("#ff8a80") if badge.startswith("⚠") else QColor("white"))
            p.drawText(9, self.size.height() - 9, badge)
            p.end()
        return sq

    def _on_loaded(self, key: str, pm: QPixmap) -> None:
        row = self._keys.pop(key, None)
        if row is None or row >= len(self.items):
            return
        m = self.items[row]
        self._icons[row] = QIcon(self._decorate(pm, m)) if not pm.isNull() else QIcon(self._placeholder(m))
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [Qt.DecorationRole])


class GalleryWindow(QDialog):
    go_to_message = Signal(str, int)          # conversation, seq

    def __init__(self, repo: LibraryRepository, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Galerie multimédia")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.repo = repo

        self.tabs = QTabBar()
        for label, _ in TABS:
            self.tabs.addTab(label)
        self.tabs.currentChanged.connect(self.reload)

        self.conv = QComboBox()
        self.sender = QComboBox()
        self.year = QComboBox()
        self.order = QComboBox()
        self.order.addItem("Plus récents d'abord", True)
        self.order.addItem("Plus anciens d'abord", False)
        for c in (self.conv, self.sender, self.year):
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(12)
        self.size_slider = QSlider(Qt.Horizontal, minimum=64, maximum=256, value=128, singleStep=16)
        self.size_slider.setFixedWidth(140)
        self.size_slider.setToolTip("Taille des miniatures")
        self.count = QLabel()
        self.count.setProperty("muted", True)
        self.month = QLabel()
        self.month.setProperty("muted", True)

        filters = QHBoxLayout()
        for w in (QLabel("Conversation"), self.conv, QLabel("Expéditeur"), self.sender, QLabel("Année"),
                  self.year, self.order):
            filters.addWidget(w)
        filters.addStretch(1)
        filters.addWidget(QLabel("Taille"))
        filters.addWidget(self.size_slider)

        self.model = GalleryModel(repo)
        self.grid = QListView()
        self.grid.setModel(self.model)
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        self.grid.doubleClicked.connect(lambda i: self.open_media(i.data(Qt.UserRole)))
        self.grid.verticalScrollBar().valueChanged.connect(self._update_month)
        self._apply_size()

        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.itemDoubleClicked.connect(self._table_open)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.table)

        status = QHBoxLayout()
        status.addWidget(self.count)
        status.addStretch(1)
        status.addWidget(self.month)
        hint = QLabel("Double-clic : ouvrir · clic droit : aller au message, dossier…")
        hint.setProperty("muted", True)
        status.addWidget(hint)

        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addLayout(filters)
        lay.addWidget(self.stack, 1)
        lay.addLayout(status)

        self._populate_filters()
        for c in (self.conv, self.sender, self.year, self.order):
            c.currentIndexChanged.connect(self.reload)
        self.size_slider.valueChanged.connect(self._apply_size)
        self.resize(1100, 760)
        self.reload()

    # ------------------------------------------------------------------ #

    def _populate_filters(self) -> None:
        self.conv.addItem("Toutes les conversations", None)
        for c in sorted(self.repo.list_conversations(), key=lambda c: c.name.casefold()):
            self.conv.addItem(c.name, c.id)
        self.sender.addItem("Tous", None)
        for (name,) in self.repo.conn.execute(
                "SELECT name FROM participants GROUP BY name ORDER BY name COLLATE NOCASE"):
            self.sender.addItem(name, name)
        self.year.addItem("Toutes", None)
        for y in self.repo.years():
            self.year.addItem(y, y)

    def set_conversation(self, conv_id: str | None) -> None:
        i = self.conv.findData(conv_id)
        self.conv.setCurrentIndex(max(i, 0))

    def filters(self) -> dict:
        return dict(conversation_id=self.conv.currentData(), sender=self.sender.currentData(),
                    year=self.year.currentData(), newest_first=self.order.currentData())

    def reload(self) -> None:
        tab = self.tabs.currentIndex()
        label, types = TABS[tab]
        f = self.filters()
        if tab in VISUAL_TABS:
            self.stack.setCurrentWidget(self.grid)
            self.model.load(types=types, **f)
            self.count.setText(plural(self.model.total, "élément"))
            self._update_month()
        else:
            self.stack.setCurrentWidget(self.table)
            self._fill_table(tab, types, f)

    def _fill_table(self, tab: int, types: tuple, f: dict) -> None:
        self.table.clear()
        self.table.setSortingEnabled(False)
        if TABS[tab][0] == "Liens":
            self.table.setHeaderLabels(["Lien", "Conversation", "Expéditeur", "Date"])
            rows = self.repo.all_links(f["conversation_id"], f["sender"], f["year"], None, f["newest_first"],
                                       limit=5000)
            for url, cid, cname, seq, date, sender in rows:
                it = QTreeWidgetItem([url, cname, sender or "", short_date(date)])
                it.setData(0, Qt.UserRole, ("link", url, cid, seq))
                it.setData(3, Qt.UserRole, date or "")
                it.setToolTip(0, url)
                self.table.addTopLevelItem(it)
            total = len(rows)
        else:
            self.table.setHeaderLabels(["Nom", "Type", "Taille", "Conversation", "Expéditeur", "Date", "État"])
            rows = self.repo.gallery_page(types=types, limit=5000, **f)
            for m in rows:
                name = m.title or (Path(m.file_path).name if m.file_path else media_label(m.media_type) or "")
                state = "OK" if m.file_available else ("non inclus" if m.not_included else "⚠ introuvable")
                it = QTreeWidgetItem([name, media_label(m.media_type) or m.media_type, human_size(m.file_size),
                                      m.conversation_name or "", m.message_sender or "",
                                      short_date(m.message_date), state])
                it.setData(0, Qt.UserRole, ("media", m))
                if not m.file_available:
                    it.setForeground(6, QColor("#d32f2f"))
                it.setToolTip(0, m.file_path or "")
                self.table.addTopLevelItem(it)
            total = len(rows)
        self.table.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSortingEnabled(True)
        self.count.setText(plural(total, "élément") + (" (5 000 premiers)" if total >= 5000 else ""))
        self.month.clear()

    def _apply_size(self) -> None:
        s = self.size_slider.value()
        self.grid.setIconSize(QSize(s, s))
        self.grid.setGridSize(QSize(s + 8, s + 8))
        self.model.set_icon_size(QSize(s, s))

    def _update_month(self) -> None:
        idx = self.grid.indexAt(QPoint(12, 12))      # première miniature visible
        m = idx.data(Qt.UserRole) if idx.isValid() else (self.model.items[0] if self.model.items else None)
        self.month.setText(month_label(m.message_date[:7]).capitalize() if m and m.message_date else "")

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def open_media(self, m: MediaRow | None) -> None:
        if m is None:
            return
        if m.media_type in ("photo", "sticker"):
            photos = [x for x in self.model.items if x.media_type in ("photo", "sticker")]
            idx = next((i for i, x in enumerate(photos) if x.id == m.id), 0)
            ImageViewer(photos or [m], idx, self).exec()
        elif m.media_type in ("video", "video_message", "animation") and m.file_available:
            play_video(m.abs_file, self, True)
        elif m.file_available:
            open_with_system(m.abs_file)

    def _media_menu(self, m: MediaRow, global_pos) -> None:
        menu = QMenu(self)
        menu.addAction("Ouvrir", lambda: self.open_media(m)).setEnabled(
            m.file_available or m.thumbnail_available)
        if m.conversation_id and m.message_seq is not None:
            menu.addAction("Aller au message", lambda: self.go_to_message.emit(m.conversation_id, m.message_seq))
        if m.file_available:
            menu.addAction("Afficher dans le dossier", lambda: show_in_folder(m.abs_file))
            menu.addAction("Copier le chemin", lambda: QGuiApplication.clipboard().setText(str(m.abs_file)))
        menu.exec(global_pos)

    def _grid_menu(self, pos) -> None:
        idx = self.grid.indexAt(pos)
        if idx.isValid():
            self._media_menu(idx.data(Qt.UserRole), self.grid.viewport().mapToGlobal(pos))

    def _table_menu(self, pos) -> None:
        it = self.table.itemAt(pos)
        if not it:
            return
        data = it.data(0, Qt.UserRole)
        if data[0] == "media":
            self._media_menu(data[1], self.table.viewport().mapToGlobal(pos))
        else:
            _, url, cid, seq = data
            menu = QMenu(self)
            menu.addAction("Ouvrir le lien", lambda: open_url(url))
            menu.addAction("Copier le lien", lambda: QGuiApplication.clipboard().setText(url))
            menu.addAction("Aller au message", lambda: self.go_to_message.emit(cid, seq))
            menu.exec(self.table.viewport().mapToGlobal(pos))

    def _table_open(self, it: QTreeWidgetItem) -> None:
        data = it.data(0, Qt.UserRole)
        if data[0] == "media":
            self.open_media(data[1])
        else:
            open_url(data[1])
