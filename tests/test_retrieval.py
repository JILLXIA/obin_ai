import json

import numpy as np
import pytest

from app.config import ROOT
from app.evaluate import has_support
from app.index import Index, expected_metadata, save_embeddings, write_index


def test_gold_keyword_retrieval(index):
    cases = [c for c in json.loads((ROOT / "evaluations/questions.json").read_text()) if "pages" in c]
    failed = [case["id"] for case in cases if not has_support(case, index.retrieve(case["query"], None))]
    assert (len(cases) - len(failed)) / len(cases) >= 0.90, f"Missing supporting passages: {failed}"


def test_retrieval_budget_and_duplicate_removal(index):
    result = index.retrieve("revenue recognition product services", None, limit=6, token_budget=3000)
    assert result
    assert len(result) <= 6
    assert sum(p.token_count for p in result) <= 3000
    assert len(result) == len({p.id for p in result})
    assert all(p.searchable for p in result)


def test_fts_query_syntax_is_data(index):
    assert isinstance(index.keyword_search('" OR * NEAR(x) ; DROP TABLE passages; --'), list)
    assert index.keyword_search("employees")
    assert index.keyword_search("?!*") == []


def test_vectors_cosine_order_and_incomplete_index(tmp_path, passages):
    selected = [p.model_copy(update={"ordinal": i, "searchable": True}) for i, p in enumerate(passages[:3])]
    path = tmp_path / "vectors.sqlite3"
    write_index(path, selected, expected_metadata("test-embedding"))
    save_embeddings(path, [selected[0].id], [[1, 0]])
    partial = Index(path)
    assert not partial.semantic_ready
    with pytest.raises(ValueError, match="incomplete"):
        partial.semantic_search([1, 0])
    save_embeddings(path, [p.id for p in selected[1:]], [[0.8, 0.2], [0, 1]])
    ready = Index(path)
    assert ready.semantic_ready
    assert ready.semantic_search([0, 10]) == [selected[2].id, selected[1].id, selected[0].id]
    with pytest.raises(ValueError, match="match"):
        ready.semantic_search([1, 2, 3])
    with pytest.raises(ValueError, match="Invalid"):
        save_embeddings(path, [selected[0].id], [[np.nan, 0]])


def test_resumable_embeddings_dont_overwrite_completed_batches(tmp_path, passages):
    selected = [p.model_copy(update={"ordinal": i, "searchable": True}) for i, p in enumerate(passages[:2])]
    path = tmp_path / "resume.sqlite3"
    write_index(path, selected, expected_metadata("test"))
    save_embeddings(path, [selected[0].id], [[1, 0]])
    assert Index(path).missing_embedding_ids == [selected[1].id]
