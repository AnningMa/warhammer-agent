import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from warhammer_agent.embeddings.cli import evaluate, fingerprint, load_index, save_index
from warhammer_agent.embeddings.providers import (
    GeminiEmbedder,
    QwenEmbedder,
    gemini_document,
    normalized_vectors,
    validate_settings,
)

ROOT = Path(__file__).resolve().parents[2]


def settings(provider):
    return json.loads((ROOT / "config/embeddings.json").read_text())[provider]


def blocks():
    return [
        {
            "block_id": "one",
            "embedding_text": "# Rule\nDocument A",
            "text": "# Rule\nDocument A",
            "section_path": ["Rule"],
            "section_title": "Rule",
            "page_numbers": [6],
        },
        {
            "block_id": "two",
            "embedding_text": "# Other\nDocument B",
            "text": "# Other\nDocument B",
            "section_path": ["Other"],
            "section_title": "Other",
            "page_numbers": [7],
        },
    ]


def fake_gemini(monkeypatch, config, tmp_path, response_values=None):
    calls = []
    values = (
        response_values if response_values is not None else [1.0] * config["dimensions"]
    )

    def embed_content(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=values)])

    client = SimpleNamespace(
        models=SimpleNamespace(embed_content=embed_content), close=lambda: None
    )
    constructors = []
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    monkeypatch.setitem(
        sys.modules,
        "google.genai",
        SimpleNamespace(Client=lambda **kwargs: constructors.append(kwargs) or client),
    )
    monkeypatch.setitem(
        sys.modules,
        "google.genai.types",
        SimpleNamespace(
            EmbedContentConfig=lambda **kwargs: kwargs,
            HttpOptions=lambda **kwargs: kwargs,
            HttpRetryOptions=lambda **kwargs: kwargs,
        ),
    )
    monkeypatch.setitem(
        sys.modules, "google", SimpleNamespace(genai=sys.modules["google.genai"])
    )
    sys.modules["google.genai"].types = sys.modules["google.genai.types"]
    return GeminiEmbedder(config, tmp_path), calls, constructors


def test_gemini_documents_are_separate_requests_and_query_uses_task(
    monkeypatch, tmp_path
):
    config = {**settings("gemini"), "request_interval_seconds": 0}
    model, calls, constructors = fake_gemini(monkeypatch, config, tmp_path)
    vectors = model.embed_documents(blocks())
    assert vectors.shape == (2, 768)
    assert len(calls) == 2
    assert all(isinstance(c["contents"], str) for c in calls)
    assert calls[0]["contents"] == gemini_document(blocks()[0])
    assert calls[0]["config"] == {"output_dimensionality": 768}
    assert constructors[0]["http_options"]["retry_options"]["attempts"] == 3
    model.embed_query("Can I advance and shoot?")
    assert (
        calls[-1]["contents"] == "task: search result | query: Can I advance and shoot?"
    )
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1)


def test_blank_key_fails_without_importing_cloud_sdk(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="Fill GEMINI_API_KEY"):
        GeminiEmbedder(settings("gemini"), tmp_path)


def test_gemini_oversize_fails_before_any_request(monkeypatch, tmp_path):
    model, calls, _ = fake_gemini(monkeypatch, settings("gemini"), tmp_path)
    with pytest.raises(ValueError, match="byte guard"):
        model.embed_documents([{**blocks()[0], "embedding_text": "x" * 8193}])
    assert not calls


def test_gemini_bad_dimension_fails(monkeypatch, tmp_path):
    model, _, _ = fake_gemini(monkeypatch, settings("gemini"), tmp_path, [1.0, 2.0])
    with pytest.raises(ValueError, match="invalid shape"):
        model.embed_documents(blocks()[:1])


def test_qwen_prompts_truncation_guard_and_normalization(monkeypatch, tmp_path):
    calls, constructors = [], []

    def encode(texts, **kwargs):
        calls.append((texts, kwargs))
        return np.tile(np.arange(1, 1025, dtype=np.float32), (len(texts), 1))

    local_model = SimpleNamespace(
        tokenizer=SimpleNamespace(encode=lambda text, **kwargs: list(range(len(text)))),
        encode=encode,
    )
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(
            SentenceTransformer=lambda name, **kwargs: (
                constructors.append((name, kwargs)) or local_model
            )
        ),
    )
    config = {**settings("qwen"), "max_seq_length": 200}
    model = QwenEmbedder(config, tmp_path)
    result = model.embed_documents(blocks())
    assert constructors[0][0] == "Qwen/Qwen3-Embedding-0.6B"
    assert constructors[0][1]["device"] == "cpu"
    assert local_model.tokenizer.padding_side == "left"
    assert calls[0][0] == [b["embedding_text"] for b in blocks()]
    assert calls[0][1]["prompt"] == ""
    assert result.shape == (2, 768)
    assert np.allclose(np.linalg.norm(result, axis=1), 1)
    model.embed_query("When can I shoot?")
    assert calls[-1][0][0].startswith("Instruct: ")
    assert "\nQuery:When can I shoot?" in calls[-1][0][0]
    count = len(calls)
    with pytest.raises(ValueError, match="max_seq_length"):
        model.embed_documents([{**blocks()[0], "embedding_text": "x" * 201}])
    assert len(calls) == count


@pytest.mark.parametrize("values", [[[0, 0]], [[float("nan"), 1]], [[1, 2, 3]]])
def test_invalid_vectors_rejected(values):
    with pytest.raises(ValueError):
        normalized_vectors(values, 1, 2)


def test_index_roundtrip_and_model_or_corpus_changes_rejected(tmp_path):
    path = tmp_path / "gemini.npz"
    config = settings("gemini")
    signature = fingerprint("gemini", config)
    matrix = normalized_vectors([[1, 0], [0, 1]], 2, 2)
    save_index(
        path,
        blocks(),
        matrix,
        {"fingerprint": signature, "input_sha256": "source", "dimensions": 2},
    )
    loaded, vectors = load_index(path, signature, "source")
    assert loaded == blocks()
    assert np.array_equal(vectors, matrix)
    assert list(tmp_path.iterdir()) == [path]
    with pytest.raises(ValueError, match="rebuild"):
        load_index(path, fingerprint("qwen", settings("qwen")), "source")
    with pytest.raises(ValueError, match="rebuild"):
        load_index(path, signature, "changed")


def test_evaluation_matches_target_block_not_only_page():
    model = SimpleNamespace(embed_query=lambda text: np.array([1, 0]))
    cases = [
        {
            "id": "example",
            "question": "rule?",
            "page_number": 7,
            "section_title": "Other",
        }
    ]
    result = evaluate(cases, blocks(), np.array([[1, 0], [0, 1]]), model, 2)
    assert result["hit_rate"] == 1
    assert result["mrr_at_k"] == 0.5
    assert result["results"][0]["rank"] == 2


def test_invalid_model_and_dimensions():
    with pytest.raises(ValueError, match="dimensions"):
        validate_settings("qwen", {**settings("qwen"), "dimensions": 2048})
    with pytest.raises(ValueError, match="gemini-embedding-2 only"):
        validate_settings(
            "gemini", {**settings("gemini"), "model": "gemini-embedding-001"}
        )
