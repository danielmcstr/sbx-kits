#!/usr/bin/env python3
"""
End-to-End Validation and Conformance Test Suite for sbx-kits.

Validates:
1. Descriptor YAML formatting and schema versioning
2. Kit kind constraints and companion Dockerfile pairing
3. Capability configurations (network policies, credentials, skill links)
4. Skill YAML frontmatter and file existence
5. Master kit set composition, capability merging, and zero-trust proxy rules
"""

import sys
import os
import re
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path

# Color helpers
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

REPO_ROOT = Path(__file__).resolve().parent.parent
KITS_DIR = REPO_ROOT / "kits"

KNOWN_CAPABILITIES = {
    "com.docker.sandbox/sbx@1",
    "com.docker.sandbox/git-identity@1",
    "com.docker.sandbox/agent-skills@1",
    "com.docker.sandbox/agent-skill@1",
    "com.docker.sandbox/agent-context@1",
    "com.docker.sandbox/dockerd@1",
    "com.docker.sandbox/network-policy@1",
    "com.docker.sandbox/credential@1",
}


def parse_simple_yaml(text: str) -> dict:
    """Lightweight YAML parser for kit descriptors without external pip dependencies."""
    lines = text.splitlines()
    data = {"_raw_lines": lines}
    current_key = None
    sub_key = None
    list_target = None
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
            
        indent = len(line) - len(line.lstrip(" "))
        
        # Top-level keys
        if indent == 0 and ":" in stripped:
            parts = stripped.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            current_key = key
            sub_key = None
            list_target = None
            if val:
                data[key] = val.strip("\"'")
            else:
                data[key] = [] if key in ("provides", "kits", "capabilities") else {}
        elif indent == 2 and current_key:
            if stripped.startswith("- "):
                val = stripped[2:].strip().strip("\"'")
                if isinstance(data[current_key], list):
                    if ":" in val:
                        item_parts = val.split(":", 1)
                        data[current_key].append({item_parts[0].strip(): item_parts[1].strip().strip("\"'")})
                    else:
                        data[current_key].append(val)
            elif ":" in stripped:
                parts = stripped.split(":", 1)
                sub_key = parts[0].strip()
                val = parts[1].strip()
                if isinstance(data[current_key], dict):
                    data[current_key][sub_key] = val.strip("\"'") if val else {}
    return data


def test_kit_descriptors():
    print(f"\n{YELLOW}[1/6] Validating Kit Descriptors & Schemas...{RESET}")
    expected_kits = [
        ("antigravity", "antigravity.yaml", "workload"),
        ("python-ml", "python-ml.yaml", "mixin"),
        ("colab", "colab.yaml", "mixin"),
        ("kaggle", "kaggle.yaml", "mixin"),
        ("playwright-mcp", "playwright-mcp.yaml", "mixin"),
        ("agy-colab-kaggle", "agy-colab-kaggle.yaml", "set"),
    ]

    for kit_dir_name, yaml_filename, expected_kind in expected_kits:
        kit_path = KITS_DIR / kit_dir_name
        assert kit_path.is_dir(), f"Missing kit directory: {kit_dir_name}"
        
        yaml_path = kit_path / yaml_filename
        assert yaml_path.is_file(), f"Missing descriptor file: {yaml_path}"

        content = yaml_path.read_text(encoding="utf-8")
        assert content.startswith("# syntax=docker/sandbox-kit:3"), \
            f"{yaml_filename} must begin with # syntax=docker/sandbox-kit:3"
        
        assert 'schemaVersion: "3"' in content or "schemaVersion: '3'" in content, \
            f"{yaml_filename} missing schemaVersion: '3'"
        
        assert f"kind: {expected_kind}" in content, \
            f"{yaml_filename} expected kind '{expected_kind}'"

        parsed = parse_simple_yaml(content)
        if expected_kind != "set":
            assert "version" in parsed, \
                f"{yaml_filename} missing top-level version required for versioned provides"

        print(f"  ✓ {kit_dir_name}/{yaml_filename} [kind: {expected_kind}, v3 syntax OK]")


