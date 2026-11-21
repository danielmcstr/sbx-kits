# Execution Plan: Modular Docker Sandbox Kits Repository (`sbx-kits`)

## Objective
Create a modular Docker Sandbox Kit v3 repository containing an Antigravity workload, four independent mixins (`python-ml-mixin`, `colab-mixin`, `kaggle-mixin`, `playwright-mcp-mixin`), and a master kit set (`agy-colab-kaggle-kit`), complete with zero-trust proxy credentials, headless keyring configurations, and automated skill linking. The Playwright MCP mixin is an optional plugin selected ad hoc and is intentionally excluded from the master set.

---

## Phase 1: Directory Scaffold & Base Workload (`antigravity-kit-v3`)

### Step 1.1: Create Directory Structure
Instruct the agent to create the exact directory tree:
```bash
mkdir -p kits/antigravity-kit-v3
mkdir -p kits/python-ml-mixin
mkdir -p kits/colab-mixin
mkdir -p kits/kaggle-mixin
mkdir -p kits/playwright-mcp-mixin
mkdir -p kits/agy-colab-kaggle-kit
```

### Step 1.2: Populate `kits/antigravity-kit-v3/`
1. **`antigravity.dockerfile`**: Base on `docker.io/sbx/antigravity-image:latest`, create user/workspace directories, and set entrypoint to `agy --dangerously-skip-permissions`.
2. **`antigravity.yaml`**: Define `kind: workload`, register `com.docker.sandbox/agent-skills@1` pointing to `/home/agent/.gemini/config/skills`, enable `git-identity@1`, allow network egress domains, and configure optional proxy-managed `GEMINI_API_KEY` and Google OAuth credentials plus the Antigravity settings lifecycle hook.
3. **`antigravity-context.md`**: Add core agent context rules.

---

## Phase 2: Create Modular Toolchain & Skill Mixins

### Step 2.1: Populate `kits/python-ml-mixin/` (uv, ruff, jupytext, nbstripout)
1. **`python-ml.dockerfile`**: Multi-stage build copying binaries from Astral's official images (`uv`, `ruff`) and installing `jupytext` and `nbstripout` in `/opt/python-ml/venv`. Stage `notebook-uv-workflow/SKILL.md`.
2. **`SKILL.md`**: Write the notebook workflow guidelines (percent scripts, sync before push, local ruff/uv checks).
3. **`python-ml.yaml`**: Define `kind: mixin`, `provides: [uv, ruff, jupytext, nbstripout]`, network policy (`pypi.org`), and `agent-skill@1`.

### Step 2.2: Populate `kits/colab-mixin/` (Google Colab CLI + Keyring)
1. **`keyringrc.cfg`**: Configure `keyrings.alt.file.PlaintextKeyring`.
2. **`colab.dockerfile`**: Install `google-colab-cli`, `keyring`, and `keyrings.alt` in `/opt/colab/venv`, export `colab skill` to `/usr/share/colab-mixin/skills/colab-operator/SKILL.md`, and symlink `colab`.
3. **`colab.yaml`**: Define `kind: mixin`, `provides: [colab]`, network policy for Google Colab/OAuth endpoints, `credential@1` for OAuth token exchanges (`google-colab`), and `agent-skill@1`.

### Step 2.3: Populate `kits/kaggle-mixin/` (Kaggle CLI + Official Skill)
1. **`kaggle.dockerfile`**: Install `kaggle` in `/opt/kaggle/venv`, sparse-clone the official skills directory (`SKILL.md` + `references/*.md`) from `https://github.com/Kaggle/kaggle-cli`, and symlink `kaggle`.
2. **`kaggle.yaml`**: Define `kind: mixin`, `provides: [kaggle]`, network policy for Kaggle APIs, `credential@1` for proxy-managed `KAGGLE_API_TOKEN` injection, and `agent-skill@1`.

