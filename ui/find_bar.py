"""Barre de recherche dans la conversation ouverte (Ctrl+F)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QToolButton, QWidget

from app import design, icons
from database.search_engine import MODE_PREFIX, SearchEngine, SearchQuery


class FindBar(QWidget):
    """Recherche les occurrences dans une conversation et navigue de l'une à l'autre.

    Entrée / ▲ : occurrence plus ancienne ; Maj+Entrée / ▼ : plus récente.
    """

    navigate = Signal(int, list)              # seq, termes
    terms_changed = Signal(list)              # termes à surligner ([] = aucun)
    advanced_requested = Signal(str)          # texte → recherche avancée
    closed = Signal()

    def __init__(self, engine: SearchEngine, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("FindBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.engine = engine
        self.conv_id: str | None = None
        self.current_seq_provider = lambda: None
        self.seqs: list[int] = []
        self.terms: list[str] = []
        self.index = -1

        self.edit = QLineEdit(placeholderText="Rechercher dans cette conversation…")
        self.edit.setProperty("variant", "search")
        self.edit.setAccessibleName("Rechercher dans cette conversation")
        self._icon_action = self.edit.addAction(icons.icon("search", design.current().muted, 16),
                                                QLineEdit.LeadingPosition)
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(lambda: self._timer.start())
        self.edit.returnPressed.connect(lambda: self.step(-1))
        QShortcut(QKeySequence("Shift+Return"), self.edit, activated=lambda: self.step(1),
                  context=Qt.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.close_bar,
                  context=Qt.WidgetWithChildrenShortcut)
        self.count = QLabel()
        self.count.setProperty("muted", True)
        self.count.setMinimumWidth(70)
        up = QToolButton(toolTip="Occurrence précédente, plus ancienne (Entrée)")
        down = QToolButton(toolTip="Occurrence suivante, plus récente (Maj+Entrée)")
        icons.bind(up, "chevron-up", "muted", 18)
        icons.bind(down, "chevron-down", "muted", 18)
        up.setAccessibleName("Occurrence précédente")
        down.setAccessibleName("Occurrence suivante")
        up.clicked.connect(lambda: self.step(-1))
        down.clicked.connect(lambda: self.step(1))
        adv = QToolButton(text="Avancée…", toolTip="Ouvrir la recherche avancée sur cette conversation")
        adv.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        icons.bind(adv, "filters", "muted", 16)
        adv.clicked.connect(lambda: self.advanced_requested.emit(self.edit.text()))
        close = QToolButton(toolTip="Fermer (Échap)")
        close.setAccessibleName("Fermer la recherche")
        icons.bind(close, "close", "muted", 16)
        close.clicked.connect(self.close_bar)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 8, 12, 8)
        lay.setSpacing(4)
        lay.addWidget(self.edit, 1)
        for w in (self.count, up, down, adv, close):
            lay.addWidget(w)
        self._timer = QTimer(self, singleShot=True, interval=250, timeout=self.search)
        self.hide()

    def open_bar(self, conv_id: str) -> None:
        if conv_id != self.conv_id:
            self.reset(conv_id)
        self.show()
        self.edit.setFocus()
        self.edit.selectAll()

    def reset(self, conv_id: str | None) -> None:
        self.conv_id = conv_id
        self.seqs, self.terms, self.index = [], [], -1
        self.count.clear()

    def close_bar(self) -> None:
        self.hide()
        self.edit.blockSignals(True)
        self.edit.clear()
        self.edit.blockSignals(False)
        self.reset(self.conv_id)
        self.terms_changed.emit([])
        self.closed.emit()

    def search(self) -> None:
        text = self.edit.text().strip()
        if not text or not self.conv_id:
            self.seqs, self.terms, self.index = [], [], -1
            self.count.clear()
            self.terms_changed.emit([])
            return
        self.seqs, self.terms = self.engine.matching_seqs(
            SearchQuery(text, mode=MODE_PREFIX, conversation_ids=[self.conv_id]))
        self.terms_changed.emit(self.terms)
        if not self.seqs:
            self.index = -1
            self.count.setText("Aucun")
            return
        # Première occurrence : la plus récente avant (ou à) la position affichée
        cur = self.current_seq_provider()
        self.index = len(self.seqs) - 1
        if cur is not None:
            before = [i for i, s in enumerate(self.seqs) if s <= cur + 30]
            if before:
                self.index = before[-1]
        self._go()

    def step(self, delta: int) -> None:
        if self._timer.isActive():
            self.search()
            return
        if not self.seqs:
            return
        self.index = (self.index + delta) % len(self.seqs)
        self._go()

    def _go(self) -> None:
        self.count.setText(f"{self.index + 1} / {len(self.seqs)}")
        self.navigate.emit(self.seqs[self.index], self.terms)
