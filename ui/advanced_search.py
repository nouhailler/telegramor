"""Filtres combinables de la recherche avancée."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDateEdit, QFormLayout, QHBoxLayout, QLineEdit, QPushButton,
    QWidget,
)

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
        self.filename = QLineEdit(placeholderText="ex. facture, .pdf, IMG_2034")
        self.filename.setClearButtonEnabled(True)
        self.sort = _combo([("Pertinence", SORT_RELEVANCE), ("Plus récents d'abord", SORT_NEWEST),
                            ("Plus anciens d'abord", SORT_OLDEST)])
        reset = QPushButton("Réinitialiser les filtres")
        reset.clicked.connect(self.reset)

        form = QFormLayout(self)
        form.setContentsMargins(4, 4, 4, 4)
        form.setLabelAlignment(Qt.AlignRight)
        form.addRow("Recherche", self.mode)
        form.addRow("Conversation", self.conversation)
        form.addRow("Archive", self.archive)
        form.addRow("Expéditeur", self.sender)
        form.addRow("Période", self.date_from)
        form.addRow("", self.date_to)
        form.addRow("Type", self.content)
        form.addRow("Pièce jointe", self.media)
        form.addRow("Lien", self.link)
        form.addRow("Nom de fichier", self.filename)
        form.addRow("Tri", self.sort)
        form.addRow("", reset)

        for c in (self.mode, self.conversation, self.archive, self.content, self.media, self.link, self.sort,
                  self.sender):
            # largeur limitée : les longs noms de conversation ne doivent pas élargir le panneau
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(8)
        for c in (self.mode, self.conversation, self.archive, self.content, self.media, self.link, self.sort):
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
        for c in (self.mode, self.conversation, self.archive, self.content, self.media, self.link, self.sort):
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
                                           q.content_type, q.has_media, q.has_link, q.filename))

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
            filename=self.filename.text().strip() or None, sort=self.sort.currentData())
