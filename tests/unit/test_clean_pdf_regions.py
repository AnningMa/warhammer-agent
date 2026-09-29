import hashlib
from pathlib import Path

import pymupdf
import pytest

from warhammer_agent.ingestion.regions import clean_regions


def make_fixture(path: Path) -> dict:
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 50), "TITLE", fontsize=12)
        page.insert_text((50, 70), "Correct body.", fontsize=9)
        page.insert_text((50, 90), "Thumbnail noise", fontsize=5)
        doc.save(path)
    return {
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "page": 1,
        "min_font_size": 8,
        "heading_min_font_size": 11,
        "regions": [
            {"id": "one", "bbox": [40, 30, 250, 110], "expected_heading": "TITLE"}
        ],
    }


def test_region_keeps_body_and_audits_thumbnail(tmp_path):
    path = tmp_path / "sample.pdf"
    report = clean_regions(path, make_fixture(path))
    assert report["sections"][0]["text"] == "Correct body."
    assert report["excluded_spans"][0]["text"] == "Thumbnail noise"
    assert report["sections"][0]["source_spans"][0]["bbox"]


def test_changed_source_requires_review(tmp_path):
    path = tmp_path / "sample.pdf"
    rules = make_fixture(path)
    rules["source_sha256"] = "wrong"
    with pytest.raises(ValueError, match="PDF changed"):
        clean_regions(path, rules)


def test_wrong_heading_requires_review(tmp_path):
    path = tmp_path / "sample.pdf"
    rules = make_fixture(path)
    rules["regions"][0]["expected_heading"] = "OTHER"
    with pytest.raises(ValueError, match="heading/body"):
        clean_regions(path, rules)
