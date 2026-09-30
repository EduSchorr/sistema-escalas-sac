> **Language:** English · [Português (Brasil)](README.pt-BR.md)

<div align="center">

# Workforce Scheduler

### Rule-based team scheduling · permissions · audit · local deployment

**A local-first workforce scheduling application built to manage rotating teams, weekend coverage and operational access rules.**

![Python](https://img.shields.io/badge/Python-20232A?style=for-the-badge&logo=python&logoColor=3776AB)
![SQLite](https://img.shields.io/badge/SQLite-20232A?style=for-the-badge&logo=sqlite&logoColor=003B57)
![JavaScript](https://img.shields.io/badge/JavaScript-20232A?style=for-the-badge&logo=javascript&logoColor=F7DF1E)
![HTML5](https://img.shields.io/badge/HTML5-20232A?style=for-the-badge&logo=html5&logoColor=E34F26)

</div>

---

## What this project demonstrates

The system was created for an operational environment where schedules need to respect coverage, rotation and rest constraints while still allowing controlled manual adjustments.

This repository is a **sanitized portfolio edition** using synthetic employees and no production database.

## Public portfolio features

- automatic multi-week schedule generation;
- 5x2-oriented workload validation;
- maximum six consecutive work days;
- dedicated N2 Saturday/Sunday rotation;
- balanced general-team weekend coverage;
- periodic full-weekend-off rotation;
- controlled manual Work / Off / Vacation / Leave adjustments;
- department-aware schedule views;
- role-based access checks;
- PBKDF2 password hashing and session tokens;
- audit trail for schedule and administrative changes;
- local SQLite backup creation;
- CSV/Excel-compatible schedule export;
- LAN-friendly local deployment;
- synthetic seed data for a fresh demo database.

The original operational prototype also evolved around break reminders, richer user administration, external directory synchronization, duty swaps and local update flows. Private integration details and production-specific routines are intentionally not shipped in this public edition.

## Architecture

```text
Browser
  │
  ├── index.html
  ├── app.js
  └── style.css
  │
  ▼
Python ThreadingHTTPServer
  │
  ├── authenticated API
  ├── permission checks
  ├── scheduler_engine.py
  ├── audit / backup / export
  └── local static hosting
  │
  ▼
SQLite
  ├── employees
  ├── schedule
  ├── users
  ├── sessions
  ├── audit
  └── settings
```

The backend intentionally relies mostly on the Python standard library, keeping the local deployment lightweight.

## Scheduling engine

The public engine models:

- five working days per complete week;
- two weekly days off;
- no more than six consecutive working days;
- one N2/on-call worker on Saturday and another on Sunday;
- weekday compensation for employees who cover the weekend;
- equalized general-team Saturday/Sunday coverage;
- one rotating full weekend off for the general team;
- shift-aware balancing when choosing weekend groups;
- validation before the generated result is accepted.

The engine lives in [`scheduler_engine.py`](scheduler_engine.py), separated from HTTP and persistence code so the rules can be tested independently.

These rules represent one operational scheduling model and should be adapted to applicable labor rules and company policy before real-world use.

## Run locally

Requires **Python 3.11+** and no third-party packages.

### Windows PowerShell

```powershell
$env:ESCALA_ADMIN_PASSWORD="choose-a-strong-password"
python server.py
```

Then open:

```text
http://localhost:8766
```

If `ESCALA_ADMIN_PASSWORD` is omitted on a fresh database, the server generates a temporary administrator password and prints it once in the terminal.

The default username is:

```text
admin
```

## Tests

Run the scheduling-engine tests with:

```bash
python -m unittest -v tests/test_scheduler_engine.py
```

The portfolio build includes tests for:

- 5x2 distribution across complete weeks;
- one N2 worker on Saturday and one on Sunday;
- rejection of an invalid team shape.

## Optional configuration

See [`.env.example`](.env.example).

`SCHEDULE_CUTOFF` protects historical dates from manual modification.

`NEW_SCHEDULE_START` sets the earliest date accepted by automatic generation.

`ESCALA_PORT` changes the local HTTP port.

The original implementation supported an optional external SQLite employee directory. `CENTRAL_DB_PATH` remains documented as a deployment seam, but the private synchronization routine is not included in the portfolio build.

## Privacy

The public repository does **not** include:

- real employee names;
- real e-mail addresses;
- production schedules;
- company databases;
- live session/password-reset tokens;
- production backup files;
- hard-coded administrator credentials;
- private network addresses;
- private integration paths.

See [`PORTFOLIO_EDITION.md`](PORTFOLIO_EDITION.md).

## Baseline

Portfolio baseline derived from **2.7.4**.

---

<div align="center">

Built by **Eduardo Lima** · [GitHub](https://github.com/EduSchorr)

</div>
