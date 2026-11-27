"""Fenêtre de statistiques : tuiles chiffrées et graphiques (dessinés avec QPainter).

Conventions graphiques : une seule série par graphique, couleur d'accent du
thème ; barres fines à coin arrondi côté valeur, ancrées sur la ligne de base,
séparées de 2 px ; grille discrète ; info-bulle au survol de chaque barre ou
case ; carte de chaleur à une seule teinte (clair → foncé).
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
    QPushButton, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QToolButton, QToolTip, QVBoxLayout,
    QWidget,
)

from app import design, icons
from app.styles import Theme
from database.db_manager import Database
from database.repositories import LibraryRepository, media_label
from services.statistics_service import Scope, Statistics, compare, compute, to_csv, weekday_label

from .components import dialog_header
from .formatting import MOIS_COURTS, day_medium, month_label, plural


def _fmt(n: int | float) -> str:
    if isinstance(n, float):
        return f"{n:,.1f}".replace(",", " ").replace(".", ",")
    return f"{n:,}".replace(",", " ")


def _rounded_bar(rect: QRectF, radius: float, horizontal: bool = False) -> QPainterPath:
    """Barre arrondie côté valeur seulement (ancrée sur la ligne de base)."""
    path = QPainterPath()
    r = min(radius, rect.width() / 2, rect.height() / 2)
    if horizontal:
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right() - r, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
        path.lineTo(rect.right(), rect.bottom() - r)
        path.quadTo(rect.right(), rect.bottom(), rect.right() - r, rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
    else:
        path.moveTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + r)
        path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())
        path.lineTo(rect.right() - r, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
        path.lineTo(rect.right(), rect.bottom())
    path.closeSubpath()
    return path


class BarChart(QWidget):
    """Histogramme vertical, une série. `labels` : étiquettes d'axe (vides = non affichées)."""

    bar_clicked = Signal(int)

    def __init__(self, theme: Theme, height: int = 190, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.values: list[int] = []
        self.labels: list[str] = []
        self.tips: list[str] = []
        self.hover = -1
        self.clickable = False
        self.setMinimumHeight(height)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, values: list[int], labels: list[str], tips: list[str]) -> None:
        self.values, self.labels, self.tips = values, labels, tips
        self.update()

    def _geom(self) -> tuple[QRectF, float]:
        fm = QFontMetrics(self.font())
        plot = QRectF(fm.horizontalAdvance("00000") + 8, 8, self.width() - fm.horizontalAdvance("00000") - 16,
                      self.height() - fm.height() - 20)
        step = plot.width() / max(len(self.values), 1)
        return plot, step

    def paintEvent(self, _e) -> None:  # noqa: N802
        if not self.values:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.theme
        plot, step = self._geom()
        vmax = max(max(self.values), 1)
        fm = QFontMetrics(self.font())
        # grille discrète (0, moitié, max)
        p.setPen(QColor(t.muted))
        for frac in (0, 0.5, 1):
            y = plot.bottom() - frac * plot.height()
            p.setPen(QColor(t.border))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(t.muted))
            p.drawText(QRectF(0, y - fm.height() / 2, plot.left() - 6, fm.height()), Qt.AlignRight | Qt.AlignVCenter,
                       _fmt(round(vmax * frac)))
        gap = 2 if step > 6 else 0
        accent = QColor(t.accent)
        for i, v in enumerate(self.values):
            if v <= 0:
                continue
            h = v / vmax * plot.height()
            rect = QRectF(plot.left() + i * step + gap / 2, plot.bottom() - h, max(step - gap, 1), h)
            col = QColor(accent)
            if self.hover >= 0 and i != self.hover:
                col.setAlphaF(0.55)
            p.fillPath(_rounded_bar(rect, 4), col)
        # étiquettes d'axe
        p.setPen(QColor(t.muted))
        last_right = -1e9
        for i, lab in enumerate(self.labels):
            if not lab:
                continue
            x = plot.left() + (i + 0.5) * step
            w = fm.horizontalAdvance(lab)
            if x - w / 2 < last_right + 6:
                continue
            p.drawText(QRectF(x - w / 2, plot.bottom() + 4, w, fm.height()), Qt.AlignCenter, lab)
            last_right = x + w / 2
        p.end()

    def _index_at(self, x: float) -> int:
        plot, step = self._geom()
        if not self.values or x < plot.left() or x > plot.right():
            return -1
        return min(int((x - plot.left()) / step), len(self.values) - 1)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        i = self._index_at(e.position().x())
        if i != self.hover:
            self.hover = i
            self.update()
        if i >= 0:
            QToolTip.showText(e.globalPosition().toPoint(), self.tips[i] if i < len(self.tips) else "", self)
            self.setCursor(Qt.PointingHandCursor if self.clickable and self.values[i] else Qt.ArrowCursor)

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self.hover = -1
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        i = self._index_at(e.position().x())
        if i >= 0 and self.clickable and self.values[i]:
            self.bar_clicked.emit(i)


