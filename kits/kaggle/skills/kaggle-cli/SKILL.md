---
name: kaggle-cli
description: Interact with Kaggle datasets, competitions, kernels (notebooks), and models using the official kaggle CLI.
---

# Kaggle CLI Skill

## Overview
Automate Kaggle workflows including searching and downloading competition data, submitting predictions, pulling and pushing notebook kernels, and managing models.

## Authentication
Authentication is managed transparently by the Docker Sandbox proxy.
The environment supplies proxy-managed `KAGGLE_API_TOKEN` (or `KAGGLE_USERNAME` and `KAGGLE_KEY`) automatically to all Kaggle API requests.

## Common Operations

### Competitions
```bash
# List active competitions
kaggle competitions list

# Download competition data
kaggle competitions download -c <competition-name>

# Submit prediction file
kaggle competitions submit -c <competition-name> -f submission.csv -m "Model submission"

# Check submission status and leaderboard
kaggle competitions submissions -c <competition-name>
kaggle competitions leaderboard -c <competition-name> --show
```

### Datasets
```bash
# Search datasets
kaggle datasets list -s "dataset-query"

# Download and unzip dataset files
kaggle datasets download -d <owner>/<dataset-name> --unzip -p ./data
```

### Kernels / Notebooks
```bash
# Pull notebook files and metadata
kaggle kernels pull <owner>/<kernel-slug> -p ./kernel

# Push updated notebook to Kaggle
kaggle kernels push -p ./kernel
```

### Models
```bash
# Search published models
kaggle models list -s "llama"
```

For advanced usage, refer to the files in `references/`.
