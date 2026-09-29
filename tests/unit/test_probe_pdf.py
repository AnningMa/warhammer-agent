from pathlib import Path

import pymupdf

from warhammer_agent.ingestion.probe import probe_pdf


def test_native_text_blank_rotation_and_image(tmp_path: Path) -> None:
    path = tmp_path / "sample.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "Hello PDF")
        page.set_rotation(90)
        blank = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 2, 2), False)
        pix.clear_with(255)
        blank.insert_image(pymupdf.Rect(10, 10, 30, 30), pixmap=pix)
        doc.set_metadata({"title": "Probe test"})
        doc.save(path)
    report = probe_pdf(path)
    assert report["page_count"] == 2
    assert report["metadata"]["title"] == "Probe test"
    assert report["summary"]["no_text_pages"] == [2]
    assert report["summary"]["rotated_pages"] == [1]
    assert report["summary"]["image_instances_measured"] == 1
    assert report["summary"]["pages_with_errors"] == []
    assert report["pages"][0]["non_whitespace_length"] == 8


def test_table_failure_is_not_zero(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "sample.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(path)

    def fail(*args, **kwargs):
        raise RuntimeError("table detection failed")

    monkeypatch.setattr(pymupdf.Page, "find_tables", fail)
    report = probe_pdf(path)
    assert report["summary"]["pages_with_errors"] == [1]
    assert "table_count" not in report["pages"][0]
    assert "tables" in report["pages"][0]["errors"]
