#!/usr/bin/env python3
"""Workspace-backed session persistence manager for Antigravity (agy).

Keeps live Antigravity SQLite WAL databases on the container's fast local disk
and cooperatively merges allowlisted, SQLite-checkpointed snapshots into a
git-excluded directory inside the mounted workspace (default: $WORKSPACE_DIR/.sbx-agy).

Multi-sandbox safe:
- Uses an atomic mkdir critical section (.sync.lockdir) during brief syncs.
- Syncs conversations/<uuid>.db and brain/<uuid>/ additively (only locally
  created or modified UUIDs are pushed; other sandboxes' UUIDs are preserved).
- Cooperatively merges conversation_summaries.db (including FTS5 search index
  and conversation_parents) on a local container temp copy before atomic rename
  onto the virtiofs mount.
- Tracks active per-sandbox UUID claims (.active/<sandbox_id>.json) to prevent
  silently clobbering a conversation currently active in another sandbox.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator

CONFIG_PATH = Path(
    os.environ.get(
        "SBX_AGY_CONFIG_PATH",
        str(Path.home() / ".config" / "sbx-agy" / "persistence.json"),
    )
)
STATE_PATH = Path(
    os.environ.get(
        "SBX_AGY_STATE_PATH",
        "/tmp/sbx-agy-hydrated-state.json",
    )
)
SYNC_LOCK_STALE_SECONDS = 30
SYNC_LOCK_TIMEOUT_SECONDS = 15
ACTIVE_CLAIM_STALE_SECONDS = 60

SYNC_MISC_DIRS = ("annotations", "implicit")
SYNC_RAW_FILES = ("jetbox_summaries_proto.pb",)
EXCLUDED_FILE_SUFFIXES = (".tmp", ".db-wal", ".db-shm")


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "persist_sessions": True,
        "session_dir": ".sbx-agy",
        "auto_resume": False,
    }
    if CONFIG_PATH.is_file():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
        except (OSError, json.JSONDecodeError):
            pass

    if "SBX_AGY_PERSIST" in os.environ:
        cfg["persist_sessions"] = os.environ["SBX_AGY_PERSIST"]
    if "SBX_AGY_SESSION_DIR" in os.environ:
        cfg["session_dir"] = os.environ["SBX_AGY_SESSION_DIR"]
    if "SBX_AGY_AUTO_RESUME" in os.environ:
        cfg["auto_resume"] = os.environ["SBX_AGY_AUTO_RESUME"]

    cfg["persist_sessions"] = parse_bool(cfg.get("persist_sessions"), True)
    cfg["auto_resume"] = parse_bool(cfg.get("auto_resume"), False)
    cfg["session_dir"] = str(cfg.get("session_dir") or ".sbx-agy").strip()
    return cfg


def get_app_data_dir() -> Path:
    return Path(
        os.environ.get(
            "SBX_AGY_APP_DATA_DIR",
            os.environ.get(
                "ANTIGRAVITY_APP_DATA_DIR",
                str(Path.home() / ".gemini" / "antigravity-cli"),
            ),
        )
    )


def get_workspace_dir() -> Path | None:
    ws = os.environ.get("WORKSPACE_DIR") or os.getcwd()
    path = Path(ws)
    if not path.is_dir():
        return None
    return path


def resolve_store_dir(workspace_dir: Path, session_dir: str) -> Path:
    if not session_dir or session_dir in {".", ".."}:
        raise ValueError(f"Invalid session_dir: {session_dir!r}")
    rel = Path(session_dir)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"session_dir must be a safe workspace-relative path: {session_dir!r}")
    return workspace_dir / rel


def get_sandbox_id() -> str:
    raw = (
        os.environ.get("SANDBOX_ID")
        or os.environ.get("SANDBOX_VM_ID")
        or os.environ.get("HOSTNAME")
        or f"pid-{os.getpid()}"
    )
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in raw)


def load_local_state() -> dict[str, Any]:
    if STATE_PATH.is_file():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"hydrated_conv_sigs": {}, "owned_uuids": [], "blocked_uuids": []}


def save_local_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(f"{STATE_PATH}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def ensure_git_ignored(workspace_dir: Path, store_dir: Path) -> None:
    """Protect against accidental git commits without mutating tracked .gitignore."""
    store_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(store_dir, 0o700)
    except OSError:
        pass

    # Barrier 1: self-ignoring .gitignore inside the session directory
    inner_ignore = store_dir / ".gitignore"
    if not inner_ignore.exists():
        inner_ignore.write_text(
            "# Managed by antigravity session persistence.\n"
            "# Never commit Antigravity session databases or transcripts.\n"
            "*\n",
            encoding="utf-8",
        )

    # Barrier 2: repo-local .git/info/exclude (works for standard repos & worktrees)
    try:
        top_proc = subprocess.run(
            ["git", "-C", str(workspace_dir), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if top_proc.returncode != 0:
            return
        git_top = Path(top_proc.stdout.strip()).resolve()
        exclude_proc = subprocess.run(
            ["git", "-C", str(workspace_dir), "rev-parse", "--git-path", "info/exclude"],
            capture_output=True,
            text=True,
            check=False,
        )
        if exclude_proc.returncode != 0:
            return
        exclude_raw = exclude_proc.stdout.strip()
        exclude_path = Path(exclude_raw)
        if not exclude_path.is_absolute():
            exclude_path = (workspace_dir / exclude_path).resolve()

        rel_store = store_dir.resolve().relative_to(git_top).as_posix().rstrip("/") + "/"
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
        lines = [line.strip() for line in existing.splitlines()]
        if rel_store not in lines and rel_store.rstrip("/") not in lines:
            prefix = "" if (not existing or existing.endswith("\n")) else "\n"
            with exclude_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{prefix}{rel_store}\n")
    except (OSError, ValueError):
        pass


@contextlib.contextmanager
def store_sync_lock(store_dir: Path, my_id: str) -> Iterator[bool]:
    """Acquire a short-lived atomic mkdir lock for cooperative store updates."""
    lock_dir = store_dir / ".sync.lockdir"
    owner_file = lock_dir / "owner.json"
    deadline = time.time() + SYNC_LOCK_TIMEOUT_SECONDS
    acquired = False

    while time.time() < deadline:
        try:
            lock_dir.mkdir(parents=False, exist_ok=False)
            acquired = True
            break
        except FileExistsError:
            try:
                stale = False
                if owner_file.is_file():
                    data = json.loads(owner_file.read_text(encoding="utf-8"))
                    ts = float(data.get("epoch") or 0.0)
                    stale = (time.time() - ts) > SYNC_LOCK_STALE_SECONDS
                else:
                    st = lock_dir.stat()
                    stale = (time.time() - st.st_mtime) > SYNC_LOCK_STALE_SECONDS
                if stale:
                    shutil.rmtree(lock_dir, ignore_errors=True)
                    continue
            except (OSError, json.JSONDecodeError):
                pass
            time.sleep(0.1)
        except OSError:
            break

    if acquired:
        try:
            owner_file.write_text(
                json.dumps({"sandbox_id": my_id, "pid": os.getpid(), "epoch": time.time()}) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    try:
        yield acquired
    finally:
        if acquired:
            shutil.rmtree(lock_dir, ignore_errors=True)


def write_active_claim(store_dir: Path, my_id: str, active_uuids: list[str]) -> None:
    active_dir = store_dir / ".active"
    active_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = store_dir / ".tmp"
    payload = {
        "sandbox_id": my_id,
        "pid": os.getpid(),
        "heartbeat_utc": utc_now_iso(),
        "heartbeat_epoch": time.time(),
        "active_uuids": sorted(set(active_uuids)),
    }
    atomic_write_bytes(
        active_dir / f"{my_id}.json",
        (json.dumps(payload, indent=2) + "\n").encode("utf-8"),
        tmp_dir,
    )


def release_active_claim(store_dir: Path, my_id: str) -> None:
    claim = store_dir / ".active" / f"{my_id}.json"
    try:
        claim.unlink(missing_ok=True)
    except OSError:
        pass


def get_other_active_claims(store_dir: Path, my_id: str) -> dict[str, str]:
    """Return {uuid: owning_sandbox_id} for UUIDs claimed by other live sandboxes."""
    claimed: dict[str, str] = {}
    active_dir = store_dir / ".active"
    if not active_dir.is_dir():
        return claimed
    now = time.time()
    for path in active_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        owner = str(data.get("sandbox_id") or "")
        if not owner or owner == my_id:
            continue
        hb = float(data.get("heartbeat_epoch") or 0.0)
        if (now - hb) > ACTIVE_CLAIM_STALE_SECONDS:
            continue
        for cid in data.get("active_uuids") or []:
            claimed[str(cid)] = owner
    return claimed


def list_live_sandboxes(store_dir: Path) -> list[dict[str, Any]]:
    active_dir = store_dir / ".active"
    if not active_dir.is_dir():
        return []
    now = time.time()
    live: list[dict[str, Any]] = []
    for path in sorted(active_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        hb = float(data.get("heartbeat_epoch") or 0.0)
        if (now - hb) <= ACTIVE_CLAIM_STALE_SECONDS:
            live.append(data)
    return live


def sqlite_signature(db_path: Path) -> list[int]:
    st = db_path.stat()
    wal = Path(f"{db_path}-wal")
    if wal.exists():
        wst = wal.stat()
        return [st.st_mtime_ns, st.st_size, wst.st_mtime_ns, wst.st_size]
    return [st.st_mtime_ns, st.st_size, 0, 0]


def sqlite_backup_to_file(src_db: Path, dst_file: Path) -> bool:
    """Create a clean, checkpointed SQLite backup (WAL-safe, standalone DB)."""
    if not src_db.is_file():
        return False
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    if dst_file.exists():
        dst_file.unlink()

    src_conn: sqlite3.Connection | None = None
    dst_conn: sqlite3.Connection | None = None
    try:
        src_conn = sqlite3.connect(str(src_db), timeout=5.0)
        dst_conn = sqlite3.connect(str(dst_file), timeout=5.0)
        src_conn.backup(dst_conn, pages=256, sleep=0.02)
        dst_conn.commit()
    finally:
        if dst_conn is not None:
            dst_conn.close()
        if src_conn is not None:
            src_conn.close()

    for suffix in ("-wal", "-shm", "-journal"):
        Path(f"{dst_file}{suffix}").unlink(missing_ok=True)
    return True


def sqlite_backup_atomic(src_db: Path, dst_db: Path, tmp_dir: Path) -> bool:
    """Backup src_db to local container temp, then atomically replace dst_db."""
    if not src_db.is_file():
        return False
    dst_db.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sbx-agy-bak-") as local_tmp:
        local_bak = Path(local_tmp) / dst_db.name
        if not sqlite_backup_to_file(src_db, local_bak):
            return False
        stage_file = tmp_dir / f"{dst_db.name}.{os.getpid()}.tmp"
        shutil.copyfile(local_bak, stage_file)
        try:
            os.chmod(stage_file, 0o600)
        except OSError:
            pass
        os.replace(stage_file, dst_db)
    return True


def merge_conversation_summaries_db(
    local_summaries: Path,
    store_summaries: Path,
    tmp_dir: Path,
    skip_uuids: set[str],
) -> bool:
    """Cooperatively merge conversation_summaries.db on local disk, then atomic-replace."""
    if not local_summaries.is_file():
        return False

    with tempfile.TemporaryDirectory(prefix="sbx-agy-merge-") as work_str:
        work = Path(work_str)
        src_snap = work / "src.db"
        if not sqlite_backup_to_file(local_summaries, src_snap):
            return False

        if not store_summaries.is_file():
            stage = tmp_dir / f"conversation_summaries.db.{os.getpid()}.tmp"
            store_summaries.parent.mkdir(parents=True, exist_ok=True)
            tmp_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_snap, stage)
            try:
                os.chmod(stage, 0o600)
            except OSError:
                pass
            os.replace(stage, store_summaries)
            return True

        merged_db = work / "merged.db"
        shutil.copyfile(store_summaries, merged_db)

        conn = sqlite3.connect(str(merged_db), timeout=5.0)
        try:
            conn.execute("ATTACH DATABASE ? AS src", (str(src_snap),))

            main_tables = {
                row[0]
                for row in conn.execute("SELECT name FROM main.sqlite_master WHERE type='table'")
            }
            src_tables = {
                row[0]
                for row in conn.execute("SELECT name FROM src.sqlite_master WHERE type='table'")
            }

            winners: list[str] = []
            if "conversation_summaries" in main_tables and "conversation_summaries" in src_tables:
                main_cols = [
                    row[1] for row in conn.execute("PRAGMA main.table_info(conversation_summaries)")
                ]
                src_cols = [
                    row[1] for row in conn.execute("PRAGMA src.table_info(conversation_summaries)")
                ]
                common_cols = [c for c in main_cols if c in src_cols]

                existing_meta: dict[str, tuple[int, str]] = {}
                for cid, sc, lm in conn.execute(
                    "SELECT conversation_id, step_count, CAST(last_modified_time AS TEXT) "
                    "FROM main.conversation_summaries"
                ):
                    existing_meta[cid] = (int(sc or 0), str(lm or ""))

                for cid, sc, lm in conn.execute(
                    "SELECT conversation_id, step_count, CAST(last_modified_time AS TEXT) "
                    "FROM src.conversation_summaries"
                ):
                    if cid in skip_uuids:
                        continue
                    src_key = (int(sc or 0), str(lm or ""))
                    cur_key = existing_meta.get(cid)
                    if cur_key is None or src_key > cur_key:
                        winners.append(cid)

                if winners and common_cols:
                    col_list = ", ".join(f'"{c}"' for c in common_cols)
                    placeholders = ", ".join("?" for _ in winners)
                    conn.execute(
                        f"INSERT OR REPLACE INTO main.conversation_summaries ({col_list}) "
                        f"SELECT {col_list} FROM src.conversation_summaries "
                        f"WHERE conversation_id IN ({placeholders})",
                        winners,
                    )

            if winners and "conversation_parents" in main_tables and "conversation_parents" in src_tables:
                placeholders = ", ".join("?" for _ in winners)
                conn.execute(
                    f"INSERT OR REPLACE INTO main.conversation_parents (conversation_id, parent_id) "
                    f"SELECT conversation_id, parent_id FROM src.conversation_parents "
                    f"WHERE conversation_id IN ({placeholders})",
                    winners,
                )

            if winners and "conversations_fts" in main_tables and "conversations_fts" in src_tables:
                fts_main_cols = [
                    row[1] for row in conn.execute("PRAGMA main.table_info(conversations_fts)")
                ]
                fts_src_cols = [
                    row[1] for row in conn.execute("PRAGMA src.table_info(conversations_fts)")
                ]
                fts_cols = [c for c in fts_main_cols if c in fts_src_cols]
                if fts_cols:
                    fts_col_list = ", ".join(f'"{c}"' for c in fts_cols)
                    for cid in winners:
                        conn.execute(
                            "DELETE FROM main.conversations_fts WHERE conversation_id = ?",
                            (cid,),
                        )
                        conn.execute(
                            f"INSERT INTO main.conversations_fts ({fts_col_list}) "
                            f"SELECT {fts_col_list} FROM src.conversations_fts "
                            f"WHERE conversation_id = ?",
                            (cid,),
                        )

            conn.commit()
            conn.execute("DETACH DATABASE src")
        finally:
            conn.close()

        if not winners:
            return False

        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{merged_db}{suffix}").unlink(missing_ok=True)

        tmp_dir.mkdir(parents=True, exist_ok=True)
        stage = tmp_dir / f"conversation_summaries.db.{os.getpid()}.tmp"
        shutil.copyfile(merged_db, stage)
        try:
            os.chmod(stage, 0o600)
        except OSError:
            pass
        os.replace(stage, store_summaries)
        return True


def atomic_write_bytes(dst: Path, data: bytes, tmp_dir: Path, mode: int = 0o600) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = tmp_dir / f"{dst.name}.{os.getpid()}.tmp"
    with tmp_file.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.chmod(tmp_file, mode)
    except OSError:
        pass
    os.replace(tmp_file, dst)


def copy_file_if_newer(src: Path, dst: Path, tmp_dir: Path | None = None) -> bool:
    if not src.is_file():
        return False
    src_st = src.stat()
    if dst.is_file():
        dst_st = dst.stat()
        if dst_st.st_size == src_st.st_size and int(dst_st.st_mtime) >= int(src_st.st_mtime):
            return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if tmp_dir is not None:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = tmp_dir / f"{dst.name}.{os.getpid()}.tmp"
        shutil.copy2(src, tmp_file)
        os.replace(tmp_file, dst)
    else:
        shutil.copy2(src, dst)
    return True


def sync_tree_additive(src_root: Path, dst_root: Path, tmp_dir: Path | None = None) -> int:
    """Copy new/updated files additively without deleting unrelated files in dst."""
    if not src_root.is_dir():
        return 0
    copied = 0
    for dirpath, _, filenames in os.walk(src_root):
        rel_dir = Path(dirpath).relative_to(src_root)
        target_dir = dst_root / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in filenames:
            if fname.endswith(EXCLUDED_FILE_SUFFIXES):
                continue
            src_file = Path(dirpath) / fname
            if not src_file.is_file() or src_file.is_symlink():
                continue
            dst_file = target_dir / fname
            if copy_file_if_newer(src_file, dst_file, tmp_dir=tmp_dir):
                copied += 1
    return copied


def merge_json_dict_file(src: Path, dst: Path, tmp_dir: Path) -> bool:
    if not src.is_file():
        return False
    try:
        src_data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(src_data, dict):
        return False

    merged: dict[str, Any] = {}
    if dst.is_file():
        try:
            dst_data = json.loads(dst.read_text(encoding="utf-8"))
            if isinstance(dst_data, dict):
                merged.update(dst_data)
        except (OSError, json.JSONDecodeError):
            pass

    before = dict(merged)
    merged.update(src_data)
    if merged == before and dst.is_file():
        return False
    atomic_write_bytes(dst, (json.dumps(merged, indent=2) + "\n").encode("utf-8"), tmp_dir)
    return True


def merge_jsonl_file(src: Path, dst: Path, tmp_dir: Path) -> bool:
    if not src.is_file():
        return False
    try:
        src_lines = src.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False

    existing_lines: list[str] = []
    if dst.is_file():
        try:
            existing_lines = dst.read_text(encoding="utf-8").splitlines()
        except OSError:
            existing_lines = []

    seen = set(existing_lines)
    merged = list(existing_lines)
    changed = False
    for line in src_lines:
        if line and line not in seen:
            seen.add(line)
            merged.append(line)
            changed = True

    if not changed and dst.is_file():
        return False
    content = ("\n".join(merged) + "\n") if merged else ""
    atomic_write_bytes(dst, content.encode("utf-8"), tmp_dir)
    return True


def cmd_hydrate(_args: argparse.Namespace) -> int:
    cfg = load_config()
    if not cfg["persist_sessions"]:
        return 0
    ws = get_workspace_dir()
    if ws is None:
        return 0

    store_dir = resolve_store_dir(ws, cfg["session_dir"])
    app_dir = get_app_data_dir()
    my_id = get_sandbox_id()

    ensure_git_ignored(ws, store_dir)
    app_dir.mkdir(parents=True, exist_ok=True)

    hydrated_sigs: dict[str, list[int]] = {}

    with store_sync_lock(store_dir, my_id):
        # Restore SQLite conversation_summaries.db
        store_summaries = store_dir / "conversation_summaries.db"
        local_summaries = app_dir / "conversation_summaries.db"
        if store_summaries.is_file():
            if copy_file_if_newer(store_summaries, local_summaries):
                for suffix in ("-wal", "-shm"):
                    Path(f"{local_summaries}{suffix}").unlink(missing_ok=True)

        # Restore all persisted conversations/<uuid>.db and record baseline signatures
        store_convs = store_dir / "conversations"
        local_convs = app_dir / "conversations"
        if store_convs.is_dir():
            local_convs.mkdir(parents=True, exist_ok=True)
            for db_file in sorted(store_convs.glob("*.db")):
                dst_db = local_convs / db_file.name
                if copy_file_if_newer(db_file, dst_db):
                    for suffix in ("-wal", "-shm"):
                        Path(f"{dst_db}{suffix}").unlink(missing_ok=True)
                if dst_db.is_file():
                    hydrated_sigs[db_file.stem] = sqlite_signature(dst_db)

        # Restore brain/<uuid>/ and supplementary directories
        sync_tree_additive(store_dir / "brain", app_dir / "brain")
        for rel_dir in SYNC_MISC_DIRS:
            sync_tree_additive(store_dir / rel_dir, app_dir / rel_dir)

        # Restore metadata files
        store_last = store_dir / "cache" / "last_conversations.json"
        if store_last.is_file():
            copy_file_if_newer(store_last, app_dir / "cache" / "last_conversations.json")

        store_history = store_dir / "history.jsonl"
        if store_history.is_file():
            copy_file_if_newer(store_history, app_dir / "history.jsonl")

        for raw_name in SYNC_RAW_FILES:
            src_raw = store_dir / raw_name
            if src_raw.is_file():
                copy_file_if_newer(src_raw, app_dir / raw_name)

        write_active_claim(store_dir, my_id, [])

    save_local_state({"hydrated_conv_sigs": hydrated_sigs, "owned_uuids": [], "blocked_uuids": []})
    return 0


def sync_once(
    ws: Path,
    store_dir: Path,
    app_dir: Path,
    my_id: str,
    force: bool = False,
    quiet: bool = False,
    sig_cache: dict[str, list[int]] | None = None,
) -> tuple[bool, int]:
    """Cooperatively push locally created/modified conversations and merge shared indexes."""
    ensure_git_ignored(ws, store_dir)
    state = load_local_state()
    hydrated_sigs: dict[str, list[int]] = state.get("hydrated_conv_sigs") or {}
    owned_uuids: set[str] = set(state.get("owned_uuids") or [])
    blocked_uuids: set[str] = set(state.get("blocked_uuids") or [])
    if force:
        blocked_uuids.clear()

    # Detect which local conversation UUIDs were created or modified in THIS sandbox
    local_convs = app_dir / "conversations"
    dirty_uuids: list[str] = []
    if local_convs.is_dir():
        for db_file in sorted(local_convs.glob("*.db")):
            cid = db_file.stem
            cur_sig = sqlite_signature(db_file)
            base_sig = hydrated_sigs.get(cid)
            if base_sig is None or cur_sig != base_sig or cid in owned_uuids:
                owned_uuids.add(cid)
                if sig_cache is None or sig_cache.get(cid) != cur_sig:
                    dirty_uuids.append(cid)

    with store_sync_lock(store_dir, my_id) as locked:
        if not locked:
            if not quiet:
                print(
                    f"[agy-session] Could not acquire sync lock for {store_dir}; will retry.",
                    file=sys.stderr,
                )
            return False, 0

        tmp_dir = store_dir / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        other_claims = get_other_active_claims(store_dir, my_id)

        skipped_uuids: set[str] = set(blocked_uuids)
        if not force:
            for cid in list(dirty_uuids):
                if cid in other_claims:
                    skipped_uuids.add(cid)
                    blocked_uuids.add(cid)
                    if not quiet:
                        print(
                            f"[agy-session] WARNING: conversation '{cid}' is currently active in "
                            f"sandbox '{other_claims[cid]}'; skipping to avoid conflict. "
                            f"(Run separate conversations per sandbox, or use --force.)",
                            file=sys.stderr,
                        )
            for cid in owned_uuids:
                if cid in other_claims:
                    skipped_uuids.add(cid)
                    blocked_uuids.add(cid)

        owned_uuids -= blocked_uuids

        updates = 0

        # 1. Push ONLY locally created/modified conversations/<uuid>.db & brain/<uuid>/
        for cid in dirty_uuids:
            if cid in skipped_uuids:
                continue
            src_db = local_convs / f"{cid}.db"
            if src_db.is_file():
                cur_sig = sqlite_signature(src_db)
                if sqlite_backup_atomic(src_db, store_dir / "conversations" / f"{cid}.db", tmp_dir):
                    if sig_cache is not None:
                        sig_cache[cid] = cur_sig
                    updates += 1

            src_brain = app_dir / "brain" / cid
            if src_brain.is_dir():
                updates += sync_tree_additive(src_brain, store_dir / "brain" / cid, tmp_dir=tmp_dir)

        # Also sync any brand-new brain/<uuid>/ directory for owned UUIDs even if DB didn't change
        for cid in sorted(owned_uuids - skipped_uuids):
            src_brain = app_dir / "brain" / cid
            if src_brain.is_dir():
                updates += sync_tree_additive(src_brain, store_dir / "brain" / cid, tmp_dir=tmp_dir)

        # 2. Cooperatively merge conversation_summaries.db (table + parents + FTS5)
        local_summaries = app_dir / "conversation_summaries.db"
        if local_summaries.is_file() and (owned_uuids - skipped_uuids or force):
            sum_sig = sqlite_signature(local_summaries)
            if sig_cache is None or sig_cache.get("__summaries__") != sum_sig:
                if merge_conversation_summaries_db(
                    local_summaries=local_summaries,
                    store_summaries=store_dir / "conversation_summaries.db",
                    tmp_dir=tmp_dir,
                    skip_uuids=skipped_uuids,
                ):
                    updates += 1
                if sig_cache is not None:
                    sig_cache["__summaries__"] = sum_sig

        # 3. Additive supplementary dirs & raw metadata
        for rel_dir in SYNC_MISC_DIRS:
            updates += sync_tree_additive(app_dir / rel_dir, store_dir / rel_dir, tmp_dir=tmp_dir)

        if owned_uuids - skipped_uuids or force:
            if merge_json_dict_file(
                app_dir / "cache" / "last_conversations.json",
                store_dir / "cache" / "last_conversations.json",
                tmp_dir,
            ):
                updates += 1

        if merge_jsonl_file(app_dir / "history.jsonl", store_dir / "history.jsonl", tmp_dir):
            updates += 1

        for raw_name in SYNC_RAW_FILES:
            if copy_file_if_newer(app_dir / raw_name, store_dir / raw_name, tmp_dir=tmp_dir):
                updates += 1

        # Refresh this sandbox's active UUID claim
        write_active_claim(store_dir, my_id, sorted(owned_uuids - skipped_uuids))

        if updates > 0 or not (store_dir / ".last_sync.json").exists():
            meta = {
                "last_sync_utc": utc_now_iso(),
                "sandbox_id": my_id,
                "workspace_dir": str(ws),
                "updates": updates,
            }
            atomic_write_bytes(
                store_dir / ".last_sync.json",
                (json.dumps(meta, indent=2) + "\n").encode("utf-8"),
                tmp_dir,
            )

    state["owned_uuids"] = sorted(owned_uuids)
    state["blocked_uuids"] = sorted(blocked_uuids)
    save_local_state(state)
    return True, updates


def cmd_push(args: argparse.Namespace) -> int:
    cfg = load_config()
    if not cfg["persist_sessions"] and not args.force:
        return 0
    ws = get_workspace_dir()
    if ws is None:
        return 0
    store_dir = resolve_store_dir(ws, cfg["session_dir"])
    app_dir = get_app_data_dir()
    my_id = get_sandbox_id()

    ok, updates = sync_once(
        ws=ws,
        store_dir=store_dir,
        app_dir=app_dir,
        my_id=my_id,
        force=args.force,
        quiet=args.quiet,
    )
    if args.release_lock:
        release_active_claim(store_dir, my_id)
    if not args.quiet and ok:
        print(f"[agy-session] Synced {updates} update(s) to {store_dir}")
    return 0 if ok else 1


def cmd_watch(args: argparse.Namespace) -> int:
    cfg = load_config()
    if not cfg["persist_sessions"]:
        return 0
    ws = get_workspace_dir()
    if ws is None:
        return 0
    store_dir = resolve_store_dir(ws, cfg["session_dir"])
    app_dir = get_app_data_dir()
    my_id = get_sandbox_id()

    stop = False

    def handle_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    sig_cache: dict[str, list[int]] = {}
    interval = max(5, int(args.interval))

    while not stop:
        for _ in range(interval):
            if stop:
                break
            time.sleep(1)
        if stop:
            break
        try:
            sync_once(
                ws=ws,
                store_dir=store_dir,
                app_dir=app_dir,
                my_id=my_id,
                force=False,
                quiet=True,
                sig_cache=sig_cache,
            )
        except Exception:
            pass

    return 0


def cmd_should_auto_resume(_args: argparse.Namespace) -> int:
    cfg = load_config()
    if not cfg["persist_sessions"] or not cfg["auto_resume"]:
        return 1
    ws = get_workspace_dir()
    if ws is None:
        return 1
    last_path = get_app_data_dir() / "cache" / "last_conversations.json"
    if not last_path.is_file():
        return 1
    try:
        data = json.loads(last_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get(str(ws)):
            return 0
    except (OSError, json.JSONDecodeError):
        pass
    return 1


def dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for fname in files:
            fpath = Path(root) / fname
            try:
                total += fpath.stat().st_size
            except OSError:
                pass
    return total


def cmd_status(_args: argparse.Namespace) -> int:
    cfg = load_config()
    ws = get_workspace_dir()
    my_id = get_sandbox_id()
    print(f"persist_sessions : {cfg['persist_sessions']}")
    print(f"auto_resume      : {cfg['auto_resume']}")
    print(f"session_dir      : {cfg['session_dir']}")
    print(f"sandbox_id       : {my_id}")
    print(f"workspace_dir    : {ws}")
    if ws is None:
        return 0
    store_dir = resolve_store_dir(ws, cfg["session_dir"])
    print(f"store_path       : {store_dir}")
    print(f"store_exists     : {store_dir.is_dir()}")
    live = list_live_sandboxes(store_dir)
    live_ids = [str(item.get("sandbox_id")) for item in live]
    print(f"sync_mode        : cooperative-merge (active sandboxes: {len(live_ids)} {live_ids})")
    last_sync = store_dir / ".last_sync.json"
    if last_sync.is_file():
        try:
            meta = json.loads(last_sync.read_text(encoding="utf-8"))
            print(f"last_sync_utc    : {meta.get('last_sync_utc')}")
        except (OSError, json.JSONDecodeError):
            pass
    convs = list((store_dir / "conversations").glob("*.db")) if (store_dir / "conversations").is_dir() else []
    size_mb = dir_size_bytes(store_dir) / (1024 * 1024)
    print(f"conversations    : {len(convs)}")
    print(f"store_size_mb    : {size_mb:.2f}")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    cfg = load_config()
    ws = get_workspace_dir()
    if ws is None:
        return 0
    store_dir = resolve_store_dir(ws, cfg["session_dir"])
    convs_dir = store_dir / "conversations"
    if not convs_dir.is_dir():
        print("No persisted conversations found.")
        return 0

    titles: dict[str, tuple[str, str]] = {}
    summaries_db = store_dir / "conversation_summaries.db"
    if summaries_db.is_file():
        try:
            conn = sqlite3.connect(f"file:{summaries_db}?mode=ro", uri=True)
            for cid, title, mtime in conn.execute(
                "SELECT conversation_id, title, last_modified_time FROM conversation_summaries"
            ):
                titles[cid] = (title or "", str(mtime or ""))
            conn.close()
        except sqlite3.Error:
            pass

    dbs = sorted(convs_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dbs:
        print("No persisted conversations found.")
        return 0
    for db in dbs:
        cid = db.stem
        size_kb = db.stat().st_size / 1024
        title, mtime = titles.get(cid, ("", ""))
        label = f" | {title}" if title else ""
        ts = f" | {mtime}" if mtime else ""
        print(f"{cid}  ({size_kb:7.1f} KB){ts}{label}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agy-session",
        description="Workspace-backed Antigravity sandbox session persistence",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("hydrate", help="Restore persisted sessions from workspace into local container state")

    for name in ("push", "sync"):
        p = sub.add_parser(name, help="Checkpoint and cooperatively merge local sessions into workspace store")
        p.add_argument("--force", action="store_true", help="Override active-UUID conflict guard")
        p.add_argument("--release-lock", action="store_true", help="Release this sandbox's active claim after syncing")
        p.add_argument("--quiet", action="store_true", help="Suppress non-error output")

    p_watch = sub.add_parser("watch", help="Periodically sync local sessions in the background")
    p_watch.add_argument("--interval", type=int, default=20, help="Sync interval in seconds (default: 20)")

    sub.add_parser("should-auto-resume", help="Exit 0 if auto_resume is enabled and prior session exists")
    sub.add_parser("status", help="Show session persistence status")
    sub.add_parser("list", help="List persisted conversations in the workspace store")

    parsed = parser.parse_args(argv)
    if parsed.command == "hydrate":
        return cmd_hydrate(parsed)
    if parsed.command in {"push", "sync"}:
        return cmd_push(parsed)
    if parsed.command == "watch":
        return cmd_watch(parsed)
    if parsed.command == "should-auto-resume":
        return cmd_should_auto_resume(parsed)
    if parsed.command == "status":
        return cmd_status(parsed)
    if parsed.command == "list":
        return cmd_list(parsed)
    return 1


if __name__ == "__main__":
    sys.exit(main())
