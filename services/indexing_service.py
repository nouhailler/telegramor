"""Importation en arrière-plan (thread dédié, connexion SQLite propre au thread)."""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal

from database.db_manager import Database
from database.repositories import LibraryRepository
from importer.import_manager import import_path


class ImportWorker(QObject):
    progress = Signal(int, int, str)        # fait, total, libellé
    finished = Signal(list)                 # [(source, texte du rapport, nb erreurs)]
    failed = Signal(str)

    def __init__(self, sources: list[str], db_path: Path) -> None:
        super().__init__()
        self.sources = sources
        self.db_path = db_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        reports = []
        try:
            with Database(self.db_path) as db:
                repo = LibraryRepository(db)
                for i, src in enumerate(self.sources):
                    if self._cancel:
                        break
                    prefix = f"[{i + 1}/{len(self.sources)}] " if len(self.sources) > 1 else ""

                    def cb(done: int, total: int, label: str, prefix=prefix) -> None:
                        self.progress.emit(done, max(total, 1) + 1, prefix + label)

                    result = import_path(src, progress=cb)
                    self.progress.emit(1, 1, prefix + "Enregistrement dans la bibliothèque…")
                    summary = repo.save_import(result, src)
                    errors = sum(a.severity == "erreur" for a in result.report.anomalies)
                    reports.append((src, result.report.to_text() + "\n" + summary.to_text(), errors))
        except Exception as exc:  # noqa: BLE001 - remonté à l'interface
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")
            return
        self.finished.emit(reports)


def start_import(sources: list[str], db_path: Path, parent: QObject) -> tuple[QThread, ImportWorker]:
    thread = QThread(parent)
    worker = ImportWorker(sources, db_path)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    # quit() est sûr entre threads : appel direct pour que le thread s'arrête
    # dès la fin du travail, sans attendre la boucle d'événements principale.
    worker.finished.connect(thread.quit, Qt.DirectConnection)
    worker.failed.connect(thread.quit, Qt.DirectConnection)
    thread.finished.connect(worker.deleteLater)
    thread.start()
    return thread, worker
