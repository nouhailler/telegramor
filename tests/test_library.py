"""Tests de la bibliothèque multi-archives : doublons, fusion, renommage, intégrité, déplacement."""

from __future__ import annotations

import shutil
import sqlite3

import pytest

from database.db_manager import MIGRATIONS, SCHEMA_VERSION, Database
from database.repositories import LibraryRepository
from database.search_engine import SearchEngine, SearchQuery
from importer.import_manager import import_path
from tests.conftest import REFERENCE_HTML, msg, page, service


def day_title(day: int, hour: int) -> str:
    return f"{day:02d}.03.2024 {hour:02d}:00:00 UTC+01:00"


def export(tmp_path, folder: str, name: str, items: list[tuple[int, int, int, str]], extra: str = "") -> object:
    """items : (message_id, jour de mars 2024, heure, texte). Un séparateur par jour."""
    d = tmp_path / folder
    d.mkdir()
    blocks, current, sep_id = [], None, -1
    for mid, day, hour, text in items:
        if day != current:
            months = "March"
            blocks.append(service(sep_id, f"{day} {months} 2024"))
            sep_id -= 1
            current = day
        blocks.append(msg(mid, f'<div class="text">{text}</div>', sender="Alice" if mid % 2 else "Bob",
                          title=day_title(day, hour)))
    (d / "messages.html").write_text(page("".join(blocks) + extra, name=name))
    return d


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "lib.sqlite")
    yield LibraryRepository(db)
    db.close()


def save(repo, d):
    return repo.save_import(import_path(d), d)


def visible(repo, conv_id):
    return [(m.kind, m.message_id) for m in repo.messages_after(conv_id, -1, 1000)]


A_ITEMS = [(1, 1, 9, "un"), (2, 1, 10, "deux"), (3, 2, 9, "trois"), (4, 3, 9, "quatre"), (5, 3, 10, "cinq")]
B_ITEMS = [(4, 3, 9, "quatre"), (5, 3, 10, "cinq"), (6, 3, 11, "six"), (7, 4, 9, "sept"), (8, 5, 9, "huit")]


def test_overlapping_exports_are_merged_without_duplicates(repo, tmp_path):
    a = export(tmp_path, "export_2024_03_03", "Bob", A_ITEMS)
    b = export(tmp_path, "export_2024_03_05", "Bob", B_ITEMS)
    s1 = save(repo, a)
    s2 = save(repo, b)
    assert (s1.new_messages, s1.duplicates) == (5, 0)
    assert (s2.new_messages, s2.duplicates) == (3, 2)
    convs = repo.list_conversations()
    assert len(convs) == 1 and convs[0].message_count == 8
    conv = convs[0].id
    v = visible(repo, conv)
    assert [mid for kind, mid in v if kind == "default"] == [1, 2, 3, 4, 5, 6, 7, 8]
    seps = [m.separator_date for m in repo.messages_after(conv, -1, 1000) if m.kind == "date_separator"]
    assert seps == ["2024-03-01", "2024-03-02", "2024-03-03", "2024-03-04", "2024-03-05"]
    # chaque séparateur précède les messages de son jour
    days = [m.day for m in repo.messages_after(conv, -1, 1000)]
    assert days == sorted(days)
    stats = repo.library_stats()
    assert (stats["messages"], stats["duplicates"]) == (8, 2)
    assert SearchEngine(repo.db).search(SearchQuery("quatre")).total == 1
    assert {a.name: a.duplicates for a in repo.list_archives()} == {"export_2024_03_03": 2,
                                                                     "export_2024_03_05": 2}
    names = {p.name: p.message_count for p in repo.participants(conv)}
    assert names == {"Alice": 4, "Bob": 4}


def test_deleting_an_archive_promotes_its_duplicates(repo, tmp_path):
    a = export(tmp_path, "A", "Bob", A_ITEMS)
    b = export(tmp_path, "B", "Bob", B_ITEMS)
    aid = save(repo, a).archive_id
    save(repo, b)
    repo.delete_archive(aid)
    conv = repo.list_conversations()[0]
    assert conv.message_count == 5
    assert [mid for kind, mid in visible(repo, conv.id) if kind == "default"] == [4, 5, 6, 7, 8]
    assert repo.library_stats()["duplicates"] == 0


def test_reimport_order_independent(repo, tmp_path):
    a = export(tmp_path, "A", "Bob", A_ITEMS)
    b = export(tmp_path, "B", "Bob", B_ITEMS)
    save(repo, b)                       # la plus récente d'abord
    save(repo, a)
    conv = repo.list_conversations()[0].id
    assert [mid for kind, mid in visible(repo, conv) if kind == "default"] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_identical_copy_detected(repo, tmp_path):
    a = export(tmp_path, "A", "Bob", A_ITEMS)
    copy = tmp_path / "copie_sur_disque_externe"
    shutil.copytree(a, copy)
    save(repo, a)
    s = save(repo, copy)
    assert s.identical_to == "A"
    assert (s.new_messages, s.duplicates) == (0, 5)
    assert "Contenu identique" in s.to_text()
    assert repo.list_conversations()[0].message_count == 5


