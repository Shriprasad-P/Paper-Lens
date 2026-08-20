"""Lexical, semantic, and hybrid evidence retrieval foundations."""
from enum import Enum


class RetrievalMethod(str, Enum):
    LEXICAL = "LEXICAL"
    SEMANTIC = "SEMANTIC"
    HYBRID = "HYBRID"
