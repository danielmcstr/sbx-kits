const fs = require("fs");
const path = require("path");

const home = process.env.HOME || "/home/agent";
const configDir = path.join(home, ".gemini", "config");
const configPath = path.join(configDir, "mcp_config.json");

const entry = {
  command: "/opt/playwright-mcp-mixin/runtime/bin/node",
  args: [
    "/opt/playwright-mcp-mixin/node_modules/@playwright/mcp/cli.js",
    "--headless",
    "--no-sandbox",
    "--browser",
    "chromium",
  ],
  env: {
    PLAYWRIGHT_BROWSERS_PATH: "/opt/playwright-mcp-mixin/browsers",
    LD_LIBRARY_PATH: "/opt/playwright-mcp-mixin/libs",
  },
};

fs.mkdirSync(configDir, { recursive: true });

let config = {};
if (fs.existsSync(configPath)) {
  const raw = fs.readFileSync(configPath, "utf8").trim();
  if (raw) {
    config = JSON.parse(raw);
  }
}

config.mcpServers = config.mcpServers || {};
config.mcpServers.playwright = entry;

fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`);
fs.chmodSync(configPath, 0o600);
