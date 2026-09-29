import json
import sys

import pytest

from warhammer_agent.ingestion.clean import main
from warhammer_agent.ingestion.validation import verify_hash


def test_changed_source_is_rejected(tmp_path):
    source = tmp_path / "source"
    source.write_text("changed")
    with pytest.raises(ValueError, match="Source changed"):
        verify_hash(source, "0" * 64)


def test_missing_reviewed_page_is_rejected(tmp_path, monkeypatch):
    rules = tmp_path / "page.json"
    rules.write_text(json.dumps({"page": 4, "handler": "regions", "schema_version": 1}))
    monkeypatch.setattr(
        sys, "argv", ["clean_pdf", "unused.pdf", "--rules", str(rules), "--pages", "5"]
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
