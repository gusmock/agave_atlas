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
