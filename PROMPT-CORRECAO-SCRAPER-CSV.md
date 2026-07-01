# Correção e enriquecimento do scraper de estrutura de curso (CSV)

> **Para:** time de scraper
> **Objetivo:** (1) destravar a validação do backend e (2) fazer o scraper **classificar e extrair o
> máximo de informação possível** do plano de curso SENAI para dentro dos CSVs.
> **Caso de referência:** curso *Técnico em Manutenção e Suporte em Informática* — pacote em
> `estrutura_tecnico-em-manutencao-e-suporte-em-informatica/`.

---

## 1. Contexto: por que o pacote está sendo reprovado

O sistema recebe os 21 CSVs no endpoint `POST /api/course-structure-imports/validate`. A estrutura de
arquivos, os cabeçalhos e as referências entre arquivos **estão corretos** — não é preciso mexer nisso.

O problema é o **conteúdo**: 4 colunas de *enum* obrigatórias estão saindo **100% vazias**. O backend trata
célula de enum vazia como valor inválido (`INVALID_ENUM_VALUE`) e **reprova o pacote inteiro** — basta uma
célula para `valid` virar `false`.

Aproveitando a correção, o pacote também está deixando muitos campos opcionais vazios e **9 arquivos de
relação/SAEP apenas com cabeçalho**. Queremos enriquecer isso ao máximo.

### Como o backend valida (contrato)

- **Enum**: o valor da célula tem que ser **exatamente** um dos valores permitidos — MAIÚSCULAS, em inglês,
  sem acento, sem espaços, *case-sensitive*. Vazio é inválido.
- **Referência** (`INVALID_REFERENCE`): toda `key` citada num arquivo de relação precisa existir no arquivo
  de origem (ex.: um `subfunctionKey` em `12-unit-subfunctions.csv` tem que existir em `07-subfunctions.csv`).
- **Inteiro** (`INVALID_INTEGER`): colunas `order`, `minTotalHours`, `workloadHours`, `quantity`, `year`.
- **Chave única** (`DUPLICATED_KEY`): colunas `*Key` não podem repetir dentro do mesmo arquivo.
- **URL** (`INVALID_URL`): se `19-learning-resources.csv > url` for preenchido, precisa ser `http`/`https` válido.
- Resposta de sucesso: `{ "valid": true, "errors": [] }`. Cada erro vem com `file`, `row` e `field`
  apontando exatamente a célula problemática.

---

## 2. PRIORIDADE 1 — bloqueia a importação (corrigir já)

As 4 colunas de enum abaixo estão **100% vazias** e precisam ser preenchidas em **todas** as linhas.

### 2.1 `01-program.csv > deliveryMode` (0/1)

Valores válidos: `IN_PERSON` · `ONLINE` · `HYBRID`.
Curso presencial → `IN_PERSON`.

```diff
- ...,1000,
+ ...,1000,IN_PERSON
```

### 2.2 `04-course-units.csv > difficulty` (0/16)

Valores válidos: `BEGINNER` · `INTERMEDIATE` · `ADVANCED`.
Classificar pelo módulo da unidade:

| Tipo de módulo (`03-modules.csv > type`) | `difficulty` |
|---|---|
| `INDUSTRY_BASICS`, `INTRODUCTORY` | `BEGINNER` |
| `SPECIFIC_I` | `INTERMEDIATE` |
| `SPECIFIC_II` | `ADVANCED` |

```diff
- uc-1-introducao-a-qualidade-e-produtividade,mod-1-basico,...,16,,,"Desenvolver..."
+ uc-1-introducao-a-qualidade-e-produtividade,mod-1-basico,...,16,BEGINNER,,"Desenvolver..."
```

### 2.3 `09-capacities.csv > bloomTaxonomy` (0/180)

Valores válidos: `REMEMBER` · `UNDERSTAND` · `APPLY` · `ANALYZE` · `EVALUATE` · `CREATE`.
Classificar pelo **verbo de ação** que abre a descrição da capacidade:

