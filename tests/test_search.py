"""Tests du moteur de recherche."""

from __future__ import annotations

import shutil
import time

import pytest

from database.db_manager import Database
from database.repositories import LibraryRepository
from database.search_engine import (
    MODE_EXACT, MODE_PREFIX, MODE_WORDS, SORT_CHRONO, SORT_NEWEST, SORT_OLDEST, SearchEngine,
    SearchError, SearchQuery, build_match, highlight_html, highlight_spans,
)
from importer.import_manager import import_path
from tests.conftest import REFERENCE_HTML, msg, page, service


@pytest.fixture
def lib(tmp_path):
    ref = tmp_path / "ChatExport"
    ref.mkdir()
    shutil.copy(REFERENCE_HTML, ref / "messages.html")
    other = tmp_path / "Autre"
    other.mkdir()
    (other / "messages.html").write_text(page(
        service(-1, "3 August 2023")
        + msg(1, '<div class="text">Nos vacances en Italie étaient géniales</div>', sender="Claire",
              title="03.08.2023 09:00:00 UTC+02:00")
        + msg(2, '<div class="text">L\'Italie, encore ! Rome puis Naples.</div>', sender="Marc",
              title="03.08.2023 10:00:00 UTC+02:00")
        + msg(3, '<div class="media_wrap clearfix"><a class="media clearfix pull_left block_link media_file" '
                 'href="files/Programme_Rome.pdf"><div class="body"><div class="title bold">Programme_Rome.pdf'
                 '</div></div></a></div><div class="text">le programme</div>', sender="Claire",
              title="04.08.2023 10:00:00 UTC+02:00")
        + msg(4, '<div class="text">Pas de vacances cette année, voir '
                 '<a href="https://exemple.org">https://exemple.org</a></div>', sender="Marc", title="05.08.2023 10:00:00 UTC+02:00"),
        name="Voyages"))
    db = Database(tmp_path / "lib.sqlite")
    repo = LibraryRepository(db)
    repo.save_import(import_path(ref), ref)
    repo.save_import(import_path(other), other)
    yield SearchEngine(db), repo
    db.close()


def ids(page_):
    return [h.message_id for h in page_.hits]


def test_build_match():
    assert build_match("vacances Italie", MODE_PREFIX)[0] == 'text : ("vacances"* AND "Italie"*)'
    assert build_match("vacances Italie", MODE_WORDS)[0] == 'text : ("vacances" AND "Italie")'
    assert build_match("vacances en Italie", MODE_EXACT)[0] == 'text : ("vacances en Italie")'
    m, terms = build_match('"en Italie" -Rome cafe', MODE_PREFIX)
    assert m == 'text : ("en Italie" AND "cafe"* NOT "Rome")'
    assert terms == ["en Italie", "cafe"]
    assert build_match('-seul', MODE_PREFIX)[0] is None
    # guillemet non fermé : traité comme des mots ordinaires, aucune syntaxe FTS injectée
    assert build_match('"; DROP TABLE', MODE_PREFIX)[0] == 'text : ("DROP"* AND "TABLE"*)'


def test_global_search_across_archives(lib):
    eng, _ = lib
    p = eng.search(SearchQuery("vacances Italie"))
    assert p.total == 1
    h = p.hits[0]
    assert (h.conversation_name, h.sender, h.archive_name) == ("Voyages", "Claire", "Autre")
    assert "<mark>vacances</mark>" in h.snippet_html and "<mark>Italie</mark>" in h.snippet_html
    assert h.date_local.startswith("2023-08-03T09:00:00")
    # les deux conversations sont interrogées ensemble
    assert {x.conversation_name for x in eng.search(SearchQuery("super")).hits} == {"faycal"}
    assert eng.search(SearchQuery("italie")).total == 2


def test_accents_case_and_prefix(lib):
    eng, _ = lib
    assert ids(eng.search(SearchQuery("CAFÉ"))) == [191565]        # « cafe » dans le texte
    assert ids(eng.search(SearchQuery("genial"))) == [1]            # préfixe + accents
    assert eng.search(SearchQuery("genial", mode=MODE_WORDS)).total == 0
    assert eng.search(SearchQuery("géniales", mode=MODE_WORDS)).total == 1


