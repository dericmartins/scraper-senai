"""Extração de áreas, modalidades e cursos via API do in.senai.br.

A SPA consome a API JSON em ``api.in.senai.br``, autenticada pelos mesmos
cookies da sessão SSO (domínio .in.senai.br). Em vez de raspar o DOM (tabs,
tabelas, tooltips), usamos os endpoints diretamente através do contexto
Playwright autenticado — mais robusto e muito mais leve para o servidor.

Endpoints (verificados em 2026-06):
- GET /versions                          -> versões disponíveis (situationId "1" = atual)
- GET /areas?versionId={v}               -> todas as áreas + contagem de cursos por modalidade
- GET /areas/{area_id}?versionId={v}     -> área: nome, eixo tecnológico, versão
- GET /courses/areaVersion/{av_id}       -> TODOS os cursos da área (todas as modalidades),
                                            já com CBO (código + descrição) embutido

⚠️ Dois IDs distintos por área:
- ``area.id``        (ex.: 11) — usado na URL do site, no --area-id e no CSV.
- ``areaVersion.id`` (ex.: 38) — interno, usado em /courses/areaVersion/{id}.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page
from rich.console import Console

from .auth import ensure_authenticated
from .constants import MODALIDADES, REQUEST_DELAY_S

logger = logging.getLogger(__name__)
console = Console()

API_BASE = "https://api.in.senai.br"


# --- Camada HTTP ---------------------------------------------------------------


def _api_get(page: Page, path: str) -> Any:
    """GET autenticado na API; refaz o login e tenta de novo se a sessão expirar."""
    url = f"{API_BASE}{path}"
    resp = page.context.request.get(url)
    if resp.status in (401, 403):
        logger.warning("Sessão expirou no meio da execução (%s em %s); refazendo login.", resp.status, path)
        console.print("🔄 Sessão expirou — refazendo login...")
        ensure_authenticated(page)
        resp = page.context.request.get(url)
    if not resp.ok:
        raise RuntimeError(f"API {path} retornou {resp.status}: {resp.text()[:200]}")
    return resp.json()["data"]


def get_current_version_id(page: Page) -> str:
    """Retorna o ID da versão atual dos itinerários (situationId '1')."""
    versions = _api_get(page, "/versions")
    for v in versions:
        if v.get("situationId") == "1":
            return str(v["id"])
    return str(versions[0]["id"])  # fallback: primeira da lista


def list_areas(page: Page, version_id: str) -> list[dict[str, Any]]:
    """Lista todas as áreas da versão, com os dois IDs e contagens por modalidade."""
    data = _api_get(page, f"/areas?versionId={version_id}")
    return data["areas"]


# --- Montagem das linhas do CSV --------------------------------------------------


def _format_versao(version: dict[str, Any]) -> str:
    """{'referenceYear': 2025, 'subversion': 1} -> '2025.1'."""
    return f"{version.get('referenceYear', '')}.{version.get('subversion', '')}"


def _course_to_row(area_info: dict[str, str], course: dict[str, Any]) -> dict[str, str]:
    """Converte um curso da API numa linha do CSV (campos nulos viram vazio)."""
    cbo_family = course.get("cboFamily") or {}
    cbo_specific = course.get("cboSpecific") or {}
    if cbo_family.get("code") and cbo_specific.get("code"):
        # O site exibe o sufixo com 2 dígitos (ex.: 3422-05); a API manda "5".
        especifico = str(cbo_specific["code"])
        if especifico.isdigit():
            especifico = f"{int(especifico):02d}"
        cbo = f"{cbo_family['code']}-{especifico}"
    else:
        cbo = cbo_family.get("code") or ""

    modality_level = course.get("modalityLevel") or {}
    workload = course.get("workload")
    return {
        **area_info,
        "modalidade": (modality_level.get("modality") or {}).get("description", ""),
        "curso": (course.get("course") or {}).get("name", ""),
        "carga_horaria": f"{workload}h" if workload is not None else "",
        "nivel_modalidade": modality_level.get("description", ""),
        "cbo": cbo,
        "cbo_descricao": cbo_specific.get("name", ""),
    }


def _filter_modalidade(rows: list[dict[str, str]], modalidade: str | None) -> list[dict[str, str]]:
    """Filtra por modalidade (case-insensitive); None mantém tudo."""
    if modalidade is None:
        return rows
    alvo = modalidade.casefold()
    return [r for r in rows if r["modalidade"].casefold() == alvo]


# --- Extração -------------------------------------------------------------------


def extract_area(
    page: Page,
    area_id: int,
    modalidade: str | None = None,
    version_id: str | None = None,
    expected_count: int | None = None,
) -> list[dict[str, str]]:
    """Extrai todos os cursos (todas as modalidades) de uma área.

    Args:
        area_id: ID público da área (o mesmo da URL do site).
        modalidade: filtro opcional por modalidade.
        version_id: versão dos itinerários (default: a atual).
        expected_count: total de cursos esperado (sanity check da listagem).
    """
    if version_id is None:
        version_id = get_current_version_id(page)

    data = _api_get(page, f"/areas/{area_id}?versionId={version_id}")
    av = data["areaVersion"]
    area_info = {
        "area_id": str(av["area"]["id"]),
        "area": av["area"]["name"],
        "eixo": (av.get("technologicalAxle") or {}).get("name", ""),
        "versao": _format_versao(av.get("version") or {}),
    }
    area_version_id = av["id"]  # ID interno usado pelo endpoint de cursos

    courses = _api_get(page, f"/courses/areaVersion/{area_version_id}")
    if expected_count is not None and expected_count != len(courses):
        logger.warning(
            "Área %s: listagem anuncia %d cursos, API de cursos retornou %d.",
            area_info["area"], expected_count, len(courses),
        )

    rows = [_course_to_row(area_info, c) for c in courses]
    console.print(
        f"📚 [bold]{area_info['area']}[/bold] (id {area_info['area_id']}): "
        f"{len(rows)} curso(s) extraído(s)"
    )
    return _filter_modalidade(rows, modalidade)


def extract_from_url(page: Page, url: str, modalidade: str | None = None) -> list[dict[str, str]]:
    """Extrai a partir de uma URL de área do site.

    O ``tab`` da URL vira filtro de modalidade (se --modalidade não foi dado);
    o ``version`` da query é respeitado.
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    # Esperado: ['itineraries', 'areas', '{area_id}']
    if len(parts) < 3 or parts[0] != "itineraries" or parts[1] != "areas" or not parts[2].isdigit():
        raise ValueError(
            f"URL não reconhecida: {url!r}. "
            "Esperado: https://in.senai.br/itineraries/areas/{id}/?version=2&tab=N"
        )
    area_id = int(parts[2])

    query = parse_qs(parsed.query)
    version_id = query.get("version", [None])[0]
    if modalidade is None and "tab" in query:
        tab = int(query["tab"][0])
        modalidade = MODALIDADES.get(tab)
        if modalidade is None:
            raise ValueError(f"tab={tab} fora do intervalo conhecido (0-5).")
        console.print(f"🏷️  tab={tab} → filtrando modalidade [bold]{modalidade}[/bold]")

    return extract_area(page, area_id, modalidade, version_id=version_id)


