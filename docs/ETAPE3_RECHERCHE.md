# Étape 3 : moteur de recherche

## Moteur (`database/search_engine.py`)

- **Une seule requête** interroge toutes les archives et toutes les
  conversations : la table FTS5 `messages_fts` (créée à l'étape 2, tenue à
  jour par triggers) est jointe aux tables `messages`, `conversations` et
  `archives`.
- **Insensible à la casse et aux accents** (tokenizer
  `unicode61 remove_diacritics 2`).
- **Trois modes** : début de mot (par défaut, `vac` → `vacances`), mots
  entiers, expression exacte. Dans le texte, `"…"` force une expression et
  `-mot` exclut un mot. Le texte saisi n'est jamais injecté tel quel dans la
  syntaxe FTS5 : chaque mot est extrait puis cité.
- **Filtres combinables**, utilisables sans texte : conversation, archive,
  expéditeur, période (jour local), type de contenu, pièce jointe, lien, nom
  de fichier (sous-chaîne du chemin ou du titre, jokers SQL neutralisés).
- **Tri** par pertinence (BM25), du plus récent au plus ancien ou l'inverse ;
  **pagination** par LIMIT/OFFSET avec le nombre total de résultats.
- **Extraits** produits par `snippet()` de FTS5, échappés puis surlignés avec
  `<mark>`.
- **Surlignage dans les bulles** : `highlight_html` repère les termes sans
  tenir compte des accents ni de la casse, en ne touchant que le texte (jamais
  les balises ni les liens).

### Performance

Sur 200 000 messages, toutes les combinaisons testées répondent en moins de
0,3 s. Un piège a été corrigé : avec un filtre d'expéditeur, SQLite
choisissait l'index de l'expéditeur et relançait la recherche plein texte pour
chaque message (154 s). Un `CROSS JOIN` impose désormais l'index plein texte
comme point de départ. Un test vérifie le temps de réponse.

## Interface

| Fonction | Où |
|---|---|
| Recherche globale | barre en haut de la fenêtre (Ctrl+Maj+F) ; résultats dans le panneau gauche |
| Résultat | conversation, date, expéditeur, type, archive, extrait surligné |
| Ouverture d'un résultat | conversation chargée autour du message, message centré et surligné, termes surlignés dans les bulles |
| Retour aux résultats | ils restent affichés ; Échap ou ✕ ramène la liste des conversations |
| Pagination | chargement automatique de 50 résultats de plus en bas de liste |
| Recherche avancée | « Filtres ▾ » (Ctrl+Maj+A) ; compteur de filtres actifs |
| Recherche dans la conversation | 🔍 ou Ctrl+F : compteur « 2 / 3 », ▲▼, Entrée / Maj+Entrée ; « Avancée… » ouvre les filtres sur cette conversation |

## Vérifications

- 11 tests du moteur : expressions FTS générées, recherche multi-archives,
  accents et casse, expression exacte et exclusion, chaque filtre, nom de
  fichier, tri et pagination, requêtes vides ou mal formées, surlignage,
  performance sur 200 000 messages.
- 3 tests d'interface : ouverture d'un résultat d'une autre conversation
  (positionnement, surbrillance, termes surlignés, fermeture), filtres depuis
  l'interface, recherche dans la conversation (compteur, navigation, fermeture).
- Contrôle visuel par captures d'écran.

## Limites

1. **Mots composés et apostrophes** : « l'Italie » est traité comme
   l'expression « l Italie ». Chercher « Italie » le trouve bien.
2. **Pas de lemmatisation** : « cheval » ne trouve pas « chevaux ». Le mode
   « début de mot » couvre les pluriels en -s et la plupart des conjugaisons
   régulières.
3. **Noms d'expéditeurs** : le filtre attend le nom exact, proposé par
   autocomplétion.
4. **Recherche sémantique** (par le sens) : prévue plus tard ; le moteur est
   isolé dans `search_engine.py` pour pouvoir l'ajouter.
