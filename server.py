from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
import socket
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scheduler_engine import Employee, ScheduleGenerationError, generate_schedule
from security import hash_password, new_salt, session_token, verify_password
from storage import BACKUPS, DB, DEPARTMENTS, audit, backup_database, connect, create_session, init_db, list_backups, now

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("ESCALA_PORT", "8766"))
SCHEDULE_CUTOFF = os.environ.get("SCHEDULE_CUTOFF", "").strip()
NEW_SCHEDULE_START = os.environ.get("NEW_SCHEDULE_START", "").strip()


def json_bytes(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")


def body_json(handler) -> dict:
    size = int(handler.headers.get("Content-Length", "0") or 0)
    if size > 2_000_000:
        raise ValueError("Request body is too large.")
    raw = handler.rfile.read(size) if size else b"{}"
    data = json.loads(raw or b"{}")
    if not isinstance(data, dict):
        raise ValueError("JSON object expected.")
    return data


def department(query: dict[str, list[str]], fallback="SAC_ECOMMERCE") -> str:
    value = (query.get("department") or [fallback])[0]
    return value if value in DEPARTMENTS else fallback


def local_ips() -> list[str]:
    values = {"127.0.0.1"}
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, family=socket.AF_INET):
            values.add(info[4][0])
    except OSError:
        pass
    return sorted(values, key=lambda ip: (ip == "127.0.0.1", ip))


