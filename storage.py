from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from security import hash_password, new_salt

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
BACKUPS = ROOT / "backups"
DB = DATA / "escala.db"

DEPARTMENTS = {
    "SAC_ECOMMERCE": "Atendimento",
    "TELE_VENDAS": "Televendas",
}

DEMO_EMPLOYEES = [
    ("N2 Demo 01", "08h–18h", "10h–20h", 0, "N2"),
    ("N2 Demo 02", "08h–18h", "10h–20h", 1, "N2"),
    ("N2 Demo 03", "12h–22h", "10h–20h", 2, "N2"),
    ("Agente Demo 01", "08h–18h", "08h–18h", 3, "GERAL"),
    ("Agente Demo 02", "08h–18h", "08h–18h", 4, "GERAL"),
    ("Agente Demo 03", "12h–22h", "12h–22h", 5, "GERAL"),
    ("Agente Demo 04", "12h–22h", "12h–22h", 6, "GERAL"),
    ("Agente Demo 05", "08h–18h", "08h–18h", 7, "GERAL"),
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now() -> str:
    return utcnow().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> str | None:
    DATA.mkdir(parents=True, exist_ok=True)
    BACKUPS.mkdir(parents=True, exist_ok=True)
    temporary_password: str | None = None

    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS employees(
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              weekday_shift TEXT NOT NULL,
              weekend_shift TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              rotation_order INTEGER NOT NULL,
              group_type TEXT NOT NULL DEFAULT 'GERAL',
              department TEXT NOT NULL DEFAULT 'SAC_ECOMMERCE',
              break_start TEXT,
              break_end TEXT
            );

            CREATE TABLE IF NOT EXISTS schedule(
              id INTEGER PRIMARY KEY,
              employee_id INTEGER NOT NULL REFERENCES employees(id),
              work_date TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('T','F','FERIAS','AFASTADO')),
              shift TEXT,
              source TEXT NOT NULL DEFAULT 'automatico',
              note TEXT,
              updated_at TEXT NOT NULL,
              UNIQUE(employee_id, work_date)
            );

            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY,
              employee_id INTEGER REFERENCES employees(id),
              username TEXT NOT NULL UNIQUE,
              email TEXT,
              password_hash TEXT NOT NULL,
              salt TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'COLABORADOR',
              can_manage_employees INTEGER NOT NULL DEFAULT 0,
              can_edit_schedule INTEGER NOT NULL DEFAULT 0,
              can_generate_schedule INTEGER NOT NULL DEFAULT 0,
              can_manage_users INTEGER NOT NULL DEFAULT 0,
              can_switch_departments INTEGER NOT NULL DEFAULT 0,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions(
              token TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id),
              expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit(
              id INTEGER PRIMARY KEY,
              occurred_at TEXT NOT NULL,
              user_name TEXT NOT NULL,
              action TEXT NOT NULL,
              entity TEXT NOT NULL,
              details TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS break_alert_ack(
              user_id INTEGER NOT NULL REFERENCES users(id),
              alert_date TEXT NOT NULL,
              acknowledged_at TEXT NOT NULL,
              PRIMARY KEY(user_id, alert_date)
            );
            """
        )

        if not conn.execute("SELECT 1 FROM employees LIMIT 1").fetchone():
            for row in DEMO_EMPLOYEES:
                conn.execute(
                    """INSERT INTO employees(
                       name,weekday_shift,weekend_shift,rotation_order,group_type,department,break_start,break_end
                       ) VALUES(?,?,?,?,?,'SAC_ECOMMERCE','12:00','13:00')""",
                    row,
                )

        if not conn.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
            configured = os.environ.get("ESCALA_ADMIN_PASSWORD", "").strip()
            if configured:
                password = configured
            else:
                password = secrets.token_urlsafe(12)
                temporary_password = password
            salt = new_salt()
            conn.execute(
                """INSERT INTO users(
                   username,email,password_hash,salt,role,
                   can_manage_employees,can_edit_schedule,can_generate_schedule,
                   can_manage_users,can_switch_departments,active,created_at
                   ) VALUES('admin','admin@example.com',?,?, 'ADMIN',1,1,1,1,1,1,?)""",
                (hash_password(password, salt), salt, now()),
            )

        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now(),))

    return temporary_password


def audit(conn: sqlite3.Connection, action: str, entity: str, details: dict, user_name: str = "Sistema") -> None:
    conn.execute(
        "INSERT INTO audit(occurred_at,user_name,action,entity,details) VALUES(?,?,?,?,?)",
        (now(), user_name, action, entity, json.dumps(details, ensure_ascii=False)),
    )


def create_session(conn: sqlite3.Connection, user_id: int, token: str, hours: int = 12) -> str:
    expires = (utcnow() + timedelta(hours=hours)).isoformat(timespec="seconds")
    conn.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)", (token, user_id, expires))
    return expires


def backup_database(label: str = "manual") -> Path:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = BACKUPS / f"escala_{label}_{stamp}.db"
    with connect() as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    return target


def list_backups() -> list[dict]:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    result = []
    for path in sorted(BACKUPS.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        result.append({
            "name": path.name,
            "size": path.stat().st_size,
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        })
    return result
