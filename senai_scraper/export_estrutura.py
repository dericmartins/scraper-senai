"""Geração dos CSVs de importação de estrutura de curso + JSON bruto.

Formato dos templates: ~/Downloads/importacao-estrutura-curso/em-branco/
Campos sem fonte no I.N. (SAEP, bloomTaxonomy, difficulty, deliveryMode,
pré-requisitos, pivôs 11/12/13/15/16/20/21/22) ficam vazios ou só com
cabeçalho, para curadoria manual. O course.json preserva TUDO da API.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

# Cabeçalhos exatos dos templates (em-branco/).
TEMPLATE_HEADERS: dict[str, list[str]] = {
    "01-program.csv": ["programKey", "name", "shortName", "cboCode", "qualificationLevel", "techAxis", "techArea", "techSegment", "minTotalHours", "deliveryMode"],
    "02-campus-programs.csv": ["campusKey", "programKey"],
    "03-modules.csv": ["moduleKey", "programKey", "type", "name", "order"],
    "04-course-units.csv": ["unitKey", "moduleKey", "programKey", "title", "order", "workloadHours", "difficulty", "summary", "objectives"],
    "05-capacity-saep.csv": ["capacitySaepKey", "programKey", "order", "description", "type", "bloomTaxonomy"],
    "06-functions.csv": ["functionKey", "programKey", "order", "title"],
    "07-subfunctions.csv": ["subfunctionKey", "functionKey", "order", "title"],
    "08-performance-standards.csv": ["performanceStandardKey", "subfunctionKey", "order", "description"],
    "09-capacities.csv": ["capacityKey", "unitKey", "type", "description", "bloomTaxonomy"],
    "10-knowledge-topics.csv": ["knowledgeTopicKey", "unitKey", "parentKnowledgeTopicKey", "order", "description"],
    "11-unit-capacity-saep.csv": ["unitKey", "capacitySaepKey"],
    "12-unit-subfunctions.csv": ["unitKey", "subfunctionKey"],
    "13-capacity-saep-capacities.csv": ["capacitySaepKey", "capacityKey"],
    "15-capacity-performance-standards.csv": ["capacityKey", "performanceStandardKey"],
    "16-unit-prerequisites.csv": ["unitKey", "prerequisiteUnitKey"],
    "17-learning-environments.csv": ["environmentKey", "unitKey", "campusKey", "name", "description"],
    "18-equipment-items.csv": ["equipmentKey", "environmentKey", "name", "quantity"],
    "19-learning-resources.csv": ["resourceKey", "environmentKey", "type", "title", "url", "fileKey", "author", "year"],
    "20-capacity-saep-functions.csv": ["capacitySaepKey", "functionKey"],
    "21-capacity-saep-subfunctions.csv": ["capacitySaepKey", "subfunctionKey"],
    "22-saep-knowledge-topics.csv": ["saepKnowledgeTopicKey", "capacitySaepKey", "order", "description"],
}

CAMPUS_KEY = "selected-campus"

# Valores de enum aceitos pelo backend, por (arquivo, coluna). Vazio é inválido.
# 05 só é checado quando o arquivo tem linhas (header-only é válido).
ALLOWED_ENUMS: dict[tuple[str, str], set[str]] = {
    ("01-program.csv", "deliveryMode"): {"IN_PERSON", "ONLINE", "HYBRID"},
    ("03-modules.csv", "type"): {"INTRODUCTORY", "INDUSTRY_BASICS", "SPECIFIC_I", "SPECIFIC_II", "OTHER"},
    ("04-course-units.csv", "difficulty"): {"BEGINNER", "INTERMEDIATE", "ADVANCED"},
    ("05-capacity-saep.csv", "type"): {"TECHNICAL", "BASIC"},
    ("05-capacity-saep.csv", "bloomTaxonomy"): {"REMEMBER", "UNDERSTAND", "APPLY", "ANALYZE", "EVALUATE", "CREATE"},
    ("09-capacities.csv", "type"): {"TECHNICAL", "BASIC", "SOCIOEMOTIONAL"},
    ("09-capacities.csv", "bloomTaxonomy"): {"REMEMBER", "UNDERSTAND", "APPLY", "ANALYZE", "EVALUATE", "CREATE"},
    ("19-learning-resources.csv", "type"): {"FILE", "LINK", "EMBED"},
}

# Chave natural (PK) de cada arquivo com dados.
PRIMARY_KEYS: dict[str, str] = {
    "01-program.csv": "programKey",
    "03-modules.csv": "moduleKey",
    "04-course-units.csv": "unitKey",
    "06-functions.csv": "functionKey",
    "07-subfunctions.csv": "subfunctionKey",
    "08-performance-standards.csv": "performanceStandardKey",
    "09-capacities.csv": "capacityKey",
    "10-knowledge-topics.csv": "knowledgeTopicKey",
    "17-learning-environments.csv": "environmentKey",
    "18-equipment-items.csv": "equipmentKey",
    "19-learning-resources.csv": "resourceKey",
}

# Vínculos entre arquivos: (filho, coluna FK, pai, coluna PK, FK vazia permitida).
FOREIGN_KEYS: list[tuple[str, str, str, str, bool]] = [
    ("02-campus-programs.csv", "programKey", "01-program.csv", "programKey", False),
    ("03-modules.csv", "programKey", "01-program.csv", "programKey", False),
    ("04-course-units.csv", "programKey", "01-program.csv", "programKey", False),
    ("04-course-units.csv", "moduleKey", "03-modules.csv", "moduleKey", False),
    ("06-functions.csv", "programKey", "01-program.csv", "programKey", False),
    ("07-subfunctions.csv", "functionKey", "06-functions.csv", "functionKey", False),
    ("08-performance-standards.csv", "subfunctionKey", "07-subfunctions.csv", "subfunctionKey", False),
    ("09-capacities.csv", "unitKey", "04-course-units.csv", "unitKey", False),
    ("10-knowledge-topics.csv", "unitKey", "04-course-units.csv", "unitKey", False),
    ("10-knowledge-topics.csv", "parentKnowledgeTopicKey", "10-knowledge-topics.csv", "knowledgeTopicKey", True),
    ("17-learning-environments.csv", "unitKey", "04-course-units.csv", "unitKey", False),
    ("18-equipment-items.csv", "environmentKey", "17-learning-environments.csv", "environmentKey", False),
    ("19-learning-resources.csv", "environmentKey", "17-learning-environments.csv", "environmentKey", False),
    ("12-unit-subfunctions.csv", "unitKey", "04-course-units.csv", "unitKey", False),
    ("12-unit-subfunctions.csv", "subfunctionKey", "07-subfunctions.csv", "subfunctionKey", False),
]

# Categorias de infraestrutura do I.N. -> arquivo de destino.
_INFRA_AMBIENTE = "ambientes pedagógicos"
_INFRA_EQUIPAMENTO = {"máquinas, equipamentos, ferramentas e instrumentos", "materiais consumíveis"}
_INFRA_RECURSO = "recursos didáticos"


def slugify(texto: str, max_len: int = 50) -> str:
    """'Técnico em Comércio Exterior' -> 'tecnico-em-comercio-exterior'."""
    norm = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    norm = re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")
    return norm[:max_len].rstrip("-")


def _format_cbo_code(curso: dict[str, Any]) -> str:
    """cboFamily 3422 + cboSpecific 5 -> '342205' (formato do template, sem hífen)."""
    family = (curso.get("cboFamily") or {}).get("code")
    specific = (curso.get("cboSpecific") or {}).get("code")
    if not family:
        return ""
    if specific and str(specific).isdigit():
        return f"{family}{int(specific):02d}"
    return str(family)


def _difficulty_enum(modulo: dict[str, Any]) -> str:
    """Mapeia o tipo do módulo para o nível de dificuldade da UC (template 04).

    INDUSTRY_BASICS/INTRODUCTORY -> BEGINNER; SPECIFIC_I -> INTERMEDIATE;
    SPECIFIC_II -> ADVANCED; OTHER (Específico III+) -> ADVANCED (default).
    """
    tipo = _module_type_enum(modulo)
    return {
        "INDUSTRY_BASICS": "BEGINNER",
        "INTRODUCTORY": "BEGINNER",
        "SPECIFIC_I": "INTERMEDIATE",
        "SPECIFIC_II": "ADVANCED",
    }.get(tipo, "ADVANCED")


# Radical do verbo de ação (sem acento, minúsculo) -> taxonomia de Bloom do
# template (09/05). Casa por prefixo: "configurar"/"configuram" caem em "configur".
_BLOOM_VERB_STEMS: dict[str, str] = {
    "identific": "REMEMBER", "list": "REMEMBER", "nome": "REMEMBER", "defin": "REMEMBER",
    "reconhec": "UNDERSTAND", "compreend": "UNDERSTAND", "descrev": "UNDERSTAND",
    "interpret": "UNDERSTAND", "classific": "UNDERSTAND",
    "aplic": "APPLY", "execut": "APPLY", "utiliz": "APPLY", "realiz": "APPLY",
    "oper": "APPLY", "instal": "APPLY", "configur": "APPLY",
    "analis": "ANALYZE", "diferenci": "ANALYZE", "examin": "ANALYZE", "diagnostic": "ANALYZE",
    "avali": "EVALUATE", "verific": "EVALUATE", "selecion": "EVALUATE",
    "justific": "EVALUATE", "test": "EVALUATE",
    "elabor": "CREATE", "cri": "CREATE", "desenvolv": "CREATE",
    "projet": "CREATE", "planej": "CREATE", "mont": "CREATE",
    "propo": "CREATE", "estrutur": "CREATE", "tracar": "CREATE", "trac": "CREATE",
    # Verbos adicionais frequentes nos planos SENAI (inferência; default era UNDERSTAND).
    "empreg": "APPLY", "codific": "APPLY", "atualiz": "APPLY", "organiz": "APPLY",
    "segu": "APPLY", "atend": "APPLY", "registr": "APPLY", "comunic": "APPLY",
    "compar": "ANALYZE", "levant": "ANALYZE", "correlacion": "ANALYZE",
    "monitor": "EVALUATE",
}


def _bloom_taxonomy(description: str) -> str:
    """Classifica a capacidade pela taxonomia de Bloom a partir do 1º verbo.

    Default UNDERSTAND para verbos não mapeados (loga para curadoria).
    """
    desc = (description or "").strip()
    if not desc:
        return "UNDERSTAND"
    primeiro = re.sub(r"[^a-z]", "", slugify(desc.split()[0], 50))
    for stem, bloom in _BLOOM_VERB_STEMS.items():
        if primeiro.startswith(stem):
            return bloom
    logger.info("bloomTaxonomy: verbo não mapeado %r (default UNDERSTAND)", desc.split()[0])
    return "UNDERSTAND"


def _module_type_enum(modulo: dict[str, Any]) -> str:
    """Mapeia o tipo de módulo do I.N. para o enum do template.

    moduleType do I.N.: 1='Básico' e 5='Módulo da Indústria' (≙ Fundamentos da
    Indústria), 2='Introdutório', 3='Específico' (I/II pelo sufixo da descrição;
    III+ não existe no enum -> OTHER).
    """
    modulo_info = modulo.get("module") or {}
    descricao = modulo_info.get("description", "")
    type_id = (modulo_info.get("moduleType") or {}).get("id")
    if type_id in (1, 5):
        return "INDUSTRY_BASICS"
    if type_id == 2:
        return "INTRODUCTORY"
    if type_id == 3:
        sufixo = descricao.strip().split()[-1] if descricao.strip() else ""
        return {"I": "SPECIFIC_I", "II": "SPECIFIC_II"}.get(sufixo, "OTHER")
    return "OTHER"


def _flatten_knowledge(
    topicos: list[dict[str, Any]], unit_key: str, parent_key: str, prefixo: str,
) -> list[dict[str, str]]:
    """Achata a árvore de conhecimentos ('sublist') em linhas do template 10."""
    rows: list[dict[str, str]] = []
    # Chave pelo índice do irmão (i), não pela position da API: garante unicidade
    # mesmo se a API repetir positions; a coluna "order" preserva a position.
    for i, t in enumerate(topicos, start=1):
        key = f"{prefixo}-{i}"
        rows.append(
            {
                "knowledgeTopicKey": key,
                "unitKey": unit_key,
                "parentKnowledgeTopicKey": parent_key,
                "order": str(t.get("position", "")),
                "description": t.get("description", ""),
            }
        )
        rows.extend(_flatten_knowledge(t.get("sublist", []), unit_key, key, key))
    return rows


def _clean_cell(value: str) -> str:
    """Normaliza uma célula em UMA linha física: troca quebras/whitespace por espaço.

    O backend faz parsing por linha física (não RFC-4180), então descrições com
    \n embutido viram linhas-fantasma com colunas deslocadas. Saneando na escrita,
    cada registro ocupa exatamente uma linha. O course.json preserva o texto bruto.
    """
    if not value:
        return value
    return re.sub(r"\s+", " ", value).strip()


def build_rows(structure: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Converte a estrutura extraída nas linhas de cada CSV do template."""
    rows: dict[str, list[dict[str, str]]] = {name: [] for name in TEMPLATE_HEADERS}

    curso = structure["curso"]
    area = structure["area"]
    nome = (curso.get("course") or {}).get("name", "")
    ano = area.get("versao", "").split(".")[0]
    program_key = f"{slugify(nome)}-{ano}" if ano else slugify(nome)
    modality_level = curso.get("modalityLevel") or {}

    # 01/02 — programa e campus
    rows["01-program.csv"].append(
        {
            "programKey": program_key,
            "name": nome,
            "shortName": "",
            "cboCode": _format_cbo_code(curso),
            "qualificationLevel": modality_level.get("description", ""),
            "techAxis": area.get("eixo", ""),
            "techArea": area.get("area", ""),
            "techSegment": "",
            "minTotalHours": str(curso.get("workload", "")),
            "deliveryMode": "IN_PERSON",
        }
    )
    rows["02-campus-programs.csv"].append({"campusKey": CAMPUS_KEY, "programKey": program_key})

    # 06/07/08 — funções > subfunções > padrões de desempenho
    # Chaves por índice (enumerate) para unicidade garantida; "order" usa a position da API.
    for f_i, f in enumerate(structure.get("funcoes", []), start=1):
        f_key = f"func-{f_i}"
        rows["06-functions.csv"].append(
            {
                "functionKey": f_key,
                "programKey": program_key,
                "order": str(f.get("position", f_i)),
                "title": (f.get("function") or {}).get("description", ""),
            }
        )
        for sf_i, sf in enumerate((f.get("function") or {}).get("subfunctions", []), start=1):
            sf_key = f"subfunc-{f_i}-{sf_i}"
            rows["07-subfunctions.csv"].append(
                {
                    "subfunctionKey": sf_key,
                    "functionKey": f_key,
                    "order": str(sf.get("position", sf_i)),
                    "title": (sf.get("subfunction") or {}).get("description", ""),
                }
            )
            for pd_i, pd in enumerate((sf.get("subfunction") or {}).get("performanceStandards", []), start=1):
                rows["08-performance-standards.csv"].append(
                    {
                        "performanceStandardKey": f"pd-{f_i}-{sf_i}-{pd_i}",
                        "subfunctionKey": sf_key,
                        "order": str(pd.get("position", pd_i)),
                        "description": (pd.get("performanceStandard") or {}).get("description", ""),
                    }
                )

    # 03/04 — módulos e UCs; 09/10/17/18/19 — detalhes por UC
    # Ordenado por "position" (sequência real do curso); o campo "order" da API
    # é ordenação dentro do tipo de módulo e pode se repetir entre módulos.
    uc_seq = 0
    modulos = sorted(structure.get("modulos", []), key=lambda m: m.get("position", 0))
    for modulo in modulos:
        m_pos = modulo.get("position", 0)
        m_key = f"mod-{m_pos}-{slugify((modulo.get('module') or {}).get('description', ''), 30)}"
        rows["03-modules.csv"].append(
            {
                "moduleKey": m_key,
                "programKey": program_key,
                "type": _module_type_enum(modulo),
                "name": (modulo.get("module") or {}).get("description", ""),
                "order": str(m_pos),
            }
        )
        for uc in modulo.get("curricularUnitList", []):
            uc_seq += 1
            uc_nome = (uc.get("curricularUnit") or {}).get("name", "")
            u_key = f"uc-{uc_seq}-{slugify(uc_nome, 40)}"
            rows["04-course-units.csv"].append(
                {
                    "unitKey": u_key,
                    "moduleKey": m_key,
                    "programKey": program_key,
                    "title": uc_nome,
                    "order": str(uc.get("position", "")),
                    "workloadHours": str(uc.get("workload", "")),
                    "difficulty": _difficulty_enum(modulo),
                    "summary": "",
                    "objectives": uc.get("objective", ""),
                }
            )

            # 09 — capacidades (básicas + técnicas) da UC
            for tipo, lista in (
                ("BASIC", uc.get("capacidades_basicas", [])),
                ("TECHNICAL", uc.get("capacidades_tecnicas", [])),
            ):
                for i, cap in enumerate(lista, start=1):
                    rows["09-capacities.csv"].append(
                        {
                            "capacityKey": f"cap-{uc_seq}-{tipo[0].lower()}{i}",
                            "unitKey": u_key,
                            "type": tipo,
                            "description": cap.get("description", ""),
                            "bloomTaxonomy": _bloom_taxonomy(cap.get("description", "")),
                        }
                    )

            # 10 — conhecimentos (árvore)
            rows["10-knowledge-topics.csv"].extend(
                _flatten_knowledge(uc.get("conhecimentos", []), u_key, "", f"kt-{uc_seq}")
            )

            # 17/18/19 — infraestrutura categorizada
            env_key = ""
            ambientes, equipamentos, recursos = [], [], []
            for item in uc.get("infraestrutura", []):
                categoria = ((item.get("type") or {}).get("description") or item.get("typeDescription") or "").strip().lower()
                if categoria == _INFRA_AMBIENTE:
                    ambientes.append(item)
                elif categoria in _INFRA_EQUIPAMENTO:
                    equipamentos.append(item)
                elif categoria == _INFRA_RECURSO:
                    recursos.append(item)
                # demais categorias (ex.: Observações/Recomendações) ficam só no JSON
            for i, item in enumerate(ambientes, start=1):
                key = f"env-{uc_seq}-{i}"
                env_key = env_key or key  # equipamentos/recursos apontam para o 1º ambiente
                rows["17-learning-environments.csv"].append(
                    {
                        "environmentKey": key,
                        "unitKey": u_key,
                        "campusKey": CAMPUS_KEY,
                        "name": item.get("description", ""),
                        "description": "",
                    }
                )
            if not env_key and (equipamentos or recursos):
                # UC sem ambiente pedagógico no I.N.: cria um fallback para os
                # equipamentos/recursos não ficarem com referência solta.
                env_key = f"env-{uc_seq}-1"
                rows["17-learning-environments.csv"].append(
                    {
                        "environmentKey": env_key,
                        "unitKey": u_key,
                        "campusKey": CAMPUS_KEY,
                        "name": "Ambiente pedagógico (não especificado no I.N.)",
                        "description": "",
                    }
                )
            for i, item in enumerate(equipamentos, start=1):
                rows["18-equipment-items.csv"].append(
                    {
                        "equipmentKey": f"equip-{uc_seq}-{i}",
                        "environmentKey": env_key,
                        "name": item.get("description", ""),
                        "quantity": "",
                    }
                )
            for i, item in enumerate(recursos, start=1):
                url = item.get("link") or item.get("url") or ""
                if not url:
                    urls = item.get("infrastructureUrlCurricularUnitCvList") or []
                    if urls:
                        primeiro = urls[0]
                        url = primeiro if isinstance(primeiro, str) else (
                            primeiro.get("url") or primeiro.get("link") or ""
                        )
                rows["19-learning-resources.csv"].append(
                    {
                        "resourceKey": f"res-{uc_seq}-{i}",
                        "environmentKey": env_key,
                        "type": "LINK" if url else ("FILE" if item.get("fileKey") else "LINK"),
                        "title": item.get("description", ""),
                        "url": url,
                        "fileKey": "",
                        "author": "",
                        "year": "",
                    }
                )

    # 12 — unidade <-> subfunção, único cruzamento extraível ("aproveitamentos").
    # Casamento por slug do título contra as chaves já geradas em 04 e 07; pares
    # não resolvidos são descartados (nunca emitir referência solta) e deduplicados.
    uc_por_slug = {slugify(r["title"], 40): r["unitKey"] for r in rows["04-course-units.csv"]}
    sf_por_slug = {slugify(r["title"], 40): r["subfunctionKey"] for r in rows["07-subfunctions.csv"]}
    vistos: set[tuple[str, str]] = set()
    for apv in structure.get("aproveitamentos", []) or []:
        for s in apv.get("subfunctionList", []) or []:
            sf_txt = s.get("subfunction", "") or ""
            uc_txt = ((s.get("curricularUnitUtilization") or {}).get("name", "")) or ""
            u_key = uc_por_slug.get(slugify(uc_txt, 40))
            sf_key = sf_por_slug.get(slugify(sf_txt, 40))
            if not u_key or not sf_key or (u_key, sf_key) in vistos:
                continue
            vistos.add((u_key, sf_key))
            rows["12-unit-subfunctions.csv"].append(
                {"unitKey": u_key, "subfunctionKey": sf_key}
            )

    return rows


