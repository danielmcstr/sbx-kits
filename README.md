# Modular Docker Sandbox Kits (`sbx-kits`)

A modular, production-ready repository of Docker Sandbox Kit v3 packages. It provides an Antigravity agent workload (`antigravity-kit-v3`), three independent toolchain and skill mixins (`python-ml-mixin`, `colab-mixin`, `kaggle-mixin`), and a master kit set (`agy-colab-kaggle-kit`).

Built with zero-trust proxy credential injection, headless keyring management, and automated agent skill linking.

---

## Architecture Overview

```
sbx-kits/
├── kits/
│   ├── antigravity-kit-v3/       # Base Agent Workload (kind: workload)
│   │   ├── antigravity.yaml       # v3 Workload Descriptor (skills, git-identity, Gemini proxy)
│   │   ├── antigravity.dockerfile # Runtime container recipe
│   │   └── antigravity-context.md # Agent operating instructions
│   ├── python-ml-mixin/          # Python Toolchain Mixin (kind: mixin)
│   │   ├── python-ml.yaml         # Mixin Descriptor (uv, ruff, jupytext, nbstripout)
│   │   ├── python-ml.dockerfile   # Multi-stage binary install & venv recipe
│   │   └── skills/                # Agent Skill: notebook-uv-workflow
│   ├── colab-mixin/              # Google Colab Mixin (kind: mixin)
│   │   ├── colab.yaml             # Mixin Descriptor (OAuth proxy, Colab APIs)
│   │   ├── colab.dockerfile       # Colab CLI & keyring installer
│   │   ├── keyringrc.cfg          # PlaintextKeyring backend configuration
│   │   └── skills/                # Agent Skill: colab-operator
│   ├── kaggle-mixin/             # Kaggle Mixin (kind: mixin)
│   │   ├── kaggle.yaml            # Mixin Descriptor (proxy-managed token)
│   │   ├── kaggle.dockerfile      # Kaggle CLI installer & staged skills
│   │   └── skills/                # Agent Skill: kaggle-cli + references
│   ├── playwright-mcp-mixin/      # Optional Plugin Mixin (kind: mixin)
│   │   ├── playwright-mcp.yaml    # Mixin Descriptor (MCP config + browser egress)
│   │   ├── playwright-mcp.dockerfile # Node 20, Playwright MCP, headless Chromium
│   │   ├── install-mcp-config.js  # Idempotent ~/.gemini/config/mcp_config.json merge
│   │   └── skills/                # Agent Skill: browser-automation
│   └── agy-colab-kaggle-kit/      # Master Set (kind: set)
│       └── agy-colab-kaggle.yaml  # Unified composition descriptor
├── tests/
│   └── test_sbx_kits_e2e.py       # E2E validation and conformance test suite
└── docs/
    └── EXECUTION_PLAN.md          # Architectural execution plan
```

---

## Included Kits & Capabilities

| Kit | Kind | Provided Tools | Injected Skills | Network & Credential Grants |
| :--- | :--- | :--- | :--- | :--- |
| **`antigravity-kit-v3`** | `workload` | `antigravity`, `agy` | Skill mount point: `~/.gemini/config/skills` | `generativelanguage.googleapis.com`<br>`api.github.com`<br>`GEMINI_API_KEY` proxy injection<br>Google OAuth proxy session |
| **`python-ml-mixin`** | `mixin` | `uv`, `ruff`, `jupytext`, `nbstripout` | `notebook-uv-workflow` | `pypi.org`, `files.pythonhosted.org` |
| **`colab-mixin`** | `mixin` | `colab` | `colab-operator` | `colab.research.google.com`, `oauth2.googleapis.com`<br>Headless `PlaintextKeyring` |
| **`kaggle-mixin`** | `mixin` | `kaggle` | `kaggle-cli` | `api.kaggle.com`, `storage.googleapis.com`<br>`KAGGLE_API_TOKEN` proxy injection |
| **`playwright-mcp-mixin`** | `mixin` | `playwright-mcp` | `browser-automation` | `*` (browser egress)<br>Local stdio MCP server, no credentials |
| **`agy-colab-kaggle-kit`** | `set` | *All 8 tools combined* | *All 3 skills combined* | Complete merged policy; excludes Playwright MCP |

---

## How to Use

### 1. Prerequisites
- Docker Engine with Buildx support
- Docker Sandbox CLI (`sbx`)
- Python 3.9+ (for running validation test suites)

### 2. Validate Kit Schemas

These are Docker Sandbox Kit **v3 source kits**. `sbx kit validate` is a v1/v2 command and rejects them; validate with the BuildKit frontend instead. Use a `docker-container` builder so descriptor annotations survive export:
```bash
docker buildx inspect kit-builder >/dev/null 2>&1 || \
  docker buildx create --name kit-builder --driver docker-container --bootstrap

for entry in \
  antigravity-kit-v3:antigravity.yaml \
  python-ml-mixin:python-ml.yaml \
  colab-mixin:colab.yaml \
  kaggle-mixin:kaggle.yaml \
  playwright-mcp-mixin:playwright-mcp.yaml; do
  dir=${entry%%:*}; file=${entry#*:}
  (cd "kits/$dir" && docker buildx build --builder kit-builder . -f "$file" --output type=cacheonly)
done
```

Inspect the resolved declarations without starting a sandbox. Keep the `SBX_KIT_BUILDER=sandbox` prefix; without it `sbx` uses the default `docker` driver, which cannot export the OCI layout this error reports:
```bash
SBX_KIT_BUILDER=sandbox sbx kit inspect ./kits/python-ml-mixin
```