def test_companion_dockerfiles():
    print(f"\n{YELLOW}[2/6] Validating Companion Dockerfiles & Stage References...{RESET}")
    dockerfile_kits = [
        ("antigravity", "antigravity.dockerfile", "antigravity.yaml"),
        ("python-ml", "python-ml.dockerfile", "python-ml.yaml"),
        ("colab", "colab.dockerfile", "colab.yaml"),
        ("kaggle", "kaggle.dockerfile", "kaggle.yaml"),
        ("playwright-mcp", "playwright-mcp.dockerfile", "playwright-mcp.yaml"),
    ]

    for kit_dir_name, dockerfile_name, yaml_name in dockerfile_kits:
        kit_dir = KITS_DIR / kit_dir_name
        df_path = kit_dir / dockerfile_name
        assert df_path.is_file(), f"Missing companion Dockerfile: {df_path}"
        
        df_content = df_path.read_text(encoding="utf-8")
        # Check syntax header
        assert "# syntax=docker/dockerfile:1" in df_content or "FROM " in df_content, \
            f"{dockerfile_name} missing FROM directive"

        if kit_dir_name in {"python-ml", "colab", "kaggle"}:
            assert "FROM docker.io/sbx/shell-docker-image:latest" in df_content, \
                f"{dockerfile_name} must share the Docker-enabled sandbox base"

        # Check local COPY references exist
        for line in df_content.splitlines():
            line_str = line.strip()
            if line_str.startswith("COPY ") and not line_str.startswith("COPY --from="):
                parts = [p for p in line_str.split()[1:] if not p.startswith("--")]
                # e.g., COPY [--chmod=0644] skills/colab-operator/SKILL.md /path/to/dest
                src = parts[0]
                src_path = kit_dir / src
                assert src_path.exists(), f"COPY source '{src}' in {dockerfile_name} does not exist at {src_path}"

        print(f"  ✓ {kit_dir_name}/{dockerfile_name} [Companion pair matched, staged sources OK]")


def test_skills_frontmatter():
    print(f"\n{YELLOW}[3/6] Validating Agent Skills Specification & Frontmatter...{RESET}")
    skills = [
        ("python-ml", "skills/notebook-uv-workflow/SKILL.md", "notebook-uv-workflow"),
        ("colab", "skills/colab-operator/SKILL.md", "colab-operator"),
        ("kaggle", "skills/kaggle-cli/SKILL.md", "kaggle-cli"),
        ("playwright-mcp", "skills/browser-automation/SKILL.md", "browser-automation"),
    ]

    for kit_dir_name, rel_path, expected_skill_name in skills:
        skill_file = KITS_DIR / kit_dir_name / rel_path
        assert skill_file.is_file(), f"Missing skill file: {skill_file}"
        
        text = skill_file.read_text(encoding="utf-8")
        assert text.startswith("---"), f"{rel_path} must begin with YAML frontmatter delimiter '---'"
        
        # Extract frontmatter
        parts = text.split("---", 2)
        assert len(parts) >= 3, f"{rel_path} invalid frontmatter structure"
        frontmatter = parts[1]
        
        assert f"name: {expected_skill_name}" in frontmatter, \
            f"Frontmatter name mismatch: expected '{expected_skill_name}'"
        assert "description:" in frontmatter, f"{rel_path} missing description in frontmatter"

        print(f"  ✓ {kit_dir_name} -> {expected_skill_name} [Frontmatter & instructions valid]")

    # Check references for kaggle
    kaggle_refs = KITS_DIR / "kaggle" / "skills" / "kaggle-cli" / "references"
    for ref_name in ["competitions.md", "datasets.md", "kernels.md"]:
        assert (kaggle_refs / ref_name).is_file(), f"Missing kaggle reference doc: {ref_name}"
    print(f"  ✓ kaggle-cli reference documents verified (competitions, datasets, kernels)")


