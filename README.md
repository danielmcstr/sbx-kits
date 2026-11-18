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
| **`antigravity-kit-v3`** | `workload` | `antigravity`, `agy` | Skill mount point: `~/.gemini/config/skills` | `generativelanguage.googleapis.com`<br>`api.github.com`<br>`GEMINI_API_KEY` proxy injection |
| **`python-ml-mixin`** | `mixin` | `uv`, `ruff`, `jupytext`, `nbstripout` | `notebook-uv-workflow` | `pypi.org`, `files.pythonhosted.org` |
| **`colab-mixin`** | `mixin` | `colab` | `colab-operator` | `colab.research.google.com`, `oauth2.googleapis.com`<br>Headless `PlaintextKeyring` |
| **`kaggle-mixin`** | `mixin` | `kaggle` | `kaggle-cli` | `api.kaggle.com`, `storage.googleapis.com`<br>`KAGGLE_API_TOKEN` proxy injection |
| **`agy-colab-kaggle-kit`** | `set` | *All 8 tools combined* | *All 3 skills combined* | Complete merged policy |

---

## How to Use

### 1. Prerequisites
- Docker Engine with Buildx support
- Docker Sandbox CLI (`sbx`)
- Python 3.9+ (for running validation test suites)

### 2. Validate Kit Schemas

Validate individual kit descriptors using `sbx`:
```bash
# Validate each kit descriptor
sbx kit validate ./kits/antigravity-kit-v3
sbx kit validate ./kits/python-ml-mixin
sbx kit validate ./kits/colab-mixin
sbx kit validate ./kits/kaggle-mixin
```

Alternatively, run the built-in end-to-end conformance test suite:
```bash
python3 tests/test_sbx_kits_e2e.py
```

### 3. Run Locally (No Push Required)

You can run sandboxes directly from local kit source directories using `sbx run`:

#### Run with Individual Mixins:
```bash
sbx run ./kits/antigravity-kit-v3 \
  --kit ./kits/python-ml-mixin \
  --kit ./kits/colab-mixin \
  --kit ./kits/kaggle-mixin \
  .
```

#### Run the Master Composed Set:
```bash
sbx run ./kits/agy-colab-kaggle-kit .
```

### 4. Build and Publish Kits to OCI Registry

Each kit uses `# syntax=docker/sandbox-kit:3`, enabling direct builds with BuildKit:

```bash
# Build kit images
docker buildx build -f kits/antigravity-kit-v3/antigravity.yaml -t your-org/sbx-kit-antigravity:latest --push .
docker buildx build -f kits/python-ml-mixin/python-ml.yaml -t your-org/sbx-kit-python-ml:latest --push .
docker buildx build -f kits/colab-mixin/colab.yaml -t your-org/sbx-kit-colab:latest --push .
docker buildx build -f kits/kaggle-mixin/kaggle.yaml -t your-org/sbx-kit-kaggle:latest --push .

# Build and publish the master set
docker buildx build -f kits/agy-colab-kaggle-kit/agy-colab-kaggle.yaml -t your-org/sbx-kit-agy-colab-kaggle:latest --push .
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

---

## Security Model

- **Least-Privilege Egress**: Every mixin specifies strict host-level network allowlists in `com.docker.sandbox/network-policy@1`.
- **Zero-Trust Proxied Credentials**: Secrets (`GEMINI_API_KEY`, `KAGGLE_API_TOKEN`, OAuth tokens) never enter the container in plaintext. The host sandbox proxy transparently intercepts API requests to designated hosts and injects the authorization headers.
- **Rootless Execution**: Workloads and mixins run unprivileged under the `agent` user (`UID 1000`).
