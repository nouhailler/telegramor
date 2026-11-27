# Audit fonctionnel initial de Telegramor (version 1.2)

Audit réalisé le 27 novembre 2026, avant toute évolution fonctionnelle, sur
le commit `e00cda2` (branche `main`).

## 1. Synthèse

Telegramor (Telegram Archive Explorer) est une application de bureau Python 3
et PySide6 (Qt 6). Elle importe les exports **HTML** de Telegram Desktop dans
une bibliothèque SQLite locale, avec un index plein texte FTS5. L'application
est solide sur son cœur de métier :

- import robuste et parallélisé ;
- fusion de plusieurs archives avec dédoublonnage des messages ;
- recherche multicritère rapide ;
- galerie, statistiques et chronologie ;
- copie de médias ;
- design system récent (v1.2).

Elle ne contient en revanche **aucune donnée personnelle propre à
l'utilisateur** : pas de favoris, de notes, de collections ni de marqueurs de
lecture en base. Elle n'a pas non plus d'export de conversations, de
sauvegarde, de diagnostic global ni d'intégration continue. Ces manques
définissent les priorités.

Volumétrie du code : environ 12 000 lignes Python, 9 fichiers de tests.

**Tests :**

- 117 fonctions de test, soit 129 cas avec les paramétrages.
- Résultat : 128 réussis et 1 ignoré, en 4 min 33 s dans `.venv`. Le test
  ignoré exige un export réel situé hors du dépôt.

## 2. Analyse technique

| Domaine | Constat |
|---|---|
| Architecture | Couches nettes : `importer/` (analyse HTML, sans Qt), `database/` (SQLite, dépôts, moteur de recherche), `services/` (statistiques, médias, copie, navigation), `ui/` (PySide6), `app/` (fenêtre principale, paramètres, design system). L'interface ne manipule jamais SQLite directement : elle passe par `LibraryRepository` et `SearchEngine`. |
| Dépendances | Obligatoires : `python3-pyside6.qtcore/qtgui/qtwidgets/qtsvg`, `python3-bs4`, `python3-lxml`. Facultatives : `python3-pyside6.qtmultimedia` et `qtmultimediawidgets` (lecteur vidéo intégré, détection déjà présente via `MULTIMEDIA_AVAILABLE`). Aucune dépendance réseau. |
| Base SQLite | Schéma versionné par `PRAGMA user_version`, migrations append-only dans `database/db_manager.py`. v1 : archives, conversations, participants, messages, médias, réactions, références, liens, FTS5 avec triggers. v2 : doublons inter-archives, `archive_files` (SHA-256 des HTML), alias de conversations. WAL activé, clés étrangères actives. |
| Import | Détection d'archives, analyse en 8 processus, raccordement (`_stitch`), assainissement du HTML, rapport d'import. Les exports originaux ne sont jamais modifiés (ouverture en lecture seule). |
| Recherche | FTS5 (`unicode61 remove_diacritics 2`) : mots, préfixes, « expression exacte », `-exclusion`. Filtres : conversation, archive, expéditeur, période, type de contenu, médias, liens, nom de fichier. Tri, pagination (`fetchMore`), surlignage insensible aux accents, compteur de résultats. |
| `database/semantic.py` | **Point d'extension seulement** : protocole `SemanticProvider` sans implémentation. Le moteur sait déjà consommer un fournisseur (`MODE_SEMANTIC`) ; un fournisseur factice est testé. |
| Relations | `reply_to_message_id` et `message_references` sont stockés. La citation est affichée dans la bulle et cliquable vers le message d'origine. Une cible absente est signalée (« absent de la bibliothèque »). |
| Médias | Chemins relatifs au fichier HTML, résolus à la lecture. Statut d'existence mis à jour (`refresh_media_status`). Miniatures décodées en arrière-plan. Visionneuse photo et lecteur vidéo facultatif. |
| Galerie | 6 onglets, filtres conversation / expéditeur / année, tri, pagination par 200, menu « aller au message », copie multiple (v1.1). |
| Statistiques | Tuiles, graphiques par mois, heure et jour, carte jour × heure, expéditeurs, médias, mots fréquents. Portée : bibliothèque, conversation ou expéditeur. Pas de filtre de période, de comparaison ni d'export. |
| Exports | Uniquement la **copie de fichiers médias** (`services/media_export.py`). Aucun export de conversation. |
| Paramètres | `QSettings` (fichier INI) : thème, zoom, panneau, tri, lecteur vidéo, nom de l'utilisateur, dernière conversation, **dernière position par conversation** (`last_seq`), dossiers récents, options de copie. |
| Erreurs et journaux | Messages d'erreur dans l'interface ; rapport d'import détaillé. Pas de module `logging` : aucun journal sur disque, donc aucun risque de fuite de contenu par les logs. |
| Tests | Parseur, import, base, bibliothèque, recherche, médias, copie, statistiques, interface hors écran (`QT_QPA_PLATFORM=offscreen`). Les données de test sont synthétiques (générateurs `tests/conftest.py`), sauf une fixture d'export réel ignorée par git. |
| Paquet Debian | `packaging/build_deb.sh` (dpkg-deb) : `/usr/lib/telegram-archive-explorer`, lanceur, `.desktop`, icône, dépendances déclarées. Les données utilisateur (`~/.local/share/…`, `~/.config/…`) ne sont jamais touchées par le paquet. |
| CI | **Aucune** (pas de dossier `.github/`). |

