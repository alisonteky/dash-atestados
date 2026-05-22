# Dashboard de Atestados

Projeto inicial para transformar o arquivo Excel de atestados em um dashboard web leve, auditavel e sem dependencia externa no MVP.

## Como rodar

1. Gerar os dados a partir do Excel:

```powershell
npm run import
```

Por padrão, o importador lê duas planilhas na pasta `mvp`:

- `ATESTADOS OPERAÇÃO 2026 cópia.xlsx`: base operacional de motoristas, cobradores e afastados.
- `Planilha Monitoramento dos Atestados Médicos .xlsx`: base de manutenção e administrativo, limitada ao histórico de 2025 e 2026. Linhas de motoristas/cobradores nesta planilha são ignoradas para evitar dupla origem.

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

A planilha geral de funcionários não possui tabelas formais do Excel; ela é lida por abas mensais de 2025 e 2026. Cada linha de manutenção/administrativo recebe `origem = Empresa`. Motoristas e cobradores são mantidos exclusivamente na origem `Operação`, e a visão `Consolidado` ainda remove sobreposições por `chapa + dataInicial + dataFinal` como proteção adicional.

## Funcionalidades profissionais iniciadas

- Login com sessao HTTP-only.
- Perfil unico inicial: `admin`.
- Banco SQLite local ignorado pelo Git.
- Estrutura profissional de usuarios, perfis, permissoes, lotes, funcionarios, medicos, CID, atestados, afastamentos, validacoes, erros e auditoria.
- Upload autenticado das duas planilhas em lote.
- Pre-validacao antes de gravar os registros relacionais.
- Confirmacao manual da importacao.
- Versionamento por lote.
- Rollback logico de lotes confirmados.
- Armazenamento privado dos arquivos Excel importados em `storage/imports/`.
- Historico das importacoes com status, totais, versao e hash dos arquivos.
- Logs de auditoria por usuario para login, visualizacao, importacao, confirmacao e rollback.
- Dashboard usando API autenticada quando o backend esta ativo e JSON demonstrativo quando publicado estaticamente.
- Schema PostgreSQL inicial em `server/schema.postgres.sql`.
- Conexao PostgreSQL real via `DATABASE_URL`, mantendo SQLite apenas como fallback local sem dependencias.

## Fluxo profissional de importacao

1. Entrar com o usuario administrador.
2. Abrir `Importar Excel`.
3. Selecionar a planilha de Operacao e a planilha Empresa.
4. Executar `Pre-validar`.
5. Revisar totais, avisos e divergencias.
6. Confirmar a importacao.
7. Consultar o historico ou reverter um lote confirmado quando necessario.

## Implantacao sem custo

A recomendacao sem mensalidade e uma VM Oracle Cloud Always Free com backend, PostgreSQL e armazenamento privado no mesmo servidor. A alternativa Supabase Free pode servir para homologacao, mas possui limites de banco, storage, pausa por inatividade e backup.

Detalhes em `docs/deployment-free.md`.

## PostgreSQL e deploy

Para rodar com PostgreSQL real, defina `DATABASE_URL`:

```powershell
$env:DATABASE_URL="postgresql://dash_user:SENHA@localhost:5432/dash_atestados"
$env:DASH_ADMIN_PASSWORD="SENHA_ADMIN_FORTE"
$env:DASH_COOKIE_SECURE="1"
python server/app.py --init-db
python server/app.py --host 0.0.0.0 --port 8000
```

Tambem ha `Dockerfile`, `requirements.txt` e `deploy/docker-compose.yml` para subir app + PostgreSQL em uma VM.

Detalhes em `docs/postgres-deploy.md`.

## Proximo ciclo recomendado

- Testar o deploy em uma VM gratuita com `deploy/docker-compose.yml`.
- Criar perfis de acesso por area e nivel de permissao alem do admin.
- Adicionar criptografia dos arquivos importados em repouso.
- Agendar a rotina `deploy/backup-postgres.sh` e testar `deploy/restore-postgres.sh`.
- Revisar politicas internas de LGPD antes de inserir dados reais em producao.
