"""Resolve runtime credentials without putting session keys in shared config."""

import os
from pathlib import Path


def resolve_api_key(root: Path, settings: dict, api_key: str | None = None) -> str:
    """An explicit key takes priority; None retains the CLI's .env fallback."""
    if api_key is None:
        from dotenv import load_dotenv

        load_dotenv(root / ".env", override=False)
        key = os.environ.get(settings["api_key_env"], "").strip()
    else:
        key = api_key.strip()
    if not key:
        raise ValueError("Provide a Google API key before making Gemini requests")
    return key
