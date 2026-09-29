"""Command-line entry point for probe."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from warhammer_agent.ingestion.probe import main

if __name__ == "__main__":
    main()