## 3. Inventaire fonctionnel

| Fonctionnalité | État constaté | Décision |
|---|---|---|
| Recherche multicritère | **Existante** (texte, expression, exclusion, conversation, archive, expéditeur, dates, type, médias, liens, fichier, pagination, surlignage, compteur, multi-archives) | **Compléter** : historique, recherches enregistrées, filtre « réponses » |
| Recherche sémantique | **Partielle** : protocole et branchement moteur, sans fournisseur | Reporter en P3 (voir § 6) ; conserver le point d'extension |
| Favoris et épingles | **Absents**. Les épingles Telegram sont des messages de service (« a épinglé… »), conservés tels quels. | **Créer** les favoris Telegramor, distincts des épingles Telegram |
| Annotations personnelles | **Absentes** | **Créer** (avec recherche) |
| Collections et albums | **Absents** | **Créer** |
| Détection des doublons | **Partielle** : doublons de *messages* entre archives (non destructif, `is_duplicate`) et empreintes SHA-256 des *fichiers HTML*. Rien pour les fichiers médias. | **Compléter** : SHA-256 des médias, regroupement, occurrences |
| Transcription audio/vidéo | **Absente** | Reporter en P3 |
| Navigation et marqueurs de lecture | **Partielle** : restauration de la dernière position par conversation (QSettings). Pas de marqueur « lu jusqu'ici » ni de reprise explicite. | **Compléter** en base SQLite |
| Fils de discussion | **Partiels** : citation cliquable vers le parent, sans vue des réponses ni du fil | **Compléter** : vue du fil (parents et réponses) |
| Exports et impression | **Partiels** : copie de médias uniquement | **Créer** l'export de conversations (HTML, Markdown, JSON, PDF) et l'impression |
| Statistiques avancées | **Existantes** (riches) | **Compléter** : période, n-grammes, clic sur un mot, export CSV et PNG |
| Comparaisons statistiques | **Absentes** | **Créer** (deux conversations ou deux périodes) |
| IA locale | **Absente** | Reporter en P3 |
| Diagnostic des archives | **Partiel** : vérification d'intégrité *par archive* (fichiers HTML modifiés ou manquants, médias absents) | **Compléter** : diagnostic global de la bibliothèque, avec rapport exportable |
| Sauvegarde et restauration | **Absentes** | **Créer** (API de sauvegarde SQLite, données personnelles, paramètres) |
| Vérification des dépendances | **Partielle** : Qt Multimedia détecté (menu grisé avec info-bulle) ; erreur brute si PySide6 manque | **Compléter** : écran de diagnostic avec commandes `apt` |
| Vérification des mises à jour | **Absente** | **Créer** (facultative, désactivée par défaut) |
| Packaging alternatif | **Absent** | Étude, reportée (voir § 6) |
| CI GitHub Actions | **Absente** | **Créer** (tests et construction du `.deb`) |

