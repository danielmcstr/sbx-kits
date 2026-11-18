# syntax=docker/dockerfile:1
FROM docker.io/sbx/antigravity-image:latest

USER root
# Ensure workspace and agent config directories exist with proper permissions
RUN mkdir -p /home/agent/workspace /home/agent/.gemini/config/skills \
    && chown -R agent:agent /home/agent

USER agent
WORKDIR /home/agent/workspace

ENTRYPOINT ["agy", "--dangerously-skip-permissions"]
