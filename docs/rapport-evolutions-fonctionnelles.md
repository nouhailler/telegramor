# Rapport des évolutions fonctionnelles (version 1.3)

Mission : faire de Telegramor un gestionnaire et explorateur d'archives
Telegram plus complet, fiable et respectueux de la vie privée, sans
dupliquer l'existant. Point de départ : version 1.2 (commit `e00cda2`).
Audit préalable : [audit-fonctionnel-initial.md](audit-fonctionnel-initial.md).

## 1. Synthèse de l'audit initial

La v1.2 était solide sur son cœur :

- import parallèle, bibliothèque multi-archives avec doublons de messages ;
- recherche FTS5 multicritère ;
- galerie, statistiques, chronologie et copie de médias.

En revanche, il lui manquait :

- toute donnée personnelle de l'utilisateur ;
- l'export de conversations ;
- la sauvegarde ;
- le diagnostic global ;
- l'intégration continue.

`database/semantic.py` n'était qu'un point d'extension (protocole sans
implémentation).

## 2. État avant intervention

| Domaine | État v1.2 |
|---|---|
| Recherche multicritère | Existante et complète (texte, expression, exclusion, filtres, tri, pagination, surlignage) ; ni historique ni recherches enregistrées |
| Données personnelles | Aucune (seule la dernière position de défilement, dans le fichier INI) |
| Doublons | Messages entre archives et empreintes des HTML ; rien pour les médias |
| Fils | Citation cliquable vers le parent seulement |
| Exports | Copie de fichiers médias seulement |
| Statistiques | Riches, mais sans période, comparaison, n-grammes ni export |
| Fiabilité | Vérification par archive ; pas de diagnostic global, de sauvegarde, de CI ni de contrôle des dépendances |

## 3. Fonctionnalités conservées sans changement

Sont inchangés :

- l'import et l'analyse HTML (`importer/`) ;
- la fusion multi-archives et la détection de renommage ;
- l'index FTS5 et la syntaxe de recherche ;
- la galerie et la copie de médias (v1.1) ;
- la chronologie, la visionneuse et le lecteur vidéo ;
- le design system v1.2 ;
- tous les menus et raccourcis existants.

Les nouvelles entrées sont seulement ajoutées.

## 4. Fonctionnalités complétées

- **Recherche** :
  - filtre *Réponse à un message* (`SearchQuery.is_reply`) ;
  - historique des 30 dernières recherches, enregistré à l'ouverture d'un
    résultat ;
  - recherches enregistrées (nommées) ;
  - export des résultats.

  Le tout réutilise `SearchQuery` et le moteur existant, sans second moteur.
- **Doublons** : empreintes SHA-256 des fichiers médias
  (`services/media_dedup.py`), avec :
  - un cache par chemin, taille et date ;
  - un calcul en arrière-plan, interruptible ;
  - les groupes de fichiers identiques avec leur provenance ;
  - les occurrences d'un fichier depuis la galerie ;
  - l'option galerie *Masquer les fichiers identiques*.

  Le mécanisme `is_duplicate` des messages n'est pas dupliqué : les copies
  d'un même message ne comptent pas comme doublons de médias.
- **Fils de discussion** (`services/threads.py`) : remontée jusqu'au premier
  message connu, puis réponses récursives. Le maillon manquant est signalé
  (« absent des archives »), jamais deviné.
- **Marqueurs de lecture** : ils complètent `last_seq`, qui garde la position
  d'affichage :
  - le message le plus avancé consulté est stocké en base ;
  - un repère est affiché à la visite suivante ;
  - *Reprendre la lecture* (Ctrl+R), *Marquer comme lu jusqu'ici*,
    *Réinitialiser*.
- **Diagnostic** (`services/diagnostics.py`) : global, il réutilise
  `verify_archive`. Il contrôle :
  - l'intégrité SQLite et les clés étrangères ;
  - les deux index FTS5 ;
  - les messages orphelins, les dates manquantes et les conversations vides ;
  - les réponses non résolues ;
  - les archives absentes et les HTML modifiés ou manquants ;
  - les médias manquants et les chemins invalides ;
  - les fichiers orphelins et les doublons ;
  - les données personnelles orphelines.

  Chaque constat a un niveau de gravité et une recommandation ; le rapport
  s'exporte en Markdown. La seule correction proposée (reconstruire l'index)
  est explicite.
