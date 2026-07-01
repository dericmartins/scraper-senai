# Scraper SENAI — Itinerários (in.senai.br)

CLI em Python para extrair informações de cursos do site de Itinerários do SENAI
e exportar em CSV (compatível com Excel).

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate          # fish: source .venv/bin/activate.fish
pip install -r requirements.txt
playwright install chromium
```

## Autenticação

O site exige login via SSO (identidade.senai.br). As credenciais podem vir de
um arquivo `.env`, de variáveis de ambiente ou de um prompt seguro (a senha
não aparece ao digitar):

```bash
# Opção 1 — arquivo .env na raiz do projeto (recomendado)
cp .env.example .env   # e preencha SENAI_EMAIL e SENAI_PASSWORD

# Opção 2 — variáveis de ambiente
export SENAI_EMAIL="seu@email.com"       # fish: set -x SENAI_EMAIL "seu@email.com"
export SENAI_PASSWORD="sua-senha"        # opcional; se ausente, será pedida via prompt
```

O `.env` já está no `.gitignore` — nunca o commite.

A sessão é salva em `session.json` e reutilizada nas execuções seguintes.
Se expirar, o login é refeito automaticamente.

Para validar apenas o login (recomendado no primeiro uso, em modo visual):

```bash
python -m senai_scraper --login-only --no-headless
```

## Uso

```bash
# Buscar um curso pelo nome (parcial, case-insensitive)
python -m senai_scraper --curso "eletricista"

# Extrair de uma URL de área específica
python -m senai_scraper --url "https://in.senai.br/itineraries/areas/12/?version=2&tab=2"

# Extrair todas as modalidades de uma área (por nome ou ID)
python -m senai_scraper --area "Metalmecânica"
python -m senai_scraper --area-id 12

# Varrer TODAS as áreas e modalidades
python -m senai_scraper --all

# Opções adicionais
python -m senai_scraper --all --modalidade "Técnico" --output tecnicos.csv
python -m senai_scraper --area-id 12 --no-headless   # depuração visual

# Estrutura COMPLETA de um curso (módulos, UCs, capacidades, conhecimentos,
# funções/subfunções/padrões, infraestrutura, socioemocionais, IA, contexto)
python -m senai_scraper --curso "eletrotécnica" --detalhe
python -m senai_scraper --curso "eletrotécnica" --detalhe --output-dir minha_pasta
```

## Modo `--detalhe` (estrutura completa do curso)

Busca o curso pelo endpoint nativo do site (com desambiguação interativa se
houver mais de um resultado) e gera numa pasta (`estrutura_<curso>/`):

- **21 CSVs** no formato dos templates de importação de estrutura de curso
  (`01-program.csv` … `22-saep-knowledge-topics.csv`), prontos para o importador;
- **course.json** com TUDO que a API retornou (inclusive o que não cabe nos
  templates: capacidades socioemocionais, competências de IA, contexto de
  trabalho, CNAE, observações de infraestrutura, saídas intermediárias).

Após gravar, a integridade é validada automaticamente (chaves naturais únicas
e toda referência cruzada entre arquivos resolvendo); problemas aparecem no
terminal e em `errors.log`.

Campos sem fonte no I.N. ficam vazios para curadoria manual: SAEP (arquivos
05, 11, 13, 20, 21, 22 saem só com cabeçalho), `bloomTaxonomy`, `difficulty`,
`deliveryMode`, pré-requisitos de UC e os pivôs 12, 15 e 16.

### Modalidades válidas para `--modalidade`

Iniciação Profissional · Qualificação Profissional · Técnico ·
Especialização Técnica · Aperfeiçoamento Profissional · Graduação · Pós-graduação

## Saída

CSV em `utf-8-sig` (abre direto no Excel) com as colunas:

`area_id, area, eixo, versao, modalidade, curso, carga_horaria, nivel_modalidade, cbo, cbo_descricao`

## Como funciona a extração

O login é feito via navegador (Playwright) no SSO. Para os dados, em vez de
raspar o DOM (tabs, tabelas, tooltips), o scraper consome a **API JSON**
que a própria SPA usa (`api.in.senai.br`), autenticada pelos cookies da
sessão — mais robusto e mais leve para o servidor:

- `GET /areas?versionId={v}` — todas as áreas e contagens por modalidade
- `GET /areas/{area_id}?versionId={v}` — nome, eixo tecnológico e versão da área
- `GET /courses/areaVersion/{id}` — todos os cursos da área, já com CBO + descrição

Observações:

- `--curso` varre todas as áreas e filtra localmente pelo nome.
- Se a sessão expirar no meio da varredura (HTTP 401), o login é refeito
  automaticamente e a chamada é repetida.
- Alguns cursos não possuem CBO — as colunas `cbo`/`cbo_descricao` ficam vazias.

## Estrutura do projeto

```
senai_scraper/
├── cli.py        # interface de linha de comando (typer)
├── auth.py       # login SSO + sessão persistente (session.json)
├── scraper.py    # extração de áreas/modalidades/cursos
├── export.py     # gravação do CSV
└── constants.py  # URLs, modalidades, colunas, timeouts
```

## Solução de problemas

- **Login falha**: rode com `--no-headless`, observe o formulário do SSO e
  ajuste os seletores no topo de `senai_scraper/auth.py`
  (`EMAIL_SELECTOR`, `PASSWORD_SELECTOR`, `SUBMIT_SELECTOR`).
- **Sessão inválida em loop**: apague `session.json` e refaça o login.
- **Erros durante a extração**: detalhes ficam em `errors.log`.
