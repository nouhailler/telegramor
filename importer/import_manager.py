"""Orchestration d'une importation : détection → parsing → médias → rapport.

Les fichiers HTML sont analysés indépendamment (en parallèle dans des
processus séparés pour les gros exports), puis raccordés dans l'ordre. Le
résultat est identique à une lecture séquentielle. La persistance est faite
ensuite par `database.repositories.LibraryRepository.save_import`.
"""

from __future__ import annotations

import multiprocessing
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import archive_detector, media_scanner
from .import_report import ImportReport
from .models import Anomaly, Conversation, Message, MessageKind
from .telegram_html_parser import FileParseResult, ParserState, TelegramHtmlParser, make_conversation_id

ProgressCallback = Callable[[int, int, str], None]   # (fait, total, libellé)


@dataclass
class ImportResult:
    archive_root: Path
    conversations: list[Conversation]
    report: ImportReport


PARALLEL_MIN_FILES = 4      # en dessous, le coût de démarrage des processus l'emporte


def _workers(n_files: int) -> int:
    env = os.environ.get("TAE_WORKERS")
    if env:
        return max(1, int(env))
    if n_files < PARALLEL_MIN_FILES:
        return 1
    return max(1, min(n_files, (os.cpu_count() or 2) - 1, 8))


def _parse_job(path: str, rel: str) -> FileParseResult:
    """Analyse d'un fichier, état vierge (exécutable dans un processus séparé)."""
    return TelegramHtmlParser().parse_file(path, None, ParserState(), source_name=rel)


def _parse_all(jobs: list[tuple[str, str]], progress: ProgressCallback | None) -> dict[str, FileParseResult]:
    total = len(jobs)
    results: dict[str, FileParseResult] = {}
    workers = _workers(total)
    if workers <= 1:
        for i, (path, rel) in enumerate(jobs):
            if progress:
                progress(i, total, rel)
            results[rel] = _parse_job(path, rel)
        return results
    # « spawn » plutôt que « fork » : sûr même depuis une application Qt multithread
    ctx = multiprocessing.get_context("spawn")
    try:
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
            futures = {pool.submit(_parse_job, path, rel): rel for path, rel in jobs}
            for done, fut in enumerate(as_completed(futures), start=1):
                rel = futures[fut]
                results[rel] = fut.result()
                if progress:
                    progress(done, total, f"{rel} ({workers} processus)")
    except (BrokenProcessPool, OSError):
        # Environnement où les processus ne peuvent pas démarrer : repli séquentiel
        for i, (path, rel) in enumerate(jobs):
            if rel not in results:
                if progress:
                    progress(i, total, rel)
                results[rel] = _parse_job(path, rel)
    return results


def _stitch(results: list[FileParseResult]) -> tuple[list[Message], list[Anomaly]]:
    """Raccorde les fichiers d'une conversation analysés indépendamment.

    Reproduit exactement une lecture séquentielle : numérotation continue,
    expéditeur hérité par les messages regroupés en tête de fichier,
    contrôle date/séparateur à la jonction des fichiers.
    """
    messages: list[Message] = []
    anomalies: list[Anomaly] = []
    pos = 0
    last_sender = last_initials = last_userpic = None
    separator = None
    for res in results:
        fixed: set[str] = set()
        before_first_sender = True
        before_first_separator = True
        for m in res.messages:
            m.position = pos
            pos += 1
            if m.kind is MessageKind.DATE_SEPARATOR:
                before_first_separator = False
                separator = m.separator_date
                continue
            if m.kind is not MessageKind.DEFAULT:
                continue
            if before_first_sender and m.sender is None and last_sender is not None:
                m.sender, m.sender_initials, m.sender_userpic_class = last_sender, last_initials, last_userpic
                m.sender_inherited = True
                fixed.add(m.html_id)
            elif m.sender is not None and not m.sender_inherited:
                before_first_sender = False
            if m.sender is not None:
                last_sender, last_initials, last_userpic = m.sender, m.sender_initials, m.sender_userpic_class
            if before_first_separator and separator is not None and m.date is not None \
                    and m.date.date() != separator:
                anomalies.append(Anomaly(
                    "SEPARATOR_MISMATCH",
                    f"Date {m.date.date().isoformat()} différente du séparateur {separator.isoformat()}",
                    m.html_id, m.source_file))
        anomalies.extend(a for a in res.anomalies
                         if not (a.code == "JOINED_WITHOUT_SENDER" and a.html_id in fixed))
        messages.extend(res.messages)
    return messages, anomalies


