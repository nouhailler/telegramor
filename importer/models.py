"""Classes de données produites par le parseur d'exports Telegram HTML.

Ces classes sont indépendantes de toute interface graphique et de la base de
données : elles décrivent fidèlement ce qui a été lu dans l'export. La couche
`database` se chargera plus tard de les persister.

Règle générale : tout champ lu dans l'export est conservé tel quel (valeurs
brutes `*_raw`) en plus de sa version interprétée, afin de ne perdre aucune
information et de pouvoir ré-interpréter sans ré-importer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from enum import Enum
from typing import Any


class MessageKind(str, Enum):
    """Nature structurelle du bloc `.message` dans l'export."""

    DEFAULT = "default"          # message ordinaire (.message.default)
    SERVICE = "service"          # événement système (.message.service)
    DATE_SEPARATOR = "date_separator"  # .message.service contenant une date seule


class MediaType(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"
    ANIMATION = "animation"          # GIF
    STICKER = "sticker"
    VOICE = "voice"                  # message vocal
    VIDEO_MESSAGE = "video_message"  # vidéo ronde
    AUDIO = "audio"                  # fichier musical
    FILE = "file"                    # document quelconque
    LOCATION = "location"
    CONTACT = "contact"
    CALL = "call"
    POLL = "poll"
    GAME = "game"
    INVOICE = "invoice"
    UNKNOWN = "unknown"


@dataclass
class Media:
    """Pièce jointe d'un message. Les chemins sont ceux de l'export, jamais reconstruits."""

    media_type: MediaType
    file_path: str | None = None        # href de l'export (relatif au fichier HTML)
    thumbnail_path: str | None = None   # src de la miniature
    duration_raw: str | None = None     # ex. "00:42"
    duration_seconds: int | None = None
    title: str | None = None            # ex. nom de fichier, "Voice message"
    description: str | None = None      # ex. interprète, coordonnées
    status: str | None = None           # ex. "00:05, 12.3 KB"
    thumb_width: int | None = None
    thumb_height: int | None = None
    not_included: bool = False          # fichier volontairement exclu de l'export
    css_class: str | None = None        # classe d'origine (traçabilité)
    # Renseignés par le media_scanner (None = non vérifié)
    file_exists: bool | None = None
    thumbnail_exists: bool | None = None
    file_size: int | None = None


@dataclass
class Reaction:
    emoji: str                          # emoji Unicode, ou src d'un emoji personnalisé
    count: int                          # nombre de réactions (≥ len(users))
    users: list[str] = field(default_factory=list)  # noms lus dans les attributs title
    is_custom_emoji: bool = False
    active: bool = False                # réaction de l'utilisateur qui a exporté


@dataclass
class Message:
    # Identification
    html_id: str                        # attribut id brut, ex. "message185995"
    message_id: int                     # identifiant Telegram (négatif pour les services)
    conversation_id: str
    source_file: str                    # fichier HTML d'origine (relatif à l'archive)
    position: int                       # ordre d'apparition dans la conversation

    kind: MessageKind
    is_joined: bool = False

    # Expéditeur
    sender: str | None = None
    sender_inherited: bool = False      # True si hérité (message .joined)
    sender_initials: str | None = None
    sender_userpic_class: str | None = None  # ex. "userpic4" (couleur d'avatar)

    # Date
    date: datetime | None = None        # datetime « aware » si fuseau connu
    date_raw: str | None = None         # attribut title brut
    timezone: str | None = None         # ex. "UTC+01:00"
    utc_offset_minutes: int | None = None
    edited_raw: str | None = None       # mention de modification éventuelle
    separator_date: date | None = None  # pour les séparateurs de date

    # Contenu
    text: str = ""                      # texte brut (retours à la ligne conservés)
    html: str = ""                      # HTML utile assaini (liste blanche)
    links: list[str] = field(default_factory=list)
    service_text: str | None = None     # texte d'un message système

    # Relations
    reply_to_message_id: int | None = None
    reply_to_file: str | None = None    # autre fichier HTML si la cible y est
    reply_raw: str | None = None
    forwarded_from: str | None = None
    forwarded_date_raw: str | None = None
    via_bot: str | None = None
    signature: str | None = None

    reactions: list[Reaction] = field(default_factory=list)
    media: list[Media] = field(default_factory=list)

    # Avertissements de parsing propres à ce message
    warnings: list[str] = field(default_factory=list)

    @property
    def content_types(self) -> list[str]:
        types: list[str] = []
        if self.text:
            types.append("text")
        if self.links:
            types.append("link")
        types.extend(m.media_type.value for m in self.media)
        return types

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class Conversation:
    conversation_id: str
    name: str
    source_dir: str                     # répertoire de la conversation (absolu)
    source_files: list[str] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)

    @property
    def participants(self) -> list[str]:
        seen: dict[str, None] = {}
        for m in self.messages:
            if m.sender:
                seen.setdefault(m.sender, None)
        return list(seen)


@dataclass
class Anomaly:
    code: str                           # identifiant stable, ex. "MISSING_THUMBNAIL"
    message: str                        # description en français
    html_id: str | None = None
    source_file: str | None = None
    severity: str = "avertissement"     # "info" | "avertissement" | "erreur"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
