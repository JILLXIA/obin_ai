import pytest

from app.document import extract_passages
from app.index import Index, expected_metadata, write_index


@pytest.fixture(scope="session")
def passages():
    return extract_passages()


@pytest.fixture(scope="session")
def index(tmp_path_factory, passages):
    path = tmp_path_factory.mktemp("index") / "test.sqlite3"
    write_index(path, passages, expected_metadata("text-embedding-3-small"))
    return Index(path)
