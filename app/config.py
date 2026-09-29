from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "_10-K-Q4-2023-As-Filed.pdf"
SECTION_MAP_PATH = Path(__file__).parent / "resources" / "sections.json"
DOCUMENT_TITLE = "Apple Inc. · 2023 Form 10-K"
EXTRACTION_VERSION = "2"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openai_api_key: SecretStr = SecretStr("")
    answer_model: str = "gpt-6-luna"
    embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = 45
    index_path: Path = ROOT / "data" / "index.sqlite3"

    @property
    def api_key(self) -> str:
        return self.openai_api_key.get_secret_value().strip()
