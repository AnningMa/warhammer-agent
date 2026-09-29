from warhammer_agent.ingestion.parse import token_recall


def test_token_recall_counts_duplicates():
    assert token_recall("rule rule move", "rule move") == 0.6667


def test_token_recall_ignores_case_punctuation_and_order():
    assert token_recall("Move, then SHOOT!", "shoot then move") == 1.0


def test_token_recall_handles_empty_native_page():
    assert token_recall(" \n", "<!-- image -->") is None
