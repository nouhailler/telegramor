"""Zone droite : informations, participants, galerie de médias, fichiers et liens."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout, QLabel, QListWidget, QListWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from app.styles import sender_color
from database.models import ConversationSummary, MediaRow
from database.repositories import FILE_MEDIA, VISUAL_MEDIA, LibraryRepository, media_label
from services.media_service import open_url, open_with_system

from .formatting import full_datetime, period, plural, short_date
from .media_gallery import MediaGallery
from .timeline import Timeline


class InformationPanel(QWidget):
    jump_requested = Signal(int)              # seq
    day_requested = Signal(str)               # AAAA-MM-JJ
    open_media = Signal(MediaRow)

    def __init__(self, repo: LibraryRepository, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.repo = repo
        self.conv: ConversationSummary | None = None
        self.setMinimumWidth(300)

        self.avatar = QLabel(alignment=Qt.AlignCenter)
        self.avatar.setFixedSize(72, 72)
        self.name = QLabel(alignment=Qt.AlignCenter, objectName="ChatTitle")
        self.name.setWordWrap(True)

        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight)
        self.f_messages = QLabel()
        self.f_period = QLabel(wordWrap=True)
        self.f_media = QLabel()
        self.f_archives = QLabel(wordWrap=True)
        for label, w in (("Messages", self.f_messages), ("Période", self.f_period),
                         ("Médias", self.f_media), ("Archive(s)", self.f_archives)):
            lab = QLabel(label)
            lab.setProperty("muted", True)
            self.form.addRow(lab, w)

        self.participants = QListWidget()
        self.participants.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.gallery = MediaGallery()
        self.gallery.media_selected.connect(lambda m: m.message_seq is not None and self.jump_requested.emit(m.message_seq))
        self.gallery.media_activated.connect(self.open_media)
        self.files = QListWidget()
        self.files.itemClicked.connect(self._jump_item)
        self.files.itemDoubleClicked.connect(self._open_file_item)
        self.links = QListWidget()
        self.links.itemClicked.connect(self._jump_item)
        self.links.itemDoubleClicked.connect(lambda it: open_url(it.data(Qt.UserRole + 1)))

        self.tabs = QTabWidget()
        self.tabs.addTab(self.gallery, "Médias")
        self.tabs.addTab(self.files, "Fichiers")
        self.tabs.addTab(self.links, "Liens")
        self.timeline = Timeline("#3390ec")
        self.timeline.day_selected.connect(self.day_requested)
        self.tabs.addTab(self.timeline, "Dates")

        part_title = QLabel("<b>Participants</b>")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 12, 10, 6)
        lay.addWidget(self.avatar, 0, Qt.AlignHCenter)
        lay.addWidget(self.name)
        lay.addLayout(self.form)
        lay.addWidget(part_title)
        lay.addWidget(self.participants)
        lay.addWidget(self.tabs, 1)

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
        color = sender_color(None, conv.name)
        self.avatar.setText((conv.name[:1] or "?").upper())
        self.avatar.setStyleSheet(f"background:{color}; color:white; border-radius:36px; font-size:26px; font-weight:bold;")
        self.name.setText(conv.name)
        self.f_messages.setText(f"{conv.message_count:,}".replace(",", " "))
        self.f_period.setText(period(conv.first_date, conv.last_date))
        self.f_archives.setText(", ".join(conv.archives))

        self.participants.clear()
        for p in self.repo.participants(conv.id):
            it = QListWidgetItem()
            it.setToolTip(f"Premier message : {short_date(p.first_date)}\nDernier message : {short_date(p.last_date)}")
            self.participants.addItem(it)
            lbl = QLabel(f"<span style='color:{sender_color(p.userpic_class, p.name)}'>●</span>&nbsp; "
                         f"<b>{escape(p.name)}</b> <span style='color:gray'>— {plural(p.message_count, 'message')}</span>")
            lbl.setContentsMargins(4, 2, 4, 2)
            it.setSizeHint(lbl.sizeHint())
            self.participants.setItemWidget(it, lbl)

        rows = min(self.participants.count(), 6)
        row_h = self.participants.sizeHintForRow(0) if rows else 0
        self.participants.setFixedHeight(rows * row_h + 6)

        visual = self.repo.medias(conv.id, VISUAL_MEDIA)
        self.gallery.set_items(visual)
        files = self.repo.medias(conv.id, FILE_MEDIA)
        missing = sum(not m.file_available for m in visual + files if m.file_path)
        self.f_media.setText(f"{len(visual)} visuel(s), {len(files)} fichier(s)"
                             + (f" — {missing} introuvable(s)" if missing else ""))
        self.files.clear()
        for m in files:
            name = m.title or (m.file_path.rsplit("/", 1)[-1] if m.file_path else media_label(m.media_type))
            state = "" if m.file_available else ("  (non inclus)" if m.not_included else "  ⚠ introuvable")
            it = QListWidgetItem(f"{media_label(m.media_type)} — {name}{state}")
            it.setToolTip(f"{m.message_sender or ''} · {full_datetime(m.message_date)}\n{m.file_path or ''}\n"
                          "Clic : aller au message · Double-clic : ouvrir")
            it.setData(Qt.UserRole, m.message_seq)
            it.setData(Qt.UserRole + 1, m)
            self.files.addItem(it)
        self.links.clear()
        for url, seq, date, sender in self.repo.links(conv.id):
            it = QListWidgetItem(url)
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

    def _jump_item(self, it: QListWidgetItem) -> None:
        seq = it.data(Qt.UserRole)
        if seq is not None:
            self.jump_requested.emit(int(seq))

    def _open_file_item(self, it: QListWidgetItem) -> None:
        m: MediaRow = it.data(Qt.UserRole + 1)
        if m and m.file_available:
            open_with_system(m.abs_file)
