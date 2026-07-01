"""Constantes do projeto: URLs, modalidades, colunas do CSV e timeouts."""

from pathlib import Path

# --- URLs e domínios ---------------------------------------------------------
BASE_URL = "https://in.senai.br"
AREAS_URL = f"{BASE_URL}/itineraries/areas"
AREA_URL_TEMPLATE = f"{BASE_URL}/itineraries/areas/{{area_id}}/?version=2&tab={{tab}}"

APP_DOMAIN = "in.senai.br"
SSO_DOMAIN = "identidade.senai.br"

# --- Modalidades (índice da tab -> nome) --------------------------------------
# Verificado contra a API em 2026-06: tab = position - 1. São 7 modalidades
# (o site ganhou "Graduação" na tab 5; "Pós-graduação" é a tab 6).
MODALIDADES: dict[int, str] = {
    0: "Iniciação Profissional",
    1: "Qualificação Profissional",
    2: "Técnico",
    3: "Especialização Técnica",
    4: "Aperfeiçoamento Profissional",
    5: "Graduação",
    6: "Pós-graduação",
}

# --- Saída CSV -----------------------------------------------------------------
CSV_COLUMNS: list[str] = [
    "area_id",
    "area",
    "eixo",
    "versao",
    "modalidade",
    "curso",
    "carga_horaria",
    "nivel_modalidade",
    "cbo",
    "cbo_descricao",
]
DEFAULT_OUTPUT = Path("cursos_senai.csv")

# --- Arquivos de estado --------------------------------------------------------
SESSION_FILE = Path("session.json")
LOG_FILE = Path("errors.log")

# --- Timeouts e rate-limiting --------------------------------------------------
DEFAULT_TIMEOUT_MS = 30_000   # espera padrão por seletores/navegação
LOGIN_TIMEOUT_MS = 180_000    # tempo generoso para o fluxo SSO (inclui MFA manual)
REQUEST_DELAY_S = 1.5         # pausa entre navegações para não sobrecarregar o servidor
