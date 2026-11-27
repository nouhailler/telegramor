"""Boîte de dialogue « Copier vers un dossier » pour des médias sélectionnés."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressDialog, QPushButton, QVBoxLayout, QWidget,
)

from app import design, icons
from app.settings import AppSettings
from database.models import MediaRow
from ui.components import dialog_header
from ui.formatting import plural
from services.media_export import (
    NAMING_DATE, NAMING_ORIGINAL, ExportOptions, ExportResult, execute, plan_copies, summary_text, total_size,
)
from services.media_service import human_size, show_in_folder


KIND_WORDS = {
    "photo": ("photo", "photos"), "video": ("vidéo", "vidéos"), "video_message": ("message vidéo", "messages vidéo"),
    "animation": ("GIF", "GIF"), "sticker": ("autocollant", "autocollants"), "file": ("fichier", "fichiers"),
    "audio": ("fichier audio", "fichiers audio"), "voice": ("message vocal", "messages vocaux"),
}


class ExportDialog(QDialog):
    def __init__(self, medias: list[MediaRow], settings: AppSettings | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Copier vers un dossier")
        self.medias = medias
        self.settings = settings or AppSettings()
        self.result_: ExportResult | None = None

        available = [m for m in medias if m.file_available]
        kinds = Counter(m.media_type for m in available)
        unique = {m.abs_file.resolve() for m in available}
        size = sum(p.stat().st_size for p in unique if p.is_file())
        detail = ", ".join(plural(n, *KIND_WORDS.get(k, ("pièce jointe", "pièces jointes")))
                           for k, n in kinds.most_common())
        text = f"<b>{len(unique)} fichier(s) à copier</b> ({human_size(size)})"
        if detail:
            text += f"<br><span style='color:{design.current().muted}'>{detail}</span>"
        missing = len(medias) - len(available)
        if missing:
            text += f"<br>⚠ {missing} élément(s) ignoré(s) : fichier absent de l'export."
        self.summary = QLabel(text)
        self.summary.setWordWrap(True)

        opts = self.settings.export_options()
        self.dest = QLineEdit(self.settings.last_export_dir or str(Path.home() / "Images"))
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.dest, 1)
        row.addWidget(browse)

        self.naming = QComboBox()
        self.naming.addItem("Nom d'origine (photo_12@16-12-2025_18-33-18.jpg)", NAMING_ORIGINAL)
        self.naming.addItem("Date du message en tête (2025-12-16_18-33-18_photo_12….jpg)", NAMING_DATE)
        self.naming.setCurrentIndex(max(0, self.naming.findData(opts["naming"])))
        self.by_conv = QCheckBox("Un sous-dossier par conversation")
        self.by_conv.setChecked(opts["by_conversation"])
        self.set_mtime = QCheckBox("Dater les fichiers copiés avec la date du message")
        self.set_mtime.setToolTip("Les visionneuses de photos pourront les trier chronologiquement.")
        self.set_mtime.setChecked(opts["set_mtime"])

        form = QFormLayout()
        form.addRow("Dossier de destination", row)
        form.addRow("Noms des fichiers", self.naming)
        form.addRow("", self.by_conv)
        form.addRow("", self.set_mtime)

        note = QLabel("Les fichiers de l'export ne sont pas modifiés. Aucun fichier existant n'est écrasé : "
                      "en cas de nom déjà pris, un suffixe « (2) » est ajouté.")
        note.setWordWrap(True)
        note.setProperty("muted", True)

        buttons = QDialogButtonBox()
        buttons.addButton("Annuler", QDialogButtonBox.RejectRole)
        self.ok = buttons.addButton("Copier", QDialogButtonBox.AcceptRole)
        self.ok.setProperty("variant", "primary")
        icons.bind(self.ok, "copy", "surface", 16, "surface", "surface")
        self.ok.setEnabled(bool(available))
        buttons.accepted.connect(self._run)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(12)
        lay.addWidget(dialog_header("Copier vers un dossier", "", "copy"))
        summary_card = QFrame()
        summary_card.setObjectName("StatTile")
        sl = QVBoxLayout(summary_card)
        sl.setContentsMargins(14, 10, 14, 10)
        sl.addWidget(self.summary)
        lay.addWidget(summary_card)
        lay.addLayout(form)
        lay.addWidget(note)
        lay.addWidget(buttons)
        self.resize(660, self.sizeHint().height())

    def options(self) -> ExportOptions:
        return ExportOptions(self.naming.currentData(), self.by_conv.isChecked(), self.set_mtime.isChecked())

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Dossier de destination", self.dest.text() or str(Path.home()))
        if d:
            self.dest.setText(d)

    def _run(self) -> None:
        dest = Path(self.dest.text().strip()).expanduser()
        if not self.dest.text().strip():
            QMessageBox.warning(self, "Copier vers un dossier", "Choisissez un dossier de destination.")
            return
        if dest.exists() and not dest.is_dir():
            QMessageBox.warning(self, "Copier vers un dossier", f"« {dest} » n'est pas un dossier.")
            return
        opts = self.options()
        plans, result = plan_copies(self.medias, dest, opts)
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "Copier vers un dossier", f"Impossible de créer le dossier :\n{e}")
            return
        self.settings.last_export_dir = str(dest)
        self.settings.save_export_options(opts.naming, opts.by_conversation, opts.set_mtime)

        progress = QProgressDialog("Copie en cours…", "Annuler", 0, max(1, len(plans)), self)
        progress.setWindowTitle("Copie des médias")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(400)
        size = human_size(total_size(plans))

        def tick(done: int, total: int, name: str) -> bool:
            progress.setValue(done)
            if name:
                progress.setLabelText(f"{done + 1} / {total} ({size} au total)\n{name}")
            QApplication.processEvents()
            return not progress.wasCanceled()

        self.result_ = execute(plans, result, opts, tick)
        progress.close()
        self.accept()
        self._show_result(self.result_)

    def _show_result(self, r: ExportResult) -> None:
        box = QMessageBox(QMessageBox.Warning if r.errors else QMessageBox.Information,
                          "Copie terminée" if not r.cancelled else "Copie interrompue", summary_text(r),
                          parent=self.parentWidget())
        open_btn = box.addButton("Ouvrir le dossier", QMessageBox.ActionRole) if r.copied else None
        box.addButton("Fermer", QMessageBox.RejectRole)
        box.exec()
        if open_btn is not None and box.clickedButton() is open_btn:
            show_in_folder(r.destination)


def copy_to_folder(medias: list[MediaRow], parent: QWidget, settings: AppSettings | None = None) -> None:
    """Point d'entrée commun : galerie, panneau d'informations…"""
    if not medias:
        return
    ExportDialog(medias, settings, parent).exec()
