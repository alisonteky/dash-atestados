from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sqlite3
import sys
import traceback
import uuid
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
STORAGE_DIR = ROOT / "storage"
DB_PATH = STORAGE_DIR / "dash-atestados.sqlite3"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
PRIVATE_IMPORT_DIR = STORAGE_DIR / "imports"
DEFAULT_SOURCE = ROOT.parent / "ATESTADOS OPERAÇÃO 2026 cópia.xlsx"
DEFAULT_COMPANY_SOURCE = ROOT.parent / "Planilha Monitoramento dos Atestados Médicos .xlsx"
SESSION_COOKIE = "dash_session"
SESSION_DAYS = 1
PASSWORD_ITERATIONS = 260_000
MAX_JSON_BYTES = 5_000_000
MAX_UPLOAD_BYTES = 120 * 1024 * 1024
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin2026"

sys.path.insert(0, str(ROOT))
from scripts.import_excel import build_payload  # noqa: E402

if USE_POSTGRES:
    try:
        import psycopg  # type: ignore[import-not-found]
        from psycopg.rows import dict_row  # type: ignore[import-not-found]
        from psycopg.types.json import Jsonb  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on production dependency
        raise RuntimeError("Instale as dependencias de producao: pip install -r requirements.txt") from exc


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def translate_sql(sql: str) -> str:
    if not USE_POSTGRES:
        return sql
    return sql.replace("?", "%s")


class DatabaseConnection:
    def __init__(self) -> None:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        if USE_POSTGRES:
            self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)  # type: ignore[name-defined]
        else:
            self.conn = sqlite3.connect(DB_PATH)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")

    def __enter__(self) -> "DatabaseConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        return self.conn.execute(translate_sql(sql), params)

    def executescript(self, script: str) -> None:
        if not USE_POSTGRES:
            self.conn.executescript(script)
            return
        script = (ROOT / "server" / "schema.postgres.sql").read_text(encoding="utf-8")
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self.execute(statement)


def connect() -> DatabaseConnection:
    return DatabaseConnection()


def last_insert_id(conn: DatabaseConnection, cursor: Any) -> int:
    if USE_POSTGRES:
        row = conn.execute("SELECT lastval() AS id").fetchone()
        return int(row["id"])
    return int(cursor.lastrowid)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(base64.b64encode(digest).decode("ascii"), expected)
    except (ValueError, TypeError):
        return False


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS role_permissions (
                role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
                PRIMARY KEY (role_id, permission_id)
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                records_atestados INTEGER NOT NULL DEFAULT 0,
                records_afastados INTEGER NOT NULL DEFAULT 0,
                total_dias INTEGER NOT NULL DEFAULT 0,
                total_atestados INTEGER NOT NULL DEFAULT 0,
                validation_json TEXT NOT NULL,
                payload_json TEXT,
                error_message TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL,
                source_file TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                operation_file_path TEXT NOT NULL,
                company_file_path TEXT NOT NULL,
                records_atestados INTEGER NOT NULL DEFAULT 0,
                records_funcionarios INTEGER NOT NULL DEFAULT 0,
                records_afastados INTEGER NOT NULL DEFAULT 0,
                total_dias INTEGER NOT NULL DEFAULT 0,
                total_atestados INTEGER NOT NULL DEFAULT 0,
                validation_json TEXT NOT NULL,
                payload_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                prevalidated_at TEXT,
                committed_at TEXT,
                rolled_back_at TEXT,
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS imported_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
                file_role TEXT NOT NULL,
                original_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapa TEXT NOT NULL UNIQUE,
                nome TEXT NOT NULL,
                funcao TEXT NOT NULL,
                origem_preferencial TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                crm TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE (nome, crm)
            );

            CREATE TABLE IF NOT EXISTS cid_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                capitulo TEXT NOT NULL,
                subcategoria TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (capitulo, subcategoria)
            );

            CREATE TABLE IF NOT EXISTS certificates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
                employee_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
                doctor_id INTEGER REFERENCES doctors(id) ON DELETE SET NULL,
                cid_id INTEGER REFERENCES cid_codes(id) ON DELETE SET NULL,
                origem TEXT NOT NULL,
                source_sheet TEXT NOT NULL,
                excel_row INTEGER NOT NULL,
                data_recebimento TEXT,
                periodo TEXT NOT NULL,
                data_inicial TEXT,
                data_final TEXT,
                total_no_mes INTEGER NOT NULL,
                tipo_duracao TEXT NOT NULL,
                ano INTEGER,
                mes TEXT NOT NULL,
                atestados INTEGER NOT NULL,
                afastamento_inss TEXT NOT NULL DEFAULT '',
                observacao_gestores TEXT NOT NULL DEFAULT '',
                tratativa_seguranca TEXT NOT NULL DEFAULT '',
                tratativa_diretoria TEXT NOT NULL DEFAULT '',
                tratativa_jonilton TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS absences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
                employee_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
                doctor_id INTEGER REFERENCES doctors(id) ON DELETE SET NULL,
                cid_id INTEGER REFERENCES cid_codes(id) ON DELETE SET NULL,
                origem TEXT NOT NULL,
                source_sheet TEXT NOT NULL,
                excel_row INTEGER NOT NULL,
                colaborador TEXT NOT NULL,
                periodo TEXT NOT NULL,
                total INTEGER NOT NULL,
                ano INTEGER,
                mes TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS import_validations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
                scope TEXT NOT NULL,
                status TEXT NOT NULL,
                validation_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS import_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER REFERENCES import_batches(id) ON DELETE CASCADE,
                severity TEXT NOT NULL,
                scope TEXT NOT NULL,
                row_ref TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL DEFAULT '',
                ip_address TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        ensure_user_columns(conn)
        seed_roles_permissions(conn)
        ensure_admin_user(conn)


