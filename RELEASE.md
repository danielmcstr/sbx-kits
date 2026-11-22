# Release Process

This document explains how to version, tag, publish, and verify a new release of `sbx-kits`.

---

## Versioning Policy

- **Repository releases** use Semantic Versioning git tags prefixed with `v`:
  - Stable releases: `vMAJOR.MINOR.PATCH` (for example, `v1.0.0`, `v1.1.0`, `v1.1.1`)
  - Pre-releases: `vMAJOR.MINOR.PATCH-<label>` (for example, `v1.1.0-rc.1`, `v1.2.0-beta.1`)
- **Per-kit descriptor versions** (`version:` in each `kits/*/*.yaml`) are versioned **independently**. Only bump `version:` inside the specific kit descriptor(s) whose image, tools, skills, or capabilities changed.
- **GHCR container tags** published automatically by CI:

| Trigger | Tags published to `ghcr.io/danielmcstr/sbx-kits/<name>` | Updates `:latest`? | Creates GitHub Release? |
| :--- | :--- | :--- | :--- |
| Push to `main` | `:latest`, `:sha-<short>` | Yes | No |
| Stable tag (`v1.2.3`) | `:1.2.3`, `:1.2`, `:latest`, `:sha-<short>` | Yes | Yes (Latest release) |
| Pre-release tag (`v1.2.3-rc.1`) | `:1.2.3-rc.1`, `:sha-<short>` | **No** | Yes (Pre-release) |

- **Master kit set reproducibility:** In git, `kits/agy-colab-kaggle/agy-colab-kaggle.yaml` references `:latest` for ongoing `main` builds. When CI builds a tagged release (`vX.Y.Z`), it automatically pins the 4 member refs in `agy-colab-kaggle.yaml` to `:X.Y.Z` so every versioned set release resolves the exact member kit versions built for that release.

---

## Pre-Release Checklist

1. **Sync `main` and ensure a clean working tree:**
   ```bash
   git checkout main
   git pull origin main
   git status
   ```
2. **Bump per-kit `version:` fields** in any modified kit descriptor(s) (`kits/*/*.yaml`), if not already updated in the feature/fix commit(s).
3. **Run the conformance test suite locally:**
   ```bash
   python3 tests/test_sbx_kits_e2e.py
   ```
4. *(Optional)* Run a local BuildKit dry-run across modified kits (see step 3 in [README.md](README.md)).
5. **Push any pending commits to `main`** and confirm the `main` build is green.

> **Important:** CI rejects tags that do not match strict semver or whose commit is not reachable from `origin/main`. Always tag a commit already pushed to `main`.

---

## Cutting a Release

Create an annotated semver tag on `main` and push it to GitHub:

```bash
# Stable release example
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

For a pre-release candidate (does **not** move `:latest`):

```bash
git tag -a v1.1.0-rc.1 -m "Release v1.1.0-rc.1"
git push origin v1.1.0-rc.1
```

---

## What Happens Automatically in CI

Pushing a `v*` tag triggers [`.github/workflows/publish-kits.yml`](.github/workflows/publish-kits.yml) in four strictly gated stages:

1. **`validate`**:
   - Verifies the tag matches `^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$`.
   - Verifies the tagged commit is an ancestor of `origin/main`.
   - Runs `python3 tests/test_sbx_kits_e2e.py`.
2. **`build-kits`** *(runs only if `validate` passes)*:
   - Builds and pushes all 5 leaf kits (`antigravity`, `python-ml`, `colab`, `kaggle`, `playwright-mcp`) to `ghcr.io/danielmcstr/sbx-kits/*`.
3. **`build-set`** *(runs only if all 5 leaf kits succeed)*:
   - Pins the 4 member refs in `agy-colab-kaggle.yaml` to `:<version>` and pushes `ghcr.io/danielmcstr/sbx-kits/agy-colab-kaggle:<version>`.
4. **`release`** *(runs only if `validate`, `build-kits`, and `build-set` all pass on a `v*` tag)*:
   - Inspects the live OCI digests (`sha256:...`) of all 6 published images.
   - Generates release notes combining pinned `sbx run` quickstart commands, an image/digest table (including each kit's descriptor version), and GitHub's auto-generated changelog.
   - Creates (or updates on re-run) the GitHub Release, marking tags with `-` as pre-releases.

Monitor progress from your terminal:

```bash
gh run list --limit 3
gh run watch
```

---

## Post-Release Verification

1. **Check the GitHub Release page** at `https://github.com/danielmcstr/sbx-kits/releases` and verify all 6 image tags and SHA256 digests are listed.
2. **Verify package visibility** (especially on the first release of any new kit) at `https://github.com/danielmcstr?tab=packages` — ensure all packages are set to **Public**.
3. **Verify anonymous pull of the pinned release tag:**
   ```bash
   docker logout ghcr.io
   SBX_KIT_BUILDER=sandbox sbx kit inspect ghcr.io/danielmcstr/sbx-kits/agy-colab-kaggle:1.0.0
   ```

---

## Hotfixes & Rollbacks

- **Never overwrite an existing published semver tag.** Container digests and semver tags should remain immutable so users pinning `:1.0.0` get consistent builds.
- If a regression is discovered after release:
  1. Fix or revert the change on `main` (this immediately updates `:latest` on push).
  2. Cut a new patch release (`v1.0.1`) following the standard procedure above.
  3. Optionally mark the affected GitHub Release notes with a warning pointing users to the patched version.
