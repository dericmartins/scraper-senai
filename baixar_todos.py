#!/usr/bin/env python3
"""Rebaixa todos os cursos já presentes (estrutura_*/) com as correções atuais.

Não-interativo: usa o nome exato gravado em cada course.json para buscar e
selecionar a versão correta, numa única sessão de login. Pula o curso (sem
abortar o lote) se a busca não resolver para uma versão única/exata.
"""
from __future__ import annotations

import glob
import json
import logging
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

from senai_scraper.auth import ensure_authenticated, open_session
from senai_scraper.constants import LOG_FILE
from senai_scraper.course_detail import fetch_course_structure, search_course_versions
from senai_scraper.export_estrutura import slugify, write_structure

console = Console()
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("baixar_todos")


def alvos() -> list[str]:
    nomes: list[str] = []
    for cj in sorted(glob.glob("estrutura_*/course.json")):
        d = json.load(open(cj, encoding="utf-8"))
        nome = ((d.get("curso") or {}).get("course") or {}).get("name")
        if nome:
            nomes.append(nome)
    return nomes


def escolher(nome: str, matches: list[dict]) -> dict | None:
    if not matches:
        return None
    exatos = [m for m in matches if m["nome"].strip().lower() == nome.strip().lower()]
    if len(exatos) == 1:
        return exatos[0]
    if len(matches) == 1:
        return matches[0]
    # ambíguo: prefere exato; se houver vários exatos, o de versão "maior" (mais recente)
    pool = exatos or matches
    return sorted(pool, key=lambda m: m.get("versao", ""), reverse=True)[0]


def main() -> None:
    nomes = alvos()
    console.print(f"♻️  Rebaixando {len(nomes)} curso(s) com as correções atuais...\n")
    ok, falhas = 0, []
    with open_session(headless=True) as page:
        ensure_authenticated(page)
        for nome in nomes:
            try:
                matches = search_course_versions(page, nome)
                escolhido = escolher(nome, matches)
                if escolhido is None:
                    console.print(f"⚠️  [yellow]{nome}[/yellow]: nenhuma versão encontrada — pulado.")
                    falhas.append(nome)
                    continue
                if len(matches) > 1:
                    console.print(f"ℹ️  {nome}: {len(matches)} versões; usando {escolhido['versao']} ({escolhido['area']}).")
                structure = fetch_course_structure(page, escolhido)
                destino = Path(f"estrutura_{slugify(escolhido['nome'])}")
                write_structure(structure, destino)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("Falha ao baixar %s", nome)
                console.print(f"❌ [red]{nome}[/red]: {exc}")
                falhas.append(nome)
    console.print(f"\n✅ Concluído: {ok}/{len(nomes)} baixado(s)." +
                  (f" Falhas: {falhas}" if falhas else ""))


if __name__ == "__main__":
    main()
