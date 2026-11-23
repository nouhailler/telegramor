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
    assert st.per_sender == [("patrick", 16), ("robert", 10), ("faycal", 6)]
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
    st = compute(db, sender="robert")
    assert st.messages == 10 and st.per_sender == [("robert", 10)]
    assert compute(db, conversation_id="inexistante").messages == 0


def test_neighbour_day():
    days = {"2024-01-05": 1, "2024-01-20": 2, "2024-03-02": 1}
    assert neighbour_day(days, "2024-01-05", 1) == "2024-01-20"
    assert neighbour_day(days, "2024-01-10", -1) == "2024-01-05"
    assert neighbour_day(days, "2024-03-02", 1) is None
    assert neighbour_day(days, "2024-01-20", 1, "month") == "2024-03-02"
    assert neighbour_day(days, "2024-03-02", -1, "month") == "2024-01-05"
    assert neighbour_day(days, None, -1) == "2024-03-02"
