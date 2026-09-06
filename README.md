# ValScores

ValScores includes an iOS client and a local FastAPI backend. This document covers the minimal backend development setup.

## Prerequisites

- Git
- Python 3.12 or 3.13; Python 3.12 is the development baseline recorded in `.python-version`

Run all commands below from the repository root.

## Backend setup

```bash
git clone https://github.com/singhsitanshu/ValScores.git
cd ValScores
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

The editable install reads the pinned runtime dependencies from `pyproject.toml`. No separate requirements file or manual `PYTHONPATH` configuration is needed.

## Start the backend

```bash
python -m uvicorn valoreal.api:app --reload --host 127.0.0.1 --port 8000
```

The API is available at <http://127.0.0.1:8000>. FastAPI's interactive OpenAPI documentation is at <http://127.0.0.1:8000/docs>, and the raw schema is at <http://127.0.0.1:8000/openapi.json>.

Stop the development server with `Ctrl-C`.

## SQLite database

Importing the backend creates any missing tables and applies the application's existing lightweight column initialization automatically. The SQLite database is always read from and created at:

```text
valoreal/valorant_stats.db
```

No manual database command or Python source edit is required for a clean checkout.