def validate_rows(rows: dict[str, list[dict[str, str]]]) -> list[str]:
    """Valida unicidade das chaves naturais e integridade referencial.

    Returns:
        Lista de problemas encontrados (vazia = íntegro).
    """
    problemas: list[str] = []
    for arq, pk in PRIMARY_KEYS.items():
        dups = [k for k, n in Counter(r[pk] for r in rows[arq]).items() if n > 1]
        if dups:
            problemas.append(f"{arq}: chave {pk} duplicada: {dups[:5]}")
    for filho, fk, pai, pk, vazio_ok in FOREIGN_KEYS:
        pais = {r[pk] for r in rows[pai]}
        soltas = {r[fk] for r in rows[filho] if not (vazio_ok and r[fk] == "")} - pais
        if soltas:
            problemas.append(
                f"{filho}.{fk} -> {pai}.{pk}: {len(soltas)} referência(s) solta(s): {sorted(soltas)[:5]}"
            )
    for (arq, col), permitidos in ALLOWED_ENUMS.items():
        invalidos = sorted({r.get(col, "") for r in rows[arq]} - permitidos)
        if invalidos:
            problemas.append(
                f"{arq}.{col}: valor(es) de enum inválido(s) (vazio/fora da lista): {invalidos[:5]}"
            )
    return problemas