def test_exact_phrase_and_exclusion(lib):
    eng, _ = lib
    assert ids(eng.search(SearchQuery("vacances en Italie", mode=MODE_EXACT))) == [1]
    assert eng.search(SearchQuery("Italie vacances", mode=MODE_EXACT)).total == 0
    assert ids(eng.search(SearchQuery('"italie encore"'))) == [2]
    assert ids(eng.search(SearchQuery("italie -rome"))) == [1]


def test_filters(lib):
    eng, repo = lib
    voyages = next(c.id for c in repo.list_conversations() if c.name == "Voyages")
    assert eng.search(SearchQuery("vacances", conversation_ids=[voyages])).total == 2
    assert ids(eng.search(SearchQuery("vacances", sender="Marc"))) == [4]
    assert ids(eng.search(SearchQuery("", sender="robert", date_from="2026-07-06", date_to="2026-07-06",
                                      sort=SORT_OLDEST))) == [191563, 191564, 191565, 191566, 191569,
                                                               191583, 191621]
    assert ids(eng.search(SearchQuery(content_type="photo", sort=SORT_OLDEST))) == [186728, 188184]
    assert ids(eng.search(SearchQuery(content_type="video"))) == [196573]
    assert ids(eng.search(SearchQuery(content_type="file"))) == [3]
    assert set(ids(eng.search(SearchQuery(content_type="link")))) == {185995, 4}
    assert eng.search(SearchQuery(has_media=True)).total == 4
    links = eng.search(SearchQuery("vacances", has_link=True))
    assert ids(links) == [4] and links.hits[0].has_link
    assert eng.search(SearchQuery(content_type="text", sender="Claire")).total == 1
    archive_ref = next(a.id for a in repo.list_archives() if a.name == "ChatExport")
    assert eng.search(SearchQuery("italie", archive_ids=[archive_ref])).total == 0
    with pytest.raises(SearchError):
        eng.search(SearchQuery(content_type="inconnu"))


def test_filename_search(lib):
    eng, _ = lib
    p = eng.search(SearchQuery(filename="rome"))
    assert ids(p) == [3]
    assert "<mark>Rome</mark>" in p.hits[0].snippet_html
    assert ids(eng.search(SearchQuery(filename="jenseng"))) == [196573]   # chemin de la vidéo
    assert eng.search(SearchQuery(filename="%")).total == 0               # pas de joker SQL


def test_date_separators_never_returned(lib):
    eng, _ = lib
    p = eng.search(SearchQuery(date_from="2000-01-01", sort=SORT_CHRONO), limit=500)
    assert all(h.kind != "date_separator" for h in p.hits)
    assert p.total == 36                                                   # 32 + 4
    assert eng.search(SearchQuery(date_from="2025-01-01")).total == 32


def test_sort_and_pagination(lib):
    eng, _ = lib
    newest = eng.search(SearchQuery(date_from="2000-01-01", sort=SORT_NEWEST), limit=5)
    assert newest.total == 36 and len(newest.hits) == 5 and newest.has_more
    assert newest.hits[0].message_id == 196573
    page2 = eng.search(SearchQuery(date_from="2000-01-01", sort=SORT_NEWEST), offset=5, limit=5)
    assert not set(ids(newest)) & set(ids(page2))
    last = eng.search(SearchQuery(date_from="2000-01-01", sort=SORT_NEWEST), offset=35, limit=5)
    assert len(last.hits) == 1 and not last.has_more
    assert eng.search(SearchQuery(date_from="2000-01-01", sort=SORT_OLDEST), limit=1).hits[0].message_id == 1


def test_empty_and_punctuation_queries(lib):
    eng, _ = lib
    assert SearchQuery().is_empty()
    assert eng.search(SearchQuery("?!;")).total == 0
    assert eng.search(SearchQuery('vacances"')).total == 2                # guillemet non fermé


