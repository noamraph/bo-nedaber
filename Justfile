# This file is for convenient commands for this project.
# See https://github.com/casey/just

# Run a test server on localhost:8000
run:
    uv run uvicorn bo_nedaber.main:app --reload

# Do long-polling (getUpdates), and forward updates to the local server
proxy:
    uv run python webhook_proxy.py

# Disable webhook, to allow proxy
delete_webhook:
    uv run python -c 'from dev import *; print(delete_webhook())'

mypy:
    uv run mypy

pylint:
    uv run pylint *.py bo_nedaber/*.py tests/*.py

precommit:
    uv run pre-commit run --all-files

pytest:
    uv run pytest
