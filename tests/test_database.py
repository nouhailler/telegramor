"""Tests de la persistance SQLite."""

from __future__ import annotations

import shutil

import pytest

from database.db_manager import SCHEMA_VERSION, Database
from database.repositories import LibraryRepository
from importer.import_manager import import_path
from tests.conftest import REFERENCE_HTML, msg, page, service


@pytest.fixture
def export_dir(tmp_path):
    d = tmp_path / "ChatExport"
    d.mkdir()
    shutil.copy(REFERENCE_HTML, d / "messages.html")
    (d / "photos").mkdir()
    (d / "photos" / "photo_1@10-01-2026_20-28-43.jpg").write_bytes(b"x")
    return d


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "lib.sqlite")
    yield LibraryRepository(db)
    db.close()


def load(repo, path):
    return repo.save_import(import_path(path), path).archive_id


def test_schema_version_and_reopen(tmp_path):
    p = tmp_path / "lib.sqlite"
    with Database(p) as db:
        assert db.version == SCHEMA_VERSION
    with Database(p) as db:  # réouverture : aucune migration rejouée
        assert db.version == SCHEMA_VERSION


def test_newer_schema_refused(tmp_path):
    p = tmp_path / "lib.sqlite"
    with Database(p) as db:
        db.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError):
        Database(p)


def test_save_and_list(repo, export_dir):
    load(repo, export_dir)
    convs = repo.list_conversations()
    assert len(convs) == 1
    c = convs[0]
    assert (c.name, c.message_count, c.media_count) == ("faycal", 32, 3)
    assert c.last_preview == "bonne matinées 🤔" and c.last_sender == "patrick"
    assert c.archives == ["ChatExport"]
    assert repo.library_stats() == {"archives": 1, "conversations": 1, "messages": 32, "duplicates": 0,
                                    "medias": 3}
    names = {p.name: p.message_count for p in repo.participants(c.id)}
    assert names == {"patrick": 16, "robert": 10, "faycal": 6}


def test_reimport_does_not_duplicate(repo, export_dir):
    load(repo, export_dir)
    load(repo, export_dir)
    assert repo.library_stats()["messages"] == 32
    assert len(repo.list_archives()) == 1
    fts = repo.conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    assert fts == repo.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 40


def test_delete_archive_removes_conversation(repo, export_dir):
    aid = load(repo, export_dir)
    repo.delete_archive(aid)
    assert repo.list_conversations() == []
    assert repo.conn.execute("SELECT COUNT(*) FROM medias").fetchone()[0] == 0


def test_pagination(repo, export_dir):
    load(repo, export_dir)
    cid = repo.list_conversations()[0].id
    lo, hi = repo.seq_bounds(cid)
    assert (lo, hi) == (0, 39)
    last = repo.messages_before(cid, hi + 1, 5)
    assert [m.seq for m in last] == [35, 36, 37, 38, 39]
    nxt = repo.messages_after(cid, 10, 3)
    assert [m.seq for m in nxt] == [11, 12, 13]
    assert [m.seq for m in repo.messages_between(cid, 3, 5)] == [3, 4, 5]


def test_message_hydration(repo, export_dir):
    load(repo, export_dir)
    cid = repo.list_conversations()[0].id
    seq = repo.seq_of_message(cid, 189181)
    m = repo.message_by_seq(cid, seq)
    assert m.reply is not None and m.reply.message_id == 189180
    assert m.reply.sender == "robert" and m.reply.seq == repo.seq_of_message(cid, 189180)
    target = repo.message_by_seq(cid, m.reply.seq)
    assert target.reactions[0].emoji == "👍" and target.reactions[0].users == ["patrick"]
    first = repo.message_by_seq(cid, repo.seq_of_message(cid, 185995))
    assert len(first.links) == 1 and first.links[0].startswith("https://youtu.be/")


def test_media_paths_resolved(repo, export_dir):
    load(repo, export_dir)
    cid = repo.list_conversations()[0].id
    photos = repo.medias(cid, ("photo",))
    assert len(photos) == 2
    assert photos[0].abs_file == (export_dir / "photos/photo_1@10-01-2026_20-28-43.jpg").resolve()
    assert photos[0].file_available and not photos[0].thumbnail_available
    assert not photos[1].file_available
    assert photos[0].message_sender == "patrick"
    # Archive déplacée : seule la racine change, les chemins restent relatifs
    stored = repo.conn.execute("SELECT file_path FROM medias WHERE media_type='photo' LIMIT 1").fetchone()[0]
    assert stored == "photos/photo_1@10-01-2026_20-28-43.jpg"


def test_date_navigation(repo, export_dir):
    load(repo, export_dir)
    cid = repo.list_conversations()[0].id
    days = repo.days_with_messages(cid)
    assert days["2026-03-22"] == 12
    seq = repo.seq_for_day(cid, "2026-03-01")
    m = repo.message_by_seq(cid, seq)
    assert m.kind == "date_separator" and m.separator_date == "2026-03-01"
    # jour sans message → premier jour suivant
    m2 = repo.message_by_seq(cid, repo.seq_for_day(cid, "2026-03-02"))
    assert m2.day == "2026-03-22"
    assert repo.seq_for_day(cid, "2030-01-01") == 39
    assert repo.month_index(cid)[0] == ("2025-12", 3)


def test_owner_detection(repo, export_dir):
    load(repo, export_dir)
    assert repo.detect_owner() == "patrick"


def test_fts_ready(repo, export_dir):
    load(repo, export_dir)
    rows = repo.conn.execute(
        "SELECT m.message_id FROM messages_fts f JOIN messages m ON m.id = f.rowid "
        "WHERE messages_fts MATCH 'cafe'").fetchall()
    assert [r[0] for r in rows] == [191565]


def test_two_archives_same_conversation_merge(repo, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "messages.html").write_text(page(service(-1, "1 February 2024") + msg(1, '<div class="text">x</div>'),
                                          name="Bob"))
    (b / "messages.html").write_text(page(msg(5, '<div class="text">y</div>', title="02.02.2024 10:00:00 UTC+01:00"),
                                          name="Bob"))
    load(repo, a)
    load(repo, b)
    convs = repo.list_conversations()
    assert len(convs) == 1 and convs[0].message_count == 2
    assert sorted(convs[0].archives) == ["a", "b"]
    assert [m.message_id for m in repo.messages_after(convs[0].id, -1, 10)] == [-1, 1, 5]
