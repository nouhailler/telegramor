# Rapport de refonte graphique — Telegramor

Refonte exclusivement visuelle et ergonomique de Telegram Archive Explorer.
Aucune fonctionnalité n'a été ajoutée ni retirée. L'importateur, le parseur HTML,
le schéma SQLite, les requêtes, le moteur de recherche, les statistiques et la
gestion des médias sont inchangés : `git diff` sur `importer/`, `database/` et
`services/` est vide.

Toutes les captures de ce document proviennent d'une bibliothèque de démonstration
entièrement fictive (conversations, prénoms et photos générés). Elles ne contiennent
aucune donnée issue d'une archive réelle. Dans les captures de la bibliothèque des
archives, la colonne « Emplacement » est masquée pour ne pas montrer de chemin local.

---

## 1. Audit initial

**Composants vieillissants**

- **Fenêtre principale**
  - Barre d'outils native.
  - Boutons texte précédés d'emojis (🖼, 📊, 🗄).
  - Pas de navigation identifiable.
  - La recherche globale n'était qu'un champ parmi d'autres.
- **En-tête de conversation** : symboles Unicode (←, 🔍, 📅, ⤒, ⤓, ⓘ) à la place de pictogrammes, rendu irrégulier selon les polices.
- **Contrôles Qt « Fusion » non stylés**
  - Barres de défilement avec flèches.
  - Listes déroulantes, cases à cocher, en-têtes de tableaux, menus et infobulles natifs.
- **Bibliothèque des archives** : tableau à grille et alternance de couleurs, rangée de neuf boutons identiques sans hiérarchie, état « OK / Introuvable » en simple texte.
- **Statistiques** : tuiles bleues génériques, graphiques posés sans carte ni hiérarchie.

**Incohérences**

- Couleurs codées en dur dans une dizaine de fichiers : `#3390ec`, `#d32f2f`, `#ff8a80`, `#3b4a59`, `#111`, `gray`…
- Plusieurs `setStyleSheet` locaux.
- Couleur d'accent différente entre la chronologie (bleu fixe) et le reste.
- Les vignettes de la galerie et du panneau latéral étaient dessinées par deux codes distincts.

**Lisibilité et espacements**

- Marges serrées : bulles à 10 px, lignes collées.
- Séparateurs de jours peu visibles (pastille grise sans repère).
- Nom de l'expéditeur et heure peu hiérarchisés.
- Liste des participants écrasée.
- Libellés tronqués sans points de suspension.

**Thème sombre** : simple jeu de couleurs proche de Telegram, sans cohérence avec le thème clair (bulles « vertes » côté utilisateur en clair, bleues en sombre).

**Problème découvert pendant la refonte**

- L'ancienne feuille de style ne référençait aucun fichier.
- La nouvelle utilise des pictogrammes PNG pour les flèches et les coches.
- Leur chemin de cache contenait le nom de l'application, avec des espaces, ce qui rendait la feuille de style illisible pour Qt (« Could not parse application stylesheet »).
- Corrigé : dossier `~/.cache/telegramor/icons` et chemins entre guillemets.
- Une vérification règle par règle confirme désormais **0 erreur** sur les 208 règles.

## 2. Direction artistique

Telegramor est pensé comme **une bibliothèque conversationnelle** : un outil calme
pour de longues sessions de lecture.

- **Fond** : surfaces gris bleuté très clair, panneaux blancs bordés d'un filet discret.
- **Couleur** : utilisée avec parcimonie, le bleu principal pour l'action et la sélection, le violet et le turquoise en accents ponctuels.
- **Hiérarchie** : portée par la typographie (titres demi-gras, légendes en gris ardoise, surtitres en petites capitales) plutôt que par des aplats.
- **Formes** : coins arrondis réguliers (6, 8, 12, 16 px), pictogrammes au trait, aucune ombre lourde ni dégradé appuyé.
- **Inspirations** : la clarté de Linear et Notion, l'organisation des gestionnaires de réseaux sociaux (Buffer, Later, Metricool). Aucun élément n'en est copié.

## 3. Palette finale