def extract_all_areas(page: Page, modalidade: str | None = None) -> list[dict[str, str]]:
    """Varre todas as áreas da versão atual, com rate-limiting entre elas."""
    version_id = get_current_version_id(page)
    areas = list_areas(page, version_id)
    console.print(f"🗺️  {len(areas)} áreas encontradas (versão {version_id}).")

    all_rows: list[dict[str, str]] = []
    for i, entry in enumerate(areas, start=1):
        area_id = int(entry["area"]["id"])
        expected = sum(m.get("courseCount", 0) for m in entry.get("modalities", []))
        console.print(f"[dim]({i}/{len(areas)})[/dim] ", end="")
        try:
            rows = extract_area(
                page, area_id, modalidade, version_id=version_id, expected_count=expected
            )
            all_rows.extend(rows)
        except Exception:
            logger.exception("Falha ao extrair área %s (%s)", area_id, entry["area"].get("name"))
            console.print(f"⚠️  Falha na área {entry['area'].get('name')} — pulando (ver errors.log).")
        time.sleep(REQUEST_DELAY_S)
    return all_rows


def find_area_by_name(page: Page, nome: str) -> int:
    """Resolve nome de área -> area_id (parcial, case-insensitive).

    Raises:
        ValueError: se nenhuma área casar, ou se o termo for ambíguo.
    """
    version_id = get_current_version_id(page)
    areas = list_areas(page, version_id)
    termo = nome.casefold()

    exatas = [a for a in areas if a["area"]["name"].casefold() == termo]
    parciais = [a for a in areas if termo in a["area"]["name"].casefold()]
    matches = exatas or parciais

    if not matches:
        nomes = ", ".join(sorted(a["area"]["name"] for a in areas))
        raise ValueError(f"Nenhuma área casa com {nome!r}. Áreas disponíveis: {nomes}")
    if len(matches) > 1:
        nomes = ", ".join(a["area"]["name"] for a in matches)
        raise ValueError(f"Termo {nome!r} é ambíguo: {nomes}. Seja mais específico.")
    return int(matches[0]["area"]["id"])


def search_curso(page: Page, nome: str, modalidade: str | None = None) -> list[dict[str, str]]:
    """Busca cursos pelo nome (parcial, case-insensitive) em todas as áreas."""
    termo = nome.casefold()
    rows = extract_all_areas(page, modalidade)
    encontrados = [r for r in rows if termo in r["curso"].casefold()]
    console.print(f"🔍 {len(encontrados)} curso(s) casando com {nome!r}.")
    return encontrados
