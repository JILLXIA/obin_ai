"""Create real-document citation metadata for the mocked browser answer."""

import json

from app.config import ROOT, Settings
from app.index import Index
from app.models import DraftAnswer, DraftStatement
from app.service import assemble

index = Index(Settings().index_path)
passage = next(p for p in index.ordered if p.pdf_page == 31 and "383,285" in p.text)
draft = DraftAnswer(
    status="answered",
    message="",
    statements=[
        DraftStatement(
            text="Apple reported total net sales of $383,285 million for fiscal 2023.",
            evidence_ids=[passage.id],
        )
    ],
)
target = ROOT / "data" / "browser-answer.json"
target.write_text(json.dumps(assemble(draft, [passage], "browser-fixture").model_dump(), indent=2))
print(f"Browser fixture written to {target}; this is a test answer, not an LLM result.")