class Handler(SimpleHTTPRequestHandler):
    server_version = "WorkforceScheduler/2.7.4-portfolio"

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().isoformat(timespec='seconds')}] {self.client_address[0]} {fmt % args}")

    def send_json(self, payload, status=200, headers=None):
        raw = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def send_text(self, text: str, content_type="text/plain; charset=utf-8", status=200, filename=None):
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(raw)

    def token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth.split(None, 1)[1].strip()
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("escala_session")
        return morsel.value if morsel else ""

    def current_user(self):
        token = self.token()
        if not token:
            return None
        with connect() as conn:
            row = conn.execute(
                """SELECT u.*,e.name AS employee_name,e.department,e.break_start,e.break_end
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   LEFT JOIN employees e ON e.id=u.employee_id
                   WHERE s.token=? AND s.expires_at>? AND u.active=1""",
                (token, now()),
            ).fetchone()
            return dict(row) if row else None

    def require_user(self):
        user = self.current_user()
        if not user:
            self.send_json({"error": "Authentication required.", "auth": False}, HTTPStatus.UNAUTHORIZED)
            return None
        return user

    def require_permission(self, user, key):
        if user["role"] == "ADMIN" or bool(user.get(key)):
            return True
        self.send_json({"error": "Você não possui permissão para esta ação."}, HTTPStatus.FORBIDDEN)
        return False

    def end_session_cookie(self):
        self.send_header("Set-Cookie", "escala_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path

        if path == "/api/me":
            user = self.current_user()
            if not user:
                return self.send_json({"authenticated": False})
            fields = (
                "id", "username", "email", "role", "employee_id", "department",
                "can_manage_employees", "can_edit_schedule", "can_generate_schedule",
                "can_manage_users", "can_switch_departments",
            )
            return self.send_json({"authenticated": True, "user": {key: user.get(key) for key in fields}})

        if path == "/api/server-info":
            return self.send_json({
                "hostname": socket.gethostname(),
                "port": PORT,
                "urls": [f"http://{ip}:{PORT}" for ip in local_ips()],
                "scheduleCutoff": SCHEDULE_CUTOFF,
                "newScheduleStart": NEW_SCHEDULE_START,
                "portfolio": True,
            })

        if not path.startswith("/api/"):
            if path == "/":
                self.path = "/index.html"
            return super().do_GET()

        user = self.require_user()
        if not user:
            return
        dept = department(query, user.get("department") or "SAC_ECOMMERCE")

        if path == "/api/employees":
            with connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM employees WHERE department=? ORDER BY active DESC,rotation_order,name", (dept,)
                ).fetchall()
            return self.send_json([dict(row) for row in rows])

        if path == "/api/schedule":
            start = (query.get("start") or [date.today().replace(day=1).isoformat()])[0]
            end = (query.get("end") or [(date.today() + timedelta(days=31)).isoformat()])[0]
            args = [dept, start, end]
            sql = """SELECT s.*,e.name AS employee_name FROM schedule s
                     JOIN employees e ON e.id=s.employee_id
                     WHERE e.department=? AND s.work_date BETWEEN ? AND ?"""
            if user.get("employee_id") and user["role"] != "ADMIN" and not any(
                user.get(key) for key in ("can_manage_employees", "can_edit_schedule", "can_generate_schedule")
            ):
                sql += " AND e.id=?"
                args.append(user["employee_id"])
            sql += " ORDER BY e.rotation_order,s.work_date"
            with connect() as conn:
                rows = conn.execute(sql, args).fetchall()
            return self.send_json([dict(row) for row in rows])

        if path == "/api/dashboard":
            with connect() as conn:
                active = conn.execute("SELECT COUNT(*) FROM employees WHERE active=1 AND department=?", (dept,)).fetchone()[0]
                n2 = conn.execute("SELECT COUNT(*) FROM employees WHERE active=1 AND department=? AND group_type='N2'", (dept,)).fetchone()[0]
                since = (date.today() - timedelta(days=7)).isoformat()
                changes = conn.execute("SELECT COUNT(*) FROM audit WHERE occurred_at>=?", (since,)).fetchone()[0]
                next_row = conn.execute(
                    """SELECT e.name,s.work_date,s.shift FROM schedule s JOIN employees e ON e.id=s.employee_id
                       WHERE e.department=? AND e.group_type='N2' AND s.status='T' AND s.work_date>=?
                       AND CAST(strftime('%w',s.work_date) AS INTEGER) IN (0,6)
                       ORDER BY s.work_date LIMIT 1""",
                    (dept, date.today().isoformat()),
                ).fetchone()
            return self.send_json({"active": active, "n2": n2, "changes": changes, "next_weekend": dict(next_row) if next_row else None})

        if path == "/api/audit":
            if not self.require_permission(user, "can_manage_users"):
                return
            with connect() as conn:
                rows = conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200").fetchall()
            return self.send_json([dict(row) for row in rows])

        if path == "/api/backups":
            if user["role"] != "ADMIN":
                return self.send_json({"error": "Administrador necessário."}, HTTPStatus.FORBIDDEN)
            return self.send_json(list_backups())

        if path == "/api/users":
            if not self.require_permission(user, "can_manage_users"):
                return
            with connect() as conn:
                rows = conn.execute(
                    """SELECT u.id,u.employee_id,u.username,u.email,u.role,u.active,
                              u.can_manage_employees,u.can_edit_schedule,u.can_generate_schedule,
                              u.can_manage_users,u.can_switch_departments,e.name
                       FROM users u LEFT JOIN employees e ON e.id=u.employee_id ORDER BY u.id"""
                ).fetchall()
            return self.send_json([dict(row) for row in rows])

        if path == "/api/my-break":
            today = date.today().isoformat()
            if not user.get("employee_id"):
                return self.send_json({"employee": None})
            with connect() as conn:
                entry = conn.execute(
                    "SELECT status,shift FROM schedule WHERE employee_id=? AND work_date=?",
                    (user["employee_id"], today),
                ).fetchone()
                ack = conn.execute(
                    "SELECT acknowledged_at FROM break_alert_ack WHERE user_id=? AND alert_date=?",
                    (user["id"], today),
                ).fetchone()
            return self.send_json({
                "employee": user.get("employee_name"),
                "date": today,
                "breakStart": user.get("break_start"),
                "breakEnd": user.get("break_end"),
                "workingToday": bool(entry and entry["status"] == "T"),
                "status": entry["status"] if entry else None,
                "shift": entry["shift"] if entry else None,
                "acknowledged": bool(ack),
                "acknowledgedAt": ack["acknowledged_at"] if ack else None,
            })

        if path == "/api/export.csv":
            start = (query.get("start") or [date.today().replace(day=1).isoformat()])[0]
            end = (query.get("end") or [(date.today() + timedelta(days=31)).isoformat()])[0]
            with connect() as conn:
                rows = conn.execute(
                    """SELECT e.name,e.group_type,s.work_date,s.status,s.shift,s.source,s.note
                       FROM schedule s JOIN employees e ON e.id=s.employee_id
                       WHERE e.department=? AND s.work_date BETWEEN ? AND ?
                       ORDER BY e.rotation_order,s.work_date""",
                    (dept, start, end),
                ).fetchall()
            out = io.StringIO()
            writer = csv.writer(out, delimiter=";")
            writer.writerow(["Colaborador", "Grupo", "Data", "Status", "Horário", "Origem", "Observação"])
            for row in rows:
                writer.writerow(list(row))
            return self.send_text("\ufeff" + out.getvalue(), "text/csv; charset=utf-8", filename=f"escala_{start}_{end}.csv")

        return self.send_json({"error": "Endpoint not found."}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path

        if path == "/api/login":
            try:
                payload = body_json(self)
                username = str(payload.get("username", "")).strip().lower()
                password = str(payload.get("password", ""))
                with connect() as conn:
                    row = conn.execute("SELECT * FROM users WHERE lower(username)=? AND active=1", (username,)).fetchone()
                    if not row or not verify_password(password, row["salt"], row["password_hash"]):
                        return self.send_json({"error": "Usuário ou senha inválidos."}, HTTPStatus.UNAUTHORIZED)
                    token = session_token()
                    create_session(conn, row["id"], token)
                return self.send_json({"ok": True, "token": token})
            except Exception as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

        user = self.require_user()
        if not user:
            return
        dept = department(query, user.get("department") or "SAC_ECOMMERCE")

        try:
            payload = body_json(self)

            if path == "/api/logout":
                token = self.token()
                with connect() as conn:
                    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
                return self.send_json({"ok": True})

            if path == "/api/schedule/generate":
                if not self.require_permission(user, "can_generate_schedule"):
                    return
                start = date.fromisoformat(str(payload["start"]))
                end = date.fromisoformat(str(payload["end"]))
                if SCHEDULE_CUTOFF and start.isoformat() <= SCHEDULE_CUTOFF:
                    return self.send_json({"error": f"Escala protegida até {SCHEDULE_CUTOFF}."}, HTTPStatus.BAD_REQUEST)
                if NEW_SCHEDULE_START and start.isoformat() < NEW_SCHEDULE_START:
                    return self.send_json({"error": f"A geração deve começar em {NEW_SCHEDULE_START} ou depois."}, HTTPStatus.BAD_REQUEST)

                backup_database("antes_gerar")
                with connect() as conn:
                    employee_rows = conn.execute(
                        "SELECT * FROM employees WHERE active=1 AND department=? ORDER BY rotation_order,id", (dept,)
                    ).fetchall()
                    team = [
                        Employee(
                            id=row["id"], name=row["name"], weekday_shift=row["weekday_shift"],
                            weekend_shift=row["weekend_shift"], rotation_order=row["rotation_order"],
                            group_type=row["group_type"],
                        ) for row in employee_rows
                    ]
                    cursor_key = f"rotation_cursor:{dept}"
                    cursor_row = conn.execute("SELECT value FROM settings WHERE key=?", (cursor_key,)).fetchone()
                    cursor = int(cursor_row["value"]) if cursor_row else 0
                    generated, metadata = generate_schedule(team, start, end, rotation_cursor=cursor)
                    conn.execute(
                        "DELETE FROM schedule WHERE work_date BETWEEN ? AND ? AND employee_id IN (SELECT id FROM employees WHERE department=?)",
                        (start.isoformat(), end.isoformat(), dept),
                    )
                    stamp = now()
                    for row in generated:
                        conn.execute(
                            """INSERT INTO schedule(employee_id,work_date,status,shift,source,note,updated_at)
                               VALUES(?,?,?,?,?,?,?)""",
                            (row.employee_id, row.work_date.isoformat(), row.status, row.shift, "automatico", row.note, stamp),
                        )
                    conn.execute(
                        "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (cursor_key, str(metadata["rotation_cursor"])),
                    )
                    audit(conn, "GERAR", "escala", {"department": dept, "start": start.isoformat(), "end": end.isoformat(), "weeks": metadata["weeks"]}, user["username"])
                return self.send_json({"ok": True, "count": len(generated), **metadata})

            if path == "/api/schedule/edit":
                if not self.require_permission(user, "can_edit_schedule"):
                    return
                work_date = str(payload["date"])
                if SCHEDULE_CUTOFF and work_date <= SCHEDULE_CUTOFF:
                    return self.send_json({"error": f"Escala protegida até {SCHEDULE_CUTOFF}."}, HTTPStatus.BAD_REQUEST)
                employee_id = int(payload["employeeId"])
                status = str(payload["status"])
                if status not in {"T", "F", "FERIAS", "AFASTADO"}:
                    raise ValueError("Invalid status.")
                shift = str(payload.get("shift") or "") if status == "T" else None
                note = str(payload.get("note") or "")[:500]
                with connect() as conn:
                    owner = conn.execute("SELECT name,department FROM employees WHERE id=?", (employee_id,)).fetchone()
                    if not owner or owner["department"] != dept:
                        raise ValueError("Employee does not belong to this department.")
                    old = conn.execute("SELECT * FROM schedule WHERE employee_id=? AND work_date=?", (employee_id, work_date)).fetchone()
                    conn.execute(
                        """INSERT INTO schedule(employee_id,work_date,status,shift,source,note,updated_at)
                           VALUES(?,?,?,?, 'manual', ?, ?)
                           ON CONFLICT(employee_id,work_date) DO UPDATE SET
                           status=excluded.status,shift=excluded.shift,source='manual',note=excluded.note,updated_at=excluded.updated_at""",
                        (employee_id, work_date, status, shift, note, now()),
                    )
                    audit(conn, "EDITAR", "escala", {"employee": owner["name"], "date": work_date, "before": dict(old) if old else None, "after": {"status": status, "shift": shift, "note": note}}, user["username"])
                return self.send_json({"ok": True})

            if path == "/api/employees":
                if not self.require_permission(user, "can_manage_employees"):
                    return
                with connect() as conn:
                    order = conn.execute("SELECT COALESCE(MAX(rotation_order),-1)+1 FROM employees WHERE department=?", (dept,)).fetchone()[0]
                    cur = conn.execute(
                        """INSERT INTO employees(name,weekday_shift,weekend_shift,active,rotation_order,group_type,department,break_start,break_end)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (
                            str(payload["name"]).strip(), str(payload.get("weekdayShift") or "08h–18h"),
                            str(payload.get("weekendShift") or "08h–18h"), 1, int(payload.get("rotationOrder", order)),
                            str(payload.get("groupType") or "GERAL"), dept,
                            str(payload.get("breakStart") or "") or None, str(payload.get("breakEnd") or "") or None,
                        ),
                    )
                    audit(conn, "CRIAR", "colaborador", {"id": cur.lastrowid, "name": payload["name"], "department": dept}, user["username"])
                return self.send_json({"ok": True, "id": cur.lastrowid})

            if path == "/api/backup":
                if user["role"] != "ADMIN":
                    return self.send_json({"error": "Administrador necessário."}, HTTPStatus.FORBIDDEN)
                target = backup_database("manual")
                with connect() as conn:
                    audit(conn, "CRIAR", "backup", {"file": target.name}, user["username"])
                return self.send_json({"ok": True, "name": target.name})

            if path == "/api/users/create":
                if not self.require_permission(user, "can_manage_users"):
                    return
                username = str(payload.get("username", "")).strip().lower()
                password = str(payload.get("password", "")).strip()
                if len(username) < 3 or len(password) < 8:
                    raise ValueError("Username and a temporary password of at least 8 characters are required.")
                role = "ADMIN" if payload.get("role") == "ADMIN" else "COLABORADOR"
                salt = new_salt()
                with connect() as conn:
                    cur = conn.execute(
                        """INSERT INTO users(username,email,password_hash,salt,role,can_manage_employees,can_edit_schedule,
                           can_generate_schedule,can_manage_users,can_switch_departments,active,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,1,?)""",
                        (
                            username, str(payload.get("email") or "") or None, hash_password(password, salt), salt, role,
                            int(role == "ADMIN"), int(role == "ADMIN"), int(role == "ADMIN"), int(role == "ADMIN"), int(role == "ADMIN"), now(),
                        ),
                    )
                    audit(conn, "CRIAR", "usuario", {"id": cur.lastrowid, "username": username, "role": role}, user["username"])
                return self.send_json({"ok": True, "id": cur.lastrowid})

            if path == "/api/my-break/ack":
                if not user.get("employee_id"):
                    raise ValueError("User is not linked to an employee.")
                today = date.today().isoformat()
                stamp = now()
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO break_alert_ack(user_id,alert_date,acknowledged_at) VALUES(?,?,?) ON CONFLICT(user_id,alert_date) DO UPDATE SET acknowledged_at=excluded.acknowledged_at",
                        (user["id"], today, stamp),
                    )
                return self.send_json({"ok": True, "acknowledgedAt": stamp})

            return self.send_json({"error": "Endpoint not found."}, HTTPStatus.NOT_FOUND)

        except ScheduleGenerationError as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except (KeyError, ValueError, TypeError) as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            print("Unhandled error:", repr(exc))
            return self.send_json({"error": "Unexpected server error."}, HTTPStatus.INTERNAL_SERVER_ERROR)


if __name__ == "__main__":
    os.chdir(ROOT)
    temporary_password = init_db()
    if temporary_password:
        print("\nPortfolio demo administrator created")
        print("username: admin")
        print("temporary password:", temporary_password)
        print("Set ESCALA_ADMIN_PASSWORD before shared use.\n")
    print(f"Workforce Scheduler running on http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
