# syntax=docker/dockerfile:1
FROM node:20-bookworm-slim AS browser-env

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/playwright-mcp-mixin/runtime \
    && cp -a /usr/local/. /opt/playwright-mcp-mixin/runtime/

ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-mcp-mixin/browsers

RUN npm install --prefix /opt/playwright-mcp-mixin \
    @playwright/mcp@0.0.86 \
    && /opt/playwright-mcp-mixin/runtime/bin/node \
      /opt/playwright-mcp-mixin/node_modules/playwright/cli.js \
      install chromium

RUN set -eu; \
    browser=$(find /opt/playwright-mcp-mixin/browsers -name chrome-headless-shell -type f -print -quit); \
    mkdir -p /opt/playwright-mcp-mixin/libs; \
    printf '%s\n' "$browser" > /tmp/ldd-targets; \
    i=0; \
    while [ "$i" -lt 6 ]; do \
      while read -r target; do \
        ldd "$target" 2>/dev/null | awk '/=> \// {print $3}' || true; \
      done < /tmp/ldd-targets | sort -u > /tmp/ldd-next; \
      : > /tmp/ldd-targets.new; \
      while read -r lib; do \
        case "$lib" in \
          */libc.so.6|*/libpthread.so.0|*/libdl.so.2|*/libm.so.6|*/librt.so.1|*/libgcc_s.so.1|*/libstdc++.so.6|*/libsystemd.so.0|*/libudev.so.1|*/ld-linux-x86-64.so.2) continue ;; \
        esac; \
        cp -L "$lib" /opt/playwright-mcp-mixin/libs/ 2>/dev/null || true; \
        printf '%s\n' "$lib" >> /tmp/ldd-targets.new; \
      done < /tmp/ldd-next; \
      cp /tmp/ldd-targets.new /tmp/ldd-targets; \
      i=$((i + 1)); \
    done; \
    chmod -R a+rX /opt/playwright-mcp-mixin

FROM docker.io/sbx/antigravity-image:latest

USER root

COPY --from=browser-env /opt/playwright-mcp-mixin /opt/playwright-mcp-mixin
COPY --chmod=0644 install-mcp-config.js /opt/playwright-mcp-mixin/install-mcp-config.js
RUN mkdir -p /usr/share/playwright-mcp-mixin/skills/browser-automation \
    && chmod -R a+rX /usr/share/playwright-mcp-mixin
COPY --chmod=0644 skills/browser-automation/SKILL.md /usr/share/playwright-mcp-mixin/skills/browser-automation/SKILL.md

USER agent
