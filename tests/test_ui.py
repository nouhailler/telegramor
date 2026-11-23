"""Tests de l'interface (rendu hors écran, sans affichage)."""

from __future__ import annotations

import os
import shutil
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from app.settings import AppSettings  # noqa: E402
from database.db_manager import Database  # noqa: E402
from database.repositories import LibraryRepository  # noqa: E402
from importer.import_manager import import_path  # noqa: E402
from services.media_service import ThumbnailLoader  # noqa: E402
from tests.conftest import REFERENCE_HTML, msg, page, service  # noqa: E402
from ui.message_view import MAX_ROWS  # noqa: E402
from ui.message_widgets import MessageBubbleRow, PillRow, VideoThumb  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def pump(app, n: int = 15) -> None:
    for _ in range(n):
        app.processEvents()
        time.sleep(0.025)
        ThumbnailLoader.instance().wait()
    app.processEvents()


@pytest.fixture
def settings(tmp_path):
    s = AppSettings(QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    s.s.clear()
    return s


@pytest.fixture
def library(tmp_path):
    d = tmp_path / "ChatExport"
    d.mkdir()
    shutil.copy(REFERENCE_HTML, d / "messages.html")
    db_path = tmp_path / "lib.sqlite"
    with Database(db_path) as db:
        LibraryRepository(db).save_import(import_path(d), d)
    return db_path


def make_window(app, db_path, settings) -> MainWindow:
    w = MainWindow(db_path, settings)
    w.resize(1400, 900)
    w.show()
    pump(app)
    return w


def test_empty_library_shows_welcome(app, tmp_path, settings):
    w = make_window(app, tmp_path / "vide.sqlite", settings)
    assert w.center.currentWidget() is w.welcome
    w.close()


def test_conversation_display(app, library, settings):
    w = make_window(app, library, settings)
    mv = w.message_view
    assert w.conv_list.model.rowCount() == 1
    assert mv.conv.name == "fabien"
    assert len(mv.rows) == 40
    pills = [r for r in mv.rows if isinstance(r, PillRow)]
    bubbles = [r for r in mv.rows if isinstance(r, MessageBubbleRow)]
    assert (len(pills), len(bubbles)) == (8, 32)
    assert mv.owner == "pierre"                       # détecté via les réactions
    out = [r for r in bubbles if r.bubble.property("outgoing")]
    assert len(out) == 16
    # ouverture sur le dernier message
    sb = mv.area.verticalScrollBar()
    assert sb.value() == sb.maximum()
    # vidéo : la bibliothèque de test ne contient pas les médias → signalé
    video_row = bubbles[-1]
    thumbs = video_row.findChildren(VideoThumb)
    assert thumbs and thumbs[0].note == "⚠ vidéo introuvable"
    w.close()


def test_reply_navigation_and_back(app, library, settings):
    w = make_window(app, library, settings)
    mv = w.message_view
    cid = mv.conv.id
    reply_seq = w.repo.seq_of_message(cid, 189181)
    target_seq = w.repo.seq_of_message(cid, 189180)
    mv.jump_to_seq(reply_seq, highlight=False, remember=False)
    pump(app)
    row = mv._row_for(reply_seq)
    mv._on_reply(row.msg)
    pump(app)
    target = mv._row_for(target_seq)
    assert target.bubble.property("highlighted") is True
    assert mv.back_btn.isEnabled()
    mv.go_back()
    pump(app)
    assert not mv.history.can_go_back()
    w.close()


def test_date_navigation(app, library, settings):
    w = make_window(app, library, settings)
    mv = w.message_view
    mv.go_to_day("2026-03-02")       # pas de message ce jour : jour suivant
    pump(app)
    first = mv._first_visible_row()
    assert first.msg.day == "2026-03-22"
    assert "22 mars 2026" in mv.date_badge.text()
    mv.go_first()
    pump(app)
    assert mv.first_visible_seq() == 0
    w.close()


def test_theme_zoom_and_panel(app, library, settings):
    w = make_window(app, library, settings)
    w.act_dark.setChecked(True)
    w.toggle_dark()
    w.change_zoom(1)
    pump(app)
    assert settings.dark_mode and settings.zoom == 110
    assert len(w.message_view.rows) == 40
    w.toggle_info_panel()
    assert not w.info_panel.isVisible() and not settings.info_panel_visible
    assert w.info_panel.gallery.model().rowCount() == 3
    assert w.info_panel.links.count() == 1
    w.close()


def test_position_restored_after_restart(app, library, settings):
    w = make_window(app, library, settings)
    w.message_view.go_to_day("2026-01-11")
    pump(app)
    seq = w.message_view.first_visible_seq()
    w.close()
    assert settings.last_seq(w.message_view.conv.id) == seq
    w2 = make_window(app, library, settings)
    assert w2.message_view.first_visible_seq() == seq
    w2.close()


def test_progressive_loading_large_conversation(app, tmp_path, settings):
    d = tmp_path / "big"
    d.mkdir()
    blocks = [service(-1, "1 February 2024")]
    blocks += [msg(i, f'<div class="text">message numéro {i}</div>', sender="Alice" if i % 2 else "Bob")
               for i in range(1, 3001)]
    (d / "messages.html").write_text(page("".join(blocks), name="Gros"))
    db_path = tmp_path / "big.sqlite"
    with Database(db_path) as db:
        LibraryRepository(db).save_import(import_path(d), d)
    w = make_window(app, db_path, settings)
    mv = w.message_view
    assert len(mv.rows) == 120                       # seule la fin est chargée
    assert mv.rows[-1].seq == 3000
    sb = mv.area.verticalScrollBar()
    for _ in range(10):                               # remonte le fil
        before = mv.first_visible_seq()
        sb.setValue(0)
        pump(app, 14)
        assert len(mv.rows) <= MAX_ROWS
        assert mv.first_visible_seq() <= before
    assert mv.rows[0].seq < 2400
    # l'ancre évite les sauts : la ligne visible reste proche après chargement
    mv.jump_to_seq(1500, highlight=False)
    pump(app)
    assert abs(mv.first_visible_seq() - 1500) < 20
    w.close()


def test_import_from_gui_runs_in_background(app, tmp_path, settings, monkeypatch):
    """Régression : les signaux du thread d'import doivent être traités dans le thread principal."""
    import threading

    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QProgressDialog

    d = tmp_path / "ChatExport"
    d.mkdir()
    shutil.copy(REFERENCE_HTML, d / "messages.html")
    w = make_window(app, tmp_path / "gui.sqlite", settings)
    main_thread = threading.get_ident()
    seen_threads: set[int] = set()
    reports: list[str] = []
    qt_warnings: list[str] = []
    progress_calls: list[int] = []
    real_dialog_set = QProgressDialog.setValue

    def record_set(self, v):              # appelé par le vrai slot de progression
        seen_threads.add(threading.get_ident())
        progress_calls.append(v)
        real_dialog_set(self, v)

    def record_report(text):
        seen_threads.add(threading.get_ident())
        reports.append(text)

    monkeypatch.setattr(QProgressDialog, "setValue", record_set)
    monkeypatch.setattr(w, "show_import_report", record_report)
    previous = qInstallMessageHandler(lambda mode, ctx, msg: qt_warnings.append(msg))
    try:
        w.run_import([str(d)])
        deadline = time.time() + 20
        while w._import_thread is not None and time.time() < deadline:
            pump(app, 2)
    finally:
        qInstallMessageHandler(previous)
    assert w._import_thread is None, "importation non terminée"
    assert reports and "40   ✔ complet" in reports[0]
    assert progress_calls
    assert seen_threads == {main_thread}
    assert not [m for m in qt_warnings if "another thread" in m]
    assert w.conv_list.model.rowCount() == 1
    assert w.center.currentWidget() is w.message_view
    w.close()


@pytest.fixture
def two_conversations(tmp_path, library):
    other = tmp_path / "Voyages"
    other.mkdir()
    (other / "messages.html").write_text(page(
        service(-1, "3 August 2023")
        + msg(1, '<div class="text">Un café à Rome demain ?</div>', sender="Claire",
              title="03.08.2023 09:00:00 UTC+02:00"), name="Voyages"))
    with Database(library) as db:
        LibraryRepository(db).save_import(import_path(other), other)
    return library


def test_global_search_opens_result_in_context(app, two_conversations, settings):
    w = make_window(app, two_conversations, settings)
    w.conv_list.select(next(c.id for c in w.repo.list_conversations() if c.name == "fabien"))
    pump(app)
    w.search("cafe")
    pump(app)
    panel = w.search_panel
    assert w.left.currentWidget() is panel
    assert panel.model.total == 2
    names = {panel.model.hits[i].conversation_name for i in range(2)}
    assert names == {"fabien", "Voyages"}
    # clic sur le résultat de l'autre conversation : elle s'ouvre sur le message, surligné
    row = next(i for i, h in enumerate(panel.model.hits) if h.conversation_name == "Voyages")
    panel.view.setCurrentIndex(panel.model.index(row))
    pump(app)
    mv = w.message_view
    assert mv.conv.name == "Voyages"
    hit = panel.model.hits[row]
    target = mv._row_for(hit.seq)
    assert target is not None and target.bubble.property("highlighted") is True
    assert mv.terms == ["cafe"]
    assert "background-color" in target.text_label.text()       # terme surligné dans la bulle
    # retour aux résultats : ils sont toujours là ; fermer la recherche retire le surlignage
    assert panel.model.total == 2
    w.close_search()
    pump(app)
    assert w.left.currentWidget() is w.conv_list and mv.terms == []
    assert w.conv_list.current_id() == mv.conv.id
    w.close()


def test_advanced_filters_from_gui(app, two_conversations, settings):
    w = make_window(app, two_conversations, settings)
    w.open_advanced_search()
    pump(app)
    f = w.search_panel.filters
    assert w.search_panel.filters_area.isVisible()
    f.content.setCurrentIndex(f.content.findData("photo"))
    w.search_panel.run()
    assert w.search_panel.model.total == 2
    f.reset()
    f.sender.setCurrentText("Claire")
    w.search_panel.run()
    assert w.search_panel.model.total == 1
    assert "Filtres (1)" in w.search_panel.filters_btn.text()
    w.close()


def test_find_in_conversation(app, library, settings):
    w = make_window(app, library, settings)
    mv = w.message_view
    mv.open_find_bar()
    assert mv.find_bar.isVisible()
    mv.find_bar.edit.setText("super")
    mv.find_bar.search()
    pump(app)
    assert mv.find_bar.count.text() == "3 / 3"
    assert mv.terms == ["super"]
    first = mv.find_bar.seqs[mv.find_bar.index]
    mv.find_bar.step(-1)
    pump(app)
    assert mv.find_bar.count.text() == "2 / 3"
    assert mv.find_bar.seqs[mv.find_bar.index] < first
    row = mv._row_for(mv.find_bar.seqs[mv.find_bar.index])
    assert row.bubble.property("highlighted") is True
    mv.find_bar.close_bar()
    pump(app)
    assert not mv.find_bar.isVisible() and mv.terms == []
    w.close()


def test_library_dialog_and_archive_filter(app, two_conversations, settings, tmp_path):
    w = make_window(app, two_conversations, settings)
    # filtre par archive dans la liste des conversations
    assert w.conv_list.archive_filter.isVisibleTo(w)
    voyages = next(a for a in w.repo.list_archives() if a.name == "Voyages")
    w.conv_list.archive_filter.setCurrentIndex(w.conv_list.archive_filter.findData(voyages.id))
    pump(app)
    assert [c.name for c in w.conv_list.model.items] == ["Voyages"]
    w.conv_list.archive_filter.setCurrentIndex(0)
    pump(app)
    assert w.conv_list.model.rowCount() == 2

    w.open_library()
    pump(app)
    dlg = w.library_dialog
    assert dlg.isVisible() and dlg.table.rowCount() == 2
    # déplacement d'une archive puis relocalisation depuis la fenêtre
    moved = tmp_path / "deplace" / "Voyages"
    moved.parent.mkdir()
    shutil.move(str(tmp_path / "Voyages"), str(moved))
    dlg.refresh()
    row = next(r for r in range(2) if dlg.table.item(r, 0).text() == "Voyages")
    assert dlg.table.item(row, 1).text() == "Introuvable"
    dlg.table.selectRow(row)
    assert dlg.relocate_to(dlg.selected(), str(moved))
    assert dlg.table.item(row, 1).text() == "OK"
    # retrait de l'archive : la conversation disparaît, les fichiers restent
    dlg.table.selectRow(row)
    dlg.delete(confirm=lambda: True)
    pump(app)
    assert dlg.table.rowCount() == 1 and (moved / "messages.html").exists()
    assert w.conv_list.model.rowCount() == 1
    assert not w.conv_list.archive_filter.isVisibleTo(w)
    dlg.close()
    w.close()


def test_reindex_from_library(app, library, settings, monkeypatch):
    w = make_window(app, library, settings)
    reports: list[str] = []
    monkeypatch.setattr(w, "show_import_report", reports.append)
    w.open_library()
    w.library_dialog.reindex()
    deadline = time.time() + 20
    while w._import_thread is not None and time.time() < deadline:
        pump(app, 2)
    assert reports and "avait déjà été importée" in reports[0]
    assert w.repo.library_stats()["messages"] == 32 and len(w.repo.list_archives()) == 1
    w.library_dialog.close()
    w.close()


def test_timeline_and_day_stepping(app, library, settings):
    w = make_window(app, library, settings)
    mv = w.message_view
    tl = w.info_panel.timeline
    assert tl.topLevelItemCount() == 2                         # 2026, 2025
    w.show_timeline()
    assert w.info_panel.tabs.currentWidget() is tl
    tl.day_selected.emit("2026-01-10")
    pump(app)
    assert mv._first_visible_row().msg.day == "2026-01-10"
    mv.step_day(1)
    pump(app)
    assert mv._first_visible_row().msg.day == "2026-01-11"
    mv.step_day(1, "month")
    pump(app)
    assert mv._first_visible_row().msg.day == "2026-03-01"
    assert tl.currentItem() is not None and tl.currentItem().data(0, Qt.UserRole + 1) == "2026-03-01"
    w.close()


def test_gallery_window(app, library, settings):
    w = make_window(app, library, settings)
    w.open_gallery()
    g = w._gallery
    pump(app)
    assert g.model.total == 2                                   # photos
    g.tabs.setCurrentIndex(1)
    assert g.model.total == 1                                   # vidéo
    g.tabs.setCurrentIndex(5)
    assert g.table.topLevelItemCount() == 1                     # lien
    g.tabs.setCurrentIndex(0)
    g.sender.setCurrentIndex(g.sender.findData("remi"))
    assert g.model.total == 0
    g.sender.setCurrentIndex(0)
    m = g.model.items[0]
    g.go_to_message.emit(m.conversation_id, m.message_seq)
    pump(app)
    row = w.message_view._row_for(m.message_seq)
    assert row is not None and row.bubble.property("highlighted") is True
    g.close()
    w.close()


def test_statistics_window(app, library, settings):
    w = make_window(app, library, settings)
    w.open_statistics()
    st = w._statistics
    pump(app)
    assert st.stats.messages == 32 and st.tiles.count() == 6
    assert st.months.clickable                                  # portée = conversation ouverte
    march = next(i for i, (ym, _) in enumerate(st.stats.per_month) if ym == "2026-03")
    st.months.bar_clicked.emit(march)
    pump(app)
    assert w.message_view._first_visible_row().msg.day == "2026-03-01"
    st.conv.setCurrentIndex(0)                                  # toute la bibliothèque
    assert not st.months.clickable and st.stats.conversations == 1
    st.close()
    w.close()