def test_same_path_reimport_replaces(repo, tmp_path):
    a = export(tmp_path, "A", "Bob", A_ITEMS)
    save(repo, a)
    s = save(repo, a)
    assert s.replaced and s.duplicates == 0 and len(repo.list_archives()) == 1


def test_renamed_conversation_is_recognised(repo, tmp_path):
    a = export(tmp_path, "A", "Bob", A_ITEMS)
    b = export(tmp_path, "B", "Bob Martin", B_ITEMS + [(9, 5, 10, "neuf"), (10, 5, 11, "dix")])
    save(repo, a)
    s = save(repo, b)
    # seulement 2 couples communs sur 5 : trop peu → pas de fusion
    assert s.renamed == [] and len(repo.list_conversations()) == 2


def test_renamed_conversation_merged_when_overlap_is_large(repo, tmp_path):
    a = export(tmp_path, "A", "Bob", A_ITEMS)
    b = export(tmp_path, "B", "Bob Martin", A_ITEMS[1:] + [(9, 6, 9, "neuf")])
    save(repo, a)
    s = save(repo, b)
    assert s.renamed == [("Bob Martin", "Bob")]
    convs = repo.list_conversations()
    assert len(convs) == 1 and convs[0].message_count == 6
    # l'alias est mémorisé pour les imports suivants
    c = export(tmp_path, "C", "Bob Martin", [(20, 7, 9, "vingt")])
    save(repo, c)
    assert len(repo.list_conversations()) == 1


def test_groups_with_same_ids_but_other_dates_are_not_merged(repo, tmp_path):
    a = export(tmp_path, "A", "Groupe vélo", A_ITEMS)
    other = [(mid, day + 10, hour, text) for mid, day, hour, text in A_ITEMS]
    b = export(tmp_path, "B", "Groupe rando", other)
    save(repo, a)
    s = save(repo, b)
    assert s.renamed == [] and s.duplicates == 0
    assert len(repo.list_conversations()) == 2


def test_canonical_copy_prefers_available_media(repo, tmp_path):
    photo = ('<div class="media_wrap clearfix"><a class="photo_wrap clearfix pull_left" href="photos/p.jpg">'
             '<img class="photo" src="photos/p_thumb.jpg"/></a></div>')
    a = tmp_path / "A"
    b = tmp_path / "B"
    for d in (a, b):
        d.mkdir()
        (d / "messages.html").write_text(page(msg(42, photo, title=day_title(1, 9)), name="Bob"))
    (b / "photos").mkdir()
    (b / "photos" / "p.jpg").write_bytes(b"x")
    save(repo, a)
    save(repo, b)
    conv = repo.list_conversations()[0].id
    m = repo.messages_after(conv, -1, 10)[0]
    assert m.archive_name == "B" and m.media[0].file_available


def test_undated_service_events_keep_their_place(repo, tmp_path):
    pin = service(500, 'Alice pinned <a href="#go_to_message2">this message</a>')
    a = export(tmp_path, "A", "Bob", A_ITEMS[:2], extra="")
    html = (a / "messages.html").read_text().replace(
        '<div class="message default clearfix" id="message2">', pin + '<div class="message default clearfix" id="message2">')
    (a / "messages.html").write_text(html)
    b = export(tmp_path, "B", "Bob", [(0, 1, 8, "zéro")])
    save(repo, a)
    save(repo, b)
    conv = repo.list_conversations()[0].id
    order = [mid for _, mid in visible(repo, conv)]
    assert order.index(500) == order.index(1) + 1 and order.index(500) < order.index(2)
    assert order.index(0) < order.index(1)


def test_relocation_and_integrity(repo, tmp_path):
    d = tmp_path / "ChatExport"
    d.mkdir()
    shutil.copy(REFERENCE_HTML, d / "messages.html")
    (d / "photos").mkdir()
    (d / "photos" / "photo_1@10-01-2026_20-28-43.jpg").write_bytes(b"x")
    aid = save(repo, d).archive_id
    rep = repo.verify_archive(aid)
    assert rep.root_exists and rep.files_ok == 1 and not rep.files_modified
    assert rep.media_total == 3 and rep.media_missing == 2           # photo 2 et vidéo absentes

    moved = tmp_path / "disque" / "Telegram_2026"
    moved.parent.mkdir()
    shutil.move(str(d), str(moved))
    a = repo.get_archive(aid)
    assert not a.root_exists and a.status == "Introuvable"
    assert not repo.verify_archive(aid).root_exists

    wrong = tmp_path / "autre"
    wrong.mkdir()
    assert repo.check_relocation(aid, wrong)[0] == ["messages.html"]
    with pytest.raises(ValueError):
        repo.relocate_archive(aid, wrong)

    repo.relocate_archive(aid, moved)
    a = repo.get_archive(aid)
    assert a.root_exists and a.root_path == str(moved.resolve())
    conv = repo.list_conversations()[0].id
    photo = repo.medias(conv, ("photo",))[0]
    assert photo.file_available and photo.abs_file.parent.parent == moved.resolve()

    # fichier modifié après l'import → signalé
    html = moved / "messages.html"
    html.write_text(html.read_text().replace("Top", "Top !"))
    assert repo.verify_archive(aid).files_modified == ["messages.html"]