### Step 2.4: Populate `kits/playwright-mcp-mixin/` (Optional Playwright MCP Plugin)
1. **`playwright-mcp.dockerfile`**: Build a Debian Bookworm `browser-env` stage with Node 20, `@playwright/mcp`, headless Chromium, and its runtime libraries; copy the runtime, browsers, and staged library closure into an `docker.io/sbx/antigravity-image:latest` final base, then stage the MCP config installer and browser-automation skill.
2. **`install-mcp-config.js`**: Idempotently merge a `playwright` stdio entry into `~/.gemini/config/mcp_config.json` without replacing other MCP servers.
3. **`playwright-mcp.yaml`**: Define `kind: mixin`, `provides: [playwright-mcp]`, runtime egress `*`, `agent-skill@1`, and a lifecycle install hook. Keep this mixin out of `agy-colab-kaggle-kit`.

---

## Phase 3: Master Kit Set & Verification

### Step 3.1: Populate `kits/agy-colab-kaggle-kit/agy-colab-kaggle.yaml`
1. **`agy-colab-kaggle.yaml`**: Define `kind: set` combining the workload and all three modular mixins.

### Step 3.2: Local Validation & Dry Run
Instruct the agent to run local checks on your host machine. These are v3 source kits, so `sbx kit validate` (v1/v2 tooling) does not apply; use the BuildKit frontend with a `docker-container` builder:
```bash
# 1. Create a builder that preserves v3 descriptor annotations
docker buildx inspect kit-builder >/dev/null 2>&1 || \
  docker buildx create --name kit-builder --driver docker-container --bootstrap

# 2. Validate each v3 source kit descriptor and recipe
for entry in \
  antigravity-kit-v3:antigravity.yaml \
  python-ml-mixin:python-ml.yaml \
  colab-mixin:colab.yaml \
  kaggle-mixin:kaggle.yaml \
  playwright-mcp-mixin:playwright-mcp.yaml; do
  dir=${entry%%:*}; file=${entry#*:}
  (cd "kits/$dir" && docker buildx build --builder kit-builder . -f "$file" --output type=cacheonly)
done

# 3. Inspect resolved declarations without starting a sandbox.
#    The sandbox builder is required; the default docker driver cannot export OCI layouts.
#    Do not inspect the set yet: its members must be pushed to OCI first (see step 4).
SBX_KIT_BUILDER=sandbox sbx kit inspect ./kits/python-ml-mixin

# 4. Test local composition and boot the interactive sandbox.
#    Keep SBX_KIT_BUILDER=sandbox on every local run; the default docker driver
#    fails with "OCI exporter is not supported for the docker driver".
SBX_KIT_BUILDER=sandbox sbx run ./kits/antigravity-kit-v3 \
  --kit ./kits/python-ml-mixin \
  --kit ./kits/colab-mixin \
  --kit ./kits/kaggle-mixin \
  --kit-arg auth_method=consumer \
  .

# 5. Add optional plugin mixins ad hoc when needed
SBX_KIT_BUILDER=sandbox sbx run ./kits/antigravity-kit-v3 \
  --kit ./kits/playwright-mcp-mixin \
  --kit-arg auth_method=consumer \
  .
```

### Step 3.3: In-Sandbox Verification
Verify the private Docker Engine and toolchain from the host:
```bash
sbx exec sbx-kits-final sh -lc 'docker info --format "{{.ServerVersion}} {{.Driver}}"; docker run --rm alpine:3.20 echo nested-ok; uv --version; ruff --version; jupytext --version; nbstripout --version; kaggle --version; colab -h'
```

Inside the running `agy` session, verify that:
* Typing `/skills` shows **`notebook-uv-workflow`**, **`colab-operator`**, and **`kaggle-cli`**, plus **`browser-automation`** when the Playwright MCP mixin was selected.
* Running `colab sessions` and `kaggle datasets list` succeeds without keyring errors or unproxied secrets.
