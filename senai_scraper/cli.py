"""Interface de linha de comando do scraper SENAI."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

# Carrega SENAI_EMAIL/SENAI_PASSWORD de um .env na raiz do projeto, se existir.
load_dotenv()

from . import scraper
from .auth import ensure_authenticated, open_session
from .constants import DEFAULT_OUTPUT, LOG_FILE, MODALIDADES
from .course_detail import fetch_course_structure, search_course_versions
from .export import write_csv
from .export_estrutura import slugify, write_structure

app = typer.Typer(add_completion=False, rich_markup_mode="rich")
console = Console()
logger = logging.getLogger("senai_scraper")


def setup_logging() -> None:
    """Configura logging em arquivo (errors.log)."""
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def validate_modalidade(modalidade: str | None) -> str | None:
    """Valida o filtro de modalidade contra a lista conhecida (case-insensitive)."""
    if modalidade is None:
        return None
    for nome in MODALIDADES.values():
        if nome.lower() == modalidade.strip().lower():
            return nome
    validas = ", ".join(MODALIDADES.values())
    raise typer.BadParameter(f"Modalidade inválida: {modalidade!r}. Use uma de: {validas}")


def _extrair_estrutura(page, curso: str, output_dir: Optional[Path]) -> None:
    """Busca o curso pelo endpoint nativo, desambigua e exporta a estrutura completa."""
    matches = search_course_versions(page, curso)
    if not matches:
        console.print(f"❌ Nenhum curso encontrado para {curso!r} na versão atual.")
        raise typer.Exit(code=1)

    if len(matches) == 1:
        escolhido = matches[0]
    else:
        console.print(f"🔎 {len(matches)} cursos encontrados para {curso!r}:")
        for i, m in enumerate(matches, start=1):
            console.print(f"  [bold]{i}[/bold]. {m['nome']}  [dim]({m['area']} · {m['versao']})[/dim]")
        n = typer.prompt("Número do curso desejado", type=int)
        if not 1 <= n <= len(matches):
            raise typer.BadParameter(f"Escolha entre 1 e {len(matches)}.")
        escolhido = matches[n - 1]

    structure = fetch_course_structure(page, escolhido)
    destino = output_dir or Path(f"estrutura_{slugify(escolhido['nome'])}")
    write_structure(structure, destino)


def _regenerar_todos() -> None:
    """Regera os 21 CSVs de cada pacote estrutura_*/ a partir do course.json salvo.

    Offline: o course.json é exatamente o `structure` consumido por build_rows,
    então não há re-scraping. Reescreve os CSVs no próprio diretório.
    """
    pacotes = sorted(Path.cwd().glob("estrutura_*/course.json"))
    if not pacotes:
        console.print("❌ Nenhum estrutura_*/course.json encontrado no diretório atual.")
        raise typer.Exit(code=1)
    console.print(f"♻️  Regerando {len(pacotes)} pacote(s) a partir do course.json...")
    for cj in pacotes:
        with open(cj, encoding="utf-8") as fh:
            structure = json.load(fh)
        console.print(f"[bold]{cj.parent.name}[/bold]")
        write_structure(structure, cj.parent)


@app.command()
def main(
    curso: Optional[str] = typer.Option(None, "--curso", help="Busca curso pelo nome (parcial, case-insensitive)."),
    url: Optional[str] = typer.Option(None, "--url", help="Extrai diretamente de uma URL de área."),
    area: Optional[str] = typer.Option(None, "--area", help="Extrai todas as modalidades de uma área pelo nome."),
    area_id: Optional[int] = typer.Option(None, "--area-id", help="Extrai todas as modalidades de uma área pelo ID."),
    all_areas: bool = typer.Option(False, "--all", help="Varre TODAS as áreas e modalidades."),
    modalidade: Optional[str] = typer.Option(None, "--modalidade", help="Filtra por modalidade (ex.: 'Técnico')."),
    output: Path = typer.Option(DEFAULT_OUTPUT, "--output", help="Arquivo CSV de saída."),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Use --no-headless para depurar visualmente."),
    login_only: bool = typer.Option(False, "--login-only", help="Apenas valida/realiza o login e salva a sessão."),
    detalhe: bool = typer.Option(False, "--detalhe", help="Com --curso: extrai a estrutura COMPLETA do curso e gera os CSVs de importação + course.json."),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="Pasta de saída no modo --detalhe (default: estrutura_<curso>/)."),
    regen_all: bool = typer.Option(False, "--regen-all", help="Regera offline os CSVs de todos os pacotes estrutura_*/ a partir do course.json salvo (sem login/scraping)."),
) -> None:
    """Extrai cursos dos Itinerários SENAI (in.senai.br) e exporta em CSV."""
    setup_logging()
    if regen_all:
        _regenerar_todos()
        return
    modalidade = validate_modalidade(modalidade)

    modes = [curso is not None, url is not None, area is not None, area_id is not None, all_areas]
    if sum(modes) > 1:
        raise typer.BadParameter("Use apenas um modo por vez: --curso, --url, --area, --area-id ou --all.")
    if sum(modes) == 0 and not login_only:
        raise typer.BadParameter("Informe um modo: --curso, --url, --area, --area-id, --all ou --login-only.")
    if detalhe and curso is None:
        raise typer.BadParameter('--detalhe requer --curso "nome do curso".')

    try:
        with open_session(headless=headless) as page:
            ensure_authenticated(page)
            if login_only and sum(modes) == 0:
                console.print("🎉 Autenticação OK. Pronto para a próxima etapa (extração).")
                return

            if detalhe:
                _extrair_estrutura(page, curso, output_dir)
                return

            console.print("🔎 Iniciando extração...")
            if curso is not None:
                rows = scraper.search_curso(page, curso, modalidade)
            elif url is not None:
                rows = scraper.extract_from_url(page, url, modalidade)
            elif area_id is not None:
                rows = scraper.extract_area(page, area_id, modalidade)
            elif area is not None:
                resolved_id = scraper.find_area_by_name(page, area)
                rows = scraper.extract_area(page, resolved_id, modalidade)
            else:
                rows = scraper.extract_all_areas(page, modalidade)

            count = write_csv(rows, output)
            console.print(f"💾 {count} curso(s) exportado(s) para [bold]{output}[/bold]")
    except NotImplementedError as exc:
        console.print(f"🚧 {exc}")
        raise typer.Exit(code=2)
    except Exception as exc:  # noqa: BLE001 — última barreira: loga e informa o usuário
        logger.exception("Falha na execução")
        console.print(f"❌ Erro: {exc}\n   Detalhes em {LOG_FILE}.")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
