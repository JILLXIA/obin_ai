"""SQLite evidence storage and small-corpus hybrid retrieval."""

import os
import re
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np

from app.config import EXTRACTION_VERSION, PDF_PATH, SECTION_MAP_PATH
from app.document import checksum
from app.models import Passage

STOPWORDS = {
    "a",
    "an",
    "the",
    "of",
    "in",
    "for",
    "to",
    "from",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "do",
    "does",
    "did",
    "how",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "about",
    "apple",
    "company",
    "its",
    "it",
    "and",
    "or",
    "as",
    "at",
    "by",
    "with",
    "this",
    "that",
    "please",
    "tell",
    "me",
    "according",
    "report",
    "filing",
    "s",
    "have",
    "had",
    "on",
}


def expected_metadata(embedding_model: str) -> dict[str, str]:
    return {
        "pdf_sha256": checksum(PDF_PATH),
        "section_map_sha256": checksum(SECTION_MAP_PATH),
        "extraction_version": EXTRACTION_VERSION,
        "embedding_model": embedding_model,
    }


def write_index(path: Path, passages: list[Passage], metadata: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="index-", suffix=".sqlite3", dir=path.parent)
    os.close(fd)
    try:
        with sqlite3.connect(temporary) as db:
            db.executescript("""
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE passages (id TEXT PRIMARY KEY, data TEXT NOT NULL, embedding BLOB);
                CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, headings, body, tokenize='porter unicode61');
            """)
            db.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
            for passage in passages:
                db.execute(
                    "INSERT INTO passages(id, data) VALUES (?, ?)", (passage.id, passage.model_dump_json())
                )
                if passage.searchable:
                    db.execute(
                        "INSERT INTO search VALUES (?, ?, ?)",
                        (passage.id, " > ".join(passage.section_path), passage.text),
                    )
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_metadata(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            return dict(db.execute("SELECT key, value FROM metadata"))
    except sqlite3.DatabaseError:
        return {}


def save_embeddings(path: Path, ids: list[str], vectors: list[list[float]]) -> None:
    if len(ids) != len(vectors):
        raise ValueError("Embedding response count differs from input count.")
    with sqlite3.connect(path) as db:
        for identifier, vector in zip(ids, vectors, strict=True):
            array = np.asarray(vector, dtype=np.float32)
            if array.ndim != 1 or not array.size or not np.isfinite(array).all() or not np.linalg.norm(array):
                raise ValueError("Invalid embedding vector.")
            db.execute("UPDATE passages SET embedding=? WHERE id=?", (array.tobytes(), identifier))


class Index:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as db:
            rows = db.execute("SELECT id, data, embedding FROM passages").fetchall()
        self.passages = {row[0]: Passage.model_validate_json(row[1]) for row in rows}
        self.ordered = sorted(self.passages.values(), key=lambda p: p.ordinal)
        self.vector_ids = [row[0] for row in rows if row[2] is not None and self.passages[row[0]].searchable]
        vector_ids = set(self.vector_ids)
        arrays = [np.frombuffer(row[2], dtype=np.float32) for row in rows if row[0] in vector_ids]
        self.matrix = np.stack(arrays) if arrays else np.empty((0, 0), dtype=np.float32)
        if arrays:
            if not np.isfinite(self.matrix).all() or (np.linalg.norm(self.matrix, axis=1) == 0).any():
                raise ValueError("Corrupt embeddings; rebuild the index.")
            self.matrix = self.matrix / np.linalg.norm(self.matrix, axis=1, keepdims=True)

    def connect(self):
        return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)

    @property
    def missing_embedding_ids(self) -> list[str]:
        ready = set(self.vector_ids)
        return [p.id for p in self.ordered if p.searchable and p.id not in ready]

    @property
    def semantic_ready(self) -> bool:
        return bool(self.vector_ids) and not self.missing_embedding_ids

    def keyword_search(self, query: str, limit: int = 20) -> list[str]:
        tokens = list(
            dict.fromkeys(t.lower() for t in re.findall(r"\w+", query) if t.lower() not in STOPWORDS)
        )
        if not tokens:
            return []
        # Bind the FTS expression and quote each token; user syntax is never executed.
        expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens[:80])
        with self.connect() as db:
            return [
                r[0]
                for r in db.execute(
                    "SELECT id FROM search WHERE search MATCH ? ORDER BY bm25(search, 0, 2, 1) LIMIT ?",
                    (expression, limit),
                )
            ]

    def semantic_search(self, vector: list[float], limit: int = 20) -> list[str]:
        if not self.semantic_ready:
            raise ValueError("Embeddings are incomplete. Run python -m app.ingest.")
        query = np.asarray(vector, dtype=np.float32)
        if (
            query.shape != (self.matrix.shape[1],)
            or not np.isfinite(query).all()
            or not np.linalg.norm(query)
        ):
            raise ValueError("Query embedding does not match the document index.")
        scores = self.matrix @ (query / np.linalg.norm(query))
        return [self.vector_ids[int(i)] for i in np.argsort(-scores, kind="stable")[:limit]]

    def retrieve(
        self, query: str, vector: list[float] | None, limit: int = 12, token_budget: int = 12000
    ) -> list[Passage]:
        rankings = [self.keyword_search(query)]
        if vector is not None:
            rankings.append(self.semantic_search(vector))
        scores: dict[str, float] = defaultdict(float)
        for ranking in rankings:
            for rank, identifier in enumerate(ranking, 1):
                scores[identifier] += 1 / (60 + rank)
        ranked = sorted(scores, key=lambda key: (-scores[key], self.passages[key].ordinal))
        result: list[Passage] = []
        seen: set[str] = set()
        used = 0

        def append(passage):
            nonlocal used
            normalized = re.sub(r"\s+", " ", passage.text)
            if passage.id in seen or any(normalized == re.sub(r"\s+", " ", p.text) for p in result):
                return
            if len(result) < limit and used + passage.token_count <= token_budget:
                result.append(passage)
                seen.add(passage.id)
                used += passage.token_count

        # Reserve two slots for continuations, particularly multi-page notes.
        for identifier in ranked[: max(1, limit - 2)]:
            append(self.passages[identifier])
        for passage in result[:]:
            for ordinal in (passage.ordinal + 1, passage.ordinal - 1):
                if 0 <= ordinal < len(self.ordered):
                    neighbor = self.ordered[ordinal]
                    if neighbor.searchable and neighbor.section_path == passage.section_path:
                        append(neighbor)
        for identifier in ranked:
            append(self.passages[identifier])
        return result
