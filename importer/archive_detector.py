"""Détection des conversations dans un export Telegram.

Formats pris en charge :
- export d'une seule conversation : un répertoire contenant messages.html,
  éventuellement messages2.html, messages3.html… ;
- export complet du compte : chats/chat_001/messages*.html, etc. ;
- un fichier HTML isolé.

Chaque répertoire contenant des fichiers messages*.html est une conversation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MESSAGES_FILE_RE = re.compile(r"^messages(\d*)\.html$", re.IGNORECASE)
IGNORED_DIRS = {"css", "js", "images", "photos", "video_files", "voice_messages",
                "round_video_messages", "files", "stickers", "audio_files", "profile_pictures"}


@dataclass
class ConversationSource:
    directory: Path
    files: list[Path] = field(default_factory=list)   # dans l'ordre de lecture


def _file_order(p: Path) -> int:
    m = MESSAGES_FILE_RE.match(p.name)
    return int(m.group(1) or 1) if m else 0


def detect(path: str | Path) -> tuple[Path, list[ConversationSource]]:
    """Retourne (racine de l'archive, conversations détectées)."""
    path = Path(path).expanduser().resolve()
    if path.is_file():
        return path.parent, [ConversationSource(path.parent, [path])]
    if not path.is_dir():
        raise FileNotFoundError(f"Chemin introuvable : {path}")

    groups: dict[Path, list[Path]] = {}
    for f in path.rglob("*.html"):
        if any(part in IGNORED_DIRS for part in f.relative_to(path).parts[:-1]):
            continue
        if MESSAGES_FILE_RE.match(f.name):
            groups.setdefault(f.parent, []).append(f)

    sources = [ConversationSource(d, sorted(files, key=_file_order))
               for d, files in sorted(groups.items())]
    return path, sources
