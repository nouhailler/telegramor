"""Détection non destructive des médias identiques (empreinte SHA-256).

- Seuls les fichiers sont lus ; rien n'est supprimé, déplacé ni modifié.
- Les empreintes sont stockées dans `media_hashes` (une ligne par média de la
  bibliothèque) ; `file_hash_cache` évite de relire un fichier inchangé.
- Un « doublon » est un fichier strictement identique (même empreinte, même
  taille). Deux photos simplement semblables ne sont jamais regroupées.
- Les copies d'un même *message* présentes dans plusieurs archives sont déjà
  gérées par la bibliothèque (is_duplicate) et ne comptent pas ici.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from database.db_manager import Database
from database.repositories import LibraryRepository

CHUNK = 1024 * 1024


def sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


@dataclass
class HashSummary:
    hashed: int = 0          # fichiers lus
    from_cache: int = 0      # empreintes reprises du cache (fichier inchangé)
    missing: int = 0         # fichier absent ou chemin invalide
    errors: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False


@dataclass
class Occurrence:
    media_id: int
    media_type: str
    conversation_id: str
    conversation_name: str
    message_id: int
    seq: int
    sender: str | None
    date_local: str | None
    path: Path | None


@dataclass
class DuplicateGroup:
    sha256: str
    size: int
    occurrences: list[Occurrence]


def pending_count(db: Database) -> int:
    """Médias dont le fichier est présent mais dont l'empreinte n'est pas encore calculée."""
    return db.conn.execute(
        """SELECT COUNT(*) FROM medias md JOIN messages m ON m.id = md.message_pk
           WHERE m.is_duplicate = 0 AND md.file_exists = 1
             AND NOT EXISTS (SELECT 1 FROM media_hashes h WHERE h.media_id = md.id)""").fetchone()[0]


def compute_hashes(db: Database, repo: LibraryRepository,
                   progress: Callable[[int, int], bool] | None = None) -> HashSummary:
    """Calcule les empreintes manquantes. progress(fait, total) -> False pour annuler."""
    c = db.conn
    rows = c.execute(
        """SELECT md.id, m.archive_id, m.source_file, md.file_path FROM medias md
           JOIN messages m ON m.id = md.message_pk
           WHERE m.is_duplicate = 0 AND md.file_exists = 1
             AND NOT EXISTS (SELECT 1 FROM media_hashes h WHERE h.media_id = md.id)
           ORDER BY m.archive_id, md.id""").fetchall()
    summary = HashSummary()
    batch: list[tuple[int, str, int]] = []
    cache_rows: list[tuple[str, int, int, str]] = []

    def flush() -> None:
        with c:
            c.executemany("INSERT OR REPLACE INTO media_hashes VALUES (?, ?, ?)", batch)
            c.executemany("INSERT OR REPLACE INTO file_hash_cache VALUES (?, ?, ?, ?)", cache_rows)
        batch.clear()
        cache_rows.clear()

    for i, (media_id, archive_id, source_file, rel) in enumerate(rows):
        if progress and progress(i, len(rows)) is False:
            summary.cancelled = True
            break
        path = repo.resolve_path(archive_id, source_file, rel)
        if path is None or not path.is_file():
            summary.missing += 1
            continue
        try:
            st = path.stat()
            key = str(path)
            cached = c.execute("SELECT size, mtime_ns, sha256 FROM file_hash_cache WHERE path = ?", (key,)).fetchone()
            if cached and cached[0] == st.st_size and cached[1] == st.st_mtime_ns:
                digest, size = cached[2], cached[0]
                summary.from_cache += 1
            else:
                digest, size = sha256_file(path)
                cache_rows.append((key, size, st.st_mtime_ns, digest))
                summary.hashed += 1
            batch.append((media_id, digest, size))
        except OSError as exc:
            summary.errors.append((str(path), exc.strerror or str(exc)))
        if len(batch) >= 500:
            flush()
    flush()
    if progress and not summary.cancelled:
        progress(len(rows), len(rows))
    return summary


_OCC_SELECT = """SELECT md.id, md.media_type, m.conversation_id, c.name, m.message_id, m.seq, m.sender,
                        m.date_local, m.archive_id, m.source_file, md.file_path, h.sha256, h.size
                 FROM media_hashes h JOIN medias md ON md.id = h.media_id
                 JOIN messages m ON m.id = md.message_pk AND m.is_duplicate = 0
                 JOIN conversations c ON c.id = m.conversation_id"""


def _occ(repo: LibraryRepository, r) -> Occurrence:
    return Occurrence(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], repo.resolve_path(r[8], r[9], r[10]))


def duplicate_groups(db: Database, repo: LibraryRepository, limit: int | None = None) -> list[DuplicateGroup]:
    """Groupes de fichiers identiques présents au moins deux fois, du plus volumineux au plus petit."""
    rows = db.conn.execute(
        f"""{_OCC_SELECT} WHERE h.sha256 IN (
                SELECT h2.sha256 FROM media_hashes h2 JOIN medias md2 ON md2.id = h2.media_id
                JOIN messages m2 ON m2.id = md2.message_pk AND m2.is_duplicate = 0
                GROUP BY h2.sha256 HAVING COUNT(*) > 1)
            ORDER BY h.size DESC, h.sha256, m.date_utc""").fetchall()
    groups: dict[str, DuplicateGroup] = {}
    for r in rows:
        g = groups.get(r[11])
        if g is None:
            if limit is not None and len(groups) >= limit:
                break
            g = groups[r[11]] = DuplicateGroup(r[11], r[12], [])
        g.occurrences.append(_occ(repo, r))
    return list(groups.values())


def occurrences(db: Database, repo: LibraryRepository, media_id: int) -> list[Occurrence]:
    """Toutes les occurrences du fichier d'un média (lui compris) ; [] si l'empreinte est inconnue."""
    row = db.conn.execute("SELECT sha256 FROM media_hashes WHERE media_id = ?", (media_id,)).fetchone()
    if not row:
        return []
    return [_occ(repo, r) for r in db.conn.execute(f"{_OCC_SELECT} WHERE h.sha256 = ? ORDER BY m.date_utc",
                                                    (row[0],))]


def stats(db: Database) -> dict[str, int]:
    r = db.conn.execute(
        """SELECT COUNT(*), COALESCE(SUM(n - 1), 0), COALESCE(SUM((n - 1) * size), 0) FROM (
               SELECT COUNT(*) AS n, MAX(h.size) AS size FROM media_hashes h
               JOIN medias md ON md.id = h.media_id JOIN messages m ON m.id = md.message_pk AND m.is_duplicate = 0
               GROUP BY h.sha256 HAVING COUNT(*) > 1)""").fetchone()
    hashed = db.conn.execute("SELECT COUNT(*) FROM media_hashes").fetchone()[0]
    return {"groups": r[0], "extra_copies": r[1], "extra_bytes": r[2], "hashed": hashed,
            "pending": pending_count(db)}
