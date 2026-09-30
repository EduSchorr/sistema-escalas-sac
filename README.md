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

## Main features

- automatic multi-week schedule generation;
- 5x2-oriented workload validation;
- maximum consecutive-work-day protection;
- dedicated weekend rotation for N2/on-call roles;
- balanced Saturday/Sunday coverage for the general team;
- controlled weekend duty swaps with weekday compensation;
- manual Work / Off / Vacation / Leave adjustments;
- two operational departments with permission-aware switching;
- per-user schedule visibility;
- role-based permissions for schedule, team, users and departments;
- PBKDF2 password hashing and session tokens;
- first-access / password-reset token flow;
- optional local Outlook e-mail delivery;
- scheduled break reminders with acknowledgement;
- audit trail for administrative changes;
- local SQLite backup and restore;
- Excel-compatible schedule export;
- optional employee-directory synchronization from another SQLite database;
- ZIP-based local update workflow;
- LAN-friendly local deployment.

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
  ├── authentication / permissions
  ├── schedule generation engine
  ├── audit + backup + update APIs
  └── optional directory sync
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

The project intentionally uses the Python standard library for most of the backend, which keeps local deployment lightweight.

## Scheduling rules represented

The portfolio baseline includes rules for:

- five working days per week;
- two weekly days off;
- no more than six consecutive working days;
- one N2/on-call worker on Saturday and another on Sunday;
- weekday compensation for N2 weekend duty;
- equalized general-team weekend coverage;
- periodic full weekends off based on rotation history;
- cancellation of automatic generation when validation detects coverage or rest violations.

These rules are examples of an operational scheduling model and should be adapted to local labor rules and company policy before real-world use.

## Run locally

```bash
python server.py
```

The server defaults to:

```text
http://localhost:8766
```

For a fresh portfolio database, set the administrator password before starting:

### Windows PowerShell

```powershell
$env:ESCALA_ADMIN_PASSWORD="choose-a-strong-password"
python server.py
```

If the variable is omitted, the application creates a random temporary password and prints it once in the terminal.

## Optional configuration

Copy `.env.example` values into your environment as needed.

`CENTRAL_DB_PATH` enables the optional read-only employee synchronization flow against another local SQLite source.

`SCHEDULE_CUTOFF` can protect historical dates from manual modification.

`NEW_SCHEDULE_START` controls the earliest date accepted by the generator.

## Privacy

The public repository does **not** include:

- real employee names;
- real e-mail addresses;
- production schedules;
- company databases;
- session/password-reset tokens;
- production backup files;
- hard-coded administrator credentials;
- private network addresses.

See [`PORTFOLIO_EDITION.md`](PORTFOLIO_EDITION.md).

## Baseline

Portfolio baseline: **2.7.4**

---

<div align="center">

Built by **Eduardo Lima** · [GitHub](https://github.com/EduSchorr)

</div>
