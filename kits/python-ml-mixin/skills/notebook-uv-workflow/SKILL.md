---
name: notebook-uv-workflow
description: Best practices and commands for managing Jupyter notebooks, virtual environments with uv, linting with ruff, and syncing with jupytext and nbstripout.
---

# Notebook & UV Workflow Guidelines

## Core Principles
1. **Clean Notebook Commits**: Always strip notebook outputs before git commits using `nbstripout`.
2. **Paired Scripts via Jupytext**: Author notebook logic as percent scripts (`# %%`) and keep them synchronized with `.ipynb` via `jupytext --sync`.
3. **High-Performance Python Environment (`uv`)**:
   - Manage dependencies using `uv`: `uv venv`, `uv pip install <pkg>`, `uv run <cmd>`.
   - Lock dependencies with `uv lock`.
4. **Fast Linting and Formatting (`ruff`)**:
   - Check lint rules: `ruff check .`
   - Format source files: `ruff format .`

## Common Commands
```bash
# Pair notebook with percent-formatted Python script
jupytext --set-formats ipynb,py:percent my_notebook.ipynb

# Sync changes between script and notebook
jupytext --sync my_notebook.py

# Run ruff checks
ruff check . --fix
ruff format .

# Strip notebook output cells
nbstripout my_notebook.ipynb
```
