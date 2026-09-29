from app.index import Index
from app.models import AnswerBlock, ChatResponse, Citation, DraftAnswer, GroundingReview, Passage
from app.provider import InvalidModelResponse, OpenAIProvider

INSUFFICIENT_MESSAGE = "I couldn’t find sufficient support in the retrieved passages to provide a verified answer. Try naming the topic, metric, or reporting year more specifically."


def validate_draft(draft: DraftAnswer, passages: list[Passage]) -> str:
    allowed = {p.id for p in passages}
    if draft.status in ("answered", "partial") and not draft.statements:
        return "An answered or partial response must contain supported statements."
    if draft.status in ("insufficient_evidence", "needs_clarification") and draft.statements:
        return "Non-answer statuses must have no statements."
    if draft.status == "answered" and draft.message.strip():
        return "An answered response must have an empty message."
    if draft.status != "answered" and not draft.message.strip():
        return "Provide a limitation or clarification message."
    if len(draft.statements) > 12:
        return "Use at most twelve concise statements."
    for statement in draft.statements:
        if not statement.text.strip() or not statement.evidence_ids:
            return "Each factual statement needs text and supporting evidence IDs."
        if not set(statement.evidence_ids) <= allowed:
            return "Use only evidence IDs from the provided passages."
    return ""


def validate_review(review: GroundingReview, draft: DraftAnswer) -> str:
    indices = [v.statement_index for v in review.claims]
    if sorted(indices) != list(range(len(draft.statements))):
        return "Grounding review did not cover every statement exactly once."
    if not review.status_appropriate or not review.message_is_safe:
        return review.feedback or "The answer status or uncited message is inappropriate."
    unsupported = [
        v.reason or "A statement is unsupported by its cited evidence."
        for v in review.claims
        if not v.supported
    ]
    return "; ".join(unsupported) if unsupported else ""


def assemble(draft: DraftAnswer, passages: list[Passage], request_id: str) -> ChatResponse:
    lookup = {p.id: p for p in passages}
    citation_ids: dict[str, str] = {}
    citations = []
    blocks = []
    for statement in draft.statements:
        statement_ids = []
        for evidence_id in dict.fromkeys(statement.evidence_ids):
            if evidence_id not in citation_ids:
                citation_id = str(len(citation_ids) + 1)
                citation_ids[evidence_id] = citation_id
                passage = lookup[evidence_id]
                citations.append(
                    Citation(
                        id=citation_id,
                        document_id=passage.document_id,
                        pdf_page=passage.pdf_page,
                        printed_page=passage.printed_page,
                        section_path=passage.section_path,
                        excerpt=passage.text,
                        highlight_rects=passage.highlight_rects,
                    )
                )
            statement_ids.append(citation_ids[evidence_id])
        blocks.append(AnswerBlock(text=statement.text.strip(), citation_ids=statement_ids))
    if draft.message.strip():
        blocks.append(AnswerBlock(text=draft.message.strip(), citation_ids=[]))
    return ChatResponse(status=draft.status, answer_blocks=blocks, citations=citations, request_id=request_id)


class ChatService:
    def __init__(self, index: Index, provider: OpenAIProvider):
        self.index = index
        self.provider = provider

    async def answer(self, query: str, request_id: str) -> ChatResponse:
        vector = (await self.provider.embed([query]))[0]
        passages = self.index.retrieve(query, vector)
        if not passages:
            return self.insufficient(request_id)
        feedback = ""
        model_error = None
        for _ in range(2):
            try:
                model_error = None
                draft = await self.provider.generate(query, passages, feedback)
                feedback = validate_draft(draft, passages)
                if feedback:
                    continue
                review = await self.provider.review(query, passages, draft)
                feedback = validate_review(review, draft)
                if not feedback:
                    return assemble(draft, passages, request_id)
            except InvalidModelResponse as exc:
                model_error = exc
                feedback = "The previous attempt did not produce valid complete structured output."
        if model_error:
            raise model_error
        return self.insufficient(request_id)

    @staticmethod
    def insufficient(request_id):
        return ChatResponse(
            status="insufficient_evidence",
            citations=[],
            request_id=request_id,
            answer_blocks=[AnswerBlock(text=INSUFFICIENT_MESSAGE, citation_ids=[])],
        )
