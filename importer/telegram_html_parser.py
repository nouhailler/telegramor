"""Parseur des exports HTML de Telegram Desktop.

Principes :
- lecture seule : les fichiers d'export ne sont jamais modifiés ;
- aucune exécution de JavaScript : seuls les éléments et attributs sont lus ;
- fidélité : chaque bloc `.message` produit un objet `Message`, même s'il
  contient des éléments inconnus (ceux-ci sont signalés, pas ignorés) ;
- les chemins de médias sont repris tels quels (`href` / `src`), jamais
  reconstruits.

Une conversation peut être répartie sur plusieurs fichiers (messages.html,
messages2.html, …). L'état `ParserState` est transmis d'un fichier à l'autre
pour que l'héritage de l'expéditeur des messages `.joined` traverse les
frontières de fichiers.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from .html_sanitizer import html_to_text, is_safe_href, sanitize_children
from .models import Anomaly, Media, MediaType, Message, MessageKind, Reaction

# --------------------------------------------------------------------------- #
# Expressions et tables de correspondance
# --------------------------------------------------------------------------- #

DATE_TITLE_RE = re.compile(
    r"(?P<d>\d{2})\.(?P<m>\d{2})\.(?P<y>\d{4})\s+"
    r"(?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})"
    r"(?:\s+(?P<tz>UTC(?P<sign>[+-])(?P<tzh>\d{2}):(?P<tzm>\d{2})))?"
)
GO_TO_RE = re.compile(r"go_to_message(-?\d+)")
GO_TO_JS_RE = re.compile(r"GoToMessage\((-?\d+)\)")
MESSAGE_ID_RE = re.compile(r"^message(-?\d+)$")
DURATION_RE = re.compile(r"\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b")
STYLE_SIZE_RE = re.compile(r"width:\s*(\d+)px;\s*height:\s*(\d+)px")
RAW_BLOCK_RE = re.compile(r"""<div\s+class=["']message(?:\s[^"']*)?["']""", re.IGNORECASE)

MONTHS_EN = {
    m: i for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"], start=1)
}
SEPARATOR_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$")

# Blocs `.media` génériques (div ou a) → type de média
GENERIC_MEDIA_CLASSES = {
    "media_voice_message": MediaType.VOICE,
    "media_audio_file": MediaType.AUDIO,
    "media_file": MediaType.FILE,
    "media_photo": MediaType.PHOTO,
    "media_video": MediaType.VIDEO,          # affiné plus bas (vidéo ronde)
    "media_location": MediaType.LOCATION,
    "media_live_location": MediaType.LOCATION,
    "media_venue": MediaType.LOCATION,
    "media_contact": MediaType.CONTACT,
    "media_call": MediaType.CALL,
    "media_game": MediaType.GAME,
    "media_invoice": MediaType.INVOICE,
    "media_poll": MediaType.POLL,
}

# Enfants directs connus du `.body` d'un message ordinaire
KNOWN_BODY_CLASSES = {
    "date", "from_name", "text", "media_wrap", "reply_to", "reactions",
    "forwarded", "signature",
}


# --------------------------------------------------------------------------- #
# Fonctions utilitaires
# --------------------------------------------------------------------------- #

def make_conversation_id(name: str) -> str:
    """Identifiant provisoire et déterministe d'une conversation.

    L'export HTML ne contient pas l'identifiant Telegram du chat ; on dérive
    donc un identifiant stable du nom. La détection fine des doublons entre
    archives (étape 4) s'appuiera en plus sur le recouvrement des message_id.
    """
    digest = hashlib.sha1(name.strip().casefold().encode("utf-8")).hexdigest()
    return f"conv-{digest[:12]}"


def parse_duration(raw: str | None) -> int | None:
    if not raw:
        return None
    m = DURATION_RE.search(raw)
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s)


def parse_date_title(title: str) -> tuple[datetime | None, str | None, int | None, str | None]:
    """Analyse l'attribut title d'une date : « 16.12.2025 18:33:18 UTC+01:00 ».

    Retourne (datetime, fuseau, décalage en minutes, reste éventuel du title).
    """
    m = DATE_TITLE_RE.search(title)
    if not m:
        return None, None, None, None
    try:
        naive = datetime(int(m["y"]), int(m["m"]), int(m["d"]),
                         int(m["H"]), int(m["M"]), int(m["S"]))
    except ValueError:
        return None, None, None, None
    tz_label = offset = None
    dt = naive
    if m["tz"]:
        offset = int(m["tzh"]) * 60 + int(m["tzm"])
        if m["sign"] == "-":
            offset = -offset
        tz_label = m["tz"]
        dt = naive.replace(tzinfo=timezone(timedelta(minutes=offset)))
    rest = (title[:m.start()] + " " + title[m.end():]).strip() or None
    return dt, tz_label, offset, rest


def parse_separator_date(text: str) -> date | None:
    m = SEPARATOR_RE.match(text.strip())
    if not m:
        return None
    month = MONTHS_EN.get(m.group(2).lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None


def _classes(tag: Tag) -> list[str]:
    return list(tag.get("class") or [])


def _has_class(tag: Tag, cls: str) -> bool:
    return cls in _classes(tag)


def _child(tag: Tag, cls: str, name: str | None = None) -> Tag | None:
    """Premier enfant DIRECT portant la classe `cls`."""
    for c in tag.find_all(name or True, recursive=False):
        if _has_class(c, cls):
            return c
    return None


def _text(tag: Tag | None) -> str | None:
    if tag is None:
        return None
    t = html_to_text(tag)
    return t or None


def _thumb_size(img: Tag | None) -> tuple[int | None, int | None]:
    if img is None:
        return None, None
    m = STYLE_SIZE_RE.search(img.get("style", ""))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


# --------------------------------------------------------------------------- #
# Résultats de parsing
# --------------------------------------------------------------------------- #

@dataclass
class ParserState:
    """État transmis entre les fichiers successifs d'une même conversation."""

    position: int = 0
    last_sender: str | None = None
    last_initials: str | None = None
    last_userpic: str | None = None
    current_separator: date | None = None


