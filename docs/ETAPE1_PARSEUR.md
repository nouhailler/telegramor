# Étape 1 : parseur fiable

## 1. Analyse de la structure du fichier de référence

Fichier : `ChatExport_2026-11-23/messages.html` (19 Ko, conversation « fabien »).

| Élément | Sélecteur réel | Occurrences |
|---|---|---|
| Nom de conversation | `.page_header .text.bold` | 1 |
| Historique | `.history` | 1 |
| Bloc message | `div.message` (id `messageNNN`) | 40 |
| Séparateur de date | `.message.service > .body.details` (id négatif) | 8 |
| Message ordinaire | `.message.default` | 32 |
| dont regroupé | `.message.default.joined` (sans avatar ni `.from_name`) | 8 |
| Avatar | `.userpic_wrap .userpic.userpicN .initials` | 24 |
| Date | `.pull_right.date.details[title]` : `16.12.2025 18:33:18 UTC+01:00` | 32 |
| Réponse | `.reply_to.details a[href="#go_to_message189180"]` | 1 |
| Réactions | `span.reactions > span.reaction.active > .emoji + .userpics .initials[title]` | 2 |
| Photo | `.media_wrap > a.photo_wrap[href] > img.photo[src]` | 2 |
| Vidéo | `.media_wrap > a.video_file_wrap[href] > .video_duration + img.video_file[src]` | 1 |

Points notables :

- **Les séparateurs de date** sont des messages `service` à identifiant négatif
  dont le texte est une date anglaise (« 16 December 2025 »). Ils sont
  distingués des vrais événements système (épinglage, ajout de membre…) par
  analyse de ce texte.
- **L'heure exacte** n'est que dans l'attribut `title` ; le texte visible
  (« 18:33 ») est ignoré. Le fuseau `UTC+01:00` est conservé tel quel.
