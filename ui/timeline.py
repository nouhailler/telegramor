"""Chronologie d'une conversation : années → mois → jours, avec densité d'activité."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem

from app import design

from .formatting import JOURS, MOIS, plural

ROLE_DAY = Qt.UserRole + 1
ROLE_COUNT = Qt.UserRole + 2
ROLE_MAX = Qt.UserRole + 3


class DensityDelegate(QStyledItemDelegate):
    """Colonne 1 : barre proportionnelle au nombre de messages (relatif au niveau)."""

    def __init__(self, accent: str, parent=None) -> None:
        super().__init__(parent)
        self.accent = accent

    def paint(self, p, option, index) -> None:
        super().paint(p, option, index)
        if index.column() != 1:
            return
        th = design.current()
        n = index.data(ROLE_COUNT) or 0
        vmax = index.data(ROLE_MAX) or 1
        count_w = 44
        track = QRectF(option.rect.left() + 4, option.rect.center().y() - 3, option.rect.width() - count_w - 12, 6)
        w = max(track.width() * n / vmax, 4)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        bg = QPainterPath()
        bg.addRoundedRect(track, 3, 3)
        p.fillPath(bg, QColor(th.panel if not (option.state & QStyle.State_Selected) else th.surface))
        bar = QPainterPath()
        bar.addRoundedRect(QRectF(track.left(), track.top(), w, track.height()), 3, 3)
        p.fillPath(bar, QColor(self.accent))
        p.setPen(QColor(th.muted))
        p.drawText(QRectF(track.right() + 6, option.rect.top(), count_w, option.rect.height()),
                   Qt.AlignRight | Qt.AlignVCenter, f"{n:,}".replace(",", "\u202f"))
        p.restore()

    def sizeHint(self, option, index):  # noqa: N802
        s = super().sizeHint(option, index)
        s.setHeight(max(s.height(), 30))
        return s


def reduced_motion() -> bool:
    """Préférence « réduire les animations » (variable d'environnement GNOME/Qt usuelle)."""
    import os
    return os.environ.get("TAE_REDUCE_MOTION", "") == "1" or os.environ.get("GTK_ENABLE_ANIMATIONS", "1") == "0"


class Timeline(QTreeWidget):
    day_selected = Signal(str)          # AAAA-MM-JJ

    def __init__(self, accent: str, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setColumnCount(2)
        self.setItemDelegate(DensityDelegate(accent, self))
        self.setUniformRowHeights(False)
        self.setIndentation(14)
        self.setAnimated(not reduced_motion())
        self.header().setStretchLastSection(True)
        self.header().setSectionResizeMode(0, self.header().ResizeMode.ResizeToContents)
        self.itemClicked.connect(self._clicked)
        self.itemActivated.connect(self._clicked)
        self.days: dict[str, int] = {}

    def set_accent(self, accent: str) -> None:
        self.itemDelegate().accent = accent
        self.viewport().update()

    def set_days(self, days: dict[str, int]) -> None:
        """days : {AAAA-MM-JJ: nombre de messages}."""
        self.clear()
        self.days = days
        years: dict[str, dict[str, dict[str, int]]] = {}
        for d, n in sorted(days.items()):
            years.setdefault(d[:4], {}).setdefault(d[5:7], {})[d] = n
        ymax = max((sum(sum(m.values()) for m in ms.values()) for ms in years.values()), default=1)
        for y, months in sorted(years.items(), reverse=True):
            total = sum(sum(m.values()) for m in months.values())
            yi = self._item(None, y, total, ymax, f"{y}-01-01")
            mmax = max(sum(m.values()) for m in months.values())
            for mm, ds in sorted(months.items()):
                mi = self._item(yi, MOIS[int(mm) - 1].capitalize(), sum(ds.values()), mmax, f"{y}-{mm}-01")
                dmax = max(ds.values())
                for d, n in sorted(ds.items()):
                    dd = date.fromisoformat(d)
                    self._item(mi, f"{JOURS[dd.weekday()][:3]}. {dd.day}", n, dmax, d)
        if self.topLevelItemCount():
            self.topLevelItem(0).setExpanded(True)

    def _item(self, parent, label: str, n: int, vmax: int, day: str) -> QTreeWidgetItem:
        it = QTreeWidgetItem(parent or self, [label, ""])
        if parent is None:                      # années : plus visibles
            f = QFont(self.font())
            f.setWeight(QFont.DemiBold)
            f.setPointSizeF(f.pointSizeF() * 1.05)
            it.setFont(0, f)
        it.setData(0, ROLE_DAY, day)
        it.setData(1, ROLE_COUNT, n)
        it.setData(1, ROLE_MAX, vmax)
        it.setToolTip(0, plural(n, "message"))
        it.setToolTip(1, plural(n, "message"))
        return it

    def _clicked(self, it: QTreeWidgetItem, _col: int = 0) -> None:
        day = it.data(0, ROLE_DAY)
        if day:
            self.day_selected.emit(day)

    def select_day(self, day: str | None) -> None:
        """Met en évidence le jour affiché (sans émettre de signal)."""
        if not day:
            return
        for i in range(self.topLevelItemCount()):
            y = self.topLevelItem(i)
            if y.data(0, ROLE_DAY)[:4] != day[:4]:
                continue
            for j in range(y.childCount()):
                m = y.child(j)
                if m.data(0, ROLE_DAY)[:7] != day[:7]:
                    continue
                for k in range(m.childCount()):
                    d = m.child(k)
                    if d.data(0, ROLE_DAY) == day:
                        self.blockSignals(True)
                        self.setCurrentItem(d)
                        self.blockSignals(False)
                        self.scrollToItem(d)
                        return


def neighbour_day(days: dict[str, int] | list[str], current: str | None, step: int, unit: str = "day") -> str | None:
    """Jour ayant des messages avant/après `current` (unit = 'day' ou 'month')."""
    ordered = sorted(days)
    if not ordered:
        return None
    if current is None:
        return ordered[-1] if step < 0 else ordered[0]
    if unit == "month":
        cur = current[:7]
        if step > 0:
            return next((d for d in ordered if d[:7] > cur), None)
        prev_months = [d for d in ordered if d[:7] < cur]
        if not prev_months:
            return None
        target = prev_months[-1][:7]
        return next(d for d in ordered if d[:7] == target)
    if step > 0:
        return next((d for d in ordered if d > current), None)
    prev = [d for d in ordered if d < current]
    return prev[-1] if prev else None
