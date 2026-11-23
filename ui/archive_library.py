"""Fenêtre « Bibliothèque des archives » : liste, état, intégrité, déplacement, réindexation."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QListWidget, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from database.models import ArchiveRow
from database.repositories import LibraryRepository
from importer.import_report import ImportReport
from services.media_service import show_in_folder

from .formatting import parse_iso, period, plural, short_date

COLUMNS = ["Nom", "État", "Conversations", "Messages", "En commun", "Médias", "Période", "Importée le",
           "Emplacement"]


class ArchiveLibraryDialog(QDialog):
    import_requested = Signal()
    reindex_requested = Signal(str)          # chemin source
    library_changed = Signal()
    show_report = Signal(str, str)           # titre, texte

    def __init__(self, repo: LibraryRepository, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bibliothèque des archives")
        self.repo = repo
        self.archives: list[ArchiveRow] = []

        self.summary = QLabel()
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setTextElideMode(Qt.ElideMiddle)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        h.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.doubleClicked.connect(lambda *_: self.verify())

        self.details_title = QLabel("<b>Conversations de l'archive</b>")
        self.details = QListWidget()

        def btn(text: str, slot, tip: str = "") -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        self.b_import = btn("Importer…", self.import_requested.emit, "Ajouter une nouvelle archive (Ctrl+O)")
        self.b_reindex = btn("Réindexer", self.reindex,
                             "Relire l'export depuis son emplacement et remplacer son contenu (sans doublons)")
        self.b_verify = btn("Vérifier l'intégrité", self.verify,
                            "Contrôler la présence et l'empreinte des fichiers HTML et la présence des médias")
        self.b_locate = btn("Localiser…", self.locate, "Indiquer le nouvel emplacement d'une archive déplacée")
        self.b_rename = btn("Renommer…", self.rename, "Changer le nom affiché de l'archive")
        self.b_report = btn("Rapport d'import", self.report, "Afficher le rapport de la dernière importation")
        self.b_folder = btn("Ouvrir le dossier", self.open_folder)
        self.b_delete = btn("Retirer…", self.delete,
                            "Retirer l'archive de la bibliothèque (les fichiers ne sont pas supprimés)")
        self.b_fts = btn("Reconstruire l'index de recherche", self.rebuild_index,
                         "Reconstruit entièrement l'index plein texte de toute la bibliothèque")
        close = btn("Fermer", self.accept)

        actions = QHBoxLayout()
        for b in (self.b_import, self.b_reindex, self.b_verify, self.b_locate, self.b_rename, self.b_report,
                  self.b_folder, self.b_delete):
            actions.addWidget(b)
        actions.addStretch(1)
        bottom = QHBoxLayout()
        bottom.addWidget(self.b_fts)
        bottom.addStretch(1)
        note = QLabel("Les fichiers d'export ne sont jamais modifiés ni supprimés par l'application.")
        note.setProperty("muted", True)
        bottom.addWidget(note)
        bottom.addWidget(close)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        det = QWidget()
        dl = QVBoxLayout(det)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(self.details_title)
        dl.addWidget(self.details)
        split.addWidget(det)
        split.setSizes([320, 180])

        lay = QVBoxLayout(self)
        lay.addWidget(self.summary)
        lay.addWidget(split, 1)
        lay.addLayout(actions)
        lay.addLayout(bottom)
        self.resize(1150, 620)
        self.refresh()

    # ------------------------------------------------------------------ #

    def refresh(self, select_id: int | None = None) -> None:
        current = select_id if select_id is not None else (self.selected().id if self.selected() else None)
        self.archives = self.repo.list_archives()
        stats = self.repo.library_stats()
        missing = sum(not a.root_exists for a in self.archives)
        self.summary.setText(
            f"<b>{plural(stats['archives'], 'archive')}</b> · {plural(stats['conversations'], 'conversation')} · "
            f"{plural(stats['messages'], 'message')} · {plural(stats['medias'], 'média')} · "
            f"{plural(stats['duplicates'], 'doublon')} écarté(s)"
            + (f" · <span style='color:#d32f2f'>⚠ {missing} introuvable(s)</span>" if missing else ""))
        self.table.setRowCount(len(self.archives))
        for row, a in enumerate(self.archives):
            imported = parse_iso(a.imported_at)
            values = [a.name, a.status, a.conversations, a.messages_count, a.duplicates, a.media_count,
                      period(a.first_date, a.last_date), imported.strftime("%d/%m/%Y %H:%M") if imported else "",
                      a.source_path]
            for col, v in enumerate(values):
                it = QTableWidgetItem(str(v))
                if isinstance(v, int):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it.setData(Qt.UserRole, a.id)
                if not a.root_exists:
                    it.setForeground(QColor("#d32f2f"))
                    it.setToolTip("Emplacement introuvable : utilisez « Localiser… »")
                self.table.setItem(row, col, it)
        if current is not None:
            for row, a in enumerate(self.archives):
                if a.id == current:
                    self.table.selectRow(row)
        elif self.archives:
            self.table.selectRow(0)
        self._on_select()

    def selected(self) -> ArchiveRow | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        aid = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        return next((a for a in self.archives if a.id == aid), None)

    def _on_select(self) -> None:
        a = self.selected()
        for b in (self.b_reindex, self.b_verify, self.b_locate, self.b_rename, self.b_report, self.b_folder,
                  self.b_delete):
            b.setEnabled(a is not None)
        if a is not None:
            self.b_reindex.setEnabled(a.root_exists)
            self.b_folder.setEnabled(a.root_exists)
        self.details.clear()
        if a is None:
            return
        self.details_title.setText(f"<b>Conversations de « {a.name} »</b>")
        for c in self.repo.list_conversations(a.id):
            self.details.addItem(f"{c.name}   —   {plural(c.message_count, 'message')}, "
                                 f"{short_date(c.first_date)} → {short_date(c.last_date)}"
                                 + (f"   (aussi dans : {', '.join(x for x in c.archives if x != a.name)})"
                                    if len(c.archives) > 1 else ""))

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def reindex(self) -> None:
        a = self.selected()
        if a and a.root_exists:
            self.reindex_requested.emit(a.source_path)

    def verify(self) -> None:
        a = self.selected()
        if not a:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rep = self.repo.verify_archive(a.id)
        finally:
            QApplication.restoreOverrideCursor()
        self.show_report.emit(f"Intégrité de « {a.name} »", rep.to_text())
        self.refresh(a.id)
        self.library_changed.emit()

    def locate(self) -> None:
        a = self.selected()
        if not a:
            return
        start = str(Path(a.root_path).parent) if Path(a.root_path).parent.exists() else str(Path.home())
        new = QFileDialog.getExistingDirectory(self, f"Nouvel emplacement de « {a.name} »", start)
        if new:
            self.relocate_to(a, new)

    def relocate_to(self, a: ArchiveRow, new: str, confirm=None) -> bool:
        """Vérifie puis applique un nouvel emplacement. `confirm` (tests) remplace la boîte de dialogue."""
        missing, changed = self.repo.check_relocation(a.id, new)
        force = False
        if missing or changed:
            text = (f"Ce dossier ne correspond pas exactement à l'archive :\n"
                    f"{len(missing)} fichier(s) HTML manquant(s), {len(changed)} différent(s).\n\n"
                    + "\n".join(f"· {p}" for p in (missing + changed)[:8]))
            if missing and len(missing) == self.repo.conn.execute(
                    "SELECT COUNT(*) FROM archive_files WHERE archive_id = ?", (a.id,)).fetchone()[0]:
                QMessageBox.warning(self, "Emplacement incorrect", text + "\n\nAucun fichier de l'archive "
                                    "n'a été trouvé dans ce dossier.")
                return False
            ask = confirm or (lambda: QMessageBox.question(
                self, "Emplacement différent", text + "\n\nUtiliser quand même ce dossier ?") == QMessageBox.Yes)
            if not ask():
                return False
            force = True
        self.repo.relocate_archive(a.id, new, force=force)
        self.refresh(a.id)
        self.library_changed.emit()
        return True

    def rename(self) -> None:
        a = self.selected()
        if not a:
            return
        name, ok = QInputDialog.getText(self, "Renommer l'archive", "Nom affiché :", text=a.name)
        if ok and name.strip():
            self.repo.rename_archive(a.id, name)
            self.refresh(a.id)
            self.library_changed.emit()

    def report(self) -> None:
        a = self.selected()
        if not a:
            return
        raw = self.repo.conn.execute("SELECT report_json FROM archives WHERE id = ?", (a.id,)).fetchone()[0]
        text = ImportReport.from_dict(json.loads(raw)).to_text() if raw else "Aucun rapport enregistré."
        self.show_report.emit(f"Rapport d'import de « {a.name} »", text)

    def open_folder(self) -> None:
        a = self.selected()
        if a and a.root_exists:
            show_in_folder(Path(a.root_path))

    def delete(self, confirm=None) -> None:
        a = self.selected()
        if not a:
            return
        ask = confirm or (lambda: QMessageBox.question(
            self, "Retirer l'archive",
            f"Retirer « {a.name} » de la bibliothèque ?\n\n"
            f"Ses {a.messages_count} messages ne seront plus consultables ni recherchables, sauf ceux "
            "également présents dans une autre archive.\nLes fichiers d'export sur le disque ne sont pas "
            "supprimés ; vous pourrez réimporter l'archive plus tard.") == QMessageBox.Yes)
        if ask():
            self.repo.delete_archive(a.id)
            self.refresh()
            self.library_changed.emit()

    def rebuild_index(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.repo.rebuild_search_index()
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Index de recherche", "L'index de recherche a été reconstruit.")

    def copy_path(self) -> None:
        a = self.selected()
        if a:
            QGuiApplication.clipboard().setText(a.source_path)