- **Les liens** ont un texte visible anonymisé (« https://youtu.be/anonymisé »)
  mais un `href` réel : le parseur conserve les deux (texte pour la recherche,
  `href` dans `links` et dans le HTML assaini).
- **Médias** : la miniature de la vidéo pointe vers `video_files/jean.mp4_thumb.jpg`
  alors que le fichier présent est `jenseng.mp4_thumb.jpg`. Conformément au
  cahier des charges, le chemin n'est **pas** corrigé : il est signalé manquant.
- **Expéditeurs** : « remi » porte l'avatar « f » / `userpic4` de « fabien ».
  C'est probablement un effet de l'anonymisation ; le parseur garde le nom
  affiché et signale l'incohérence (`INITIALS_MISMATCH`, niveau info).
- Certains noms ont une espace finale (`fabien `), d'autres non (`remi`) :
  noms normalisés (espaces réduites).

## 2. Classes de données (`importer/models.py`)

- `Message` : identifiants (`html_id`, `message_id`, `conversation_id`,
  `source_file`, `position`), `kind` (default / service / date_separator),
  `is_joined`, expéditeur (+ `sender_inherited`, initiales, couleur d'avatar),
  date (`datetime` avec fuseau, `date_raw`, `timezone`, `utc_offset_minutes`,
  `edited_raw`), contenu (`text` brut, `html` assaini, `links`), relations
  (`reply_to_message_id`, `reply_to_file`, `forwarded_from`, `via_bot`,
  `signature`), `reactions`, `media`, `warnings`.
- `Media` : type, `file_path` (href) et `thumbnail_path` (src) séparés,
  durée brute et en secondes, titre / description / statut, taille de la
  miniature, `not_included`, et après vérification `file_exists`,
  `thumbnail_exists`, `file_size`.
- `Reaction` : emoji (ou image d'emoji personnalisé), nombre, personnes,
  `active`.
- `Conversation`, `Anomaly`.

## 3. Parseur

- Héritage d'expéditeur des messages `joined` depuis le dernier message
  ordinaire nommé, **y compris entre fichiers** (`ParserState`).
- Types reconnus en plus de la référence : GIF, stickers, vocaux, audio,
  fichiers, vidéos rondes, localisation, contact, appel, jeu, facture, sondage,
  messages transférés, via bot, signature, réponse vers un autre fichier,
  réactions avec compteur et emoji personnalisé, mention de modification,
  événements système avec lien.
- **Rien n'est perdu en silence** : tout élément inconnu d'un message est
  conservé en texte et signalé (`UNKNOWN_ELEMENT`).

## 4. Contrôles qualité du rapport

| Code | Contrôle |
|---|---|
| `COUNT_MISMATCH` / `DOM_COUNT_MISMATCH` | comptage indépendant des blocs par expression régulière sur le HTML brut, comparé au DOM et aux objets produits |
| `DUPLICATE_ID` | identifiant présent plusieurs fois |
| `CHRONOLOGY` | date antérieure au message précédent |
| `SEPARATOR_MISMATCH` | date d'un message ≠ séparateur de date courant |
| `JOINED_WITHOUT_SENDER`, `MISSING_SENDER` | expéditeur introuvable |
| `UNPARSED_DATE`, `NO_TIMEZONE`, `MISSING_DATE` | dates |
| `REPLY_UNRESOLVED`, `REPLY_TARGET_MISSING` | réponses sans cible / cible absente |
| `MISSING_FILE`, `MISSING_THUMBNAIL`, `NOT_INCLUDED` | médias |
| `SUSPICIOUS_PATH` | chemin hors archive (non consulté) |
| `INITIALS_MISMATCH` | avatar incohérent avec le nom |
| `EMPTY_MESSAGE`, `UNKNOWN_ELEMENT`, `UNKNOWN_BLOCK` | contenu non reconnu |

## 5. Rapport sur le fichier de référence

40 blocs détectés / 40 importés (complet) : 32 messages ordinaires dont
8 regroupés, 8 séparateurs, 3 expéditeurs, 1 réponse (cible trouvée),
2 réactions, 1 lien, 2 photos, 1 vidéo (42 s), 0 audio, 1 fichier manquant
(miniature vidéo), du 2025-12-16 18:33:18 au 2026-11-12 18:34:47 (+01:00).
Aucune erreur ; 1 avertissement, 6 infos.

## 6. Limites identifiées

1. **Formats non observés en réel** : vocaux, stickers, sondages, transferts…
   ont été écrits d'après la structure connue des exports Telegram Desktop et
   testés sur des fragments synthétiques. À valider sur un export réel qui en
   contient ; le signalement `UNKNOWN_ELEMENT` garantit qu'un écart ne passe
   pas inaperçu.
2. **Identifiant de conversation** : l'export HTML ne contient pas l'identifiant
   Telegram du chat. L'identifiant actuel est dérivé du nom ; deux contacts
   homonymes seraient fusionnés. L'étape 4 (doublons) ajoutera le recouvrement
   des `message_id`.
3. **Langue des séparateurs** : seuls les mois anglais sont reconnus (format
   produit par Telegram Desktop). Un séparateur non reconnu serait classé comme
   événement système, sans perte.
4. **Fuseau horaire** : celui de la machine au moment de l'export est appliqué
   à tous les messages (ici `+01:00` même en juillet). C'est ce que contient
   l'export ; aucune correction n'est faite.
5. **Personnes ayant réagi** : seules celles affichées par l'export (attribut
   `title` des avatars) sont connues ; au-delà, seul le compteur est disponible.
6. **Performance** : ~2 300 messages/s (100 000 messages en 43 s avec
   BeautifulSoup + lxml). Suffisant pour une importation en arrière-plan ;
   optimisable plus tard (lxml direct, parallélisation par fichier).
7. Le texte brut normalise l'indentation des blocs `<pre>` ; le HTML assaini
   la conserve.
