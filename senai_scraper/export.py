"""Exportação dos cursos extraídos para CSV (utf-8-sig, compatível com Excel)."""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable
from pathlib import Path

from .constants import CSV_COLUMNS

logger = logging.getLogger(__name__)


def write_csv(rows: Iterable[dict[str, str]], output: Path) -> int:
    """Grava as linhas no CSV e retorna a quantidade escrita.

    Campos ausentes viram célula vazia; campos extras são ignorados.
    """
    count = 0
    with open(output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})
            count += 1
    logger.info("CSV gravado: %s (%d linhas)", output, count)
    return count
