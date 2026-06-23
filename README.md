# Atlas e Observatorio do Agave

Aplicacao web para explorar documentos cientificos e tecnologicos sobre agave,
etanol, biomassa e rotas associadas. O projeto migra a planilha-base para SQLite,
apresenta os resultados em formato didatico e permite ingestao autenticada de
novos documentos com extracao via Gemini.

## Decisao tecnica

Este projeto usa **Python no backend + HTML/CSS/JS no frontend**.

Motivo: o sistema precisa de login, upload de documentos, chave da API Gemini no
servidor, renomeacao e armazenamento de arquivos, e uma base SQL local. Um app
puramente HTML+JS exporia a chave Gemini e nao teria um local seguro para salvar
arquivos e banco de dados. O frontend continua em HTML+JS para manter a interface
leve, didatica e facil de publicar.

## Estrutura

```text
app/
  main.py              Aplicacao Starlette/ASGI
  db.py                Schema e consultas SQLite
  importer.py          Migracao da planilha para SQL
  gemini.py            Cliente REST Gemini
  extractors.py        Extracao local de texto quando possivel
  templates/index.html Interface principal
  static/              CSS, JS e imagens
scripts/
  import_spreadsheet.py Importa a planilha .xlsm/.xlsx/.csv
  init_db.py            Cria schema e usuario admin
data/
  db/agave_obs.sqlite3 Banco SQLite
  uploads/documents/   Documentos inseridos e renomeados
```

## Configuracao

1. Crie um ambiente virtual e instale as dependencias:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Copie `.env.example` para `.env` e ajuste:

```bash
cp .env.example .env
```

3. Importe a planilha:

```bash
python scripts/import_spreadsheet.py "/Users/gusmock/Downloads/Prospecção etanol_base de dados.xlsm"
```

4. Rode o servidor:

```bash
uvicorn app.main:app --reload --port 8018
```

Abra `http://127.0.0.1:8018`.

## Publicar em sandbox aberto no Render

O projeto inclui `render.yaml` para publicar como Render Web Service com runtime
Python e disco persistente.

1. Suba este diretorio para um repositorio GitHub.
2. No Render, crie um Blueprint a partir do repositorio.
3. Preencha os secrets solicitados:

```text
AGAVE_ADMIN_PASSWORD
GEMINI_API_KEY
```

4. Confirme que o disco persistente foi montado em `/var/data`.
5. Apos o deploy, valide:

```text
https://SEU-SERVICO.onrender.com/health
```

Em producao, o banco e os uploads usam:

```text
AGAVE_DB_PATH=/var/data/db/agave_obs.sqlite3
AGAVE_UPLOAD_DIR=/var/data/uploads/documents
```

No primeiro deploy, `scripts/start_render.sh` copia o SQLite inicial para o disco
persistente somente se ainda nao existir banco em `/var/data/db`. Depois disso,
o banco persistente nao e sobrescrito nos proximos deploys.

Antes de publicar, gere uma nova chave Gemini e substitua no painel do Render,
pois a chave anterior foi compartilhada no chat durante o desenvolvimento.

## Login local

O usuario inicial vem de `.env`:

```text
AGAVE_ADMIN_USER=admin
AGAVE_ADMIN_PASSWORD=agave123
```

Troque esses valores antes de usar em rede. A senha e armazenada no SQLite com
PBKDF2-HMAC-SHA256.

## Gemini

Defina `GEMINI_API_KEY` em `.env`. A aplicacao envia o documento e/ou texto
extraido ao Gemini e espera JSON com campos como titulo, resumo, tipo, palavras
chave, titulares, autores, datas, tecnologias e evidencias. O documento inserido
e renomeado de forma estavel e salvo em `data/uploads/documents/`.

Sem `GEMINI_API_KEY`, o upload ainda salva o arquivo, mas marca a extracao como
pendente/erro.
