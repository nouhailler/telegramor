"""Interface des fonctions 1.3 : données personnelles, fils, exports, outils (hors écran)."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget  # noqa: E402

from app.settings import AppSettings  # noqa: E402
from database.db_manager import Database  # noqa: E402
from database.repositories import LibraryRepository  # noqa: E402
from importer.import_manager import import_path  # noqa: E402
from services.media_service import ThumbnailLoader  # noqa: E402
from tests.conftest import build_synthetic_exports  # noqa: E402
from ui.message_widgets import MessageBubbleRow  # noqa: E402


def pump(app, n: int = 10) -> None:
    for _ in range(n):
        app.processEvents()
        time.sleep(0.02)
        ThumbnailLoader.instance().wait()
    app.processEvents()


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    from app.main_window import MainWindow
    a, b = build_synthetic_exports(tmp_path / "exports")
    path = tmp_path / "lib.sqlite"
    with Database(path) as db:
        repo = LibraryRepository(db)
        repo.save_import(import_path(a), a)
        repo.save_import(import_path(b), b)
    st = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    st.s.clear()
    # aucune boîte modale bloquante pendant les tests
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    w = MainWindow(path, st)
    w.resize(1400, 900)
    w.show()
    pump(qapp, 20)
    yield w
    w.close()


def _open(win, qapp, name: str):
    conv = next(c for c in win.repo.list_conversations() if c.name == name)
    win.conv_list.select(conv.id)
    pump(qapp, 15)
    return conv


def _bubble(win, message_id: int) -> MessageBubbleRow:
    return next(r for r in win.message_view.rows if isinstance(r, MessageBubbleRow) and r.msg.message_id == message_id)


def test_favorite_note_collection_from_bubble(win, qapp, monkeypatch):
    conv = _open(win, qapp, "Voyage en Italie")
    msg = _bubble(win, 2).msg
    win._on_personal_action("favorite", msg)
    pump(qapp)
    assert _bubble(win, 2).msg.favorite and win.personal.is_favorite(conv.id, 2)
    assert _bubble(win, 2).findChild(QWidget, "FavoriteMark") is not None

    from ui import personal_window
    monkeypatch.setattr(personal_window.NoteDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(personal_window.NoteDialog, "text", property(lambda self: "Réserver le train"))
    win._on_personal_action("note", msg)
    pump(qapp)
    row = _bubble(win, 2)
    assert row.msg.note == "Réserver le train"
    assert row.findChild(QWidget, "PersonalNote") is not None

    cid = win.personal.create_collection("Italie")
    win._on_personal_action(f"collection:{cid}", msg)
    pump(qapp)
    assert _bubble(win, 2).msg.collections == 1
    assert win.message_view._ctx().collections == [(cid, "Italie")]


def test_personal_window_lists_and_navigates(win, qapp):
    conv = _open(win, qapp, "Voyage en Italie")
    win.personal.set_favorite(conv.id, 6)
    win.personal.set_note(conv.id, 3, "Train de nuit validé")
    cid = win.personal.create_collection("Souvenirs")
    win.personal.add_to_collection(cid, conv.id, 6, 0)
    win.open_personal()
    pw = win._personal_window
    pump(qapp)
    assert pw.fav_table.rowCount() == 1 and pw.note_table.rowCount() == 1
    assert pw.item_table.rowCount() == 1 and pw.coll_list.count() == 1
    pw.note_search.setText("valide")
    assert pw.note_table.rowCount() == 1
    pw.note_search.setText("inexistant")
    assert pw.note_table.rowCount() == 0
    from ui.personal_window import ROLE_ITEM
    item = pw.fav_table.item(0, 0).data(ROLE_ITEM)
    pw._go(item)
    pump(qapp, 15)
    assert any(r.msg.message_id == 6 for r in win.message_view.rows)
    exported = []
    pw.export_requested.disconnect()
    pw.export_requested.connect(lambda title, keys: exported.append((title, keys)))
    pw._export("Favoris", pw._items(pw.fav_table))
    assert exported == [("Favoris", [(conv.id, 6)])]
    pw.close()


def test_thread_dialog_and_read_marker(win, qapp):
    conv = _open(win, qapp, "Voyage en Italie")
    win.show_thread(conv.id, 3)
    dlg = win._thread_dialog
    assert dlg.tree.topLevelItemCount() == 1                           # racine : message 1
    assert dlg.tree.topLevelItem(0).childCount() == 2                  # réponses 2 et 4
    dlg.close()
    win.show_thread(conv.id, 5)
    assert "absent" in win._thread_dialog.tree.topLevelItem(0).text(0)
    win._thread_dialog.close()

    # Repère de lecture : mémorisé, affiché à la visite suivante, reprise au message suivant
    win.message_view.mark_read_until(_bubble(win, 3).msg)
    assert win.personal.read_marker(conv.id) == 3
    _open(win, qapp, "Famille")
    _open(win, qapp, "Voyage en Italie")
    assert win.message_view._marker_shown == 3
    assert _bubble(win, 3).findChild(QWidget, "ReadMarker") is not None
    assert win.message_view.resume_reading()
    win.message_view.reset_reading()
    assert win.personal.read_marker(conv.id) is None and win.message_view._marker_shown is None


def test_search_reply_filter_history_and_saved(win, qapp):
    win.search("train")
    pump(qapp)
    panel = win.search_panel
    assert panel.model.total >= 1
    panel._emit_index(panel.model.index(0))
    assert [q.text for q in win.personal.search_history()] == ["train"]
    from database.search_engine import SearchQuery
    win.personal.save_search("Réponses de Léa", SearchQuery(sender="Léa", is_reply=True))
    saved = win.personal.saved_searches()[0]
    panel.apply_query(saved.query)
    pump(qapp)
    assert panel.filters.reply.currentData() is True and panel.filters.sender.currentText() == "Léa"
    assert [h.message_id for h in panel.model.hits] == [3]
    panel._fill_more_menu()
    titles = [a.text() for a in panel.more_menu.actions()]
    assert "Enregistrer cette recherche…" in titles and "Exporter les résultats…" in titles


def test_export_and_print_dialogs(win, qapp, tmp_path, monkeypatch):
    from ui import conversation_export_dialog as ced
    _open(win, qapp, "Voyage en Italie")
    captured = {}
    monkeypatch.setattr(ced.ConversationExportDialog, "exec",
                        lambda self: captured.setdefault("dlg", self) and QDialog.Accepted)
    win.export_conversation()
    dlg = captured["dlg"]
    assert dlg.ok.isEnabled() and "message" in dlg.preview.text()
    dlg.whole.setChecked(False)
    dlg.date_from.setDate(dlg.date_from.date().fromString("2025-07-01", "yyyy-MM-dd"))
    assert all((m.day or "") >= "2025-07-01" for m in dlg._messages)
    out = tmp_path / "export.md"
    monkeypatch.setattr(ced.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(ced.QMessageBox, "exec", lambda self: 0)
    dlg.fmt.setCurrentIndex(dlg.fmt.findData("md"))
    dlg._run()
    assert out.is_file() and "Premier matin à Florence" in out.read_text()
    # Impression sans QtPrintSupport : page HTML prête à imprimer ouverte dans le navigateur
    opened = []
    monkeypatch.setattr(ced, "PRINT_SUPPORT", False)
    monkeypatch.setattr(ced, "open_with_system", lambda p: opened.append(p) or True)
    captured.clear()
    win.print_conversation()
    captured["dlg"]._run()
    assert opened and opened[0].suffix == ".html" and "Ctrl+P" in opened[0].read_text()


def test_tools_dialogs(win, qapp, tmp_path, monkeypatch):
    from ui import tools_dialogs as td
    win.open_diagnostics()
    dlg = win._diagnostics
    for _ in range(200):
        pump(qapp, 2)
        if dlg.report is not None:
            break
    assert dlg.report is not None and not dlg.report.errors and "Recommandation" in dlg.view.toPlainText()
    dlg.close()

    win.open_duplicates()
    dd = win._duplicates
    dd.compute()
    for _ in range(200):
        pump(qapp, 2)
        if not dd.hash_btn.isEnabled() and dd.tree.topLevelItemCount():
            break
    assert dd.tree.topLevelItemCount() == 1
    dd.close()
    # galerie : option « masquer les fichiers identiques »
    win.open_gallery()
    g = win._gallery
    g.set_conversation(None)
    pump(qapp, 10)
    n_all = g.model.rowCount()
    g.unique_check.setChecked(True)
    pump(qapp, 10)
    assert g.model.rowCount() == n_all - 1
    g.close()

    td.DependenciesDialog(win).close()

    bd = td.BackupDialog(win.db, win.settings.file_path(), "1.3", win)
    target = tmp_path / "sauv.zip"
    monkeypatch.setattr(td.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    bd.create()
    assert target.is_file()
    bd.close()


def test_statistics_period_words_export_and_compare(win, qapp, tmp_path, monkeypatch):
    from ui import statistics_window as sw
    _open(win, qapp, "Voyage en Italie")
    win.open_statistics()
    s = win._statistics
    pump(qapp)
    total = s.stats.messages
    s.date_from.set_value("2025-07-01")
    s.date_from.changed.emit()
    assert s.stats.messages < total and s.stats.date_from == "2025-07-01"
    assert "href=" in s.words.text()
    searched = []
    s.search_word.disconnect()
    s.search_word.connect(searched.append)
    s.words.linkActivated.emit("florence")
    assert searched == ["florence"]
    out = tmp_path / "stats.csv"
    monkeypatch.setattr(sw.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    s.export_csv()
    assert "Messages par heure" in out.read_text(encoding="utf-8-sig")
    png = tmp_path / "stats.png"
    monkeypatch.setattr(sw.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(png), "")))
    s.export_png()
    assert png.read_bytes().startswith(b"\x89PNG")
    s.open_compare()
    c = s._compare
    c.a.year.setCurrentIndex(c.a.year.findData("2025"))
    c.b.conv.setCurrentIndex(c.b.conv.findText("Famille"))
    assert c.table.rowCount() >= 10
    assert c.table.horizontalHeaderItem(1).text() == "A — Toute la bibliothèque · 2025"
    assert c.table.horizontalHeaderItem(2).text() == "B — Famille"
    c.close()
    s.close()
