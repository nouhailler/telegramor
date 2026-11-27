"""Zone centrale : affichage d'une conversation en bulles, avec chargement progressif.

Seule une fenêtre de messages (au plus MAX_ROWS lignes) est présente en mémoire.
Des pages sont chargées en haut ou en bas au défilement, et les lignes
éloignées sont libérées. Lors de chaque modification, une ligne visible sert
d'ancre pour que l'affichage ne « saute » pas.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QMenu, QScrollArea,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from app import icons
from app.design import sender_color
from app.styles import Theme
from database.models import ConversationSummary, MediaRow, MessageRow
from database.repositories import LibraryRepository
from database.search_engine import SearchEngine
from services.media_service import open_url
from services.navigation_service import Location, NavigationHistory

from .components import ElidedLabel, dialog_header
from .find_bar import FindBar
from .timeline import neighbour_day
from .formatting import day_long, month_label, period, plural
from .media_viewer import ImageViewer, play_video
from .message_widgets import RenderContext, RowWidget, make_row

PAGE = 60
MAX_ROWS = 400
EDGE_PX = 600
SETTLE_MS = 250         # durée de stabilisation après un saut
READING_MAX = 1060      # largeur maximale de la colonne de lecture
TOP_MARGIN = 8          # marge au-dessus d'une ligne positionnée « en haut »


class DateDialog(QDialog):
    """Choix d'une date ; les jours contenant des messages sont en gras."""

    def __init__(self, days: dict[str, int], current: str | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Aller à la date")
        self.cal = QCalendarWidget()
        self.cal.setGridVisible(False)
        self.cal.setLocale(self.locale())
        self.cal.setFirstDayOfWeek(Qt.Monday)
        bold = QTextCharFormat()
        bold.setFontWeight(QFont.Bold)
        bold.setForeground(self.palette().highlight())
        for d, n in days.items():
            qd = QDate.fromString(d, "yyyy-MM-dd")
            fmt = QTextCharFormat(bold)
            fmt.setToolTip(plural(n, "message"))
            self.cal.setDateTextFormat(qd, fmt)
        if days:
            ks = sorted(days)
            self.cal.setDateRange(QDate.fromString(ks[0], "yyyy-MM-dd"), QDate.fromString(ks[-1], "yyyy-MM-dd"))
        if current:
            self.cal.setSelectedDate(QDate.fromString(current, "yyyy-MM-dd"))
        self.cal.activated.connect(lambda *_: self.accept())
        info = QLabel("Les jours en gras contiennent des messages. Double-clic pour y aller.")
        info.setProperty("muted", True)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Aller")
        bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Ok).setProperty("variant", "primary")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        lay.setSpacing(10)
        lay.addWidget(dialog_header("Aller à la date", "", "calendar"))
        lay.addWidget(self.cal)
        lay.addWidget(info)
        lay.addWidget(bb)

    def selected_day(self) -> str:
        return self.cal.selectedDate().toString("yyyy-MM-dd")


