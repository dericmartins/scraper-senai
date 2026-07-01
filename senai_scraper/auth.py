"""Autenticação SSO (identidade.senai.br) e gestão de sessão persistente.

Fluxo real (verificado contra o site em 2026-06):
1. Sem sessão, ``in.senai.br/itineraries/areas`` redireciona para
   ``in.senai.br/login?to=...`` (página com o botão "Entrar com conta SENAI").
2. O botão leva ao SSO WSO2 em ``identidade.senai.br/authenticationendpoint/login.do``,
   com e-mail/CPF e senha na MESMA tela e submit "Continue".
3. Após autenticar, volta para ``in.senai.br`` e a sessão é salva em session.json.

Os seletores abaixo foram extraídos do HTML real. Se o site mudar, rode com
``--no-headless`` para inspecionar e ajuste aqui.
"""

from __future__ import annotations

import getpass
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)
from rich.console import Console

from .constants import (
    APP_DOMAIN,
    AREAS_URL,
    DEFAULT_TIMEOUT_MS,
    LOGIN_TIMEOUT_MS,
    SESSION_FILE,
    SSO_DOMAIN,
)

logger = logging.getLogger(__name__)
console = Console()

# --- Seletores verificados contra o site real ---------------------------------
APP_LOGIN_BUTTON_NAME = "Entrar com conta SENAI"  # botão na página in.senai.br/login
# SSO (identidade.senai.br) — data-testids estáveis do WSO2 customizado.
# Atenção: existe um input HIDDEN com id "username"; o campo visível é o do testid.
EMAIL_SELECTOR = "[data-testid='login-page-username-input']"
PASSWORD_SELECTOR = "[data-testid='login-page-password-input']"
SUBMIT_SELECTOR = "#loginForm button[type='submit']"  # botão "Continue"


def get_credentials() -> tuple[str, str]:
    """Obtém credenciais via SENAI_EMAIL/SENAI_PASSWORD ou prompt seguro."""
    email = os.environ.get("SENAI_EMAIL")
    password = os.environ.get("SENAI_PASSWORD")
    if not email:
        email = input("📧 E-mail/CPF SENAI: ").strip()
    if not password:
        password = getpass.getpass("🔑 Senha SENAI (não aparece ao digitar): ")
    return email, password


def create_context(browser: Browser) -> BrowserContext:
    """Cria o contexto do navegador, reaproveitando session.json se existir."""
    if SESSION_FILE.exists():
        logger.info("Reutilizando sessão salva em %s", SESSION_FILE)
        return browser.new_context(storage_state=str(SESSION_FILE))
    return browser.new_context()


def save_session(context: BrowserContext) -> None:
    """Persiste cookies/localStorage da sessão atual em session.json."""
    context.storage_state(path=str(SESSION_FILE))
    logger.info("Sessão salva em %s", SESSION_FILE)


def _is_authenticated_url(url: str) -> bool:
    """True se a URL é da aplicação autenticada (não é SSO nem /login)."""
    parsed = urlparse(url)
    if SSO_DOMAIN in parsed.netloc:
        return False
    return not parsed.path.startswith("/login")


def is_logged_in(page: Page) -> bool:
    """Navega até a listagem de áreas e verifica se caímos numa tela de login.

    Sem sessão o site redireciona para ``in.senai.br/login?to=...`` (e dali
    para o SSO), então a checagem é pela URL final — sem depender do DOM.
    """
    page.goto(AREAS_URL, wait_until="domcontentloaded")
    try:
        # SPA: espera as requisições assentarem antes de inspecionar a URL final.
        page.wait_for_load_state("networkidle", timeout=DEFAULT_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        logger.warning("networkidle não atingido ao validar sessão; usando URL atual.")
    logged = _is_authenticated_url(page.url)
    logger.info("Validação de sessão: url=%s logged_in=%s", page.url, logged)
    return logged


def perform_login(page: Page) -> None:
    """Executa o fluxo completo de login a partir da página in.senai.br/login.

    Se o cookie do SSO ainda for válido, o identidade.senai.br re-autentica
    silenciosamente (volta direto ao app, sem formulário) — nesse caso nem
    pedimos credenciais.

    Raises:
        RuntimeError: se o SSO não redirecionar de volta (credenciais inválidas,
            captcha/MFA pendente etc.).
    """
    # Etapa 1: botão "Entrar com conta SENAI" leva ao identidade.senai.br —
    # OU direto de volta ao app, se o SSO re-autenticar sem formulário.
    page.get_by_role("button", name=APP_LOGIN_BUTTON_NAME).click()
    page.wait_for_url(
        lambda url: SSO_DOMAIN in urlparse(url).netloc or _is_authenticated_url(url),
        timeout=DEFAULT_TIMEOUT_MS,
    )
    if SSO_DOMAIN not in urlparse(page.url).netloc:
        logger.info("SSO re-autenticou silenciosamente; URL atual: %s", page.url)
        console.print("✅ SSO re-autenticou sem pedir credenciais.")
        return

    # Etapa 2: formulário do SSO (e-mail/CPF e senha na mesma tela).
    email, password = get_credentials()
    logger.info("Iniciando login SSO como %s", email)
    page.wait_for_selector(EMAIL_SELECTOR, timeout=DEFAULT_TIMEOUT_MS)
    page.fill(EMAIL_SELECTOR, email)
    # O backend WSO2 lê o input HIDDEN name="username", normalmente copiado do
    # campo visível por JS. Preenche também direto, por garantia.
    page.evaluate(
        "(v) => { const h = document.getElementById('username'); if (h) h.value = v; }",
        email,
    )
    page.fill(PASSWORD_SELECTOR, password)
    page.click(SUBMIT_SELECTOR)

    # Etapa 3: espera voltar à aplicação autenticada. Timeout generoso para o
    # caso de MFA/captcha resolvido manualmente em modo --no-headless.
    console.print("⏳ Aguardando redirecionamento de volta para in.senai.br...")
    try:
        page.wait_for_url(
            lambda url: APP_DOMAIN in urlparse(url).netloc and _is_authenticated_url(url),
            timeout=LOGIN_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            f"SSO não redirecionou de volta (URL atual: {page.url}). "
            "Possíveis causas: credenciais inválidas, captcha ou MFA. "
            "Rode com --no-headless para ver a tela do SSO."
        ) from exc
    logger.info("Login concluído; URL atual: %s", page.url)


def ensure_authenticated(page: Page) -> None:
    """Garante sessão válida: reusa a salva ou refaz o login e persiste.

    Raises:
        RuntimeError: se mesmo após o login a validação continuar falhando.
    """
    if is_logged_in(page):
        console.print("✅ Sessão válida.")
        return

    console.print("🔐 Sessão ausente ou expirada — realizando login no SSO...")
    perform_login(page)

    if not is_logged_in(page):
        raise RuntimeError(
            "Login aparentemente concluído, mas a aplicação ainda exige login. "
            "Rode com --no-headless para inspecionar e me envie o que aparecer."
        )
    save_session(page.context)
    console.print("✅ Login realizado e sessão salva em session.json.")


@contextmanager
def open_session(headless: bool = True) -> Iterator[Page]:
    """Abre navegador + contexto (com sessão salva, se houver) e entrega a Page."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = create_context(browser)
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            yield page
        finally:
            browser.close()
