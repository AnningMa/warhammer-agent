"""Shared source integrity checks."""

import hashlib
from pathlib import Path


def verify_hash(path: Path, expected: str) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"Source changed; correction requires review: {path}")