| Verbo na descrição | `bloomTaxonomy` |
|---|---|
| Identificar, Listar, Nomear, Definir | `REMEMBER` |
| Reconhecer, Compreender, Descrever, Interpretar, Classificar | `UNDERSTAND` |
| Aplicar, Executar, Utilizar, Realizar, Operar, Instalar, Configurar | `APPLY` |
| Analisar, Diferenciar, Examinar, Diagnosticar | `ANALYZE` |
| Avaliar, Verificar, Selecionar, Justificar, Testar | `EVALUATE` |
| Elaborar, Criar, Desenvolver, Projetar, Planejar, Montar | `CREATE` |

```diff
- cap-1-b1,uc-1-...,BASIC,Identificar as ferramentas da qualidade...,
+ cap-1-b1,uc-1-...,BASIC,Identificar as ferramentas da qualidade...,REMEMBER
- cap-1-b2,uc-1-...,BASIC,Reconhecer as etapas da filosofia Lean...,
+ cap-1-b2,uc-1-...,BASIC,Reconhecer as etapas da filosofia Lean...,UNDERSTAND
```

### 2.4 `19-learning-resources.csv > type` (0/9)

Valores válidos: `FILE` · `LINK` · `EMBED`.

| Situação | `type` |
|---|---|
| tem `url` preenchida | `LINK` |
| é arquivo / tem `fileKey` | `FILE` |
| conteúdo embutido (vídeo/iframe) | `EMBED` |
| nada disso (default) | `LINK` |

```diff
- res-2-1,env-2-1,,"Livros, apostilas, vídeos ilustrativos...",,,,
+ res-2-1,env-2-1,LINK,"Livros, apostilas, vídeos ilustrativos...",,,,
```

> ⚠️ **Não mexer** nos enums que já estão corretos: `03-modules.csv > type` e `09-capacities.csv > type`.

---

## 3. PRIORIDADE 2 — enriquecer colunas opcionais vazias

Preencher **quando a informação existir na fonte**. Se não existir, pode deixar vazio (são opcionais) —
mas **não inventar** dados factuais.

| Arquivo > coluna | Hoje | O que extrair |
|---|---|---|
| `01-program.csv > shortName` | 0/1 | sigla/abreviação do curso, se houver |
| `01-program.csv > techSegment` | 0/1 | segmento tecnológico |
| `04-course-units.csv > summary` | 0/16 | ementa/resumo da unidade (o `objectives` já vem preenchido — **não repetir** os objetivos aqui) |
| `17-learning-environments.csv > description` | 0/41 | descrição do ambiente de aprendizagem |
| `18-equipment-items.csv > quantity` | 0/27 | quantidade do equipamento, se o plano informar número (inteiro) |
| `19-learning-resources.csv > url / author / year / fileKey` | 0/9 | dados da referência bibliográfica/recurso (`year` inteiro; `url` http/https válida) |

---

## 4. PRIORIDADE 3 — popular os arquivos de relação/SAEP (hoje só com cabeçalho)

Este é o ponto mais importante do "extrair o máximo". O **perfil ocupacional** (funções, subfunções e
padrões de desempenho — arquivos `06`, `07`, `08`) já foi extraído, mas a **matriz SAEP** e os
**cruzamentos com o currículo** não. Quase tudo isso está na *matriz curricular* / *perfil profissional*
do plano de curso e deve ser extraível.

Se uma relação realmente não existir na fonte, pode ficar vazia — mas **tentar ao máximo**.