| Rôle | Clair | Sombre |
|---|---|---|
| Fond principal | `#F5F7FB` | `#0E1420` |
| Surfaces et panneaux | `#FFFFFF` | `#151D2B` |
| Fond discret / survol | `#F0F3F8` / `#F2F5FA` | `#1A2333` / `#1E2839` |
| Zone de lecture | `#F3F6FA` | `#0F1622` |
| Bleu principal | `#3986D8` | `#5B9DE6` |
| Bleu secondaire | `#5B9DE6` | `#79B0EE` |
| Violet d'accent | `#8170D8` | `#9C8FF0` |
| Turquoise | `#36B9B0` | `#4CC9BF` |
| Texte principal | `#202B3C` | `#E4EAF3` |
| Texte secondaire | `#738096` | `#93A1B6` |
| Bordures | `#E7ECF3` | `#232E40` |
| Positif (vert doux) | `#2E9C6A` sur `#E5F5EC` | `#4CC38A` sur `#15302A` |
| Avertissement (orange doux) | `#C9801F` sur `#FDF2E2` | `#E7A64E` sur `#352914` |
| Erreur (rouge modéré) | `#C9463F` sur `#FBEBEA` | `#EF706B` sur `#3A1E22` |
| Bulle reçue / envoyée | `#FFFFFF` / `#E6F0FC` | `#182131` / `#1D3553` |
| Surlignage de recherche | `#FFE69C` | `#5E4F18` |

En thème sombre, les boutons principaux utilisent un bleu plus profond (`#3A78C4`)
pour garder un texte blanc lisible.

## 4. Système de design

| Fichier | Rôle |
|---|---|
| `app/design.py` (nouveau) | Jetons : classe `Theme` (45 rôles de couleur), thèmes `LIGHT` et `DARK`, espacements (4 à 32 px), rayons (6 à 16 px), dimensions (barre latérale, barre du haut, largeurs minimales des panneaux), pile typographique, couleurs d'avatar accordées à la palette. Fonctions `current()`, `sender_color()`, `name_color()` (noms éclaircis en sombre). |
| `app/icons.py` (nouveau) | 56 pictogrammes SVG dessinés pour l'application (trait 1,8 px, grille 24 × 24), colorés à la volée avec les jetons. Variantes d'état (survol, coché, désactivé). `bind()` recolore automatiquement les boutons au changement de thème. `qss_icon()` fournit les flèches et coches de la feuille de style. |
| `app/styles.py` (réécrit) | **Feuille de style unique** générée depuis les jetons, pour tous les contrôles Qt et les composants propres à l'application. Les variantes passent par des propriétés : `variant="primary" / "ghost" / "danger" / "secondary" / "segmented"`, `card="true"`, `role="title" / "section" / "caption" / "overline"`. |
| `ui/components.py` (nouveau) | Composants réutilisables : `dialog_header()` (en-tête commun des fenêtres secondaires), `ElidedLabel` (libellé terminé par « … », texte complet en infobulle), `card()`, `separator()`. |

**Typographie**

- Pile de polices : Inter, Noto Sans, Cantarell, Ubuntu, DejaVu Sans. La première police installée est retenue (Cantarell sur une Debian GNOME standard).
- Taille de base : 10 pt.
- Titres : 15 pt ; sections : 11,5 pt ; légendes : 8,6 pt.
- Interligne des messages : 138 %.

**Icônes** : plus aucun emoji dans la navigation ni dans les actions principales. Les emojis restent uniquement dans le contenu des messages (réactions, textes).

## 5. Fichiers modifiés

**Créés**

- `app/design.py`
- `app/icons.py`
- `ui/components.py`
- `docs/rapport-refonte-graphique.md`
- `docs/captures/*.png`

**Modifiés**

- `app/styles.py`
- `app/main_window.py`
- `app/resources/icon.svg` (nouveau logo)
- `ui/conversation_list.py`
- `ui/message_view.py`
- `ui/message_widgets.py`
- `ui/information_panel.py`
- `ui/timeline.py`
- `ui/media_gallery.py`
- `ui/gallery_window.py`
- `ui/media_viewer.py`
- `ui/statistics_window.py`
- `ui/archive_library.py`
- `ui/global_search.py`
- `ui/advanced_search.py`
- `ui/find_bar.py`
- `ui/export_dialog.py`
- `packaging/build_deb.sh` : ajout de la dépendance `python3-pyside6.qtsvg`, nécessaire aux pictogrammes. Sans elle, l'application fonctionne mais les boutons s'affichent sans pictogramme.
- `README.md`

## 6. Écrans modernisés