def test_rename_archive(repo, tmp_path):
    aid = save(repo, export(tmp_path, "A", "Bob", A_ITEMS)).archive_id
    repo.rename_archive(aid, "Export de mars 2024")
    assert repo.list_archives()[0].name == "Export de mars 2024"
    assert repo.list_conversations()[0].archives == ["Export de mars 2024"]
    with pytest.raises(ValueError):
        repo.rename_archive(aid, "  ")


def test_filter_conversations_by_archive(repo, tmp_path):
    a = save(repo, export(tmp_path, "A", "Bob", A_ITEMS)).archive_id
    b = save(repo, export(tmp_path, "B", "Claire", [(1, 9, 9, "x")])).archive_id
    assert [c.name for c in repo.list_conversations(a)] == ["Bob"]
    assert [c.name for c in repo.list_conversations(b)] == ["Claire"]
    assert len(repo.list_conversations()) == 2


def test_migration_from_v1_and_hash_backfill(tmp_path):
    d = tmp_path / "ChatExport"
    d.mkdir()
    shutil.copy(REFERENCE_HTML, d / "messages.html")
    path = tmp_path / "ancienne.sqlite"
    # base au schéma v1 remplie avec le code de l'époque (colonnes v1 uniquement)
    conn = sqlite3.connect(path)
    for stmt in MIGRATIONS[0]:
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO archives (id, source_path, root_path, name, imported_at) VALUES (1, ?, ?, 'ChatExport', 'x')",
                 (str(d), str(d)))
    conn.execute("INSERT INTO conversations (id, name) VALUES ('c', 'fabien')")
    conn.execute("INSERT INTO conversation_sources VALUES ('c', 1, '.', '[\"messages.html\"]')")
    conn.execute("INSERT INTO messages (conversation_id, archive_id, seq, message_id, html_id, source_file, kind, text)"
                 " VALUES ('c', 1, 7, 1, 'message1', 'messages.html', 'default', 'bonjour')")
    conn.commit()
    conn.close()
    with Database(path) as db:
        assert db.version == SCHEMA_VERSION
        assert tuple(db.conn.execute("SELECT position, is_duplicate FROM messages").fetchone()) == (7, 0)
        repo = LibraryRepository(db)
        assert repo.backfill_file_hashes() == 1
        assert repo.verify_archive(1).files_ok == 1


def test_rebuild_search_index(repo, tmp_path):
    save(repo, export(tmp_path, "A", "Bob", A_ITEMS))
    repo.conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('delete-all')")
    assert SearchEngine(repo.db).search(SearchQuery("quatre")).total == 0
    repo.rebuild_search_index()
    assert SearchEngine(repo.db).search(SearchQuery("quatre")).total == 1


def test_fts_trigger_restored_after_import_and_after_failure(repo, tmp_path, monkeypatch):
    def has_trigger():
        return repo.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='messages_ai'").fetchone() is not None
    save(repo, export(tmp_path, "A", "Bob", A_ITEMS))
    assert has_trigger()
    assert SearchEngine(repo.db).search(SearchQuery("quatre")).total == 1

    def boom(conv_id):
        raise RuntimeError("panne simulée")
    monkeypatch.setattr(repo, "_rebuild_conversation", boom)
    with pytest.raises(RuntimeError):
        save(repo, export(tmp_path, "B", "Claire", [(1, 9, 9, "neuf")]))
    assert has_trigger()                                    # transaction annulée, trigger intact
    assert [a.name for a in repo.list_archives()] == ["A"]
    # l'indexation automatique fonctionne toujours pour une insertion ordinaire
    repo.conn.execute("INSERT INTO messages (conversation_id, archive_id, seq, message_id, html_id, source_file,"
                      " kind, text) VALUES (?, 1, 999, 999, 'message999', 'x', 'default', 'zanzibar')",
                      (repo.list_conversations()[0].id,))
    assert SearchEngine(repo.db).search(SearchQuery("zanzibar")).total == 1