def write_structure(structure: dict[str, Any], out_dir: Path) -> None:
    """Grava os 21 CSVs do template + course.json e valida a integridade."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = build_rows(structure)
    rows = {
        fname: [{k: _clean_cell(v) for k, v in r.items()} for r in linhas]
        for fname, linhas in rows.items()
    }
    for filename, headers in TEMPLATE_HEADERS.items():
        with open(out_dir / filename, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows[filename])
    with open(out_dir / "course.json", "w", encoding="utf-8") as fh:
        json.dump(structure, fh, ensure_ascii=False, indent=2)

    preenchidos = sum(1 for r in rows.values() if r)
    console.print(
        f"💾 Estrutura gravada em [bold]{out_dir}/[/bold] "
        f"({preenchidos} CSVs com dados, {len(TEMPLATE_HEADERS) - preenchidos} só cabeçalho, + course.json)"
    )
    for filename in sorted(TEMPLATE_HEADERS):
        n = len(rows[filename])
        if n:
            console.print(f"   • {filename}: {n} linha(s)")

    problemas = validate_rows(rows)
    if problemas:
        for p in problemas:
            logger.warning("Integridade: %s", p)
            console.print(f"⚠️  Integridade: {p}")
        console.print("⚠️  Revise antes de importar (detalhes em errors.log).")
    else:
        console.print("🔒 Integridade validada: chaves únicas e todas as referências resolvem.")
