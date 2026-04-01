# E-Form Data Collection

E-Form Data Collection is a standalone Flask + PostgreSQL project for managing route import, A/B/C classification, assignment files, sync, reporting, and verification for the e-form collection workflow.

Feature Guide: [docs/features.md](/C:/Users/phukt/gathering_data/eform-data-collection/docs/features.md)

## Tech Stack

- Python 3.11
- Flask
- Streamlit
- PostgreSQL
- SQLAlchemy 2.0
- Alembic
- Poetry
- Docker / Docker Compose

## Prerequisites

- Python 3.11 recommended
- Poetry installed
- Docker Desktop installed and running in Linux containers mode

## Recommended Local Setup

For local development, the simplest flow is:

- Run PostgreSQL in Docker
- Run Alembic, Flask, Streamlit, and tests on the host machine with Poetry

This matches the current `dev.ini`, which points PostgreSQL to `localhost`.

## First-Time Setup

### 1. Start PostgreSQL

```powershell
docker compose up -d postgres
```

Check that the container is running:

```powershell
docker compose ps
```

### 2. Install dependencies

```powershell
poetry install --with dev
```

### 3. Create the first migration

```powershell
poetry run alembic revision --autogenerate -m "initial"
```

### 4. Apply the migration

```powershell
poetry run alembic upgrade head
```

### 5. Verify the tables

```powershell
docker compose exec postgres psql -U eform_user -d eform_data -c "\dt"
```

Expected tables:

- `branches`
- `branch_mappings`
- `segments`
- `assignments`
- `collected_records`
- `unmapped_records`
- `sync_log`
- `sync_cursor`
- `verification_log`

## Running the Project

### Flask API

```powershell
poetry run python app.py
```

Health check:

```text
http://localhost:8000/api/health-check
```

### Streamlit UI

```powershell
poetry run streamlit run src/streamlit_app.py
```

### Manual Sync

```powershell
poetry run python sync.py
```

## Tests

Run all tests:

```powershell
poetry run pytest
```

Run unit tests only:

```powershell
poetry run pytest tests/unit
```

## Useful Commands

```powershell
docker compose up -d
docker compose down
make streamlit
make sync
```

## Configuration

Environment config files:

- `src/config/env/dev.ini`
- `src/config/env/prod.ini`

Main PostgreSQL settings:

- `host`
- `port`
- `database`
- `username`
- `password`

Keep real production secrets out of the repository.

## Notes

- Python 3.11 is the safest choice for local development.
- If Docker Desktop is installed but `docker compose` cannot connect, make sure Docker Desktop is running.
- If you later want to run the full app inside Docker, the app container should connect to PostgreSQL using the Compose service name `postgres`, not `localhost`.
