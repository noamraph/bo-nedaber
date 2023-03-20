# This file is for convenient commands for this project.
# See https://github.com/casey/just

# Run a test server on localhost:8000
run:
    poetry run uvicorn bo_nedaber.main:app --reload

# Do long-polling (getUpdates), and forward updates to the local server
proxy:
    poetry run python webhook_proxy.py

mypy:
    poetry run mypy

pylint:
    poetry run pylint *.py bo_nedaber/*.py tests/*.py

precommit:
    poetry run pre-commit run --all-files

pytest:
    poetry run pytest
