"""Deterministic, page-local evidence extraction from the one supported PDF."""

import hashlib
import json
import math
import re
from bisect import bisect_right
from pathlib import Path

import pdfplumber

from app.config import PDF_PATH, SECTION_MAP_PATH
from app.models import Passage, Rect


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def estimate_tokens(text: str) -> int:
    # Deliberately conservative for this English filing, including column whitespace.
    # No tokenizer download is needed to prepare or inspect the document offline.
    return max(1, math.ceil(len(text) / 3))


def load_section_map(pdf_path: Path = PDF_PATH, map_path: Path = SECTION_MAP_PATH) -> dict:
    mapping = json.loads(map_path.read_text())
    if checksum(pdf_path) != mapping["pdf_sha256"]:
        raise ValueError("The PDF changed. Rebuild and review the section map before indexing it.")
    return mapping


def printed_label(lines: list[dict]) -> str | None:
    for line in reversed(lines):
        match = re.fullmatch(r"Apple Inc\.\s*\|\s*2023 Form 10-K\s*\|\s*(\d+)", line["text"])
        if match:
            return match[1]
        if line["top"] > 730 and re.fullmatch(r"\d{1,2}", line["text"].strip()):
            return line["text"].strip()
    return None


def line_text(line: dict) -> str:
    """Use pdfplumber's reading order and inferred spaces, preserving each table row.

    extract_text_lines omits whitespace glyphs from its chars list; reconstructing
    prose by concatenating those glyphs would silently join every word together.
    """
    return line["text"].strip()


def line_rect(line: dict, width: float, height: float) -> Rect:
    return Rect(
        x=line["x0"] / width,
        y=line["top"] / height,
        width=(line["x1"] - line["x0"]) / width,
        height=(line["bottom"] - line["top"]) / height,
    )


def is_numeric_table(lines: list[dict]) -> bool:
    # Keep an entire section-page intact when it contains a financial table.
    return sum(bool(re.search(r"\d[\d,.%()]*\s+[$€]?\s*\(?\d", l["text"])) for l in lines) >= 2


def chunk_lines(lines: list[dict], target: int = 600) -> list[list[dict]]:
    if not lines:
        return []
    # Even the largest table-bearing section-page is comfortably under the
    # embeddings input limit. Never separate a financial row from its headers.
    if is_numeric_table(lines):
        return [lines]
    paragraphs: list[list[dict]] = []
    for line in lines:
        if not paragraphs or line["top"] - paragraphs[-1][-1]["bottom"] > 7:
            paragraphs.append([])
        paragraphs[-1].append(line)
    chunks: list[list[dict]] = []
    current: list[dict] = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        joined = current + paragraph
        if current and estimate_tokens("\n".join(line_text(l) for l in joined)) > target:
            chunks.append(current)
            # Overlap only whole small paragraphs, inside this page and section.
            last = paragraphs[paragraph_index - 1]
            current = last[:] if estimate_tokens("\n".join(line_text(l) for l in last)) <= 80 else []
        current.extend(paragraph)
    if current:
        chunks.append(current)
    return chunks


def extract_passages(pdf_path: Path = PDF_PATH, map_path: Path = SECTION_MAP_PATH) -> list[Passage]:
    mapping = load_section_map(pdf_path, map_path)
    sections = mapping["sections"]
    positions = [(entry["page"], entry["top"]) for entry in sections]
    document_id = mapping["pdf_sha256"][:16]
    passages = []
    with pdfplumber.open(pdf_path) as doc:
        if len(doc.pages) != mapping["page_count"]:
            raise ValueError("Unexpected PDF page count.")
        for page in doc.pages:
            lines = page.extract_text_lines()
            if not lines:
                raise ValueError(f"No extractable text on PDF page {page.page_number}.")
            label = printed_label(lines)
            # Check map anchors on every ingest; no model-generated headings.
            for section in (s for s in sections if s["page"] == page.page_number and s["anchor_text"]):
                following = [l for l in lines if section["top"] - 1 <= l["top"] <= section["top"] + 50]
                actual = " ".join(l["text"] for l in following)
                if not actual.startswith(section["anchor_text"]):
                    raise ValueError(
                        f"Section anchor mismatch on page {page.page_number}: {section['anchor_text']}"
                    )
            groups: list[tuple[int, list[dict]]] = []
            for line in lines:
                if line["top"] > 740 and ("Apple Inc. |" in line["text"] or line["text"].strip().isdigit()):
                    continue
                section_index = max(0, bisect_right(positions, (page.page_number, line["top"] + 0.01)) - 1)
                if not groups or groups[-1][0] != section_index:
                    groups.append((section_index, []))
                groups[-1][1].append(line)
            for section_index, group in groups:
                for chunk in chunk_lines(group):
                    text = "\n".join(line_text(l) for l in chunk)
                    section_path = sections[section_index]["section_path"]
                    # A heading on its own is navigational, not supporting evidence.
                    heading_only = re.sub(r"\s+", " ", text) == section_path[-1]
                    identity = f"{document_id}:{page.page_number}:{chunk[0]['top']:.3f}:{text}"
                    passages.append(
                        Passage(
                            id="p_" + hashlib.sha256(identity.encode()).hexdigest()[:16],
                            document_id=document_id,
                            pdf_page=page.page_number,
                            printed_page=label,
                            section_path=section_path,
                            text=text,
                            highlight_rects=[line_rect(l, page.width, page.height) for l in chunk],
                            token_count=estimate_tokens(text + " > ".join(section_path)),
                            ordinal=len(passages),
                            searchable=page.page_number != 3 and not heading_only,
                        )
                    )
    return passages
