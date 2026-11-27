"""« Mon espace » : favoris, notes et collections personnelles, et boîtes de
dialogue associées (note, fil de discussion).

Ces données sont propres à Telegramor (jamais issues de l'export Telegram).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app import design, icons
from services.personal_data import PersonalData, PersonalItem
from services.threads import Thread
from ui.advanced_search import OptionalDate
from ui.components import dialog_header
from ui.formatting import parse_iso, plural

ROLE_ITEM = Qt.UserRole + 1


def _date(iso: str | None) -> str:
    dt = parse_iso(iso)
    return dt.strftime("%d/%m/%Y %H:%M") if dt else ""


class NoteDialog(QDialog):
    def __init__(self, text: str, context: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Note personnelle")
        self.edit = QPlainTextEdit(text)
        self.edit.setPlaceholderText("Ex. « À vérifier », « Important pour le projet »…")
        self.edit.setTabChangesFocus(True)
        ctx = QLabel(context)
        ctx.setWordWrap(True)
        ctx.setProperty("muted", True)
        info = QLabel("Note privée enregistrée localement dans Telegramor. Elle n'est jamais ajoutée à l'export "
                      "Telegram ni aux exports de conversations. Laisser vide pour la supprimer.")
        info.setWordWrap(True)
        info.setProperty("role", "caption")
        bb = QDialogButtonBox()
        bb.addButton("Annuler", QDialogButtonBox.RejectRole)
        ok = bb.addButton("Enregistrer", QDialogButtonBox.AcceptRole)
        ok.setProperty("variant", "primary")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(10)
        lay.addWidget(dialog_header("Note personnelle", "", "note"))
        lay.addWidget(ctx)
        lay.addWidget(self.edit, 1)
        lay.addWidget(info)
        lay.addWidget(bb)
        self.resize(520, 340)

    @property
    def text(self) -> str:
        return self.edit.toPlainText()


class ThreadDialog(QDialog):
    """Fil de discussion reconstitué à partir des citations."""
    go_to = Signal(str, int)            # conversation, seq

    def __init__(self, thread: Thread, conv_name: str, parent=None) -> None:
        super().__init__(parent)
        self.thread = thread
        self.setWindowTitle("Fil de discussion")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Message", "Expéditeur", "Date"])
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(18)
        self.tree.setAlternatingRowColors(True)
        t = design.current()
        if thread.missing_parent is not None:
            miss = QTreeWidgetItem(self.tree, [f"Message n° {thread.missing_parent} absent des archives "
                                               "(relation impossible à reconstituer)", "", ""])
            miss.setForeground(0, design.current().color("danger"))
            miss.setIcon(0, icons.icon("alert", t.danger, 16))
        parents: dict[int, QTreeWidgetItem] = {}
        bold = QFont(self.tree.font())
        bold.setBold(True)
        for n in thread.flat:
            label = ("↳ " if n.depth else "") + (n.text or "(pièce jointe)")
            it = QTreeWidgetItem([label, n.sender or "", _date(n.date_local)])
            it.setData(0, ROLE_ITEM, n.seq)
            it.setToolTip(0, n.text)
            if n.is_focus:
                for c in range(3):
                    it.setFont(c, bold)
                it.setIcon(0, icons.icon("dot", t.accent, 14))
            parent = parents.get(n.depth - 1)
            (parent.addChild(it) if parent is not None and n.depth else self.tree.addTopLevelItem(it))
            parents[n.depth] = it
        self.tree.expandAll()
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setStretchLastSection(False)
        self.tree.itemActivated.connect(self._go)
        self.tree.itemDoubleClicked.connect(self._go)
        info = QLabel(f"{plural(thread.size, 'message')} dans ce fil · seules les citations présentes dans "
                      "l'export sont utilisées." + (" Fil tronqué (trop de réponses)." if thread.truncated else ""))
        info.setWordWrap(True)
        info.setProperty("muted", True)
        go = QPushButton("Aller au message")
        go.setProperty("variant", "primary")
        go.clicked.connect(lambda: self.tree.currentItem() and self._go(self.tree.currentItem()))
        close = QPushButton("Fermer")
        close.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(close)
        btns.addWidget(go)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(10)
        lay.addWidget(dialog_header("Fil de discussion", conv_name, "thread"))
        lay.addWidget(self.tree, 1)
        lay.addWidget(info)
        lay.addLayout(btns)
        self.resize(760, 480)

    def _go(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        seq = item.data(0, ROLE_ITEM)
        if seq is not None:
            self.go_to.emit(self.thread.conversation_id, seq)


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.setWordWrap(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    return t


def _fill(table: QTableWidget, items: list[PersonalItem], columns) -> None:
    table.setSortingEnabled(False)
    table.setRowCount(len(items))
    muted = design.current().color("muted")
    for r, it in enumerate(items):
        for c, fn in enumerate(columns):
            cell = QTableWidgetItem(fn(it) or "")
            cell.setData(ROLE_ITEM, it)
            cell.setToolTip(fn(it) or "")
            if not it.available:
                cell.setForeground(muted)
                cell.setToolTip("Message absent de la bibliothèque actuelle (archive supprimée ?) — conservé")
            table.setItem(r, c, cell)


def _excerpt(it: PersonalItem) -> str:
    if not it.available:
        return "(message absent de la bibliothèque)"
    base = it.excerpt or (it.media_path or it.kind_label)
    return base


class PersonalWindow(QDialog):
    go_to = Signal(str, int)                        # conversation, seq
    export_requested = Signal(str, list)            # titre, [(conversation, message_id)]
    changed = Signal()

    def __init__(self, personal: PersonalData, repo, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mon espace — Telegramor")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.pd = personal
        self.repo = repo
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(False)
        t = design.current()
        self.tabs.addTab(self._favorites_tab(), icons.icon("star", t.muted, 16), "Favoris")
        self.tabs.addTab(self._notes_tab(), icons.icon("note", t.muted, 16), "Notes")
        self.tabs.addTab(self._collections_tab(), icons.icon("collection", t.muted, 16), "Collections")
        export_all = QPushButton("Exporter mes données personnelles…")
        export_all.setProperty("variant", "ghost")
        icons.bind(export_all, "save", "muted", 16)
        export_all.setToolTip("Favoris, notes, collections, marqueurs de lecture et recherches enregistrées (JSON)")
        export_all.clicked.connect(self.export_personal_json)
        foot = QHBoxLayout()
        note = QLabel("Données créées dans Telegramor, stockées localement et séparées des archives Telegram.")
        note.setProperty("role", "caption")
        foot.addWidget(note, 1)
        foot.addWidget(export_all)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 14)
        lay.setSpacing(12)
        lay.addWidget(dialog_header("Mon espace", "Favoris, notes et collections personnelles", "star"))
        lay.addWidget(self.tabs, 1)
        lay.addLayout(foot)
        self.resize(1080, 680)
        self.refresh()

    # ------------------------------------------------------------------ #
    def _favorites_tab(self) -> QWidget:
        w = QWidget()
        self.fav_conv = QComboBox()
        self.fav_sender = QComboBox()
        self.fav_from = OptionalDate("Depuis le")
        self.fav_to = OptionalDate("Jusqu'au")
        self.fav_sort = QComboBox()
        self.fav_sort.addItem("Plus récents d'abord", True)
        self.fav_sort.addItem("Plus anciens d'abord", False)
        for c in (self.fav_conv, self.fav_sender, self.fav_sort):
            c.currentIndexChanged.connect(self.refresh_favorites)
        for d in (self.fav_from, self.fav_to):
            d.changed.connect(self.refresh_favorites)
        filt = QHBoxLayout()
        for widget in (self.fav_conv, self.fav_sender, self.fav_from, self.fav_to, self.fav_sort):
            filt.addWidget(widget)
        filt.addStretch(1)
        self.fav_table = _table(["Date", "Conversation", "Expéditeur", "Message", "Note"])
        self.fav_table.itemDoubleClicked.connect(lambda cell: self._go(cell.data(ROLE_ITEM)))
        self.fav_count = QLabel()
        self.fav_count.setProperty("muted", True)
        go = self._button("Aller au message", "chat", lambda: self._go(self._current(self.fav_table)), primary=True)
        rm = self._button("Retirer des favoris", "trash", self._remove_favorite)
        ex = self._button("Exporter ces messages…", "export", lambda: self._export(
            "Mes messages favoris", self._items(self.fav_table)))
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.addLayout(filt)
        lay.addWidget(self.fav_table, 1)
        lay.addLayout(self._bar(self.fav_count, ex, rm, go))
        return w

    def _notes_tab(self) -> QWidget:
        w = QWidget()
        self.note_search = QLineEdit(placeholderText="Rechercher dans mes notes (accents et casse ignorés)…")
        self.note_search.setClearButtonEnabled(True)
        self.note_search.addAction(icons.icon("search"), QLineEdit.LeadingPosition)
        self.note_search.textChanged.connect(self.refresh_notes)
        self.note_table = _table(["Modifiée le", "Conversation", "Expéditeur", "Message", "Note"])
        self.note_table.itemDoubleClicked.connect(lambda cell: self._go(cell.data(ROLE_ITEM)))
        self.note_count = QLabel()
        self.note_count.setProperty("muted", True)
        go = self._button("Aller au message", "chat", lambda: self._go(self._current(self.note_table)), primary=True)
        edit = self._button("Modifier…", "pencil", self._edit_note)
        rm = self._button("Supprimer la note", "trash", self._delete_note)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.addWidget(self.note_search)
        lay.addWidget(self.note_table, 1)
        lay.addLayout(self._bar(self.note_count, rm, edit, go))
        return w

    def _collections_tab(self) -> QWidget:
        w = QWidget()
        self.coll_list = QListWidget()
        self.coll_list.currentRowChanged.connect(lambda _r: self.refresh_items())
        new = self._button("Nouvelle", "plus", self._new_collection)
        ren = self._button("Renommer…", "pencil", self._rename_collection)
        dele = self._button("Supprimer", "trash", self._delete_collection)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        cap = QLabel("COLLECTIONS")
        cap.setProperty("role", "overline")
        ll.addWidget(cap)
        ll.addWidget(self.coll_list, 1)
        lb = QHBoxLayout()
        for b in (new, ren, dele):
            lb.addWidget(b)
        ll.addLayout(lb)
        self.coll_desc = QLabel()
        self.coll_desc.setWordWrap(True)
        self.coll_desc.setProperty("muted", True)
        self.item_kind = QComboBox()
        for label, key in (("Tous les éléments", None), ("Messages", "message"), ("Photos", "photo"),
                           ("Vidéos", "video"), ("Documents et audio", "file"), ("Liens", "link")):
            self.item_kind.addItem(label, key)
        self.item_kind.currentIndexChanged.connect(self.refresh_items)
        self.item_search = QLineEdit(placeholderText="Rechercher dans la collection…")
        self.item_search.setClearButtonEnabled(True)
        self.item_search.textChanged.connect(self.refresh_items)
        self.item_sort = QComboBox()
        self.item_sort.addItem("Plus récents d'abord", True)
        self.item_sort.addItem("Plus anciens d'abord", False)
        self.item_sort.currentIndexChanged.connect(self.refresh_items)
        f = QHBoxLayout()
        f.addWidget(self.item_kind)
        f.addWidget(self.item_search, 1)
        f.addWidget(self.item_sort)
        self.item_table = _table(["Type", "Date", "Conversation", "Expéditeur", "Contenu"])
        self.item_table.itemDoubleClicked.connect(lambda cell: self._go(cell.data(ROLE_ITEM)))
        self.item_count = QLabel()
        self.item_count.setProperty("muted", True)
        go = self._button("Aller au message", "chat", lambda: self._go(self._current(self.item_table)), primary=True)
        open_f = self._button("Ouvrir le fichier", "external", self._open_item_file)
        rm = self._button("Retirer de la collection", "trash", self._remove_item)
        ex = self._button("Exporter…", "export", lambda: self._export(
            f"Collection « {self.coll_list.currentItem().text()} »" if self.coll_list.currentItem() else "Collection",
            self._items(self.item_table)))
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.coll_desc)
        rl.addLayout(f)
        rl.addWidget(self.item_table, 1)
        rl.addLayout(self._bar(self.item_count, ex, rm, open_f, go))
        split = QSplitter(Qt.Horizontal)
        split.setProperty("variant", "spaced")
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([260, 800])
        split.setChildrenCollapsible(False)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.addWidget(split)
        return w

    # ------------------------------------------------------------------ #
    def _button(self, text: str, icon: str, slot, primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        if primary:
            b.setProperty("variant", "primary")
            icons.bind(b, icon, "surface", 16, "surface", "surface")
        else:
            icons.bind(b, icon, "muted", 16)
        b.clicked.connect(lambda *_: slot())
        return b

    @staticmethod
    def _bar(label: QLabel, *buttons) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(label, 1)
        for b in buttons:
            h.addWidget(b)
        return h

    @staticmethod
    def _current(table: QTableWidget) -> PersonalItem | None:
        cell = table.item(table.currentRow(), 0) if table.currentRow() >= 0 else None
        return cell.data(ROLE_ITEM) if cell else None

    @staticmethod
    def _items(table: QTableWidget) -> list[PersonalItem]:
        return [table.item(r, 0).data(ROLE_ITEM) for r in range(table.rowCount())]

    def _go(self, it: PersonalItem | None) -> None:
        if it is None:
            return
        if not it.available:
            QMessageBox.information(self, "Message absent", "Ce message n'est plus dans la bibliothèque "
                                    "(archive supprimée ?). La donnée personnelle est conservée et redeviendra "
                                    "accessible si l'archive est réimportée.")
            return
        self.go_to.emit(it.conversation_id, it.seq)

    def _export(self, title: str, items: list[PersonalItem]) -> None:
        keys = [(i.conversation_id, i.message_id) for i in items if i.available]
        if not keys:
            QMessageBox.information(self, "Exporter", "Aucun message disponible à exporter.")
            return
        self.export_requested.emit(title, keys)

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        convs = self.repo.list_conversations()
        for combo, first, items in ((self.fav_conv, "Toutes les conversations", [(c.id, c.name) for c in convs]),):
            cur = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(first, None)
            for k, label in items:
                combo.addItem(label, k)
            combo.setCurrentIndex(max(0, combo.findData(cur)))
            combo.blockSignals(False)
        senders = sorted({it.sender for it in self.pd.favorites() if it.sender})
        cur = self.fav_sender.currentData()
        self.fav_sender.blockSignals(True)
        self.fav_sender.clear()
        self.fav_sender.addItem("Tous les expéditeurs", None)
        for s in senders:
            self.fav_sender.addItem(s, s)
        self.fav_sender.setCurrentIndex(max(0, self.fav_sender.findData(cur)))
        self.fav_sender.blockSignals(False)
        self.refresh_favorites()
        self.refresh_notes()
        self.refresh_collections()

    def refresh_favorites(self) -> None:
        items = self.pd.favorites(self.fav_conv.currentData(), self.fav_sender.currentData(), self.fav_from.value(),
                                  self.fav_to.value(), self.fav_sort.currentData())
        _fill(self.fav_table, items, [lambda i: _date(i.date_local), lambda i: i.conversation_name or i.conversation_id,
                                      lambda i: i.sender, _excerpt, lambda i: i.note])
        self.fav_count.setText(plural(len(items), "favori"))

    def refresh_notes(self) -> None:
        items = self.pd.notes(self.note_search.text())
        _fill(self.note_table, items, [lambda i: _date(i.created_at), lambda i: i.conversation_name or i.conversation_id,
                                       lambda i: i.sender, _excerpt, lambda i: i.note])
        self.note_count.setText(plural(len(items), "note"))

    def refresh_collections(self, select: int | None = None) -> None:
        cur = select if select is not None else (self.coll_list.currentItem().data(ROLE_ITEM)
                                                 if self.coll_list.currentItem() else None)
        self.coll_list.blockSignals(True)
        self.coll_list.clear()
        t = design.current()
        for c in self.pd.collections():
            it = QListWidgetItem(icons.icon("collection", t.muted, 16), c.name)
            it.setData(ROLE_ITEM, c.id)
            it.setData(ROLE_ITEM + 1, c.description)
            it.setToolTip(f"{c.name} — {plural(c.count, 'élément')}" + (f"\n{c.description}" if c.description else ""))
            self.coll_list.addItem(it)
            if c.id == cur:
                self.coll_list.setCurrentItem(it)
        if self.coll_list.currentRow() < 0 and self.coll_list.count():
            self.coll_list.setCurrentRow(0)
        self.coll_list.blockSignals(False)
        self.refresh_items()

    def refresh_items(self) -> None:
        cur = self.coll_list.currentItem()
        if cur is None:
            self.item_table.setRowCount(0)
            self.coll_desc.setText("Créez une collection pour regrouper des messages, photos, vidéos, documents "
                                   "ou liens issus de conversations différentes (les fichiers ne sont pas déplacés).")
            self.item_count.setText("")
            return
        self.coll_desc.setText(cur.data(ROLE_ITEM + 1) or "")
        self.coll_desc.setVisible(bool(cur.data(ROLE_ITEM + 1)))
        items = self.pd.collection_items(cur.data(ROLE_ITEM), self.item_search.text(), self.item_kind.currentData(),
                                         self.item_sort.currentData())
        _fill(self.item_table, items, [lambda i: i.kind_label, lambda i: _date(i.date_local),
                                       lambda i: i.conversation_name or i.conversation_id, lambda i: i.sender,
                                       lambda i: (i.media_path + " · " if i.media_path else "") + _excerpt(i)])
        self.item_count.setText(plural(len(items), "élément"))

    # ------------------------------------------------------------------ #
    def _remove_favorite(self) -> None:
        it = self._current(self.fav_table)
        if it:
            self.pd.set_favorite(it.conversation_id, it.message_id, False)
            self.refresh_favorites()
            self.changed.emit()

    def _edit_note(self) -> None:
        it = self._current(self.note_table)
        if not it:
            return
        dlg = NoteDialog(it.note or "", f"{it.conversation_name or ''} · {it.sender or ''} · {_excerpt(it)[:120]}",
                         self)
        if dlg.exec() == QDialog.Accepted:
            self.pd.set_note(it.conversation_id, it.message_id, dlg.text)
            self.refresh_notes()
            self.changed.emit()

    def _delete_note(self) -> None:
        it = self._current(self.note_table)
        if it and QMessageBox.question(self, "Supprimer la note", "Supprimer définitivement cette note ?\n\n"
                                       f"« {it.note[:200]} »") == QMessageBox.Yes:
            self.pd.set_note(it.conversation_id, it.message_id, "")
            self.refresh_notes()
            self.changed.emit()

    def _new_collection(self) -> int | None:
        name, ok = QInputDialog.getText(self, "Nouvelle collection", "Nom de la collection :")
        if not ok or not name.strip():
            return None
        try:
            cid = self.pd.create_collection(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Nouvelle collection", str(exc))
            return None
        self.refresh_collections(select=cid)
        self.changed.emit()
        return cid

    def _rename_collection(self) -> None:
        cur = self.coll_list.currentItem()
        if cur is None:
            return
        name, ok = QInputDialog.getText(self, "Renommer la collection", "Nom :", text=cur.text())
        if not ok:
            return
        desc, ok = QInputDialog.getText(self, "Renommer la collection", "Description (facultative) :",
                                        text=cur.data(ROLE_ITEM + 1) or "")
        try:
            self.pd.update_collection(cur.data(ROLE_ITEM), name, desc if ok else (cur.data(ROLE_ITEM + 1) or ""))
        except ValueError as exc:
            QMessageBox.warning(self, "Renommer la collection", str(exc))
            return
        self.refresh_collections()
        self.changed.emit()

    def _delete_collection(self) -> None:
        cur = self.coll_list.currentItem()
        if cur is None:
            return
        if QMessageBox.question(self, "Supprimer la collection",
                                f"Supprimer la collection « {cur.text()} » ?\n\nLes messages et les fichiers "
                                "d'origine ne sont pas touchés : seule la liste est supprimée.") == QMessageBox.Yes:
            self.pd.delete_collection(cur.data(ROLE_ITEM))
            self.refresh_collections()
            self.changed.emit()

    def _remove_item(self) -> None:
        it = self._current(self.item_table)
        if it and it.item_id is not None:
            self.pd.remove_item(it.item_id)
            self.refresh_collections()
            self.changed.emit()

    def _open_item_file(self) -> None:
        it = self._current(self.item_table)
        if not it or not it.available:
            return
        from services.media_service import open_with_system
        msg = self.repo.message_by_seq(it.conversation_id, it.seq)
        medias = [m for m in (msg.media if msg else []) if it.media_ordinal < 0 or m.ordinal == it.media_ordinal]
        target = next((m for m in medias if m.file_available), None)
        if target is None:
            QMessageBox.information(self, "Ouvrir le fichier", "Aucun fichier disponible pour cet élément.")
            return
        open_with_system(target.abs_file)

    def export_personal_json(self) -> None:
        """Export explicite et distinct des données personnelles (fichier privé, droits 0600)."""
        base = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getSaveFileName(self, "Exporter mes données personnelles",
                                              str(Path(base) / "telegramor-donnees-personnelles.json"), "JSON (*.json)")
        if not path:
            return
        data = json.dumps(self.pd.export_dict(), ensure_ascii=False, indent=1)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        counts = ", ".join(f"{v} {k}" for k, v in self.pd.counts().items() if v) or "aucune donnée"
        QMessageBox.information(self, "Export terminé", f"Données personnelles exportées ({counts}) :\n{path}\n\n"
                                "Ce fichier contient vos notes : conservez-le en lieu sûr.")
