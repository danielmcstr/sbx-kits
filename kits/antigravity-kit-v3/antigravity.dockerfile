# syntax=docker/dockerfile:1
ARG BASE_IMAGE=docker.io/sbx/antigravity-image:latest
FROM ${BASE_IMAGE}

USER root
# Ensure workspace and agent config directories exist with proper permissions
RUN mkdir -p /home/agent/workspace /home/agent/.gemini/config/skills /home/agent/.config/sbx-agy \
    && chown -R agent:agent /home/agent

# Install workspace-backed session persistence helper and TTY-safe entrypoint
COPY agy_session_sync.py /usr/local/bin/agy-session
COPY agy-entrypoint.sh /usr/local/bin/agy-entrypoint
RUN chmod 0755 /usr/local/bin/agy-session /usr/local/bin/agy-entrypoint

USER agent
WORKDIR /home/agent/workspace

ENTRYPOINT ["/usr/local/bin/agy-entrypoint"]
