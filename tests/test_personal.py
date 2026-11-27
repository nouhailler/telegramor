"""Données personnelles Telegramor : favoris, notes, collections, lecture, recherches."""

from __future__ import annotations

import sqlite3

from database.db_manager import MIGRATIONS, SCHEMA_VERSION, Database
from database.repositories import LibraryRepository
from database.search_engine import SearchEngine, SearchQuery
from importer.import_manager import import_path
from services.personal_data import PersonalData, describe_query, query_from_json, query_to_json


def test_favorites_notes_flags_and_filters(synthetic_lib):
    db, repo, convs = synthetic_lib
    pd = PersonalData(db)
    v = convs["Voyage en Italie"].id
    assert pd.toggle_favorite(v, 2) is True
    pd.set_favorite(v, 6)
    pd.set_note(v, 6, "  À imprimer pour l'album  ")
    rows = repo.messages_between(v, *repo.seq_bounds(v))
    by_id = {m.message_id: m for m in rows if m.kind == "default"}
    assert by_id[2].favorite and by_id[6].favorite and not by_id[1].favorite
    assert by_id[6].note == "À imprimer pour l'album"
    favs = pd.favorites()
    assert [f.message_id for f in favs] == [6, 2]                     # plus récent d'abord
    assert favs[0].note and favs[0].media_type == "photo" and favs[0].available
    assert [f.message_id for f in pd.favorites(newest_first=False)] == [2, 6]
    assert [f.message_id for f in pd.favorites(sender="Marc")] == [2]
    assert [f.message_id for f in pd.favorites(date_from="2025-07-01")] == [6]
    assert pd.favorites(conversation_id=convs["Famille"].id) == []
    assert pd.toggle_favorite(v, 2) is False and not pd.is_favorite(v, 2)


def test_note_search_ignores_accents_and_case(synthetic_lib):
    db, _, convs = synthetic_lib
    pd = PersonalData(db)
    v, f = convs["Voyage en Italie"].id, convs["Famille"].id
    pd.set_note(v, 1, "Vérifier les horaires du train")
    pd.set_note(f, 2, "Montrer à mamie")
    assert [n.message_id for n in pd.notes("VERIF")] == [1]
    assert [n.conversation_name for n in pd.notes("mamie")] == ["Famille"]
    assert len(pd.notes()) == 2
    assert pd.notes("introuvable") == [] and pd.notes("!!!") == []
    pd.set_note(v, 1, "Horaires confirmés")                          # modification : index mis à jour
    assert pd.notes("vérifier") == [] and len(pd.notes("confirmes")) == 1
    pd.set_note(v, 1, "")                                            # suppression
    assert pd.note(v, 1) is None and pd.notes("confirmes") == []


def test_collections_lifecycle(synthetic_lib):
    db, _, convs = synthetic_lib
    pd = PersonalData(db)
    v, f = convs["Voyage en Italie"].id, convs["Famille"].id
    cid = pd.create_collection("Souvenirs", "Photos à garder")
    assert pd.add_to_collection(cid, v, 6, 0) and pd.add_to_collection(cid, f, 2, 0)
    assert pd.add_to_collection(cid, v, 8)                         # message avec lien
    assert pd.add_to_collection(cid, v, 6, 0) is False             # pas de doublon
    other = pd.create_collection("Italie")
    pd.add_to_collection(other, v, 6, 0)                           # un élément, plusieurs collections
    assert pd.collections_of(v, 6) == ["Italie", "Souvenirs"]
    items = pd.collection_items(cid)
    assert len(items) == 3 and {i.conversation_name for i in items} == {"Voyage en Italie", "Famille"}
    assert [i.message_id for i in pd.collection_items(cid, kind="photo")] == [2, 6]
    assert [i.message_id for i in pd.collection_items(cid, kind="link")] == [8]
    assert [i.message_id for i in pd.collection_items(cid, search="noël")] == []
    assert [i.message_id for i in pd.collection_items(cid, search="florence")] == [2, 6]   # légende ou nom de fichier
    assert [i.message_id for i in pd.collection_items(cid, search="premier matin")] == [6]
    assert {c.name: c.count for c in pd.collections()} == {"Italie": 1, "Souvenirs": 3}
    try:
        pd.create_collection("souvenirs ".strip().capitalize())
        raise AssertionError("doublon accepté")
    except ValueError:
        pass
    pd.update_collection(cid, "Souvenirs 2025", "")
    pd.remove_item(items[0].item_id)
    assert len(pd.collection_items(cid)) == 2
    pd.delete_collection(cid)                                       # les messages restent
    assert [c.name for c in pd.collections()] == ["Italie"]
    assert db.conn.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (v,)).fetchone()[0] > 0


def test_personal_data_survives_archive_reimport(synthetic_lib, tmp_path):
    db, repo, convs = synthetic_lib
    pd = PersonalData(db)
    v = convs["Voyage en Italie"].id
    pd.set_favorite(v, 4)
    pd.set_note(v, 4, "Appartement réservé")
    arch = next(a for a in repo.list_archives() if a.name == "ExportVoyage")
    repo.delete_archive(arch.id)
    item = pd.favorites()[0]
    assert item.message_id == 4 and not item.available             # signalé absent, conservé
    src = tmp_path / "exports" / "ExportVoyage"
    repo.save_import(import_path(src), src)
    item = pd.favorites()[0]
    assert item.available and item.sender == "Camille" and item.note == "Appartement réservé"


