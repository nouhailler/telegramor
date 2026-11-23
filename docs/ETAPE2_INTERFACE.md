# Étape 2 : première interface

## Choix d'architecture

**Base SQLite dès l'étape 2.** L'interface lit les messages page par page ;
il fallait donc une persistance. Le schéma complet du cahier des charges est
créé (archives, conversations, participants, messages, medias, reactions,
message_references, links) avec la table FTS5 `messages_fts` tenue à jour par
triggers. Elle sera exploitée à l'étape 3. Les migrations passent par
`PRAGMA user_version` (`database/db_manager.py`).

**Ordre d'affichage.** Chaque message reçoit un `seq` (ordre dans la
conversation). Les séparateurs de date de l'export sont conservés et affichés
tels quels.

**Chemins des médias.** La base stocke le `href`/`src` brut et la racine de
l'archive. Le chemin absolu est calculé à l'affichage
(racine / dossier du fichier HTML / href). Déplacer une archive ne demandera
donc que de mettre à jour `archives.root_path` (étape 4).

**Vue des messages.** Widgets Qt par message dans une zone défilante, avec
fenêtre glissante : 120 messages au départ, puis des pages de 60 chargées en
haut ou en bas au défilement, et au plus 400 lignes en mémoire. Une ligne
visible sert d'ancre à chaque chargement pour éviter les sauts. Les
miniatures sont décodées dans des threads (`QThreadPool`) et mises en cache
(`QPixmapCache`, 256 Mo).

**Aucun moteur web.** Le HTML assaini est rendu par `QLabel` (sous-ensemble
de HTML, sans JavaScript ni ressource distante).

**Importation non bloquante.** Elle tourne dans un `QThread` avec sa propre
connexion SQLite (mode WAL), sous une barre de progression annulable.

## Couverture du cahier des charges (pilier 2)

| Exigence | État |
|---|---|
| Liste des conversations : nom, date, aperçu, nombre, recherche, tri | ✔ |
| Bulles, différenciation des expéditeurs, dates et heures | ✔ (côté droit = titulaire du compte) |
| Photos intégrées, agrandissables | ✔ visionneuse avec zoom et navigation |
| Vidéos avec aperçu | ✔ miniature, durée ; lecteur intégré si Qt Multimedia, sinon système |
| Liens cliquables (navigateur) | ✔ |
| Réactions | ✔ avec les noms en info-bulle |
| Réponses avec navigation vers l'original | ✔ surbrillance temporaire + retour |
| Navigation chronologique | ✔ calendrier, menu année/mois, début/fin |
| Panneau d'informations masquable | ✔ participants, période, galerie, fichiers, liens |
| Mode sombre / clair, français, zoom | ✔ |
| Copier un message, ouvrir un fichier dans son application | ✔ menu contextuel |
| Retour au dernier message consulté | ✔ au redémarrage |
| Vocaux, GIF, autocollants, fichiers | ✔ carte ou aperçu selon le format |
| Fichier manquant : indication sans bloquer | ✔ |

## Vérifications

- 80 tests automatisés, dont 7 tests d'interface hors écran : affichage de la
  conversation réelle, saut vers une réponse puis retour, navigation par date,
  thème/zoom/panneau, restauration de la position après redémarrage,
  chargement progressif sur 3 000 messages.
- Rendu contrôlé par captures d'écran (thèmes clair et sombre).

## Limites connues

1. **Lecture vidéo intégrée** : elle nécessite
   `python3-pyside6.qtmultimedia` et `python3-pyside6.qtmultimediawidgets`
   (sinon, l'application ouvre le lecteur du système). Vérifiée sur la vidéo
   de l'export de référence : durée, image, son et lecture corrects (FFmpeg 7.1).
2. **Interface non essayée sur votre écran** : les tests et les captures ont
   été faits en rendu hors écran. Le rendu réel (polices, emojis couleur sous
   Wayland) peut différer légèrement.
3. **Fusion d'une même conversation venant de plusieurs archives** : les
   messages de la seconde archive sont ajoutés après ceux de la première, sans
   dédoublonnage. Ce sera traité à l'étape 4.
4. **Côté droit des bulles** : le titulaire du compte est deviné à partir des
   réactions « actives ». Sans réaction, il faut le choisir via
   Affichage → Mon nom.
5. Les messages vocaux et fichiers audio s'ouvrent dans l'application du
   système (pas de lecteur audio intégré).
