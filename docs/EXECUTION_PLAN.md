# Execution Plan: Modular Docker Sandbox Kits Repository (`sbx-kits`)

## Objective
Create a modular Docker Sandbox Kit v3 repository containing an Antigravity workload, three independent mixins (`python-ml-mixin`, `colab-mixin`, `kaggle-mixin`), and a master kit set (`agy-colab-kaggle-kit`), complete with zero-trust proxy credentials, headless keyring configurations, and automated skill linking.

---

## Phase 1: Directory Scaffold & Base Workload (`antigravity-kit-v3`)

### Step 1.1: Create Directory Structure
Instruct the agent to create the exact directory tree:
```bash
mkdir -p kits/antigravity-kit-v3
mkdir -p kits/python-ml-mixin
mkdir -p kits/colab-mixin
mkdir -p kits/kaggle-mixin
mkdir -p kits/agy-colab-kaggle-kit
```

### Step 1.2: Populate `kits/antigravity-kit-v3/`
1. **`antigravity.dockerfile`**: Base on `docker.io/sbx/antigravity-image:latest`, create user/workspace directories, and set entrypoint to `agy --dangerously-skip-permissions`.
2. **`antigravity.yaml`**: Define `kind: workload`, register `com.docker.sandbox/agent-skills@1` pointing to `/home/agent/.gemini/config/skills`, enable `git-identity@1`, allow network egress domains, and configure the startup lifecycle hook for `GEMINI_API_KEY`.
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

---

## Phase 3: Master Kit Set & Verification

### Step 3.1: Populate `kits/agy-colab-kaggle-kit/agy-colab-kaggle.yaml`
1. **`agy-colab-kaggle.yaml`**: Define `kind: set` combining the workload and all three modular mixins.

### Step 3.2: Local Validation & Dry Run
Instruct the agent to run local checks on your host machine:
```bash
# 1. Validate each mixin spec schema
sbx kit validate ./kits/antigravity-kit-v3
sbx kit validate ./kits/python-ml-mixin
sbx kit validate ./kits/colab-mixin
sbx kit validate ./kits/kaggle-mixin

# 2. Test local composition and boot the interactive sandbox
sbx run ./kits/antigravity-kit-v3 \
  --kit ./kits/python-ml-mixin \
  --kit ./kits/colab-mixin \
  --kit ./kits/kaggle-mixin \
  .
```

### Step 3.3: In-Sandbox Verification
Inside the running `agy` session, verify that:
* Typing `/skills` shows **`notebook-uv-workflow`**, **`colab-operator`**, and **`kaggle-cli`**.
* Running `colab sessions` and `kaggle datasets list` succeeds without keyring errors or unproxied secrets.