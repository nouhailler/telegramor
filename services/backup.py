"""Sauvegarde et restauration de la bibliothèque Telegramor.

Une sauvegarde est une archive ZIP privée (droits 0600) contenant :
- `manifest.json`            : version, date, contenu, empreintes SHA-256 ;
- `donnees-personnelles.json`: favoris, notes, collections, marqueurs, recherches ;
- `bibliotheque.sqlite`      : copie cohérente de la base (API de sauvegarde
                               SQLite, sûre même pendant l'utilisation) — facultatif ;
- `parametres.ini`           : préférences de l'application — si disponibles.

Ce qui N'EST PAS sauvegardé : les exports Telegram eux-mêmes (fichiers HTML et
médias). Ils restent à l'emplacement choisi par l'utilisateur, qui en garde la
maîtrise ; la base ne contient que leur chemin. Après une restauration sur une
autre machine, il suffit de relocaliser les archives.

La restauration lit uniquement les noms de fichiers attendus dans le ZIP
(aucune extraction de chemins arbitraires) et vérifie l'intégrité de la base
avant de remplacer quoi que ce soit ; la base actuelle est conservée à côté.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from database.db_manager import SCHEMA_VERSION, Database
from services.personal_data import PersonalData

FORMAT = "telegramor-backup"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
PERSONAL = "donnees-personnelles.json"
LIBRARY = "bibliotheque.sqlite"
SETTINGS = "parametres.ini"


class BackupError(Exception):
    pass


@dataclass
class BackupManifest:
    created_at: str
    app_version: str
    schema_version: int
    contents: list[str]
    sha256: dict[str, str] = field(default_factory=dict)
    personal_counts: dict[str, int] = field(default_factory=dict)
    library_counts: dict[str, int] = field(default_factory=dict)

    def describe(self) -> str:
        lines = [f"Sauvegarde du {self.created_at.replace('T', ' à ')} (Telegramor {self.app_version}, schéma "
                 f"v{self.schema_version})"]
        if LIBRARY in self.contents:
            lc = self.library_counts
            lines.append(f"· Bibliothèque complète : {lc.get('archives', 0)} archive(s), "
                         f"{lc.get('messages', 0):,} messages".replace(",", " "))
        if PERSONAL in self.contents:
            pc = {k: v for k, v in self.personal_counts.items() if v}
            lines.append("· Données personnelles : " + (", ".join(f"{v} {k}" for k, v in pc.items()) or "aucune"))
        if SETTINGS in self.contents:
            lines.append("· Paramètres de l'application")
        return "\n".join(lines)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def default_backup_name() -> str:
    return f"telegramor-sauvegarde-{datetime.now():%Y-%m-%d_%H%M}.zip"


def create_backup(db: Database, destination: Path, app_version: str, settings_file: Path | None = None,
                  include_library: bool = True) -> BackupManifest:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pd = PersonalData(db)
    with tempfile.TemporaryDirectory(prefix="telegramor-") as tmp:
        tmpd = Path(tmp)
        files: dict[str, Path] = {}
        (tmpd / PERSONAL).write_text(json.dumps(pd.export_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        files[PERSONAL] = tmpd / PERSONAL
        lib_counts: dict[str, int] = {}
        if include_library:
            target = sqlite3.connect(tmpd / LIBRARY)
            with target:
                db.conn.backup(target)          # copie cohérente, même base ouverte (WAL)
            target.execute("PRAGMA journal_mode = DELETE")
            target.close()
            files[LIBRARY] = tmpd / LIBRARY
            q = lambda s: db.conn.execute(s).fetchone()[0]  # noqa: E731
            lib_counts = {"archives": q("SELECT COUNT(*) FROM archives"),
                          "messages": q("SELECT COUNT(*) FROM messages WHERE is_duplicate = 0")}
        if settings_file and Path(settings_file).is_file():
            shutil.copy2(settings_file, tmpd / SETTINGS)
            files[SETTINGS] = tmpd / SETTINGS
        manifest = BackupManifest(
            created_at=datetime.now().isoformat(timespec="seconds"), app_version=app_version,
            schema_version=db.version, contents=sorted(files), sha256={k: _sha(p) for k, p in files.items()},
            personal_counts=pd.counts(), library_counts=lib_counts)
        partial = destination.with_name(destination.name + ".partiel")
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as raw, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFEST, json.dumps({"format": FORMAT, "version": FORMAT_VERSION, **manifest.__dict__},
                                            ensure_ascii=False, indent=1))
            for name, path in files.items():
                z.write(path, name)
        os.replace(partial, destination)
        os.chmod(destination, 0o600)
    return manifest


def read_manifest(path: Path) -> BackupManifest:
    try:
        with zipfile.ZipFile(path) as z:
            data = json.loads(z.read(MANIFEST))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as exc:
        raise BackupError(f"Ce fichier n'est pas une sauvegarde Telegramor valide ({exc}).") from exc
    if data.get("format") != FORMAT:
        raise BackupError("Ce fichier n'est pas une sauvegarde Telegramor.")
    if int(data.get("version", 0)) > FORMAT_VERSION:
        raise BackupError("Cette sauvegarde provient d'une version plus récente de Telegramor.")
    known = {k: data[k] for k in BackupManifest.__dataclass_fields__ if k in data}
    return BackupManifest(**known)


def _extract_checked(z: zipfile.ZipFile, name: str, manifest: BackupManifest, dest: Path) -> Path:
    """Extrait UN membre attendu vers `dest` et vérifie son empreinte."""
    if name not in manifest.contents or name not in z.namelist():
        raise BackupError(f"La sauvegarde ne contient pas {name}.")
    out = dest / name
    with z.open(name) as src, open(out, "wb") as dst:
        shutil.copyfileobj(src, dst)
    expected = manifest.sha256.get(name)
    if expected and _sha(out) != expected:
        raise BackupError(f"{name} est corrompu (empreinte SHA-256 différente).")
    return out


def restore_personal_data(db: Database, path: Path, replace: bool = False) -> dict[str, int]:
    """Restaure (fusionne par défaut) les données personnelles dans la bibliothèque ouverte."""
    manifest = read_manifest(path)
    with tempfile.TemporaryDirectory(prefix="telegramor-") as tmp, zipfile.ZipFile(path) as z:
        f = _extract_checked(z, PERSONAL, manifest, Path(tmp))
        data = json.loads(f.read_text(encoding="utf-8"))
    return PersonalData(db).import_dict(data, replace=replace)


def check_library_file(path: Path) -> dict[str, int]:
    """Vérifie une base SQLite extraite : intégrité et version de schéma."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            res = [r[0] for r in conn.execute("PRAGMA integrity_check")]
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            n = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"La base sauvegardée est illisible ({exc}).") from exc
    if res != ["ok"]:
        raise BackupError("La base sauvegardée est endommagée : " + "; ".join(res[:3]))
    if version > SCHEMA_VERSION:
        raise BackupError("La base sauvegardée provient d'une version plus récente de Telegramor.")
    return {"schema": version, "messages": n}


def restore_library(path: Path, db_path: Path, settings_file: Path | None = None) -> Path:
    """Remplace la bibliothèque (connexion FERMÉE) par celle de la sauvegarde.

    Retourne le chemin où la base précédente a été conservée.
    """
    manifest = read_manifest(path)
    db_path = Path(db_path)
    with tempfile.TemporaryDirectory(prefix="telegramor-", dir=db_path.parent) as tmp, zipfile.ZipFile(path) as z:
        new = _extract_checked(z, LIBRARY, manifest, Path(tmp))
        check_library_file(new)
        settings_new = (_extract_checked(z, SETTINGS, manifest, Path(tmp))
                        if settings_file and SETTINGS in manifest.contents else None)
        kept = db_path.with_name(f"{db_path.stem}.avant-restauration-{datetime.now():%Y%m%d-%H%M%S}{db_path.suffix}")
        if db_path.exists():
            shutil.copy2(db_path, kept)
        for suffix in ("-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        os.replace(new, db_path)
        os.chmod(db_path, 0o600)
        if settings_new is not None:
            shutil.copy2(settings_new, settings_file)
    # La base restaurée s'ouvre et migre normalement (schéma plus ancien accepté)
    Database(db_path).close()
    return kept
