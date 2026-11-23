"""Point d'extension pour une recherche sémantique (par le sens), prévue ultérieurement.

Aucun modèle n'est fourni : l'application reste 100 % locale et sans dépendance
lourde. Un fournisseur (ex. modèle d'embeddings local + index vectoriel)
implémente `SemanticProvider` puis est branché sur le moteur :

    engine = SearchEngine(db)
    engine.semantic = MonFournisseur(db)
    engine.search(SearchQuery("souvenirs de vacances", mode=MODE_SEMANTIC))

Le moteur se charge ensuite des filtres (conversation, expéditeur, dates, type…),
de l'exclusion des doublons, de la pagination et de la présentation des
résultats : le fournisseur ne fait que proposer des messages candidats classés.

Pistes de stockage pour un fournisseur : une table `message_embeddings
(message_pk INTEGER PRIMARY KEY, model TEXT, vector BLOB)` ajoutée par une
migration, alimentée en tâche de fond après chaque import (`index_archive`).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SemanticProvider(Protocol):
    name: str

    def is_ready(self) -> bool:
        """Vrai si l'index est disponible (modèle chargé, messages indexés)."""
        ...

    def search(self, text: str, limit: int) -> list[tuple[int, float]]:
        """[(messages.id, score)] par pertinence décroissante. Les doublons et filtres
        sont appliqués ensuite par le moteur : renvoyer large (ex. limit = 2000)."""
        ...

    def index_archive(self, archive_id: int) -> int:
        """Indexe (ou réindexe) les messages d'une archive ; retourne le nombre indexé."""
        ...
