import json

import pytest

from app.config import PDF_PATH, SECTION_MAP_PATH
from app.document import load_section_map


def test_covers_entire_pdf_and_preserves_plain_text(passages):
    assert {p.pdf_page for p in passages} == set(range(1, 81))
    text = "\n".join(p.text for p in passages)
    assert "The Company designs, manufactures and markets smartphones" in text
    assert "Apple Computer Trading (Shanghai) Co., Ltd." in text
    assert len({p.id for p in passages}) == len(passages)
    assert all(p.section_path for p in passages)


def test_financial_table_keeps_headers_units_and_years(passages):
    statement = next(p for p in passages if p.pdf_page == 31 and "383,285" in p.text)
    assert statement.printed_page == "28"
    assert "In millions" in statement.text
    assert "2023 2022 2021" in statement.text
    assert "Total net sales 383,285 394,328 365,817" in statement.text
    assert "(565)" in statement.text
    assert statement.section_path[-1] == "CONSOLIDATED STATEMENTS OF OPERATIONS"
    balance = next(p for p in passages if p.pdf_page == 33 and "29,965" in p.text)
    assert "2023 2022" in balance.text
    assert "In millions" in balance.text
    assert "352,583" in balance.text


def test_continuing_note_and_midpage_heading(passages):
    revenue = next(p for p in passages if p.pdf_page == 38 and "200,583" in p.text)
    earnings = next(p for p in passages if p.pdf_page == 38 and "6.13" in p.text)
    assert revenue.section_path[-1] == "Note 2 – Revenue"
    assert earnings.section_path[-1] == "Note 3 – Earnings Per Share"
    assert revenue.section_path[0] == "PART II"
    assert revenue.printed_page == earnings.printed_page == "35"
    assert max(r.y + r.height for r in revenue.highlight_rects) < min(r.y for r in earnings.highlight_rects)


def test_subheadings_and_exhibit_labels(passages):
    iphone = next(p for p in passages if p.pdf_page == 4 and "iPhone 15 Pro" in p.text)
    assert iphone.section_path[-2:] == ["Products", "iPhone"]
    inventory = next(p for p in passages if "first-in, first-out" in p.text)
    assert inventory.section_path[-1] == "Inventories"
    voting = next(p for p in passages if p.pdf_page == 62 and "one vote per share" in p.text)
    assert voting.section_path[0] == "Exhibit 4.1"
    assert voting.section_path[-2:] == ["Common Stock", "Voting Rights"]
    assert next(p for p in passages if p.pdf_page == 63).printed_page == "2"
    assert next(p for p in passages if p.pdf_page == 76).printed_page is None


def test_highlight_rectangles_fit_page_and_toc_is_not_evidence(passages):
    for passage in passages:
        assert passage.highlight_rects
        for rect in passage.highlight_rects:
            assert 0 <= rect.x <= 1 and 0 <= rect.y <= 1
            assert rect.width > 0 and rect.height > 0
            assert rect.x + rect.width <= 1.001 and rect.y + rect.height <= 1.001
    assert all(not p.searchable for p in passages if p.pdf_page == 3)


def test_changed_document_is_rejected(tmp_path):
    copy = tmp_path / "changed.pdf"
    copy.write_bytes(PDF_PATH.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="PDF changed"):
        load_section_map(copy)


def test_section_map_matches_document_checksum():
    assert len(json.loads(SECTION_MAP_PATH.read_text())["sections"]) > 150
    load_section_map()