class HBarChart(QWidget):
    """Barres horizontales classées (expéditeurs, types de médias)."""

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.rows: list[tuple[str, int]] = []
        self.total = 0
        self.setMouseTracking(True)

    def set_data(self, rows: list[tuple[str, int]], max_rows: int = 12) -> None:
        self.total = sum(n for _, n in rows)
        if len(rows) > max_rows:
            rest = sum(n for _, n in rows[max_rows - 1:])
            rows = rows[:max_rows - 1] + [(f"Autres ({len(rows) - max_rows + 1})", rest)]
        self.rows = rows
        fm = QFontMetrics(self.font())
        self.setMinimumHeight(max(len(rows), 1) * (fm.height() + 10) + 4)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(300, self.minimumHeight())

    def paintEvent(self, _e) -> None:  # noqa: N802
        if not self.rows:
            p = QPainter(self)
            p.setPen(QColor(self.theme.muted))
            p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignTop, "Aucun")
            p.end()
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = QFontMetrics(self.font())
        row_h = fm.height() + 10
        label_w = min(max(fm.horizontalAdvance(n) for n, _ in self.rows) + 12, self.width() * 0.4)
        value_w = fm.horizontalAdvance("000 000 (100 %)") + 8
        vmax = max(n for _, n in self.rows) or 1
        avail = self.width() - label_w - value_w
        for i, (name, n) in enumerate(self.rows):
            y = i * row_h
            p.setPen(QColor(self.theme.text))
            p.drawText(QRectF(0, y, label_w - 8, row_h), Qt.AlignRight | Qt.AlignVCenter,
                       fm.elidedText(name, Qt.ElideRight, int(label_w - 8)))
            w = max(n / vmax * avail, 2)
            p.fillPath(_rounded_bar(QRectF(label_w, y + 5, w, row_h - 10), 4, horizontal=True),
                       QColor(self.theme.accent))
            p.setPen(QColor(self.theme.muted))
            pct = f" ({n / self.total:.0%})".replace("%", " %") if self.total else ""
            p.drawText(QRectF(label_w + w + 6, y, value_w, row_h), Qt.AlignLeft | Qt.AlignVCenter, _fmt(n) + pct)
        p.end()


