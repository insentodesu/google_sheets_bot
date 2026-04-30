"""Entrypoint for accountant MAX bot."""

import sys
from pathlib import Path

# Первой строкой в journalctl — до тяжёлых импортов (maxapi и т.д.).
_ROOT = Path(__file__).resolve().parent
print(f"MAX bot: run.py directory = {_ROOT}", file=sys.stderr, flush=True)

import asyncio

from scheduler import run_scheduler_loop


if __name__ == "__main__":
    asyncio.run(run_scheduler_loop())