@dataclass
class FileParseResult:
    source_file: str
    conversation_name: str | None
    messages: list[Message] = field(default_factory=list)
    raw_block_count: int = 0           # comptage indépendant sur le texte brut
    dom_block_count: int = 0           # blocs .message trouvés dans le DOM
    pagination_links: list[str] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Parseur
# --------------------------------------------------------------------------- #

class TelegramHtmlParser:
    def __init__(self, html_parser: str | None = None) -> None:
        if html_parser is None:
            try:
                import lxml  # noqa: F401
                html_parser = "lxml"
            except ImportError:  # repli sur le parseur de la bibliothèque standard
                html_parser = "html.parser"
        self.html_parser = html_parser

    # -- API publique ------------------------------------------------------- #

    def parse_file(
        self,
        path: str | Path,
        conversation_id: str | None = None,
        state: ParserState | None = None,
        source_name: str | None = None,
    ) -> FileParseResult:
        path = Path(path)
        raw = path.read_bytes().decode("utf-8", errors="replace")
        return self.parse_html(raw, conversation_id, state, source_name or path.name)

    def parse_html(
        self,
        raw: str,
        conversation_id: str | None = None,
        state: ParserState | None = None,
        source_name: str = "messages.html",
    ) -> FileParseResult:
        state = state or ParserState()
        soup = BeautifulSoup(raw, self.html_parser)

        header = soup.select_one(".page_header .text.bold")
        name = _text(header)
        result = FileParseResult(source_file=source_name, conversation_name=name)
        result.raw_block_count = len(RAW_BLOCK_RE.findall(raw))

        conv_id = conversation_id or make_conversation_id(name or source_name)

        history = soup.select_one(".history")
        if history is None:
            result.anomalies.append(Anomaly(
                "NO_HISTORY", "Aucun bloc .history trouvé : ce fichier n'est pas un export de conversation.",
                source_file=source_name, severity="erreur"))
            return result

        blocks = [d for d in history.find_all("div") if _has_class(d, "message")]
        result.dom_block_count = len(blocks)
        for block in blocks:
            msg = self._parse_block(block, conv_id, source_name, state, result)
            if msg is not None:
                result.messages.append(msg)

        for a in soup.select("a.pagination"):
            href = a.get("href")
            if href:
                result.pagination_links.append(href)
        return result

    # -- Blocs ---------------------------------------------------------------- #

    def _parse_block(self, block: Tag, conv_id: str, src: str,
                     state: ParserState, result: FileParseResult) -> Message | None:
        html_id = block.get("id", "")
        m = MESSAGE_ID_RE.match(html_id)
        if not m:
            result.anomalies.append(Anomaly(
                "BAD_MESSAGE_ID", f"Identifiant de message inattendu : {html_id!r}",
                html_id=html_id or None, source_file=src, severity="erreur"))
            message_id = 0
        else:
            message_id = int(m.group(1))

        is_service = _has_class(block, "service")
        msg = Message(
            html_id=html_id, message_id=message_id, conversation_id=conv_id,
            source_file=src, position=state.position,
            kind=MessageKind.SERVICE if is_service else MessageKind.DEFAULT,
            is_joined=_has_class(block, "joined"),
        )
        state.position += 1

        if is_service:
            self._parse_service(block, msg, state)
        elif _has_class(block, "default"):
            self._parse_default(block, msg, state, result)
        else:
            msg.warnings.append("Type de bloc inconnu : " + " ".join(_classes(block)))
            result.anomalies.append(Anomaly(
                "UNKNOWN_BLOCK", "Bloc .message de type inconnu ("
                + " ".join(_classes(block)) + ")", html_id, src))
            msg.text = html_to_text(block)
        return msg

    def _parse_service(self, block: Tag, msg: Message, state: ParserState) -> None:
        body = _child(block, "body")
        if body is None:
            msg.warnings.append("Message système sans .body")
            return
        text = html_to_text(body)
        msg.service_text = text
        msg.html = sanitize_children(body)
        sep = parse_separator_date(text)
        if sep is not None:
            msg.kind = MessageKind.DATE_SEPARATOR
            msg.separator_date = sep
            state.current_separator = sep
        else:
            msg.text = text
            # ex. « X pinned this message » : lien vers le message concerné
            for a in body.find_all("a", href=True):
                g = GO_TO_RE.search(a["href"])
                if g:
                    msg.reply_to_message_id = int(g.group(1))
                    file_part = a["href"].split("#", 1)[0]
                    msg.reply_to_file = file_part or None
                    break

    def _parse_default(self, block: Tag, msg: Message, state: ParserState,
                       result: FileParseResult) -> None:
        src = msg.source_file

        # Avatar (absent des messages joined)
        wrap = _child(block, "userpic_wrap")
        initials = userpic = None
        if wrap is not None:
            pic = wrap.find(class_="userpic")
            if pic is not None:
                userpic = next((c for c in _classes(pic) if re.fullmatch(r"userpic\d+", c)), None)
                ini = pic.find(class_="initials")
                initials = _text(ini)

        body = _child(block, "body")
        if body is None:
            msg.warnings.append("Message sans .body")
            result.anomalies.append(Anomaly("NO_BODY", "Message ordinaire sans .body", msg.html_id, src, "erreur"))
            return

        # Date
        date_div = _child(body, "date")
        if date_div is not None and date_div.get("title"):
            msg.date_raw = date_div["title"]
            dt, tz, off, rest = parse_date_title(msg.date_raw)
            msg.date, msg.timezone, msg.utc_offset_minutes = dt, tz, off
            if rest:
                msg.edited_raw = rest
            if dt is None:
                result.anomalies.append(Anomaly(
                    "UNPARSED_DATE", f"Date illisible : {msg.date_raw!r}", msg.html_id, src))
            elif tz is None:
                result.anomalies.append(Anomaly(
                    "NO_TIMEZONE", "Date sans fuseau horaire (heure locale supposée)", msg.html_id, src, "info"))
        else:
            result.anomalies.append(Anomaly("MISSING_DATE", "Message sans date", msg.html_id, src))

        # Expéditeur
        from_div = _child(body, "from_name")
        if from_div is not None:
            msg.sender, msg.via_bot = self._split_from_name(from_div)
        if msg.sender:
            msg.sender_initials, msg.sender_userpic_class = initials, userpic
            state.last_sender, state.last_initials, state.last_userpic = msg.sender, initials, userpic
        else:
            if state.last_sender is None:
                result.anomalies.append(Anomaly(
                    "JOINED_WITHOUT_SENDER",
                    "Message regroupé sans expéditeur précédent identifiable",
                    msg.html_id, src, "erreur"))
            else:
                msg.sender = state.last_sender
                msg.sender_initials = state.last_initials
                msg.sender_userpic_class = state.last_userpic
                msg.sender_inherited = True
            if not msg.is_joined:
                result.anomalies.append(Anomaly(
                    "MISSING_SENDER", "Message non regroupé sans .from_name (expéditeur hérité)",
                    msg.html_id, src))

        # Contenu : soit directement dans body, soit dans un bloc transféré
        container = body
        fwd = _child(body, "forwarded")
        if fwd is not None:
            fname = _child(fwd, "from_name")
            if fname is not None:
                dspan = fname.find(class_="date")
                if dspan is not None:
                    msg.forwarded_date_raw = dspan.get("title") or _text(dspan)
                msg.forwarded_from, _ = self._split_from_name(fname)
            container = fwd

        self._parse_content(container, msg)

        # Réponse
        reply = _child(body, "reply_to")
        if reply is not None:
            self._parse_reply(reply, msg, result)

        # Signature (canaux)
        sig = _child(body, "signature")
        if sig is not None:
            msg.signature = _text(sig)

        # Réactions
        reacts = _child(body, "reactions")
        if reacts is not None:
            msg.reactions = self._parse_reactions(reacts)

        # Éléments inconnus : signalés pour ne rien perdre en silence
        for child in body.find_all(True, recursive=False):
            if not (set(_classes(child)) & KNOWN_BODY_CLASSES):
                desc = f"<{child.name} class=\"{' '.join(_classes(child))}\">"
                msg.warnings.append("Élément inconnu conservé en texte : " + desc)
                extra = html_to_text(child)
                if extra:
                    msg.text = (msg.text + "\n" + extra).strip()
                result.anomalies.append(Anomaly(
                    "UNKNOWN_ELEMENT", f"Élément non reconnu dans le message : {desc}", msg.html_id, src))

        if not msg.text and not msg.media and fwd is None:
            result.anomalies.append(Anomaly(
                "EMPTY_MESSAGE", "Message sans texte ni média reconnu", msg.html_id, src))

        # Cohérence date / séparateur de date
        if msg.date is not None and state.current_separator is not None:
            if msg.date.date() != state.current_separator:
                result.anomalies.append(Anomaly(
                    "SEPARATOR_MISMATCH",
                    f"Date {msg.date.date().isoformat()} différente du séparateur "
                    f"{state.current_separator.isoformat()}", msg.html_id, src))

    # -- Sous-éléments ------------------------------------------------------- #

    @staticmethod
    def _split_from_name(from_div: Tag) -> tuple[str | None, str | None]:
        """Sépare le nom de l'expéditeur des mentions annexes (via @bot, date)."""
        via = None
        name_parts: list[str] = []
        for c in from_div.children:
            if isinstance(c, Tag):
                if _has_class(c, "date"):
                    continue
                if _has_class(c, "details"):
                    t = (_text(c) or "").strip()
                    if t.lower().startswith("via"):
                        via = t[3:].strip()
                    continue
                name_parts.append(c.get_text())
            else:
                name_parts.append(str(c))
        name = " ".join("".join(name_parts).split())
        return (name or None), via

    def _parse_content(self, container: Tag, msg: Message) -> None:
        text_div = _child(container, "text")
        if text_div is not None:
            msg.text = html_to_text(text_div)
            msg.html = sanitize_children(text_div)
            for a in text_div.find_all("a", href=True):
                href = a["href"].strip()
                if is_safe_href(href) and not href.startswith("#"):
                    msg.links.append(href)

        media_wrap = _child(container, "media_wrap")
        if media_wrap is not None:
            for el in media_wrap.find_all(True, recursive=False):
                msg.media.append(self._parse_media(el, msg))

    def _parse_media(self, el: Tag, msg: Message) -> Media:
        cls = _classes(el)
        href = el.get("href") if el.name == "a" else None

        if "photo_wrap" in cls:
            img = el.find("img", class_="photo")
            w, h = _thumb_size(img)
            return Media(MediaType.PHOTO, file_path=href, thumbnail_path=img.get("src") if img else None,
                         thumb_width=w, thumb_height=h, css_class="photo_wrap")
        if "video_file_wrap" in cls:
            img = el.find("img", class_="video_file")
            dur = _text(el.find(class_="video_duration"))
            w, h = _thumb_size(img)
            return Media(MediaType.VIDEO, file_path=href, thumbnail_path=img.get("src") if img else None,
                         duration_raw=dur, duration_seconds=parse_duration(dur),
                         thumb_width=w, thumb_height=h, css_class="video_file_wrap")
        if "animated_wrap" in cls:
            img = el.find("img", class_="animated")
            w, h = _thumb_size(img)
            return Media(MediaType.ANIMATION, file_path=href, thumbnail_path=img.get("src") if img else None,
                         thumb_width=w, thumb_height=h, css_class="animated_wrap")
        if "sticker_wrap" in cls:
            img = el.find("img", class_="sticker")
            w, h = _thumb_size(img)
            return Media(MediaType.STICKER, file_path=href, thumbnail_path=img.get("src") if img else None,
                         thumb_width=w, thumb_height=h, css_class="sticker_wrap")
        if "poll" in cls or "media_poll" in cls:
            question = _text(el.find(class_="question"))
            answers = [a for a in (_text(x) for x in el.find_all(class_="answer")) if a]
            total = _text(el.find(class_="total"))
            return Media(MediaType.POLL, title=question, description="\n".join(answers) or None,
                         status=total, css_class="poll")

        generic = next((c for c in cls if c in GENERIC_MEDIA_CLASSES), None)
        if generic is not None or "media" in cls:
            mtype = GENERIC_MEDIA_CLASSES.get(generic, MediaType.UNKNOWN)
            title = _text(el.find(class_="title"))
            desc = _text(el.find(class_="description"))
            status = _text(el.find(class_="status"))
            if mtype is MediaType.VIDEO and title and "video message" in title.lower():
                mtype = MediaType.VIDEO_MESSAGE
            thumb = el.find("img", class_="thumb")
            not_included = el.name != "a" or bool(status and "not included" in status.lower())
            dur_seconds = parse_duration(status) if mtype in (
                MediaType.VOICE, MediaType.AUDIO, MediaType.VIDEO, MediaType.VIDEO_MESSAGE, MediaType.CALL) else None
            duration_raw = None
            if dur_seconds is not None and status:
                dm = DURATION_RE.search(status)
                duration_raw = dm.group(0) if dm else None
            if mtype is MediaType.UNKNOWN:
                msg.warnings.append("Média de type inconnu : " + " ".join(cls))
            return Media(mtype, file_path=href if (href and not href.startswith("#")) else None,
                         thumbnail_path=thumb.get("src") if thumb else None,
                         title=title, description=desc, status=status,
                         duration_raw=duration_raw, duration_seconds=dur_seconds,
                         not_included=not_included, css_class=generic or "media")

        msg.warnings.append("Média non reconnu : " + " ".join(cls))
        return Media(MediaType.UNKNOWN, file_path=href, title=_text(el), css_class=" ".join(cls) or el.name)

    def _parse_reply(self, reply: Tag, msg: Message, result: FileParseResult) -> None:
        msg.reply_raw = _text(reply)
        a = reply.find("a")
        target = None
        if a is not None:
            href = a.get("href", "")
            g = GO_TO_RE.search(href) or GO_TO_JS_RE.search(a.get("onclick", ""))
            if g:
                target = int(g.group(1))
            file_part = href.split("#", 1)[0] if "#" in href else ""
            msg.reply_to_file = file_part or None
        if target is None:
            result.anomalies.append(Anomaly(
                "REPLY_UNRESOLVED",
                f"Réponse sans identifiant de message cible ({msg.reply_raw!r})",
                msg.html_id, msg.source_file, "info"))
        msg.reply_to_message_id = target

    @staticmethod
    def _parse_reactions(container: Tag) -> list[Reaction]:
        reactions: list[Reaction] = []
        for r in container.find_all(class_="reaction"):
            emoji_el = r.find(class_="emoji")
            custom = False
            emoji = ""
            if emoji_el is not None:
                img = emoji_el.find("img")
                if img is not None and img.get("src"):
                    emoji, custom = img["src"], True
                else:
                    emoji = (_text(emoji_el) or "").strip()
            users: list[str] = []
            pics = r.find(class_="userpics")
            if pics is not None:
                for u in pics.find_all(attrs={"title": True}):
                    users.append(u["title"].strip())
            count_el = r.find(class_="count")
            count = None
            if count_el is not None:
                digits = re.sub(r"\D", "", count_el.get_text())
                count = int(digits) if digits else None
            if count is None:
                count = max(len(users), 1)
            reactions.append(Reaction(emoji=emoji, count=count, users=users,
                                      is_custom_emoji=custom, active=_has_class(r, "active")))
        return reactions
