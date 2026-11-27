"""Tests du calcul des statistiques et de la navigation par jour."""

from __future__ import annotations

import shutil

import pytest

from database.db_manager import Database
from database.repositories import LibraryRepository
from importer.import_manager import import_path
from services.statistics_service import compute
from tests.conftest import REFERENCE_HTML
from ui.timeline import neighbour_day


@pytest.fixture
def db(tmp_path):
    d = tmp_path / "ChatExport"
    d.mkdir()
    shutil.copy(REFERENCE_HTML, d / "messages.html")
    database = Database(tmp_path / "lib.sqlite")
    LibraryRepository(database).save_import(import_path(d), d)
    yield database
    database.close()


def test_reference_statistics(db):
    st = compute(db)
    assert (st.messages, st.conversations, st.participants) == (32, 1, 3)
    assert (st.first_day, st.last_day) == ("2025-12-16", "2026-11-12")
    assert st.active_days == 8 and st.span_days == 332
    assert st.busiest_day == ("2026-03-22", 12)
    assert st.longest_streak == (2, "2026-01-10", "2026-01-11")
    assert st.longest_silence == (128, "2026-07-07", "2026-11-11")
    assert st.per_sender == [("pierre", 16), ("remi", 10), ("fabien", 6)]
    assert sum(st.per_hour) == 32 and st.per_hour[16] == 9
    assert sum(st.per_weekday) == 32 and st.per_weekday[6] == 14        # dimanche 22 mars
    assert sum(map(sum, st.heatmap)) == 32
    # mois continus, zéros compris (février 2026 vide)
    assert st.per_month[:3] == [("2025-12", 3), ("2026-01", 2), ("2026-02", 0)]
    assert len(st.per_month) == 12
    assert st.media == {"photo": 2, "video": 1} and st.links == 1
    words = dict(st.top_words)
    assert words["super"] == 3 and "les" not in words and "est" not in words


def test_statistics_filtered_by_sender(db):
    st = compute(db, sender="remi")
    assert st.messages == 10 and st.per_sender == [("remi", 10)]
    assert compute(db, conversation_id="inexistante").messages == 0


def test_neighbour_day():
    days = {"2024-01-05": 1, "2024-01-20": 2, "2024-03-02": 1}
    assert neighbour_day(days, "2024-01-05", 1) == "2024-01-20"
    assert neighbour_day(days, "2024-01-10", -1) == "2024-01-05"
    assert neighbour_day(days, "2024-03-02", 1) is None
    assert neighbour_day(days, "2024-01-20", 1, "month") == "2024-03-02"
    assert neighbour_day(days, "2024-03-02", -1, "month") == "2024-01-05"
    assert neighbour_day(days, None, -1) == "2024-03-02"


def test_period_ngrams_exclusions_and_csv(synthetic_lib):
    from services.statistics_service import compute, to_csv
    db, _, convs = synthetic_lib
    v = convs["Voyage en Italie"].id
    july = compute(db, v, date_from="2025-07-01", date_to="2025-07-31")
    assert july.messages == 3 and july.first_day == "2025-07-07" and july.date_from == "2025-07-01"
    assert compute(db, v, date_to="2025-05-12").messages == 4
    full = compute(db)
    words = dict(full.top_words)
    assert "florence" in words or "Florence".lower() in words
    excl = dict(compute(db, excluded_words=["Florence"]).top_words)
    assert "florence" not in excl
    csv_text = to_csv(full, "Toute la bibliothèque")
    assert "Messages par mois" in csv_text and "Groupes de deux mots" in csv_text and ";" in csv_text


def test_ngrams_counted_only_when_repeated(tmp_path):
    from database.db_manager import Database
    from database.repositories import LibraryRepository
    from importer.import_manager import import_path
    from services.statistics_service import compute
    from tests.conftest import msg as m, page as pg
    d = tmp_path / "e"
    d.mkdir()
    body = "".join(m(i, f'<div class="text">{t}</div>', title=f"0{i}.03.2025 10:00:00 UTC+01:00")
                   for i, t in enumerate(["Le train de nuit part tôt", "Encore le train de nuit !",
                                          "Réservation du train de nuit faite", "Billet pour Rome",
                                          "Billet pour Rome encore", "Une phrase isolée"], 1))
    (d / "messages.html").write_text(pg(body))
    db = Database(tmp_path / "l.sqlite")
    LibraryRepository(db).save_import(import_path(d), d)
    st = compute(db)
    # les mots de moins de 3 lettres (« de ») sont ignorés : « train de nuit » → « train nuit »
    assert ("train nuit", 3) in st.top_bigrams
    # un mot courant (« pour ») coupe la suite : pas de faux groupe « billet rome »
    assert all(b != "billet rome" for b, _ in st.top_bigrams)
    assert all(n > 1 for _, n in st.top_bigrams)                # un groupe vu une seule fois n'est pas retenu
    db.close()


def test_compare_two_periods_normalizes_by_duration(synthetic_lib):
    from services.statistics_service import Scope, compare
    db, _, convs = synthetic_lib
    v = convs["Voyage en Italie"].id
    cmp = compare(db, Scope("Mai", v, date_from="2025-05-01", date_to="2025-05-31"),
                  Scope("Juillet", v, date_from="2025-07-01", date_to="2025-07-31"))
    rows = {r[0]: r for r in cmp.rows}
    assert rows["Messages"][1:3] == ("5", "3")
    assert rows["Durée de la période (jours)"][1:3] == ("31", "31")
    assert rows["Messages par jour (sur la période)"][3] == "-40 %"
    assert abs(sum(cmp.hours_pct[0]) - 100) < 0.5
    other = compare(db, Scope("Voyage", v), Scope("Famille", convs["Famille"].id))
    assert {r[0] for r in other.rows} >= {"Participants actifs", "Médias pour 100 messages"}
