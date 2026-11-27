"""Reconstitution des fils de discussion à partir des citations (reply_to).

Seules les relations présentes dans l'export sont utilisées : un message cité
absent des archives est signalé comme tel, jamais deviné.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from database.db_manager import Database

MAX_DEPTH = 200
MAX_NODES = 2000


@dataclass
class ThreadNode:
    message_id: int
    seq: int | None                    # None : message absent de la bibliothèque
    sender: str | None = None
    date_local: str | None = None
    text: str = ""
    depth: int = 0
    is_focus: bool = False
    children: list["ThreadNode"] = field(default_factory=list)


@dataclass
class Thread:
    conversation_id: str
    focus_id: int
    ancestors: list[ThreadNode]         # du plus ancien au parent direct
    missing_parent: int | None          # identifiant cité introuvable en tête de fil
    flat: list[ThreadNode]              # racine connue puis réponses, en profondeur d'abord
    truncated: bool = False

    @property
    def size(self) -> int:
        return sum(1 for n in self.flat if n.seq is not None)


def _node(r, depth=0, focus=False) -> ThreadNode:
    text = (r[4] or r[5] or "").replace("\n", " ")
    return ThreadNode(r[0], r[1], r[2], r[3], text[:200] + ("…" if len(text) > 200 else ""), depth, focus)


_SELECT = """SELECT m.message_id, m.seq, m.sender, m.date_local, m.text,
                    (SELECT md.media_type FROM medias md WHERE md.message_pk = m.id LIMIT 1),
                    m.reply_to_message_id
             FROM messages m WHERE m.conversation_id = ? AND m.is_duplicate = 0"""


def build_thread(db: Database, conversation_id: str, message_id: int) -> Thread:
    c = db.conn

    def get(mid: int):
        return c.execute(_SELECT + " AND m.message_id = ? AND m.kind = 'default'", (conversation_id, mid)).fetchone()

    focus = get(message_id)
    if focus is None:
        raise ValueError("Message introuvable dans la bibliothèque.")
    # Remonter les citations jusqu'au premier message du fil (ou jusqu'au maillon manquant)
    chain = []
    missing = None
    seen = {message_id}
    parent = focus[6]
    while parent is not None and len(chain) < MAX_DEPTH and parent not in seen:
        seen.add(parent)
        r = get(parent)
        if r is None:
            missing = parent
            break
        chain.append(r)
        parent = r[6]
    chain.reverse()
    root = chain[0] if chain else focus
    ancestors = [_node(r) for r in chain]

    # Descendre : toutes les réponses (récursivement) à partir de la racine connue
    flat: list[ThreadNode] = []
    truncated = False
    visited: set[int] = set()

    def walk(r, depth: int) -> None:
        nonlocal truncated
        if r[0] in visited:
            return
        if len(flat) >= MAX_NODES:
            truncated = True
            return
        visited.add(r[0])
        flat.append(_node(r, depth, r[0] == message_id))
        for child in c.execute(_SELECT + " AND m.reply_to_message_id = ? AND m.kind = 'default' ORDER BY m.seq",
                               (conversation_id, r[0])):
            walk(child, depth + 1)

    walk(root, 0)
    return Thread(conversation_id, message_id, ancestors, missing, flat, truncated)


def replies_count(db: Database, conversation_id: str, message_id: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND is_duplicate = 0 AND reply_to_message_id = ?",
        (conversation_id, message_id)).fetchone()[0]
