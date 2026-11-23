"""Connexion SQLite et migrations de schéma.

Le numéro de version du schéma est stocké dans `PRAGMA user_version`.
Chaque migration est une liste d'instructions SQL appliquées dans une
transaction ; pour faire évoluer le schéma, ajouter une entrée à MIGRATIONS
(ne jamais modifier une migration déjà publiée).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

APP_DIR_NAME = "telegram-archive-explorer"
DB_FILE_NAME = "bibliotheque.sqlite"


def default_db_path() -> Path:
    """~/.local/share/telegram-archive-explorer/bibliotheque.sqlite (ou $TAE_DB)."""
    env = os.environ.get("TAE_DB")
    if env:
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_DIR_NAME / DB_FILE_NAME


# Trigger d'indexation plein texte des nouveaux messages. Il est suspendu
# pendant les imports en masse (voir LibraryRepository.save_import).
FTS_INSERT_TRIGGER = """CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, text, sender) VALUES (new.id, new.text, new.sender);
        END"""

MIGRATIONS: list[list[str]] = [
    # --- v1 : schéma initial ------------------------------------------------
    [
        """CREATE TABLE archives (
            id              INTEGER PRIMARY KEY,
            source_path     TEXT NOT NULL UNIQUE,   -- chemin choisi à l'import (dossier ou fichier)
            root_path       TEXT NOT NULL,          -- racine pour résoudre les chemins relatifs
            name            TEXT NOT NULL,
            imported_at     TEXT NOT NULL,
            files_parsed    INTEGER NOT NULL DEFAULT 0,
            messages_count  INTEGER NOT NULL DEFAULT 0,
            media_count     INTEGER NOT NULL DEFAULT 0,
            first_date      TEXT,
            last_date       TEXT,
            report_json     TEXT
        )""",
        """CREATE TABLE conversations (
            id                   TEXT PRIMARY KEY,
            name                 TEXT NOT NULL,
            message_count        INTEGER NOT NULL DEFAULT 0,
            media_count          INTEGER NOT NULL DEFAULT 0,
            first_date           TEXT,
            last_date            TEXT,
            last_preview         TEXT,
            last_sender          TEXT
        )""",
        """CREATE TABLE conversation_sources (
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            archive_id      INTEGER NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
            source_dir      TEXT NOT NULL,           -- relatif à archives.root_path
            source_files    TEXT NOT NULL,           -- JSON
            PRIMARY KEY (conversation_id, archive_id)
        )""",
        """CREATE TABLE participants (
            id              INTEGER PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            message_count   INTEGER NOT NULL DEFAULT 0,
            initials        TEXT,
            userpic_class   TEXT,
            first_date      TEXT,
            last_date       TEXT,
            UNIQUE (conversation_id, name)
        )""",
        """CREATE TABLE messages (
            id                  INTEGER PRIMARY KEY,
            conversation_id     TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            archive_id          INTEGER NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
            seq                 INTEGER NOT NULL,     -- ordre d'affichage dans la conversation
            message_id          INTEGER NOT NULL,     -- identifiant Telegram
            html_id             TEXT NOT NULL,
            source_file         TEXT NOT NULL,        -- relatif à archives.root_path
            kind                TEXT NOT NULL,
            is_joined           INTEGER NOT NULL DEFAULT 0,
            sender              TEXT,
            sender_inherited    INTEGER NOT NULL DEFAULT 0,
            sender_initials     TEXT,
            sender_userpic      TEXT,
            date_local          TEXT,                 -- ISO 8601 avec décalage, tel qu'exporté
            date_utc            TEXT,                 -- ISO 8601 UTC (tri, filtres)
            day                 TEXT,                 -- AAAA-MM-JJ local (navigation)
            date_raw            TEXT,
            timezone            TEXT,
            utc_offset_minutes  INTEGER,
            edited_raw          TEXT,
            separator_date      TEXT,
            text                TEXT NOT NULL DEFAULT '',
            html                TEXT NOT NULL DEFAULT '',
            service_text        TEXT,
            reply_to_message_id INTEGER,
            reply_to_file       TEXT,
            reply_raw           TEXT,
            forwarded_from      TEXT,
            forwarded_date_raw  TEXT,
            via_bot             TEXT,
            signature           TEXT,
            has_media           INTEGER NOT NULL DEFAULT 0,
            has_link            INTEGER NOT NULL DEFAULT 0,
            warnings            TEXT,
            UNIQUE (archive_id, source_file, html_id)
        )""",
        "CREATE INDEX idx_messages_conv_seq ON messages(conversation_id, seq)",
        "CREATE INDEX idx_messages_conv_msgid ON messages(conversation_id, message_id)",
        "CREATE INDEX idx_messages_conv_day ON messages(conversation_id, day)",
        "CREATE INDEX idx_messages_date ON messages(date_utc)",
        "CREATE INDEX idx_messages_sender ON messages(sender)",
        """CREATE TABLE medias (
            id               INTEGER PRIMARY KEY,
            message_pk       INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            conversation_id  TEXT NOT NULL,
            ordinal          INTEGER NOT NULL,
            media_type       TEXT NOT NULL,
            file_path        TEXT,                    -- href brut (relatif au fichier HTML)
            thumbnail_path   TEXT,                    -- src brut
            duration_raw     TEXT,
            duration_seconds INTEGER,
            title            TEXT,
            description      TEXT,
            status           TEXT,
            thumb_width      INTEGER,
            thumb_height     INTEGER,
            not_included     INTEGER NOT NULL DEFAULT 0,
            css_class        TEXT,
            file_exists      INTEGER,
            thumbnail_exists INTEGER,
            file_size        INTEGER
        )""",
        "CREATE INDEX idx_medias_message ON medias(message_pk)",
        "CREATE INDEX idx_medias_conv_type ON medias(conversation_id, media_type)",
        """CREATE TABLE reactions (
            id              INTEGER PRIMARY KEY,
            message_pk      INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            emoji           TEXT NOT NULL,
            count           INTEGER NOT NULL,
            users           TEXT,                     -- JSON
            is_custom_emoji INTEGER NOT NULL DEFAULT 0,
            active          INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX idx_reactions_message ON reactions(message_pk)",
        """CREATE TABLE message_references (
            id                INTEGER PRIMARY KEY,
            message_pk        INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            ref_type          TEXT NOT NULL,          -- 'reply' | 'service_link'
            target_message_id INTEGER NOT NULL,
            target_file       TEXT
        )""",
        "CREATE INDEX idx_refs_message ON message_references(message_pk)",
        """CREATE TABLE links (
            id          INTEGER PRIMARY KEY,
            message_pk  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            url         TEXT NOT NULL
        )""",
        "CREATE INDEX idx_links_message ON links(message_pk)",
        # Recherche plein texte (exploitée à l'étape 3), synchronisée par triggers
        """CREATE VIRTUAL TABLE messages_fts USING fts5(
            text, sender, content='messages', content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        )""",
        FTS_INSERT_TRIGGER,
        """CREATE TRIGGER messages_ad AFTER DELETE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, text, sender)
            VALUES ('delete', old.id, old.text, old.sender);
        END""",
        """CREATE TRIGGER messages_au AFTER UPDATE OF text, sender ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, text, sender)
            VALUES ('delete', old.id, old.text, old.sender);
            INSERT INTO messages_fts(rowid, text, sender) VALUES (new.id, new.text, new.sender);
        END""",
    ],
    # --- v2 : bibliothèque multi-archives (étape 4) ---------------------------
    [
        # Doublons : un même message présent dans plusieurs archives est conservé
        # dans chacune, mais une seule copie (canonique) est affichée et recherchée.
        "ALTER TABLE messages ADD COLUMN is_duplicate INTEGER NOT NULL DEFAULT 0",
        # Ordre d'origine dans l'archive (seq devient l'ordre fusionné)
        "ALTER TABLE messages ADD COLUMN position INTEGER",
        "UPDATE messages SET position = seq",
        "CREATE INDEX idx_messages_conv_dup_seq ON messages(conversation_id, is_duplicate, seq)",
        "ALTER TABLE archives ADD COLUMN content_hash TEXT",
        """CREATE TABLE archive_files (
            archive_id  INTEGER NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
            rel_path    TEXT NOT NULL,            -- fichier HTML, relatif à root_path
            size        INTEGER NOT NULL,
            sha256      TEXT NOT NULL,
            PRIMARY KEY (archive_id, rel_path)
        )""",
        # Autres noms sous lesquels une conversation a été exportée (renommage)
        """CREATE TABLE conversation_aliases (
            name            TEXT NOT NULL PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE
        )""",
    ],
]

SCHEMA_VERSION = len(MIGRATIONS)


class Database:
    """Connexion à la bibliothèque. Une instance par thread."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if str(self.path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA cache_size = -65536")     # 64 Mo : accélère la mise à jour des index
        self.conn.execute("PRAGMA temp_store = MEMORY")
        self.migrate()

    @property
    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        current = self.version
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"La bibliothèque utilise le schéma v{current}, plus récent que cette version "
                f"de l'application (v{SCHEMA_VERSION}).")
        for version in range(current, SCHEMA_VERSION):
            with self.conn:
                for stmt in MIGRATIONS[version]:
                    self.conn.execute(stmt)
                self.conn.execute(f"PRAGMA user_version = {version + 1}")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
