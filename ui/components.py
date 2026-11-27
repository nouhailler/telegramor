"""Composants graphiques réutilisables (en-têtes de fenêtre, cartes, pastilles d'état)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app import design, icons


def dialog_header(title: str, subtitle: str = "", icon_name: str | None = None) -> QWidget:
    """En-tête commun des fenêtres secondaires : pictogramme, titre et sous-titre."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(12)
    if icon_name:
        tile = QLabel()
        tile.setObjectName("FileIcon")
        tile.setFixedSize(38, 38)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap(icon_name, design.current().accent, 20))
        h.addWidget(tile)
    col = QVBoxLayout()
    col.setSpacing(0)
    t = QLabel(title)
    t.setProperty("role", "title")
    col.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setProperty("muted", True)
        s.setWordWrap(True)
        col.addWidget(s)
    h.addLayout(col, 1)
    return w


def card(parent=None) -> QFrame:
    """Surface blanche (ou bleu nuit) bordée et arrondie."""
    f = QFrame(parent)
    f.setProperty("card", True)
    return f


def separator(vertical: bool = False) -> QFrame:
    s = QFrame()
    s.setProperty("separator", True)
    if vertical:
        s.setFixedWidth(1)
    return s


class ElidedLabel(QLabel):
    """Libellé d'une ligne qui se termine par « … » quand la place manque (texte complet en info-bulle)."""

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self):  # noqa: N802
        s = super().minimumSizeHint()
        s.setWidth(20)
        return s

    def paintEvent(self, _e) -> None:  # noqa: N802
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        r = self.contentsRect()
        p.drawText(r, int(self.alignment()) | Qt.AlignVCenter,
                   self.fontMetrics().elidedText(self.text(), Qt.ElideRight, r.width()))
        p.end()
