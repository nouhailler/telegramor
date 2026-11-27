"""Diagnostic, doublons de médias, sauvegarde, exports, dépendances, mises à jour."""

from __future__ import annotations

import io
import json
import stat
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from database.db_manager import Database
from services import backup, conversation_export as cx, dependencies, diagnostics, media_dedup, update_check
from services.personal_data import PersonalData


def _snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    return {str(p.relative_to(folder)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in folder.rglob("*") if p.is_file()}


# --------------------------------------------------------------------------- #
# Doublons de médias
# --------------------------------------------------------------------------- #

def test_media_dedup_groups_and_gallery(synthetic_lib, tmp_path):
    db, repo, convs = synthetic_lib
    before = _snapshot(tmp_path / "exports")
    assert media_dedup.pending_count(db) == 3                      # 3 photos présentes, 1 absente
    s = media_dedup.compute_hashes(db, repo)
    assert (s.hashed, s.missing, s.errors) == (3, 0, [])
    assert media_dedup.pending_count(db) == 0
    groups = media_dedup.duplicate_groups(db, repo)
    assert len(groups) == 1
    occ = groups[0].occurrences
    assert {o.conversation_name for o in occ} == {"Voyage en Italie", "Famille"}
    assert {o.message_id for o in occ} == {6, 2}
    assert len(media_dedup.occurrences(db, repo, occ[0].media_id)) == 2
    st = media_dedup.stats(db)
    assert st["groups"] == 1 and st["extra_copies"] == 1
    # Galerie : le doublon exact n'apparaît qu'une fois dans la vue générale…
    assert repo.gallery_count(("photo",)) == 4
    assert repo.gallery_count(("photo",), unique=True) == 3
    # … mais reste visible si son autre occurrence est hors du filtre courant
    fam = convs["Famille"].id
    assert repo.gallery_count(("photo",), conversation_id=fam, unique=True) == 2
    assert repo.gallery_count(("photo",), year="2025", sender="Inès", unique=True) == 1
    page = repo.gallery_page(("photo",), unique=True)
    assert len(page) == 3 and all(p.message_id is not None for p in page)
    # Réindexation : les empreintes sont reprises du cache, sans relire les fichiers
    db.conn.execute("DELETE FROM media_hashes")
    s2 = media_dedup.compute_hashes(db, repo)
    assert s2.from_cache == 3 and s2.hashed == 0
    assert _snapshot(tmp_path / "exports") == before             # rien n'a été modifié


def test_media_dedup_cancel(synthetic_lib):
    db, repo, _ = synthetic_lib
    s = media_dedup.compute_hashes(db, repo, progress=lambda i, n: i < 1)
    assert s.cancelled and media_dedup.pending_count(db) == 2


# --------------------------------------------------------------------------- #
# Diagnostic
# --------------------------------------------------------------------------- #

def test_diagnostics_report(synthetic_lib, tmp_path):
    db, repo, convs = synthetic_lib
    before = _snapshot(tmp_path / "exports")
    PersonalData(db).set_note(convs["Famille"].id, 4242, "message disparu")
    steps = []
    rep = diagnostics.run_diagnostics(db, repo, progress=lambda label, i, n: steps.append(label) or True)
    assert steps[-1] == "Terminé" and not rep.cancelled
    titles = {f.title: f for f in rep.findings}
    assert not rep.errors
    assert titles["Médias référencés mais introuvables"].count == 1
    assert titles["Réponses dont le message d'origine est absent des archives"].count == 1
    orphan = next(f for f in rep.findings if f.title.startswith("Fichiers présents dans « ExportFamille »"))
    assert orphan.details == ["photos/orphelin.jpg"]
    assert any(f.category == "Données personnelles" for f in rep.findings)
    assert rep.checked["Messages"] > 0 and rep.checked["Archives"] == 2
    md = rep.to_markdown()
    assert "# Diagnostic" in md and "Recommandation" in md
    assert _snapshot(tmp_path / "exports") == before               # lecture seule


def test_diagnostics_detects_broken_fts_and_missing_archive(synthetic_lib, tmp_path):
    db, repo, _ = synthetic_lib
    # désynchronise volontairement l'index plein texte
    db.conn.execute("INSERT INTO messages_fts(messages_fts, rowid, text, sender) VALUES ('delete', "
                    "(SELECT MIN(id) FROM messages WHERE text != ''), "
                    "(SELECT text FROM messages WHERE id = (SELECT MIN(id) FROM messages WHERE text != '')), "
                    "(SELECT sender FROM messages WHERE id = (SELECT MIN(id) FROM messages WHERE text != '')))")
    db.conn.commit()
    (tmp_path / "exports" / "ExportFamille").rename(tmp_path / "exports" / "Deplacee")
    rep = diagnostics.run_diagnostics(db, repo, scan_orphans=False)
    titles = [f.title for f in rep.errors]
    assert "Index plein texte des messages incohérent" in titles
    assert any(t.startswith("Archive introuvable") for t in titles)
    repo.rebuild_search_index()                                    # correction explicite
    rep2 = diagnostics.run_diagnostics(db, repo, scan_orphans=False)
    assert "Index plein texte des messages incohérent" not in [f.title for f in rep2.errors]


def test_diagnostics_cancel(synthetic_lib):
    db, repo, _ = synthetic_lib
    rep = diagnostics.run_diagnostics(db, repo, progress=lambda label, i, n: i < 2)
    assert rep.cancelled and rep.summary() == "Diagnostic interrompu."


# --------------------------------------------------------------------------- #
# Sauvegarde et restauration
# --------------------------------------------------------------------------- #

def test_backup_and_restore(synthetic_lib, tmp_path):
    db, repo, convs = synthetic_lib
    pd = PersonalData(db)
    v = convs["Voyage en Italie"].id
    pd.set_favorite(v, 6)
    pd.set_note(v, 6, "Pour l'album photo")
    settings = tmp_path / "telegramor.ini"
    settings.write_text("[ui]\ndark_mode=true\n")
    dest = tmp_path / "sauvegardes" / backup.default_backup_name()
    man = backup.create_backup(db, dest, "1.3", settings_file=settings)
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    assert set(man.contents) == {backup.LIBRARY, backup.PERSONAL, backup.SETTINGS}
    read = backup.read_manifest(dest)
    assert read.personal_counts["notes"] == 1 and "Bibliothèque complète" in read.describe()

    # Restauration des données personnelles seules (fusion) dans une base vierge
    fresh = Database(tmp_path / "vierge.sqlite")
    added = backup.restore_personal_data(fresh, dest)
    assert added["notes"] == 1 and PersonalData(fresh).note(v, 6) == "Pour l'album photo"
    fresh.close()

    # Restauration complète : la base actuelle est conservée à côté
    pd.set_note(v, 6, "modifiée après la sauvegarde")
    db_path = Path(db.path)
    db.close()
    settings.write_text("[ui]\ndark_mode=false\n")
    kept = backup.restore_library(dest, db_path, settings_file=settings)
    assert kept.exists() and "dark_mode=true" in settings.read_text()
    reopened = Database(db_path)
    assert PersonalData(reopened).note(v, 6) == "Pour l'album photo"
    assert reopened.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] > 0
    reopened.close()
    db.conn = Database(db_path).conn                              # pour la fermeture par la fixture


