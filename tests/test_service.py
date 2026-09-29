from unittest.mock import AsyncMock, Mock

import pytest

from app.models import ClaimVerdict, DraftAnswer, DraftStatement, GroundingReview
from app.provider import InvalidModelResponse
from app.service import ChatService, assemble, validate_draft, validate_review


def supported(passage):
    return DraftAnswer(
        status="answered",
        message="",
        statements=[
            DraftStatement(text="Total net sales were $383,285 million in 2023.", evidence_ids=[passage.id]),
        ],
    )


def approval():
    return GroundingReview(
        claims=[ClaimVerdict(statement_index=0, supported=True, reason="Supported")],
        status_appropriate=True,
        message_is_safe=True,
        feedback="",
    )


@pytest.fixture
def evidence(passages):
    return next(p for p in passages if p.pdf_page == 31 and "383,285" in p.text)


@pytest.fixture
def fake_provider(evidence):
    return Mock(
        embed=AsyncMock(return_value=[[1, 0]]),
        generate=AsyncMock(return_value=supported(evidence)),
        review=AsyncMock(return_value=approval()),
    )


def test_citation_metadata_and_excerpt_come_from_source(evidence):
    answer = assemble(supported(evidence), [evidence], "request1")
    assert answer.answer_blocks[0].citation_ids == ["1"]
    citation = answer.citations[0]
    assert citation.pdf_page == 31 and citation.printed_page == "28"
    assert citation.excerpt == evidence.text
    assert citation.section_path == evidence.section_path
    assert citation.highlight_rects == evidence.highlight_rects


def test_repeated_citations_are_deduplicated(evidence):
    draft = supported(evidence)
    draft.statements *= 2
    answer = assemble(draft, [evidence], "request")
    assert len(answer.citations) == 1
    assert all(block.citation_ids == ["1"] for block in answer.answer_blocks)


def test_uncited_claims_and_invalid_status_are_rejected(evidence):
    draft = supported(evidence)
    draft.statements[0].evidence_ids = []
    assert validate_draft(draft, [evidence])
    draft = supported(evidence)
    draft.status = "insufficient_evidence"
    assert validate_draft(draft, [evidence])


async def test_valid_answer_has_grounding_pass(evidence, fake_provider):
    index = Mock(retrieve=Mock(return_value=[evidence]))
    answer = await ChatService(index, fake_provider).answer("2023 total net sales?", "req")
    assert answer.status == "answered"
    fake_provider.review.assert_awaited_once()
    fake_provider.embed.assert_awaited_once_with(["2023 total net sales?"])


async def test_invented_citation_gets_one_repair(evidence, fake_provider):
    invalid = supported(evidence)
    invalid.statements[0].evidence_ids = ["fabricated"]
    fake_provider.generate.side_effect = [invalid, supported(evidence)]
    answer = await ChatService(Mock(retrieve=lambda *_: [evidence]), fake_provider).answer("sales?", "req")
    assert answer.status == "answered"
    assert fake_provider.generate.await_count == 2
    assert "only evidence IDs" in fake_provider.generate.call_args.args[2]


async def test_unsupported_answer_is_never_published(evidence, fake_provider):
    review = approval()
    review.claims[0].supported = False
    review.claims[0].reason = "Wrong year"
    fake_provider.review.return_value = review
    answer = await ChatService(Mock(retrieve=lambda *_: [evidence]), fake_provider).answer("sales?", "req")
    assert answer.status == "insufficient_evidence"
    assert not answer.citations
    assert fake_provider.generate.await_count == 2
    assert "383,285" not in answer.answer_blocks[0].text


async def test_incomplete_model_output_is_bounded(evidence, fake_provider):
    fake_provider.generate.side_effect = InvalidModelResponse("incomplete")
    with pytest.raises(InvalidModelResponse):
        await ChatService(Mock(retrieve=lambda *_: [evidence]), fake_provider).answer("sales?", "req")
    assert fake_provider.generate.await_count == 2


def test_missing_or_duplicate_verdicts_fail(evidence):
    review = approval()
    review.claims = []
    assert validate_review(review, supported(evidence))


def test_rejected_claim_cannot_pass_with_an_empty_reason(evidence):
    review = approval()
    review.claims[0].supported = False
    review.claims[0].reason = ""
    assert validate_review(review, supported(evidence))
    review.claims = [ClaimVerdict(statement_index=0, supported=True, reason="ok")] * 2
    assert validate_review(review, supported(evidence))


async def test_uncited_message_must_pass_review(evidence, fake_provider):
    fake_provider.generate.return_value = DraftAnswer(
        status="needs_clarification", statements=[], message="Which metric do you mean?"
    )
    fake_provider.review.return_value = GroundingReview(
        claims=[], status_appropriate=True, message_is_safe=True, feedback=""
    )
    answer = await ChatService(Mock(retrieve=lambda *_: [evidence]), fake_provider).answer(
        "What about 2022?", "req"
    )
    assert answer.status == "needs_clarification"
    assert answer.citations == []
    fake_provider.review.assert_awaited_once()


async def test_provider_failure_is_not_misreported_as_no_evidence(evidence, fake_provider):
    fake_provider.embed.side_effect = TimeoutError("provider timeout")
    with pytest.raises(TimeoutError):
        await ChatService(Mock(), fake_provider).answer("sales?", "req")
