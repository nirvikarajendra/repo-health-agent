"""Logging setup shared by the command-line entry points."""

import logging
from datetime import date
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging() -> None:
    """Log INFO and above to the terminal and to logs/YYYY-MM-DD.log (appended)."""
    LOGS_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOGS_DIR / f"{date.today().isoformat()}.log", mode="a"),
        ],
    )
    # httpx logs every request at INFO; keep only its warnings.
    logging.getLogger("httpx").setLevel(logging.WARNING)
