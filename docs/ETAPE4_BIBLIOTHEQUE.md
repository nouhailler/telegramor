# Étape 4 : bibliothèque personnelle

## Schéma v2 (migration automatique)

Au premier lancement, la bibliothèque passe du schéma v1 au v2 sans perte.
Cette migration a été vérifiée sur une copie de la bibliothèque réelle.

| Ajout | Rôle |
|---|---|
| `messages.is_duplicate` | copie non affichée d'un message présent dans plusieurs archives |
| `messages.position` | ordre d'origine dans l'export (`seq` devient l'ordre fusionné) |
| `archive_files` | chemin, taille et SHA-256 de chaque fichier HTML importé |
| `archives.content_hash` | empreinte de l'ensemble de l'archive |
| `conversation_aliases` | autres noms d'une conversation renommée |

Les empreintes des archives importées avant la v2 sont calculées au
démarrage.

## Doublons et fusion

- **Identité d'un message** : même conversation et même identifiant
  Telegram (> 0). Toutes les copies sont conservées, une par archive, mais
  une seule est **canonique**, c'est-à-dire affichée, comptée et recherchée.
  La canonique est la copie dont les médias sont présents sur le disque ;
  à défaut, celle de l'archive importée en premier.
- **Retirer une archive** fait réapparaître automatiquement ses messages
  encore présents dans une autre archive : rien n'est perdu.
- **Séparateurs de date** : un seul par jour après fusion.
- **Ordre** : celui de l'export pour une conversation venant d'une seule
  archive (fidélité totale). Pour plusieurs archives, l'ordre est
  chronologique ; les événements sans date suivent l'élément qui les
  précédait dans leur export. Le résultat ne dépend pas de l'ordre
  d'importation (testé).
- **Même dossier réimporté** : son contenu est remplacé.
- **Copie identique ailleurs** (empreinte égale) : signalée dans le rapport,
  et tous ses messages sont des doublons.

## Conversation renommée

L'export HTML ne contient pas l'identifiant du chat. Une conversation
importée sous un nom inconnu est rapprochée d'une conversation existante si
elles partagent assez de couples (identifiant de message, date exacte) :
au moins 3, et au moins 20 % de l'échantillon. La date évite de confondre
deux groupes dont les identifiants de messages recommencent tous deux à 1
(testé). Le nouveau nom est mémorisé comme alias.

## Emplacements et intégrité

- Les médias sont référencés par chemin relatif ; seule la racine de
  l'archive est stockée.
- **Archive introuvable** (déplacée, disque débranché) : signalée au
  démarrage et en rouge dans la bibliothèque. Les messages restent lisibles,
  seuls les médias manquent.
- **Localiser…** vérifie que le dossier choisi contient bien les fichiers
  HTML de l'archive (présence et empreinte) avant de mettre à jour son
  emplacement ; en cas d'écart partiel, une confirmation est demandée.
- **Vérifier l'intégrité** : fichiers HTML présents et inchangés depuis
  l'import, médias présents (l'état des médias est mis à jour).
- **Réindexer** relit l'export depuis son emplacement, sans créer de doublons.
- **Reconstruire l'index de recherche** reconstruit FTS5 (`rebuild`) puis
  l'optimise.

## Vérifications

- 15 tests de bibliothèque :
  - exports qui se recoupent, dans les deux ordres d'importation ;
  - retrait d'une archive et réapparition de ses messages ;
  - copie identique, réimport du même dossier ;
  - renommage (seuil de rapprochement, alias, groupes homonymes) ;
  - choix de la copie canonique selon les médias présents ;
  - place des événements sans date ;
  - déplacement puis relocalisation, fichier modifié après l'import ;
  - renommage d'une archive, filtre par archive ;
  - migration v1 → v2, reconstruction de l'index.
- 2 tests d'interface : filtre par archive, fenêtre Bibliothèque
  (archive introuvable, relocalisation, retrait), réindexation en
  arrière-plan.

## Limites

1. **Deux contacts portant exactement le même nom** et exportés séparément
   sont fusionnés : leurs messages ne se recoupent pas, mais l'identifiant de
   conversation est dérivé du nom. Il n'existe pas encore de commande pour
   les séparer.
2. **Messages modifiés entre deux exports** : la copie canonique est choisie
   d'après les médias présents, pas d'après la version la plus récente du
   texte. Les deux versions sont conservées en base.
3. Le contrôle d'intégrité ne compte comme manquants que les fichiers
   originaux, pas les miniatures.
