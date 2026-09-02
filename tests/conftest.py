"""Configuración compartida de tests: exposición del path y helpers de fixtures."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def make_entry(*, title: str, link: str = "https://example.com/post",
               summary: str, published_parsed=None) -> SimpleNamespace:
    """Construye un objeto mínimo compatible con lo que espera parse_post.parse().

    parse_post accede a los campos vía getattr (title, link, summary,
    published_parsed/updated_parsed), igual que un entry real de feedparser.
    """
    return SimpleNamespace(
        title=title,
        link=link,
        summary=summary,
        published_parsed=published_parsed,
        updated_parsed=None,
    )


def load_july_2026_entry() -> SimpleNamespace:
    """Entry real del Feature Summary de julio 2026, capturado el 2026-08-11.

    Este fixture permite testear el parser contra HTML real de manera local
    y determinista.
    """
    html = (FIXTURES_DIR / "july_2026_feature_summary.html").read_text(encoding="utf-8")
    meta = json.loads((FIXTURES_DIR / "july_2026_feature_summary.json").read_text(encoding="utf-8"))
    published_parsed = time.struct_time(tuple(meta["published_parsed"])) if meta["published_parsed"] else None
    return make_entry(
        title=meta["title"],
        link=meta["link"],
        summary=html,
        published_parsed=published_parsed,
    )