- **Statistiques** :
  - filtre de période et mots exclus (mémorisés) ;
  - expressions de deux et trois mots, retenues si vues au moins deux fois ;
  - clic sur un mot ou une expression pour lancer la recherche globale ;
  - export CSV de toutes les séries, avec unités, et export PNG du tableau de
    bord ;
  - comparaison de deux portées (conversation, année, période) : volumes
    ramenés à la durée, répartitions horaires en %, export CSV.
- **Dépendances** :
  - avant de démarrer l'interface, un message clair dans le terminal (avec la
    commande `apt`) remplace la trace Python ;
  - fenêtre *Aide › Composants installés* (obligatoires et facultatifs,
    conséquences, commande pour Debian, Ubuntu, Fedora ou pip, bouton
    *Copier*) ;
  - signalement discret des composants facultatifs absents, une fois par
    version.

## 5. Fonctionnalités nouvelles

- **Favoris personnels**, distincts des épingles Telegram (qui restent des
  événements de service) : étoile dans la bulle, filtres conversation,
  expéditeur et période, tri, export.
- **Notes privées** :
  - encadré « Ma note » distinct sous le message ;
  - index FTS5 dédié, sans accents ni casse ;
  - modification et suppression ;
  - recherche transversale dans *Mon espace*.
- **Collections** :
  - pour les messages et les médias (rang du média), y compris depuis la
    galerie ;
  - un élément peut appartenir à plusieurs collections ;
  - renommage, description, suppression sans toucher aux sources ;
  - filtres par type, recherche, tri, ouverture du fichier.
- **Mon espace** (Ctrl+B et barre latérale) : une seule fenêtre à trois
  onglets, plus l'export explicite des données personnelles en JSON (droits
  0600).
