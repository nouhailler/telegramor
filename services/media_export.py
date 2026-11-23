"""Copie de médias sélectionnés vers un dossier choisi par l'utilisateur.

Règles :
- les fichiers de l'export sont seulement lus (jamais déplacés ni modifiés) ;
- aucun fichier existant n'est écrasé dans le dossier de destination : en cas de
  conflit de nom, un suffixe « (2) », « (3) »… est ajouté ;
- les médias dont le fichier est absent de l'export sont ignorés et comptés ;
- un même fichier sélectionné deux fois n'est copié qu'une fois.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from database.models import MediaRow

NAMING_ORIGINAL = "original"       # photo_12@16-12-2025_18-33-18.jpg
NAMING_DATE = "date"               # 2025-12-16_18-33-18_photo_12@16-12-2025_18-33-18.jpg

_UNSAFE = re.compile(r'[\x00-\x1f/\\:*?"<>|]+')


@dataclass
class ExportOptions:
    naming: str = NAMING_ORIGINAL
    by_conversation: bool = False      # un sous-dossier par conversation
    set_mtime: bool = True             # date de modification = date du message


@dataclass
class CopyPlan:
    media: MediaRow
    source: Path
    target: Path


@dataclass
class ExportResult:
    destination: Path
    copied: list[Path] = field(default_factory=list)
    renamed: int = 0                   # copiés sous un autre nom (conflit)
    missing: int = 0                   # fichier absent de l'export
    duplicates: int = 0                # même fichier sélectionné plusieurs fois
    errors: list[tuple[str, str]] = field(default_factory=list)   # (fichier, message)
    cancelled: bool = False
    bytes_copied: int = 0


def safe_name(name: str) -> str:
    name = _UNSAFE.sub("_", name).strip(" .")
    return name[:180] or "media"


def _message_datetime(m: MediaRow) -> datetime | None:
    if not m.message_date:
        return None
    try:
        return datetime.fromisoformat(m.message_date)
    except ValueError:
        return None


def target_name(m: MediaRow, options: ExportOptions) -> str:
    base = safe_name(m.abs_file.name if m.abs_file else (m.title or "media"))
    if options.naming == NAMING_DATE:
        dt = _message_datetime(m)
        if dt is not None:
            base = f"{dt:%Y-%m-%d_%H-%M-%S}_{base}"
    return base


def _unique(path: Path, taken: set[Path]) -> Path:
    if path not in taken and not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 2
    while True:
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if candidate not in taken and not candidate.exists():
            return candidate
        i += 1


def plan_copies(medias: Iterable[MediaRow], destination: Path, options: ExportOptions,
                ) -> tuple[list[CopyPlan], ExportResult]:
    """Calcule les copies à faire (sans rien écrire)."""
    destination = Path(destination)
    result = ExportResult(destination)
    plans: list[CopyPlan] = []
    seen: set[Path] = set()
    taken: set[Path] = set()
    for m in medias:
        if not m.file_available:
            result.missing += 1
            continue
        src = m.abs_file.resolve()
        if src in seen:
            result.duplicates += 1
            continue
        seen.add(src)
        folder = destination
        if options.by_conversation:
            folder = destination / safe_name(m.conversation_name or "Sans nom")
        wanted = folder / target_name(m, options)
        target = _unique(wanted, taken)
        if target != wanted:
            result.renamed += 1
        taken.add(target)
        plans.append(CopyPlan(m, src, target))
    return plans, result


def total_size(plans: list[CopyPlan]) -> int:
    total = 0
    for p in plans:
        try:
            total += p.source.stat().st_size
        except OSError:
            pass
    return total


def execute(plans: list[CopyPlan], result: ExportResult, options: ExportOptions,
            progress: Callable[[int, int, str], bool] | None = None) -> ExportResult:
    """Copie les fichiers. `progress(fait, total, nom)` peut renvoyer False pour annuler."""
    n = len(plans)
    for i, p in enumerate(plans):
        if progress and progress(i, n, p.target.name) is False:
            result.cancelled = True
            break
        created = False
        try:
            p.target.parent.mkdir(parents=True, exist_ok=True)
            # « x » : ne jamais écraser, même si un fichier apparaît entre-temps
            with open(p.source, "rb") as fsrc, open(p.target, "xb") as fdst:
                created = True
                shutil.copyfileobj(fsrc, fdst, 1024 * 1024)
            dt = _message_datetime(p.media) if options.set_mtime else None
            if dt is not None:
                ts = dt.timestamp()
                os.utime(p.target, (ts, ts))
            else:
                st = p.source.stat()
                os.utime(p.target, (st.st_atime, st.st_mtime))
            result.copied.append(p.target)
            result.bytes_copied += p.target.stat().st_size
        except OSError as e:
            if created:                     # pas de copie partielle laissée derrière
                p.target.unlink(missing_ok=True)
            result.errors.append((p.source.name, e.strerror or str(e)))
    if progress and not result.cancelled:
        progress(n, n, "")
    return result


def export_medias(medias: Iterable[MediaRow], destination: Path, options: ExportOptions | None = None,
                  progress: Callable[[int, int, str], bool] | None = None) -> ExportResult:
    options = options or ExportOptions()
    plans, result = plan_copies(medias, destination, options)
    return execute(plans, result, options, progress)


def summary_text(r: ExportResult) -> str:
    from .media_service import human_size
    lines = [f"{len(r.copied)} fichier(s) copié(s) ({human_size(r.bytes_copied)}) dans :\n{r.destination}"]
    if r.renamed:
        lines.append(f"{r.renamed} renommé(s) pour ne pas écraser un fichier existant.")
    if r.duplicates:
        lines.append(f"{r.duplicates} sélectionné(s) en double, copié(s) une seule fois.")
    if r.missing:
        lines.append(f"{r.missing} ignoré(s) : fichier absent de l'export.")
    if r.cancelled:
        lines.append("Copie interrompue : les fichiers déjà copiés sont conservés.")
    if r.errors:
        lines.append(f"{len(r.errors)} erreur(s) :")
        lines += [f"  • {name} : {msg}" for name, msg in r.errors[:10]]
        if len(r.errors) > 10:
            lines.append(f"  … et {len(r.errors) - 10} autre(s)")
    return "\n".join(lines)
