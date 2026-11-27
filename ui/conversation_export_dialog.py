"""Export et impression de messages : conversation (entière ou période),
résultats de recherche, favoris, collection.

Aperçu avant validation : nombre de messages, période, participants, pièces
jointes. Les notes et autres données personnelles ne sont jamais incluses.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate, QStandardPaths, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QVBoxLayout, QWidget,
)

from app import design, icons
from database.models import MessageRow
from services import conversation_export as cx
from services.media_service import human_size, open_with_system, show_in_folder
from ui.components import dialog_header
from ui.formatting import plural

try:  # impression directe facultative (paquet python3-pyside6.qtprintsupport)
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    PRINT_SUPPORT = True
except ImportError:  # pragma: no cover - dépend de l'installation
    PRINT_SUPPORT = False

MODE_EXPORT, MODE_PRINT = "export", "print"


class ConversationExportDialog(QDialog):
    """`loader(day_from, day_to)` renvoie les messages à exporter (période facultative)."""

    def __init__(self, title: str, loader, parent: QWidget | None = None, mode: str = MODE_EXPORT,
                 period: tuple[str | None, str | None] | None = None,
                 conv_names: dict[str, str] | None = None, default_dir: str = "") -> None:
        super().__init__(parent)
        self.mode = mode
        self.title_text = title
        self.loader = loader
        self.conv_names = conv_names or {}
        self.default_dir = default_dir
        self.outcome: cx.ExportOutcome | None = None
        self.setWindowTitle("Imprimer" if mode == MODE_PRINT else "Exporter des messages")

        self.fmt = QComboBox()
        for key, label in cx.FORMATS.items():
            self.fmt.addItem(label, key)
        self.include_media = QCheckBox("Copier les pièces jointes à côté du document")
        self.include_media.setToolTip("Les fichiers sont copiés dans un dossier « …_fichiers » (jamais déplacés, "
                                      "jamais écrasés).")
        self.whole = QCheckBox("Toute la période")
        self.whole.setChecked(True)
        self.date_from = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.date_to = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        if period and period[0] and period[1]:
            self.date_from.setDate(QDate.fromString(period[0][:10], "yyyy-MM-dd"))
            self.date_to.setDate(QDate.fromString(period[1][:10], "yyyy-MM-dd"))
            self.date_from.setDateRange(self.date_from.date(), self.date_to.date())
            self.date_to.setDateRange(self.date_from.date(), self.date_to.date())
        dates = QHBoxLayout()
        dates.addWidget(self.whole)
        dates.addWidget(QLabel("du"))
        dates.addWidget(self.date_from)
        dates.addWidget(QLabel("au"))
        dates.addWidget(self.date_to)
        dates.addStretch(1)
        for w in (self.date_from, self.date_to):
            w.setEnabled(False)
            w.dateChanged.connect(self._refresh)
        self.whole.toggled.connect(lambda on: (self.date_from.setEnabled(not on), self.date_to.setEnabled(not on),
                                               self._refresh()))

        form = QFormLayout()
        if mode == MODE_EXPORT:
            form.addRow("Format", self.fmt)
        if period is not None:
            form.addRow("Période", dates)
        if mode == MODE_EXPORT:
            form.addRow("", self.include_media)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.RichText)
        prev = QFrame(objectName="StatTile")
        pl = QVBoxLayout(prev)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.addWidget(self.preview)

        privacy = QLabel("Seuls les messages issus de l'export Telegram sont repris. Vos notes, favoris et "
                         "collections Telegramor ne sont jamais inclus.")
        privacy.setWordWrap(True)
        privacy.setProperty("muted", True)
        extra = ""
        if mode == MODE_PRINT:
            extra = ("La boîte de dialogue d'impression du système va s'ouvrir." if PRINT_SUPPORT else
                     "Une page prête à imprimer s'ouvre dans votre navigateur (Ctrl+P). Pour imprimer "
                     "directement, installez le paquet python3-pyside6.qtprintsupport.")
        hint = QLabel(extra)
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        hint.setVisible(bool(extra))

        bb = QDialogButtonBox()
        bb.addButton("Annuler", QDialogButtonBox.RejectRole)
        self.ok = bb.addButton("Imprimer…" if mode == MODE_PRINT else "Exporter…", QDialogButtonBox.AcceptRole)
        self.ok.setProperty("variant", "primary")
        icons.bind(self.ok, "printer" if mode == MODE_PRINT else "export", "surface", 16, "surface", "surface")
        bb.accepted.connect(self._run)
        bb.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(12)
        lay.addWidget(dialog_header(self.windowTitle(), title, "printer" if mode == MODE_PRINT else "export"))
        lay.addLayout(form)
        lay.addWidget(prev)
        lay.addWidget(privacy)
        lay.addWidget(hint)
        lay.addWidget(bb)
        self.resize(620, self.sizeHint().height())
        self._messages: list[MessageRow] = []
        self._refresh()

    def _period(self) -> tuple[str | None, str | None]:
        if self.whole.isChecked():
            return None, None
        return self.date_from.date().toString("yyyy-MM-dd"), self.date_to.date().toString("yyyy-MM-dd")

    def _refresh(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._messages = self.loader(*self._period())
        finally:
            QApplication.restoreOverrideCursor()
        msgs = self._messages
        if not msgs:
            self.preview.setText("<b>Aucun message</b> pour cette sélection.")
            self.ok.setEnabled(False)
            return
        self.ok.setEnabled(True)
        days = [m.day for m in msgs if m.day]
        senders = {m.sender for m in msgs if m.sender and m.kind == "default"}
        medias = [md for m in msgs for md in m.media]
        avail = [md for md in medias if md.file_available]
        size = sum(md.abs_file.stat().st_size for md in avail if md.abs_file.is_file())
        muted = design.current().muted
        first = msgs[0].text or msgs[0].service_text or ""
        self.preview.setText(
            f"<b>{plural(len(msgs), 'message')}</b>"
            + (f" · du {days[0]} au {days[-1]}" if days else "")
            + f"<br><span style='color:{muted}'>{plural(len(senders), 'participant')} · "
            f"{plural(len(medias), 'pièce jointe', 'pièces jointes')} ({len(avail)} disponible(s), "
            f"{human_size(size)})</span>"
            + (f"<br><span style='color:{muted}'>Début : « {first[:90]}{'…' if len(first) > 90 else ''} »</span>"
               if first else ""))

    def _run(self) -> None:
        if self.mode == MODE_PRINT:
            self._print()
            return
        fmt = self.fmt.currentData()
        base = self.default_dir or QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        suggested = str(Path(base) / (cx.media_export.safe_name(self.title_text) + cx.EXTENSIONS[fmt]))
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer l'export", suggested,
                                              f"{cx.FORMATS[fmt]} (*{cx.EXTENSIONS[fmt]})")
        if not path:
            return
        path = Path(path)
        if path.suffix.lower() != cx.EXTENSIONS[fmt]:
            path = path.with_suffix(cx.EXTENSIONS[fmt])
        progress = QProgressDialog("Copie des pièces jointes…", "Annuler", 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(500)

        def tick(done: int, total: int, name: str) -> bool:
            progress.setMaximum(max(total, 1))
            progress.setValue(done)
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            self.outcome = cx.export_messages(self._messages, path, fmt, self.title_text,
                                              self.include_media.isChecked(), tick, self.conv_names)
        except OSError as exc:
            progress.close()
            QMessageBox.critical(self, "Export impossible", f"L'export a échoué :\n{exc}")
            return
        progress.close()
        self.accept()
        o = self.outcome
        text = f"{plural(o.messages, 'message')} exporté(s) dans :\n{o.path}"
        if o.media_copied or o.media_missing:
            text += f"\n\n{o.media_copied} pièce(s) jointe(s) copiée(s)"
            if o.media_missing:
                text += f", {o.media_missing} absente(s) de l'export"
        if o.errors:
            text += "\n\nErreurs :\n" + "\n".join(o.errors[:8])
        box = QMessageBox(QMessageBox.Information, "Export terminé", text, parent=self.parentWidget())
        open_btn = box.addButton("Ouvrir", QMessageBox.ActionRole)
        folder_btn = box.addButton("Afficher dans le dossier", QMessageBox.ActionRole)
        box.addButton("Fermer", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            open_with_system(o.path)
        elif box.clickedButton() is folder_btn:
            show_in_folder(o.path)

    def _print(self) -> None:
        if PRINT_SUPPORT:
            from PySide6.QtGui import QTextDocument
            printer = QPrinter(QPrinter.HighResolution)
            printer.setDocName(self.title_text)
            dlg = QPrintDialog(printer, self)
            if dlg.exec() != QDialog.Accepted:
                return
            doc = QTextDocument()
            doc.setHtml(cx.to_html(self._messages, self.title_text, for_qt=True, conv_names=self.conv_names))
            doc.print_(printer)
            self.accept()
            return
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / "impression"
        path = cx.printable_html(self._messages, self.title_text, folder, self.conv_names)
        self.accept()
        if not open_with_system(path):
            QMessageBox.information(self.parentWidget(), "Imprimer",
                                    f"Ouvrez ce fichier dans un navigateur pour l'imprimer :\n{path}")
