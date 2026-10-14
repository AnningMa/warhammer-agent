"""Command-line entry point for Gemini and Qwen rule embeddings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from warhammer_agent.embeddings.cli import main

if __name__ == "__main__":
    main()
