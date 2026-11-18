# Antigravity Sandbox Agent Context

## Operating Environment
- Primary workspace: `/home/agent/workspace`.
- Execution user: Non-root user `agent` (`uid=1000`).
- Privilege policy: Run all commands unprivileged in user space; do not attempt `sudo` or modify system roots.

## Tooling & Skills Discovery
- Dynamic mixin skills are automatically linked into `/home/agent/.gemini/config/skills`.
- Inspect active skills via `/skills` or within the skill configuration path.
- Available toolchains are staged under `/opt/<mixin-name>/` with binaries exposed on system `PATH`.

## Credentials & Zero-Trust Security
- Credentials (such as `GEMINI_API_KEY`, `KAGGLE_API_TOKEN`, OAuth tokens) are transparently injected by the Docker Sandbox proxy.
- Local values may contain sentinel proxy tokens. Never log, disclose, or attempt to overwrite proxy tokens with manual secrets.
