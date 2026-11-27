"""Objets de lecture renvoyés par les dépôts (vers l'interface).

Ils sont volontairement simples et immuables du point de vue de l'interface :
l'interface ne manipule jamais directement SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ArchiveRow:
    id: int
    source_path: str
    root_path: str
    name: str
    imported_at: str
    files_parsed: int
    messages_count: int
    media_count: int
    first_date: str | None
    last_date: str | None
    conversations: int = 0
    duplicates: int = 0            # messages également présents dans une autre archive
    root_exists: bool = True

    @property
    def status(self) -> str:
        return "OK" if self.root_exists else "Introuvable"


@dataclass
class IntegrityReport:
    archive_id: int
    root_exists: bool
    files_ok: int = 0
    files_missing: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    media_total: int = 0
    media_missing: int = 0
    media_missing_examples: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.root_exists and not self.files_missing and not self.files_modified

    def to_text(self) -> str:
        if not self.root_exists:
            return "Emplacement introuvable : l'archive a été déplacée ou le support n'est pas branché."
        lines = [f"Fichiers HTML intacts : {self.files_ok}"]
        if self.files_missing:
            lines.append(f"Fichiers HTML manquants : {len(self.files_missing)}")
            lines += [f"   · {p}" for p in self.files_missing[:20]]
        if self.files_modified:
            lines.append(f"Fichiers HTML modifiés depuis l'import : {len(self.files_modified)} "
                         "(réindexer l'archive pour prendre en compte les changements)")
            lines += [f"   · {p}" for p in self.files_modified[:20]]
        lines.append(f"Médias référencés : {self.media_total}, introuvables : {self.media_missing}")
        lines += [f"   · {p}" for p in self.media_missing_examples]
        lines.append("Résultat : " + ("archive intègre ✔" if self.ok else "anomalies détectées ✘"))
        return "\n".join(lines)


@dataclass
class ConversationSummary:
    id: str
    name: str
    message_count: int
    media_count: int
    first_date: str | None
    last_date: str | None
    last_preview: str | None
    last_sender: str | None
    archives: list[str] = field(default_factory=list)


@dataclass
class ParticipantRow:
    name: str
    message_count: int
    initials: str | None
    userpic_class: str | None
    first_date: str | None
    last_date: str | None


@dataclass
class MediaRow:
    id: int
    media_type: str
    file_path: str | None           # tel que lu dans l'export
    thumbnail_path: str | None
    abs_file: Path | None           # chemin absolu résolu (None si non résoluble)
    abs_thumbnail: Path | None
    duration_raw: str | None
    title: str | None
    description: str | None
    status: str | None
    thumb_width: int | None
    thumb_height: int | None
    not_included: bool
    # Contexte (galerie)
    message_seq: int | None = None
    message_date: str | None = None
    message_sender: str | None = None
    conversation_id: str | None = None
    conversation_name: str | None = None
    file_size: int | None = None
    message_id: int | None = None   # identifiant Telegram du message (clé des données personnelles)
    ordinal: int = 0                # rang du média dans son message

    @property
    def file_available(self) -> bool:
        return self.abs_file is not None and self.abs_file.is_file()

    @property
    def thumbnail_available(self) -> bool:
        return self.abs_thumbnail is not None and self.abs_thumbnail.is_file()


@dataclass
class ReactionRow:
    emoji: str
    count: int
    users: list[str]
    is_custom_emoji: bool
    active: bool
    abs_image: Path | None = None    # image d'emoji personnalisé


@dataclass
class ReplyPreview:
    message_id: int
    seq: int | None                  # None si la cible n'est pas dans la bibliothèque
    sender: str | None
    text: str
    media_type: str | None


@dataclass
class MessageRow:
    pk: int
    conversation_id: str
    seq: int
    message_id: int
    kind: str
    is_joined: bool
    sender: str | None
    sender_initials: str | None
    sender_userpic: str | None
    date_local: str | None
    day: str | None
    timezone: str | None
    edited_raw: str | None
    separator_date: str | None
    text: str
    html: str
    service_text: str | None
    reply_to_message_id: int | None
    reply_raw: str | None
    forwarded_from: str | None
    via_bot: str | None
    signature: str | None
    archive_name: str
    media: list[MediaRow] = field(default_factory=list)
    reactions: list[ReactionRow] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    reply: ReplyPreview | None = None
    # Données personnelles Telegramor (jamais issues de l'export)
    favorite: bool = False
    note: str | None = None
    collections: int = 0
