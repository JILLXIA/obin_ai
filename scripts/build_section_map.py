"""Rebuild the document-specific heading map for review; never called at request time.

The checked-in map is tied to the PDF checksum. After changing this script or the
PDF, inspect the printed hierarchy and rendered pages before accepting the map.
"""

import hashlib
import json
import re
from bisect import bisect_right
from difflib import SequenceMatcher
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "_10-K-Q4-2023-As-Filed.pdf"


def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def build():
    reader = PdfReader(PDF)
    with pdfplumber.open(PDF) as pdf:
        page_lines = [p.extract_text_lines() for p in pdf.pages]
    entries = []

    def walk(items, parents=()):
        previous = parents
        for item in items:
            if isinstance(item, list):
                walk(item, previous)
                continue
            page = reader.get_destination_page_number(item) + 1
            title = item.title
            if title == "Cover Page":
                entry = {"page": 1, "top": 0, "section_path": [title], "anchor_text": ""}
            else:
                candidates = []
                lines = page_lines[page - 1]
                for start, line in enumerate(lines):
                    joined = ""
                    for end in range(start, min(start + 3, len(lines))):
                        if end > start and lines[end]["top"] - lines[end - 1]["bottom"] > 14:
                            break
                        joined += (" " if joined else "") + lines[end]["text"]
                        score = SequenceMatcher(None, normalize(title), normalize(joined)).ratio()
                        candidates.append((score, line["top"], joined))
                score, top, visible_title = max(candidates, key=lambda c: (c[0], -c[1]))
                if score < 0.70:
                    raise ValueError(f"Heading did not match: {page}: {title} ({score:.2f})")
                entry = {
                    "page": page,
                    "top": round(top, 3),
                    "section_path": [*parents, visible_title],
                    "anchor_text": visible_title,
                }
            entries.append(entry)
            previous = tuple(entry["section_path"])

    walk(reader.outline)
    # This actual heading has a superscript footnote in another font and is not
    # detected as an all-bold line. It ends the Financial Statement Schedules.
    item15 = next(e["section_path"] for e in entries if e["section_path"][-1].startswith("Item 15."))
    exhibits = next(l for l in page_lines[56] if l["text"].startswith("(3) Exhibits required"))
    entries.append(
        {
            "page": 57,
            "top": round(exhibits["top"], 3),
            "section_path": [*item15, exhibits["text"]],
            "anchor_text": exhibits["text"],
        }
    )
    # Printed preamble precedes PART I even though its bookmark targets the top.
    entries.append({"page": 4, "top": 0, "section_path": ["Forward-looking statements"], "anchor_text": ""})
    entries.sort(key=lambda e: (e["page"], e["top"]))
    base_entries = entries[:]
    positions = [(e["page"], e["top"]) for e in base_entries]
    last_bold = None
    last_base = None
    for page, lines in enumerate(page_lines, 1):
        if page < 4:
            continue
        i = 0
        while i < len(lines):
            line = lines[i]
            chars = [c for c in line["chars"] if c["text"].strip()]
            style = (
                "bold"
                if chars and all("Bold" in c["fontname"] and "Obl" not in c["fontname"] for c in chars)
                else "italic"
            )
            styled = chars and all(
                ("Bold" in c["fontname"] or "Obl" in c["fontname"]) and 8.9 <= c["size"] <= 10.1
                for c in chars
            )
            if not styled or line["top"] > 740:
                i += 1
                continue
            start = i
            text = line["text"]
            while i + 1 < len(lines):
                following = lines[i + 1]
                if following["top"] - lines[i]["bottom"] > 5:
                    break
                next_chars = [c for c in following["chars"] if c["text"].strip()]
                if not next_chars or not all(
                    ("Bold" in c["fontname"] if style == "bold" else "Obl" in c["fontname"])
                    and 8.9 <= c["size"] <= 10.1
                    for c in next_chars
                ):
                    break
                i += 1
                text += " " + following["text"]
            i += 1
            base_index = bisect_right(positions, (page, line["top"] + 1)) - 1
            base = base_entries[max(0, base_index)]
            if base is not last_base:
                last_bold = None
                last_base = base
            if any(e["page"] == page and abs(e["top"] - line["top"]) < 2 for e in base_entries):
                continue
            if (
                not re.search(r"[A-Za-z]", text)
                or text in {"Apple Inc.", "ASSETS:", "LIABILITIES AND SHAREHOLDERS’ EQUITY:"}
                or len(text) > 350
                or base["section_path"] == ["Forward-looking statements"]
            ):
                continue
            # Short italic subtitles and bold risk headings; not italic body paragraphs.
            if style == "italic" and (len(text) > 110 or i - start > 2):
                continue
            path = base["section_path"][:]
            if style == "italic" and last_bold:
                path = last_bold["section_path"][:]
            # Exhibit 4.1 uses an additional all-caps group above regular bold subheads.
            if page >= 62 and page <= 75:
                prefix = [
                    "Exhibit 4.1",
                    "DESCRIPTION OF COMMON STOCK" if page < 64 else "DESCRIPTION OF DEBT SECURITIES",
                ]
                if text.startswith("DESCRIPTION OF"):
                    path = ["Exhibit 4.1"]
                elif style == "bold":
                    path = prefix
                elif last_bold:
                    path = last_bold["section_path"][:]
                else:
                    path = prefix + ["Common Stock"]
            entry = {
                "page": page,
                "top": round(line["top"], 3),
                "section_path": path if path[-1] == text else [*path, text],
                "anchor_text": text,
            }
            if style == "bold":
                last_bold = entry
            entries.append(entry)
    entries.sort(key=lambda e: (e["page"], e["top"]))
    result = {
        "pdf_sha256": hashlib.sha256(PDF.read_bytes()).hexdigest(),
        "page_count": 80,
        "sections": entries,
    }
    target = ROOT / "app" / "resources" / "sections.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for entry in entries:
        print(f"{entry['page']:2} {entry['top']:6.1f} {' > '.join(entry['section_path'])}")


if __name__ == "__main__":
    build()