def test_read_marker_only_moves_forward(synthetic_lib):
    db, repo, convs = synthetic_lib
    pd = PersonalData(db)
    v = convs["Voyage en Italie"].id
    seq = lambda mid: repo.seq_of_message(v, mid)  # noqa: E731
    assert pd.read_marker(v) is None
    assert pd.advance_read_marker(v, 3, seq(3))
    assert not pd.advance_read_marker(v, 2, seq(2))
    assert pd.read_marker(v) == 3
    assert pd.advance_read_marker(v, 7, seq(7)) and pd.read_marker(v) == 7
    pd.set_read_marker(v, 1)                                        # modification manuelle
    assert pd.read_marker(v) == 1
    pd.clear_read_marker(v)
    assert pd.read_marker(v) is None


def test_search_history_and_saved_searches(synthetic_lib):
    db, _, _ = synthetic_lib
    pd = PersonalData(db)
    q1 = SearchQuery("florence", sender="Camille")
    pd.record_search(q1)
    pd.record_search(SearchQuery("train"))
    pd.record_search(q1)                                            # remonte en tête, sans doublon
    pd.record_search(SearchQuery())                                 # vide : ignorée
    hist = pd.search_history()
    assert [h.text for h in hist] == ["florence", "train"] and hist[0].sender == "Camille"
    for i in range(40):
        pd.record_search(SearchQuery(f"mot{i}"))
    assert len(pd.search_history()) == 30
    pd.clear_search_history()
    assert pd.search_history() == []
    pd.save_search("Photos de Léa", SearchQuery(sender="Léa", content_type="photo"))
    pd.save_search("Photos de Léa", SearchQuery(sender="Léa", content_type="video"))   # remplace
    saved = pd.saved_searches()
    assert len(saved) == 1 and saved[0].query.content_type == "video"
    assert "de Léa" in describe_query(saved[0].query)
    pd.delete_saved_search(saved[0].id)
    assert pd.saved_searches() == []
    q = SearchQuery("a", is_reply=True, date_from="2025-01-01")
    assert query_from_json(query_to_json(q)) == q
    assert query_from_json('{"text": "x", "champ_inconnu": 1}').text == "x"


def test_reply_filter(synthetic_lib):
    db, _, convs = synthetic_lib
    eng = SearchEngine(db)
    replies = eng.search(SearchQuery(is_reply=True), limit=100)
    assert sorted(h.message_id for h in replies.hits) == [2, 3, 4, 5]
    not_replies = eng.search(SearchQuery(is_reply=False, conversation_ids=[convs["Voyage en Italie"].id]), limit=100)
    assert 2 not in [h.message_id for h in not_replies.hits]


def test_export_import_personal_data(synthetic_lib, tmp_path):
    db, _, convs = synthetic_lib
    pd = PersonalData(db)
    v = convs["Voyage en Italie"].id
    pd.set_favorite(v, 1)
    pd.set_note(v, 1, "Idée de départ")
    cid = pd.create_collection("Italie")
    pd.add_to_collection(cid, v, 6, 0)
    pd.set_read_marker(v, 5)
    pd.save_search("Trains", SearchQuery("train"))
    data = pd.export_dict()
    other = Database(tmp_path / "autre.sqlite")
    pd2 = PersonalData(other)
    pd2.set_note(v, 1, "Note existante")
    added = pd2.import_dict(data)                                   # fusion : l'existant est conservé
    assert pd2.note(v, 1) == "Note existante" and added["favoris"] == 1 and added["notes"] == 0
    assert pd2.counts()["éléments de collections"] == 1 and pd2.read_marker(v) == 5
    pd2.import_dict(data, replace=True)
    assert pd2.note(v, 1) == "Idée de départ"
    try:
        pd2.import_dict({"format": "autre"})
        raise AssertionError
    except ValueError:
        pass
    other.close()


def test_migration_v2_to_v3_preserves_data(tmp_path):
    """Une bibliothèque v2 existante est migrée sans perte et reçoit les tables personnelles."""
    path = tmp_path / "ancienne.sqlite"
    conn = sqlite3.connect(path)
    for version in range(2):
        for stmt in MIGRATIONS[version]:
            conn.execute(stmt)
    conn.execute("PRAGMA user_version = 2")
    conn.execute("INSERT INTO archives (id, source_path, root_path, name, imported_at) VALUES (1, '/a', '/a', 'A', 'x')")
    conn.execute("INSERT INTO conversations (id, name) VALUES ('c1', 'Conv')")
    conn.execute("INSERT INTO messages (conversation_id, archive_id, seq, message_id, html_id, source_file, kind, "
                 "text) VALUES ('c1', 1, 1, 10, 'message10', 'messages.html', 'default', 'bonjour')")
    conn.commit()
    conn.close()
    db = Database(path)
    assert db.version == SCHEMA_VERSION == 3
    assert db.conn.execute("SELECT text FROM messages").fetchone()[0] == "bonjour"
    assert db.conn.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'bonjour'").fetchone()[0] == 1
    PersonalData(db).set_favorite("c1", 10)
    assert LibraryRepository(db).messages_between("c1", 1, 1)[0].favorite
    db.close()


def test_thread_reconstruction(synthetic_lib):
    from services.threads import build_thread, replies_count
    db, _, convs = synthetic_lib
    v = convs["Voyage en Italie"].id
    t = build_thread(db, v, 3)                       # 1 ← 2 ← 3 et 1 ← 4
    assert [n.message_id for n in t.ancestors] == [1, 2]
    assert [(n.message_id, n.depth) for n in t.flat] == [(1, 0), (2, 1), (3, 2), (4, 1)]
    assert [n.message_id for n in t.flat if n.is_focus] == [3] and t.missing_parent is None
    assert replies_count(db, v, 1) == 2
    t5 = build_thread(db, v, 5)                      # cite le n° 999, absent de l'export
    assert t5.missing_parent == 999 and t5.ancestors == [] and [n.message_id for n in t5.flat] == [5]
