# syntax=docker/dockerfile:1
FROM docker.io/sbx/shell-docker-image:latest

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-venv \
    ca-certificates \
    openssh-client \
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

# Configure /opt/colab/venv OAuth via a .pth hook (immune to system sitecustomize.py):
# - routes colab token exchanges to accounts.google.com/o/oauth2/token
# - sends client_id in POST body (RFC 6749 client_secret_post) through sbx proxy
# - fills bundled client_id/client_secret when loading proxy-seeded sentinel token.json
COPY _sbx_colab_oauth.py /tmp/_sbx_colab_oauth.py
RUN SITE_PACKAGES=$(/opt/colab/venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))') \
    && install -m 0644 /tmp/_sbx_colab_oauth.py "$SITE_PACKAGES/_sbx_colab_oauth.py" \
    && printf 'import _sbx_colab_oauth\n' > "$SITE_PACKAGES/sbx_colab_oauth.pth" \
    && chmod 0644 "$SITE_PACKAGES/sbx_colab_oauth.pth" \
    && rm -f /tmp/_sbx_colab_oauth.py

# Stage bundled skill for sandbox skill linking
RUN mkdir -p /usr/share/colab-mixin/skills/colab-operator
COPY skills/colab-operator/SKILL.md /usr/share/colab-mixin/skills/colab-operator/SKILL.md

USER agent