| Arquivo | Representa | Colunas |
|---|---|---|
| `05-capacity-saep.csv` | capacidades SAEP do curso | `capacitySaepKey`, `programKey`, `order` (int), `description`, `type` (`TECHNICAL`\|`BASIC`), `bloomTaxonomy` (lista da seção 2.3) |
| `22-saep-knowledge-topics.csv` | conhecimentos de cada capacidade SAEP | `saepKnowledgeTopicKey`, `capacitySaepKey`, `order` (int), `description` (**único no arquivo**) |
| `12-unit-subfunctions.csv` | liga unidade curricular ↔ subfunção | `unitKey`, `subfunctionKey` |
| `16-unit-prerequisites.csv` | pré-requisito entre unidades | `unitKey`, `prerequisiteUnitKey` |
| `11-unit-capacity-saep.csv` | unidade ↔ capacidade SAEP | `unitKey`, `capacitySaepKey` |
| `13-capacity-saep-capacities.csv` | capacidade SAEP ↔ capacidade (arquivo 09) | `capacitySaepKey`, `capacityKey` |
| `15-capacity-performance-standards.csv` | capacidade ↔ padrão de desempenho | `capacityKey`, `performanceStandardKey` |
| `20-capacity-saep-functions.csv` | capacidade SAEP ↔ função | `capacitySaepKey`, `functionKey` |
| `21-capacity-saep-subfunctions.csv` | capacidade SAEP ↔ subfunção | `capacitySaepKey`, `subfunctionKey` |

**Exemplo — `05-capacity-saep.csv`:**
```csv
capacitySaepKey,programKey,order,description,type,bloomTaxonomy
csaep-1,tecnico-em-manutencao-e-suporte-em-informatica-2025,1,"Instalar hardware e software de computadores conforme normas técnicas",TECHNICAL,APPLY
```

**Exemplo — `12-unit-subfunctions.csv`** (todo `unitKey` precisa existir em `04`, todo `subfunctionKey` em `07`):
```csv
unitKey,subfunctionKey
uc-1-introducao-a-qualidade-e-produtividade,subfunc-1-1
```

> ⚠️ **Atenção a referências:** toda `key` citada num arquivo de relação precisa existir no arquivo de
> origem, senão dá `INVALID_REFERENCE`. E **se popular `05-capacity-saep.csv`, todas as colunas dele passam
> a ser obrigatórias** (inclusive `type` e `bloomTaxonomy`).

---

## 5. Regras gerais (checklist final)

- [ ] Nenhuma célula de **enum** vazia; valores exatamente como listados (MAIÚSCULAS, EN, sem acento, *case-sensitive*).
- [ ] `order` e numéricos (`minTotalHours`, `workloadHours`, `quantity`, `year`) são **inteiros**.
- [ ] Colunas `*Key` **não repetem** dentro do mesmo arquivo.
- [ ] Toda `key` de relação **existe** no arquivo de origem (sem `INVALID_REFERENCE`).
- [ ] Campos opcionais podem ficar vazios se a fonte não tiver — **não inventar** `cboCode`, `author`,
      `year`, `url`. Para **classificações** (`difficulty`, `bloomTaxonomy`, `type` de recurso) **pode inferir**.
- [ ] `campusKey` pode continuar como `selected-campus` — o backend ignora e usa o campus do formulário.
- [ ] Não alterar `03-modules.csv > type` nem `09-capacities.csv > type` (já corretos).

---

## 6. Como validar a correção

Reenviar o pacote para `POST /api/course-structure-imports/validate`.

- **Sucesso:** `{ "valid": true, "errors": [] }`.
- **Erro:** cada item de `errors` traz `file`, `row` e `field` apontando a célula exata — corrigir e reenviar.

### Referência rápida de enums

```
deliveryMode (01)     = IN_PERSON | ONLINE | HYBRID
difficulty   (04)     = BEGINNER | INTERMEDIATE | ADVANCED
bloomTaxonomy (09,05) = REMEMBER | UNDERSTAND | APPLY | ANALYZE | EVALUATE | CREATE
type (19 resource)    = FILE | LINK | EMBED
type (03 module)      = INTRODUCTORY | INDUSTRY_BASICS | SPECIFIC_I | SPECIFIC_II | OTHER   (já ok)
type (09 capacity)    = TECHNICAL | BASIC | SOCIOEMOTIONAL                                  (já ok)
type (05 capacitySaep)= TECHNICAL | BASIC
```
