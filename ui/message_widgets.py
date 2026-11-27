"""Widgets élémentaires d'affichage d'un message : bulle, médias, réactions, citations."""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPixmap, QTextDocument,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy, QVBoxLayout, QWidget,
)

from app import design, icons
from app.design import name_color, sender_color
from app.styles import Theme
from database.models import MediaRow, MessageRow
from database.repositories import media_label
from database.search_engine import highlight_html
from services.media_service import ThumbnailLoader, human_size, open_with_system, show_in_folder

from .formatting import day_long, full_datetime, soft_wrap_html, time_hm


@dataclass
class RenderContext:
    theme: Theme
    owner: str | None
    font: QFont
    bubble_max_width: int
    on_reply: Callable[[MessageRow], None]
    on_photo: Callable[[MediaRow], None]
    on_video: Callable[[MediaRow], None]
    on_link: Callable[[str], None]
    terms: list[str] = field(default_factory=list)   # termes recherchés à surligner

    @property
    def scale(self) -> float:
        return self.font.pointSizeF() / 10.0


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def small_font(base: QFont, factor: float = 0.82) -> QFont:
    f = QFont(base)
    f.setPointSizeF(max(base.pointSizeF() * factor, 6))
    return f


# --------------------------------------------------------------------------- #
# Images asynchrones
# --------------------------------------------------------------------------- #

