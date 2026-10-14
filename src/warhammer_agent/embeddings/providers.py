"""Provider-specific retrieval formatting, length checks and vector validation."""

import math
import os
import time
from pathlib import Path

import numpy as np


def normalized_vectors(values, rows: int, dimensions: int) -> np.ndarray:
    vectors = np.asarray(values, dtype=np.float32)
    if vectors.shape != (rows, dimensions) or not np.isfinite(vectors).all():
        raise ValueError("Embedding response has invalid shape or non-finite values")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if not np.isfinite(norms).all() or (norms <= 0).any():
        raise ValueError("Embedding response contains an invalid or zero vector")
    return vectors / norms


def gemini_document(block: dict) -> str:
    title = " > ".join(block.get("section_path", [])) or "none"
    return f"title: {title} | text: {block['embedding_text']}"


def gemini_query(query: str, task: str) -> str:
    return f"task: {task} | query: {query}"


def qwen_query(query: str, instruction: str) -> str:
    return f"Instruct: {instruction}\nQuery:{query}"


def validate_settings(provider: str, settings: dict) -> None:
    dimensions = settings["dimensions"]
    if type(dimensions) is not int:
        raise ValueError("dimensions must be an integer")
    maximum, minimum = (3072, 128) if provider == "gemini" else (1024, 32)
    if not minimum <= dimensions <= maximum:
        raise ValueError(
            f"{provider} dimensions must be between {minimum} and {maximum}"
        )
    if provider == "gemini":
        if settings["model"] != "gemini-embedding-2":
            raise ValueError("This adapter supports gemini-embedding-2 only")
        for name in ["timeout_ms", "attempts", "max_input_bytes"]:
            if type(settings[name]) is not int or settings[name] <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if settings["max_input_bytes"] > 8192:
            raise ValueError(
                "max_input_bytes cannot exceed the conservative 8192-byte guard"
            )
        if settings["query_task"] not in {"search result", "question answering"}:
            raise ValueError("Unsupported Gemini retrieval task")
        interval = settings.get("request_interval_seconds", 0)
        if (
            not isinstance(interval, (int, float))
            or not math.isfinite(interval)
            or interval < 0
        ):
            raise ValueError("request_interval_seconds must be non-negative")
    elif provider == "qwen":
        if settings["model"] != "Qwen/Qwen3-Embedding-0.6B":
            raise ValueError("This adapter supports Qwen/Qwen3-Embedding-0.6B only")
        for name in ["batch_size", "max_seq_length"]:
            if type(settings[name]) is not int or settings[name] <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if settings["max_seq_length"] > 32768:
            raise ValueError("Qwen max_seq_length cannot exceed 32768")
        if not settings["query_instruction"].strip():
            raise ValueError("Qwen query_instruction cannot be blank")
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")


class GeminiEmbedder:
    def __init__(self, settings: dict, root: Path):
        validate_settings("gemini", settings)
        from dotenv import load_dotenv

        load_dotenv(root / ".env", override=False)
        key = os.environ.get(settings["api_key_env"], "").strip()
        if not key:
            raise ValueError(
                f"Fill {settings['api_key_env']} in .env or the environment"
            )
        from google import genai
        from google.genai import types

        self.settings = settings
        self.config = types.EmbedContentConfig(
            output_dimensionality=settings["dimensions"]
        )
        self.client = genai.Client(
            api_key=key,
            http_options=types.HttpOptions(
                timeout=settings["timeout_ms"],
                retry_options=types.HttpRetryOptions(attempts=settings["attempts"]),
            ),
        )
        self._last_request = None

    def _encode(self, texts: list[str]) -> np.ndarray:
        # A list of strings can be aggregated by Embedding 2. Submit exactly
        # one string per request to guarantee one document -> one vector.
        limit = self.settings["max_input_bytes"]
        if any(len(text.encode("utf-8")) > limit for text in texts):
            raise ValueError(
                "Input exceeds conservative Gemini byte guard; split the block first"
            )
        result = []
        for text in texts:
            interval = self.settings.get("request_interval_seconds", 0)
            if self._last_request is not None:
                time.sleep(max(0, interval - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            response = self.client.models.embed_content(
                model=self.settings["model"], contents=text, config=self.config
            )
            embeddings = response.embeddings or []
            if len(embeddings) != 1:
                raise ValueError("Expected exactly one Gemini embedding per document")
            statistics = getattr(embeddings[0], "statistics", None)
            if statistics is not None and getattr(statistics, "truncated", False):
                raise ValueError("Gemini truncated the input; split the block first")
            result.append(embeddings[0].values)
        return normalized_vectors(result, len(texts), self.settings["dimensions"])

    def embed_documents(self, blocks: list[dict]) -> np.ndarray:
        return self._encode([gemini_document(b) for b in blocks])

    def embed_query(self, query: str) -> np.ndarray:
        return self._encode([gemini_query(query, self.settings["query_task"])])[0]

    def close(self) -> None:
        self.client.close()


class QwenEmbedder:
    def __init__(self, settings: dict, root: Path):
        validate_settings("qwen", settings)
        from sentence_transformers import SentenceTransformer

        self.settings = settings
        self.model = SentenceTransformer(
            settings["model"],
            device=settings["device"],
            cache_folder=str(root / settings["cache_dir"]),
            local_files_only=settings["local_files_only"],
        )
        # Set this on the loaded tokenizer: newer Sentence Transformers uses
        # processor_kwargs instead of the older tokenizer_kwargs constructor.
        self.model.tokenizer.padding_side = "left"
        self.model.max_seq_length = settings["max_seq_length"]

    def _encode(self, texts: list[str]) -> np.ndarray:
        # Check full tokenizer inputs before SentenceTransformer can truncate.
        for text in texts:
            tokens = self.model.tokenizer.encode(
                text, add_special_tokens=True, truncation=False
            )
            if len(tokens) > self.settings["max_seq_length"]:
                raise ValueError(
                    "Input exceeds Qwen max_seq_length; split the block first"
                )
        vectors = self.model.encode(
            texts,
            batch_size=self.settings["batch_size"],
            prompt="",
            convert_to_numpy=True,
            normalize_embeddings=False,
            show_progress_bar=False,
        )
        vectors = np.asarray(vectors)
        if vectors.ndim != 2 or vectors.shape[1] < self.settings["dimensions"]:
            raise ValueError("Invalid Qwen embedding response")
        # MRL: truncate first, then normalize again for cosine similarity.
        return normalized_vectors(
            vectors[:, : self.settings["dimensions"]],
            len(texts),
            self.settings["dimensions"],
        )

    def embed_documents(self, blocks: list[dict]) -> np.ndarray:
        return self._encode([b["embedding_text"] for b in blocks])

    def embed_query(self, query: str) -> np.ndarray:
        return self._encode([qwen_query(query, self.settings["query_instruction"])])[0]

    def close(self) -> None:
        pass


def create_embedder(provider: str, settings: dict, root: Path):
    return (GeminiEmbedder if provider == "gemini" else QwenEmbedder)(settings, root)
