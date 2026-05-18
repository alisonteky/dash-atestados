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
DEFAULT_SOURCE = ROOT.parent / "ATESTADOS OPERAÇÃO 2026 cópia.xlsx"
SESSION_COOKIE = "dash_session"
SESSION_DAYS = 1
PASSWORD_ITERATIONS = 260_000
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin2026"

sys.path.insert(0, str(ROOT))
from scripts.import_excel import build_payload  # noqa: E402


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
            """
        )
        ensure_admin_user(conn)


def ensure_admin_user(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    if existing:
        return

    username = os.environ.get("DASH_ADMIN_USER", DEFAULT_ADMIN_USER)
    password = os.environ.get("DASH_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    conn.execute(
        "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
        (username, hash_password(password), "admin", iso_now()),
    )


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_json_body(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length == 0:
        return {}
    if length > 5_000_000:
        raise ValueError("Payload muito grande.")
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def row_to_import(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sourceFile": row["source_file"],
        "sourceName": Path(row["source_file"]).name,
        "sourceHash": row["source_hash"],
        "status": row["status"],
        "recordsAtestados": row["records_atestados"],
        "recordsAfastados": row["records_afastados"],
        "totalDias": row["total_dias"],
        "totalAtestados": row["total_atestados"],
        "validation": json.loads(row["validation_json"]),
        "errorMessage": row["error_message"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "userId": row["user_id"],
    }


class DashHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
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
            self.send_json({"status": "ok", "database": DB_PATH.exists()})
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

        if path == "/api/imports":
            self.handle_import(user)
            return

        self.send_json({"error": "Rota nao encontrada."}, HTTPStatus.NOT_FOUND)

    def handle_dashboard(self) -> None:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM import_runs
                WHERE status = 'ok' AND payload_json IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            self.send_json({"error": "Nenhuma importacao concluida no banco."}, HTTPStatus.NOT_FOUND)
            return
        self.send_json(json.loads(row["payload_json"]))

    def handle_import_history(self) -> None:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM import_runs
                ORDER BY id DESC
                LIMIT 50
                """
            ).fetchall()
        self.send_json({"imports": [row_to_import(row) for row in rows]})

    def handle_import(self, user: sqlite3.Row) -> None:
        started_at = iso_now()
        source = DEFAULT_SOURCE
        try:
            body = get_json_body(self)
            if body.get("sourcePath"):
                source = Path(str(body["sourcePath"])).expanduser().resolve()
            if not source.exists():
                raise FileNotFoundError(f"Arquivo Excel nao encontrado: {source}")
            if source.suffix.lower() != ".xlsx":
                raise ValueError("O arquivo de importacao precisa ser .xlsx.")

            payload = build_payload(source)
            validation = payload["validation"]["atestados"]
            status = validation["status"]
            if status != "ok":
                raise ValueError("A importacao encontrou divergencias de validacao.")

            payload["metadata"]["importedBy"] = user["username"]
            payload["metadata"]["importedAt"] = iso_now()
            source_hash = file_hash(source)
            finished_at = iso_now()

            with connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO import_runs (
                        source_file,
                        source_hash,
                        status,
                        records_atestados,
                        records_afastados,
                        total_dias,
                        total_atestados,
                        validation_json,
                        payload_json,
                        error_message,
                        started_at,
                        finished_at,
                        user_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(source),
                        source_hash,
                        "ok",
                        payload["sourceTables"]["atestados"]["records"],
                        payload["sourceTables"]["afastados"]["records"],
                        validation["somaDiasImportada"],
                        validation["somaAtestadosImportada"],
                        json.dumps(payload["validation"], ensure_ascii=False),
                        json.dumps(payload, ensure_ascii=False),
                        None,
                        started_at,
                        finished_at,
                        user["id"],
                    ),
                )
                import_id = cursor.lastrowid

            self.send_json({"status": "ok", "importId": import_id, "dashboard": payload}, HTTPStatus.CREATED)
        except Exception as exc:  # noqa: BLE001
            finished_at = iso_now()
            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO import_runs (
                        source_file,
                        source_hash,
                        status,
                        validation_json,
                        error_message,
                        started_at,
                        finished_at,
                        user_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(source),
                        "",
                        "erro",
                        "{}",
                        str(exc),
                        started_at,
                        finished_at,
                        user["id"],
                    ),
                )
            traceback.print_exc()
            self.send_json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)

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
                self.send_json({"error": "Usuario ou senha invalidos."}, HTTPStatus.UNAUTHORIZED)
                return

            token = secrets.token_urlsafe(32)
            expires_at = utc_now() + dt.timedelta(days=SESSION_DAYS)
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, user["id"], iso_now(), expires_at.isoformat(timespec="seconds")),
            )

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_DAYS * 86400}",
        )
        self.end_headers()
        self.wfile.write(json.dumps({"authenticated": True, "user": self.public_user(user)}).encode("utf-8"))

    def handle_logout(self) -> None:
        token = self.session_token()
        if token:
            with connect() as conn:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
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

    def send_json(self, payload: dict[str, Any] | list[Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
        print(f"Banco inicializado em: {DB_PATH}")
        return 0

    mimetypes.add_type("application/javascript", ".js")
    address = (args.host, args.port)
    print(f"Dashboard profissional em http://{args.host}:{args.port}")
    if os.environ.get("DASH_ADMIN_PASSWORD"):
        print("Credenciais administrativas carregadas das variaveis de ambiente.")
    else:
        print(f"Login local inicial: {DEFAULT_ADMIN_USER} / {DEFAULT_ADMIN_PASSWORD}")
    ThreadingHTTPServer(address, DashHandler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
