---
name: colab-operator
description: Operate Google Colab environments via the colab CLI. Use when asked to create or manage GPU/TPU sessions, run Python/shell on a remote Colab VM, sync files, install packages, or export session history.
---

# Google Colab Operator Skill

Operate remote Google Colab VMs via the `colab` CLI (`google-colab-cli`) inside a zero-trust Docker Sandbox.

## Mental Model
- **A session is a live Jupyter kernel on a rented VM.** `colab new -s <name>` allocates a billable VM; `colab stop -s <name>` releases it.
- **Kernel state persists across `colab exec` calls in the same session.** Variables, imports, and functions survive between invocations until `colab restart-kernel -s <name>` or `colab stop -s <name>`.
- **Default working directory on the VM is `/content`.** Prefer absolute paths (`/content/...`) for remote files.
- **Named vs. orphan `[?]` sessions:** `colab sessions` lists all server-side assignments. Runtimes not created by this CLI (e.g., opened in a browser) appear as `[?] <endpoint>` and are not in `~/.config/colab-cli/sessions.json`, so `colab status` / `colab exec -s <name>` will not find them — always create a named session with `colab new -s <name>`.

## Zero-Trust Authentication (Docker Sandbox)
- OAuth credentials for `google-colab` are **proxy-managed** by Docker Sandbox:
  - Inside the sandbox, `~/.config/colab-cli/token.json` and the headless `PlaintextKeyring` only ever hold sentinel tokens (`colab-at-proxy-managed` / `colab-rt-proxy-managed`). Real access and refresh tokens remain exclusively on the host.
  - On first use (when no `google-colab` host binding exists yet), a human runs `colab sessions` once and completes the copy-paste OAuth consent flow. The sandbox proxy intercepts `accounts.google.com/o/oauth2/token`, stores the real tokens on the host, and returns sentinels to the container. All future sandboxes are pre-seeded automatically.
- **Verify auth with `colab sessions` or `colab usage`.** Do **not** use `colab whoami` inside the sandbox — `whoami` sends the access token in a URL query parameter (`?access_token=...`) rather than an `Authorization: Bearer` header, so the zero-trust proxy intentionally leaves the sentinel unmasked.

## Common Operations

### Provision & Manage Sessions
```bash
# Verify auth and list server-side assignments
colab sessions

# Check compute-unit balance and usage rate
colab usage

# Create a named CPU session (always pass -s <name>)
colab new -s work

# Create a GPU or TPU session
# Supported --gpu: T4, L4, G4, A100, H100 | Supported --tpu: v5e1, v6e1
colab new -s train --gpu T4

# Inspect session hardware and IDLE/BUSY state
colab status -s work

# Release the VM when done (stops billing)
colab stop -s work
```

### Execute Code & Scripts
```bash
# Preferred: execute a local Python script on the remote kernel
colab exec -s work -f script.py

# Execute piped Python code
echo "import torch; print(torch.cuda.is_available())" | colab exec -s work

# Pass environment variables safely to the remote kernel
colab exec -s work --env DATA_DIR=/content/data -f train.py

# Ephemeral one-shot job (provisions VM, runs Python script, then releases VM)
colab run --gpu T4 train.py --epochs 5
```

### Files, Packages, SSH & Logs
```bash
# Install packages on the remote VM
colab install -s work torch transformers
colab install -s work -r requirements.txt

# File transfer & inspection
colab ls -s work /content
colab upload -s work local_data.csv /content/local_data.csv
colab download -s work /content/model.pt ./model.pt
colab rm -s work /content/temp.bin

# One-shot shell command on the VM (requires an ed25519/ecdsa key or -i KEY)
colab ssh -s work -- 'nvidia-smi | head -n 10'

# Export session history as a Jupyter notebook or markdown
colab log -s work -o session_export.ipynb
```

## Safety & Agent Rules
- Never run interactive TTY commands (`colab repl`, bare `colab ssh`, `colab auth`, `colab drivemount`) from an automated agent turn — they expect a human terminal and will hang.
- Always release VMs with `colab stop -s <name>` when finished, or use `colab run` for ephemeral one-shot jobs.
