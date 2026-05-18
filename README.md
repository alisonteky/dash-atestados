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

## Publicacao demonstrativa

Para evitar exposicao de dados sensiveis, o arquivo real `public/data/dashboard-data.json` fica ignorado no Git. Para apresentacoes publicas, gere a base demonstrativa:

```powershell
npm run demo
```

O workflow de GitHub Pages publica `public/` usando `public/data/dashboard-data.demo.json` como `dashboard-data.json`.

## Estrutura

- `scripts/import_excel.py`: leitor OOXML do arquivo `.xlsx`, sem bibliotecas externas.
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

## Proximo ciclo recomendado

- Criar banco PostgreSQL.
- Transformar o importador em endpoint autenticado.
- Adicionar login e perfis de acesso.
- Salvar historico de importacoes.
- Normalizar cadastro de colaboradores, medicos e capitulos CID.
