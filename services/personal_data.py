"""Données personnelles créées dans Telegramor : favoris, notes, collections,
marqueurs de lecture, historique et recherches enregistrées.

Ces données sont strictement séparées des données Telegram importées :
- elles vivent dans les tables `user_*` de la bibliothèque SQLite locale ;
- elles désignent un message par la clé stable (conversation, identifiant
  Telegram du message), qui survit à la réindexation d'une archive ;
- elles ne sont jamais écrites dans les exports Telegram ni incluses dans les
  exports de conversations (voir services/conversation_export.py).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime

from database.db_manager import Database
from database.repositories import media_label
from database.search_engine import SearchQuery

WHOLE_MESSAGE = -1          # media_ordinal d'un élément de collection désignant le message entier
HISTORY_LIMIT = 30
EXPORT_FORMAT = "telegramor-personal-data"
EXPORT_VERSION = 1


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class PersonalItem:
    """Un message (ou un média d'un message) référencé par une donnée personnelle."""
    conversation_id: str
    message_id: int
    conversation_name: str | None = None
    seq: int | None = None                 # None : message absent de la bibliothèque actuelle
    sender: str | None = None
    date_local: str | None = None
    day: str | None = None
    excerpt: str = ""
    media_type: str | None = None
    note: str | None = None
    created_at: str | None = None
    item_id: int | None = None             # élément de collection
    media_ordinal: int = WHOLE_MESSAGE
    media_path: str | None = None          # fichier du média désigné (élément de collection)

    @property
    def available(self) -> bool:
        return self.seq is not None

    @property
    def kind_label(self) -> str:
        if self.media_type:
            return (media_label(self.media_type) or "Média").split(" ", 1)[-1]
        return "Message"


@dataclass
class CollectionRow:
    id: int
    name: str
    description: str
    created_at: str
    count: int = 0


@dataclass
class SavedSearch:
    id: int
    name: str
    query: SearchQuery
    created_at: str


def query_to_json(q: SearchQuery) -> str:
    return json.dumps(asdict(q), ensure_ascii=False, sort_keys=True)


def query_from_json(s: str) -> SearchQuery:
    data = json.loads(s)
    known = {f.name for f in fields(SearchQuery)}
    return SearchQuery(**{k: v for k, v in data.items() if k in known})


def describe_query(q: SearchQuery) -> str:
    """Résumé lisible d'une recherche (historique, recherches enregistrées)."""
    parts = []
    if q.text.strip():
        parts.append(f"« {q.text.strip()} »")
    if q.sender:
        parts.append(f"de {q.sender}")
    if q.date_from or q.date_to:
        parts.append(f"{q.date_from or '…'} → {q.date_to or '…'}")
    if q.content_type:
        from database.search_engine import CONTENT_LABELS
        parts.append(CONTENT_LABELS.get(q.content_type, q.content_type).lower())
    if q.filename:
        parts.append(f"fichier « {q.filename} »")
    if q.has_link:
        parts.append("avec lien")
    if q.is_reply:
        parts.append("réponses")
    if q.conversation_ids:
        parts.append(f"{len(q.conversation_ids)} conversation(s)")
    return " · ".join(parts) or "Tous les messages"


# Sélection commune : la donnée personnelle (alias x) est jointe à la copie
# affichée du message (is_duplicate = 0) et à sa conversation. LEFT JOIN :
# un message disparu (archive supprimée) reste listé, signalé « absent ».
_ITEM_SELECT = """SELECT x.conversation_id, x.message_id, c.name, m.seq, m.sender, m.date_local, m.day,
        COALESCE(NULLIF(m.text, ''), m.service_text, ''),
        (SELECT md.media_type FROM medias md WHERE md.message_pk = m.id ORDER BY md.ordinal LIMIT 1)"""
_ITEM_JOIN = """LEFT JOIN messages m ON m.conversation_id = x.conversation_id
            AND m.message_id = x.message_id AND m.is_duplicate = 0
        LEFT JOIN conversations c ON c.id = x.conversation_id"""


def _filters(conversation_id, sender, date_from, date_to) -> tuple[list[str], list]:
    where, params = [], []
    if conversation_id:
        where.append("x.conversation_id = ?")
        params.append(conversation_id)
    if sender:
        where.append("m.sender = ?")
        params.append(sender)
    if date_from:
        where.append("m.day >= ?")
        params.append(date_from)
    if date_to:
        where.append("m.day <= ?")
        params.append(date_to)
    return where, params


def _item(r) -> PersonalItem:
    text = (r[7] or "").replace("\n", " ")
    return PersonalItem(conversation_id=r[0], message_id=r[1], conversation_name=r[2], seq=r[3],
                        sender=r[4], date_local=r[5], day=r[6],
                        excerpt=text[:240] + ("…" if len(text) > 240 else ""), media_type=r[8])


class PersonalData:
    def __init__(self, db: Database) -> None:
        self.conn = db.conn

    # ------------------------------------------------------------------ #
    # Favoris
    # ------------------------------------------------------------------ #
    def is_favorite(self, conversation_id: str, message_id: int) -> bool:
        return self.conn.execute("SELECT 1 FROM user_favorites WHERE conversation_id = ? AND message_id = ?",
                                 (conversation_id, message_id)).fetchone() is not None

    def set_favorite(self, conversation_id: str, message_id: int, on: bool = True) -> None:
        with self.conn:
            if on:
                self.conn.execute("INSERT OR IGNORE INTO user_favorites VALUES (?, ?, ?)",
                                  (conversation_id, message_id, _now()))
            else:
                self.conn.execute("DELETE FROM user_favorites WHERE conversation_id = ? AND message_id = ?",
                                  (conversation_id, message_id))

    def toggle_favorite(self, conversation_id: str, message_id: int) -> bool:
        on = not self.is_favorite(conversation_id, message_id)
        self.set_favorite(conversation_id, message_id, on)
        return on

    def favorites(self, conversation_id: str | None = None, sender: str | None = None,
                  date_from: str | None = None, date_to: str | None = None,
                  newest_first: bool = True) -> list[PersonalItem]:
        where, params = _filters(conversation_id, sender, date_from, date_to)
        order = "DESC" if newest_first else "ASC"
        rows = self.conn.execute(
            f"""{_ITEM_SELECT}, x.created_at,
                    (SELECT n.note FROM user_notes n WHERE n.conversation_id = x.conversation_id
                       AND n.message_id = x.message_id)
                FROM user_favorites x {_ITEM_JOIN}
                {'WHERE ' + ' AND '.join(where) if where else ''}
                ORDER BY m.date_utc IS NULL, m.date_utc {order}, x.created_at {order}""", params).fetchall()
        out = []
        for r in rows:
            it = _item(r)
            it.created_at, it.note = r[9], r[10]
            out.append(it)
        return out

    # ------------------------------------------------------------------ #
    # Notes
    # ------------------------------------------------------------------ #
    def note(self, conversation_id: str, message_id: int) -> str | None:
        r = self.conn.execute("SELECT note FROM user_notes WHERE conversation_id = ? AND message_id = ?",
                              (conversation_id, message_id)).fetchone()
        return r[0] if r else None

    def set_note(self, conversation_id: str, message_id: int, text: str | None) -> None:
        """Crée, modifie ou (texte vide) supprime la note d'un message."""
        text = (text or "").strip()
        with self.conn:
            if not text:
                self.conn.execute("DELETE FROM user_notes WHERE conversation_id = ? AND message_id = ?",
                                  (conversation_id, message_id))
                return
            now = _now()
            self.conn.execute(
                """INSERT INTO user_notes (conversation_id, message_id, note, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (conversation_id, message_id) DO UPDATE SET note = excluded.note,
                       updated_at = excluded.updated_at""",
                (conversation_id, message_id, text, now, now))

    def notes(self, search: str = "", conversation_id: str | None = None, sender: str | None = None,
              date_from: str | None = None, date_to: str | None = None,
              newest_first: bool = True) -> list[PersonalItem]:
        """Notes, éventuellement filtrées par recherche plein texte (accents et casse ignorés)."""
        where, params = _filters(conversation_id, sender, date_from, date_to)
        src = "user_notes x"
        match = _note_match(search)
        if match:
            src = "user_notes_fts f JOIN user_notes x ON x.id = f.rowid"
            where.insert(0, "user_notes_fts MATCH ?")
            params.insert(0, match)
        elif search.strip():
            return []
        order = "DESC" if newest_first else "ASC"
        rows = self.conn.execute(
            f"""{_ITEM_SELECT}, x.updated_at, x.note FROM {src} {_ITEM_JOIN}
                {'WHERE ' + ' AND '.join(where) if where else ''}
                ORDER BY x.updated_at {order}""", params).fetchall()
        out = []
        for r in rows:
            it = _item(r)
            it.created_at, it.note = r[9], r[10]
            out.append(it)
        return out

    # ------------------------------------------------------------------ #
    # Collections
    # ------------------------------------------------------------------ #
    def collections(self) -> list[CollectionRow]:
        return [CollectionRow(*r[:4], count=r[4]) for r in self.conn.execute(
            """SELECT c.id, c.name, c.description, c.created_at,
                      (SELECT COUNT(*) FROM user_collection_items i WHERE i.collection_id = c.id)
               FROM user_collections c ORDER BY c.name COLLATE NOCASE""")]

    def create_collection(self, name: str, description: str = "") -> int:
        name = name.strip()
        if not name:
            raise ValueError("Le nom de la collection est vide.")
        with self.conn:
            if self.conn.execute("SELECT 1 FROM user_collections WHERE name = ?", (name,)).fetchone():
                raise ValueError(f"Une collection « {name} » existe déjà.")
            cur = self.conn.execute("INSERT INTO user_collections (name, description, created_at) VALUES (?, ?, ?)",
                                    (name, description.strip(), _now()))
            return cur.lastrowid

    def update_collection(self, collection_id: int, name: str, description: str = "") -> None:
        name = name.strip()
        if not name:
            raise ValueError("Le nom de la collection est vide.")
        with self.conn:
            other = self.conn.execute("SELECT id FROM user_collections WHERE name = ?", (name,)).fetchone()
            if other and other[0] != collection_id:
                raise ValueError(f"Une collection « {name} » existe déjà.")
            self.conn.execute("UPDATE user_collections SET name = ?, description = ? WHERE id = ?",
                              (name, description.strip(), collection_id))

    def delete_collection(self, collection_id: int) -> None:
        """Supprime la collection et ses références ; les messages et fichiers sources restent intacts."""
        with self.conn:
            self.conn.execute("DELETE FROM user_collection_items WHERE collection_id = ?", (collection_id,))
            self.conn.execute("DELETE FROM user_collections WHERE id = ?", (collection_id,))

    def add_to_collection(self, collection_id: int, conversation_id: str, message_id: int,
                          media_ordinal: int = WHOLE_MESSAGE) -> bool:
        """Ajoute un élément ; retourne False s'il y figurait déjà."""
        with self.conn:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO user_collection_items
                   (collection_id, conversation_id, message_id, media_ordinal, added_at) VALUES (?, ?, ?, ?, ?)""",
                (collection_id, conversation_id, message_id, media_ordinal, _now()))
            return cur.rowcount > 0

    def remove_item(self, item_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM user_collection_items WHERE id = ?", (item_id,))

    def collections_of(self, conversation_id: str, message_id: int) -> list[str]:
        return [r[0] for r in self.conn.execute(
            """SELECT DISTINCT c.name FROM user_collection_items i JOIN user_collections c ON c.id = i.collection_id
               WHERE i.conversation_id = ? AND i.message_id = ? ORDER BY c.name COLLATE NOCASE""",
            (conversation_id, message_id))]

    def collection_items(self, collection_id: int, search: str = "", kind: str | None = None,
                         newest_first: bool = True) -> list[PersonalItem]:
        """Éléments d'une collection. kind : None, 'message', 'photo', 'video', 'file', 'link'."""
        order = "DESC" if newest_first else "ASC"
        rows = self.conn.execute(
            f"""SELECT x.conversation_id, x.message_id, c.name, m.seq, m.sender, m.date_local, m.day,
                       COALESCE(NULLIF(m.text, ''), m.service_text, ''),
                       COALESCE(sel.media_type,
                                (SELECT md.media_type FROM medias md WHERE md.message_pk = m.id
                                 ORDER BY md.ordinal LIMIT 1)),
                       x.added_at, x.id, x.media_ordinal, COALESCE(sel.title, sel.file_path), m.has_link,
                       (SELECT n.note FROM user_notes n WHERE n.conversation_id = x.conversation_id
                          AND n.message_id = x.message_id)
                FROM user_collection_items x {_ITEM_JOIN}
                LEFT JOIN medias sel ON sel.message_pk = m.id AND sel.ordinal = x.media_ordinal
                WHERE x.collection_id = ?
                ORDER BY m.date_utc IS NULL, m.date_utc {order}, x.added_at {order}""",
            (collection_id,)).fetchall()
        needle = search.strip().casefold()
        out = []
        for r in rows:
            it = _item(r)
            it.created_at, it.item_id, it.media_ordinal, it.media_path, it.note = r[9], r[10], r[11], r[12], r[14]
            if it.media_ordinal == WHOLE_MESSAGE and r[12] is None and not it.media_type:
                it.media_type = None
            if kind and _kind_of(it, bool(r[13])) != kind:
                continue
            if needle and needle not in " ".join(filter(None, (
                    it.excerpt, it.sender, it.conversation_name, it.media_path, it.note))).casefold():
                continue
            out.append(it)
        return out

    # ------------------------------------------------------------------ #
    # Marqueurs de lecture (suivi de consultation dans Telegramor)
    # ------------------------------------------------------------------ #
    def read_marker(self, conversation_id: str) -> int | None:
        r = self.conn.execute("SELECT message_id FROM user_read_markers WHERE conversation_id = ?",
                              (conversation_id,)).fetchone()
        return r[0] if r else None

    def set_read_marker(self, conversation_id: str, message_id: int) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO user_read_markers VALUES (?, ?, ?) ON CONFLICT (conversation_id)
                   DO UPDATE SET message_id = excluded.message_id, updated_at = excluded.updated_at""",
                (conversation_id, message_id, _now()))

    def advance_read_marker(self, conversation_id: str, message_id: int, seq: int) -> bool:
        """Avance le marqueur si `seq` est plus loin que la position mémorisée ; retourne True si modifié."""
        cur = self.read_marker(conversation_id)
        if cur is not None:
            r = self.conn.execute("SELECT seq FROM messages WHERE conversation_id = ? AND message_id = ? "
                                  "AND is_duplicate = 0", (conversation_id, cur)).fetchone()
            if r is not None and r[0] >= seq:
                return False
        self.set_read_marker(conversation_id, message_id)
        return True

    def clear_read_marker(self, conversation_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM user_read_markers WHERE conversation_id = ?", (conversation_id,))

    # ------------------------------------------------------------------ #
    # Historique et recherches enregistrées
    # ------------------------------------------------------------------ #
    def record_search(self, q: SearchQuery) -> None:
        if q.is_empty():
            return
        with self.conn:
            # supprimer puis réinsérer : la recherche reprend la tête de l'historique (ordre par id)
            js = query_to_json(q)
            self.conn.execute("DELETE FROM user_search_history WHERE query_json = ?", (js,))
            self.conn.execute("INSERT INTO user_search_history (query_json, used_at) VALUES (?, ?)", (js, _now()))
            self.conn.execute(
                "DELETE FROM user_search_history WHERE id NOT IN "
                "(SELECT id FROM user_search_history ORDER BY id DESC LIMIT ?)", (HISTORY_LIMIT,))

    def search_history(self) -> list[SearchQuery]:
        return [query_from_json(r[0]) for r in self.conn.execute(
            "SELECT query_json FROM user_search_history ORDER BY id DESC")]

    def clear_search_history(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM user_search_history")

    def save_search(self, name: str, q: SearchQuery) -> int:
        name = name.strip()
        if not name:
            raise ValueError("Le nom de la recherche est vide.")
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO user_saved_searches (name, query_json, created_at) VALUES (?, ?, ?)
                   ON CONFLICT (name) DO UPDATE SET query_json = excluded.query_json""",
                (name, query_to_json(q), _now()))
            return cur.lastrowid

    def saved_searches(self) -> list[SavedSearch]:
        return [SavedSearch(r[0], r[1], query_from_json(r[2]), r[3]) for r in self.conn.execute(
            "SELECT id, name, query_json, created_at FROM user_saved_searches ORDER BY name COLLATE NOCASE")]

    def delete_saved_search(self, search_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM user_saved_searches WHERE id = ?", (search_id,))

    # ------------------------------------------------------------------ #
    # Export / import (sauvegarde des données personnelles)
    # ------------------------------------------------------------------ #
    def counts(self) -> dict[str, int]:
        q = lambda t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
        return {"favoris": q("user_favorites"), "notes": q("user_notes"), "collections": q("user_collections"),
                "éléments de collections": q("user_collection_items"), "marqueurs de lecture": q("user_read_markers"),
                "recherches enregistrées": q("user_saved_searches")}

    def export_dict(self) -> dict:
        c = self.conn
        return {
            "format": EXPORT_FORMAT, "version": EXPORT_VERSION, "exported_at": _now(),
            "favorites": [dict(conversation_id=r[0], message_id=r[1], created_at=r[2])
                          for r in c.execute("SELECT * FROM user_favorites ORDER BY created_at")],
            "notes": [dict(conversation_id=r[0], message_id=r[1], note=r[2], created_at=r[3], updated_at=r[4])
                      for r in c.execute("SELECT conversation_id, message_id, note, created_at, updated_at "
                                         "FROM user_notes ORDER BY id")],
            "collections": [dict(
                name=col[1], description=col[2], created_at=col[3],
                items=[dict(conversation_id=i[0], message_id=i[1], media_ordinal=i[2], added_at=i[3])
                       for i in c.execute("SELECT conversation_id, message_id, media_ordinal, added_at "
                                          "FROM user_collection_items WHERE collection_id = ? ORDER BY id", (col[0],))])
                for col in c.execute("SELECT id, name, description, created_at FROM user_collections ORDER BY id")],
            "read_markers": [dict(conversation_id=r[0], message_id=r[1], updated_at=r[2])
                             for r in c.execute("SELECT * FROM user_read_markers")],
            "saved_searches": [dict(name=r[0], query=json.loads(r[1]), created_at=r[2])
                               for r in c.execute("SELECT name, query_json, created_at FROM user_saved_searches")],
        }

    def import_dict(self, data: dict, replace: bool = False) -> dict[str, int]:
        """Restaure des données exportées. replace=False fusionne (l'existant est conservé)."""
        if data.get("format") != EXPORT_FORMAT:
            raise ValueError("Ce fichier ne contient pas de données personnelles Telegramor.")
        if int(data.get("version", 0)) > EXPORT_VERSION:
            raise ValueError("Ces données proviennent d'une version plus récente de Telegramor.")
        c = self.conn
        added = {"favoris": 0, "notes": 0, "collections": 0, "marqueurs de lecture": 0, "recherches enregistrées": 0}
        with c:
            if replace:
                for t in ("user_collection_items", "user_collections", "user_favorites", "user_notes",
                          "user_read_markers", "user_saved_searches"):
                    c.execute(f"DELETE FROM {t}")
            for f in data.get("favorites", []):
                added["favoris"] += c.execute("INSERT OR IGNORE INTO user_favorites VALUES (?, ?, ?)",
                                              (f["conversation_id"], int(f["message_id"]),
                                               f.get("created_at") or _now())).rowcount
            for n in data.get("notes", []):
                added["notes"] += c.execute(
                    """INSERT OR IGNORE INTO user_notes (conversation_id, message_id, note, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (n["conversation_id"], int(n["message_id"]), str(n["note"]),
                     n.get("created_at") or _now(), n.get("updated_at") or _now())).rowcount
            for col in data.get("collections", []):
                row = c.execute("SELECT id FROM user_collections WHERE name = ?", (col["name"],)).fetchone()
                if row:
                    cid = row[0]
                else:
                    cid = c.execute("INSERT INTO user_collections (name, description, created_at) VALUES (?, ?, ?)",
                                    (col["name"], col.get("description", ""), col.get("created_at") or _now())).lastrowid
                    added["collections"] += 1
                for i in col.get("items", []):
                    c.execute("""INSERT OR IGNORE INTO user_collection_items
                                 (collection_id, conversation_id, message_id, media_ordinal, added_at)
                                 VALUES (?, ?, ?, ?, ?)""",
                              (cid, i["conversation_id"], int(i["message_id"]),
                               int(i.get("media_ordinal", WHOLE_MESSAGE)), i.get("added_at") or _now()))
            for r in data.get("read_markers", []):
                added["marqueurs de lecture"] += c.execute(
                    "INSERT OR IGNORE INTO user_read_markers VALUES (?, ?, ?)",
                    (r["conversation_id"], int(r["message_id"]), r.get("updated_at") or _now())).rowcount
            for s in data.get("saved_searches", []):
                added["recherches enregistrées"] += c.execute(
                    "INSERT OR IGNORE INTO user_saved_searches (name, query_json, created_at) VALUES (?, ?, ?)",
                    (s["name"], json.dumps(s["query"], ensure_ascii=False, sort_keys=True),
                     s.get("created_at") or _now())).rowcount
        return added


def _kind_of(it: PersonalItem, has_link: bool) -> str:
    t = it.media_type
    if t == "photo":
        return "photo"
    if t in ("video", "video_message", "animation"):
        return "video"
    if t in ("file", "audio", "voice"):
        return "file"
    if has_link and not t:
        return "link"
    return "message"


def _note_match(text: str) -> str | None:
    import re
    words = re.findall(r"\w+", text, re.UNICODE)
    if not words:
        return None
    return " AND ".join('"' + w.replace('"', '""') + '"*' for w in words)
