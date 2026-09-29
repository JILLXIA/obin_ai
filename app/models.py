from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Rect(BaseModel):
    """Normalized coordinates, origin at the top left of the PDF page."""

    x: float
    y: float
    width: float
    height: float


class Passage(BaseModel):
    id: str
    document_id: str
    pdf_page: int
    printed_page: str | None
    section_path: list[str]
    text: str
    highlight_rects: list[Rect]
    token_count: int
    ordinal: int
    searchable: bool = True

    @property
    def search_text(self) -> str:
        return " > ".join(self.section_path) + "\n" + self.text


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)

    @field_validator("query")
    @classmethod
    def trim_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a question about the filing.")
        return value.strip()


Status = Literal["answered", "partial", "insufficient_evidence", "needs_clarification"]


class AnswerBlock(BaseModel):
    text: str
    citation_ids: list[str]


class Citation(BaseModel):
    id: str
    document_id: str
    pdf_page: int
    printed_page: str | None
    section_path: list[str]
    excerpt: str
    highlight_rects: list[Rect]


class ChatResponse(BaseModel):
    status: Status
    answer_blocks: list[AnswerBlock]
    citations: list[Citation]
    request_id: str


class DraftStatement(BaseModel):
    text: str
    evidence_ids: list[str]


class DraftAnswer(BaseModel):
    status: Status
    statements: list[DraftStatement]
    message: str


class ClaimVerdict(BaseModel):
    statement_index: int
    supported: bool
    reason: str


class GroundingReview(BaseModel):
    claims: list[ClaimVerdict]
    status_appropriate: bool
    message_is_safe: bool
    feedback: str
