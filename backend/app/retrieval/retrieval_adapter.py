"""Small adapter that keeps HybridRetriever independent from chat's BM25 module."""

from ..chat.retrieval import BM25EvidenceRetriever
from ..db.database import SQLDatabase


def lexical_retrieve(database: SQLDatabase) -> BM25EvidenceRetriever:
    return BM25EvidenceRetriever(database)