class Heatmap(QWidget):
    """Activité par jour de la semaine × heure, une seule teinte (clair → foncé)."""

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.grid = [[0] * 24 for _ in range(7)]
        self.setMouseTracking(True)
        self.setMinimumHeight(7 * 24 + 44)

    def set_data(self, grid: list[list[int]]) -> None:
        self.grid = grid
        self.update()

    def _geom(self):
        fm = QFontMetrics(self.font())
        left = max(fm.horizontalAdvance(weekday_label(d)) for d in range(7)) + 12
        cell_w = (self.width() - left - 4) / 24
        cell_h = 24
        return left, cell_w, cell_h

    def _color(self, v: int, vmax: int) -> QColor:
        if v == 0:
            return QColor(self.theme.panel)
        a, b = QColor(self.theme.accent_soft), QColor(self.theme.accent)
        t = 0.18 + 0.82 * (v / vmax)
        return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                      int(a.blue() + (b.blue() - a.blue()) * t))

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = QFontMetrics(self.font())
        left, cw, ch = self._geom()
        vmax = max(max(r) for r in self.grid) or 1
        for d in range(7):
            p.setPen(QColor(self.theme.muted))
            p.drawText(QRectF(0, d * ch, left - 8, ch), Qt.AlignRight | Qt.AlignVCenter, weekday_label(d))
            for h in range(24):
                rect = QRectF(left + h * cw + 1, d * ch + 1, cw - 2, ch - 2)
                path = QPainterPath()
                path.addRoundedRect(rect, 4, 4)
                p.fillPath(path, self._color(self.grid[d][h], vmax))
        p.setPen(QColor(self.theme.muted))
        for h in range(0, 24, 3):
            p.drawText(QRectF(left + h * cw, 7 * ch + 2, cw * 2, fm.height()), Qt.AlignLeft, f"{h} h")
        # légende moins → plus
        y = 7 * ch + fm.height() + 8
        x = left
        p.drawText(QRectF(x, y, 60, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, "moins")
        x += fm.horizontalAdvance("moins") + 6
        for k in range(5):
            r = QRectF(x + k * 16, y + 2, 14, fm.height() - 4)
            path = QPainterPath()
            path.addRoundedRect(r, 3, 3)
            p.fillPath(path, self._color(0 if k == 0 else int(vmax * k / 4), vmax))
        p.drawText(QRectF(x + 5 * 16 + 4, y, 60, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, "plus")
        p.end()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        left, cw, ch = self._geom()
        x, y = e.position().x(), e.position().y()
        d, h = int(y // ch), int((x - left) // cw)
        if 0 <= d < 7 and 0 <= h < 24 and x >= left:
            QToolTip.showText(e.globalPosition().toPoint(),
                              f"{weekday_label(d).capitalize()}, {h} h – {h + 1} h : "
                              f"{plural(self.grid[d][h], 'message')}", self)
        else:
            QToolTip.hideText()


KPI_STYLE = {   # pictogramme et teinte de chaque indicateur (couleurs de la palette, avec parcimonie)
    "messages": ("chat", "accent"), "jours actifs": ("calendar", "turquoise"),
    "messages par jour actif": ("chart", "violet"), "jour le plus actif": ("timeline", "accent"),
    "jours d'affilée (record)": ("refresh", "turquoise"), "jours de silence (record)": ("clock", "violet"),
}


def _tile(value: str, label: str, detail: str = "") -> QFrame:
    """Carte d'indicateur : pictogramme teinté, valeur en grand, libellé et détail."""
    th = design.current()
    f = QFrame(objectName="KpiCard")
    lay = QHBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(14)
    icon_name, tone = KPI_STYLE.get(label, ("chart", "accent"))
    base = QColor(getattr(th, tone))
    soft = QColor(base)
    soft.setAlpha(36 if th.dark else 26)
    ic = QLabel(objectName="KpiIcon", alignment=Qt.AlignCenter)
    ic.setFixedSize(42, 42)
    ic.setStyleSheet(f"background: rgba({soft.red()},{soft.green()},{soft.blue()},{soft.alphaF():.2f}); "
                     f"border-radius: 12px;")
    ic.setPixmap(icons.pixmap(icon_name, base.name(), 22))
    lay.addWidget(ic, 0, Qt.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(1)
    v = QLabel(value, objectName="KpiValue")
    lab = QLabel(label[:1].upper() + label[1:], objectName="KpiLabel")
    col.addWidget(v)
    col.addWidget(lab)
    d = QLabel(detail or " ", objectName="KpiDetail")
    d.setWordWrap(True)
    col.addWidget(d)
    lay.addLayout(col, 1)
    return f


def _section(title: str, widget: QWidget, note: str = "") -> QWidget:
    """Carte de graphique : titre, note discrète, contenu."""
    w = QFrame(objectName="ChartCard")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 16)
    lay.setSpacing(10)
    head = QHBoxLayout()
    t = QLabel(escape(title))
    t.setProperty("role", "section")
    head.addWidget(t)
    if note:
        n = QLabel(escape(note))
        n.setProperty("role", "caption")
        head.addWidget(n)
    head.addStretch(1)
    lay.addLayout(head)
    lay.addWidget(widget)
    return w


class StatisticsWindow(QDialog):
    go_to_day = Signal(str, str)        # conversation, jour AAAA-MM-JJ
    search_word = Signal(str)           # clic sur un mot ou une expression : recherche globale

    def __init__(self, db: Database, repo: LibraryRepository, theme: Theme, parent=None, settings=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Statistiques")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.db, self.repo, self.theme = db, repo, theme
        self.stats: Statistics | None = None

        self.conv = QComboBox()
        self.conv.addItem("Toute la bibliothèque", None)
        for c in sorted(repo.list_conversations(), key=lambda c: c.name.casefold()):
            self.conv.addItem(c.name, c.id)
        self.sender = QComboBox()
        self.sender.addItem("Tous les expéditeurs", None)
        for (name,) in db.conn.execute("SELECT name FROM participants GROUP BY name ORDER BY name COLLATE NOCASE"):
            self.sender.addItem(name, name)
        for c in (self.conv, self.sender):
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(16)
            c.currentIndexChanged.connect(self.refresh)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(dialog_header("Statistiques", "Activité, rythmes et participants", "chart"), 1)
        scope = QLabel("Portée")
        scope.setProperty("muted", True)
        top.addWidget(scope)
        top.addWidget(self.conv)
        top.addWidget(self.sender)
        from ui.advanced_search import OptionalDate
        self.date_from = OptionalDate("Depuis le")
        self.date_to = OptionalDate("Jusqu'au")
        for d in (self.date_from, self.date_to):
            d.changed.connect(self.refresh)
        self.exclude = QLineEdit(placeholderText="Mots à exclure de l'analyse (séparés par des virgules)")
        self.exclude.setClearButtonEnabled(True)
        if settings is not None:
            self.exclude.setText(str(settings.s.value("stats/excluded_words", "")))
        self.exclude.editingFinished.connect(self._exclusions_changed)
        export = QToolButton(text="Exporter")
        export.setProperty("variant", "secondary")
        export.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        export.setPopupMode(QToolButton.InstantPopup)
        icons.bind(export, "export", "muted", 16)
        em = QMenu(export)
        em.addAction("Données (CSV)…", self.export_csv)
        em.addAction("Tableau de bord (image PNG)…", self.export_png)
        export.setMenu(em)
        cmp_btn = QPushButton("Comparer…")
        icons.bind(cmp_btn, "chart", "muted", 16)
        cmp_btn.setToolTip("Comparer deux conversations, deux années ou deux périodes")
        cmp_btn.clicked.connect(self.open_compare)
        second = QHBoxLayout()
        second.setSpacing(8)
        second.setContentsMargins(20, 0, 20, 0)
        period = QLabel("Période")
        period.setProperty("muted", True)
        second.addWidget(period)
        second.addWidget(self.date_from)
        second.addWidget(self.date_to)
        second.addWidget(self.exclude, 1)
        second.addWidget(cmp_btn)
        second.addWidget(export)
        self._second = second

        self.tiles = QGridLayout()
        self.months = BarChart(theme)
        self.months.bar_clicked.connect(self._month_clicked)
        self.hours = BarChart(theme, 150)
        self.weekdays = BarChart(theme, 150)
        self.senders = HBarChart(theme)
        self.media = HBarChart(theme)
        self.heat = Heatmap(theme)
        self.words = QLabel(wordWrap=True)
        self.words.setTextFormat(Qt.RichText)
        self.words.linkActivated.connect(lambda w: self.search_word.emit(w))
        self.ngrams = QLabel(wordWrap=True)
        self.ngrams.setTextFormat(Qt.RichText)
        self.ngrams.linkActivated.connect(lambda w: self.search_word.emit(w))
        self.month_note = QLabel()

        body = QWidget()
        b = QVBoxLayout(body)
        b.setContentsMargins(20, 6, 14, 20)
        b.setSpacing(14)
        self.tiles.setSpacing(12)
        b.addLayout(self.tiles)
        self.month_section = _section("Messages par mois", self.months)
        b.addWidget(self.month_section)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(_section("Par heure de la journée", self.hours), 3)
        row.addWidget(_section("Par jour de la semaine", self.weekdays), 2)
        b.addLayout(row)
        b.addWidget(_section("Rythme de la semaine", self.heat, "jour × heure"))
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        row2.addWidget(_section("Expéditeurs", self.senders), 1)
        row2.addWidget(_section("Médias et liens", self.media), 1)
        b.addLayout(row2)
        b.addWidget(_section("Mots les plus fréquents", self.words,
                             "hors mots courants · cliquer sur un mot pour le rechercher"))
        b.addWidget(_section("Expressions fréquentes", self.ngrams, "groupes de deux et trois mots, vus au moins "
                             "deux fois · cliquer pour rechercher"))
        b.addStretch(1)
        area = QScrollArea()
        area.setWidget(body)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 18, 0, 0)
        lay.setSpacing(12)
        top.setContentsMargins(20, 0, 20, 0)
        lay.addLayout(top)
        lay.addLayout(self._second)
        lay.addWidget(area, 1)
        self._body = body
        self.setMinimumSize(760, 560)
        self.resize(1120, 880)
        self.refresh()

    def set_conversation(self, conv_id: str | None) -> None:
        self.conv.setCurrentIndex(max(self.conv.findData(conv_id), 0))

    def _excluded(self) -> list[str]:
        return [w.strip() for w in self.exclude.text().split(",") if w.strip()]

    def _exclusions_changed(self) -> None:
        if self.settings is not None:
            self.settings.s.setValue("stats/excluded_words", self.exclude.text())
        self.refresh()

    def scope_label(self) -> str:
        parts = [self.conv.currentText()]
        if self.sender.currentData():
            parts.append(self.sender.currentText())
        a, b = self.date_from.value(), self.date_to.value()
        if a or b:
            parts.append(f"{a or '…'} → {b or '…'}")
        return " · ".join(parts)

    def refresh(self) -> None:
        conv_id = self.conv.currentData()
        st = self.stats = compute(self.db, conv_id, self.sender.currentData(), date_from=self.date_from.value(),
                                  date_to=self.date_to.value(), excluded_words=self._excluded())
        while self.tiles.count():
            w = self.tiles.takeAt(0).widget()
            if w:
                w.hide()              # masqué tout de suite : la suppression est différée
                w.deleteLater()
        streak, s0, s1 = st.longest_streak
        silence, g0, g1 = st.longest_silence
        tiles = [
            _tile(_fmt(st.messages), "messages", f"{plural(st.conversations, 'conversation')}, "
                                                 f"{plural(st.participants, 'participant')}"),
            _tile(_fmt(st.active_days), "jours actifs", f"sur {_fmt(st.span_days)} jours"),
            _tile(_fmt(st.per_active_day), "messages par jour actif"),
            _tile(_fmt(st.busiest_day[1]) if st.busiest_day else "—", "jour le plus actif",
                  day_medium(st.busiest_day[0]) if st.busiest_day else ""),
            _tile(_fmt(streak), "jours d'affilée (record)",
                  f"du {day_medium(s0)} au {day_medium(s1)}" if streak > 1 else ""),
            _tile(_fmt(silence), "jours de silence (record)",
                  f"du {day_medium(g0)} au {day_medium(g1)}" if silence else ""),
        ]
        for i, t in enumerate(tiles):
            self.tiles.addWidget(t, i // 3, i % 3)

        months = st.per_month
        self.months.set_data(
            [n for _, n in months],
            [(MOIS_COURTS[int(ym[5:]) - 1] + (" " + ym[:4] if ym[5:] == "01" or i == 0 else "")) if
             (len(months) <= 24 or ym[5:] in ("01", "07")) else "" for i, (ym, _) in enumerate(months)],
            [f"{month_label(ym).capitalize()} : {plural(n, 'message')}" for ym, n in months])
        self.months.clickable = conv_id is not None
        self.months.setToolTip("Cliquer sur un mois pour l'ouvrir dans la conversation" if conv_id else "")
        self.hours.set_data(st.per_hour, [f"{h} h" if h % 3 == 0 else "" for h in range(24)],
                            [f"{h} h – {h + 1} h : {plural(n, 'message')}" for h, n in enumerate(st.per_hour)])
        self.weekdays.set_data(st.per_weekday, [weekday_label(i)[:3] for i in range(7)],
                               [f"{weekday_label(i).capitalize()} : {plural(n, 'message')}"
                                for i, n in enumerate(st.per_weekday)])
        self.heat.set_data(st.heatmap)
        self.senders.set_data(st.per_sender)
        media_rows = [(media_label(t) or t, n) for t, n in st.media.items()]
        if st.links:
            media_rows.append(("Liens", st.links))
        self.media.set_data(sorted(media_rows, key=lambda r: -r[1]))
        if st.top_words:
            top = st.top_words[0][1]
            parts = []
            for w, n in st.top_words:
                size = 90 + int(70 * n / top)
                th = design.current()
                weight = 600 if n >= top * 0.5 else 400
                color = th.accent_text if n >= top * 0.6 else th.text
                parts.append(f"<a href='{escape(w, quote=True)}' style='text-decoration:none; font-size:{size}%; "
                             f"font-weight:{weight}; color:{color}' title='{n}'>{escape(w)}</a>"
                             f"<span style='color:{th.faint}; font-size:78%'>&nbsp;{n}</span>")
            self.words.setText("<div style='line-height:170%'>" + " &nbsp;&nbsp; ".join(parts) + "</div>")
            self.words.setToolTip(f"Calculé sur {plural(st.words_sampled, 'message')} (les plus récents de la portée)")
        else:
            self.words.setText("—")
        th = design.current()
        grams = st.top_bigrams[:15] + st.top_trigrams[:10]
        if grams:
            self.ngrams.setText("<div style='line-height:180%'>" + " &nbsp;·&nbsp; ".join(
                f"<a href='\"{escape(g, quote=True)}\"' style='text-decoration:none; color:{th.accent_text}'>"
                f"{escape(g)}</a><span style='color:{th.faint}; font-size:78%'>&nbsp;{n}</span>"
                for g, n in sorted(grams, key=lambda x: -x[1])) + "</div>")
        else:
            self.ngrams.setText("—")

    # ------------------------------------------------------------------ #
    # Exports et comparaison
    # ------------------------------------------------------------------ #

    def _save_path(self, title: str, name: str, filt: str) -> str:
        from PySide6.QtCore import QStandardPaths
        from pathlib import Path
        base = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getSaveFileName(self, title, str(Path(base) / name), filt)
        return path

    def export_csv(self) -> None:
        if not self.stats:
            return
        path = self._save_path("Exporter les données", "statistiques-telegramor.csv", "CSV (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:     # BOM : ouverture correcte dans un tableur
                f.write(to_csv(self.stats, self.scope_label()))

    def export_png(self) -> None:
        path = self._save_path("Exporter le tableau de bord", "statistiques-telegramor.png", "Image PNG (*.png)")
        if path:
            self.grab_dashboard().save(path if path.lower().endswith(".png") else path + ".png", "PNG")

    def grab_dashboard(self):
        """Image complète du tableau de bord (titres, légendes, unités et valeurs compris)."""
        from PySide6.QtGui import QPixmap
        body = self._body
        pm = QPixmap(body.size())
        pm.fill(QColor(design.current().window))
        body.render(pm)
        return pm

    def open_compare(self) -> None:
        dlg = CompareDialog(self.db, self.repo, self.theme, self)
        dlg.show()
        self._compare = dlg

    def retheme(self, theme: Theme) -> None:
        self.theme = theme
        for chart in (self.months, self.hours, self.weekdays, self.senders, self.media, self.heat):
            chart.theme = theme
        self.refresh()

    def _month_clicked(self, i: int) -> None:
        conv_id = self.conv.currentData()
        if conv_id and self.stats:
            self.go_to_day.emit(conv_id, self.stats.per_month[i][0] + "-01")


class _ScopePicker(QWidget):
    """Choix d'une portée de comparaison : conversation, expéditeur, période."""

    changed = Signal()

    def __init__(self, title: str, repo: LibraryRepository, db: Database, parent=None) -> None:
        super().__init__(parent)
        from ui.advanced_search import OptionalDate
        self.title = title
        self.conv = QComboBox()
        self.conv.addItem("Toute la bibliothèque", None)
        for c in sorted(repo.list_conversations(), key=lambda c: c.name.casefold()):
            self.conv.addItem(c.name, c.id)
        self.year = QComboBox()
        self.year.addItem("Toutes les années", None)
        for y in repo.years():
            self.year.addItem(y, y)
        self.date_from = OptionalDate("Depuis le")
        self.date_to = OptionalDate("Jusqu'au")
        for c in (self.conv, self.year):
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(14)
            c.currentIndexChanged.connect(self.changed)
        for d in (self.date_from, self.date_to):
            d.changed.connect(self.changed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        cap = QLabel(title.upper())
        cap.setProperty("role", "overline")
        lay.addWidget(cap)
        lay.addWidget(self.conv)
        lay.addWidget(self.year)
        lay.addWidget(self.date_from)
        lay.addWidget(self.date_to)

    def scope(self) -> Scope:
        a, b = self.date_from.value(), self.date_to.value()
        y = self.year.currentData()
        if y and not a and not b:
            a, b = f"{y}-01-01", f"{y}-12-31"
        label = self.conv.currentText() + (f" · {y}" if y and not (self.date_from.value() or self.date_to.value())
                                           else "") + (f" · {a} → {b}" if self.date_from.value()
                                                       or self.date_to.value() else "")
        return Scope(label, self.conv.currentData(), None, a, b)


class CompareDialog(QDialog):
    """Comparaison de deux conversations, deux années ou deux périodes (volumes ramenés à la durée)."""

    def __init__(self, db: Database, repo: LibraryRepository, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Comparer")
        self.db, self.repo, self.theme = db, repo, theme
        self.a = _ScopePicker("Portée A", repo, db)
        self.b = _ScopePicker("Portée B", repo, db)
        years = repo.years()
        if len(years) >= 2:                        # par défaut : les deux dernières années
            self.a.year.setCurrentIndex(self.a.year.findData(years[1]))
            self.b.year.setCurrentIndex(self.b.year.findData(years[0]))
        for p in (self.a, self.b):
            p.changed.connect(self.refresh)
        self.table = QTableWidget(0, 4)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.hours_a, self.hours_b = BarChart(theme, 120), BarChart(theme, 120)
        self.note = QLabel("Les volumes sont ramenés à la durée de chaque période (messages par jour, part de jours "
                           "actifs, pour 100 messages) afin de comparer des périodes de longueurs différentes. "
                           "L'écart est calculé de A vers B.")
        self.note.setWordWrap(True)
        self.note.setProperty("role", "caption")
        export = QPushButton("Exporter (CSV)…")
        icons.bind(export, "export", "muted", 16)
        export.clicked.connect(self.export_csv)
        pickers = QHBoxLayout()
        pickers.setSpacing(18)
        pickers.addWidget(self.a, 1)
        pickers.addWidget(self.b, 1)
        charts = QHBoxLayout()
        self.hours_a_card = _section("Répartition horaire — A", self.hours_a, "% des messages")
        self.hours_b_card = _section("Répartition horaire — B", self.hours_b, "% des messages")
        charts.addWidget(self.hours_a_card)
        charts.addWidget(self.hours_b_card)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(12)
        lay.addWidget(dialog_header("Comparer", "Deux conversations, deux années ou deux périodes", "chart"))
        lay.addLayout(pickers)
        lay.addWidget(self.table, 1)
        lay.addLayout(charts)
        lay.addWidget(self.note)
        lay.addWidget(export, 0, Qt.AlignRight)
        self.resize(980, 820)
        self.refresh()

    def refresh(self) -> None:
        self.result = compare(self.db, self.a.scope(), self.b.scope())
        r = self.result
        self.table.setHorizontalHeaderLabels(["Indicateur", f"A — {r.a.label}", f"B — {r.b.label}", "Écart (A → B)"])
        self.table.setRowCount(len(r.rows))
        for i, row in enumerate(r.rows):
            for j, v in enumerate(row):
                it = QTableWidgetItem(v)
                if j:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        labels = [f"{h} h" if h % 3 == 0 else "" for h in range(24)]
        for chart, values in ((self.hours_a, r.hours_pct[0]), (self.hours_b, r.hours_pct[1])):
            chart.set_data(values, labels, [f"{h} h – {h + 1} h : {v} %" for h, v in enumerate(values)])

    def export_csv(self) -> None:
        import csv
        from pathlib import Path
        from PySide6.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getSaveFileName(self, "Exporter la comparaison",
                                              str(Path(base) / "comparaison-telegramor.csv"), "CSV (*.csv)")
        if not path:
            return
        r = self.result
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Indicateur", f"A — {r.a.label}", f"B — {r.b.label}", "Écart (A → B)"])
            w.writerows(r.rows)
            w.writerow([])
            w.writerow(["Heure", "A (% des messages)", "B (% des messages)"])
            w.writerows([(f"{h:02d}h", r.hours_pct[0][h], r.hours_pct[1][h]) for h in range(24)])
            w.writerow([])
            w.writerow(["Jour", "A (% des messages)", "B (% des messages)"])
            w.writerows([(weekday_label(d), r.weekdays_pct[0][d], r.weekdays_pct[1][d]) for d in range(7)])