def test_zero_trust_proxy_policies():
    print(f"\n{YELLOW}[4/6] Validating Zero-Trust Proxy & Credential Policies...{RESET}")
    # Inspect credentials and network allowlists
    policy_checks = [
        ("antigravity", "antigravity.yaml", "generativelanguage.googleapis.com"),
        ("colab", "colab.yaml", "colab.research.google.com"),
        ("kaggle", "kaggle.yaml", "api.kaggle.com"),
    ]

    for kit_dir_name, yaml_name, expected_injected_domain in policy_checks:
        yaml_path = KITS_DIR / kit_dir_name / yaml_name
        content = yaml_path.read_text(encoding="utf-8")

        assert "com.docker.sandbox/network-policy@1" in content, \
            f"{yaml_name} missing network-policy@1"
        assert "com.docker.sandbox/credential@1" in content, \
            f"{yaml_name} missing credential@1"

        # In Docker Sandbox v3, credential injection domains MUST be explicitly listed in allowlist
        assert expected_injected_domain in content, \
            f"Injected domain {expected_injected_domain} must be declared in network allowlist"

        print(f"  ✓ {kit_dir_name} zero-trust domain injection bound: {expected_injected_domain}")

    antigravity_content = (KITS_DIR / "antigravity" / "antigravity.yaml").read_text(encoding="utf-8")
    assert "com.docker.sandbox/dockerd@1" in antigravity_content, "Private Docker Engine capability is missing"
    assert "usermod -aG docker agent" in antigravity_content, "Docker group membership hook is missing"
    assert "service: antigravity" in antigravity_content, "Antigravity OAuth service binding is missing"
    assert "agy-oauth-access-proxy-managed" in antigravity_content, "Antigravity OAuth sentinels are missing"
    assert "credentialFile:" in antigravity_content, "Antigravity OAuth credential file is missing"
    print("  ✓ antigravity proxy-managed OAuth binding configured")


def test_e2e_composition():
    print(f"\n{YELLOW}[5/6] Testing E2E Master Kit Set Composition...{RESET}")
    set_yaml_path = KITS_DIR / "agy-colab-kaggle" / "agy-colab-kaggle.yaml"
    set_content = set_yaml_path.read_text(encoding="utf-8")
    
    assert "kind: set" in set_content
    
    # Parse refs
    refs = re.findall(r"-\s+ref:\s+([^\s]+)", set_content)
    assert len(refs) == 4, f"Expected 4 kit refs in master set, found {len(refs)}"
    assert not any("playwright" in ref for ref in refs), "Playwright MCP mixin must stay ad hoc, not in the master set"

    # Map published kit references to local workspace directories
    ref_map = {
        "ghcr.io/danielmcstr/sbx-kits/antigravity:latest": KITS_DIR / "antigravity",
        "ghcr.io/danielmcstr/sbx-kits/python-ml:latest": KITS_DIR / "python-ml",
        "ghcr.io/danielmcstr/sbx-kits/colab:latest": KITS_DIR / "colab",
        "ghcr.io/danielmcstr/sbx-kits/kaggle:latest": KITS_DIR / "kaggle",
    }

    resolved_kinds = {"workload": [], "mixin": []}
    all_provides = set()
    all_skills = []

    for ref in refs:
        # Validate that set kit references do not use relative paths (SPEC-v3 requirement)
        assert not ref.startswith(".") and not ref.startswith("/"), \
            f"Set ref '{ref}' cannot be a relative or absolute path in v3 spec"
        assert ref in ref_map, f"Unknown kit reference in set: {ref}"
        target_path = ref_map[ref]
        assert target_path.is_dir(), f"Referenced kit does not exist: {target_path}"
        
        # Find yaml in target kit
        yamls = list(target_path.glob("*.yaml"))
        assert len(yamls) == 1, f"Expected exactly 1 yaml in {target_path}, found {len(yamls)}"
        
        yaml_content = yamls[0].read_text(encoding="utf-8")
        if "kind: workload" in yaml_content:
            resolved_kinds["workload"].append(target_path.name)
        elif "kind: mixin" in yaml_content:
            resolved_kinds["mixin"].append(target_path.name)

        # Extract provides
        provides_matches = re.findall(r"provides:\s*\n((?:\s+-\s+[^\n]+\n)+)", yaml_content)
        if provides_matches:
            for item in re.findall(r"-\s+([^\n]+)", provides_matches[0]):
                all_provides.add(item.strip())

        # Extract skills
        skill_matches = re.findall(r"name:\s+([a-zA-Z0-9_-]+)", yaml_content)
        for s in skill_matches:
            if s in ["notebook-uv-workflow", "colab-operator", "kaggle-cli"]:
                all_skills.append(s)

    # Conformance rules for kit set:
    # 1. Exactly 1 workload allowed
    assert len(resolved_kinds["workload"]) == 1, \
        f"Set must resolve exactly 1 workload, resolved: {resolved_kinds['workload']}"
    assert resolved_kinds["workload"][0] == "antigravity"

    # 2. 3 mixins
    assert len(resolved_kinds["mixin"]) == 3, \
        f"Set must resolve 3 mixins, resolved: {resolved_kinds['mixin']}"

    # 3. All expected tool tokens provided
    expected_provides = {"antigravity", "agy", "uv", "ruff", "jupytext", "nbstripout", "colab", "kaggle"}
    missing_provides = expected_provides - all_provides
    assert not missing_provides, f"Missing provides tokens: {missing_provides}"

    # 4. All 3 skills collected
    assert set(all_skills) == {"notebook-uv-workflow", "colab-operator", "kaggle-cli"}, \
        f"Missing skills in composition: {set(all_skills)}"

    print(f"  ✓ Workload resolved: {resolved_kinds['workload'][0]}")
    print(f"  ✓ Mixins resolved: {', '.join(resolved_kinds['mixin'])}")
    print(f"  ✓ Total provided tools: {len(all_provides)} {sorted(list(all_provides))}")
    print(f"  ✓ Dynamic skills assembled into Antigravity workload: {sorted(all_skills)}")


