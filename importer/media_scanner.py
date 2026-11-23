"""Vérification de l'existence des fichiers référencés par les médias.

Les chemins ne sont jamais reconstruits ni « devinés » : on vérifie
uniquement le chemin exact lu dans l'export (avec, au plus, le décodage des
séquences %XX d'URL). Un chemin qui sortirait du répertoire de l'archive
(chemin absolu, « .. ») est signalé et n'est pas consulté.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from .models import Anomaly, Conversation, Media


def resolve_media_path(base_dir: Path, archive_root: Path, rel: str) -> tuple[Path | None, str | None]:
    """Retourne (chemin absolu, erreur). Ne lit pas le fichier."""
    if urlparse(rel).scheme in ("http", "https", "file", "javascript", "data"):
        return None, "schéma d'URL non local"
    if Path(rel).is_absolute():
        return None, "chemin absolu"
    candidate = (base_dir / rel).resolve()
    try:
        candidate.relative_to(archive_root.resolve())
    except ValueError:
        return None, "chemin hors de l'archive"
    if not candidate.exists() and "%" in rel:
        decoded = (base_dir / unquote(rel)).resolve()
        try:
            decoded.relative_to(archive_root.resolve())
            if decoded.exists():
                return decoded, None
        except ValueError:
            pass
    return candidate, None


def scan_conversation(conv: Conversation, archive_root: Path) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    base = Path(conv.source_dir)
    for msg in conv.messages:
        for media in msg.media:
            anomalies.extend(_scan_media(media, base, archive_root, msg.html_id, msg.source_file))
    return anomalies


def _scan_media(media: Media, base: Path, root: Path, html_id: str, src: str) -> list[Anomaly]:
    out: list[Anomaly] = []
    for attr, exists_attr, code, label in (
        ("file_path", "file_exists", "MISSING_FILE", "Fichier"),
        ("thumbnail_path", "thumbnail_exists", "MISSING_THUMBNAIL", "Miniature"),
    ):
        rel = getattr(media, attr)
        if not rel:
            continue
        path, err = resolve_media_path(base, root, rel)
        if err:
            setattr(media, exists_attr, False)
            out.append(Anomaly("SUSPICIOUS_PATH", f"{label} ignoré ({err}) : {rel}", html_id, src, "erreur"))
            continue
        ok = path.is_file()
        setattr(media, exists_attr, ok)
        if ok and attr == "file_path":
            media.file_size = path.stat().st_size
        if not ok:
            out.append(Anomaly(code, f"{label} {media.media_type.value} introuvable : {rel}", html_id, src))
    if media.not_included:
        out.append(Anomaly("NOT_INCLUDED",
                           f"Média {media.media_type.value} non inclus dans l'export ({media.status or 's.o.'})",
                           html_id, src, "info"))
    return out
