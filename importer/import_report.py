"""Rapport de contrôle qualité d'une importation."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from .models import Anomaly, Conversation, MediaType, MessageKind

AUDIO_TYPES = {MediaType.AUDIO, MediaType.VOICE}


@dataclass
class ImportReport:
    archive_path: str
    conversations: int = 0
    files_parsed: int = 0
    blocks_detected: int = 0           # comptage indépendant sur le HTML brut
    blocks_parsed: int = 0             # objets Message produits
    messages_default: int = 0          # messages ordinaires (dont regroupés)
    messages_joined: int = 0
    messages_service: int = 0          # événements système (hors séparateurs)
    date_separators: int = 0
    senders: list[str] = field(default_factory=list)
    replies: int = 0
    replies_resolved: int = 0
    reactions_total: int = 0
    messages_with_reactions: int = 0
    links: int = 0
    forwarded: int = 0
    edited: int = 0
    media_by_type: dict[str, int] = field(default_factory=dict)
    photos: int = 0
    videos: int = 0
    audio_files: int = 0               # vocaux + fichiers audio
    missing_files: int = 0             # originaux + miniatures absents
    missing_file_list: list[str] = field(default_factory=list)
    not_included: int = 0
    first_message: str | None = None
    last_message: str | None = None
    anomalies: list[Anomaly] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.blocks_detected == self.blocks_parsed

    # ------------------------------------------------------------------ #

    @classmethod
    def build(cls, archive_path: str, conversations: list[Conversation],
              files_parsed: int, blocks_detected: int, anomalies: list[Anomaly]) -> "ImportReport":
        r = cls(archive_path=archive_path, conversations=len(conversations),
                files_parsed=files_parsed, blocks_detected=blocks_detected,
                anomalies=list(anomalies))
        senders: dict[str, None] = {}
        media_counter: Counter[str] = Counter()
        dates: list[datetime] = []
        for conv in conversations:
            ids = {m.message_id for m in conv.messages}
            for m in conv.messages:
                r.blocks_parsed += 1
                if m.kind is MessageKind.DATE_SEPARATOR:
                    r.date_separators += 1
                    continue
                if m.kind is MessageKind.SERVICE:
                    r.messages_service += 1
                else:
                    r.messages_default += 1
                    r.messages_joined += m.is_joined
                if m.sender:
                    senders.setdefault(m.sender, None)
                if m.date:
                    dates.append(m.date)
                if m.reply_to_message_id is not None or m.reply_raw:
                    if m.kind is MessageKind.DEFAULT:
                        r.replies += 1
                        if m.reply_to_message_id in ids:
                            r.replies_resolved += 1
                        else:
                            r.anomalies.append(Anomaly(
                                "REPLY_TARGET_MISSING",
                                f"Message cible {m.reply_to_message_id} absent de la conversation "
                                "(export partiel ?)", m.html_id, m.source_file, "info"))
                if m.reactions:
                    r.messages_with_reactions += 1
                    r.reactions_total += sum(x.count for x in m.reactions)
                r.links += len(m.links)
                r.forwarded += m.forwarded_from is not None
                r.edited += m.edited_raw is not None
                for media in m.media:
                    media_counter[media.media_type.value] += 1
                    if media.not_included:
                        r.not_included += 1
                    for path, exists in ((media.file_path, media.file_exists),
                                         (media.thumbnail_path, media.thumbnail_exists)):
                        if path and exists is False:
                            r.missing_files += 1
                            r.missing_file_list.append(path)
        r.senders = list(senders)
        r.media_by_type = dict(sorted(media_counter.items()))
        r.photos = media_counter[MediaType.PHOTO.value]
        r.videos = media_counter[MediaType.VIDEO.value] + media_counter[MediaType.VIDEO_MESSAGE.value]
        r.audio_files = sum(media_counter[t.value] for t in AUDIO_TYPES)
        if dates:
            r.first_message = min(dates).isoformat()
            r.last_message = max(dates).isoformat()
        if not r.is_complete:
            r.anomalies.insert(0, Anomaly(
                "COUNT_MISMATCH",
                f"{r.blocks_detected} blocs détectés dans le HTML brut mais {r.blocks_parsed} analysés",
                severity="erreur"))
        return r

    # ------------------------------------------------------------------ #

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ImportReport":
        """Reconstruit un rapport enregistré (archives.report_json)."""
        known = {f for f in cls.__dataclass_fields__}
        data = {k: v for k, v in d.items() if k in known}
        data["anomalies"] = [Anomaly(**a) for a in d.get("anomalies", [])]
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["is_complete"] = self.is_complete
        return d

    def to_text(self) -> str:
        sev = Counter(a.severity for a in self.anomalies)
        lines = [
            "═" * 64,
            " RAPPORT D'IMPORTATION",
            "═" * 64,
            f" Archive                    : {self.archive_path}",
            f" Conversations              : {self.conversations}",
            f" Fichiers HTML analysés     : {self.files_parsed}",
            "─" * 64,
            f" Blocs détectés (HTML brut) : {self.blocks_detected}",
            f" Blocs importés             : {self.blocks_parsed}"
            + ("   ✔ complet" if self.is_complete else "   ✘ ÉCART"),
            f"   dont messages ordinaires : {self.messages_default}",
            f"   dont regroupés (joined)  : {self.messages_joined}",
            f"   dont événements système  : {self.messages_service}",
            f"   dont séparateurs de date : {self.date_separators}",
            f" Expéditeurs identifiés     : {len(self.senders)} ({', '.join(self.senders)})",
            f" Réponses identifiées       : {self.replies} (cible trouvée : {self.replies_resolved})",
            f" Réactions                  : {self.reactions_total} sur {self.messages_with_reactions} message(s)",
            f" Liens                      : {self.links}",
            f" Messages transférés        : {self.forwarded}",
            f" Messages modifiés          : {self.edited}",
            "─" * 64,
            f" Photographies              : {self.photos}",
            f" Vidéos                     : {self.videos}",
            f" Fichiers audio / vocaux    : {self.audio_files}",
            f" Médias par type            : {self.media_by_type or '-'}",
            f" Médias non inclus (export) : {self.not_included}",
            f" Fichiers manquants         : {self.missing_files}",
        ]
        lines += [f"     · {p}" for p in self.missing_file_list]
        lines += [
            "─" * 64,
            f" Premier message            : {self.first_message or '-'}",
            f" Dernier message            : {self.last_message or '-'}",
            "─" * 64,
            f" Anomalies : {len(self.anomalies)} (erreurs : {sev['erreur']}, "
            f"avertissements : {sev['avertissement']}, infos : {sev['info']})",
        ]
        for a in self.anomalies:
            where = f" [{a.source_file}#{a.html_id}]" if a.html_id else ""
            lines.append(f"  - {a.severity.upper():13} {a.code}: {a.message}{where}")
        lines.append("═" * 64)
        return "\n".join(lines)
