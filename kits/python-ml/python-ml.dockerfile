# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:latest AS uv-bin
FROM ghcr.io/astral-sh/ruff:latest AS ruff-bin

FROM docker.io/sbx/shell-docker-image:latest

USER root

# Copy uv and ruff binaries
COPY --from=uv-bin /uv /uvx /usr/local/bin/
COPY --from=ruff-bin /ruff /usr/local/bin/

# Install python3 and virtualenv support
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install jupytext and nbstripout into isolated toolchain virtualenv
RUN python3 -m venv /opt/python-ml/venv \
    && /opt/python-ml/venv/bin/pip install --no-cache-dir jupytext nbstripout \
    && ln -s /opt/python-ml/venv/bin/jupytext /usr/local/bin/jupytext \
    && ln -s /opt/python-ml/venv/bin/nbstripout /usr/local/bin/nbstripout

# Stage bundled skill for Docker Sandboxes agent skill registration
RUN mkdir -p /usr/share/python-ml-mixin/skills/notebook-uv-workflow
COPY skills/notebook-uv-workflow/SKILL.md /usr/share/python-ml-mixin/skills/notebook-uv-workflow/SKILL.md

USER agent
