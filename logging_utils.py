from __future__ import annotations

import logging
from pathlib import Path
from models.data_structures import RuntimeSettings


def configure_logging(settings: RuntimeSettings, output_dir: Path) -> None:
    level = getattr(logging, settings.logging.level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")
    if settings.logging.to_file:
        output_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(output_dir / "run.log", encoding="utf-8")
        file_handler.setLevel(level)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        file_handler.setFormatter(formatter)
        logging.getLogger().addHandler(file_handler)
