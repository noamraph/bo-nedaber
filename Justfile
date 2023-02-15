# This file is for convenient commands for this project.
# See https://github.com/casey/just

# Run a test server on localhost:8000
run:
    poetry run uvicorn main:app --reload

mypy:
    poetry run mypy

pylint:
    poetry run pylint *.py

precommit:
    poetry run pre-commit run --all-files
