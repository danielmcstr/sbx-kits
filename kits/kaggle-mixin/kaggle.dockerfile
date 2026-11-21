# syntax=docker/dockerfile:1
FROM docker.io/sbx/shell-docker-image:latest

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install kaggle CLI into dedicated toolchain venv
RUN python3 -m venv /opt/kaggle/venv \
    && /opt/kaggle/venv/bin/pip install --no-cache-dir kaggle six \
    && ln -s /opt/kaggle/venv/bin/kaggle /usr/local/bin/kaggle

# Stage official kaggle skill and references for Docker Sandboxes skill linking
RUN mkdir -p /usr/share/kaggle-mixin/skills/kaggle-cli/references
COPY skills/kaggle-cli/SKILL.md /usr/share/kaggle-mixin/skills/kaggle-cli/SKILL.md
COPY skills/kaggle-cli/references/ /usr/share/kaggle-mixin/skills/kaggle-cli/references/

USER agent