- **Export de messages** (`services/conversation_export.py`) :
  - formats : HTML autonome imprimable (CSS A4, pas de coupure de message,
    numéros de page), PDF via Qt (sans nouvelle dépendance), Markdown, JSON ;
  - portées : conversation, période, résultats de recherche, favoris,
    collection ;
  - pièces jointes copiées en option (logique de `media_export`, jamais
    d'écrasement) ;
  - aperçu avant validation.
- **Impression** (Ctrl+P) : boîte de dialogue système si QtPrintSupport est
  présent, sinon page HTML prête à imprimer.
- **Sauvegarde et restauration** (`services/backup.py`) :
  - ZIP 0600 contenant le manifeste et les empreintes, les données
    personnelles, la base (API `backup` de SQLite, cohérente base ouverte) et
    les paramètres ;
  - restauration par fusion, remplacement ou base complète, avec contrôle
    d'intégrité, ancienne base conservée et redémarrage.
- **Vérification des mises à jour** (`services/update_check.py`) :
  - désactivée par défaut ;
  - à la demande, ou hebdomadaire si activée ;
  - un GET HTTPS sans données personnelles ;
  - lien vers la page officielle uniquement, jamais de téléchargement.
- **Intégration continue** (`.github/workflows/ci.yml`) :
  - conteneur Debian 13 ;
  - flake8 (règles pyflakes) ;
  - compilation de tous les modules ;
  - pytest complet, avec rapport JUnit ;
  - construction et vérification du `.deb` (fichiers attendus, absence de
    tests et de captures, version, dépendances) ;
  - installation réelle et contrôle des dépendances ;
  - artefacts conservés.

## 6. Fonctionnalités volontairement non développées

| Fonctionnalité | Raison | Statut |
|---|---|---|
| Recherche sémantique | Priorité P3. Exige un modèle d'embeddings local : `sentence-transformers` et numpy ne sont pas installés, et le seul moteur présent (Ollama) n'a que des modèles de dialogue. L'intégrer sans pouvoir le valider aurait livré une fonction factice. Le point d'extension `SemanticProvider` est conservé ; la table `message_embeddings` est à ajouter par migration le moment venu. | Reporté |
| IA locale (Ollama) | Priorité P3. Dépend de la recherche sémantique pour citer des sources vérifiables ; à engager après elle. | Reporté |
| Transcription audio et vidéo | Priorité P3. whisper.cpp n'est pas installé ; même raisonnement. | Reporté |
| AppImage, Flatpak | Priorité P3. Les outils (`appimagetool`, `flatpak-builder`) sont absents de l'environnement, donc aucune construction n'est vérifiable. Un manifeste non testé contredirait l'exigence « documenté et reproductible ». Le `.deb` reste la cible prioritaire. | Reporté |
| Catégories de favoris | Les collections remplissent ce rôle sans second mécanisme de regroupement. | Non applicable |
| Semaine dans la chronologie, filtres de la chronologie | La chronologie (années, mois, jours) et la carte jour × heure couvrent l'essentiel ; la période et la comparaison sont ajoutées aux statistiques. | Reporté |
| Filtre « collection » dans la galerie | Les collections s'affichent avec leurs médias dans *Mon espace*, et la galerie y ajoute des éléments. | Reporté |

## 7. Modifications de l'architecture

L'architecture en couches est respectée :

- l'interface (`ui/`) appelle des services (`services/`) testables sans Qt
  (sauf l'export PDF) ;
- les services utilisent `LibraryRepository` et `SearchEngine`.

Nouveaux modules :

- `services/` : `personal_data`, `threads`, `conversation_export`,
  `media_dedup`, `diagnostics`, `backup`, `dependencies`, `update_check` ;
- `ui/` : `personal_window` (Mon espace, note, fil),
  `conversation_export_dialog`, `tools_dialogs` (diagnostic, fichiers
  identiques, sauvegarde, composants, mises à jour).

Les traitements longs (diagnostic, empreintes) tournent dans un `QThread`
avec leur propre connexion SQLite.

Les favoris, notes et collections de chaque page de messages sont chargés en
trois requêtes groupées (`_hydrate`), sans requête par bulle.

## 8. Modifications de la base SQLite

La migration **v3** ajoute uniquement des tables ; aucune table existante
n'est modifiée.

- `user_favorites`, `user_notes` (avec l'index FTS5 `user_notes_fts` et ses
  triggers), `user_collections`, `user_collection_items`,
  `user_read_markers`, `user_saved_searches`, `user_search_history` :
  - elles portent les données personnelles ;
  - elles utilisent la clé stable (conversation, identifiant Telegram), sans
    clé étrangère vers `messages` ;
  - elles survivent donc à la réindexation et à la suppression puis
    réimportation d'une archive (testé).
- `media_hashes` (en cascade avec `medias`) et `file_hash_cache` (par chemin,
  taille et date) servent aux empreintes.

## 9. Migrations réalisées

| Test | Résultat |
|---|---|
| Base v2 synthétique → v3 (`test_migration_v2_to_v3_preserves_data`) | Données et index FTS conservés |
| Copie de la bibliothèque réelle de l'utilisateur (3 archives, 11 273 messages, 849 médias), v2 → v3 | Migration en 4 ms ; comptes de toutes les tables identiques ; `integrity_check` = ok ; diagnostic sans anomalie |

Pour la bibliothèque réelle :

- la copie a été faite par l'API de sauvegarde SQLite, en lecture seule ;
- l'original n'a pas été modifié (empreinte identique avant et après) ;
- la copie a été supprimée après le test.

Stratégie : la migration est append-only et transactionnelle. Avant toute
évolution future, *Fichier › Sauvegarde* permet une copie cohérente.

## 10. Dépendances

- **Aucune nouvelle dépendance obligatoire.**
- Paquet Debian : `python3-pyside6.qtprintsupport` est ajouté aux
  *Recommends* (impression directe, facultative).
- Le PDF utilise `QPdfWriter` de QtGui, déjà requis.
- La vérification des mises à jour utilise `urllib` de la bibliothèque
  standard.
- Les noms de paquets Debian 13 ont été vérifiés avec `apt-cache`.

## 11. Sécurité et confidentialité

- **Séparation stricte des données.** Les données importées ne sont jamais
  modifiées par les fonctions personnelles. Les exports de conversations
  n'incluent jamais de notes (testé avec un marqueur secret). L'export des
  données personnelles est une action distincte.
- **Exports HTML.** Tout le contenu est échappé, aucun script n'est produit
  (testé avec `<script>`), et seuls les liens `http(s)` sont rendus
  cliquables.
- **Sauvegardes.** Les fichiers sont créés en 0600 et écrits sous un nom
  temporaire avant renommage. La restauration :
  - ne lit que les membres attendus (aucune extraction de chemin arbitraire ;
    testé avec `../../evil.txt`) ;
  - vérifie les SHA-256 (testé sur une archive altérée) et l'intégrité
    SQLite ;
  - refuse une version de schéma plus récente.
- **Chemins.** Le diagnostic signale les chemins de médias invalides (absolu,
  URL, sortie de l'archive), qui ne sont jamais ouverts.
- **SQL.** Les valeurs sont toujours paramétrées. Les seuls fragments
  construits sont des listes de marqueurs « ? » et des identifiants entiers.
- **Réseau.** Une seule requête facultative (mises à jour), désactivée par
  défaut et documentée :
  - User-Agent générique ;
  - aucun cookie ni identifiant ;
  - lien accepté seulement s'il pointe vers `github.com` ;
  - échec silencieux hors ligne lors de la vérification automatique.
- **Aucune télémétrie, aucun journal** contenant des messages.

## 12. Résultats des tests

| Suite | Résultat |
|---|---|
| Suite complète (`pytest`, environnement `.venv`, Debian 13) | **161 réussis, 1 ignoré** en 7 min 50 s (le test ignoré exige un export réel absent du poste, sans rapport avec ces évolutions) |
| Nouveaux tests (`test_personal.py`, `test_services_v13.py`, `test_ui_v13.py`, compléments de `test_statistics.py`) | 33 tests, tous réussis |
| Analyse statique `flake8 --select=F` | Aucune erreur (11 avertissements préexistants corrigés : imports et variables inutilisés) |

Les tests utilisent exclusivement des données synthétiques
(`build_synthetic_exports` dans `tests/conftest.py`).

## 13. Build Debian

`./packaging/build_deb.sh` produit `dist/telegram-archive-explorer_1.3.0_all.deb`
(≈ 154 Ko, 55 modules Python). Contrôles effectués :

- métadonnées : Version 1.3.0, *Depends* et *Recommends* attendus ;
- contenu : aucun test, environnement virtuel, cache ni capture ;
- lancement : l'arborescence extraite du paquet démarre avec le Python
  système, et le contrôle des dépendances obligatoires ne trouve rien de
  manquant ;
- données utilisateur : le paquet n'écrit rien dans `~/.local/share` ni dans
  `~/.config`, donc une mise à jour ou une désinstallation les conserve.

## 14. CI

Le workflow `.github/workflows/ci.yml` a été écrit et ses étapes ont été
exécutées localement à l'identique : flake8, compilation, pytest,
construction et inspection du paquet.

**Son exécution sur GitHub Actions n'a pas encore eu lieu**, car rien n'est
publié tant que l'utilisateur ne l'a pas demandé. Elle devra être vérifiée
au premier push.

L'installation par `apt-get install ./…deb` n'est faite qu'en CI (conteneur
root). L'interface y est testée hors écran : son rendu visuel n'est pas
vérifié.

## 15. Validations fonctionnelles

Scénarios exécutés automatiquement, hors écran, sur données fictives : tests
d'interface et script de captures.

| Scénario | Validé par |
|---|---|
| Importer des archives de démonstration | `synthetic_lib`, script de captures (5 exports fictifs) |
| Parcourir les conversations | `test_ui.py`, `test_ui_v13.py` |
| Recherche multicritère (dont réponses, historique, recherche enregistrée) | `test_search_reply_filter_history_and_saved` |
| Ajouter un favori, une note, une collection | `test_favorite_note_collection_from_bubble`, `test_personal_window_lists_and_navigates` |
| Retrouver un média présent dans plusieurs exports | `test_media_dedup_groups_and_gallery`, `test_tools_dialogs` |
| Reconstituer un fil (dont parent absent) | `test_thread_reconstruction`, `test_thread_dialog_and_read_marker` |
| Reprendre à la dernière position consultée | `test_read_marker_only_moves_forward`, `test_thread_dialog_and_read_marker` |
| Exporter (4 formats) et imprimer | `test_conversation_exports_all_formats`, `test_export_and_print_dialogs` |
| Produire des statistiques, comparer deux périodes | `test_statistics_period_words_export_and_compare`, `test_compare_two_periods_normalizes_by_duration` |
| Lancer un diagnostic | `test_diagnostics_report`, `test_diagnostics_detects_broken_fts_and_missing_archive` |
| Sauvegarder et restaurer | `test_backup_and_restore`, `test_backup_rejects_bad_or_tampered_files` |
| Modules facultatifs absents | Impression sans QtPrintSupport (simulée), mise à jour hors ligne, composants manquants (commandes) |
| Recherche sémantique | Non applicable (non développée) |

**Non-régression** :

- les 129 tests préexistants passent, dont l'import, l'affichage, les médias,
  la recherche, les statistiques et la copie ;
- les exports d'origine sont vérifiés inchangés après diagnostic et calcul
  des empreintes (instantanés taille et date) ;
- une bibliothèque v2 réelle est migrée sans perte.

**Limite** : l'impression réelle sur papier et la boîte d'impression du
système n'ont pas été testées (QtPrintSupport n'est pas installé sur le poste
de test). Le rendu sur l'écran de l'utilisateur reste à vérifier.

## 16. Limitations restantes

- Pas de recherche sémantique, d'IA locale ni de transcription : voir § 6.
- Le PDF (moteur de texte de Qt) a une mise en page plus simple que le HTML
  imprimable : pas de coupure intelligente entre les pages ni de numéros de
  page. Pour un rendu soigné, utiliser la page HTML et *Imprimer en PDF* du
  navigateur.
- L'historique de recherche n'est enregistré qu'à l'ouverture d'un résultat.
- La vérification des mises à jour révèle, comme toute requête web, l'adresse
  IP à GitHub.
- La détection des fichiers orphelins s'arrête à 200 000 fichiers parcourus.
- L'export des résultats de recherche est limité aux 5 000 premiers.

## 17. Recommandations pour la prochaine version

1. Vérifier le premier passage de la CI sur GitHub, puis exiger son succès
   avant toute fusion.
2. Recherche sémantique facultative :
   - fournisseur `SemanticProvider` reposant sur des embeddings locaux (modèle
     d'embeddings Ollama, ou `sentence-transformers` en option) ;
   - table versionnée `message_embeddings` (modèle, dimension, vecteur) ;
   - indexation incrémentale en arrière-plan ;
   - recherche hybride avec FTS5 ;
   - affichage de la taille et de l'emplacement du modèle.
3. Assistant IA local (Ollama), uniquement par-dessus la recherche
   sémantique, avec citations obligatoires des messages sources.
4. Transcription whisper.cpp facultative : file d'attente annulable,
   transcriptions indexées dans une table dédiée.
5. Flatpak (permissions limitées aux dossiers choisis via le portail de
   fichiers) puis AppImage, validés sur une installation propre.

## Tableau récapitulatif

| Fonctionnalité | État initial | Action réalisée | Tests | Statut final |
|---|---|---|---|---|
| Recherche multicritère | Existante | Filtre réponses, historique, recherches enregistrées, export des résultats | `test_personal`, `test_ui_v13` | Validé |
| Recherche sémantique | Partielle (point d'extension) | Aucune (point d'extension conservé) | `test_semantic_extension_point` (existant) | Reporté |
| Favoris | Absents | Créés (distincts des épingles Telegram) | `test_personal`, `test_ui_v13` | Validé |
| Annotations | Absentes | Créées, avec recherche FTS | `test_personal`, `test_ui_v13` | Validé |
| Collections | Absentes | Créées (messages et médias) | `test_personal`, `test_ui_v13` | Validé |
| Détection des doublons | Partielle (messages, HTML) | SHA-256 des médias, groupes, galerie | `test_services_v13`, `test_ui_v13` | Validé |
| Transcription | Absente | — | — | Reporté |
| Marqueurs de lecture | Partiels (position INI) | Repère, reprise, marquage, réinitialisation | `test_personal`, `test_ui_v13` | Validé |
| Fils de discussion | Partiels | Vue du fil, parent absent signalé | `test_personal`, `test_ui_v13` | Validé |
| Exports et impression | Partiels (copie de médias) | HTML, PDF, Markdown, JSON, impression | `test_services_v13`, `test_ui_v13` | Partiellement validé (impression papier non testée) |
| Statistiques avancées | Existantes | Période, n-grammes, mots exclus, clic, CSV et PNG | `test_statistics`, `test_ui_v13` | Validé |
| Comparaisons statistiques | Absentes | Deux portées, normalisation par la durée | `test_statistics`, `test_ui_v13` | Validé |
| IA locale | Absente | — | — | Reporté |
| Diagnostic | Partiel (par archive) | Diagnostic global, rapport exportable | `test_services_v13`, `test_ui_v13` | Validé |
| Sauvegarde et restauration | Absentes | ZIP vérifié, 3 modes de restauration | `test_services_v13`, `test_ui_v13` | Validé |
| Vérification des dépendances | Partielle | Terminal et fenêtre de composants | `test_services_v13`, `test_ui_v13` | Validé |
| Mises à jour | Absente | Facultative, désactivée par défaut | `test_services_v13` (réseau simulé) | Partiellement validé (pas d'appel réel à GitHub en test) |
| Packaging alternatif | Absent | Étude seulement | — | Reporté |
| CI GitHub Actions | Absente | Workflow Debian 13 (tests, lint, `.deb`) | Étapes exécutées localement | Partiellement validé (premier passage GitHub à confirmer) |
