# Dashboard de Atestados

Projeto inicial para transformar o arquivo Excel de atestados em um dashboard web leve, auditavel e sem dependencia externa no MVP.

## Como rodar

1. Gerar os dados a partir do Excel:

```powershell
npm run import
```

2. Subir o dashboard local:

```powershell
npm run dev
```

3. Abrir no navegador:

```text
http://localhost:4173
```

## Como rodar a aplicacao profissional local

O backend inicial usa Python + SQLite, sem dependencias externas. Ele adiciona autenticacao, banco de dados e historico de importacoes.

1. Inicializar o banco:

```powershell
npm run init-db
```

2. Subir a aplicacao com backend:

```powershell
npm run server
```

3. Abrir no navegador:

```text
http://127.0.0.1:8000
```

Credencial local inicial:

```text
usuario: admin
senha: admin2026
```

Para ambientes reais, defina `DASH_ADMIN_USER` e `DASH_ADMIN_PASSWORD` antes da primeira inicializacao do banco.

## Publicacao demonstrativa

Para evitar exposicao de dados sensiveis, o arquivo real `public/data/dashboard-data.json` fica ignorado no Git. Para apresentacoes publicas, gere a base demonstrativa:

```powershell
npm run demo
```

O workflow de GitHub Pages publica `public/` usando `public/data/dashboard-data.demo.json` como `dashboard-data.json`.

## Estrutura

- `scripts/import_excel.py`: leitor OOXML do arquivo `.xlsx`, sem bibliotecas externas.
- `server/app.py`: backend HTTP com SQLite, sessao autenticada e historico de importacoes.
- `public/data/dashboard-data.json`: base normalizada consumida pelo dashboard.
- `public/index.html`: aplicacao web.
- `public/app.js`: filtros, agregacoes, tabelas e graficos.
- `public/styles.css`: layout visual do dashboard.
- `docs/data-dictionary.md`: dicionario inicial dos campos e regras.

## Validacoes do MVP

O importador confere a tabela principal `Tabela324` contra a linha total do Excel:

- quantidade real de registros;
- soma de `Total no mes`;
- soma de `Atestados`;
- periodo minimo e maximo;
- campos obrigatorios vazios.

Tambem importa a tabela `Tabela328` da aba `AFASTADOS`.

## Funcionalidades profissionais iniciadas

- Login com sessao HTTP-only.
- Perfil unico inicial: `admin`.
- Banco SQLite local ignorado pelo Git.
- Endpoint autenticado para importar o Excel atual.
- Historico das importacoes com status, totais e hash do arquivo.
- Dashboard usando API autenticada quando o backend esta ativo e JSON demonstrativo quando publicado estaticamente.

## Proximo ciclo recomendado

- Trocar SQLite por PostgreSQL quando houver ambiente servidor definido.
- Criar perfis de acesso por area e nivel de permissao.
- Adicionar upload seguro de novos arquivos Excel pela interface.
- Normalizar cadastro de colaboradores, medicos e capitulos CID.
- Adicionar logs de auditoria por visualizacao, importacao e exportacao.
