# syntax=docker/dockerfile:1
FROM docker.io/sbx/shell-docker-image:latest

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-venv \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install headless keyring configuration system-wide and in default XDG paths
RUN mkdir -p /etc/xdg/python_keyring
COPY keyringrc.cfg /etc/xdg/python_keyring/keyringrc.cfg

# Install google-colab-cli and keyring backends in dedicated venv
RUN python3 -m venv /opt/colab/venv \
    && /opt/colab/venv/bin/pip install --no-cache-dir \
       keyring \
       keyrings.alt \
       google-colab-cli \
    && ln -s /opt/colab/venv/bin/colab /usr/local/bin/colab

# Stage bundled skill for sandbox skill linking
RUN mkdir -p /usr/share/colab-mixin/skills/colab-operator
COPY skills/colab-operator/SKILL.md /usr/share/colab-mixin/skills/colab-operator/SKILL.md

USER agent
