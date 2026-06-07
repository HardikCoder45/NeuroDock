#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def slug(value: str) -> str:
    value = re.sub(r"\.git$", "", value.strip())
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:80] or "agent"


def infer_id(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        return slug(f"{parts[-2]}-{parts[-1]}")
    if parts:
        return slug(parts[-1])
    return slug(parsed.netloc or "agent")


def load_registry(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "updated_at": utc_now(), "agents": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("agents"), list):
        data["agents"] = []
    return data


@contextmanager
def registry_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        except ImportError:
            pass
        try:
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_UN)
            except ImportError:
                pass


def save_registry(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = utc_now()
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def git_clone(url: str, target: Path, ref: str | None = None) -> str | None:
    command = ["git", "clone", "--depth", "1"]
    if ref:
        command.extend(["--branch", ref])
    command.extend([url, str(target)])
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"git clone failed with exit {result.returncode}")
    commit = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], text=True, capture_output=True, check=False)
    return commit.stdout.strip() if commit.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Download an agent repo into a NeuroDock apps folder.")
    parser.add_argument("url", help="Git repository URL.")
    parser.add_argument("--hub", type=Path, default=Path.cwd() / ".agents" / "agents", help="Hub root.")
    parser.add_argument("--id", dest="agent_id", help="Agent id/folder name. Defaults to owner-repo from URL.")
    parser.add_argument("--ref", help="Git branch/tag to clone.")
    parser.add_argument("--force", action="store_true", help="Delete and replace an existing app folder.")
    parser.add_argument("--no-registry", action="store_true", help="Download only; do not update registry.")
    args = parser.parse_args()

    hub = args.hub.expanduser().resolve()
    agent_id = slug(args.agent_id or infer_id(args.url))
    apps_dir = hub / "apps"
    target = apps_dir / agent_id

    if target.exists():
        if not args.force:
            raise SystemExit(f"Refusing to overwrite existing folder: {target}")
        shutil.rmtree(target)

    apps_dir.mkdir(parents=True, exist_ok=True)
    commit = git_clone(args.url, target, ref=args.ref)

    manifest = {
        "id": agent_id,
        "name": agent_id,
        "description": "",
        "source": {"type": "git", "url": args.url, "ref": args.ref, "commit": commit},
        "app_path": str(target),
        "frameworks": [],
        "languages": [],
        "required_env": [],
        "tools": [],
        "protocols": [],
        "streaming": {"supported": False, "modes": []},
        "adapter": {"kind": "uninspected", "path": None},
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }

    if not args.no_registry:
        registry_path = hub / "registry" / "agents.json"
        with registry_lock(registry_path):
            registry = load_registry(registry_path)
            registry["agents"] = [agent for agent in registry["agents"] if agent.get("id") != agent_id]
            registry["agents"].append(manifest)
            save_registry(registry_path, registry)

    print(json.dumps({"agent_id": agent_id, "path": str(target), "commit": commit, "registry_updated": not args.no_registry}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