def import_path(path: str | Path, progress: ProgressCallback | None = None,
                check_media: bool = True) -> ImportResult:
    root, sources = archive_detector.detect(path)
    conversations: list[Conversation] = []
    anomalies: list[Anomaly] = []
    blocks_detected = files_parsed = 0

    if not sources:
        anomalies.append(Anomaly("NO_CONVERSATION", "Aucun fichier messages*.html trouvé", severity="erreur"))

    jobs = [(str(f), str(f.relative_to(root))) for s in sources for f in s.files]
    parsed = _parse_all(jobs, progress)
    total_files = len(jobs)

    for source in sources:
        rels = [str(f.relative_to(root)) for f in source.files]
        results = [parsed[r] for r in rels]
        if not results:
            continue
        for res in results:
            files_parsed += 1
            blocks_detected += res.raw_block_count
            if res.dom_block_count != res.raw_block_count:
                anomalies.append(Anomaly(
                    "DOM_COUNT_MISMATCH",
                    f"{res.raw_block_count} blocs dans le texte brut, {res.dom_block_count} dans le DOM",
                    source_file=res.source_file, severity="erreur"))
        name = results[0].conversation_name or source.directory.name
        conv = Conversation(make_conversation_id(name), name, str(source.directory), source_files=rels)
        for res in results[1:]:
            if res.conversation_name and res.conversation_name != name:
                anomalies.append(Anomaly(
                    "NAME_CHANGED",
                    f"Nom de conversation différent dans {res.source_file} : {res.conversation_name!r} ≠ {name!r}",
                    source_file=res.source_file, severity="info"))
        messages, stitch_anomalies = _stitch(results)
        for m in messages:
            m.conversation_id = conv.conversation_id
        conv.messages = messages
        anomalies.extend(stitch_anomalies)
        anomalies.extend(_check_conversation(conv))
        if check_media:
            anomalies.extend(media_scanner.scan_conversation(conv, root))
        conversations.append(conv)

    if progress:
        progress(total_files, total_files, "terminé")
    report = ImportReport.build(str(root), conversations, files_parsed, blocks_detected, anomalies)
    return ImportResult(root, conversations, report)


def _check_conversation(conv: Conversation) -> list[Anomaly]:
    out: list[Anomaly] = []
    ids = Counter(m.message_id for m in conv.messages)
    for mid, n in ids.items():
        if n > 1:
            out.append(Anomaly("DUPLICATE_ID", f"Identifiant {mid} présent {n} fois", f"message{mid}",
                               severity="erreur"))
    previous = None
    for m in conv.messages:
        if m.kind is not MessageKind.DEFAULT or m.date is None:
            continue
        if previous is not None and m.date < previous.date:
            out.append(Anomaly("CHRONOLOGY", f"Date antérieure au message précédent ({previous.html_id})",
                               m.html_id, m.source_file))
        previous = m
        # Initiales de l'avatar incohérentes avec le nom : signe d'un renommage
        # ou d'une anonymisation de l'export (information, pas une erreur).
        if (m.sender and m.sender_initials and not m.sender_inherited
                and not m.sender.casefold().startswith(m.sender_initials[0].casefold())):
            out.append(Anomaly(
                "INITIALS_MISMATCH",
                f"Avatar « {m.sender_initials} » pour l'expéditeur « {m.sender} »",
                m.html_id, m.source_file, "info"))
    return out
