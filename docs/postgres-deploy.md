# Deploy com PostgreSQL

## Modo local com SQLite

Sem `DATABASE_URL`, o backend usa SQLite local para desenvolvimento:

```powershell
python server/app.py --init-db
python server/app.py --port 8000
```

## Modo produção com PostgreSQL

Com `DATABASE_URL`, o backend inicializa o schema PostgreSQL em `server/schema.postgres.sql` e usa o banco real:

```bash
export DATABASE_URL="postgresql://dash_user:SENHA@localhost:5432/dash_atestados"
export DASH_ADMIN_USER="admin"
export DASH_ADMIN_PASSWORD="SENHA_ADMIN_FORTE"
export DASH_COOKIE_SECURE=1
python server/app.py --init-db
python server/app.py --host 0.0.0.0 --port 8000
```

## Deploy com Docker Compose

No servidor:

```bash
git clone https://github.com/alisonteky/dash-atestados.git
cd dash-atestados
git switch professional-backend
cp deploy/.env.example deploy/.env
```

Editar `deploy/.env` e trocar todas as senhas.

Subir:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
```

Ver logs:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs -f app
```

Backup PostgreSQL:

```bash
sh deploy/backup-postgres.sh
```

Restore PostgreSQL:

```bash
sh deploy/restore-postgres.sh backups/arquivo.sql
```

## Produção sem custo

Para custo zero, a recomendação segue sendo:

1. Oracle Cloud Always Free VM.
2. Docker Compose com `app` + `postgres`.
3. HTTPS por Caddy/Nginx.
4. Backup criptografado fora da VM.
5. Acesso SSH restrito.

## Checklist LGPD antes de dados reais

- trocar senha padrão;
- habilitar HTTPS e `DASH_COOKIE_SECURE=1`;
- restringir firewall;
- manter `storage/` fora da pasta pública;
- testar backup e restore;
- validar quem pode exportar CSV;
- revisar logs de auditoria;
- formalizar política de retenção dos arquivos Excel.