class MessageView(QWidget):
    position_changed = Signal(str, int)      # conversation, seq de la première ligne visible
    toggle_info_panel = Signal()
    advanced_search_requested = Signal(str, str)   # texte, conversation
    day_changed = Signal(str)                      # jour affiché en haut de la vue
    personal_action = Signal(str, object)          # action personnelle (favori, note…), MessageRow

    def __init__(self, repo: LibraryRepository, theme: Theme, engine: SearchEngine | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.repo = repo
        self.engine = engine or SearchEngine(repo.db)
        self.terms: list[str] = []
        self.theme = theme
        self.owner: str | None = None
        self.zoom = 100
        self.internal_video = True
        self.conv: ConversationSummary | None = None
        self.bounds: tuple[int, int] | None = None
        self.rows: list[RowWidget] = []
        self.history = NavigationHistory()
        self._loading = False
        self._anchor: tuple[RowWidget, int] | None = None
        self._pending_scroll: tuple[int, str, bool] | None = None   # seq, alignement, surbrillance
        self.personal = None          # services.personal_data.PersonalData (données personnelles)
        self._marker_shown: int | None = None   # repère de lecture affiché pour cette visite

        self._build_header()
        self.area = QScrollArea()
        self.area.setObjectName("ChatArea")
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.vbox = QVBoxLayout(self.container)
        self.vbox.setContentsMargins(0, 12, 0, 18)
        self.vbox.setSpacing(0)
        self.vbox.addStretch(1)       # pousse les messages vers le bas s'ils sont peu nombreux
        self.area.setWidget(self.container)

        self.empty = QLabel("Sélectionnez une conversation dans la liste de gauche.", alignment=Qt.AlignCenter)
        self.empty.setObjectName("EmptyState")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        self.find_bar = FindBar(self.engine)
        self.find_bar.current_seq_provider = self.first_visible_seq
        self.find_bar.navigate.connect(lambda seq, terms: self.jump_to_seq(seq, highlight=True, remember=False))
        self.find_bar.terms_changed.connect(self.set_highlight_terms)
        self.find_bar.advanced_requested.connect(
            lambda text: self.conv and self.advanced_search_requested.emit(text, self.conv.id))
        lay.addWidget(self.find_bar)
        lay.addWidget(self.area, 1)
        lay.addWidget(self.empty, 1)
        self.area.hide()
        self.header.hide()

        sb = self.area.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll)
        sb.rangeChanged.connect(self._on_range)
        self._save_timer = QTimer(self, singleShot=True, interval=600, timeout=self._emit_position)
        self._settle_timer = QTimer(self, singleShot=True, timeout=self._end_settle)

    # ------------------------------------------------------------------ #
    # En-tête
    # ------------------------------------------------------------------ #

    def _build_header(self) -> None:
        self.header = QWidget()
        self.header.setObjectName("ChatHeader")
        self.header.setFixedHeight(62)
        self.avatar = QLabel(alignment=Qt.AlignCenter)
        self.avatar.setFixedSize(38, 38)
        self.title = ElidedLabel(objectName="ChatTitle")
        self.subtitle = ElidedLabel()
        self.subtitle.setProperty("role", "caption")
        for lbl in (self.title, self.subtitle):
            lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # n'impose pas de largeur
        tl = QVBoxLayout()
        tl.setSpacing(1)
        tl.addStretch(1)
        tl.addWidget(self.title)
        tl.addWidget(self.subtitle)
        tl.addStretch(1)

        def tool(icon_name: str, tip: str, slot=None, text: str = "") -> QToolButton:
            b = QToolButton(text=text, toolTip=tip)
            b.setAccessibleName(tip.split(" (")[0])
            b.setCursor(Qt.PointingHandCursor)
            icons.bind(b, icon_name, "muted", 18)
            if slot:
                b.clicked.connect(slot)
            return b

        self.date_badge = QToolButton(toolTip="Date affichée — cliquer pour choisir une autre date (Ctrl+G)")
        self.date_badge.setObjectName("DateBadge")
        self.date_badge.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.date_badge.setCursor(Qt.PointingHandCursor)
        icons.bind(self.date_badge, "calendar", "accent", 15, "accent", "accent")
        self.date_badge.clicked.connect(self.choose_date)
        self.back_btn = tool("back", "Revenir à la position précédente (Alt+←)", self.go_back)
        self.back_btn.setEnabled(False)
        self.month_btn = QToolButton(text="Mois", toolTip="Naviguer par année et par mois")
        self.month_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.month_btn.setCursor(Qt.PointingHandCursor)
        icons.bind(self.month_btn, "list", "muted", 16)
        self.month_btn.setPopupMode(QToolButton.InstantPopup)
        self.month_menu = QMenu(self.month_btn)
        self.month_btn.setMenu(self.month_menu)
        self.month_menu.aboutToShow.connect(self._fill_month_menu)
        find = tool("search", "Rechercher dans cette conversation (Ctrl+F)", self.open_find_bar)
        top = tool("first", "Premier message (Ctrl+Début)", self.go_first)
        bottom = tool("last", "Dernier message (Ctrl+Fin)", self.go_last)
        self.info_btn = tool("info", "Afficher / masquer le panneau d'informations (Ctrl+I)", self.toggle_info_panel)
        self.info_btn.setCheckable(True)

        def sep() -> QFrame:
            s = QFrame()
            s.setProperty("separator", True)
            s.setFixedSize(1, 22)
            return s

        h = QHBoxLayout(self.header)
        h.setContentsMargins(18, 0, 12, 0)
        h.setSpacing(4)
        h.addWidget(self.avatar)
        h.addSpacing(8)
        h.addLayout(tl, 1)
        h.addWidget(self.date_badge)
        h.addSpacing(6)
        for w in (self.back_btn, find, self.month_btn, top, bottom):
            h.addWidget(w)
        h.addSpacing(4)
        h.addWidget(sep())
        h.addSpacing(4)
        h.addWidget(self.info_btn)

    def _paint_avatar(self) -> None:
        if not self.conv:
            return
        color = sender_color(None, self.conv.name)
        self.avatar.setText((self.conv.name[:1] or "?").upper())
        self.avatar.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {QColor(color).lighter(112).name()}, "
            f"stop:1 {QColor(color).darker(106).name()}); color: white; border-radius: 19px; "
            f"font-weight: 700; font-size: 12pt;")

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.reload()

    def set_zoom(self, zoom: int) -> None:
        self.zoom = zoom
        self.reload()

    def set_owner(self, owner: str | None) -> None:
        self.owner = owner
        self.reload()

    def open_conversation(self, conv: ConversationSummary | None, seq: int | None = None,
                          highlight: bool = False, align: str = "center") -> None:
        if self.conv and conv and self.conv.id != conv.id:
            self.history.clear()
            if self.find_bar.isVisible():
                self.find_bar.close_bar()
        self.conv = conv
        self._update_back()
        if conv is None:
            self._clear()
            self.area.hide()
            self.header.hide()
            self.empty.show()
            return
        self.empty.hide()
        self.area.show()
        self.header.show()
        self.bounds = self.repo.seq_bounds(conv.id)
        if self.personal is not None and (not self.rows or self.rows[0].msg.conversation_id != conv.id
                                          or getattr(self, "_marker_conv", None) != conv.id):
            self._marker_conv = conv.id
            self._marker_shown = self._visible_marker(conv.id)
        n_part = len(self.repo.participants(conv.id))
        self.title.setText(conv.name)
        self._paint_avatar()
        self.subtitle.setText(f"{plural(conv.message_count, 'message')} · {plural(n_part, 'participant')} · "
                              f"{period(conv.first_date, conv.last_date)}")
        if self.bounds is None:
            self._clear()
            return
        if seq is None:
            self._load_last()
        else:
            self.load_around(seq, highlight=highlight, align=align)

    def open_find_bar(self) -> None:
        if self.conv:
            self.find_bar.open_bar(self.conv.id)

    def set_highlight_terms(self, terms: list[str]) -> None:
        """Surligne ces termes dans les bulles (liste vide : aucun surlignage)."""
        if terms == self.terms:
            return
        self.terms = list(terms)
        if self.conv and self.rows:
            self.reload()

    def reload(self) -> None:
        if self.conv is None:
            return
        self.open_conversation(self.conv, self.first_visible_seq(), align="top")

    def current_location(self) -> Location | None:
        seq = self.first_visible_seq()
        return Location(self.conv.id, seq) if (self.conv and seq is not None) else None

    def jump_to_seq(self, seq: int, highlight: bool = True, remember: bool = True) -> None:
        if self.conv is None:
            return
        if remember:
            self.history.push(self.current_location())
            self._update_back()
        if self._row_for(seq) is not None:
            self._schedule_scroll(seq, "center", highlight)
        else:
            self.load_around(seq, highlight=highlight)

    def go_back(self) -> None:
        loc = self.history.pop()
        self._update_back()
        if loc and self.conv and loc.conversation_id == self.conv.id:
            self.jump_to_seq(loc.seq, highlight=False, remember=False)

    def go_first(self) -> None:
        if self.bounds:
            self.history.push(self.current_location())
            self._update_back()
            self.load_around(self.bounds[0], align="top")

    def go_last(self) -> None:
        if self.bounds:
            self.history.push(self.current_location())
            self._update_back()
            self._load_last()

    def choose_date(self) -> None:
        if not self.conv:
            return
        days = self.repo.days_with_messages(self.conv.id)
        row = self._first_visible_row()
        dlg = DateDialog(days, row.msg.day if row else None, self)
        if dlg.exec() == QDialog.Accepted:
            self.go_to_day(dlg.selected_day())

    def step_day(self, step: int, unit: str = "day") -> None:
        """Jour (ou mois) précédent / suivant contenant des messages."""
        if not self.conv:
            return
        row = self._first_visible_row()
        current = row.msg.day if row else None
        target = neighbour_day(self.repo.days_with_messages(self.conv.id), current, step, unit)
        if target:
            self.go_to_day(target)

    def go_to_day(self, day: str) -> None:
        if not self.conv:
            return
        seq = self.repo.seq_for_day(self.conv.id, day)
        if seq is not None:
            self.history.push(self.current_location())
            self._update_back()
            self.load_around(seq, align="top", highlight=True)

    # ------------------------------------------------------------------ #
    # Chargement
    # ------------------------------------------------------------------ #

    def _ctx(self) -> RenderContext:
        f = QFont(self.font())
        f.setPointSizeF(max(self.font().pointSizeF(), 9) * self.zoom / 100)
        return RenderContext(
            theme=self.theme, owner=self.owner, font=f, bubble_max_width=self._bubble_width(),
            on_reply=self._on_reply, on_photo=self._on_photo, on_video=self._on_video, on_link=open_url,
            terms=self.terms,
            on_action=(lambda action, msg: self.personal_action.emit(action, msg)) if self.personal else None,
            collections=[(c.id, c.name) for c in self.personal.collections()] if self.personal else [],
            read_marker=self._marker_shown)

    def _bubble_width(self) -> int:
        vw = self.area.viewport().width() if self.area.isVisible() else 900
        vw = min(vw, READING_MAX)
        return max(260, min(int(620 * self.zoom / 100), int(vw * 0.74)))

    def _clear(self) -> None:
        for r in self.rows:
            self._discard(r)
        self.rows.clear()
        self._anchor = None

    def _discard(self, r: RowWidget) -> None:
        self.vbox.removeWidget(r)
        r.hide()
        r.deleteLater()

    def _insert_rows(self, msgs: list[MessageRow], at_top: bool) -> None:
        ctx = self._ctx()
        self.container.setFont(ctx.font)
        new_rows = [make_row(m, ctx) for m in msgs]
        if at_top:
            for i, r in enumerate(new_rows):
                self.vbox.insertWidget(1 + i, r)      # après l'espace extensible
            self.rows[:0] = new_rows
        else:
            base = 1 + len(self.rows)
            for i, r in enumerate(new_rows):
                self.vbox.insertWidget(base + i, r)
            self.rows.extend(new_rows)

    def load_around(self, seq: int, highlight: bool = False, align: str = "center") -> None:
        conv_id = self.conv.id
        self._loading = True
        self._clear()
        before = self.repo.messages_before(conv_id, seq, PAGE)
        rest = self.repo.messages_after(conv_id, seq - 1, PAGE)
        self._insert_rows(before + rest, at_top=False)
        self._loading = False
        self._schedule_scroll(seq, align, highlight)

    def _load_last(self) -> None:
        conv_id = self.conv.id
        self._loading = True
        self._clear()
        msgs = self.repo.messages_before(conv_id, self.bounds[1] + 1, PAGE * 2)
        self._insert_rows(msgs, at_top=False)
        self._loading = False
        self._schedule_scroll(self.bounds[1], "bottom", False)

    def _load_more_top(self) -> None:
        if self._loading or not self.rows or self.rows[0].seq <= self.bounds[0]:
            return
        self._loading = True
        self._set_anchor()
        msgs = self.repo.messages_before(self.conv.id, self.rows[0].seq, PAGE)
        self._insert_rows(msgs, at_top=True)
        # Libère les lignes du bas (sans effet sur la position visible)
        while len(self.rows) > MAX_ROWS:
            self._discard(self.rows.pop())
        self._loading = False
        QTimer.singleShot(0, self._restore_anchor)

    def _load_more_bottom(self) -> None:
        if self._loading or not self.rows or self.rows[-1].seq >= self.bounds[1]:
            return
        self._loading = True
        self._set_anchor()
        msgs = self.repo.messages_after(self.conv.id, self.rows[-1].seq, PAGE)
        self._insert_rows(msgs, at_top=False)
        anchor_row = self._anchor[0] if self._anchor else None
        while len(self.rows) > MAX_ROWS and self.rows[0] is not anchor_row:
            self._discard(self.rows.pop(0))
        self._loading = False
        QTimer.singleShot(0, self._restore_anchor)

    # ------------------------------------------------------------------ #
    # Défilement
    # ------------------------------------------------------------------ #

    def _set_anchor(self) -> None:
        row = self._first_visible_row()
        if row is not None:
            self._anchor = (row, row.y() - self.area.verticalScrollBar().value())

    def _restore_anchor(self) -> None:
        if not self._anchor:
            return
        row, offset = self._anchor
        self.container.layout().activate()
        try:
            self.area.verticalScrollBar().setValue(row.y() - offset)
        except RuntimeError:
            pass
        self._anchor = None

    def _on_range(self, _min: int, _max: int) -> None:
        if self._anchor:
            self._restore_anchor()
        elif self._pending_scroll:
            self._apply_pending_scroll()

    def _schedule_scroll(self, seq: int, align: str, highlight: bool) -> None:
        """Positionne la vue sur `seq`. La position est réappliquée à chaque
        changement de hauteur du contenu pendant SETTLE_MS (mise en page des
        retours à la ligne, chargement des images), puis la vue est libérée."""
        self._pending_scroll = (seq, align, highlight)
        self._settle_timer.start(SETTLE_MS)
        QTimer.singleShot(0, self._apply_pending_scroll)

    def _apply_pending_scroll(self) -> None:
        if not self._pending_scroll:
            return
        seq, align, highlight = self._pending_scroll
        self.container.layout().activate()
        row = self._row_for(seq)
        if row is None and self.rows:
            row = min(self.rows, key=lambda r: abs(r.seq - seq))
        if row is not None:
            self._scroll_to_row(row, align)
            if highlight:
                row.flash()
                self._pending_scroll = (seq, align, False)
        self._update_date_badge()

    def _end_settle(self) -> None:
        self._apply_pending_scroll()
        self._pending_scroll = None
        self._update_date_badge()

    def _scroll_to_row(self, row: RowWidget, align: str) -> None:
        sb = self.area.verticalScrollBar()
        vh = self.area.viewport().height()
        if align == "bottom":
            sb.setValue(sb.maximum())
        elif align == "top":
            sb.setValue(max(row.y() - TOP_MARGIN, 0))
        else:
            sb.setValue(max(row.y() - (vh - row.height()) // 2, 0))

    def _on_scroll(self, value: int) -> None:
        self._update_date_badge()
        self._save_timer.start()
        if self._loading or self._pending_scroll or not self.rows:
            return
        sb = self.area.verticalScrollBar()
        if value < EDGE_PX:
            QTimer.singleShot(0, self._load_more_top)
        elif sb.maximum() - value < EDGE_PX:
            QTimer.singleShot(0, self._load_more_bottom)

    def _first_visible_row(self) -> RowWidget | None:
        if not self.rows:
            return None
        top = self.area.verticalScrollBar().value() + TOP_MARGIN
        lo, hi = 0, len(self.rows) - 1
        while lo < hi:      # recherche dichotomique sur la position verticale
            mid = (lo + hi) // 2
            r = self.rows[mid]
            if r.y() + r.height() <= top:
                lo = mid + 1
            else:
                hi = mid
        return self.rows[lo]

    def first_visible_seq(self) -> int | None:
        r = self._first_visible_row()
        return r.seq if r else None

    def _row_for(self, seq: int) -> RowWidget | None:
        return next((r for r in self.rows if r.seq == seq), None)

    def _update_date_badge(self) -> None:
        row = self._first_visible_row()
        day = row.msg.day if row else None
        self.date_badge.setText(day_long(day) if day else "Aller à la date")
        self.date_badge.setToolTip(f"{self.date_badge.text()} — cliquer pour choisir une autre date (Ctrl+G)")
        if day and day != getattr(self, "_last_day", None):
            self._last_day = day
            self.day_changed.emit(day)

    def _emit_position(self) -> None:
        seq = self.first_visible_seq()
        if self.conv and seq is not None:
            self.position_changed.emit(self.conv.id, seq)
        self._advance_read_marker()

    # ------------------------------------------------------------------ #
    # Suivi de lecture (local à Telegramor)
    # ------------------------------------------------------------------ #

    def _visible_marker(self, conv_id: str) -> int | None:
        """Repère à afficher : dernier message lu, sauf s'il est le dernier de la conversation."""
        mid = self.personal.read_marker(conv_id)
        if mid is None or self.bounds is None:
            return None
        seq = self.repo.seq_of_message(conv_id, mid)
        if seq is None or not self.repo.messages_after(conv_id, seq, 1):
            return None
        return mid

    def _last_visible_row(self) -> RowWidget | None:
        if not self.rows:
            return None
        bottom = self.area.verticalScrollBar().value() + self.area.viewport().height() - 8
        candidates = [r for r in self.rows if r.y() <= bottom]
        return candidates[-1] if candidates else None

    def _advance_read_marker(self) -> None:
        if self.personal is None or not self.conv or self._pending_scroll:
            return
        row = self._last_visible_row()
        while row is not None and row.msg.kind != "default":
            i = self.rows.index(row)
            row = self.rows[i - 1] if i > 0 else None
        if row is not None:
            self.personal.advance_read_marker(self.conv.id, row.msg.message_id, row.seq)

    def resume_reading(self) -> bool:
        """Va au premier message non consulté (après le repère de lecture)."""
        if self.personal is None or not self.conv:
            return False
        mid = self.personal.read_marker(self.conv.id)
        seq = self.repo.seq_of_message(self.conv.id, mid) if mid is not None else None
        if seq is None:
            return False
        nxt = self.repo.messages_after(self.conv.id, seq, 1)
        self.jump_to_seq(nxt[0].seq if nxt else seq, highlight=True)
        return True

    def mark_read_until(self, msg: MessageRow) -> None:
        if self.personal is not None:
            self.personal.set_read_marker(msg.conversation_id, msg.message_id)

    def reset_reading(self) -> None:
        if self.personal is not None and self.conv:
            self.personal.clear_read_marker(self.conv.id)
            self._marker_shown = None
            self.reload()

    def _update_back(self) -> None:
        self.back_btn.setEnabled(self.history.can_go_back())

    def _fill_month_menu(self) -> None:
        self.month_menu.clear()
        if not self.conv:
            return
        by_year: dict[str, list[tuple[str, int]]] = {}
        for ym, n in self.repo.month_index(self.conv.id):
            by_year.setdefault(ym[:4], []).append((ym, n))
        for year, months in by_year.items():
            sub = self.month_menu.addMenu(f"{year}  ({sum(n for _, n in months)})")
            for ym, n in months:
                sub.addAction(f"{month_label(ym).capitalize()}  —  {plural(n, 'message')}",
                              lambda ym=ym: self.go_to_day(ym + "-01"))

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        # Colonne de lecture centrée sur les grands écrans (lignes de longueur confortable)
        vw = self.area.viewport().width()
        side = max(0, (vw - READING_MAX) // 2)
        self.vbox.setContentsMargins(side, 12, side, 18)
        # En-tête compact : date et « Mois » réduits à leur pictogramme (texte en info-bulle)
        compact = self.width() < 820
        style = Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextBesideIcon
        for b in (self.date_badge, self.month_btn):
            if b.toolButtonStyle() != style:
                b.setToolButtonStyle(style)
        w = self._bubble_width()
        for r in self.rows:
            r.set_bubble_width(w)

    # ------------------------------------------------------------------ #
    # Actions sur les messages
    # ------------------------------------------------------------------ #

    def _on_reply(self, msg: MessageRow) -> None:
        target = msg.reply.seq if msg.reply else None
        if target is None and msg.reply_to_message_id is not None and self.conv:
            target = self.repo.seq_of_message(self.conv.id, msg.reply_to_message_id)
        if target is not None:
            self.jump_to_seq(target, highlight=True)

    def _on_photo(self, media: MediaRow) -> None:
        items = self.repo.medias(self.conv.id, ("photo",)) if self.conv else [media]
        idx = next((i for i, m in enumerate(items) if m.id == media.id), 0)
        if not items:
            items = [media]
        ImageViewer(items, idx, self.window()).exec()

    def _on_video(self, media: MediaRow) -> None:
        if media.abs_file is not None:
            play_video(media.abs_file, self.window(), self.internal_video)
