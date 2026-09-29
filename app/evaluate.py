"""Retrieval diagnostic; --live also runs OpenAI answers for manual review."""

import argparse
import asyncio
import json
from datetime import UTC, datetime

from app.config import ROOT, Settings
from app.index import Index, expected_metadata, read_metadata
from app.provider import OpenAIProvider
from app.service import ChatService


def has_support(case, passages):
    return any(
        p.pdf_page in case["pages"] and case["needle"].casefold() in p.text.casefold() for p in passages
    )


async def evaluate(live=False):
    settings = Settings()
    if read_metadata(settings.index_path) != expected_metadata(settings.embedding_model):
        raise ValueError("Prepare the index before evaluation.")
    index = Index(settings.index_path)
    if live and (not settings.api_key or not index.semantic_ready):
        raise ValueError("Live evaluation requires OPENAI_API_KEY and complete embeddings.")
    provider = OpenAIProvider(settings) if live else None
    cases = json.loads((ROOT / "evaluations" / "questions.json").read_text())
    report = {
        "mode": "live_hybrid" if live else "offline_keyword",
        "created_at": datetime.now(UTC).isoformat(),
        "model": settings.answer_model if live else None,
        "cases": [],
    }
    try:
        for case in cases:
            if "pages" not in case and not live:
                continue
            vector = (await provider.embed([case["query"]]))[0] if provider else None
            passages = index.retrieve(case["query"], vector)
            result = {**case, "retrieved_pages": sorted({p.pdf_page for p in passages})}
            if "pages" in case:
                result["support_retrieved"] = has_support(case, passages)
            if provider:
                answer = await ChatService(index, provider).answer(case["query"], f"eval-{case['id']}")
                result["answer"] = answer.model_dump()
                result["human_review"] = None
                if "expected_status" in case:
                    result["status_passed"] = answer.status == case["expected_status"]
            report["cases"].append(result)
            print(
                f"{case['id']}: "
                + (str(result.get("support_retrieved")) if "pages" in case else answer.status),
                flush=True,
            )
    finally:
        if provider:
            await provider.close()
    scored = [c for c in report["cases"] if "support_retrieved" in c]
    report["retrieval_recall"] = sum(c["support_retrieved"] for c in scored) / len(scored)
    output = ROOT / "data" / ("evaluation-live.json" if live else "evaluation-keyword.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Supporting evidence retrieved: {report['retrieval_recall']:.1%}. Report: {output}")
    if not live:
        print("This measures keyword retrieval only, not semantic retrieval or generated-answer accuracy.")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Makes paid OpenAI requests for all 26 evaluation questions."
    )
    args = parser.parse_args()
    asyncio.run(evaluate(args.live))
