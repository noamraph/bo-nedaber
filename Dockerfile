FROM python:3.11-slim

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uv /uvx /bin/

# Copy the application into the container.
COPY . /app

# Install the application dependencies.
WORKDIR /app
RUN uv sync --frozen --no-cache

EXPOSE 80

# Run the application.
# CMD ["/app/.venv/bin/fastapi", "run", "main.py", "--port", "80", "--host", "0.0.0.0"]

CMD ["uv", "run", "uvicorn", "main:app", "--port", "80", "--host", "0.0.0.0"]
