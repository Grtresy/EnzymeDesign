from __future__ import annotations

import logging
from pathlib import Path


def setup_logger(name: str, stdout_path: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    if stdout_path:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(stdout_path)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

