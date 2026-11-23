"""Accès aux données de la bibliothèque (écriture des imports, lectures paginées)."""

from __future__ import annotations

import hashlib
import json
import posixpath
from dataclasses import dataclass, field
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from importer.import_manager import ImportResult
from importer.media_scanner import resolve_media_path
from importer.models import Message, MessageKind

from .db_manager import FTS_INSERT_TRIGGER, Database
from .models import (
    ArchiveRow, ConversationSummary, IntegrityReport, MediaRow, MessageRow, ParticipantRow, ReactionRow, ReplyPreview,
)

VISUAL_MEDIA = ("photo", "video", "animation", "sticker", "video_message")
FILE_MEDIA = ("file", "audio", "voice")


@dataclass
class SaveSummary:
    """Bilan de l'enregistrement d'une archive dans la bibliothèque."""

    archive_id: int
    new_messages: int = 0
    duplicates: int = 0
    replaced: bool = False                 # même chemin déjà importé : contenu remplacé
    identical_to: str | None = None        # autre archive au contenu identique
    renamed: list[tuple[str, str]] = field(default_factory=list)   # (nouveau nom, nom existant)

    def to_text(self) -> str:
        lines = [" BIBLIOTHÈQUE",
                 f" Nouveaux messages          : {self.new_messages}",
                 f" Déjà présents (doublons)   : {self.duplicates}  — une seule copie est conservée à l'affichage"]
        if self.replaced:
            lines.append(" Cette archive avait déjà été importée : son contenu a été remplacé.")
        if self.identical_to:
            lines.append(f" ⚠ Contenu identique à l'archive « {self.identical_to} » (copie du même export ?).")
        for new, old in self.renamed:
            lines.append(f" Conversation « {new} » reconnue comme « {old} » (renommée) : fusionnées.")
        return "\n".join(lines)


def _ts(iso: str | None) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp() if iso else 0.0
    except ValueError:
        return 0.0


def _hash_files(root: Path, rel_paths: list[str]) -> list[tuple[str, int, str]]:
    """[(chemin relatif, taille, SHA-256)] des fichiers HTML d'une archive."""
    out = []
    for rel in sorted(set(rel_paths)):
        p = root / rel
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        out.append((rel, p.stat().st_size, h.hexdigest()))
    return out


def _content_hash(files: list[tuple[str, int, str]]) -> str:
    h = hashlib.sha256()
    for rel, _, sha in files:
        h.update(f"{posixpath.basename(rel)}:{sha}\n".encode())
    return h.hexdigest()


