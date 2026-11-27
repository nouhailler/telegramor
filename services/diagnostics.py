"""Diagnostic de la bibliothèque : intégrité SQLite, index, archives, médias,
relations entre messages et données personnelles.

Le diagnostic ne modifie jamais les exports Telegram ni les données de
l'utilisateur ; il actualise seulement, dans la base, l'état de présence des
médias (comme la vérification d'une archive). Aucune correction n'est appliquée
automatiquement. Chaque anomalie est accompagnée d'une recommandation ; les
corrections possibles (reconstruire l'index, réindexer, relocaliser une
archive) restent des actions explicites de l'utilisateur.

Il réutilise `LibraryRepository.verify_archive` (contrôle par archive) au lieu
de le réécrire.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from database.db_manager import SCHEMA_VERSION, Database
from database.repositories import LibraryRepository

ERROR, WARNING, INFO = "erreur", "avertissement", "information"
SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}
SEVERITY_LABELS = {ERROR: "Erreur", WARNING: "Avertissement", INFO: "Information"}

# Dossiers du gabarit d'export Telegram (icônes, styles, scripts) : jamais « orphelins »
TEMPLATE_DIRS = {"css", "js", "images"}
ORPHAN_SCAN_LIMIT = 200_000
EXAMPLES = 10


def _size(n: int) -> str:
    for unit, factor in (("Go", 1e9), ("Mo", 1e6), ("Ko", 1e3)):
        if n >= factor:
            return f"{n / factor:.1f} {unit}".replace(".", ",")
    return f"{n} octets"


@dataclass
class Finding:
    severity: str
    category: str
    title: str
    count: int = 0
    details: list[str] = field(default_factory=list)
    recommendation: str = ""


@dataclass
class DiagnosticReport:
    started: str
    duration_s: float = 0.0
    checked: dict[str, int] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    cancelled: bool = False

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors and not self.warnings

    def summary(self) -> str:
        if self.cancelled:
            return "Diagnostic interrompu."
        if self.ok:
            return "Aucune anomalie bloquante."
        return f"{len(self.errors)} erreur(s), {len(self.warnings)} avertissement(s)."

    def to_markdown(self) -> str:
        out = ["# Diagnostic de la bibliothèque Telegramor", "",
               f"- Date : {self.started}", f"- Durée : {self.duration_s:.1f} s", f"- Résultat : {self.summary()}", "",
               "## Éléments contrôlés", ""]
        out += [f"- {k} : {v:,}".replace(",", " ") for k, v in self.checked.items()]
        out += ["", "## Constats", ""]
        if not self.findings:
            out.append("Aucun constat.")
        for f in sorted(self.findings, key=lambda f: SEVERITY_ORDER[f.severity]):
            out.append(f"### [{SEVERITY_LABELS[f.severity]}] {f.title}" + (f" ({f.count})" if f.count else ""))
            out.append("")
            out.append(f"Catégorie : {f.category}")
            if f.details:
                out.append("")
                out += [f"- {d}" for d in f.details]
            if f.recommendation:
                out += ["", f"Recommandation : {f.recommendation}"]
            out.append("")
        return "\n".join(out)


def run_diagnostics(db: Database, repo: LibraryRepository, scan_orphans: bool = True,
                    progress: Callable[[str, int, int], bool] | None = None) -> DiagnosticReport:
    """progress(étape, n°, total) -> False pour interrompre."""
    t0 = time.perf_counter()
    rep = DiagnosticReport(started=datetime.now().isoformat(timespec="seconds"))
    c = db.conn
    archives = repo.list_archives()
    steps: list[tuple[str, Callable[[], None]]] = []

    def step(label):
        def deco(fn):
            steps.append((label, fn))
            return fn
        return deco

    def add(*a, **kw):
        rep.findings.append(Finding(*a, **kw))

    @step("Intégrité de la base SQLite")
    def _integrity():
        rows = [r[0] for r in c.execute("PRAGMA integrity_check")]
        if rows != ["ok"]:
            add(ERROR, "Base SQLite", "Intégrité de la base compromise", len(rows), rows[:EXAMPLES],
                "Restaurer une sauvegarde (Fichier › Sauvegarde et restauration) ou réimporter les archives.")
        fk = c.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            add(ERROR, "Base SQLite", "Références incohérentes entre tables", len(fk),
                [f"table {r[0]}, ligne {r[1]} → {r[2]}" for r in fk[:EXAMPLES]],
                "Réindexer les archives concernées depuis la bibliothèque des archives.")
        v = db.version
        if v != SCHEMA_VERSION:
            add(ERROR, "Base SQLite", f"Version de schéma inattendue (v{v}, attendu v{SCHEMA_VERSION})")
        rep.checked["Tables vérifiées"] = c.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]

    @step("Index de recherche")
    def _fts():
        for table, label in (("messages_fts", "messages"), ("user_notes_fts", "notes personnelles")):
            try:
                c.execute(f"INSERT INTO {table}({table}, rank) VALUES ('integrity-check', 1)")
            except Exception as exc:  # sqlite3.DatabaseError : index désynchronisé
                add(ERROR, "Recherche", f"Index plein texte des {label} incohérent", 0, [str(exc)],
                    "Bibliothèque des archives › Reconstruire l'index de recherche.")
        rep.checked["Index plein texte"] = 2

    @step("Messages et conversations")
    def _messages():
        rep.checked["Messages"] = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        rep.checked["Conversations"] = c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        n = c.execute("""SELECT COUNT(*) FROM messages m LEFT JOIN conversations c ON c.id = m.conversation_id
                         WHERE c.id IS NULL""").fetchone()[0]
        if n:
            add(ERROR, "Messages", "Messages sans conversation identifiable", n,
                recommendation="Réindexer les archives.")
        no_date = c.execute("SELECT COUNT(*) FROM messages WHERE kind = 'default' AND date_utc IS NULL").fetchone()[0]
        if no_date:
            ex = [f"{r[0]} · message n° {r[1]}" for r in c.execute(
                """SELECT c.name, m.message_id FROM messages m JOIN conversations c ON c.id = m.conversation_id
                   WHERE m.kind = 'default' AND m.date_utc IS NULL LIMIT ?""", (EXAMPLES,))]
            add(WARNING, "Dates", "Messages sans date exploitable", no_date, ex,
                "Ces messages restent affichés mais sont exclus des filtres de dates et des statistiques.")
        empty = [r[0] for r in c.execute(
            """SELECT c.name FROM conversations c WHERE NOT EXISTS
               (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)""")]
        if empty:
            add(INFO, "Conversations", "Conversations vides", len(empty), empty[:EXAMPLES])

    @step("Relations de réponses")
    def _replies():
        total = c.execute("""SELECT COUNT(*) FROM messages WHERE kind = 'default' AND is_duplicate = 0
                             AND reply_to_message_id IS NOT NULL""").fetchone()[0]
        rep.checked["Réponses (citations)"] = total
        rows = c.execute(
            """SELECT cv.name, m.message_id, m.reply_to_message_id FROM messages m
               JOIN conversations cv ON cv.id = m.conversation_id
               WHERE m.kind = 'default' AND m.is_duplicate = 0 AND m.reply_to_message_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM messages t WHERE t.conversation_id = m.conversation_id
                                 AND t.message_id = m.reply_to_message_id)""").fetchall()
        if rows:
            add(INFO, "Fils de discussion", "Réponses dont le message d'origine est absent des archives", len(rows),
                [f"{r[0]} · message n° {r[1]} → n° {r[2]}" for r in rows[:EXAMPLES]],
                "Normal si l'export ne couvre pas toute la période : importer un export plus complet "
                "pour reconstituer ces fils.")

    @step("Archives et fichiers HTML")
    def _archives():
        rep.checked["Archives"] = len(archives)
        missing_media = 0
        examples: list[str] = []
        total_media = 0
        for a in archives:
            ir = repo.verify_archive(a.id)
            if not ir.root_exists:
                add(ERROR, "Archives", f"Archive introuvable : {a.name}", 0, [a.root_path],
                    "Brancher le support ou relocaliser l'archive (Bibliothèque des archives › Relocaliser).")
                continue
            if ir.files_missing:
                add(WARNING, "Archives", f"Fichiers HTML manquants dans « {a.name} »", len(ir.files_missing),
                    ir.files_missing[:EXAMPLES], "Vérifier l'emplacement de l'export ; ne jamais le modifier.")
            if ir.files_modified:
                add(WARNING, "Archives", f"Fichiers HTML modifiés depuis l'import dans « {a.name} »",
                    len(ir.files_modified), ir.files_modified[:EXAMPLES],
                    "Réindexer l'archive pour prendre en compte les changements.")
            total_media += ir.media_total
            missing_media += ir.media_missing
            examples += [f"{a.name} : {p}" for p in ir.media_missing_examples]
        rep.checked["Médias référencés"] = total_media
        if missing_media:
            add(WARNING, "Médias", "Médias référencés mais introuvables", missing_media, examples[:EXAMPLES],
                "Fichiers non inclus dans l'export ou déplacés : réexporter avec les médias, "
                "ou relocaliser l'archive.")

    @step("Chemins des médias")
    def _paths():
        bad = []
        for mid, aid, src, rel in c.execute(
                """SELECT md.id, m.archive_id, m.source_file, md.file_path FROM medias md
                   JOIN messages m ON m.id = md.message_pk WHERE md.file_path IS NOT NULL AND md.file_path != ''"""):
            if repo.resolve_path(aid, src, rel) is None:
                bad.append(rel)
        if bad:
            add(WARNING, "Sécurité des chemins", "Chemins de médias invalides ou hors de l'archive (ignorés)",
                len(bad), bad[:EXAMPLES],
                "Ces références (chemin absolu, URL, « ../ ») ne sont jamais ouvertes par Telegramor.")

    @step("Fichiers orphelins")
    def _orphans():
        if not scan_orphans:
            return
        referenced: dict[int, set[str]] = {}
        for aid, src, f, t in c.execute(
                """SELECT m.archive_id, m.source_file, md.file_path, md.thumbnail_path FROM medias md
                   JOIN messages m ON m.id = md.message_pk"""):
            s = referenced.setdefault(aid, set())
            for rel in (f, t):
                p = repo.resolve_path(aid, src, rel)
                if p is not None:
                    s.add(str(p))
        for aid, src, emoji in c.execute(
                """SELECT m.archive_id, m.source_file, r.emoji FROM reactions r
                   JOIN messages m ON m.id = r.message_pk WHERE r.is_custom_emoji = 1"""):
            p = repo.resolve_path(aid, src, emoji)
            if p is not None:
                referenced.setdefault(aid, set()).add(str(p))
        scanned = 0
        for a in archives:
            root = Path(a.root_path)
            if not root.is_dir():
                continue
            refs = referenced.get(a.id, set())
            orphans: list[str] = []
            size = 0
            for dirpath, dirnames, filenames in os.walk(root):
                rel_dir = Path(dirpath).relative_to(root)
                if rel_dir.parts and rel_dir.parts[0] in TEMPLATE_DIRS:
                    dirnames[:] = []
                    continue
                for name in filenames:
                    scanned += 1
                    if scanned > ORPHAN_SCAN_LIMIT:
                        break
                    if name.endswith((".html", ".htm")) or not rel_dir.parts:
                        continue          # pages de l'export et fichiers à la racine
                    full = Path(dirpath) / name
                    if str(full.resolve()) not in refs:
                        orphans.append(str(rel_dir / name))
                        try:
                            size += full.stat().st_size
                        except OSError:
                            pass
            if orphans:
                add(INFO, "Médias", f"Fichiers présents dans « {a.name} » mais référencés par aucun message",
                    len(orphans), orphans[:EXAMPLES],
                    "Fichiers laissés tels quels (aucune suppression automatique). "
                    f"Volume : {_size(size)}.")
        rep.checked["Fichiers parcourus"] = min(scanned, ORPHAN_SCAN_LIMIT)

    @step("Fichiers identiques")
    def _dups():
        from services import media_dedup
        st = media_dedup.stats(db)
        rep.checked["Empreintes de médias"] = st["hashed"]
        if st["groups"]:
            add(INFO, "Médias", "Fichiers strictement identiques présents plusieurs fois", st["groups"],
                [f"{st['extra_copies']} copie(s) supplémentaire(s), {_size(st['extra_bytes'])}"],
                "Aucune action requise : la galerie peut masquer les doublons ; les fichiers sources "
                "ne sont jamais supprimés.")
        if st["pending"]:
            add(INFO, "Médias", "Empreintes non calculées", st["pending"],
                recommendation="Galerie › Fichiers identiques › Calculer les empreintes.")

    @step("Données personnelles")
    def _personal():
        rows = c.execute(
            """SELECT 'favori', x.conversation_id, x.message_id FROM user_favorites x
               UNION ALL SELECT 'note', x.conversation_id, x.message_id FROM user_notes x
               UNION ALL SELECT 'collection', x.conversation_id, x.message_id FROM user_collection_items x""").fetchall()
        rep.checked["Données personnelles"] = len(rows)
        lost = [r for r in rows if c.execute(
            "SELECT 1 FROM messages WHERE conversation_id = ? AND message_id = ? LIMIT 1", (r[1], r[2])).fetchone() is None]
        if lost:
            add(INFO, "Données personnelles", "Favoris, notes ou éléments de collections dont le message "
                "n'est plus dans la bibliothèque", len(lost),
                [f"{r[0]} · {r[1]} · message n° {r[2]}" for r in lost[:EXAMPLES]],
                "Ils sont conservés et redeviendront accessibles si l'archive est réimportée.")

    for i, (label, fn) in enumerate(steps):
        if progress and progress(label, i, len(steps)) is False:
            rep.cancelled = True
            break
        fn()
    if progress and not rep.cancelled:
        progress("Terminé", len(steps), len(steps))
    rep.duration_s = time.perf_counter() - t0
    return rep