| Écran | Principales améliorations |
|---|---|
| **Fenêtre principale** | Barre latérale de navigation (Conversations, Recherche, Galerie, Statistiques, Chronologie, Archives, Aide) avec pictogrammes, libellés et état actif. Barre supérieure avec section active, recherche globale mise en avant (champ large avec loupe, indication Ctrl+Maj+F), bouton « Filtres », bascule clair/sombre, bouton principal « Importer ». Écran d'accueil avec logo. Menus natifs et raccourcis inchangés. |
| **Liste des conversations** | Lignes arrondies de 68 px. Avatar à léger dégradé, nom demi-gras, extrait tronqué, date discrète. Indicateurs discrets : nombre de médias, présence dans plusieurs archives. Sélection en bleu doux avec liseré, focus clavier visible. |
| **Lecture des messages** | En-tête avec avatar, pastille de date et pictogrammes. Colonne de lecture centrée (1 060 px au plus) sur grand écran. Bulles arrondies à 14 px, marges aérées, interligne 138 %. Nom de l'expéditeur coloré. Bulles de l'utilisateur en bleu doux. Séparateurs de jours avec filets et pastille. Citations hiérarchisées. Photos et vidéos aux coins arrondis. Cartes de fichiers avec pictogramme par type. Fichier manquant toujours signalé explicitement (cadre rouge pointillé, pictogramme d'alerte). |
| **Panneau d'informations** | En-tête (avatar, nom, participants et messages). Tuiles de chiffres clés. Participants avec pastille et barre de proportion. Onglets en pastilles. Galerie latérale sur trois colonnes. Listes Fichiers et Liens avec pictogrammes. |
| **Chronologie** | Années en demi-gras. Barres d'activité arrondies sur une piste, nombre aligné à droite. Lignes plus hautes. Animation de dépliage désactivable. |
| **Galerie multimédia** | En-tête, onglets en pastilles avec pictogrammes, barre de filtres en carte. Vignettes carrées arrondies. Badge de type (vidéo et durée, GIF, absent). Date et expéditeur au survol. Sélection avec cadre et coche. Barre d'actions : « Tout copier… » et « Copier la sélection… » en bouton principal. Tableaux des fichiers et liens avec pictogrammes et état coloré. |
| **Visionneuse et lecteur vidéo** | Fond immersif bleu nuit (indépendant du thème). Barre de commandes : précédente/suivante, compteur, zoom, Ajuster, 100 %, « Ouvrir avec… », « Dossier ». |
| **Statistiques** | En-tête et sélecteurs de portée. Six cartes d'indicateurs avec pictogramme teinté et chiffre en grand. Chaque graphique dans une carte titrée. Carte d'activité en une seule teinte. Grille discrète. Mots fréquents hiérarchisés par taille et graisse. Calculs inchangés. |
| **Bibliothèque des archives** | En-tête et résumé. Barre d'actions hiérarchisée : « Importer… » en principal, actions secondaires avec pictogrammes, « Retirer… » en rouge à droite. État en pastille colorée (OK en vert, Introuvable en rouge). Tableau sans grille, lignes de 42 px. Détail des conversations dans une carte. |
| **Recherche globale et avancée** | Résultats en cartes arrondies avec sélection bleu doux. Filtres en colonne avec libellés en surtitre, lisibles dans un panneau étroit. Barre « Rechercher dans cette conversation » avec pictogrammes. |
| **Dialogues** | En-tête commun (pictogramme, titre) pour le rapport d'importation, « Aller à la date », « Copier vers un dossier », la galerie, les statistiques et la bibliothèque. Boutons principaux colorés. Boutons Qt standard en français. |

## 7. Captures avant / après

| Avant | Après |
|---|---|
| ![](captures/avant_principal.png) | ![](captures/apres_principal.png) |
| ![](captures/avant_galerie.png) | ![](captures/apres_galerie.png) |
| ![](captures/avant_statistiques.png) | ![](captures/apres_statistiques.png) |
| ![](captures/avant_bibliotheque.png) | ![](captures/apres_bibliotheque.png) |
| ![](captures/avant_visionneuse.png) | ![](captures/apres_visionneuse.png) |
| ![](captures/avant_sombre_principal.png) | ![](captures/apres_sombre_principal.png) |

Autres écrans après la refonte :

- **Recherche avancée** : ![](captures/apres_recherche_avancee.png)
- **Chronologie** : ![](captures/apres_chronologie.png)
- **Copie de médias** : ![](captures/apres_copie.png)
- **Thème sombre** :
  - Galerie : ![](captures/apres_sombre_galerie.png)
  - Statistiques : ![](captures/apres_sombre_statistiques.png)
  - Bibliothèque : ![](captures/apres_sombre_bibliotheque.png)
- **Tailles de fenêtre** :
  - 1024 × 768 : ![](captures/taille_1024x768_principal.png)
  - 1920 × 1080 : ![](captures/taille_1920x1080_principal.png)

## 8. État des thèmes

**Thème clair : complet.** Tous les écrans et dialogues utilisent les jetons ; plus aucune couleur codée en dur dans les écrans. Seules exceptions voulues : la visionneuse, toujours immersive, et le texte blanc sur les avatars et badges.

**Thème sombre : complet et conçu indépendamment.**

- Fond bleu nuit, panneaux et cartes étagés.
- Accents éclaircis.
- Noms d'expéditeurs éclaircis pour rester lisibles.
- Bouton principal plus profond pour le contraste.
- Le changement de thème (Ctrl+Maj+D, menu Affichage ou bouton lune/soleil) s'applique à chaud : fenêtre principale, pictogrammes, liste, panneau, et aussi galerie et statistiques si elles sont ouvertes. Vérifié par trois bascules successives, toutes fenêtres ouvertes, sans avertissement Qt.

## 9. Tests et non-régression

**Suite de tests**

- `.venv/bin/python -m pytest` : **128 réussis, 1 ignoré**, aucun échec.
- Le test ignoré (`tests/test_media.py::test_real_export_media`) lit l'export réel à son ancien emplacement (`~/Téléchargements/Telegram Desktop/ChatExport_2026-11-23`), qui n'existe plus sur la machine.
- Ce test est sans rapport avec la refonte. Il est ignoré par conception quand l'export est absent, et n'a été ni modifié ni désactivé.

**Vérifications complémentaires**

- **Imports Python** de tous les modules : OK.
- **Lancement** via `./run.sh` (environnement virtuel) et via `/usr/bin/python3 main.py` (environnement du paquet .deb) : la fenêtre s'ouvre, aucune trace d'erreur.
- **Feuille de style** : 208 règles analysées une à une, 0 erreur de syntaxe, en clair comme en sombre.
- **Menus et raccourcis** : le code des menus est identique à la version précédente (comparaison automatique). Tous les raccourcis restent actifs : Ctrl+O, Ctrl+L, Ctrl+M, Ctrl+Maj+S, Ctrl+Maj+F, Ctrl+F, Ctrl+Maj+A, Ctrl+K, Ctrl+G, Ctrl+T, Ctrl+I, Ctrl+Maj+D, F1, Alt+←, Ctrl+Début/Fin, Ctrl+PgPréc/PgSuiv, Ctrl+Maj+C (galerie)…
- **Code métier** : aucune modification dans `importer/`, `database/` et `services/`.
- **Interactions** couvertes par les tests d'interface, qui passent tous :
  - listes, tableaux et menus contextuels ;
  - dialogues ;
  - galerie, sélection multiple et copie ;
  - visionneuse ;
  - navigation entre conversations, réponses et dates ;
  - recherche globale, avancée et dans la conversation ;
  - chronologie ;
  - bibliothèque (localisation, réindexation) ;
  - import en arrière-plan.
- **Tailles de fenêtre** 1024 × 768, 1280 × 800, 1440 × 900 et 1920 × 1080 :
  - largeurs minimales des panneaux : liste 270 px, panneau d'informations 290 px ;
  - fenêtre de 980 × 640 au minimum ;
  - sous 1 180 px, le panneau d'informations s'efface automatiquement (le réglage de l'utilisateur n'est pas modifié ; Ctrl+I le réaffiche) ;
  - sous 820 px de zone de lecture, la date et « Mois » de l'en-tête passent en pictogramme, avec la date en infobulle.

**Accessibilité**

- Contraste suffisant des textes principaux et secondaires dans les deux thèmes.
- Taille de base de 10 pt.
- Focus visible : contour bleu sur les champs, boutons et lignes de liste au clavier.
- Infobulles descriptives et noms accessibles sur tous les boutons à pictogramme.
- Animation de dépliage de la chronologie désactivée si `GTK_ENABLE_ANIMATIONS=0` ou `TAE_REDUCE_MOTION=1`.

## 10. Problèmes rencontrés

- **Feuille de style rejetée** par Qt à cause d'un chemin de cache contenant des espaces et des chevrons. Corrigé, voir § 1.
- **Libellés tronqués** sur les boutons à pictogramme : Qt sous-estime la largeur quand une marge de feuille de style s'ajoute à une icône. `icons.bind()` impose désormais une largeur minimale calculée sur le texte en gras.
- **Débordement des filtres avancés** : les listes « Pièce jointe » et « Lien », placées côte à côte, imposaient une largeur minimale supérieure au panneau. Réglé en réduisant leur largeur minimale.
- **Onglets coupés** dans les panneaux étroits : pastilles plus compactes, sans flèches de défilement.
- **Emojis des réactions** : ils s'affichent selon la police d'emoji installée sur le système. Ce point ne relève pas de la feuille de style et n'a pas été modifié.

## 11. Points restant à améliorer

- **Police** : la police Inter n'est pas installée sur la machine de test, donc Cantarell est utilisée. Installer Inter (paquet `fonts-inter`) donnerait un rendu encore plus proche de la maquette ; l'application la choisira automatiquement.
- **Animations** : volontairement limitées (survol, sélection, dépliage). Des transitions de panneau pourraient être ajoutées, en respectant la préférence de réduction des animations.
- **Lecteur vidéo intégré** : seule sa barre de commandes a été restylée ; la zone vidéo dépend de Qt Multimedia.
- **Vérification sur votre écran** : les captures sont produites en rendu hors écran. Un essai sur un vrai bureau (mise à l'échelle HiDPI, police système) reste à faire.