The same command on `./kits/agy-colab-kaggle-kit` will still fail until the four member images are pushed, because v3 sets must reference published OCI images. Until then, use the local `sbx run` composition in step 3. Its composition is also checked statically by the built-in conformance suite:
```bash
python3 tests/test_sbx_kits_e2e.py
```

### 3. Run Locally (No Push Required)

You can run sandboxes directly from local kit source directories using `sbx run`. Keep the `SBX_KIT_BUILDER=sandbox` prefix on every local run; the default `docker` driver fails with `OCI exporter is not supported for the docker driver`. Local Python/Colab/Kaggle mixins share `docker.io/sbx/shell-docker-image:latest` as their base so the in-sandbox Docker daemon and CLI shims survive composition. The optional Playwright mixin uses `docker.io/sbx/antigravity-image:latest` as its final base and stages Node, Chromium, and the browser runtime libraries under `/opt/playwright-mcp-mixin`.

#### Run with Individual Mixins:
```bash
SBX_KIT_BUILDER=sandbox sbx run ./kits/antigravity-kit-v3 \
  --kit ./kits/python-ml-mixin \
  --kit ./kits/colab-mixin \
  --kit ./kits/kaggle-mixin \
  --kit-arg auth_method=consumer \
  .
```

#### Add Optional Plugin Mixins Ad Hoc:

Plugin mixins are not part of the master set. Add only the ones a session needs:
```bash
SBX_KIT_BUILDER=sandbox sbx run ./kits/antigravity-kit-v3 \
  --kit ./kits/playwright-mcp-mixin \
  --kit-arg auth_method=consumer \
  .
```

Use `--kit-arg auth_method=gcp --kit-arg gcp_project=<project> --kit-arg gcp_location=<location>` for Google Cloud / Gemini Enterprise OAuth sessions. An Antigravity session can use the proxy-managed Google OAuth binding, the `GEMINI_API_KEY` binding, or both.

#### Run the Master Composed Set:
```bash
SBX_KIT_BUILDER=sandbox sbx run ./kits/agy-colab-kaggle-kit .
```

### 4. Build and Publish Kits to OCI Registry

Each kit uses `# syntax=docker/sandbox-kit:3`, enabling direct builds with BuildKit. Select the `kit-builder` created in step 2; the default `docker` driver can drop the descriptor annotations:

```bash
# Build kit images
docker buildx build --builder kit-builder -f kits/antigravity-kit-v3/antigravity.yaml -t danielmcstr/sbx-kit-antigravity:latest --push .
docker buildx build --builder kit-builder -f kits/python-ml-mixin/python-ml.yaml -t danielmcstr/sbx-kit-python-ml:latest --push .
docker buildx build --builder kit-builder -f kits/colab-mixin/colab.yaml -t danielmcstr/sbx-kit-colab:latest --push .
docker buildx build --builder kit-builder -f kits/kaggle-mixin/kaggle.yaml -t danielmcstr/sbx-kit-kaggle:latest --push .
docker buildx build --builder kit-builder -f kits/playwright-mcp-mixin/playwright-mcp.yaml -t danielmcstr/sbx-kit-playwright-mcp:latest --push .

# Build and publish the master set
docker buildx build --builder kit-builder -f kits/agy-colab-kaggle-kit/agy-colab-kaggle.yaml -t danielmcstr/sbx-kit-agy-colab-kaggle:latest --push .
```

### 5. In-Sandbox Verification

Once inside the interactive Antigravity sandbox session:

1. **Verify Registered Skills**:
   Type `/skills` or inspect the linked directory:
   ```bash
   ls -la /home/agent/.gemini/config/skills
   ```
   You will see:
    - `notebook-uv-workflow`
    - `colab-operator`
    - `kaggle-cli`
    - `browser-automation` when `playwright-mcp-mixin` was selected

2. **Verify Toolchains**:

   ```bash
   uv --version
   ruff --version
   jupytext --version
   nbstripout --version
   colab --help
   kaggle --help
   ```

3. **Verify Zero-Trust Proxy Authentication**:
   - Google Colab:
     ```bash
     colab sessions
     ```
     *Executes using headless keyring without prompting for GUI authentication.*
    - Kaggle CLI:
      ```bash
      kaggle datasets list
      ```
      *Executes securely using the proxy-injected `KAGGLE_API_TOKEN`.*
    - Antigravity OAuth:
      ```bash
      cat ~/.gemini/antigravity-cli/antigravity-oauth-token
      ```
      *Shows proxy sentinel tokens only; the real tokens stay host-side.*

4. **Verify Optional Playwright MCP** (when selected):
   ```bash
   cat ~/.gemini/config/mcp_config.json
   ```
   The `playwright` stdio entry launches headless Chromium through the bundled Node runtime.

---


## Security Model

- **Least-Privilege Egress**: Every mixin specifies strict host-level network allowlists in `com.docker.sandbox/network-policy@1`.
- **Zero-Trust Proxied Credentials**: Secrets (`GEMINI_API_KEY`, `KAGGLE_API_TOKEN`, OAuth tokens) never enter the container in plaintext. The host sandbox proxy transparently intercepts API requests to designated hosts and injects the authorization headers.
- **Rootless Execution**: Workloads and mixins run unprivileged under the `agent` user (`UID 1000`).
