"""Tests de l'orchestration de l'importation et du rapport."""

from __future__ import annotations

import json
import shutil

from importer import archive_detector
from importer.import_manager import import_path
from main import main
from tests.conftest import REFERENCE_HTML, msg, page, service


def test_reference_report(tmp_path):
    shutil.copy(REFERENCE_HTML, tmp_path / "messages.html")
    r = import_path(tmp_path, check_media=False).report
    assert r.is_complete
    assert (r.blocks_detected, r.blocks_parsed) == (40, 40)
    assert (r.messages_default, r.messages_joined, r.date_separators, r.messages_service) == (32, 8, 8, 0)
    assert sorted(r.senders) == ["faycal", "patrick", "robert"]
    assert (r.replies, r.replies_resolved) == (1, 1)
    assert (r.reactions_total, r.messages_with_reactions) == (2, 2)
    assert (r.photos, r.videos, r.audio_files) == (2, 1, 0)
    assert r.links == 1
    assert r.first_message == "2025-12-16T18:33:18+01:00"
    assert r.last_message == "2026-11-12T18:34:47+01:00"
    assert sum(a.code == "INITIALS_MISMATCH" for a in r.anomalies) == 6
    assert "RAPPORT D'IMPORTATION" in r.to_text()


def test_multi_file_conversation(tmp_path):
    d = tmp_path / "export"
    d.mkdir()
    (d / "messages.html").write_text(page(
        service(-1, "1 February 2024") + msg(1, '<div class="text">a</div>', sender="Zoé")
        + '\n', extra_after_history='<a class="pagination block_link" href="messages2.html">Next</a>'))
    (d / "messages2.html").write_text(page(
        msg(2, '<div class="text">suite</div>', joined=True)
        + msg(3, '<div class="reply_to details">In reply to <a href="messages.html#go_to_message1">'
                 'this message</a></div><div class="text">r</div>', sender="Yann")))
    (d / "messages10.html").write_text(page(msg(4, '<div class="text">fin</div>', sender="Zoé")))

    _, sources = archive_detector.detect(d)
    assert [f.name for f in sources[0].files] == ["messages.html", "messages2.html", "messages10.html"]

    res = import_path(d)
    conv = res.conversations[0]
    assert conv.source_files == ["messages.html", "messages2.html", "messages10.html"]
    assert [m.message_id for m in conv.messages] == [-1, 1, 2, 3, 4]
    assert conv.messages[2].sender == "Zoé" and conv.messages[2].sender_inherited
    assert len({m.conversation_id for m in conv.messages}) == 1
    assert res.report.replies_resolved == 1
    assert conv.participants == ["Zoé", "Yann"]


def test_full_account_export_layout(tmp_path):
    for i, name in enumerate(["Alice", "Bob"], start=1):
        d = tmp_path / "chats" / f"chat_00{i}"
        d.mkdir(parents=True)
        (d / "messages.html").write_text(page(msg(i, '<div class="text">x</div>'), name=name))
    (tmp_path / "export_results.html").write_text("<html></html>")
    res = import_path(tmp_path)
    assert sorted(c.name for c in res.conversations) == ["Alice", "Bob"]
    assert res.report.conversations == 2 and res.report.files_parsed == 2


def test_duplicate_ids_and_chronology(tmp_path):
    (tmp_path / "messages.html").write_text(page(
        msg(1, '<div class="text">a</div>', title="02.02.2024 10:00:00 UTC+01:00")
        + msg(1, '<div class="text">b</div>', title="01.02.2024 10:00:00 UTC+01:00")))
    codes = {a.code for a in import_path(tmp_path).report.anomalies}
    assert {"DUPLICATE_ID", "CHRONOLOGY"} <= codes


def test_independent_count_detects_hidden_blocks(tmp_path):
    # Un bloc présent dans le texte brut mais absent du DOM doit être signalé.
    (tmp_path / "messages.html").write_text(page(
        msg(1, '<div class="text">a</div>') + '<!-- <div class="message default" id="message2"> -->'))
    r = import_path(tmp_path).report
    assert not r.is_complete
    assert {"COUNT_MISMATCH", "DOM_COUNT_MISMATCH"} <= {a.code for a in r.anomalies}


def test_empty_directory(tmp_path):
    r = import_path(tmp_path).report
    assert r.conversations == 0 and r.anomalies[0].code == "NO_CONVERSATION"


def test_cli_writes_json(tmp_path, capsys):
    shutil.copy(REFERENCE_HTML, tmp_path / "messages.html")
    out = tmp_path / "r.json"
    msgs = tmp_path / "m.json"
    code = main(["importer", str(tmp_path), "--json", str(out), "--messages", str(msgs)])
    assert code == 0  # aucune erreur (fichiers manquants = avertissements)
    data = json.loads(out.read_text())
    assert data["blocks_parsed"] == 40 and data["is_complete"]
    conv = json.loads(msgs.read_text())[0]
    assert len(conv["messages"]) == 40
    assert "RAPPORT D'IMPORTATION" in capsys.readouterr().out


def test_parallel_import_identical_to_sequential(tmp_path, monkeypatch):
    """Analyse parallèle + raccordement = lecture séquentielle, y compris aux jonctions de fichiers."""
    d = tmp_path / "export"
    d.mkdir()
    files = [
        service(-1, "1 February 2024") + msg(1, '<div class="text">a</div>', sender="Zoé"),
        msg(2, '<div class="text">regroupé en tête de fichier</div>', joined=True)
        + msg(3, '<div class="text">b</div>', sender="Yann"),
        msg(4, '<div class="text">c</div>', joined=True, title="02.02.2024 10:00:00 UTC+01:00"),   # ≠ séparateur
        service(-2, "3 February 2024") + msg(5, '<div class="text">d</div>', sender="Zoé",
                                             title="03.02.2024 10:00:00 UTC+01:00"),
    ]
    for i, h in enumerate(files):
        (d / f"messages{i + 1 if i else ''}.html").write_text(page(h))

    def run(workers: str):
        monkeypatch.setenv("TAE_WORKERS", workers)
        r = import_path(d)
        msgs = [m.to_dict() for c in r.conversations for m in c.messages]
        codes = sorted((a.code, a.html_id or "") for a in r.report.anomalies)
        return msgs, codes

    seq_msgs, seq_codes = run("1")
    par_msgs, par_codes = run("3")
    assert par_msgs == seq_msgs and par_codes == seq_codes
    by_id = {m["html_id"]: m for m in seq_msgs}
    assert by_id["message2"]["sender"] == "Zoé" and by_id["message2"]["sender_inherited"]
    assert by_id["message4"]["sender"] == "Yann"
    assert [m["position"] for m in seq_msgs] == list(range(len(seq_msgs)))
    assert ("SEPARATOR_MISMATCH", "message4") in seq_codes
    assert not any(c == "JOINED_WITHOUT_SENDER" for c, _ in seq_codes)
