"""Galerie multimédia complète : photos, vidéos, GIF, fichiers, audio et liens de toute la bibliothèque."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPixmap
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QListView, QMenu,
    QPushButton, QSizePolicy, QSlider,
    QStackedWidget, QTabBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from app import design, icons
from database.models import MediaRow
from database.repositories import LibraryRepository, media_label
from services.media_service import ThumbnailLoader, human_size, open_url, open_with_system, show_in_folder

from .components import dialog_header
from .export_dialog import copy_to_folder
from .formatting import full_datetime, month_label, plural, short_date
from .media_gallery import ThumbnailDelegate, thumb_decorate, thumb_placeholder
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
TAB_ICONS = ["image", "video", "film", "file", "music", "link"]
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
                                             args.get("year"), args.get("archive_id"), args.get("unique", False))
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
            icon = QIcon(thumb_placeholder(m, self.size))
            self._icons[row] = icon
            return icon
        # image demandée deux fois plus grande : recadrée en carré sans être agrandie (pas de flou)
        key, pm = ThumbnailLoader.instance().request(src, self.size * 2)
        if pm is not None:
            self._icons[row] = QIcon(thumb_decorate(pm, m, self.size))
            return self._icons[row]
        self._keys[key] = row
        return QIcon(thumb_placeholder(m, self.size, loading=True))

    def _on_loaded(self, key: str, pm: QPixmap) -> None:
        row = self._keys.pop(key, None)
        if row is None or row >= len(self.items):
            return
        m = self.items[row]
        self._icons[row] = QIcon(thumb_decorate(pm, m, self.size) if not pm.isNull()
                                 else thumb_placeholder(m, self.size))
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [Qt.DecorationRole])


class GalleryWindow(QDialog):
    go_to_message = Signal(str, int)          # conversation, seq

    def __init__(self, repo: LibraryRepository, parent=None, settings=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Galerie multimédia")
        self.settings = settings
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.repo = repo

        self.tabs = QTabBar()
        self.tabs.setProperty("variant", "segmented")
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setElideMode(Qt.ElideNone)
        self.tabs.setExpanding(False)
        self.tabs.setIconSize(QSize(16, 16))
        for (label, _), icon_name in zip(TABS, TAB_ICONS):
            self.tabs.addTab(label)
        self._tab_icons()
        self.tabs.currentChanged.connect(self.reload)

        self.conv = QComboBox()
        self.sender = QComboBox()
        self.year = QComboBox()
        self.order = QComboBox()
        self.order.addItem("Plus récents d'abord", True)
        self.order.addItem("Plus anciens d'abord", False)
        for c, n in ((self.conv, 18), (self.sender, 12), (self.year, 8)):
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(n)
        self.order.setToolTip("Ordre d'affichage")
        self.size_slider = QSlider(Qt.Horizontal, minimum=64, maximum=256, value=144, singleStep=16)
        self.size_slider.setFixedWidth(120)
        self.size_slider.setToolTip("Taille des miniatures")
        self.size_slider.setAccessibleName("Taille des miniatures")
        self.count = QLabel()
        self.count.setProperty("role", "caption")
        self.month = QLabel()
        self.month.setProperty("role", "caption")

        bar = QFrame(objectName="Toolbar")
        filters = QHBoxLayout(bar)
        filters.setContentsMargins(12, 8, 12, 8)
        filters.setSpacing(8)
        self._filter_icons: list[tuple[QLabel, str]] = []
        for icon_name, tip, combo in (("chat", "Conversation", self.conv), ("user", "Expéditeur", self.sender),
                                      ("calendar", "Année", self.year), ("sort", "Ordre", self.order)):
            ic = QLabel(toolTip=tip)
            self._filter_icons.append((ic, icon_name))
            combo.setToolTip(tip)
            combo.setAccessibleName(tip)
            filters.addWidget(ic)
            filters.addWidget(combo)
            filters.addSpacing(6)
        self.unique_check = QCheckBox("Masquer les fichiers identiques")
        self.unique_check.setToolTip("N'affiche qu'une occurrence des fichiers strictement identiques (SHA-256). "
                                     "Les empreintes se calculent via Fichier › Fichiers identiques.")
        filters.addWidget(self.unique_check)
        filters.addStretch(1)
        self.size_icon = QLabel(toolTip="Taille des miniatures")
        filters.addWidget(self.size_icon)
        filters.addWidget(self.size_slider)

        self.model = GalleryModel(repo)
        self.grid = QListView()
        self.grid.setModel(self.model)
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setSpacing(0)
        self.grid.setAccessibleName("Grille des médias")
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setItemDelegate(ThumbnailDelegate(self.grid))
        self.grid.setMouseTracking(True)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        self.grid.doubleClicked.connect(lambda i: self.open_media(i.data(Qt.UserRole)))
        self.grid.verticalScrollBar().valueChanged.connect(self._update_month)
        self._apply_size()

        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(False)
        self.table.setIconSize(QSize(18, 18))
        self.table.setSortingEnabled(True)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.itemDoubleClicked.connect(self._table_open)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.table)

        self.selection = QLabel()
        self.selection.setStyleSheet("font-weight: 600;")
        self.copy_sel = QPushButton("Copier la sélection…")
        self.copy_sel.setProperty("variant", "primary")
        icons.bind(self.copy_sel, "copy", "surface", 16, "surface", "surface")
        self.copy_sel.setToolTip("Copier les éléments sélectionnés vers un dossier (Ctrl+Maj+C)")
        self.copy_sel.clicked.connect(self.copy_selection)
        self.copy_all_btn = QPushButton("Tout copier…")
        icons.bind(self.copy_all_btn, "folder", "muted", 16)
        self.copy_all_btn.setToolTip("Copier vers un dossier tous les éléments de l'onglet, filtres compris")
        self.copy_all_btn.clicked.connect(self.copy_all)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self.copy_selection)

        action_bar = QFrame(objectName="ActionBar")
        status = QHBoxLayout(action_bar)
        status.setContentsMargins(20, 10, 20, 10)
        status.setSpacing(10)
        status.addWidget(self.count)
        status.addWidget(self.selection)
        status.addSpacing(10)
        status.addWidget(self.month)
        status.addStretch(1)
        hint = QLabel("Ctrl/Maj + clic : sélection multiple · double-clic : ouvrir")
        hint.setToolTip("Clic droit : aller au message, ouvrir le dossier, copier vers un dossier…")
        hint.setProperty("role", "caption")
        hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        hint.setMinimumWidth(40)
        status.addWidget(hint, 1)
        status.addWidget(self.copy_all_btn)
        status.addWidget(self.copy_sel)

        self.header_title = dialog_header("Galerie multimédia", "Photos, vidéos, fichiers et liens de "
                                          "toute la bibliothèque", "image")
        top = QVBoxLayout()
        top.setContentsMargins(20, 18, 20, 10)
        top.setSpacing(12)
        top.addWidget(self.header_title)
        tabs_row = QHBoxLayout()
        tabs_row.addWidget(self.tabs)
        tabs_row.addStretch(1)
        top.addLayout(tabs_row)
        top.addWidget(bar)
        content = QFrame()
        content.setProperty("card", True)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(8, 8, 2, 8)
        cl.addWidget(self.stack)
        body = QVBoxLayout()
        body.setContentsMargins(20, 0, 20, 14)
        body.addWidget(content)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addLayout(body, 1)
        lay.addWidget(action_bar)
        self.retheme()

        self.grid.selectionModel().selectionChanged.connect(self._update_selection)
        self.table.itemSelectionChanged.connect(self._update_selection)
        self._populate_filters()
        for c in (self.conv, self.sender, self.year, self.order):
            c.currentIndexChanged.connect(self.reload)
        self.unique_check.toggled.connect(self.reload)
        self.personal = None          # PersonalData, fourni par la fenêtre principale
        self.size_slider.valueChanged.connect(self._apply_size)
        self.resize(1180, 800)
        self.setMinimumSize(760, 520)
        self.reload()

    # ------------------------------------------------------------------ #

    def _tab_icons(self) -> None:
        t = design.current()
        for i, name in enumerate(TAB_ICONS):
            self.tabs.setTabIcon(i, icons.icon(name, t.muted, 16, t.text, t.accent))

    def retheme(self, theme=None) -> None:
        t = design.current()
        self._tab_icons()
        for ic, name in self._filter_icons:
            ic.setPixmap(icons.pixmap(name, t.muted, 16))
        self.size_icon.setPixmap(icons.pixmap("grid", t.muted, 16))
        self.model.set_icon_size(self.model.size)
        if self.stack.currentWidget() is self.table:
            self.reload()

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
                    year=self.year.currentData(), newest_first=self.order.currentData(),
                    unique=self.unique_check.isChecked())

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
        self.copy_all_btn.setEnabled(TABS[tab][0] != "Liens")
        self._update_selection()

    def _fill_table(self, tab: int, types: tuple, f: dict) -> None:
        self.table.clear()
        self.table.setSortingEnabled(False)
        if TABS[tab][0] == "Liens":
            self.table.setHeaderLabels(["Lien", "Conversation", "Expéditeur", "Date"])
            rows = self.repo.all_links(f["conversation_id"], f["sender"], f["year"], None, f["newest_first"],
                                       limit=5000)
            self.unique_check.setEnabled(False)
            for url, cid, cname, seq, date, sender in rows:
                it = QTreeWidgetItem([url, cname, sender or "", short_date(date)])
                it.setIcon(0, icons.icon("link", design.current().accent, 18))
                it.setData(0, Qt.UserRole, ("link", url, cid, seq))
                it.setData(3, Qt.UserRole, date or "")
                it.setToolTip(0, url)
                self.table.addTopLevelItem(it)
            total = len(rows)
        else:
            self.table.setHeaderLabels(["Nom", "Type", "Taille", "Conversation", "Expéditeur", "Date", "État"])
            self.unique_check.setEnabled(True)
            rows = self.repo.gallery_page(types=types, limit=5000, **f)
            for m in rows:
                name = m.title or (Path(m.file_path).name if m.file_path else media_label(m.media_type) or "")
                state = "OK" if m.file_available else ("Non inclus" if m.not_included else "Introuvable")
                it = QTreeWidgetItem([name, media_label(m.media_type) or m.media_type, human_size(m.file_size),
                                      m.conversation_name or "", m.message_sender or "",
                                      short_date(m.message_date), state])
                it.setData(0, Qt.UserRole, ("media", m))
                th = design.current()
                missing = not m.file_available and not m.not_included
                it.setIcon(0, icons.icon("alert" if missing else icons.MEDIA_ICONS.get(m.media_type, "file"),
                                         th.danger if missing else th.accent, 18))
                if not m.file_available:
                    it.setForeground(6, QColor(th.danger if missing else th.muted))
                else:
                    it.setForeground(6, QColor(th.success))
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
        self.grid.setGridSize(QSize(s + 12, s + 12))
        self.model.set_icon_size(QSize(s, s))

    def _update_month(self) -> None:
        idx = self.grid.indexAt(QPoint(12, 12))      # première miniature visible
        m = idx.data(Qt.UserRole) if idx.isValid() else (self.model.items[0] if self.model.items else None)
        self.month.setText(month_label(m.message_date[:7]).capitalize() if m and m.message_date else "")

    # ------------------------------------------------------------------ #
    # Sélection et copie vers un dossier
    # ------------------------------------------------------------------ #

    def selected_medias(self) -> list[MediaRow]:
        if self.stack.currentWidget() is self.grid:
            rows = sorted(i.row() for i in self.grid.selectionModel().selectedIndexes())
            return [self.model.items[r] for r in rows if r < len(self.model.items)]
        out = []
        for it in self.table.selectedItems():
            data = it.data(0, Qt.UserRole)
            if data and data[0] == "media":
                out.append(data[1])
        return out

    def _update_selection(self) -> None:
        n = len(self.selected_medias())
        self.selection.setText(f"· {plural(n, 'sélectionné')}" if n else "")
        self.copy_sel.setEnabled(n > 0)

    def copy_selection(self) -> None:
        copy_to_folder(self.selected_medias(), self, self.settings)

    def all_filtered(self) -> list[MediaRow]:
        types = TABS[self.tabs.currentIndex()][1]
        if not types:
            return []
        f = self.filters()
        total = self.repo.gallery_count(types, f["conversation_id"], f["sender"], f["year"], None, f["unique"])
        return self.repo.gallery_page(types=types, offset=0, limit=max(total, 1), **f)

    def copy_all(self) -> None:
        copy_to_folder(self.all_filtered(), self, self.settings)

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
        self._personal_entries(menu, m)
        menu.addSeparator()
        selected = self.selected_medias()
        if len(selected) > 1:
            menu.addAction(f"Copier les {len(selected)} éléments sélectionnés vers un dossier…", self.copy_selection)
        else:
            menu.addAction("Copier vers un dossier…", lambda: copy_to_folder([m], self, self.settings)).setEnabled(
                m.file_available)
        menu.exec(global_pos)

    def _personal_entries(self, menu: QMenu, m: MediaRow) -> None:
        """Occurrences du même fichier, favoris et collections (données personnelles)."""
        from services import media_dedup
        occ = media_dedup.occurrences(self.repo.db, self.repo, m.id)
        others = [o for o in occ if o.media_id != m.id]
        if not occ:
            menu.addAction("Occurrences : empreinte non calculée").setEnabled(False)
        elif others:
            sub = menu.addMenu(icons.icon("copy"), f"Autres occurrences de ce fichier ({len(others)})")
            for o in others:
                sub.addAction(f"{o.conversation_name} · {short_date(o.date_local)} · {o.sender or ''}",
                              lambda o=o: self.go_to_message.emit(o.conversation_id, o.seq))
        if self.personal is None or m.message_id is None or not m.conversation_id:
            return
        menu.addSeparator()
        fav = self.personal.is_favorite(m.conversation_id, m.message_id)
        menu.addAction(icons.icon("star"), "Retirer le message des favoris" if fav else "Ajouter le message aux favoris",
                       lambda: self.personal.set_favorite(m.conversation_id, m.message_id, not fav))
        sub = menu.addMenu(icons.icon("collection"), "Ajouter à une collection")
        for c in self.personal.collections():
            sub.addAction(c.name, lambda cid=c.id: self.personal.add_to_collection(
                cid, m.conversation_id, m.message_id, m.ordinal))
        sub.addSeparator()
        sub.addAction(icons.icon("plus"), "Nouvelle collection…", lambda: self._new_collection_with(m))

    def _new_collection_with(self, m: MediaRow) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        name, ok = QInputDialog.getText(self, "Nouvelle collection", "Nom de la collection :")
        if ok and name.strip():
            try:
                cid = self.personal.create_collection(name)
            except ValueError as exc:
                QMessageBox.warning(self, "Nouvelle collection", str(exc))
                return
            self.personal.add_to_collection(cid, m.conversation_id, m.message_id, m.ordinal)

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