## 4. Anomalies identifiées

1. **Aucune intégration continue.** Une régression ne peut être détectée
   qu'à la main.
2. Si PySide6 manque, l'application s'arrête sur une trace Python
   incompréhensible.
3. La « dernière position » est stockée dans le fichier INI, indexée par
   identifiant de conversation. Elle n'est ni sauvegardable avec la base ni
   distinguée d'une notion de lecture.
4. Le test `test_real_export_media` dépend d'un dossier de l'utilisateur. Il
   est correctement ignoré, mais il est invisible en CI.
5. La durée de la suite de tests est longue (environ 4,5 min). Les tests de
   performance sur 100 000 messages sont acceptables mais à surveiller en CI.
6. Pas d'anomalie bloquante dans l'import, la recherche ou l'affichage.

## 5. Doublons techniques ou fonctionnels à éviter

- **Doublons.** Le dédoublonnage des médias doit compléter `is_duplicate`
  (messages) et `archive_files` (HTML), sans créer de troisième mécanisme
  pour les messages.
- **Intégrité.** Le diagnostic global doit réutiliser `verify_archive` et
  `IntegrityReport`, non les réécrire.
- **Copie de médias.** L'export de conversations est un service distinct
  (contenu des messages), mais l'option « inclure les médias » doit réutiliser
  la logique de nommage et de copie de `services/media_export.py`.
- **Recherche.** Recherches enregistrées et historique s'appuient sur
  `SearchQuery` (sérialisation), sans second moteur.
- **Navigation.** La reprise de lecture complète `NavigationHistory` et
  `last_seq` sans les remplacer : position d'affichage d'un côté, lecture la
  plus avancée de l'autre.

## 6. Priorités retenues

| Priorité | Contenu |
|---|---|
| P0 | CI GitHub Actions (tests et `.deb`), diagnostic des dépendances, migration v3 non destructive des données personnelles |
| P1 | Favoris, notes (recherchables), collections, diagnostic global, dédoublonnage SHA-256 des médias, sauvegarde et restauration, export de conversations et impression |
| P2 | Fils de discussion, marqueurs de lecture, compléments de recherche (historique, recherches enregistrées, filtre réponses), statistiques (période, n-grammes, comparaison, exports CSV et PNG) |
| P3 | Recherche sémantique, IA locale, transcription, AppImage et Flatpak : à n'engager qu'après consolidation, sinon reportés et documentés |
| P4 | Vérification des mises à jour, README, captures fictives |

## 7. Risques de régression

- **Migration v3.** Elle doit uniquement *ajouter* des tables, sans toucher
  aux tables importées. Elle doit être testée sur une base v2 existante.
- **Survie des données personnelles.** Elles doivent survivre à la
  réindexation ou à la suppression d'une archive. Elles ne doivent donc pas
  dépendre de `messages.id` (régénéré) mais d'une clé stable :
  (conversation, identifiant Telegram du message).
- **Performance.** L'affichage des bulles ne doit pas faire une requête par
  message pour les favoris et les notes : un chargement groupé par page est
  nécessaire.
- **Galerie.** Le masquage des doublons de médias ne doit pas cacher un
  média dont la seule autre occurrence est hors du filtre courant.
- **Interface.** Les menus et raccourcis existants doivent rester inchangés
  (comparaison automatique).

## 8. Recommandations d'architecture

1. **Séparer les données.** Les données personnelles vont dans des tables
   dédiées, préfixées `user_`. Elles sont liées par `(conversation_id,
   message_id)`, sans clé étrangère en cascade vers `messages`.
2. **Un service par fonction**, testable sans Qt : `services/personal_data.py`,
   `diagnostics.py`, `media_dedup.py`, `backup.py`, `conversation_export.py`,
   `dependencies.py`, `update_check.py`.
3. **Une seule fenêtre « Mon espace »** pour les favoris, les notes et les
   collections, plutôt que trois écrans.
4. **Des traitements longs en arrière-plan** (empreintes, diagnostic), avec
   annulation.
5. **Aucune sortie réseau** hors de la vérification des mises à jour,
   facultative et désactivée par défaut.
