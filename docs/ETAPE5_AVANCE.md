# Étape 5 : améliorations et fonctions avancées

## Galerie multimédia (`ui/gallery_window.py`, Ctrl+M)

- **Six onglets** : Photos, Vidéos, GIF et autocollants, Fichiers, Audio et
  vocaux, Liens. La galerie couvre toute la bibliothèque (doublons exclus)
  ou une seule conversation.
- **Filtres** : conversation, expéditeur, année ; tri du plus récent au plus
  ancien ou l'inverse. Le mois de la première miniature visible est affiché.
- **Grille paginée** par blocs de 200 ; les miniatures sont décodées en
  arrière-plan, à la taille réglable (64 à 256 px), recadrées sans flou.
- **Fichiers et liens** : tableau triable (nom, type, taille, conversation,
  expéditeur, date, état).
- **Actions** : double-clic pour ouvrir (visionneuse, lecteur vidéo,
  application du système) ; clic droit pour *aller au message*, *afficher
  dans le dossier*, *copier le chemin*. Un fichier manquant est signalé
  (« ⚠ absent »).

## Statistiques (`services/statistics_service.py`, `ui/statistics_window.py`)

- **Portée** : toute la bibliothèque ou une conversation, éventuellement
  limitée à un expéditeur.
- **Tuiles** : messages, jours actifs, messages par jour actif, jour le plus
  actif, plus longue série de jours consécutifs, plus long silence.
- **Graphiques** dessinés avec QPainter (pas de dépendance Qt Charts) :
  messages par mois (mois vides compris ; un clic ouvre le mois dans la
  conversation), par heure, par jour de la semaine, carte jour × heure à une
  seule teinte, expéditeurs et médias en barres horizontales avec
  pourcentages, mots les plus fréquents (mots courants exclus, accents
  regroupés).
- Info-bulle au survol de chaque barre et de chaque case.

## Chronologie avancée (`ui/timeline.py`)

- **Onglet « Dates »** du panneau d'informations : arbre années → mois →
  jours, avec une barre d'activité relative à chaque niveau. Un clic amène
  au jour ; le jour lu est suivi automatiquement (Ctrl+T pour afficher
  l'onglet).
- **Jour précédent / suivant** ayant des messages (Ctrl+PgPréc / PgSuiv) et
  **mois précédent / suivant** (avec Maj). Cela complète le calendrier
  (Ctrl+G), le menu « Mois ▾ » et les boutons début / fin des étapes
  précédentes.

## Optimisations

| Mesure (100 000 messages, 100 fichiers) | Avant | Après |
|---|---|---|
| Analyse HTML | 71 s | 21 s : fichiers analysés en parallèle (8 processus « spawn », sûrs depuis Qt), puis raccordés |
| Enregistrement | 24 s | 11 s : insertions groupées, index plein texte rempli en une requête, cache SQLite de 64 Mo |

- **Raccordement des fichiers** (`_stitch`) : il reproduit exactement une
  lecture séquentielle (numérotation, expéditeur des messages regroupés en
  tête de fichier, contrôle date/séparateur aux jonctions). Un test compare
  les deux modes champ par champ.
- **Repli automatique** en séquentiel si les processus ne peuvent pas
  démarrer.
- **Trigger d'indexation** suspendu pendant l'import, dans la même
  transaction : en cas d'erreur, il est restauré (testé).

## Recherche sémantique : point d'extension (`database/semantic.py`)

Aucun modèle n'est intégré : l'application reste locale et légère. Le
protocole `SemanticProvider` (`is_ready`, `search`, `index_archive`) se
branche sur `SearchEngine.semantic`. En mode `MODE_SEMANTIC`, le fournisseur
propose des messages candidats classés ; le moteur applique ensuite les
filtres, l'exclusion des doublons, le tri et la pagination habituels. Un
fournisseur factice démontre le branchement dans les tests. La même
architecture convient à la recherche par similarité de sens, à la recherche
dans les métadonnées des médias ou à la catégorisation automatique.

## Finitions

- Icône d'application (`app/resources/icon.svg`), utilisée aussi par le
  raccourci du menu (`./install.sh --raccourci`).
- Aide des raccourcis clavier (F1).
- Boutons Galerie, Statistiques et Bibliothèque dans la barre du haut.

## Limites

1. **Mots fréquents** : ils sont calculés sur les 300 000 messages les plus
   récents de la portée, pour rester rapides.
2. **Heures des statistiques** : elles sont celles de l'export, dans le fuseau
   de l'ordinateur au moment de l'export.
3. **Fichiers et liens de la galerie** : le tableau est limité aux 5 000
   premiers ; affiner avec les filtres au-delà.
4. **Lecture audio** : les fichiers audio et vocaux s'ouvrent dans
   l'application du système.
