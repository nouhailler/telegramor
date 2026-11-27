"""Zone droite : informations, participants, galerie de médias, fichiers et liens."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
    QTabWidget, QVBoxLayout, QWidget,
)

from app import design, icons
from app.design import name_color, sender_color
from database.models import ConversationSummary, MediaRow
from database.repositories import FILE_MEDIA, VISUAL_MEDIA, LibraryRepository, media_label
from services.media_service import open_url, open_with_system

from .export_dialog import copy_to_folder
from .formatting import full_datetime, period, plural, short_date
from .media_gallery import MediaGallery
from .timeline import Timeline


class InformationPanel(QWidget):
    jump_requested = Signal(int)              # seq
    day_requested = Signal(str)               # AAAA-MM-JJ
    open_media = Signal(MediaRow)

    def __init__(self, repo: LibraryRepository, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("InfoPanel")
        self.repo = repo
        self.conv: ConversationSummary | None = None
        self.settings = None                  # AppSettings, fourni par la fenêtre principale
        self.setMinimumWidth(design.INFO_PANEL_MIN)

        self.avatar = QLabel(alignment=Qt.AlignCenter)
        self.avatar.setFixedSize(68, 68)
        self.name = QLabel(alignment=Qt.AlignCenter, objectName="InfoName")
        self.name.setWordWrap(True)
        self.headline = QLabel(alignment=Qt.AlignCenter)
        self.headline.setProperty("role", "caption")

        # Chiffres clés en tuiles
        self.f_messages = QLabel(objectName="StatValue")
        self.f_media = QLabel(objectName="StatValue")
        self.f_period = QLabel(objectName="StatValue", wordWrap=True)
        self.f_archives = QLabel(objectName="StatValue", wordWrap=True)
        self.tiles = QGridLayout()
        self.tiles.setSpacing(8)
        self._tile_icons: list[tuple[QLabel, str]] = []
        for i, (label, w, icon_name, span) in enumerate((
                ("Messages", self.f_messages, "chat", 1), ("Médias", self.f_media, "image", 1),
                ("Période", self.f_period, "calendar", 2), ("Archive(s)", self.f_archives, "archive", 2))):
            tile = QFrame(objectName="StatTile")
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(10, 8, 10, 8)
            tl.setSpacing(2)
            head = QHBoxLayout()
            head.setSpacing(6)
            ic = QLabel()
            self._tile_icons.append((ic, icon_name))
            lab = QLabel(label, objectName="StatLabel")
            head.addWidget(ic)
            head.addWidget(lab, 1)
            tl.addLayout(head)
            tl.addWidget(w)
            row = 0 if i < 2 else i - 1
            col = i if i < 2 else 0
            self.tiles.addWidget(tile, row, col, 1, span)

        self.participants = QListWidget()
        self.participants.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.participants.setSelectionMode(QAbstractItemView.NoSelection)
        self.participants.setFocusPolicy(Qt.NoFocus)

        self.gallery = MediaGallery()
        self.gallery.media_selected.connect(lambda m: m.message_seq is not None and self.jump_requested.emit(m.message_seq))
        self.gallery.media_activated.connect(self.open_media)
        self.gallery.copy_requested.connect(lambda ms: copy_to_folder(ms, self, self.settings))
        self.files = QListWidget()
        self.files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._files_menu)
        self.files.setIconSize(QSize(18, 18))
        self.files.itemClicked.connect(self._jump_item)
        self.files.itemDoubleClicked.connect(self._open_file_item)
        self.links = QListWidget()
        self.links.setIconSize(QSize(18, 18))
        self.links.itemClicked.connect(self._jump_item)
        self.links.itemDoubleClicked.connect(lambda it: open_url(it.data(Qt.UserRole + 1)))
        for lst in (self.files, self.links):
            lst.setWordWrap(False)
            lst.setTextElideMode(Qt.ElideMiddle)

        self.tabs = QTabWidget()
        self.tabs.tabBar().setProperty("variant", "segmented")
        self.tabs.tabBar().setExpanding(True)
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.gallery, "Médias")
        self.tabs.addTab(self.files, "Fichiers")
        self.tabs.addTab(self.links, "Liens")
        self.timeline = Timeline(design.current().accent)
        self.timeline.day_selected.connect(self.day_requested)
        self.tabs.addTab(self.timeline, "Dates")

        part_title = QLabel("PARTICIPANTS")
        part_title.setProperty("role", "overline")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 18, 14, 10)
        lay.setSpacing(8)
        lay.addWidget(self.avatar, 0, Qt.AlignHCenter)
        lay.addWidget(self.name)
        lay.addWidget(self.headline)
        lay.addSpacing(4)
        lay.addLayout(self.tiles)
        lay.addSpacing(6)
        lay.addWidget(part_title)
        lay.addWidget(self.participants)
        lay.addSpacing(4)
        lay.addWidget(self.tabs, 1)
        self.retheme()

    def retheme(self) -> None:
        t = design.current()
        for ic, name in self._tile_icons:
            ic.setPixmap(icons.pixmap(name, t.muted, 14))
        self.timeline.set_accent(t.accent)
        if self.conv is not None:
            self.set_conversation(self.conv)

    def set_conversation(self, conv: ConversationSummary | None) -> None:
        self.conv = conv
        if conv is None:
            for w in (self.name, self.f_messages, self.f_period, self.f_media, self.f_archives):
                w.clear()
            self.participants.clear()
            self.gallery.set_items([])
            self.files.clear()
            self.links.clear()
            self.timeline.clear()
            return
        color = QColor(sender_color(None, conv.name))
        self.avatar.setText((conv.name[:1] or "?").upper())
        self.avatar.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {color.lighter(112).name()}, "
            f"stop:1 {color.darker(106).name()}); color: white; border-radius: 34px; font-size: 24px; "
            f"font-weight: bold;")
        self.name.setText(conv.name)
        self.f_messages.setText(f"{conv.message_count:,}".replace(",", " "))
        self.f_period.setText(period(conv.first_date, conv.last_date))
        self.f_archives.setText(", ".join(conv.archives))

        self.participants.clear()
        parts = self.repo.participants(conv.id)
        top = max((p.message_count for p in parts), default=1)
        t = design.current()
        row_h = 34
        for p in parts:
            it = QListWidgetItem()
            it.setToolTip(f"Premier message : {short_date(p.first_date)}\nDernier message : {short_date(p.last_date)}")
            self.participants.addItem(it)
            it.setSizeHint(QSize(10, row_h))
            self.participants.setItemWidget(it, self._participant_row(p, top, t))
        rows = min(self.participants.count(), 5)
        self.participants.setFixedHeight(rows * row_h + 4)
        self.headline.setText(f"{plural(len(parts), 'participant')} · {plural(conv.message_count, 'message')}")

        visual = self.repo.medias(conv.id, VISUAL_MEDIA)
        self.gallery.set_items(visual)
        files = self.repo.medias(conv.id, FILE_MEDIA)
        missing = sum(not m.file_available for m in visual + files if m.file_path)
        self.f_media.setText(f"{len(visual) + len(files)}"
                             + (f" <span style='color:{t.danger}; font-weight:normal; font-size:9pt'>· "
                                f"{missing} introuvable(s)</span>" if missing else ""))
        self.f_media.setToolTip(f"{len(visual)} visuel(s), {len(files)} fichier(s)")
        self.files.clear()
        for m in files:
            name = m.title or (m.file_path.rsplit("/", 1)[-1] if m.file_path else media_label(m.media_type))
            state = "" if m.file_available else ("  (non inclus)" if m.not_included else "  ⚠ introuvable")
            it = QListWidgetItem(f"{name}{state}")
            missing_file = bool(m.file_path and not m.file_available and not m.not_included)
            it.setIcon(icons.icon("alert" if missing_file else icons.MEDIA_ICONS.get(m.media_type, "file"),
                                  t.danger if missing_file else t.accent, 18))
            if missing_file:
                it.setForeground(QColor(t.danger))
            it.setToolTip(f"{m.message_sender or ''} · {full_datetime(m.message_date)}\n{m.file_path or ''}\n"
                          "Clic : aller au message · Double-clic : ouvrir")
            it.setData(Qt.UserRole, m.message_seq)
            it.setData(Qt.UserRole + 1, m)
            self.files.addItem(it)
        self.links.clear()
        for url, seq, date, sender in self.repo.links(conv.id):
            it = QListWidgetItem(url)
            it.setIcon(icons.icon("link", t.accent, 18))
            it.setToolTip(f"{sender or ''} · {full_datetime(date)}\nClic : aller au message · Double-clic : ouvrir")
            it.setData(Qt.UserRole, seq)
            it.setData(Qt.UserRole + 1, url)
            self.links.addItem(it)
        # libellés courts (le panneau est étroit) ; les nombres sont en info-bulle
        self.tabs.setTabToolTip(0, plural(len(visual), "média visuel", "médias visuels"))
        self.tabs.setTabToolTip(1, plural(len(files), "fichier"))
        self.tabs.setTabToolTip(2, plural(self.links.count(), "lien"))
        self.tabs.setTabToolTip(3, "Années, mois et jours ; cliquer pour y aller")
        self.timeline.set_days(self.repo.days_with_messages(conv.id))

    @staticmethod
    def _participant_row(p, top: int, t) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 0, 4, 0)
        h.setSpacing(8)
        dot = QLabel((p.name[:1] or "?").upper())
        dot.setFixedSize(24, 24)
        dot.setAlignment(Qt.AlignCenter)
        dot.setStyleSheet(f"background: {sender_color(p.userpic_class, p.name)}; color: white; border-radius: 12px;"
                          f" font-weight: bold; font-size: 8pt;")
        name = QLabel(f"<b>{escape(p.name)}</b>")
        name.setStyleSheet(f"color: {t.text};")
        count = QLabel(f"{p.message_count:,}".replace(",", "\u202f"))
        count.setProperty("role", "caption")
        count.setToolTip(plural(p.message_count, "message"))
        bar = QFrame()
        bar.setFixedSize(max(4, int(46 * p.message_count / max(top, 1))), 4)
        bar.setStyleSheet(f"background: {name_color(p.userpic_class, p.name, t)}; border-radius: 2px;")
        h.addWidget(dot)
        h.addWidget(name, 1)
        h.addWidget(bar)
        h.addWidget(count)
        return w

    def _files_menu(self, pos) -> None:
        selected = [it.data(Qt.UserRole + 1) for it in self.files.selectedItems()]
        every = [self.files.item(i).data(Qt.UserRole + 1) for i in range(self.files.count())]
        menu = QMenu(self)
        n = len(selected)
        label = "Copier vers un dossier…" if n <= 1 else f"Copier les {n} fichiers sélectionnés vers un dossier…"
        menu.addAction(label, lambda: copy_to_folder(selected, self, self.settings)).setEnabled(n > 0)
        menu.addAction("Copier tous les fichiers de la conversation…",
                       lambda: copy_to_folder(every, self, self.settings)).setEnabled(bool(every))
        menu.exec(self.files.viewport().mapToGlobal(pos))

    def _jump_item(self, it: QListWidgetItem) -> None:
        if QApplication.keyboardModifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            return
        seq = it.data(Qt.UserRole)
        if seq is not None:
            self.jump_requested.emit(int(seq))

    def _open_file_item(self, it: QListWidgetItem) -> None:
        m: MediaRow = it.data(Qt.UserRole + 1)
        if m and m.file_available:
            open_with_system(m.abs_file)
