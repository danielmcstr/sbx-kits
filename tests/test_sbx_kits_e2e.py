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
    print(f"\n{YELLOW}[1/5] Validating Kit Descriptors & Schemas...{RESET}")
    expected_kits = [
        ("antigravity-kit-v3", "antigravity.yaml", "workload"),
        ("python-ml-mixin", "python-ml.yaml", "mixin"),
        ("colab-mixin", "colab.yaml", "mixin"),
        ("kaggle-mixin", "kaggle.yaml", "mixin"),
        ("playwright-mcp-mixin", "playwright-mcp.yaml", "mixin"),
        ("agy-colab-kaggle-kit", "agy-colab-kaggle.yaml", "set"),
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
    print(f"\n{YELLOW}[2/5] Validating Companion Dockerfiles & Stage References...{RESET}")
    dockerfile_kits = [
        ("antigravity-kit-v3", "antigravity.dockerfile", "antigravity.yaml"),
        ("python-ml-mixin", "python-ml.dockerfile", "python-ml.yaml"),
        ("colab-mixin", "colab.dockerfile", "colab.yaml"),
        ("kaggle-mixin", "kaggle.dockerfile", "kaggle.yaml"),
        ("playwright-mcp-mixin", "playwright-mcp.dockerfile", "playwright-mcp.yaml"),
    ]

    for kit_dir_name, dockerfile_name, yaml_name in dockerfile_kits:
        kit_dir = KITS_DIR / kit_dir_name
        df_path = kit_dir / dockerfile_name
        assert df_path.is_file(), f"Missing companion Dockerfile: {df_path}"
        
        df_content = df_path.read_text(encoding="utf-8")
        # Check syntax header
        assert "# syntax=docker/dockerfile:1" in df_content or "FROM " in df_content, \
            f"{dockerfile_name} missing FROM directive"

        if kit_dir_name in {"python-ml-mixin", "colab-mixin", "kaggle-mixin"}:
            assert "FROM docker.io/sbx/shell-docker-image:latest" in df_content, \
                f"{dockerfile_name} must share the Docker-enabled sandbox base"

        # Check local COPY references exist
        for line in df_content.splitlines():
            line_str = line.strip()
            if line_str.startswith("COPY ") and not line_str.startswith("COPY --from="):
                parts = line_str.split()
                # e.g., COPY skills/colab-operator/SKILL.md /path/to/dest
                src = parts[1]
                src_path = kit_dir / src
                assert src_path.exists(), f"COPY source '{src}' in {dockerfile_name} does not exist at {src_path}"

        print(f"  ✓ {kit_dir_name}/{dockerfile_name} [Companion pair matched, staged sources OK]")


def test_skills_frontmatter():
    print(f"\n{YELLOW}[3/5] Validating Agent Skills Specification & Frontmatter...{RESET}")
    skills = [
        ("python-ml-mixin", "skills/notebook-uv-workflow/SKILL.md", "notebook-uv-workflow"),
        ("colab-mixin", "skills/colab-operator/SKILL.md", "colab-operator"),
        ("kaggle-mixin", "skills/kaggle-cli/SKILL.md", "kaggle-cli"),
        ("playwright-mcp-mixin", "skills/browser-automation/SKILL.md", "browser-automation"),
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
    kaggle_refs = KITS_DIR / "kaggle-mixin" / "skills" / "kaggle-cli" / "references"
    for ref_name in ["competitions.md", "datasets.md", "kernels.md"]:
        assert (kaggle_refs / ref_name).is_file(), f"Missing kaggle reference doc: {ref_name}"
    print(f"  ✓ kaggle-cli reference documents verified (competitions, datasets, kernels)")


def test_zero_trust_proxy_policies():
    print(f"\n{YELLOW}[4/5] Validating Zero-Trust Proxy & Credential Policies...{RESET}")
    # Inspect credentials and network allowlists
    policy_checks = [
        ("antigravity-kit-v3", "antigravity.yaml", "generativelanguage.googleapis.com"),
        ("colab-mixin", "colab.yaml", "colab.research.google.com"),
        ("kaggle-mixin", "kaggle.yaml", "api.kaggle.com"),
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

    antigravity_content = (KITS_DIR / "antigravity-kit-v3" / "antigravity.yaml").read_text(encoding="utf-8")
    assert "com.docker.sandbox/dockerd@1" in antigravity_content, "Private Docker Engine capability is missing"
    assert "usermod -aG docker agent" in antigravity_content, "Docker group membership hook is missing"
    assert "service: antigravity" in antigravity_content, "Antigravity OAuth service binding is missing"
    assert "agy-oauth-access-proxy-managed" in antigravity_content, "Antigravity OAuth sentinels are missing"
    assert "credentialFile:" in antigravity_content, "Antigravity OAuth credential file is missing"
    print("  ✓ antigravity-kit-v3 proxy-managed OAuth binding configured")


def test_e2e_composition():
    print(f"\n{YELLOW}[5/5] Testing E2E Master Kit Set Composition...{RESET}")
    set_yaml_path = KITS_DIR / "agy-colab-kaggle-kit" / "agy-colab-kaggle.yaml"
    set_content = set_yaml_path.read_text(encoding="utf-8")
    
    assert "kind: set" in set_content
    
    # Parse refs
    refs = re.findall(r"-\s+ref:\s+([^\s]+)", set_content)
    assert len(refs) == 4, f"Expected 4 kit refs in master set, found {len(refs)}"
    assert not any("playwright" in ref for ref in refs), "Playwright MCP mixin must stay ad hoc, not in the master set"

    # Map published kit references to local workspace directories
    ref_map = {
        "ghcr.io/danielmcstr/sbx-kits/antigravity:latest": KITS_DIR / "antigravity-kit-v3",
        "ghcr.io/danielmcstr/sbx-kits/python-ml:latest": KITS_DIR / "python-ml-mixin",
        "ghcr.io/danielmcstr/sbx-kits/colab:latest": KITS_DIR / "colab-mixin",
        "ghcr.io/danielmcstr/sbx-kits/kaggle:latest": KITS_DIR / "kaggle-mixin",
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
    assert resolved_kinds["workload"][0] == "antigravity-kit-v3"

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
    print(f"\n{GREEN}All E2E validation and conformance tests PASSED successfully!{RESET}\n")


def main():
    try:
        test_kit_descriptors()
        test_companion_dockerfiles()
        test_skills_frontmatter()
        test_zero_trust_proxy_policies()
        test_e2e_composition()
    except AssertionError as e:
        print(f"\n{RED}TEST FAILED: {e}{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