def test_backup_rejects_bad_or_tampered_files(synthetic_lib, tmp_path):
    db, _, _ = synthetic_lib
    bad = tmp_path / "pas_une_sauvegarde.zip"
    bad.write_bytes(b"rien")
    with pytest.raises(backup.BackupError):
        backup.read_manifest(bad)
    dest = tmp_path / "s.zip"
    backup.create_backup(db, dest, "1.3", include_library=False)
    # altération du contenu : l'empreinte ne correspond plus
    with zipfile.ZipFile(dest) as z:
        files = {n: z.read(n) for n in z.namelist()}
    files[backup.PERSONAL] = files[backup.PERSONAL].replace(b"telegramor", b"telegramoR", 1)
    files["../../evil.txt"] = b"x"                                 # membre malveillant : jamais extrait
    tampered = tmp_path / "t.zip"
    with zipfile.ZipFile(tampered, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    with pytest.raises(backup.BackupError, match="corrompu"):
        backup.restore_personal_data(db, tampered)
    assert not (tmp_path.parent / "evil.txt").exists()
    with pytest.raises(backup.BackupError, match="ne contient pas"):
        backup.restore_library(dest, tmp_path / "x.sqlite")


# --------------------------------------------------------------------------- #
# Exports de conversations
# --------------------------------------------------------------------------- #

def test_conversation_exports_all_formats(synthetic_lib, tmp_path, qapp):
    db, repo, convs = synthetic_lib
    v = convs["Voyage en Italie"].id
    PersonalData(db).set_note(v, 2, "NOTE-PRIVEE-SECRETE")
    msgs = cx.gather_conversation(repo, v)
    assert [m.message_id for m in msgs if m.kind == "default"] == [1, 2, 3, 4, 5, 6, 7, 8]
    july = cx.gather_conversation(repo, v, day_from="2025-07-01", day_to="2025-07-08")
    assert [m.message_id for m in july if m.kind == "default"] == [6]
    out = tmp_path / "out"
    for fmt in cx.FORMATS:
        res = cx.export_messages(msgs, out / f"voyage{cx.EXTENSIONS[fmt]}", fmt, "Voyage en Italie")
        assert res.path.is_file() and res.path.stat().st_size > 200
    html = (out / "voyage.html").read_text()
    md = (out / "voyage.md").read_text()
    data = json.loads((out / "voyage.json").read_text())
    for text in (html, md, json.dumps(data, ensure_ascii=False)):
        assert "NOTE-PRIVEE-SECRETE" not in text                  # jamais de données personnelles
        assert "Premier matin à Florence" in text
    assert "<script" not in html and "break-inside: avoid" in html and "@page" in html
    assert data["messages"][1]["reply_to"] == 1 and data["participants"][0] in ("Léa", "Marc")
    assert (out / "voyage.pdf").read_bytes().startswith(b"%PDF")


def test_export_escapes_html_and_copies_media(synthetic_lib, tmp_path, qapp):
    db, repo, convs = synthetic_lib
    v = convs["Voyage en Italie"].id
    msgs = cx.gather_conversation(repo, v)
    msgs[1].text = "<script>alert('x')</script> & <b>gras</b>"
    html = cx.to_html(msgs, "Titre <i>dangereux</i>")
    assert "<script>alert" not in html and "&lt;script&gt;" in html and "<i>dangereux" not in html
    res = cx.export_messages(msgs, tmp_path / "e" / "voyage.html", cx.FMT_HTML, "Voyage", include_media=True)
    assert res.media_copied == 2 and res.media_dir is not None
    page = (tmp_path / "e" / "voyage.html").read_text()
    assert 'src="voyage_fichiers/florence.jpg"' in page
    # un second export ne remplace jamais les fichiers déjà copiés
    res2 = cx.export_messages(msgs, tmp_path / "e" / "voyage.html", cx.FMT_MARKDOWN, "Voyage", include_media=True)
    assert res2.media_copied == 2
    assert sorted(p.name for p in (tmp_path / "e" / "voyage_fichiers").iterdir()) == [
        "florence (2).jpg", "florence.jpg", "sienne (2).jpg", "sienne.jpg"]


def test_export_selection_across_conversations(synthetic_lib, tmp_path):
    db, repo, convs = synthetic_lib
    v, f = convs["Voyage en Italie"].id, convs["Famille"].id
    msgs = cx.gather_keys(repo, [(f, 1), (v, 6), (v, 6), (v, 4242)])
    assert [(m.conversation_id, m.message_id) for m in msgs] == [(v, 6), (f, 1)]
    md = cx.to_markdown(msgs, "Sélection", conv_names={v: "Voyage en Italie", f: "Famille"})
    assert "_(Famille)_" in md
    p = cx.printable_html(msgs, "Sélection / test", tmp_path / "impr")
    assert p.name == "Sélection _ test.html" and "Ctrl+P" in p.read_text()


# --------------------------------------------------------------------------- #
# Dépendances et mises à jour
# --------------------------------------------------------------------------- #

def test_dependencies_check_and_commands(tmp_path):
    statuses = dependencies.check_all()
    by_key = {s.dep.key: s for s in statuses}
    assert by_key["qtcore"].available and by_key["bs4"].available
    assert all(s.dep.debian for s in statuses)
    fake = [dependencies.DependencyStatus(by_key["printsupport"].dep, False),
            dependencies.DependencyStatus(by_key["multimedia"].dep, False),
            dependencies.DependencyStatus(by_key["qtcore"].dep, True)]
    assert dependencies.install_command(fake, "debian") == \
        "sudo apt install python3-pyside6.qtprintsupport python3-pyside6.qtmultimedia"
    assert dependencies.install_command(fake, "fedora") == "sudo dnf install python3-pyside6"
    assert dependencies.install_command(fake, "autre") == "python3 -m pip install PySide6"
    assert dependencies.install_command(fake[2:], "debian") == ""
    osr = tmp_path / "os-release"
    osr.write_text('ID=linuxmint\nID_LIKE="ubuntu debian"\n')
    assert dependencies.detect_distribution(osr) == "debian"
    osr.write_text("ID=fedora\n")
    assert dependencies.detect_distribution(osr) == "fedora"
    assert dependencies.detect_distribution(tmp_path / "absent") == "autre"
    missing_req = [dependencies.DependencyStatus(by_key["lxml"].dep, False, "No module named 'lxml'")]
    assert "python3-lxml" in dependencies.terminal_report(missing_req) or \
        dependencies.detect_distribution() != "debian"


def test_update_check_parsing_and_request():
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        seen["url"], seen["headers"], seen["method"] = req.full_url, dict(req.header_items()), req.get_method()
        return Resp(json.dumps({"tag_name": "v1.4.0", "published_at": "2026-12-01T10:00:00Z",
                                "html_url": "https://github.com/nouhailler/telegramor/releases/tag/v1.4.0",
                                "body": "Notes"}).encode())

    info = update_check.check_latest("1.3", opener=opener)
    assert info.newer and info.latest == "1.4.0" and info.published == "2026-12-01"
    assert seen["method"] == "GET" and seen["url"] == update_check.RELEASES_API
    assert seen["headers"]["User-agent"] == "Telegramor-update-check"
    assert "Cookie" not in seen["headers"] and "Authorization" not in seen["headers"]
    assert not update_check.parse_release({"tag_name": "1.3.0"}, "1.3").newer
    assert update_check.parse_release({"tag_name": "2.0", "html_url": "https://evil.example/x"}, "1.3").url \
        == update_check.RELEASES_PAGE
    with pytest.raises(ValueError):
        update_check.parse_release({}, "1.3")
    now = datetime(2026, 12, 10)
    assert update_check.auto_check_due(None) and update_check.auto_check_due("pas une date")
    assert not update_check.auto_check_due((now - timedelta(days=2)).isoformat(), now)
    assert update_check.auto_check_due((now - timedelta(days=8)).isoformat(), now)


def test_update_check_offline_raises_oserror():
    def opener(req, timeout):
        raise OSError("réseau indisponible")
    with pytest.raises(OSError):
        update_check.check_latest("1.3", opener=opener)
