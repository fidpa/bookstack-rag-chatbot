# Tests

Standalone Python scripts that exercise key subsystems of the chatbot backend.

## Suite

| File | Subject | Requires |
|---|---|---|
| `test_bookstack_api.py` | BookStack REST API connectivity and authentication | Running BookStack container + valid API token |
| `test_chunking_integration.py` | Chunking service, SQLite FTS5 search, performance benchmark | Stopped chatbot container (SQLite write-lock) |

## Running

Start the stack first, then load the environment used by the tests:

```bash
cp ../.env.example ../.env  # fill in BOOKSTACK_TOKEN_ID / BOOKSTACK_TOKEN_SECRET first
docker compose -f ../docker/docker-compose.yml up -d
set -a; . ../.env; set +a

# API connectivity (container can stay running)
python3 test_bookstack_api.py

# Chunking + FTS5 integration (needs SQLite single-writer access)
docker compose -f ../docker/docker-compose.yml stop chatbot
python3 test_chunking_integration.py
docker compose -f ../docker/docker-compose.yml start chatbot
```

Exit code `0` indicates success. Each script prints a one-line pass/fail summary.

## Pytest

A thin pytest harness is on the roadmap. Until then, treat these as smoke tests for manual or CI runs.