def _create_summaries_db(db_path: Path, rows: list[tuple[str, str, int, str, str]]) -> sqlite3.Connection:
    """Create a WAL-mode conversation_summaries.db matching Antigravity CLI schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            conversation_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT "",
            preview TEXT NOT NULL DEFAULT "",
            step_count INTEGER NOT NULL DEFAULT 0,
            last_modified_time DATETIME NOT NULL,
            workspace_uris TEXT NOT NULL DEFAULT ""
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_parents (
            conversation_id TEXT PRIMARY KEY,
            parent_id TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
            conversation_id UNINDEXED,
            title,
            user_body
        )
        """
    )
    for cid, title, steps, mtime, body in rows:
        conn.execute(
            "INSERT OR REPLACE INTO conversation_summaries "
            "(conversation_id, title, preview, step_count, last_modified_time, workspace_uris) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cid, title, body, steps, mtime, "/workspace"),
        )
        conn.execute("DELETE FROM conversations_fts WHERE conversation_id = ?", (cid,))
        conn.execute(
            "INSERT INTO conversations_fts (conversation_id, title, user_body) VALUES (?, ?, ?)",
            (cid, title, body),
        )
    conn.commit()
    return conn


def _create_conv_db(db_path: Path, cid: str, message: str) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS steps (id INTEGER PRIMARY KEY, cid TEXT, msg TEXT)")
    conn.execute("INSERT INTO steps (cid, msg) VALUES (?, ?)", (cid, message))
    conn.commit()
    return conn


