"""Extração da estrutura COMPLETA de um curso via API do in.senai.br.

Endpoints (descobertos no bundle JS da SPA e verificados em 2026-06):

Busca:
- GET /course-list/search?search={termo}          -> cursos agrupados por área+versão

Por curso (course_version_id):
- GET /functions/details/course-version/{id}      -> funções > subfunções > padrões de desempenho
- GET /module-list/details/course-version/{id}    -> módulos > unidades curriculares
- GET /socioemotional-competence/course-version/{id}
- GET /ai-competence/course-version/{id}
- GET /work-context/course-version/{id}/{work-condition|production-means|professional-formations|evolutions}
- GET /cnae-list/course-version/{id}
- GET /course-version/{id}/intermediate-exit-list[/exists]
- GET /utilization-list/course-version/{id}       -> aproveitamentos

Por unidade curricular (curricular_unit_course_version_id):
- GET /capacities/basic/curricular-unit-course-version/{id}
- GET /capacities/technical/curricular-unit-course-version/{id}
- GET /knowledge/curricular-unit-course-version/{id}   (hierárquico via "sublist")
- GET /infrastructure-list/curricular-unit-course-version/{id}
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

from playwright.sync_api import Page
from rich.console import Console

from .constants import REQUEST_DELAY_S
from .scraper import _api_get, _format_versao

logger = logging.getLogger(__name__)
console = Console()

# Pausa menor entre UCs (são 3 chamadas leves por UC).
UC_DELAY_S = 0.5


def search_course_versions(page: Page, nome: str) -> list[dict[str, Any]]:
    """Busca cursos pelo endpoint nativo do site, só na versão atual dos itinerários.

    Returns:
        Lista de candidatos com course_version_id, nome, modalidade, área e versão.
    """
    data = _api_get(page, f"/course-list/search?search={quote(nome)}")
    results: list[dict[str, Any]] = []
    for group in data.get("courses", []):
        version = group.get("version") or {}
        if version.get("situationId") != "1":  # apenas a versão atual
            continue
        for c in group.get("courses", []):
            results.append(
                {
                    "course_version_id": int(c["versionedId"]),
                    "nome": c["course"]["name"],
                    "modality_id": c.get("modalityId", ""),
                    "area_id": int(group["area"]["id"]),
                    "area": group["area"]["name"],
                    "version_id": str(version["id"]),
                    "versao": _format_versao(version),
                }
            )
    return results


def _fetch_optional(page: Page, path: str, default: Any) -> Any:
    """GET que tolera falha: loga e devolve `default` (nem todo curso tem tudo)."""
    try:
        return _api_get(page, path)
    except RuntimeError as exc:
        logger.warning("Endpoint opcional falhou (%s): %s", path, exc)
        return default


def _fetch_curricular_unit(page: Page, uc: dict[str, Any]) -> None:
    """Anexa capacidades, conhecimentos e infraestrutura a uma UC (in-place)."""
    uc_id = uc["curricularUnitCourseVersionId"]
    basicas = _fetch_optional(page, f"/capacities/basic/curricular-unit-course-version/{uc_id}", {})
    tecnicas = _fetch_optional(page, f"/capacities/technical/curricular-unit-course-version/{uc_id}", {})
    conhecimentos = _fetch_optional(page, f"/knowledge/curricular-unit-course-version/{uc_id}", {})
    infra = _fetch_optional(page, f"/infrastructure-list/curricular-unit-course-version/{uc_id}", [])

    uc["capacidades_basicas"] = (basicas or {}).get("capacities", [])
    uc["capacidades_tecnicas"] = (tecnicas or {}).get("capacities", [])
    uc["conhecimentos"] = (conhecimentos or {}).get("knowledgeCurricularUnitCvList", [])
    # Formato da lista de infraestrutura pode vir como lista direta ou embrulhado.
    if isinstance(infra, dict):
        infra = next((v for v in infra.values() if isinstance(v, list)), [])
    uc["infraestrutura"] = infra or []


def fetch_course_structure(page: Page, selecionado: dict[str, Any]) -> dict[str, Any]:
    """Extrai a estrutura completa do curso selecionado (ver search_course_versions).

    Returns:
        Dicionário com todos os dados retornados pela API, agrupados por seção.
    """
    cv = selecionado["course_version_id"]
    console.print(f"📖 Extraindo estrutura de [bold]{selecionado['nome']}[/bold] (course-version {cv})...")

    # Área (eixo tecnológico) e dados base do curso (vêm da listagem da área).
    area_data = _api_get(page, f"/areas/{selecionado['area_id']}?versionId={selecionado['version_id']}")
    av = area_data["areaVersion"]
    courses = _api_get(page, f"/courses/areaVersion/{av['id']}")
    base = next((c for c in courses if int(c["id"]) == cv), None)
    if base is None:
        raise RuntimeError(
            f"Curso {cv} não encontrado na listagem da área {selecionado['area']!r}."
        )

    console.print("  ⚙️  Perfil profissional (funções/subfunções/padrões)...")
    funcoes = _fetch_optional(page, f"/functions/details/course-version/{cv}", [])

    console.print("  📦 Módulos e unidades curriculares...")
    modulos = _fetch_optional(page, f"/module-list/details/course-version/{cv}", [])

    ucs = [uc for mod in modulos for uc in mod.get("curricularUnitList", [])]
    for i, uc in enumerate(ucs, start=1):
        console.print(f"  📘 UC {i}/{len(ucs)}: {uc['curricularUnit']['name']}")
        _fetch_curricular_unit(page, uc)
        time.sleep(UC_DELAY_S)

    console.print("  🧠 Socioemocionais, IA, contexto de trabalho, CNAE...")
    socio = _fetch_optional(page, f"/socioemotional-competence/course-version/{cv}", {})
    ia = _fetch_optional(page, f"/ai-competence/course-version/{cv}", {})
    contexto = {
        chave: _fetch_optional(page, f"/work-context/course-version/{cv}/{rota}", {})
        for chave, rota in [
            ("condicoes_trabalho", "work-condition"),
            ("meios_producao", "production-means"),
            ("formacoes_profissionais", "professional-formations"),
            ("evolucoes", "evolutions"),
        ]
    }
    cnae = _fetch_optional(page, f"/cnae-list/course-version/{cv}", {})
    aproveitamentos = _fetch_optional(page, f"/utilization-list/course-version/{cv}", [])

    saidas: Any = []
    exists = _fetch_optional(page, f"/course-version/{cv}/intermediate-exit-list/exists", {})
    if (exists or {}).get("doesIntermediateExitsExist"):
        saidas = _fetch_optional(page, f"/course-version/{cv}/intermediate-exit-list", [])

    time.sleep(REQUEST_DELAY_S)
    return {
        "curso": base,
        "area": {
            "area_id": str(av["area"]["id"]),
            "area": av["area"]["name"],
            "eixo": (av.get("technologicalAxle") or {}).get("name", ""),
            "versao": _format_versao(av.get("version") or {}),
        },
        "funcoes": funcoes,
        "modulos": modulos,
        "capacidades_socioemocionais": (socio or {}).get("socioemotionalList", []),
        "competencias_ia": (ia or {}).get("aiCompetenceList", []),
        "contexto_trabalho": contexto,
        "cnae": cnae,
        "saidas_intermediarias": saidas,
        "aproveitamentos": aproveitamentos,
    }
