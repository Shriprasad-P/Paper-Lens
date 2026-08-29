"""Reproducible, offline-first evaluation and benchmarking for PaperLens.

Evaluation code deliberately stays outside production services.  It consumes
typed benchmark cases and predictions, then emits versioned machine-readable
metrics without changing PaperLens business logic or ground-truth data.
"""

__all__ = ["metrics", "schemas", "provenance", "validation", "run", "real_runner"]
