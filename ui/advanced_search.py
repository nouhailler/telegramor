"""Filtres combinables de la recherche avancée."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDateEdit, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QWidget,
)

from app import icons

from database.search_engine import (
    CONTENT_LABELS, MODE_EXACT, MODE_PREFIX, MODE_WORDS, SORT_NEWEST, SORT_OLDEST, SORT_RELEVANCE,
    SearchQuery,
)

ANY = "__any__"


def _combo(items: list[tuple[str, object]]) -> QComboBox:
    c = QComboBox()
    for label, data in items:
        c.addItem(label, data)
    return c


class OptionalDate(QWidget):
    """Case à cocher + date (filtre inactif tant que la case est décochée)."""

    changed = Signal()

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        self.check = QCheckBox(label)
        self.check.setMinimumWidth(84)
        self.edit = QDateEdit(calendarPopup=True)
        self.edit.setDisplayFormat("dd/MM/yyyy")
        self.edit.setDate(QDate.currentDate())
        self.edit.setEnabled(False)
        self.check.toggled.connect(self.edit.setEnabled)
        self.check.toggled.connect(self.changed)
        self.edit.dateChanged.connect(lambda *_: self.check.isChecked() and self.changed.emit())
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.check)
        lay.addWidget(self.edit, 1)

    def value(self) -> str | None:
        return self.edit.date().toString("yyyy-MM-dd") if self.check.isChecked() else None

    def set_value(self, day: str | None) -> None:
        self.blockSignals(True)
        if day:
            self.edit.setDate(QDate.fromString(day[:10], "yyyy-MM-dd"))
        self.check.setChecked(bool(day))
        self.blockSignals(False)

    def reset(self, default: QDate | None = None) -> None:
        self.check.setChecked(False)
        if default is not None and default.isValid():
            self.edit.setDate(default)


class SearchFilters(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.mode = _combo([("Début de mot (vac → vacances)", MODE_PREFIX), ("Mots entiers", MODE_WORDS),
                            ("Expression exacte", MODE_EXACT)])
        self.conversation = _combo([("Toutes les conversations", ANY)])
        self.archive = _combo([("Toutes les archives", ANY)])
        self.sender = QComboBox()
        self.sender.setEditable(True)
        self.sender.lineEdit().setPlaceholderText("Tous les expéditeurs")
        self.sender.setInsertPolicy(QComboBox.NoInsert)
        self.date_from = OptionalDate("Depuis le")
        self.date_to = OptionalDate("Jusqu'au")
        self.content = _combo([("Tous les types", ANY)] + [(label, key) for key, label in CONTENT_LABELS.items()])
        self.media = _combo([("Indifférent", ANY), ("Avec pièce jointe", True), ("Sans pièce jointe", False)])
        self.link = _combo([("Indifférent", ANY), ("Avec lien", True), ("Sans lien", False)])
        self.reply = _combo([("Indifférent", ANY), ("Réponses uniquement", True), ("Hors réponses", False)])
        self.reply.setToolTip("Messages qui citent (répondent à) un autre message")
        self.filename = QLineEdit(placeholderText="ex. facture, .pdf, IMG_2034")
        self.filename.setClearButtonEnabled(True)
        self.sort = _combo([("Pertinence", SORT_RELEVANCE), ("Plus récents d'abord", SORT_NEWEST),
                            ("Plus anciens d'abord", SORT_OLDEST)])
        reset = QPushButton("Réinitialiser les filtres")
        reset.setProperty("variant", "ghost")
        icons.bind(reset, "refresh", "muted", 16)
        reset.clicked.connect(self.reset)

        # Libellés au-dessus des champs : lisible dans un panneau étroit
        form = QVBoxLayout(self)
        form.setContentsMargins(14, 4, 14, 8)
        form.setSpacing(4)

        def row(label: str, *widgets) -> None:
            cap = QLabel(label.upper())
            cap.setProperty("role", "overline")
            form.addSpacing(6)
            form.addWidget(cap)
            for w in widgets:
                form.addWidget(w)

        row("Recherche", self.mode)
        row("Conversation", self.conversation)
        row("Archive", self.archive)
        row("Expéditeur", self.sender)
        row("Période", self.date_from, self.date_to)
        row("Type de contenu", self.content)
        two = QHBoxLayout()
        two.setSpacing(8)
        for label, w in (("Pièce jointe", self.media), ("Lien", self.link)):
            col = QVBoxLayout()
            col.setSpacing(4)
            cap = QLabel(label.upper())
            cap.setProperty("role", "overline")
            col.addWidget(cap)
            col.addWidget(w)
            two.addLayout(col, 1)
        form.addSpacing(6)
        form.addLayout(two)
        row("Réponse à un message", self.reply)
        row("Nom de fichier", self.filename)
        row("Tri", self.sort)
        form.addSpacing(8)
        form.addWidget(reset, 0, Qt.AlignLeft)

        for c in (self.mode, self.conversation, self.archive, self.content, self.media, self.link, self.sort,
                  self.sender, self.reply):
            # largeur limitée : les longs noms de conversation ne doivent pas élargir le panneau
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(8)
        for c in (self.media, self.link):          # côte à côte : plus étroites
            c.setMinimumContentsLength(3)
        for c in (self.mode, self.conversation, self.archive, self.content, self.media, self.link, self.sort,
                  self.reply):
            c.currentIndexChanged.connect(self.changed)
        self.sender.currentTextChanged.connect(self.changed)
        self.date_from.changed.connect(self.changed)
        self.date_to.changed.connect(self.changed)
        self.filename.textChanged.connect(self.changed)

    # ------------------------------------------------------------------ #

    def populate(self, conversations: list[tuple[str, str]], archives: list[tuple[int, str]],
                 senders: list[str], first_day: str | None = None, last_day: str | None = None) -> None:
        """Renseigne les listes déroulantes en conservant la sélection courante."""
        self.blockSignals(True)
        for combo, items in ((self.conversation, conversations), (self.archive, archives)):
            current = combo.currentData()
            while combo.count() > 1:
                combo.removeItem(1)
            for key, label in items:
                combo.addItem(label, key)
            i = combo.findData(current)
            combo.setCurrentIndex(max(i, 0))
        text = self.sender.currentText()
        self.sender.clear()
        self.sender.addItems([""] + senders)
        self.sender.setCurrentText(text)
        comp = QCompleter(senders, self.sender)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.sender.setCompleter(comp)
        if first_day:
            self.date_from.edit.setDate(QDate.fromString(first_day[:10], "yyyy-MM-dd"))
        if last_day:
            self.date_to.edit.setDate(QDate.fromString(last_day[:10], "yyyy-MM-dd"))
        self.blockSignals(False)

    def set_conversation(self, conv_id: str | None) -> None:
        i = self.conversation.findData(conv_id) if conv_id else 0
        self.conversation.setCurrentIndex(max(i, 0))

    def reset(self) -> None:
        self.blockSignals(True)
        for c in (self.mode, self.conversation, self.archive, self.content, self.media, self.link, self.sort,
                  self.reply):
            c.setCurrentIndex(0)
        self.sender.setCurrentText("")
        self.date_from.reset()
        self.date_to.reset()
        self.filename.clear()
        self.blockSignals(False)
        self.changed.emit()

    def active_count(self) -> int:
        q = self.to_query("")
        return sum(x is not None for x in (q.conversation_ids, q.archive_ids, q.sender, q.date_from, q.date_to,
                                           q.content_type, q.has_media, q.has_link, q.filename, q.is_reply))

    def to_query(self, text: str) -> SearchQuery:
        def data(c: QComboBox):
            d = c.currentData()
            return None if d == ANY else d
        conv = data(self.conversation)
        arch = data(self.archive)
        sender = self.sender.currentText().strip() or None
        return SearchQuery(
            text=text, mode=self.mode.currentData(),
            conversation_ids=[conv] if conv else None, archive_ids=[arch] if arch is not None else None,
            sender=sender, date_from=self.date_from.value(), date_to=self.date_to.value(),
            content_type=data(self.content), has_media=data(self.media), has_link=data(self.link),
            filename=self.filename.text().strip() or None, is_reply=data(self.reply), sort=self.sort.currentData())

    def set_query(self, q: SearchQuery) -> None:
        """Applique une recherche enregistrée ou de l'historique (le texte est géré par l'appelant)."""
        self.blockSignals(True)

        def pick(c: QComboBox, value) -> None:
            i = c.findData(ANY if value is None else value)
            c.setCurrentIndex(max(i, 0))

        pick(self.mode, q.mode)
        pick(self.conversation, q.conversation_ids[0] if q.conversation_ids else None)
        pick(self.archive, q.archive_ids[0] if q.archive_ids else None)
        pick(self.content, q.content_type)
        pick(self.media, q.has_media)
        pick(self.link, q.has_link)
        pick(self.reply, q.is_reply)
        pick(self.sort, q.sort)
        self.sender.setCurrentText(q.sender or "")
        self.filename.setText(q.filename or "")
        for widget, value in ((self.date_from, q.date_from), (self.date_to, q.date_to)):
            widget.set_value(value)
        self.blockSignals(False)
        self.changed.emit()
