#!/usr/bin/env bash
# Installation de Telegram Archive Explorer sur Debian 13.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Vérification des paquets système"
MISSING=()
for pkg in python3 python3-venv python3-pip; do
    dpkg -s "$pkg" >/dev/null 2>&1 || MISSING+=("$pkg")
done
if [ ${#MISSING[@]} -gt 0 ]; then
    echo "Paquets manquants : ${MISSING[*]}"
    echo "Installez-les avec : sudo apt install ${MISSING[*]}"
    exit 1
fi

echo "==> Création de l'environnement virtuel (.venv)"
# --system-site-packages : permet d'utiliser PySide6 fourni par Debian
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt

if ! .venv/bin/python -c "import PySide6.QtWidgets" 2>/dev/null; then
    echo "ATTENTION : PySide6 absent, l'interface graphique ne pourra pas démarrer."
    echo "       sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtsvg"
fi
if ! .venv/bin/python -c "import PySide6.QtMultimediaWidgets" 2>/dev/null; then
    echo "Note : Qt Multimedia absent → les vidéos s'ouvriront dans le lecteur du système."
    echo "       Pour la lecture intégrée :"
    echo "       sudo apt install python3-pyside6.qtmultimedia python3-pyside6.qtmultimediawidgets"
fi

echo "==> Exécution des tests"
.venv/bin/python -m pytest -q tests
if [ "${1:-}" = "--raccourci" ]; then
    APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$APPS"
    cat > "$APPS/telegram-archive-explorer.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Telegram Archive Explorer
Comment=Bibliothèque personnelle de conversations Telegram
Exec=$(pwd)/run.sh
Icon=$(pwd)/app/resources/icon.svg
Terminal=false
Categories=Utility;Archiving;
DESKTOP
    echo "==> Raccourci ajouté au menu des applications."
fi
echo "==> Installation terminée. Lancement : ./run.sh"