def test_highlight_helpers():
    assert highlight_spans("Les Vacances à Évian", ["vacance", "evian"]) == [(4, 12), (15, 20)]
    assert highlight_spans("Straße", ["strasse"], prefix=False) == [(0, 6)]
    html = 'Voir <a href="https://vacances.fr">vacances</a> &amp; café'
    out = highlight_html(html, ["vacances", "cafe"], "<b>", "</b>")
    assert out == 'Voir <a href="https://vacances.fr"><b>vacances</b></a> &amp; <b>café</b>'


def test_performance_200k(tmp_path):
    """200 000 messages insérés directement en base (l'analyse HTML est testée ailleurs)."""
    db = Database(tmp_path / "big.sqlite")
    c = db.conn
    words = ["soleil", "pluie", "montagne", "plage", "Italie", "travail", "famille", "voiture"]
    with c:
        c.execute("INSERT INTO archives (id, source_path, root_path, name, imported_at) "
                  "VALUES (1, '/x', '/x', 'x', '2026-01-01')")
        for k in range(4):
            c.execute("INSERT INTO conversations (id, name) VALUES (?, ?)", (f"c{k}", f"Conv {k}"))
        c.executemany(
            "INSERT INTO messages (conversation_id, archive_id, seq, message_id, html_id, source_file, kind, "
            "sender, date_utc, day, text) VALUES (?, 1, ?, ?, ?, 'messages.html', 'default', ?, ?, ?, ?)",
            ((f"c{i % 4}", i, i, f"message{i}", f"P{i % 5}",
              f"20{10 + i % 15}-0{1 + i % 9}-1{i % 9}T10:00:00Z", f"20{10 + i % 15}-0{1 + i % 9}-1{i % 9}",
              f"message {i} {words[i % 8]} {words[(i * 3) % 8]} numéro{i}") for i in range(200_000)))
    eng = SearchEngine(db)
    t = time.perf_counter()
    p = eng.search(SearchQuery("pluie plage"))
    p2 = eng.search(SearchQuery("montagne", sender="P3", sort=SORT_NEWEST), offset=500)
    p3 = eng.search(SearchQuery("numéro4242", mode=MODE_WORDS))
    p4 = eng.search(SearchQuery("", conversation_ids=["c2"], date_from="2015-01-01", date_to="2016-12-31"))
    elapsed = time.perf_counter() - t
    assert p.total == 50_000 and p2.hits and p3.total == 1 and p4.total > 0
    assert elapsed < 2.0, f"recherche trop lente : {elapsed:.2f} s"
    db.close()


class ToyProvider:
    """Fournisseur factice : score = mots en commun (démontre le branchement)."""

    name = "jouet"

    def __init__(self, db):
        self.db = db

    def is_ready(self):
        return True

    def search(self, text, limit):
        words = set(text.lower().split())
        out = []
        for pk, t in self.db.conn.execute("SELECT id, text FROM messages"):
            score = len(words & set((t or "").lower().split()))
            if score:
                out.append((pk, float(score)))
        return sorted(out, key=lambda x: -x[1])[:limit]

    def index_archive(self, archive_id):
        return 0


def test_semantic_extension_point(lib):
    from database.search_engine import MODE_SEMANTIC
    from database.semantic import SemanticProvider
    eng, repo = lib
    with pytest.raises(SearchError):
        eng.search(SearchQuery("vacances", mode=MODE_SEMANTIC))
    eng.semantic = ToyProvider(repo.db)
    assert isinstance(eng.semantic, SemanticProvider)
    p = eng.search(SearchQuery("vacances italie rome", mode=MODE_SEMANTIC))
    assert p.total >= 2 and p.hits[0].message_id == 1            # 2 mots en commun : classé premier
    # les filtres du moteur s'appliquent aux candidats du fournisseur
    assert ids(eng.search(SearchQuery("vacances italie", mode=MODE_SEMANTIC, sender="Marc"))) == [4]
    assert eng.search(SearchQuery("zzz", mode=MODE_SEMANTIC)).total == 0