class AsyncImage(QLabel):
    """Image chargée en arrière-plan ; affiche un fond neutre en attendant."""

    clicked = Signal()
    RADIUS = 10

    def __init__(self, path: Path | None, box: QSize, placeholder: QSize | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.box = box
        self._key: str | None = None
        self.failed = False
        self.setFixedSize(placeholder or QSize(box.width(), int(box.width() * 0.66)))
        self.setStyleSheet(f"background: {design.current().panel}; border-radius: {self.RADIUS}px;")
        if path is not None:
            loader = ThumbnailLoader.instance()
            self._key, pm = loader.request(path, box)
            if pm is not None:
                self._apply(pm)
            else:
                loader.loaded.connect(self._on_loaded)

    def _on_loaded(self, key: str, pm: QPixmap) -> None:
        if key != self._key:
            return
        try:
            ThumbnailLoader.instance().loaded.disconnect(self._on_loaded)
        except (RuntimeError, TypeError):
            pass
        if pm.isNull():
            self.failed = True
            self.setText("Image illisible")
            return
        self._apply(pm)

    def _apply(self, pm: QPixmap) -> None:
        if pm.width() > self.box.width() or pm.height() > self.box.height():
            pm = pm.scaled(self.box, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setStyleSheet("")
        self.setFixedSize(pm.size())
        self.setPixmap(rounded(pm, self.RADIUS))

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(e)


def rounded(pm: QPixmap, radius: float) -> QPixmap:
    """Copie de l'image aux coins arrondis."""
    out = QPixmap(pm.size())
    out.setDevicePixelRatio(pm.devicePixelRatio())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    ratio = pm.devicePixelRatio()
    path.addRoundedRect(QRectF(0, 0, pm.width() / ratio, pm.height() / ratio), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


class VideoThumb(AsyncImage):
    """Miniature vidéo avec bouton lecture et durée superposés."""

    def __init__(self, path: Path | None, box: QSize, placeholder: QSize, badge: str, note: str = "",
                 parent=None) -> None:
        self.badge, self.note = badge, note
        super().__init__(path, box, placeholder, parent)
        if path is None:
            self.setStyleSheet(f"background: #1C2636; border-radius: {self.RADIUS}px;")

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        d = min(56, r.height() // 2)
        c = QRect(r.center().x() - d // 2, r.center().y() - d // 2, d, d)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 16, 28, 150))
        p.drawEllipse(c)
        p.setBrush(QColor("white"))
        tri = [QPoint(c.left() + d * 0.38, c.top() + d * 0.28), QPoint(c.left() + d * 0.38, c.bottom() - d * 0.28),
               QPoint(c.right() - d * 0.26, c.center().y())]
        p.drawPolygon(tri)
        f = small_font(self.font(), 0.9)
        p.setFont(f)
        fm = QFontMetrics(f)
        for text, y in ((self.badge, 6), (self.note, None)):
            if not text:
                continue
            w = fm.horizontalAdvance(text) + 12
            rect = QRect(8, y + 2 if y is not None else r.bottom() - fm.height() - 10, w, fm.height() + 4)
            p.setBrush(QColor(10, 16, 28, 165))
            p.drawRoundedRect(rect, 7, 7)
            p.setPen(QColor("white"))
            p.drawText(rect, Qt.AlignCenter, text)
            p.setPen(Qt.NoPen)
        p.end()


# --------------------------------------------------------------------------- #
# Cartes
# --------------------------------------------------------------------------- #

class ClickableFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(e)


def missing_widget(label: str, path: str | None) -> QWidget:
    """Indication explicite d'un fichier absent de l'export (jamais masquée)."""
    w = QFrame()
    w.setObjectName("Missing")
    w.setToolTip("Le fichier référencé par l'export n'existe pas à cet emplacement.")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(10, 8, 12, 8)
    lay.setSpacing(10)
    ic = QLabel()
    ic.setPixmap(icons.pixmap("alert", design.current().danger, 18))
    lay.addWidget(ic, 0, Qt.AlignTop)
    txt = QLabel(f"<b>{escape(label)} introuvable</b>" + (f"<br><small>{escape(path)}</small>" if path else ""))
    txt.setTextFormat(Qt.RichText)
    txt.setWordWrap(True)
    txt.setStyleSheet(f"color: {design.current().danger}; background: transparent; border: none;")
    lay.addWidget(txt, 1)
    return w


ICONS = {
    "voice": "🎤", "audio": "🎵", "file": "📎", "video_message": "📹", "location": "📍",
    "contact": "👤", "call": "📞", "poll": "📊", "game": "🎮", "invoice": "🧾", "unknown": "❔",
    "photo": "🖼", "video": "🎬", "animation": "🎞", "sticker": "🙂",
}


def file_card(m: MediaRow, ctx: RenderContext) -> QWidget:
    card = ClickableFrame()
    card.setObjectName("FileCard")
    lay = QHBoxLayout(card)
    lay.setContentsMargins(8, 8, 12, 8)
    lay.setSpacing(10)
    t = design.current()
    missing = bool(m.file_path and not m.not_included and not m.file_available)
    icon = QLabel()
    icon.setObjectName("FileIcon")
    icon.setProperty("missing", missing)
    side = int(40 * ctx.scale)
    icon.setFixedSize(side, side)
    icon.setAlignment(Qt.AlignCenter)
    icon.setPixmap(icons.pixmap("alert" if missing else icons.MEDIA_ICONS.get(m.media_type, "file"),
                                t.danger if missing else t.accent, int(20 * ctx.scale)))
    lay.addWidget(icon, 0, Qt.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(1)
    title = m.title or (Path(m.file_path).name if m.file_path else media_label(m.media_type) or "Fichier")
    title_lbl = QLabel(f"<b>{escape(title)}</b>")
    title_lbl.setWordWrap(True)
    col.addWidget(title_lbl)
    details = [x for x in (m.description, m.status) if x]
    if m.file_available and m.abs_file is not None:
        details.append(human_size(m.abs_file.stat().st_size))
    sub = QLabel(" · ".join(details))
    sub.setFont(small_font(ctx.font))
    sub.setProperty("muted", True)
    sub.setWordWrap(True)
    col.addWidget(sub)
    lay.addLayout(col, 1)
    if m.file_path and not m.not_included:
        if m.file_available:
            card.setCursor(Qt.PointingHandCursor)
            card.setToolTip(f"Ouvrir avec l'application du système\n{m.file_path}")
            card.clicked.connect(lambda: open_with_system(m.abs_file))
        else:
            warn = QLabel(f"Fichier introuvable : {escape(m.file_path)}")
            warn.setStyleSheet(f"color: {ctx.theme.missing};")
            warn.setFont(small_font(ctx.font))
            warn.setWordWrap(True)
            col.addWidget(warn)
    elif m.not_included:
        note = QLabel("Non inclus dans l'export")
        note.setFont(small_font(ctx.font))
        note.setProperty("muted", True)
        col.addWidget(note)
    return card


def media_widget(m: MediaRow, ctx: RenderContext) -> QWidget:
    s = ctx.scale
    if m.media_type in ("photo", "sticker"):
        box = QSize(int(340 * s), int(340 * s)) if m.media_type == "photo" else QSize(int(170 * s), int(170 * s))
        src = m.abs_thumbnail if m.thumbnail_available else (m.abs_file if m.file_available else None)
        if src is None:
            return missing_widget("Photo" if m.media_type == "photo" else "Autocollant", m.file_path or m.thumbnail_path)
        ph = _placeholder(m, box)
        img = AsyncImage(src, box, ph)
        tip = m.file_path or ""
        if not m.file_available:
            tip += "\n⚠ original introuvable (miniature affichée)"
        img.setToolTip(tip.strip())
        img.clicked.connect(lambda: ctx.on_photo(m))
        return img
    if m.media_type in ("video", "animation", "video_message"):
        box = QSize(int(340 * s), int(300 * s))
        thumb = m.abs_thumbnail if m.thumbnail_available else None
        note = ""
        if not m.file_available:
            note = "⚠ vidéo introuvable" if m.file_path else "non incluse"
        elif thumb is None:
            note = "miniature introuvable"
        badge = "GIF" if m.media_type == "animation" else (m.duration_raw or "")
        w = VideoThumb(thumb, box, _placeholder(m, box, QSize(int(260 * s), int(146 * s))), badge, note)
        w.setToolTip((m.file_path or "") + ("" if m.file_available else "\n⚠ fichier introuvable"))
        if m.file_available:
            w.clicked.connect(lambda: ctx.on_video(m))
        else:
            w.setCursor(Qt.ArrowCursor)
        if m.media_type == "video_message" and not m.file_available and not thumb:
            return file_card(m, ctx)
        return w
    return file_card(m, ctx)


def _placeholder(m: MediaRow, box: QSize, default: QSize | None = None) -> QSize:
    if m.thumb_width and m.thumb_height:
        sz = QSize(m.thumb_width, m.thumb_height)
        if sz.width() > box.width() or sz.height() > box.height():
            sz = sz.scaled(box, Qt.KeepAspectRatio)
        return sz
    return default or QSize(box.width(), int(box.width() * 0.66))


# --------------------------------------------------------------------------- #
# Lignes de la conversation
# --------------------------------------------------------------------------- #

class RowWidget(QWidget):
    """Ligne de la vue des messages (séparateur, événement ou message)."""

    def __init__(self, msg: MessageRow, parent=None) -> None:
        super().__init__(parent)
        self.msg = msg
        self.seq = msg.seq
        self.highlight_target: QWidget = self

    def flash(self, ms: int = 2500) -> None:
        t = self.highlight_target
        t.setProperty("highlighted", True)
        repolish(t)

        def off() -> None:
            try:
                t.setProperty("highlighted", False)
                repolish(t)
            except RuntimeError:  # widget détruit entre-temps
                pass
        QTimer.singleShot(ms, off)

    def set_bubble_width(self, w: int) -> None:
        pass


class PillRow(RowWidget):
    """Séparateur de date ou événement système, centré."""

    def __init__(self, msg: MessageRow, ctx: RenderContext, parent=None) -> None:
        super().__init__(msg, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 12, 24, 10)
        lay.setSpacing(12)
        if msg.kind == "date_separator":
            text = day_long(msg.separator_date) if msg.separator_date else (msg.service_text or "")
        else:
            text = msg.service_text or msg.text
        pill = QLabel(escape(text[:1].upper() + text[1:]) if msg.kind == "date_separator" else escape(text))
        pill.setObjectName("Pill")
        pill.setProperty("service", msg.kind == "service")
        pill.setWordWrap(msg.kind == "service")
        pill.setAlignment(Qt.AlignCenter)
        pill.setFont(small_font(ctx.font, 0.9))
        pill.setMaximumWidth(ctx.bubble_max_width)
        if msg.kind == "service":
            pill.setToolTip(full_datetime(msg.date_local) or "Événement")
            if msg.reply_to_message_id is not None:
                pill.setCursor(Qt.PointingHandCursor)
                pill.mouseReleaseEvent = lambda e: ctx.on_reply(msg)  # type: ignore[assignment]
        if msg.kind == "date_separator":
            for side in (0, 1):
                rule = QFrame()
                rule.setObjectName("DayRule")
                rule.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                if side == 0:
                    lay.addWidget(rule, 1)
                    lay.addWidget(pill)
                else:
                    lay.addWidget(rule, 1)
        else:
            lay.addStretch(1)
            lay.addWidget(pill)
            lay.addStretch(1)
        self.highlight_target = pill
        self.pill = pill

    def set_bubble_width(self, w: int) -> None:
        self.pill.setMaximumWidth(w)


class MessageBubbleRow(RowWidget):
    AVATAR = 34

    def __init__(self, msg: MessageRow, ctx: RenderContext, parent=None) -> None:
        super().__init__(msg, parent)
        self.ctx = ctx
        outgoing = bool(ctx.owner and msg.sender == ctx.owner)
        color = sender_color(msg.sender_userpic, msg.sender)
        av_size = int(self.AVATAR * ctx.scale)

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 2 if msg.is_joined else 8, 20, 1)
        row.setSpacing(10)

        # Avatar (messages reçus, premier d'un groupe)
        avatar = QLabel()
        avatar.setFixedSize(av_size, av_size)
        if not outgoing and not msg.is_joined:
            avatar.setText((msg.sender_initials or (msg.sender or "?")[:1]).upper())
            avatar.setAlignment(Qt.AlignCenter)
            c0, c1 = QColor(color).lighter(112).name(), QColor(color).darker(106).name()
            avatar.setStyleSheet(f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c0}, stop:1 {c1});"
                                 f" color: white; border-radius: {av_size // 2}px; font-weight: bold;")
            avatar.setToolTip(msg.sender or "")

        bubble = QFrame()
        bubble.setObjectName("Bubble")
        bubble.setProperty("outgoing", outgoing)
        bubble.setMaximumWidth(ctx.bubble_max_width)
        bubble.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        bubble.setContextMenuPolicy(Qt.CustomContextMenu)
        bubble.customContextMenuRequested.connect(self._menu)
        self.bubble = bubble
        self.highlight_target = bubble

        col = QVBoxLayout(bubble)
        col.setContentsMargins(13, 9, 13, 7)
        col.setSpacing(6)

        if not outgoing and not msg.is_joined and msg.sender:
            name = QLabel(f"{escape(msg.sender)}"
                          + (f" <span style='color:{ctx.theme.muted}; font-weight:normal'>via "
                             f"{escape(msg.via_bot)}</span>" if msg.via_bot else ""))
            name.setObjectName("SenderName")
            name.setFont(small_font(ctx.font, 0.94))
            name.setStyleSheet(f"color: {name_color(msg.sender_userpic, msg.sender, ctx.theme)};")
            col.addWidget(name)

        if msg.forwarded_from:
            fw = QLabel(f"↪ Transféré de <b>{escape(msg.forwarded_from)}</b>")
            fw.setObjectName("Forwarded")
            fw.setFont(small_font(ctx.font, 0.9))
            col.addWidget(fw)

        if msg.reply is not None:
            col.addWidget(self._quote(msg))

        for m in msg.media:
            col.addWidget(media_widget(m, ctx))

        self.text_label: QLabel | None = None
        self._text_ideal = 0
        if msg.text:
            self.text_label = self._text_label(msg)
            col.addWidget(self.text_label)
            self._fit_text(ctx.bubble_max_width)

        # Pied : réactions + heure
        foot = QHBoxLayout()
        foot.setSpacing(4)
        for r in msg.reactions:
            chip = QLabel()
            chip.setObjectName("ReactionChip")
            chip.setProperty("active", r.active)
            if r.is_custom_emoji and r.abs_image and r.abs_image.is_file():
                chip.setText(f"<img src='{escape(str(r.abs_image))}' height='16'> {r.count}")
            else:
                chip.setText(escape(r.emoji) + (f" {r.count}" if r.count > 1 else ""))
            chip.setToolTip(", ".join(r.users) if r.users else f"{r.count} réaction(s)")
            foot.addWidget(chip)
        foot.addStretch(1)
        meta_txt = ("modifié " if msg.edited_raw else "") + time_hm(msg.date_local)
        if msg.signature:
            meta_txt = f"{msg.signature} · {meta_txt}"
        meta = QLabel(meta_txt)
        meta.setObjectName("BubbleMeta")
        meta.setFont(small_font(ctx.font, 0.78))
        meta.setToolTip(f"{full_datetime(msg.date_local)}\nArchive : {msg.archive_name}"
                        + (f"\n{msg.edited_raw}" if msg.edited_raw else ""))
        foot.addWidget(meta)
        col.addLayout(foot)

        if outgoing:
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(avatar, 0, Qt.AlignTop)
            row.addWidget(bubble)
            row.addStretch(1)

    def set_bubble_width(self, w: int) -> None:
        self.bubble.setMaximumWidth(w)
        self._fit_text(w)

    def _fit_text(self, bubble_w: int) -> None:
        # QLabel replie trop tôt le texte dans une mise en page « Maximum » :
        # on lui impose la largeur naturelle du texte, plafonnée à celle de la bulle.
        if self.text_label is not None:
            self.text_label.setMinimumWidth(min(self._text_ideal, bubble_w - 24))

    def _text_label(self, msg: MessageRow) -> QLabel:
        lbl = QLabel()
        lbl.setObjectName("BubbleText")
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.RichText)
        html = msg.html if msg.html else escape(msg.text).replace("\n", "<br>")
        link_color = self.ctx.theme.accent
        if self.ctx.terms:
            html = highlight_html(html, self.ctx.terms,
                                  f"<span style='background-color:{self.ctx.theme.highlight}'>")
        content = (f"<style>a {{ color: {link_color}; text-decoration: none; }}</style>"
                   f"<div style='line-height:138%'>{soft_wrap_html(html)}</div>")
        lbl.setText(content)
        doc = QTextDocument()
        doc.setDefaultFont(self.ctx.font)
        doc.setDocumentMargin(0)
        doc.setHtml(content)
        self._text_ideal = int(doc.idealWidth()) + 4
        lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lbl.setOpenExternalLinks(False)
        lbl.linkActivated.connect(self._on_link)
        lbl.setContextMenuPolicy(Qt.NoContextMenu)   # menu de la bulle
        lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        return lbl

    def _quote(self, msg: MessageRow) -> QWidget:
        rep = msg.reply
        q = ClickableFrame()
        q.setObjectName("Quote")
        lay = QVBoxLayout(q)
        lay.setContentsMargins(10, 5, 10, 6)
        lay.setSpacing(1)
        who = QLabel(f"<b>{escape(rep.sender or 'Message cité')}</b>")
        who.setStyleSheet(f"color: {self.ctx.theme.accent_text};")
        who.setFont(small_font(self.ctx.font, 0.9))
        excerpt = (rep.text or media_label(rep.media_type) or "").replace("\n", " ")
        fm = QFontMetrics(small_font(self.ctx.font, 0.9))
        ex = QLabel(fm.elidedText(excerpt, Qt.ElideRight, int(self.ctx.bubble_max_width * 0.8)))
        ex.setFont(small_font(self.ctx.font, 0.9))
        ex.setProperty("muted", True)
        lay.addWidget(who)
        lay.addWidget(ex)
        if rep.seq is not None:
            q.setCursor(Qt.PointingHandCursor)
            q.setToolTip("Aller au message d'origine")
            q.clicked.connect(lambda: self.ctx.on_reply(msg))
        else:
            q.setToolTip("Message d'origine absent de la bibliothèque")
        return q

    def _on_link(self, url: str) -> None:
        if url.startswith("#go_to_message"):
            return
        self.ctx.on_link(url)

    def _menu(self, pos) -> None:
        msg = self.msg
        menu = QMenu(self)
        clip = QGuiApplication.clipboard()
        if msg.text:
            menu.addAction("Copier le texte", lambda: clip.setText(msg.text))
        for url in msg.links[:5]:
            short = url if len(url) < 50 else url[:47] + "…"
            menu.addAction(f"Copier le lien  {short}", lambda u=url: clip.setText(u))
            menu.addAction(f"Ouvrir le lien  {short}", lambda u=url: self.ctx.on_link(u))
        menu.addAction("Copier la date et l'heure", lambda: clip.setText(full_datetime(msg.date_local)))
        if msg.reply is not None and msg.reply.seq is not None:
            menu.addAction("Aller au message cité", lambda: self.ctx.on_reply(msg))
        for m in msg.media:
            if m.file_available:
                menu.addSeparator()
                label = media_label(m.media_type) or "fichier"
                menu.addAction(f"Ouvrir ({label}) avec l'application système", lambda p=m.abs_file: open_with_system(p))
                menu.addAction("Afficher dans le dossier", lambda p=m.abs_file: show_in_folder(p))
                menu.addAction("Copier le chemin du fichier", lambda p=m.abs_file: clip.setText(str(p)))
        menu.addSeparator()
        info = menu.addAction(f"Message n° {msg.message_id} · {msg.archive_name}")
        info.setEnabled(False)
        menu.exec(self.bubble.mapToGlobal(pos))


def make_row(msg: MessageRow, ctx: RenderContext) -> RowWidget:
    if msg.kind in ("date_separator", "service"):
        return PillRow(msg, ctx)
    return MessageBubbleRow(msg, ctx)
