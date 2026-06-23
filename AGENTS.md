# Agent Instructions

- Use `uv` for all Python-related tasks (run, test, lint, etc.), not `pip` or `poetry`.
- Always use a long timeout (300–400s) when running tests to account for the user's low-end laptop.
- Run tests in parallel when possible (e.g., `uv run pytest -n auto ...`).
