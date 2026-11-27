#!/usr/bin/env python3
"""Telegram Archive Explorer – point d'entrée.

    python main.py                      lance l'interface graphique
    python main.py importer CHEMIN [--json rapport.json] [--messages messages.json]
                                        [--enregistrer]  (ajoute l'archive à la bibliothèque)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from importer.import_manager import import_path


def cmd_import(args: argparse.Namespace) -> int:
    def progress(done: int, total: int, label: str) -> None:
        if args.verbose:
            print(f"  [{done}/{total}] {label}", file=sys.stderr)

    result = import_path(args.path, progress=progress)
    print(result.report.to_text())
    if args.json:
        Path(args.json).write_text(json.dumps(result.report.to_dict(), ensure_ascii=False, indent=2,
                                              default=str), encoding="utf-8")
        print(f"Rapport JSON écrit dans {args.json}")
    if args.messages:
        data = [{"conversation_id": c.conversation_id, "name": c.name, "source_files": c.source_files,
                 "messages": [m.to_dict() for m in c.messages]} for c in result.conversations]
        Path(args.messages).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Messages extraits écrits dans {args.messages}")
    if args.save:
        from database.db_manager import Database
        from database.repositories import LibraryRepository
        with Database(args.db) as db:
            summary = LibraryRepository(db).save_import(result, args.path)
            print(summary.to_text())
            print(f"Archive enregistrée dans la bibliothèque {db.path}")
    errors = [a for a in result.report.anomalies if a.severity == "erreur"]
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="telegram-archive-explorer",
                                description="Bibliothèque personnelle de conversations Telegram")
    p.add_argument("--db", help="fichier de bibliothèque SQLite (défaut : ~/.local/share/…)")
    sub = p.add_subparsers(dest="command")
    imp = sub.add_parser("importer", help="analyser un export HTML et afficher le rapport")
    imp.add_argument("path", help="répertoire d'export ou fichier messages.html")
    imp.add_argument("--json", help="écrire le rapport au format JSON")
    imp.add_argument("--messages", help="écrire les messages extraits au format JSON")
    imp.add_argument("--enregistrer", dest="save", action="store_true",
                     help="enregistrer l'archive dans la bibliothèque")
    imp.add_argument("-v", "--verbose", action="store_true")
    imp.set_defaults(func=cmd_import)
    args = p.parse_args(argv)
    if args.command is None:
        from services.dependencies import missing, terminal_report
        absent = missing(required_only=True)
        if absent:                      # message clair plutôt qu'une trace Python
            print(terminal_report(absent), file=sys.stderr)
            return 2
        from app.main_window import run_gui
        return run_gui(sys.argv, Path(args.db) if args.db else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
