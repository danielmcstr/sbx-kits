---
name: colab-operator
description: Manage Google Colab sessions, execute remote notebooks, and inspect active kernels using the colab CLI.
---

# Google Colab Operator Skill

## Overview
Control Google Colab runtimes, upload notebooks, inspect session state, and leverage cloud accelerator hardware (GPU/TPU) from the sandbox.

## Authentication
OAuth credentials for Google Colab are transparently managed by the Docker Sandbox proxy.
The headless keyring backend (`keyrings.alt.file.PlaintextKeyring`) stores session tokens non-interactively.

## Common Operations
```bash
# List active Colab notebook sessions
colab sessions

# Open or launch notebook on Colab
colab open <path-to-notebook.ipynb>

# Execute a notebook on remote Colab runtime
colab run <path-to-notebook.ipynb>
```