def table_columns(conn: DatabaseConnection, table: str) -> set[str]:
    if USE_POSTGRES:
        rows = conn.execute(
            """
            SELECT column_name AS name
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = ?
            """,
            (table,),
        ).fetchall()
        return {row["name"] for row in rows}
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def ensure_column(conn: DatabaseConnection, table: str, column: str, ddl: str) -> None:
    if column not in table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def ensure_user_columns(conn: DatabaseConnection) -> None:
    if USE_POSTGRES:
        return
    ensure_column(conn, "users", "email", "email TEXT")
    ensure_column(conn, "users", "role_id", "role_id INTEGER REFERENCES roles(id) ON DELETE SET NULL")
    ensure_column(conn, "users", "is_active", "is_active INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "users", "last_login_at", "last_login_at TEXT")


def seed_roles_permissions(conn: DatabaseConnection) -> None:
    now = iso_now()
    conn.execute(
        "INSERT INTO roles (name, description, created_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
        ("admin", "Administrador com acesso total", now),
    )
    permissions = [
        ("dashboard:view", "Visualizar dashboard e dados sensíveis"),
        ("imports:prevalidate", "Enviar planilhas e executar pré-validação"),
        ("imports:commit", "Confirmar lote de importação"),
        ("imports:rollback", "Reverter lote importado"),
        ("imports:history", "Consultar histórico de importações"),
        ("audit:view", "Consultar logs de auditoria"),
        ("users:manage", "Gerenciar usuários e permissões"),
    ]
    for code, description in permissions:
        conn.execute(
            "INSERT INTO permissions (code, description) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (code, description),
        )

    role = conn.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()
    if not role:
        return
    permission_rows = conn.execute("SELECT id FROM permissions").fetchall()
    for permission in permission_rows:
        conn.execute(
            "INSERT INTO role_permissions (role_id, permission_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (role["id"], permission["id"]),
        )


def ensure_admin_user(conn: DatabaseConnection) -> None:
    existing = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    admin_role = conn.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()
    if existing:
        if admin_role:
            conn.execute("UPDATE users SET role_id = COALESCE(role_id, ?) WHERE role = 'admin'", (admin_role["id"],))
        return

    username = os.environ.get("DASH_ADMIN_USER", DEFAULT_ADMIN_USER)
    password = os.environ.get("DASH_ADMIN_PASSWORD")
    if USE_POSTGRES and not password:
        raise RuntimeError("Defina DASH_ADMIN_PASSWORD antes de inicializar o banco PostgreSQL.")
    password = password or DEFAULT_ADMIN_PASSWORD
    conn.execute(
        "INSERT INTO users (username, password_hash, role, role_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (username, hash_password(password), "admin", admin_role["id"] if admin_role else None, iso_now()),
    )


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def db_json(value: Any) -> Any:
    if USE_POSTGRES:
        return Jsonb(value)  # type: ignore[name-defined]
    return json.dumps(value, ensure_ascii=False)


def read_json(value: Any, fallback: Any | None = None) -> Any:
    if value in (None, ""):
        return {} if fallback is None else fallback
    if isinstance(value, str):
        return json.loads(value)
    return value


def db_date(value: Any) -> Any:
    return value or None if USE_POSTGRES else value


def get_json_body(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length == 0:
        return {}
    if length > MAX_JSON_BYTES:
        raise ValueError("Payload muito grande.")
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def parse_multipart_files(handler: SimpleHTTPRequestHandler) -> dict[str, dict[str, Any]]:
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("Envie as planilhas como multipart/form-data.")

    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        raise ValueError("Nenhum arquivo recebido.")
    if length > MAX_UPLOAD_BYTES:
        raise ValueError("Upload maior que o limite permitido.")

    raw = handler.rfile.read(length)
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw
    )
    files: dict[str, dict[str, Any]] = {}
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        if not name or not filename:
            continue
        content = part.get_payload(decode=True) or b""
        if not content:
            raise ValueError(f"Arquivo vazio: {filename}")
        if not filename.lower().endswith(".xlsx"):
            raise ValueError(f"Arquivo precisa ser .xlsx: {filename}")
        files[name] = {
            "filename": Path(filename).name,
            "content": content,
            "size": len(content),
            "sha256": bytes_hash(content),
        }
    return files


def next_import_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS version FROM import_batches").fetchone()
    return int(row["version"])


def row_to_import(row: sqlite3.Row) -> dict[str, Any]:
    source_files = [source.strip() for source in row["source_file"].split("|") if source.strip()]
    source_name = " + ".join(Path(source).name for source in source_files) if source_files else Path(row["source_file"]).name
    return {
        "id": row["id"],
        "sourceFile": row["source_file"],
        "sourceName": source_name,
        "sourceHash": row["source_hash"],
        "status": row["status"],
        "recordsAtestados": row["records_atestados"],
        "recordsAfastados": row["records_afastados"],
        "totalDias": row["total_dias"],
        "totalAtestados": row["total_atestados"],
        "validation": read_json(row["validation_json"]),
        "errorMessage": row["error_message"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "userId": row["user_id"],
    }


def row_to_batch(row: sqlite3.Row) -> dict[str, Any]:
    source_files = [source.strip() for source in row["source_file"].split("|") if source.strip()]
    source_name = " + ".join(Path(source).name for source in source_files) if source_files else row["source_file"]
    return {
        "id": row["id"],
        "version": row["version"],
        "sourceFile": row["source_file"],
        "sourceName": source_name,
        "sourceHash": row["source_hash"],
        "status": row["status"],
        "recordsAtestados": row["records_atestados"],
        "recordsFuncionarios": row["records_funcionarios"],
        "recordsAfastados": row["records_afastados"],
        "totalDias": row["total_dias"],
        "totalAtestados": row["total_atestados"],
        "validation": read_json(row["validation_json"]),
        "errorMessage": row["error_message"],
        "startedAt": row["created_at"],
        "finishedAt": row["committed_at"] or row["prevalidated_at"] or row["rolled_back_at"] or row["created_at"],
        "prevalidatedAt": row["prevalidated_at"],
        "committedAt": row["committed_at"],
        "rolledBackAt": row["rolled_back_at"],
        "userId": row["created_by"],
    }


def import_summary(payload: dict[str, Any]) -> dict[str, Any]:
    validation = payload.get("validation", {})
    operation = validation.get("atestados", {})
    company = validation.get("funcionarios", {})
    consolidated = validation.get("consolidado", {})
    warnings: list[str] = []
    errors: list[str] = []

    if operation.get("status") != "ok":
        errors.append("Validação da planilha Operação requer atenção.")
    if company.get("status") not in {"ok", "nao_importado"}:
        errors.append("Validação da planilha Empresa requer atenção.")
    if consolidated.get("duplicadosPorChapaPeriodo"):
        warnings.append(f"{consolidated['duplicadosPorChapaPeriodo']} sobreposição removida no consolidado.")
    if company.get("linhasOperacionaisIgnoradas"):
        warnings.append(
            f"{company['linhasOperacionaisIgnoradas']} linhas operacionais ignoradas na Empresa por regra de origem."
        )
    empty_fields = sum(len(rows) for rows in operation.get("camposObrigatoriosVazios", {}).values())
    if empty_fields:
        errors.append(f"{empty_fields} campos obrigatórios vazios na Operação.")
    company_alerts = company.get("alertas", {})
    if company_alerts.get("camposObrigatoriosVazios"):
        errors.append(f"{company_alerts['camposObrigatoriosVazios']} campos obrigatórios vazios na Empresa.")
    if company_alerts.get("linhasSemData"):
        warnings.append(f"{company_alerts['linhasSemData']} linhas da Empresa sem data identificável.")

    return {
        "records": {
            "operacao": payload["sourceTables"]["atestados"]["records"],
            "empresa": payload["sourceTables"]["funcionarios"]["records"],
            "afastados": payload["sourceTables"]["afastados"]["records"],
            "consolidado": payload["sourceTables"]["consolidado"]["records"],
        },
        "totals": {
            "dias": payload["aggregates"]["consolidado"]["dias"],
            "atestados": payload["aggregates"]["consolidado"]["atestados"],
        },
        "years": payload["options"]["anos"],
        "warnings": warnings,
        "errors": errors,
        "canCommit": not errors,
    }


def insert_import_validations(conn: sqlite3.Connection, batch_id: int, payload: dict[str, Any]) -> None:
    now = iso_now()
    for scope, validation in payload.get("validation", {}).items():
        if not isinstance(validation, dict):
            continue
        conn.execute(
            """
            INSERT INTO import_validations (batch_id, scope, status, validation_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (batch_id, scope, str(validation.get("status", "info")), db_json(validation), now),
        )


def insert_import_messages(conn: sqlite3.Connection, batch_id: int, summary: dict[str, Any]) -> None:
    now = iso_now()
    for message in summary["warnings"]:
        conn.execute(
            "INSERT INTO import_errors (batch_id, severity, scope, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (batch_id, "warning", "prevalidacao", message, now),
        )
    for message in summary["errors"]:
        conn.execute(
            "INSERT INTO import_errors (batch_id, severity, scope, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (batch_id, "error", "prevalidacao", message, now),
        )


def upsert_employee(conn: sqlite3.Connection, record: dict[str, Any], name_key: str = "nome") -> int | None:
    chapa = str(record.get("chapa") or "").strip()
    if not chapa:
        return None
    now = iso_now()
    conn.execute(
        """
        INSERT INTO employees (chapa, nome, funcao, origem_preferencial, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(chapa) DO UPDATE SET
            nome = excluded.nome,
            funcao = excluded.funcao,
            origem_preferencial = excluded.origem_preferencial,
            updated_at = excluded.updated_at
        """,
        (
            chapa,
            str(record.get(name_key) or record.get("colaborador") or "").strip(),
            str(record.get("funcao") or "").strip(),
            str(record.get("origem") or "").strip(),
            now,
            now,
        ),
    )
    row = conn.execute("SELECT id FROM employees WHERE chapa = ?", (chapa,)).fetchone()
    return int(row["id"]) if row else None


def upsert_doctor(conn: sqlite3.Connection, record: dict[str, Any]) -> int | None:
    name = str(record.get("medico") or "").strip()
    crm = str(record.get("crmMedico") or "").strip()
    if not name:
        return None
    now = iso_now()
    conn.execute(
        "INSERT INTO doctors (nome, crm, created_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
        (name, crm, now),
    )
    row = conn.execute("SELECT id FROM doctors WHERE nome = ? AND crm = ?", (name, crm)).fetchone()
    return int(row["id"]) if row else None


def upsert_cid(conn: sqlite3.Connection, record: dict[str, Any]) -> int | None:
    chapter = str(record.get("capituloCid") or "CID Não especificado").strip()
    subcategory = str(record.get("subcategoriaCid") or "Não especificado").strip()
    now = iso_now()
    conn.execute(
        "INSERT INTO cid_codes (capitulo, subcategoria, created_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
        (chapter, subcategory, now),
    )
    row = conn.execute("SELECT id FROM cid_codes WHERE capitulo = ? AND subcategoria = ?", (chapter, subcategory)).fetchone()
    return int(row["id"]) if row else None


def persist_payload_records(conn: sqlite3.Connection, batch_id: int, payload: dict[str, Any]) -> None:
    now = iso_now()
    for record in payload["records"].get("consolidado", []):
        employee_id = upsert_employee(conn, record)
        doctor_id = upsert_doctor(conn, record)
        cid_id = upsert_cid(conn, record)
        conn.execute(
            """
            INSERT INTO certificates (
                batch_id, employee_id, doctor_id, cid_id, origem, source_sheet, excel_row,
                data_recebimento, periodo, data_inicial, data_final, total_no_mes,
                tipo_duracao, ano, mes, atestados, afastamento_inss, observacao_gestores,
                tratativa_seguranca, tratativa_diretoria, tratativa_jonilton, raw_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                employee_id,
                doctor_id,
                cid_id,
                record.get("origem", ""),
                record.get("sourceSheet", ""),
                int(record.get("excelRow") or 0),
                db_date(record.get("dataRecebimento", "")),
                record.get("periodo", ""),
                db_date(record.get("dataInicial", "")),
                db_date(record.get("dataFinal", "")),
                int(record.get("totalNoMes") or 0),
                record.get("tipoDuracao", "dias"),
                record.get("ano"),
                record.get("mes", ""),
                int(record.get("atestados") or 0),
                record.get("afastamentoInss", ""),
                record.get("observacaoGestores", ""),
                record.get("tratativaSeguranca", ""),
                record.get("tratativaDiretoria", ""),
                record.get("tratativaJonilton", ""),
                db_json(record),
                now,
            ),
        )

    for record in payload["records"].get("afastados", []):
        employee_id = upsert_employee(conn, record, "colaborador")
        doctor_id = upsert_doctor(conn, record)
        cid_id = upsert_cid(conn, record)
        conn.execute(
            """
            INSERT INTO absences (
                batch_id, employee_id, doctor_id, cid_id, origem, source_sheet, excel_row,
                colaborador, periodo, total, ano, mes, raw_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                employee_id,
                doctor_id,
                cid_id,
                record.get("origem", ""),
                record.get("sourceSheet", "AFASTADOS"),
                int(record.get("excelRow") or 0),
                record.get("colaborador", ""),
                record.get("periodo", ""),
                int(record.get("total") or 0),
                record.get("ano"),
                record.get("mes", ""),
                db_json(record),
                now,
            ),
        )


class DashHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        super().end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.route_get(path)
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            self.send_json({"error": "Rota nao encontrada."}, HTTPStatus.NOT_FOUND)
            return
        self.route_post(path)

    def route_get(self, path: str) -> None:
        if path == "/api/health":
            self.send_json({"status": "ok", "database": "postgresql" if USE_POSTGRES else str(DB_PATH), "postgres": USE_POSTGRES})
            return

        if path == "/api/auth/me":
            user = self.current_user()
            if not user:
                self.send_json({"authenticated": False}, HTTPStatus.UNAUTHORIZED)
                return
            self.send_json({"authenticated": True, "user": self.public_user(user)})
            return

        user = self.require_user()
        if not user:
            return

        if path == "/api/dashboard":
            self.handle_dashboard()
            return
        if path == "/api/imports":
            self.handle_import_history()
            return
        if path == "/api/audit-logs":
            self.handle_audit_logs()
            return

        self.send_json({"error": "Rota nao encontrada."}, HTTPStatus.NOT_FOUND)

    def route_post(self, path: str) -> None:
        if path == "/api/auth/login":
            self.handle_login()
            return
        if path == "/api/auth/logout":
            self.handle_logout()
            return

        user = self.require_user()
        if not user:
            return

        if path == "/api/imports/prevalidate":
            self.handle_import_prevalidate(user)
            return
        if path == "/api/imports/commit":
            self.handle_import_commit(user)
            return
        if path.startswith("/api/imports/") and path.endswith("/rollback"):
            self.handle_import_rollback(user, path)
            return
        if path == "/api/imports":
            self.handle_import(user)
            return

        self.send_json({"error": "Rota nao encontrada."}, HTTPStatus.NOT_FOUND)

    def handle_dashboard(self) -> None:
        user = self.current_user()
        with connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM import_batches
                WHERE status = 'committed' AND payload_json IS NOT NULL
                ORDER BY version DESC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                row = conn.execute(
                    """
                    SELECT payload_json
                    FROM import_runs
                    WHERE status = 'ok' AND payload_json IS NOT NULL
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()
            if row and user:
                self.log_audit(conn, user, "dashboard.view", "dashboard")
        if not row:
            self.send_json({"error": "Nenhuma importacao concluida no banco."}, HTTPStatus.NOT_FOUND)
            return
        self.send_json(read_json(row["payload_json"]))

    def handle_import_history(self) -> None:
        user = self.current_user()
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM import_batches
                ORDER BY id DESC
                LIMIT 50
                """
            ).fetchall()
            if rows:
                imports = [row_to_batch(row) for row in rows]
            else:
                legacy_rows = conn.execute(
                    """
                    SELECT *
                    FROM import_runs
                    ORDER BY id DESC
                    LIMIT 50
                    """
                ).fetchall()
                imports = [row_to_import(row) for row in legacy_rows]
            if user:
                self.log_audit(conn, user, "imports.history.view", "import_batches")
        self.send_json({"imports": imports})

    def handle_import(self, user: sqlite3.Row) -> None:
        source = DEFAULT_SOURCE
        company_source = DEFAULT_COMPANY_SOURCE
        try:
            body = get_json_body(self)
            if body.get("sourcePath"):
                source = Path(str(body["sourcePath"])).expanduser().resolve()
            if body.get("companySourcePath"):
                company_source = Path(str(body["companySourcePath"])).expanduser().resolve()
            if not source.exists():
                raise FileNotFoundError(f"Arquivo Excel nao encontrado: {source}")
            if not company_source.exists():
                raise FileNotFoundError(f"Planilha geral nao encontrada: {company_source}")
            if source.suffix.lower() != ".xlsx":
                raise ValueError("A planilha de operacao precisa ser .xlsx.")
            if company_source.suffix.lower() != ".xlsx":
                raise ValueError("A planilha geral precisa ser .xlsx.")

            with connect() as conn:
                batch = self.create_prevalidated_batch(conn, user, source, company_source, "default")
                committed = self.commit_batch(conn, user, batch["batchId"])

            self.send_json(
                {
                    "status": "ok",
                    "importId": committed["batchId"],
                    "batchId": committed["batchId"],
                    "version": committed["version"],
                    "dashboard": committed["dashboard"],
                },
                HTTPStatus.CREATED,
            )
        except Exception as exc:  # noqa: BLE001
            with connect() as conn:
                self.record_import_error(conn, user, f"{source} | {company_source}", str(exc))
            traceback.print_exc()
            self.send_json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)

    def handle_import_prevalidate(self, user: sqlite3.Row) -> None:
        try:
            files = parse_multipart_files(self)
            operation = files.get("operationFile")
            company = files.get("companyFile")
            if not operation or not company:
                raise ValueError("Envie as duas planilhas: Operação e Empresa.")

            upload_group = PRIVATE_IMPORT_DIR / "staged" / uuid.uuid4().hex
            upload_group.mkdir(parents=True, exist_ok=True)
            operation_path = upload_group / "operacao.xlsx"
            company_path = upload_group / "empresa.xlsx"
            operation_path.write_bytes(operation["content"])
            company_path.write_bytes(company["content"])

            with connect() as conn:
                batch = self.create_prevalidated_batch(
                    conn,
                    user,
                    operation_path,
                    company_path,
                    "upload",
                    original_names={
                        "operation": operation["filename"],
                        "company": company["filename"],
                    },
                    upload_meta={
                        "operation": operation,
                        "company": company,
                    },
                )

            self.send_json(batch, HTTPStatus.CREATED)
        except Exception as exc:  # noqa: BLE001
            with connect() as conn:
                self.record_import_error(conn, user, "upload", str(exc))
            traceback.print_exc()
            self.send_json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)

    def handle_import_commit(self, user: sqlite3.Row) -> None:
        try:
            body = get_json_body(self)
            batch_id = int(body.get("batchId") or 0)
            if not batch_id:
                raise ValueError("Informe o lote para confirmação.")
            with connect() as conn:
                committed = self.commit_batch(conn, user, batch_id)
            self.send_json(committed)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.send_json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)

    def handle_import_rollback(self, user: sqlite3.Row, path: str) -> None:
        try:
            batch_id = int(path.strip("/").split("/")[-2])
            with connect() as conn:
                row = conn.execute("SELECT * FROM import_batches WHERE id = ?", (batch_id,)).fetchone()
                if not row:
                    raise ValueError("Lote nao encontrado.")
                if row["status"] != "committed":
                    raise ValueError("Somente lotes confirmados podem ser revertidos.")
                conn.execute(
                    "UPDATE import_batches SET status = 'rolled_back', rolled_back_at = ? WHERE id = ?",
                    (iso_now(), batch_id),
                )
                self.log_audit(conn, user, "import.rollback", "import_batch", str(batch_id), {"version": row["version"]})
            self.send_json({"status": "rolled_back", "batchId": batch_id})
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.send_json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)

    def create_prevalidated_batch(
        self,
        conn: sqlite3.Connection,
        user: sqlite3.Row,
        source: Path,
        company_source: Path,
        import_kind: str,
        original_names: dict[str, str] | None = None,
        upload_meta: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        version = next_import_version(conn)
        if import_kind == "upload":
            batch_dir = PRIVATE_IMPORT_DIR / f"batch-{version:06d}"
            batch_dir.mkdir(parents=True, exist_ok=True)
            final_operation = batch_dir / "operacao.xlsx"
            final_company = batch_dir / "empresa.xlsx"
            source.replace(final_operation)
            company_source.replace(final_company)
            source = final_operation
            company_source = final_company

        payload = build_payload(source, company_source)
        payload["metadata"]["prevalidatedBy"] = user["username"]
        payload["metadata"]["prevalidatedAt"] = iso_now()
        summary = import_summary(payload)
        source_hash = f"{file_hash(source)}:{file_hash(company_source)}"
        source_file_label = f"{source} | {company_source}"
        now = iso_now()

        cursor = conn.execute(
            """
            INSERT INTO import_batches (
                version, status, source_file, source_hash, operation_file_path, company_file_path,
                records_atestados, records_funcionarios, records_afastados, total_dias,
                total_atestados, validation_json, payload_json, error_message, created_at,
                prevalidated_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version,
                "pre_validated" if summary["canCommit"] else "blocked",
                source_file_label,
                source_hash,
                str(source),
                str(company_source),
                payload["sourceTables"]["atestados"]["records"],
                payload["sourceTables"]["funcionarios"]["records"],
                payload["sourceTables"]["afastados"]["records"],
                payload["aggregates"]["consolidado"]["dias"],
                payload["aggregates"]["consolidado"]["atestados"],
                db_json(payload["validation"]),
                db_json(payload),
                "\n".join(summary["errors"]) or None,
                now,
                now,
                user["id"],
            ),
        )
        batch_id = last_insert_id(conn, cursor)
        insert_import_validations(conn, batch_id, payload)
        insert_import_messages(conn, batch_id, summary)
        self.register_imported_file(conn, batch_id, "operation", source, original_names, upload_meta)
        self.register_imported_file(conn, batch_id, "company", company_source, original_names, upload_meta)
        self.log_audit(conn, user, "import.prevalidate", "import_batch", str(batch_id), {"version": version, "kind": import_kind})
        return {
            "status": "pre_validated" if summary["canCommit"] else "blocked",
            "batchId": batch_id,
            "version": version,
            "summary": summary,
            "validation": payload["validation"],
        }

    def commit_batch(self, conn: sqlite3.Connection, user: sqlite3.Row, batch_id: int) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM import_batches WHERE id = ?", (batch_id,)).fetchone()
        if not row:
            raise ValueError("Lote nao encontrado.")
        if row["status"] != "pre_validated":
            raise ValueError("O lote precisa estar pré-validado para confirmação.")
        payload = read_json(row["payload_json"])
        payload["metadata"]["importedBy"] = user["username"]
        payload["metadata"]["importedAt"] = iso_now()

        persist_payload_records(conn, batch_id, payload)
        conn.execute(
            """
            UPDATE import_batches
            SET status = 'committed', committed_at = ?, payload_json = ?
            WHERE id = ?
            """,
            (iso_now(), db_json(payload), batch_id),
        )
        self.log_audit(conn, user, "import.commit", "import_batch", str(batch_id), {"version": row["version"]})
        return {
            "status": "committed",
            "batchId": batch_id,
            "version": row["version"],
            "dashboard": payload,
        }

    def register_imported_file(
        self,
        conn: sqlite3.Connection,
        batch_id: int,
        role: str,
        source: Path,
        original_names: dict[str, str] | None,
        upload_meta: dict[str, dict[str, Any]] | None,
    ) -> None:
        original_name = original_names.get(role, source.name) if original_names else source.name
        meta = upload_meta.get(role) if upload_meta else None
        conn.execute(
            """
            INSERT INTO imported_files (batch_id, file_role, original_name, stored_path, sha256, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                role,
                original_name,
                str(source),
                meta["sha256"] if meta else file_hash(source),
                int(meta["size"] if meta else source.stat().st_size),
                iso_now(),
            ),
        )

    def record_import_error(self, conn: sqlite3.Connection, user: sqlite3.Row, source_file: str, error: str) -> None:
        version = next_import_version(conn)
        now = iso_now()
        cursor = conn.execute(
            """
            INSERT INTO import_batches (
                version, status, source_file, source_hash, operation_file_path, company_file_path,
                validation_json, error_message, created_at, prevalidated_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (version, "error", source_file, "", "", "", db_json({}), error, now, now, user["id"]),
        )
        batch_id = last_insert_id(conn, cursor)
        conn.execute(
            "INSERT INTO import_errors (batch_id, severity, scope, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (batch_id, "error", "importacao", error, now),
        )
        self.log_audit(conn, user, "import.error", "import_batch", str(batch_id), {"error": error})

    def handle_audit_logs(self) -> None:
        user = self.current_user()
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT audit_logs.*, users.username
                FROM audit_logs
                LEFT JOIN users ON users.id = audit_logs.user_id
                ORDER BY audit_logs.id DESC
                LIMIT 200
                """
            ).fetchall()
            if user:
                self.log_audit(conn, user, "audit.view", "audit_logs")
        self.send_json(
            {
                "logs": [
                    {
                        "id": row["id"],
                        "userId": row["user_id"],
                        "username": row["username"],
                        "action": row["action"],
                        "entityType": row["entity_type"],
                        "entityId": row["entity_id"],
                        "ipAddress": row["ip_address"],
                        "userAgent": row["user_agent"],
                        "details": read_json(row["details_json"]),
                        "createdAt": row["created_at"],
                    }
                    for row in rows
                ]
            }
        )

    def handle_login(self) -> None:
        try:
            body = get_json_body(self)
        except (json.JSONDecodeError, ValueError):
            self.send_json({"error": "JSON invalido."}, HTTPStatus.BAD_REQUEST)
            return

        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        with connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if not user or not verify_password(password, user["password_hash"]):
                self.log_audit(conn, None, "auth.login_failed", "user", username, {"username": username})
                self.send_json({"error": "Usuario ou senha invalidos."}, HTTPStatus.UNAUTHORIZED)
                return

            token = secrets.token_urlsafe(32)
            expires_at = utc_now() + dt.timedelta(days=SESSION_DAYS)
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, user["id"], iso_now(), expires_at.isoformat(timespec="seconds")),
            )
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (iso_now(), user["id"]))
            self.log_audit(conn, user, "auth.login", "user", str(user["id"]))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            self.session_cookie_header(token, SESSION_DAYS * 86400),
        )
        self.end_headers()
        self.wfile.write(json.dumps({"authenticated": True, "user": self.public_user(user)}).encode("utf-8"))

    def handle_logout(self) -> None:
        token = self.session_token()
        if token:
            with connect() as conn:
                user = self.current_user()
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                if user:
                    self.log_audit(conn, user, "auth.logout", "user", str(user["id"]))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", self.session_cookie_header("", 0))
        self.end_headers()
        self.wfile.write(b'{"authenticated": false}')

    def current_user(self) -> sqlite3.Row | None:
        token = self.session_token()
        if not token:
            return None
        with connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso_now(),))
            return conn.execute(
                """
                SELECT users.*
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ? AND sessions.expires_at > ?
                """,
                (token, iso_now()),
            ).fetchone()

    def require_user(self) -> sqlite3.Row | None:
        user = self.current_user()
        if not user:
            self.send_json({"error": "Autenticacao requerida."}, HTTPStatus.UNAUTHORIZED)
            return None
        if "is_active" in user.keys() and not user["is_active"]:
            self.send_json({"error": "Usuario inativo."}, HTTPStatus.FORBIDDEN)
            return None
        return user

    def session_token(self) -> str:
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return ""
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else ""

    def public_user(self, user: sqlite3.Row) -> dict[str, Any]:
        return {"id": user["id"], "username": user["username"], "role": user["role"]}

    def session_cookie_header(self, token: str, max_age: int) -> str:
        secure = "; Secure" if os.environ.get("DASH_COOKIE_SECURE", "0") == "1" else ""
        return f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={max_age}{secure}"

    def log_audit(
        self,
        conn: sqlite3.Connection,
        user: sqlite3.Row | None,
        action: str,
        entity_type: str,
        entity_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_logs (
                user_id, action, entity_type, entity_id, ip_address, user_agent, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"] if user else None,
                action,
                entity_type,
                entity_id,
                self.client_address[0] if self.client_address else None,
                self.headers.get("User-Agent", ""),
                db_json(details or {}),
                iso_now(),
            ),
        )

    def send_json(self, payload: dict[str, Any] | list[Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Backend do dashboard de atestados.")
    parser.add_argument("--host", default=os.environ.get("DASH_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DASH_PORT", "8000")))
    parser.add_argument("--init-db", action="store_true")
    args = parser.parse_args()

    init_db()
    if args.init_db:
        print("Banco PostgreSQL inicializado via DATABASE_URL." if USE_POSTGRES else f"Banco inicializado em: {DB_PATH}")
        return 0

    mimetypes.add_type("application/javascript", ".js")
    address = (args.host, args.port)
    print(f"Dashboard profissional em http://{args.host}:{args.port}")
    print("Banco ativo: PostgreSQL." if USE_POSTGRES else f"Banco ativo: SQLite local em {DB_PATH}.")
    if os.environ.get("DASH_ADMIN_PASSWORD"):
        print("Credenciais administrativas carregadas das variaveis de ambiente.")
    else:
        print(f"Login local inicial: {DEFAULT_ADMIN_USER} / {DEFAULT_ADMIN_PASSWORD}")
    ThreadingHTTPServer(address, DashHandler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