def _run_sync(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    script = KITS_DIR / "antigravity" / "agy_session_sync.py"
    return subprocess.run(
        [sys.executable, str(script), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_session_persistence():
    print(f"\n{YELLOW}[6/6] Testing Workspace Session Persistence & Multi-Sandbox Merge...{RESET}")
    agy_yaml = (KITS_DIR / "antigravity" / "antigravity.yaml").read_text(encoding="utf-8")
    for required in ("persist_sessions:", "session_dir:", "auto_resume:", "persistence.json"):
        assert required in agy_yaml, f"antigravity.yaml missing session persistence setting: {required}"

    entrypoint = KITS_DIR / "antigravity" / "agy-entrypoint.sh"
    bash_check = subprocess.run(["bash", "-n", str(entrypoint)], capture_output=True, text=True)
    assert bash_check.returncode == 0, f"agy-entrypoint.sh syntax error: {bash_check.stderr}"

    with tempfile.TemporaryDirectory(prefix="sbx-kits-persist-test-") as tmp_root:
        root = Path(tmp_root)
        ws = root / "repo"
        ws.mkdir()
        subprocess.run(["git", "-C", str(ws), "init", "-q"], check=True)
        (ws / ".gitignore").write_text("*.log\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(ws), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(ws), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "init"],
            check=True,
        )

        # --- Sandbox A ---
        app_a = root / "sbx-a-app"
        env_a = {
            **os.environ,
            "WORKSPACE_DIR": str(ws),
            "SANDBOX_ID": "sandbox-a",
            "SBX_AGY_APP_DATA_DIR": str(app_a),
            "SBX_AGY_CONFIG_PATH": str(root / "cfg-a.json"),
            "SBX_AGY_STATE_PATH": str(root / "state-a.json"),
            "SBX_AGY_PERSIST": "true",
            "SBX_AGY_AUTO_RESUME": "true",
        }
        assert _run_sync(["hydrate"], env_a).returncode == 0

        # Create live WAL DBs + brain + metadata + decoy secrets/logs
        conv_a_conn = _create_conv_db(app_a / "conversations" / "uuid-a.db", "uuid-a", "hello from sandbox A")
        sum_a_conn = _create_summaries_db(
            app_a / "conversation_summaries.db",
            [("uuid-a", "Session A", 3, "2026-11-22T00:01:00Z", "alpha keyword")],
        )
        (app_a / "brain" / "uuid-a").mkdir(parents=True, exist_ok=True)
        (app_a / "brain" / "uuid-a" / "plan.md").write_text("# Plan A\n", encoding="utf-8")
        (app_a / "cache").mkdir(parents=True, exist_ok=True)
        (app_a / "cache" / "last_conversations.json").write_text(
            json.dumps({str(ws): "uuid-a"}), encoding="utf-8"
        )
        (app_a / "history.jsonl").write_text('{"prompt":"prompt A"}\n', encoding="utf-8")
        # Decoy secrets/logs that MUST NEVER be persisted
        (app_a / "antigravity-oauth-token").write_text("sentinel-secret", encoding="utf-8")
        (app_a / "settings.json").write_text('{"agentMode":"accept-edits"}', encoding="utf-8")
        (app_a / "log").mkdir(parents=True, exist_ok=True)
        (app_a / "log" / "cli.log").write_text("debug log", encoding="utf-8")

        # Push while WAL connections are still OPEN (live checkpoint test)
        res_a = _run_sync(["push"], env_a)
        assert res_a.returncode == 0, f"Sandbox A push failed: {res_a.stderr}"

        store = ws / ".sbx-agy"
        assert (store / "conversations" / "uuid-a.db").is_file()
        assert not (store / "conversations" / "uuid-a.db-wal").exists()
        assert not (store / "conversations" / "uuid-a.db-shm").exists()
        assert not (store / "antigravity-oauth-token").exists(), "OAuth token must never be persisted!"
        assert not (store / "settings.json").exists(), "settings.json must not be persisted!"
        assert not (store / "log").exists(), "logs must not be persisted!"

        # Verify git cleanliness (tracked .gitignore untouched, .sbx-agy ignored via info/exclude)
        git_st = subprocess.run(["git", "-C", str(ws), "status", "--porcelain"], capture_output=True, text=True, check=True)
        assert git_st.stdout.strip() == "", f"Workspace git status dirtied: {git_st.stdout!r}"
        assert (ws / ".gitignore").read_text(encoding="utf-8") == "*.log\n"
        assert ".sbx-agy/" in (ws / ".git" / "info" / "exclude").read_text(encoding="utf-8")

        # --- Sandbox B running SIMULTANEOUSLY on the same workspace ---
        app_b = root / "sbx-b-app"
        env_b = {
            **os.environ,
            "WORKSPACE_DIR": str(ws),
            "SANDBOX_ID": "sandbox-b",
            "SBX_AGY_APP_DATA_DIR": str(app_b),
            "SBX_AGY_CONFIG_PATH": str(root / "cfg-b.json"),
            "SBX_AGY_STATE_PATH": str(root / "state-b.json"),
            "SBX_AGY_PERSIST": "true",
            "SBX_AGY_AUTO_RESUME": "true",
        }
        assert _run_sync(["hydrate"], env_b).returncode == 0
        assert (app_b / "conversations" / "uuid-a.db").is_file()
        assert _run_sync(["should-auto-resume"], env_b).returncode == 0

        # Sandbox B creates its OWN conversation uuid-b AND also simulates a conflict attempt on uuid-a
        conv_b_conn = _create_conv_db(app_b / "conversations" / "uuid-b.db", "uuid-b", "hello from sandbox B")
        sum_b_conn = _create_summaries_db(
            app_b / "conversation_summaries.db",
            [("uuid-b", "Session B", 5, "2026-11-22T00:02:00Z", "beta keyword")],
        )
        # Attempt to tamper with uuid-a from Sandbox B while Sandbox A holds an active claim on uuid-a
        tamper_conn = _create_conv_db(app_b / "conversations" / "uuid-a.db", "uuid-a", "conflicting write from B")
        (app_b / "brain" / "uuid-b").mkdir(parents=True, exist_ok=True)
        (app_b / "brain" / "uuid-b" / "notes.md").write_text("# Notes B\n", encoding="utf-8")
        (app_b / "history.jsonl").write_text('{"prompt":"prompt A"}\n{"prompt":"prompt B"}\n', encoding="utf-8")

        res_b = _run_sync(["push"], env_b)
        assert res_b.returncode == 0, f"Sandbox B push failed: {res_b.stderr}"
        assert "skipping to avoid conflict" in res_b.stderr, "Active-UUID conflict guard did not trigger!"

        conv_a_conn.close()
        sum_a_conn.close()
        conv_b_conn.close()
        sum_b_conn.close()
        tamper_conn.close()

        # Release claims on exit
        assert _run_sync(["push", "--release-lock"], env_a).returncode == 0
        assert _run_sync(["push", "--release-lock"], env_b).returncode == 0

        # --- Sandbox C (fresh sandbox after A & B are deleted) ---
        app_c = root / "sbx-c-app"
        env_c = {
            **os.environ,
            "WORKSPACE_DIR": str(ws),
            "SANDBOX_ID": "sandbox-c",
            "SBX_AGY_APP_DATA_DIR": str(app_c),
            "SBX_AGY_CONFIG_PATH": str(root / "cfg-c.json"),
            "SBX_AGY_STATE_PATH": str(root / "state-c.json"),
            "SBX_AGY_PERSIST": "true",
        }
        assert _run_sync(["hydrate"], env_c).returncode == 0

        # Verify BOTH uuid-a and uuid-b survived and uuid-a was NOT clobbered by B
        for cid, expected_msg in (("uuid-a", "hello from sandbox A"), ("uuid-b", "hello from sandbox B")):
            db_c = app_c / "conversations" / f"{cid}.db"
            assert db_c.is_file(), f"Missing restored conversation {cid}"
            conn = sqlite3.connect(str(db_c))
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            msgs = [r[0] for r in conn.execute("SELECT msg FROM steps")]
            conn.close()
            assert expected_msg in msgs, f"Expected {expected_msg!r} in {cid}, got {msgs}"
            assert "conflicting write from B" not in msgs, f"Conflict guard failed for {cid}!"

        # Verify merged conversation_summaries.db + FTS5 has BOTH sessions
        sconn = sqlite3.connect(str(app_c / "conversation_summaries.db"))
        assert sconn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        ids = {r[0] for r in sconn.execute("SELECT conversation_id FROM conversation_summaries")}
        assert ids == {"uuid-a", "uuid-b"}, f"Expected both summaries merged, got {ids}"
        fts_a = [r[0] for r in sconn.execute("SELECT conversation_id FROM conversations_fts WHERE conversations_fts MATCH 'alpha'")]
        fts_b = [r[0] for r in sconn.execute("SELECT conversation_id FROM conversations_fts WHERE conversations_fts MATCH 'beta'")]
        sconn.close()
        assert fts_a == ["uuid-a"] and fts_b == ["uuid-b"], f"FTS5 merge failed: {fts_a}, {fts_b}"

        # Verify artifacts & merged history
        assert (app_c / "brain" / "uuid-a" / "plan.md").is_file()
        assert (app_c / "brain" / "uuid-b" / "notes.md").is_file()
        hist_lines = (app_c / "history.jsonl").read_text(encoding="utf-8").splitlines()
        assert '{"prompt":"prompt A"}' in hist_lines and '{"prompt":"prompt B"}' in hist_lines

        # Verify CLI status & list helpers
        assert _run_sync(["status"], env_c).returncode == 0
        list_res = _run_sync(["list"], env_c)
        assert list_res.returncode == 0 and "uuid-a" in list_res.stdout and "uuid-b" in list_res.stdout

    print("  ✓ SQLite WAL online backup, git exclusion, and credential filtering verified")
    print("  ✓ Multi-sandbox cooperative merge (summaries + FTS5 + active-UUID guard) verified")
    print(f"\n{GREEN}All E2E validation and conformance tests PASSED successfully!{RESET}\n")


def main():
    try:
        test_kit_descriptors()
        test_companion_dockerfiles()
        test_skills_frontmatter()
        test_zero_trust_proxy_policies()
        test_e2e_composition()
        test_session_persistence()
    except AssertionError as e:
        print(f"\n{RED}TEST FAILED: {e}{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
