"""Logging helpers."""

import logging
import sys


def setup_logging(
    level: int = logging.INFO,
    fmt: str = "%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s",
) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)

    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("maxapi").setLevel(logging.INFO)
    logging.getLogger("gspread").setLevel(logging.WARNING)
