#!/usr/bin/env bash
# Construit dist/telegram-archive-explorer_<version>_all.deb (Debian 13).
# Usage : ./packaging/build_deb.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PKG=telegram-archive-explorer
VERSION=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' app/main_window.py)
[[ "$VERSION" == *.*.* ]] || VERSION="$VERSION.0"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
LIB="$STAGE/usr/lib/$PKG"

mkdir -p "$LIB" "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps" "$STAGE/usr/share/doc/$PKG" "$STAGE/DEBIAN"

# Code de l'application (sans tests, environnement virtuel ni caches)
cp -r app database importer services ui main.py "$LIB/"
find "$LIB" -name '__pycache__' -prune -exec rm -rf {} +
cp README.md "$STAGE/usr/share/doc/$PKG/"
cp -r docs "$STAGE/usr/share/doc/$PKG/"
cp app/resources/icon.svg "$STAGE/usr/share/icons/hicolor/scalable/apps/$PKG.svg"

cat > "$STAGE/usr/bin/$PKG" <<LAUNCH
#!/bin/sh
export PYTHONDONTWRITEBYTECODE=1
exec /usr/bin/python3 /usr/lib/$PKG/main.py "\$@"
LAUNCH

cat > "$STAGE/usr/share/applications/$PKG.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Telegram Archive Explorer
GenericName=Explorateur d'archives Telegram
Comment=Parcourir et rechercher dans des exports HTML de Telegram, hors ligne
Exec=$PKG
Icon=$PKG
Terminal=false
Categories=Office;Utility;
Keywords=telegram;archive;export;recherche;
DESKTOP

SIZE=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3 (>= 3.11), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets, python3-bs4, python3-lxml
Recommends: python3-pyside6.qtmultimedia, python3-pyside6.qtmultimediawidgets, qt6-svg-plugins
Maintainer: nouhailler <nouhailler@users.noreply.github.com>
Homepage: https://github.com/nouhailler/telegramor
Description: explorateur local d'exports HTML de Telegram
 Telegram Archive Explorer importe les exports HTML de Telegram Desktop dans
 une bibliothèque locale SQLite (recherche plein texte FTS5) et les affiche
 dans une interface proche de Telegram : conversations, recherche globale,
 galerie de médias, statistiques et chronologie.
 .
 Fonctionnement 100 % local : aucune connexion réseau, le JavaScript des
 exports n'est jamais exécuté et les fichiers originaux ne sont pas modifiés.
CONTROL

chmod 755 "$STAGE/usr/bin/$PKG"
find "$STAGE/usr" -type d -exec chmod 755 {} +
find "$STAGE/usr" -type f ! -path "*/usr/bin/*" -exec chmod 644 {} +

mkdir -p dist
OUT="dist/${PKG}_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT"
echo "Paquet : $OUT"
