"""Usage: python -m app.ingest [--text-only] [--rebuild]."""

import argparse
import asyncio
import sys

from app.config import Settings
from app.document import extract_passages
from app.index import Index, expected_metadata, read_metadata, save_embeddings, write_index
from app.provider import OpenAIProvider


async def ingest(settings: Settings, text_only: bool = False, rebuild: bool = False) -> Index:
    metadata = expected_metadata(settings.embedding_model)
    existing = read_metadata(settings.index_path)
    if rebuild or existing != metadata:
        print("Extracting pages and checking section anchors…", flush=True)
        passages = extract_passages()
        write_index(settings.index_path, passages, metadata)
        print(
            f"Indexed {len(passages)} passages across {len({p.pdf_page for p in passages})} pages.",
            flush=True,
        )
    index = Index(settings.index_path)
    if text_only:
        print("Text index ready. Run again without --text-only to prepare semantic search.", flush=True)
        return index
    missing = index.missing_embedding_ids
    if not missing:
        print("Index and embeddings are already up to date.", flush=True)
        return index
    if not settings.api_key:
        raise ValueError(
            "Set OPENAI_API_KEY in .env, then run python -m app.ingest again. Text extraction is cached."
        )
    provider = OpenAIProvider(settings)
    try:
        for offset in range(0, len(missing), 32):
            identifiers = missing[offset : offset + 32]
            vectors = await provider.embed([index.passages[i].search_text for i in identifiers])
            save_embeddings(settings.index_path, identifiers, vectors)
            print(f"Embedded {min(offset + 32, len(missing))}/{len(missing)} remaining passages.", flush=True)
    finally:
        await provider.close()
    print("Document ready for questions.", flush=True)
    return Index(settings.index_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text-only", action="store_true", help="Extract and index without calling OpenAI.")
    parser.add_argument(
        "--rebuild", action="store_true", help="Rebuild extraction and embeddings from scratch."
    )
    args = parser.parse_args()
    try:
        asyncio.run(ingest(Settings(), args.text_only, args.rebuild))
    except Exception as exc:  # noqa: BLE001 -- CLI boundary must not leak provider bodies or secrets.
        # Avoid including provider response bodies or credentials in terminal output.
        if isinstance(exc, (ValueError, FileNotFoundError)):
            print(str(exc), file=sys.stderr)
        else:
            print(
                f"Indexing failed ({type(exc).__name__}). Check your connection and OpenAI account, then retry.",
                file=sys.stderr,
            )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