def _utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LibraryRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.conn = db.conn
        self._roots: dict[int, tuple[Path, str]] = {}

    # ===================================================================== #
    # Écriture
    # ===================================================================== #

    def save_import(self, result: ImportResult, source_path: str | Path) -> SaveSummary:
        """Enregistre une importation dans la bibliothèque.

        - Réimporter la même source (même chemin) remplace son contenu.
        - Les messages déjà présents via une autre archive (même identifiant
          Telegram dans la même conversation) sont conservés mais marqués
          comme doublons : une seule copie est affichée et recherchée.
        - Une conversation exportée sous un autre nom est reconnue grâce aux
          couples (identifiant, date) communs, et fusionnée.
        """
        source_path = str(Path(source_path).expanduser().resolve())
        root = result.archive_root
        report = result.report
        files = _hash_files(root, [f for conv in result.conversations for f in conv.source_files])
        content_hash = _content_hash(files)
        summary = SaveSummary(archive_id=0)
        c = self.conn
        with c:
            old = c.execute("SELECT id FROM archives WHERE source_path = ?", (source_path,)).fetchone()
            touched: set[str] = set()
            if old:
                summary.replaced = True
                touched |= {r[0] for r in c.execute(
                    "SELECT conversation_id FROM conversation_sources WHERE archive_id = ?", (old[0],))}
                c.execute("DELETE FROM archives WHERE id = ?", (old[0],))
            same = c.execute("SELECT name FROM archives WHERE content_hash = ?", (content_hash,)).fetchone()
            summary.identical_to = same[0] if same else None
            name = Path(source_path).name
            media_count = sum(len(m.media) for conv in result.conversations for m in conv.messages)
            cur = c.execute(
                """INSERT INTO archives (source_path, root_path, name, imported_at, files_parsed,
                       messages_count, media_count, first_date, last_date, report_json, content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (source_path, str(root), name, datetime.now().isoformat(timespec="seconds"),
                 report.files_parsed, report.blocks_parsed, media_count, report.first_message,
                 report.last_message, json.dumps(report.to_dict(), ensure_ascii=False, default=str),
                 content_hash))
            archive_id = summary.archive_id = cur.lastrowid
            c.executemany("INSERT INTO archive_files VALUES (?,?,?,?)",
                          [(archive_id, rel, size, sha) for rel, size, sha in files])
            # Indexation plein texte groupée : bien plus rapide que le trigger ligne par ligne.
            # Le DDL est transactionnel : en cas d'erreur, le trigger est restauré.
            c.execute("DROP TRIGGER IF EXISTS messages_ai")
            for conv in result.conversations:
                conv_id = self._resolve_conversation(conv, summary)
                touched.add(conv_id)
                c.execute("INSERT INTO conversation_sources VALUES (?,?,?,?)",
                          (conv_id, archive_id,
                           str(Path(conv.source_dir).resolve().relative_to(root.resolve())),
                           json.dumps(conv.source_files)))
                self._insert_messages(conv.messages, archive_id, conv_id)
            c.execute("INSERT INTO messages_fts(rowid, text, sender) "
                      "SELECT id, text, sender FROM messages WHERE archive_id = ?", (archive_id,))
            c.execute(FTS_INSERT_TRIGGER)
            for conv_id in touched:
                self._rebuild_conversation(conv_id)
                self._refresh_conversation(conv_id)
            total = c.execute("SELECT COUNT(*) FROM messages WHERE archive_id = ? AND kind = 'default'",
                              (archive_id,)).fetchone()[0]
            summary.duplicates = c.execute(_SHARED_SQL, (archive_id,)).fetchone()[0]
            summary.new_messages = total - summary.duplicates
        self._roots.clear()
        return summary

    def _resolve_conversation(self, conv, summary: "SaveSummary") -> str:
        """Identifiant de bibliothèque de la conversation importée (création, alias ou renommage)."""
        c = self.conn
        cid = conv.conversation_id
        if c.execute("SELECT 1 FROM conversations WHERE id = ?", (cid,)).fetchone():
            return cid
        alias = c.execute("SELECT conversation_id FROM conversation_aliases WHERE name = ?",
                          (conv.name,)).fetchone()
        if alias:
            return alias[0]
        # Renommage : couples (identifiant Telegram, date exacte) déjà connus ailleurs.
        # La date rend la correspondance sûre même pour les groupes, dont les
        # identifiants de messages recommencent à 1.
        sample = [(m.message_id, _utc(m.date)) for m in conv.messages
                  if m.kind is MessageKind.DEFAULT and m.message_id > 0 and m.date is not None][:300]
        if len(sample) >= 3:
            ids = [i for i, _ in sample]
            wanted = set(sample)
            hits: Counter[str] = Counter()
            marks = ",".join("?" * len(ids))
            for conv_id, mid, dutc in c.execute(
                    f"SELECT conversation_id, message_id, date_utc FROM messages WHERE message_id IN ({marks})", ids):
                if (mid, dutc) in wanted:
                    hits[conv_id] += 1
            if hits:
                best, n = hits.most_common(1)[0]
                if n >= max(3, len(sample) // 5):
                    old_name = c.execute("SELECT name FROM conversations WHERE id = ?", (best,)).fetchone()[0]
                    c.execute("INSERT OR REPLACE INTO conversation_aliases VALUES (?, ?)", (conv.name, best))
                    summary.renamed.append((conv.name, old_name))
                    return best
        c.execute("INSERT INTO conversations (id, name) VALUES (?, ?)", (cid, conv.name))
        return cid

    def _rebuild_conversation(self, conv_id: str) -> None:
        """Choisit la copie canonique de chaque message et recalcule l'ordre d'affichage."""
        c = self.conn
        rows = c.execute(
            """SELECT m.id, m.archive_id, m.message_id, m.kind, m.day, m.date_utc, m.position,
                      (SELECT COUNT(*) FROM medias x WHERE x.message_pk = m.id
                         AND (x.file_exists = 1 OR x.thumbnail_exists = 1)),
                      a.imported_at
               FROM messages m JOIN archives a ON a.id = m.archive_id
               WHERE m.conversation_id = ?""", (conv_id,)).fetchall()
        if not rows:
            return
        archives = {r[1] for r in rows}
        # 1. Doublons : même identifiant Telegram (> 0), ou séparateur du même jour
        groups: dict[tuple, list] = {}
        for r in rows:
            if r[3] == "date_separator":
                key = ("sep", r[4])
            elif r[2] > 0:
                key = ("msg", r[2])
            else:
                key = ("own", r[0])
            groups.setdefault(key, []).append(r)
        duplicate: set[int] = set()
        for members in groups.values():
            if len(members) > 1:
                # copie la plus complète (médias présents), sinon la plus ancienne importation
                best = max(members, key=lambda r: (r[7], -_ts(r[8]), -r[1]))
                duplicate |= {r[0] for r in members if r[0] != best[0]}
        # 2. Ordre : celui de l'export pour une seule archive ; sinon chronologique,
        #    les éléments non datés (événements) suivant l'élément qui les précède.
        keys: dict[int, tuple] = {}
        for aid in archives:
            last = ("", "", -1, 0)
            for r in sorted((r for r in rows if r[1] == aid), key=lambda r: r[6] if r[6] is not None else 0):
                if len(archives) == 1:
                    k = (r[6] or 0,)
                elif r[3] == "date_separator":
                    k = (r[4] or "", "", -1, 0)
                elif r[5]:
                    k = (r[4] or "", r[5], r[2], 0)
                else:
                    k = last[:3] + (last[3] + 1,)
                keys[r[0]] = k
                last = k if len(k) == 4 else last
        ordered = sorted((r for r in rows if r[0] not in duplicate), key=lambda r: keys[r[0]])
        ordered += sorted((r for r in rows if r[0] in duplicate), key=lambda r: keys[r[0]])
        c.executemany("UPDATE messages SET seq = ?, is_duplicate = ? WHERE id = ?",
                      [(i, int(r[0] in duplicate), r[0]) for i, r in enumerate(ordered)])

    def _insert_messages(self, msgs: list[Message], archive_id: int, conv_id: str) -> None:
        """Insertion groupée (executemany) : identifiants attribués à l'avance pour relier
        médias, réactions, références et liens sans relire chaque ligne."""
        c = self.conn
        next_id = c.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM messages").fetchone()[0]
        m_rows, md_rows, r_rows, ref_rows, l_rows = [], [], [], [], []
        for k, m in enumerate(msgs):
            pk = next_id + k
            dt = m.date
            sep = m.separator_date.isoformat() if m.separator_date else None
            m_rows.append((
                pk, conv_id, archive_id, m.position, m.message_id, m.html_id, m.source_file, m.kind.value,
                int(m.is_joined), m.sender, int(m.sender_inherited), m.sender_initials, m.sender_userpic_class,
                dt.isoformat() if dt else None, _utc(dt), dt.date().isoformat() if dt else sep,
                m.date_raw, m.timezone, m.utc_offset_minutes, m.edited_raw, sep, m.text, m.html, m.service_text,
                m.reply_to_message_id, m.reply_to_file, m.reply_raw, m.forwarded_from, m.forwarded_date_raw,
                m.via_bot, m.signature, int(bool(m.media)), int(bool(m.links)),
                json.dumps(m.warnings, ensure_ascii=False) if m.warnings else None, m.position))
            for i, md in enumerate(m.media):
                md_rows.append((
                    pk, conv_id, i, md.media_type.value, md.file_path, md.thumbnail_path, md.duration_raw,
                    md.duration_seconds, md.title, md.description, md.status, md.thumb_width, md.thumb_height,
                    int(md.not_included), md.css_class, None if md.file_exists is None else int(md.file_exists),
                    None if md.thumbnail_exists is None else int(md.thumbnail_exists), md.file_size))
            for r in m.reactions:
                r_rows.append((pk, r.emoji, r.count, json.dumps(r.users, ensure_ascii=False),
                               int(r.is_custom_emoji), int(r.active)))
            if m.reply_to_message_id is not None:
                ref_rows.append((pk, "reply" if m.kind is MessageKind.DEFAULT else "service_link",
                                 m.reply_to_message_id, m.reply_to_file))
            l_rows.extend((pk, url) for url in m.links)
        c.executemany(
            """INSERT INTO messages (id, conversation_id, archive_id, seq, message_id, html_id, source_file,
                   kind, is_joined, sender, sender_inherited, sender_initials, sender_userpic,
                   date_local, date_utc, day, date_raw, timezone, utc_offset_minutes, edited_raw,
                   separator_date, text, html, service_text, reply_to_message_id, reply_to_file,
                   reply_raw, forwarded_from, forwarded_date_raw, via_bot, signature, has_media,
                   has_link, warnings, position)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", m_rows)
        c.executemany(
            """INSERT INTO medias (message_pk, conversation_id, ordinal, media_type, file_path,
                   thumbnail_path, duration_raw, duration_seconds, title, description, status,
                   thumb_width, thumb_height, not_included, css_class, file_exists,
                   thumbnail_exists, file_size) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", md_rows)
        c.executemany("INSERT INTO reactions (message_pk, emoji, count, users, is_custom_emoji, active)"
                      " VALUES (?,?,?,?,?,?)", r_rows)
        c.executemany("INSERT INTO message_references (message_pk, ref_type, target_message_id, target_file)"
                      " VALUES (?,?,?,?)", ref_rows)
        c.executemany("INSERT INTO links (message_pk, url) VALUES (?,?)", l_rows)

    def _insert_message(self, m: Message, archive_id: int, seq: int, conv_id: str | None = None) -> None:
        c = self.conn
        dt = m.date
        conv_id = conv_id or m.conversation_id
        cur = c.execute(
            """INSERT INTO messages (conversation_id, archive_id, seq, message_id, html_id, source_file,
                   kind, is_joined, sender, sender_inherited, sender_initials, sender_userpic,
                   date_local, date_utc, day, date_raw, timezone, utc_offset_minutes, edited_raw,
                   separator_date, text, html, service_text, reply_to_message_id, reply_to_file,
                   reply_raw, forwarded_from, forwarded_date_raw, via_bot, signature, has_media,
                   has_link, warnings, position)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (conv_id, archive_id, seq, m.message_id, m.html_id, m.source_file,
             m.kind.value, int(m.is_joined), m.sender, int(m.sender_inherited), m.sender_initials,
             m.sender_userpic_class, dt.isoformat() if dt else None, _utc(dt),
             dt.date().isoformat() if dt else (m.separator_date.isoformat() if m.separator_date else None),
             m.date_raw, m.timezone, m.utc_offset_minutes, m.edited_raw,
             m.separator_date.isoformat() if m.separator_date else None,
             m.text, m.html, m.service_text, m.reply_to_message_id, m.reply_to_file, m.reply_raw,
             m.forwarded_from, m.forwarded_date_raw, m.via_bot, m.signature, int(bool(m.media)),
             int(bool(m.links)), json.dumps(m.warnings, ensure_ascii=False) if m.warnings else None,
             m.position))
        pk = cur.lastrowid
        for i, md in enumerate(m.media):
            c.execute(
                """INSERT INTO medias (message_pk, conversation_id, ordinal, media_type, file_path,
                       thumbnail_path, duration_raw, duration_seconds, title, description, status,
                       thumb_width, thumb_height, not_included, css_class, file_exists,
                       thumbnail_exists, file_size) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pk, conv_id, i, md.media_type.value, md.file_path, md.thumbnail_path,
                 md.duration_raw, md.duration_seconds, md.title, md.description, md.status,
                 md.thumb_width, md.thumb_height, int(md.not_included), md.css_class,
                 None if md.file_exists is None else int(md.file_exists),
                 None if md.thumbnail_exists is None else int(md.thumbnail_exists), md.file_size))
        for r in m.reactions:
            c.execute("INSERT INTO reactions (message_pk, emoji, count, users, is_custom_emoji, active)"
                      " VALUES (?,?,?,?,?,?)",
                      (pk, r.emoji, r.count, json.dumps(r.users, ensure_ascii=False),
                       int(r.is_custom_emoji), int(r.active)))
        if m.reply_to_message_id is not None:
            ref_type = "reply" if m.kind is MessageKind.DEFAULT else "service_link"
            c.execute("INSERT INTO message_references (message_pk, ref_type, target_message_id, target_file)"
                      " VALUES (?,?,?,?)", (pk, ref_type, m.reply_to_message_id, m.reply_to_file))
        for url in m.links:
            c.execute("INSERT INTO links (message_pk, url) VALUES (?,?)", (pk, url))

    def _refresh_conversation(self, conv_id: str) -> None:
        c = self.conn
        n = c.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND kind = 'default' "
                      "AND is_duplicate = 0",
                      (conv_id,)).fetchone()[0]
        if n == 0 and not c.execute("SELECT 1 FROM messages WHERE conversation_id = ? LIMIT 1",
                                    (conv_id,)).fetchone():
            c.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            return
        first, last = c.execute(
            "SELECT MIN(date_utc), MAX(date_utc) FROM messages WHERE conversation_id = ? AND kind='default' "
            "AND is_duplicate = 0",
            (conv_id,)).fetchone()
        lastrow = c.execute(
            """SELECT m.text, m.sender, (SELECT media_type FROM medias WHERE message_pk = m.id LIMIT 1)
               FROM messages m WHERE conversation_id = ? AND kind = 'default' AND is_duplicate = 0
               ORDER BY seq DESC LIMIT 1""", (conv_id,)).fetchone()
        preview = sender = None
        if lastrow:
            preview = lastrow[0] or _media_label(lastrow[2])
            sender = lastrow[1]
        media_count = c.execute("SELECT COUNT(*) FROM medias x JOIN messages m ON m.id = x.message_pk "
                                "WHERE x.conversation_id = ? AND m.is_duplicate = 0", (conv_id,)).fetchone()[0]
        c.execute("""UPDATE conversations SET message_count=?, media_count=?, first_date=?, last_date=?,
                     last_preview=?, last_sender=? WHERE id=?""",
                  (n, media_count, first, last, (preview or "")[:200], sender, conv_id))
        c.execute("DELETE FROM participants WHERE conversation_id = ?", (conv_id,))
        c.execute(
            """INSERT INTO participants (conversation_id, name, message_count, initials, userpic_class,
                   first_date, last_date)
               SELECT conversation_id, sender, COUNT(*),
                      MAX(CASE WHEN sender_inherited = 0 THEN sender_initials END),
                      MAX(CASE WHEN sender_inherited = 0 THEN sender_userpic END),
                      MIN(date_utc), MAX(date_utc)
               FROM messages WHERE conversation_id = ? AND sender IS NOT NULL AND kind = 'default'
                 AND is_duplicate = 0
               GROUP BY sender""", (conv_id,))

    # ===================================================================== #
    # Gestion des archives
    # ===================================================================== #

    def get_archive(self, archive_id: int) -> ArchiveRow | None:
        return next((a for a in self.list_archives() if a.id == archive_id), None)

    def rename_archive(self, archive_id: int, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Le nom ne peut pas être vide.")
        with self.conn:
            self.conn.execute("UPDATE archives SET name = ? WHERE id = ?", (name, archive_id))
        self._roots.clear()

    def check_relocation(self, archive_id: int, new_path: str | Path) -> tuple[list[str], list[str]]:
        """Vérifie qu'un nouvel emplacement contient bien l'archive.

        Retourne (fichiers manquants, fichiers différents) : listes vides = emplacement valide.
        """
        new_path = Path(new_path).expanduser().resolve()
        root = new_path.parent if new_path.is_file() else new_path
        missing, changed = [], []
        for rel, size, sha in self.conn.execute(
                "SELECT rel_path, size, sha256 FROM archive_files WHERE archive_id = ?", (archive_id,)):
            p = root / rel
            if not p.is_file():
                missing.append(rel)
            elif p.stat().st_size != size or _hash_files(root, [rel])[0][2] != sha:
                changed.append(rel)
        return missing, changed

    def relocate_archive(self, archive_id: int, new_path: str | Path, force: bool = False) -> None:
        """Met à jour l'emplacement d'une archive déplacée (les chemins des médias restent relatifs)."""
        new_path = Path(new_path).expanduser().resolve()
        missing, changed = self.check_relocation(archive_id, new_path)
        if (missing or changed) and not force:
            raise ValueError(f"Emplacement non conforme : {len(missing)} fichier(s) manquant(s), "
                             f"{len(changed)} différent(s).")
        a = self.get_archive(archive_id)
        old_source = Path(a.source_path)
        # Une archive importée depuis un fichier garde ce fichier comme source
        if new_path.is_dir() and old_source.suffix.lower() in (".html", ".htm"):
            source, root = new_path / old_source.name, new_path
        else:
            source, root = new_path, (new_path.parent if new_path.is_file() else new_path)
        with self.conn:
            self.conn.execute("UPDATE archives SET source_path = ?, root_path = ? WHERE id = ?",
                              (str(source), str(root), archive_id))
        self._roots.clear()
        self.refresh_media_status(archive_id)

    def refresh_media_status(self, archive_id: int) -> tuple[int, int, list[str]]:
        """Revérifie la présence des médias d'une archive. Retourne (total, manquants, exemples)."""
        rows = self.conn.execute(
            """SELECT x.id, x.file_path, x.thumbnail_path, x.not_included, m.source_file
               FROM medias x JOIN messages m ON m.id = x.message_pk WHERE m.archive_id = ?""",
            (archive_id,)).fetchall()
        updates, missing, examples = [], 0, []
        for mid, fpath, tpath, not_inc, src in rows:
            fp = self._resolve(archive_id, src, fpath)
            tp = self._resolve(archive_id, src, tpath)
            f_ok = None if not fpath else bool(fp and fp.is_file())
            t_ok = None if not tpath else bool(tp and tp.is_file())
            if fpath and not f_ok and not not_inc:
                missing += 1
                if len(examples) < 10:
                    examples.append(fpath)
            updates.append((None if f_ok is None else int(f_ok), None if t_ok is None else int(t_ok), mid))
        with self.conn:
            self.conn.executemany("UPDATE medias SET file_exists = ?, thumbnail_exists = ? WHERE id = ?", updates)
        return len(rows), missing, examples

    def verify_archive(self, archive_id: int) -> IntegrityReport:
        """Contrôle d'intégrité : présence et empreinte des fichiers HTML, présence des médias."""
        a = self.get_archive(archive_id)
        root = Path(a.root_path)
        rep = IntegrityReport(archive_id, root.is_dir())
        if not rep.root_exists:
            return rep
        missing, changed = self.check_relocation(archive_id, root)
        total = self.conn.execute("SELECT COUNT(*) FROM archive_files WHERE archive_id = ?",
                                  (archive_id,)).fetchone()[0]
        rep.files_missing, rep.files_modified = missing, changed
        rep.files_ok = total - len(missing) - len(changed)
        rep.media_total, rep.media_missing, rep.media_missing_examples = self.refresh_media_status(archive_id)
        return rep

    def backfill_file_hashes(self) -> int:
        """Calcule les empreintes manquantes (archives importées avant le schéma v2)."""
        done = 0
        todo = self.conn.execute(
            """SELECT a.id, a.root_path FROM archives a
               WHERE NOT EXISTS (SELECT 1 FROM archive_files f WHERE f.archive_id = a.id)""").fetchall()
        for aid, root in todo:
            root = Path(root)
            if not root.is_dir():
                continue
            rels = [rel for (files,) in self.conn.execute(
                "SELECT source_files FROM conversation_sources WHERE archive_id = ?", (aid,))
                for rel in json.loads(files)]
            try:
                files = _hash_files(root, rels)
            except OSError:
                continue
            with self.conn:
                self.conn.executemany("INSERT OR IGNORE INTO archive_files VALUES (?,?,?,?)",
                                      [(aid, rel, size, sha) for rel, size, sha in files])
                self.conn.execute("UPDATE archives SET content_hash = ? WHERE id = ?", (_content_hash(files), aid))
            done += 1
        return done

    def rebuild_search_index(self) -> None:
        """Reconstruit entièrement l'index plein texte (FTS5) et optimise la base."""
        with self.conn:
            self.conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
            self.conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('optimize')")
        self.conn.execute("PRAGMA optimize")

    def delete_archive(self, archive_id: int) -> None:
        with self.conn:
            touched = [r[0] for r in self.conn.execute(
                "SELECT conversation_id FROM conversation_sources WHERE archive_id = ?", (archive_id,))]
            self.conn.execute("DELETE FROM archives WHERE id = ?", (archive_id,))
            for conv_id in touched:
                # les doublons des autres archives redeviennent visibles si besoin
                self._rebuild_conversation(conv_id)
                self._refresh_conversation(conv_id)
        self._roots.clear()

    # ===================================================================== #
    # Lecture : bibliothèque
    # ===================================================================== #

    def list_archives(self) -> list[ArchiveRow]:
        rows = self.conn.execute(
            f"""SELECT a.id, a.source_path, a.root_path, a.name, a.imported_at, a.files_parsed,
                      (SELECT COUNT(*) FROM messages m WHERE m.archive_id = a.id AND m.kind = 'default'),
                      a.media_count, a.first_date, a.last_date,
                      (SELECT COUNT(*) FROM conversation_sources s WHERE s.archive_id = a.id),
                      ({_SHARED_SQL.replace("?", "a.id")})
               FROM archives a ORDER BY a.first_date, a.imported_at""").fetchall()
        return [ArchiveRow(*r[:10], conversations=r[10], duplicates=r[11],
                           root_exists=Path(r[2]).is_dir()) for r in rows]

    def list_conversations(self, archive_id: int | None = None) -> list[ConversationSummary]:
        where, params = "", ()
        if archive_id is not None:
            where = "WHERE c.id IN (SELECT conversation_id FROM conversation_sources WHERE archive_id = ?)"
            params = (archive_id,)
        rows = self.conn.execute(
            f"""SELECT c.id, c.name, c.message_count, c.media_count, c.first_date, c.last_date,
                      c.last_preview, c.last_sender,
                      (SELECT GROUP_CONCAT(a.name, ' | ') FROM conversation_sources s
                       JOIN archives a ON a.id = s.archive_id WHERE s.conversation_id = c.id)
               FROM conversations c {where} ORDER BY c.last_date DESC""", params).fetchall()
        return [ConversationSummary(*r[:8], archives=(r[8] or "").split(" | ") if r[8] else [])
                for r in rows]

    def get_conversation(self, conv_id: str) -> ConversationSummary | None:
        return next((c for c in self.list_conversations() if c.id == conv_id), None)

    def participants(self, conv_id: str) -> list[ParticipantRow]:
        rows = self.conn.execute(
            "SELECT name, message_count, initials, userpic_class, first_date, last_date FROM participants "
            "WHERE conversation_id = ? ORDER BY message_count DESC", (conv_id,)).fetchall()
        return [ParticipantRow(*r) for r in rows]

    def detect_owner(self) -> str | None:
        """Devine le titulaire du compte : personne figurant dans les réactions « actives »."""
        counter: Counter[str] = Counter()
        for (users,) in self.conn.execute("SELECT users FROM reactions WHERE active = 1 AND users IS NOT NULL"):
            try:
                counter.update(json.loads(users))
            except ValueError:
                continue
        return counter.most_common(1)[0][0] if counter else None

    def library_stats(self) -> dict[str, int]:
        q = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "archives": q("SELECT COUNT(*) FROM archives"),
            "conversations": q("SELECT COUNT(*) FROM conversations"),
            "messages": q("SELECT COUNT(*) FROM messages WHERE kind = 'default' AND is_duplicate = 0"),
            "duplicates": q("SELECT COUNT(*) FROM messages WHERE kind = 'default' AND is_duplicate = 1"),
            "medias": q("SELECT COUNT(*) FROM medias x JOIN messages m ON m.id = x.message_pk WHERE m.is_duplicate = 0"),
        }

    # ===================================================================== #
    # Lecture : messages (pagination par seq)
    # ===================================================================== #

    def seq_bounds(self, conv_id: str) -> tuple[int, int] | None:
        r = self.conn.execute("SELECT MIN(seq), MAX(seq) FROM messages WHERE conversation_id = ? AND is_duplicate = 0",
                              (conv_id,)).fetchone()
        return None if r[0] is None else (r[0], r[1])

    def messages_between(self, conv_id: str, seq_from: int, seq_to: int) -> list[MessageRow]:
        """Messages dont seq ∈ [seq_from, seq_to], dans l'ordre."""
        rows = self.conn.execute(
            _MESSAGE_SELECT + " WHERE m.conversation_id = ? AND m.is_duplicate = 0 AND m.seq BETWEEN ? AND ? ORDER BY m.seq",
            (conv_id, seq_from, seq_to)).fetchall()
        return self._hydrate(rows)

    def messages_before(self, conv_id: str, seq: int, limit: int) -> list[MessageRow]:
        rows = self.conn.execute(
            _MESSAGE_SELECT + " WHERE m.conversation_id = ? AND m.is_duplicate = 0 AND m.seq < ? ORDER BY m.seq DESC LIMIT ?",
            (conv_id, seq, limit)).fetchall()
        return self._hydrate(list(reversed(rows)))

    def messages_after(self, conv_id: str, seq: int, limit: int) -> list[MessageRow]:
        rows = self.conn.execute(
            _MESSAGE_SELECT + " WHERE m.conversation_id = ? AND m.is_duplicate = 0 AND m.seq > ? ORDER BY m.seq LIMIT ?",
            (conv_id, seq, limit)).fetchall()
        return self._hydrate(rows)

    def seq_of_message(self, conv_id: str, message_id: int) -> int | None:
        r = self.conn.execute("SELECT seq FROM messages WHERE conversation_id = ? AND message_id = ? AND is_duplicate = 0 "
                              "ORDER BY seq LIMIT 1", (conv_id, message_id)).fetchone()
        return r[0] if r else None

    def seq_for_day(self, conv_id: str, day: str) -> int | None:
        """Premier élément du jour donné (ou du premier jour suivant ayant des messages)."""
        r = self.conn.execute(
            "SELECT seq FROM messages WHERE conversation_id = ? AND is_duplicate = 0 AND day >= ? "
            "ORDER BY day, seq LIMIT 1",
            (conv_id, day)).fetchone()
        if r:
            return r[0]
        b = self.seq_bounds(conv_id)
        return b[1] if b else None

    def days_with_messages(self, conv_id: str) -> dict[str, int]:
        return {d: n for d, n in self.conn.execute(
            "SELECT day, COUNT(*) FROM messages WHERE conversation_id = ? AND kind = 'default' AND is_duplicate = 0 "
            "AND day IS NOT NULL GROUP BY day", (conv_id,))}

    def month_index(self, conv_id: str) -> list[tuple[str, int]]:
        """[(AAAA-MM, nombre de messages)] pour la navigation par mois."""
        return [tuple(r) for r in self.conn.execute(
            "SELECT substr(day, 1, 7) AS ym, COUNT(*) FROM messages WHERE conversation_id = ? "
            "AND kind = 'default' AND is_duplicate = 0 AND day IS NOT NULL GROUP BY ym ORDER BY ym", (conv_id,))]

    def message_by_seq(self, conv_id: str, seq: int) -> MessageRow | None:
        rows = self.messages_between(conv_id, seq, seq)
        return rows[0] if rows else None

    # ===================================================================== #
    # Lecture : médias, fichiers, liens
    # ===================================================================== #

    def medias(self, conv_id: str, types: tuple[str, ...]) -> list[MediaRow]:
        marks = ",".join("?" * len(types))
        rows = self.conn.execute(
            f"""SELECT md.*, m.archive_id, m.source_file, m.seq, m.date_local, m.sender
                FROM medias md JOIN messages m ON m.id = md.message_pk
                WHERE md.conversation_id = ? AND m.is_duplicate = 0 AND md.media_type IN ({marks})
                ORDER BY m.seq, md.ordinal""", (conv_id, *types)).fetchall()
        out = []
        for r in rows:
            mr = self._media_row(r, r["archive_id"], r["source_file"])
            mr.message_seq, mr.message_date, mr.message_sender = r["seq"], r["date_local"], r["sender"]
            out.append(mr)
        return out

    def _gallery_where(self, types, conversation_id, sender, year, archive_id) -> tuple[str, list]:
        where = ["m.is_duplicate = 0", f"md.media_type IN ({','.join('?' * len(types))})"]
        params: list = list(types)
        if conversation_id:
            where.append("m.conversation_id = ?")
            params.append(conversation_id)
        if sender:
            where.append("m.sender = ?")
            params.append(sender)
        if year:
            where.append("substr(m.day, 1, 4) = ?")
            params.append(str(year))
        if archive_id is not None:
            where.append("m.archive_id = ?")
            params.append(archive_id)
        return " AND ".join(where), params

    def gallery_count(self, types: tuple[str, ...], conversation_id: str | None = None, sender: str | None = None,
                      year: str | None = None, archive_id: int | None = None) -> int:
        w, p = self._gallery_where(types, conversation_id, sender, year, archive_id)
        return self.conn.execute(
            f"SELECT COUNT(*) FROM medias md JOIN messages m ON m.id = md.message_pk WHERE {w}", p).fetchone()[0]

    def gallery_page(self, types: tuple[str, ...], conversation_id: str | None = None, sender: str | None = None,
                     year: str | None = None, archive_id: int | None = None, newest_first: bool = True,
                     offset: int = 0, limit: int = 200) -> list[MediaRow]:
        """Médias de toute la bibliothèque (ou d'une conversation), paginés, avec leur contexte."""
        w, p = self._gallery_where(types, conversation_id, sender, year, archive_id)
        order = "DESC" if newest_first else "ASC"
        rows = self.conn.execute(
            f"""SELECT md.*, m.archive_id, m.source_file, m.seq, m.date_local, m.sender, m.conversation_id AS cid,
                       c.name AS cname
                FROM medias md JOIN messages m ON m.id = md.message_pk
                JOIN conversations c ON c.id = m.conversation_id
                WHERE {w} ORDER BY m.date_utc {order}, m.seq {order}, md.ordinal LIMIT ? OFFSET ?""",
            (*p, limit, offset)).fetchall()
        out = []
        for r in rows:
            mr = self._media_row(r, r["archive_id"], r["source_file"])
            mr.message_seq, mr.message_date, mr.message_sender = r["seq"], r["date_local"], r["sender"]
            mr.conversation_id, mr.conversation_name, mr.file_size = r["cid"], r["cname"], r["file_size"]
            out.append(mr)
        return out

    def all_links(self, conversation_id: str | None = None, sender: str | None = None, year: str | None = None,
                  archive_id: int | None = None, newest_first: bool = True, offset: int = 0,
                  limit: int = 500) -> list[tuple]:
        """[(url, conversation_id, nom, seq, date, expéditeur)]"""
        where, params = ["m.is_duplicate = 0"], []
        for cond, val in (("m.conversation_id = ?", conversation_id), ("m.sender = ?", sender),
                          ("substr(m.day, 1, 4) = ?", year), ("m.archive_id = ?", archive_id)):
            if val is not None and val != "":
                where.append(cond)
                params.append(val)
        order = "DESC" if newest_first else "ASC"
        return [tuple(r) for r in self.conn.execute(
            f"""SELECT l.url, m.conversation_id, c.name, m.seq, m.date_local, m.sender FROM links l
                JOIN messages m ON m.id = l.message_pk JOIN conversations c ON c.id = m.conversation_id
                WHERE {' AND '.join(where)} ORDER BY m.date_utc {order} LIMIT ? OFFSET ?""",
            (*params, limit, offset))]

    def years(self, conversation_id: str | None = None) -> list[str]:
        q = "SELECT DISTINCT substr(day, 1, 4) FROM messages WHERE is_duplicate = 0 AND day IS NOT NULL"
        p: tuple = ()
        if conversation_id:
            q += " AND conversation_id = ?"
            p = (conversation_id,)
        return [r[0] for r in self.conn.execute(q + " ORDER BY 1 DESC", p)]

    def links(self, conv_id: str) -> list[tuple[str, int, str | None, str | None]]:
        """[(url, seq, date, expéditeur)]"""
        return [tuple(r) for r in self.conn.execute(
            """SELECT l.url, m.seq, m.date_local, m.sender FROM links l
               JOIN messages m ON m.id = l.message_pk WHERE m.conversation_id = ? AND m.is_duplicate = 0
               ORDER BY m.seq""",
            (conv_id,))]

    # ===================================================================== #
    # Interne
    # ===================================================================== #

    def _root(self, archive_id: int) -> tuple[Path, str]:
        if archive_id not in self._roots:
            r = self.conn.execute("SELECT root_path, name FROM archives WHERE id = ?", (archive_id,)).fetchone()
            self._roots[archive_id] = (Path(r[0]), r[1])
        return self._roots[archive_id]

    def _resolve(self, archive_id: int, source_file: str, rel: str | None) -> Path | None:
        if not rel:
            return None
        root, _ = self._root(archive_id)
        base = root / posixpath.dirname(source_file)
        path, err = resolve_media_path(base, root, rel)
        return None if err else path

    def _media_row(self, r, archive_id: int, source_file: str) -> MediaRow:
        return MediaRow(
            id=r["id"], media_type=r["media_type"], file_path=r["file_path"],
            thumbnail_path=r["thumbnail_path"],
            abs_file=self._resolve(archive_id, source_file, r["file_path"]),
            abs_thumbnail=self._resolve(archive_id, source_file, r["thumbnail_path"]),
            duration_raw=r["duration_raw"], title=r["title"], description=r["description"],
            status=r["status"], thumb_width=r["thumb_width"], thumb_height=r["thumb_height"],
            not_included=bool(r["not_included"]))

    def _hydrate(self, rows) -> list[MessageRow]:
        if not rows:
            return []
        pks = [r["id"] for r in rows]
        marks = ",".join("?" * len(pks))
        by_pk = {r["id"]: r for r in rows}
        medias: dict[int, list[MediaRow]] = {}
        for md in self.conn.execute(f"SELECT * FROM medias WHERE message_pk IN ({marks}) ORDER BY ordinal", pks):
            src = by_pk[md["message_pk"]]
            medias.setdefault(md["message_pk"], []).append(self._media_row(md, src["archive_id"], src["source_file"]))
        reactions: dict[int, list[ReactionRow]] = {}
        for rc in self.conn.execute(f"SELECT * FROM reactions WHERE message_pk IN ({marks}) ORDER BY id", pks):
            src = by_pk[rc["message_pk"]]
            img = self._resolve(src["archive_id"], src["source_file"], rc["emoji"]) if rc["is_custom_emoji"] else None
            reactions.setdefault(rc["message_pk"], []).append(ReactionRow(
                rc["emoji"], rc["count"], json.loads(rc["users"] or "[]"), bool(rc["is_custom_emoji"]),
                bool(rc["active"]), img))
        links: dict[int, list[str]] = {}
        for lk in self.conn.execute(f"SELECT message_pk, url FROM links WHERE message_pk IN ({marks})", pks):
            links.setdefault(lk[0], []).append(lk[1])

        # Aperçus des messages cités
        conv_id = rows[0]["conversation_id"]
        targets = {r["reply_to_message_id"] for r in rows
                   if r["reply_to_message_id"] is not None and r["kind"] == "default"}
        previews: dict[int, ReplyPreview] = {}
        if targets:
            tm = ",".join("?" * len(targets))
            for t in self.conn.execute(
                    f"""SELECT m.message_id, m.seq, m.sender, m.text,
                               (SELECT media_type FROM medias WHERE message_pk = m.id LIMIT 1)
                        FROM messages m WHERE m.conversation_id = ? AND m.is_duplicate = 0
                          AND m.message_id IN ({tm})""",
                    (conv_id, *targets)):
                previews.setdefault(t[0], ReplyPreview(t[0], t[1], t[2], t[3] or "", t[4]))

        out = []
        for r in rows:
            _, archive_name = self._root(r["archive_id"])
            mr = MessageRow(
                pk=r["id"], conversation_id=r["conversation_id"], seq=r["seq"], message_id=r["message_id"],
                kind=r["kind"], is_joined=bool(r["is_joined"]), sender=r["sender"],
                sender_initials=r["sender_initials"], sender_userpic=r["sender_userpic"],
                date_local=r["date_local"], day=r["day"], timezone=r["timezone"], edited_raw=r["edited_raw"],
                separator_date=r["separator_date"], text=r["text"], html=r["html"],
                service_text=r["service_text"], reply_to_message_id=r["reply_to_message_id"],
                reply_raw=r["reply_raw"], forwarded_from=r["forwarded_from"], via_bot=r["via_bot"],
                signature=r["signature"], archive_name=archive_name,
                media=medias.get(r["id"], []), reactions=reactions.get(r["id"], []),
                links=links.get(r["id"], []))
            if r["reply_to_message_id"] is not None and r["kind"] == "default":
                mr.reply = previews.get(r["reply_to_message_id"]) or ReplyPreview(
                    r["reply_to_message_id"], None, None, r["reply_raw"] or "Message introuvable", None)
            out.append(mr)
        return out


_MESSAGE_SELECT = "SELECT m.* FROM messages m"

# Messages d'une archive également présents (même conversation, même identifiant) dans une autre
_SHARED_SQL = """SELECT COUNT(*) FROM messages m WHERE m.archive_id = ? AND m.kind = 'default'
    AND m.message_id > 0 AND EXISTS (SELECT 1 FROM messages o WHERE o.conversation_id = m.conversation_id
    AND o.message_id = m.message_id AND o.archive_id != m.archive_id)"""

_MEDIA_LABELS = {
    "photo": "🖼 Photo", "video": "🎬 Vidéo", "animation": "GIF", "sticker": "Autocollant",
    "voice": "🎤 Message vocal", "video_message": "📹 Message vidéo", "audio": "🎵 Audio",
    "file": "📎 Fichier", "location": "📍 Position", "contact": "👤 Contact", "call": "📞 Appel",
    "poll": "📊 Sondage", "game": "🎮 Jeu", "invoice": "🧾 Facture",
}


def _media_label(media_type: str | None) -> str | None:
    return _MEDIA_LABELS.get(media_type or "", "Pièce jointe" if media_type else None)


media_label = _media_label
