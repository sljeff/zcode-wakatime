#!/usr/bin/env python3
"""zcode-wakatime hook: turn ZCode hook events into WakaTime heartbeats.

Reads one hook payload (JSON) from stdin, decides whether a heartbeat is due
(throttled per file), and launches the wakatime CLI as a detached process.

Design constraints:
- Must return fast (tens of ms): parse, throttle check, detached spawn, exit.
- Must stay silent on stdout (ZCode parses hook stdout as strict JSON) and
  quiet on stderr; failures are only written to debug.log when debugging.
- Zero third-party dependencies; Python 3.9+ (system python3 is enough).
- Exit code is always 0; no exception may ever reach the host.

Event mapping:
- PostToolUse / PostToolUseFailure: the file the tool touched (tool_input),
  is_write true for file-mutating tools; failures never count as writes.
- UserPromptSubmit / Stop: re-send the most recent file of the current
  project (read heartbeat) if it is fresh enough.
"""

import json
import os
import shutil
import subprocess
import sys
import time

VERSION = "0.1.2"
# First token "ZCode" is the editor tag WakaTime attributes the heartbeat to;
# without it the server guesses an editor from the plugin name ("Zcode").
PLUGIN_ARG = "ZCode zcode-wakatime/" + VERSION

WRITE_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit", "ApplyPatch"}
# Tool input keys that carry a file path, in priority order.
PATH_KEYS = ("file_path", "filePath", "notebook_path", "path", "abs_path")

# Payloads may embed whole file contents or command output; parsing those
# burns the hook's time budget, so oversize payloads are skipped entirely.
MAX_PAYLOAD_BYTES = 1000000

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".zcode", "zcode-wakatime")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOCK_FILE = os.path.join(STATE_DIR, "state.lock")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")
DEBUG_LOG = os.path.join(STATE_DIR, "debug.log")

DEFAULT_HEARTBEAT_INTERVAL = 120  # seconds per file, matches editor plugins
FRESH_ENTITY_SECONDS = 900       # max age for reusing a project's last file

_config = {}
INTERVAL = DEFAULT_HEARTBEAT_INTERVAL


def debug(msg):
    # Only enabled via {"debug": true} in config.json; never on by default.
    if not _config.get("debug"):
        return
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write("%.3f %s\n" % (time.time(), msg))
    except Exception:
        pass


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_config():
    """Populate _config/INTERVAL from config.json; never raises, and a
    broken or mistyped config falls back to defaults instead of crashing."""
    global _config, INTERVAL
    cfg = load_json(CONFIG_FILE, {})
    if not isinstance(cfg, dict):
        cfg = {}
    _config = cfg
    # Env override is for debugging/tests; config values are clamped sanely.
    raw = os.environ.get(
        "ZCODE_WAKATIME_INTERVAL", cfg.get("heartbeat_interval", DEFAULT_HEARTBEAT_INTERVAL)
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_HEARTBEAT_INTERVAL
    if "ZCODE_WAKATIME_INTERVAL" in os.environ:
        INTERVAL = min(max(value, 1), 86400)
    else:
        INTERVAL = min(max(value, 30), 86400)


def find_cli():
    """Locate the wakatime CLI without paying for a filesystem walk."""
    override = os.environ.get("WAKATIME_CLI")
    if override:
        override = os.path.expanduser(override)
        if os.path.isfile(override) and os.access(override, os.X_OK):
            return override
    for name in ("wakatime", "wakatime-cli"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        os.path.join(HOME, ".local", "bin", "wakatime"),
        os.path.join(HOME, ".local", "bin", "wakatime-cli"),
        os.path.join(HOME, ".wakatime", "wakatime-cli"),
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def entity_from_tool(tool_name, tool_input):
    """Return (abs_file_path_or_None, is_write, had_path) for a tool event.

    had_path distinguishes "tool named a file that no longer exists" (report
    nothing rather than attributing the activity to another file) from
    "tool touches no single file" (caller may fall back to the project's
    last file).
    """
    is_write = tool_name in WRITE_TOOLS
    if not isinstance(tool_input, dict):
        return None, is_write, False
    for key in PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            path = os.path.expanduser(value.strip())
            if not os.path.isabs(path):
                path = os.path.join(_cwd, path)
            if os.path.isfile(path):
                return path, is_write, True
            if not os.path.isdir(path):
                return None, is_write, True  # named file is gone
    return None, is_write, False


def send_heartbeat(cli, entity, is_write):
    args = [
        cli,
        "--entity", entity,
        "--entity-type", "file",
        "--project-folder", _cwd,
        "--plugin", PLUGIN_ARG,
    ]
    if is_write:
        args.append("--write")

    debug("spawning: %s" % " ".join(args))
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True  # detach: survive this script
    else:
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, **kwargs)


def normalize_state(state):
    """Coerce a loaded state file into the expected shape; drop junk entries
    so one bad write can never silence the plugin permanently."""
    if not isinstance(state, dict):
        return {"entities": {}, "projects": {}}

    def clean(table):
        if not isinstance(table, dict):
            return {}
        out = {}
        for key, value in table.items():
            if isinstance(key, str) and isinstance(value, dict) and isinstance(value.get("ts"), (int, float)):
                out[key] = value
        return out

    return {"entities": clean(state.get("entities")), "projects": clean(state.get("projects"))}


def write_state(state, now):
    state["entities"] = {k: v for k, v in state["entities"].items() if now - v.get("ts", 0) < 86400}
    state["projects"] = {k: v for k, v in state["projects"].items() if now - v.get("ts", 0) < 86400}
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    tmp = "%s.%d.tmp" % (STATE_FILE, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


def acquire_lock():
    """Serialize concurrent hooks. Returns an fd to release, -1 to proceed
    unlocked (non-posix or lock unavailable for other reasons), or None when
    another hook currently holds the lock (skip this event entirely)."""
    if os.name != "posix":
        return -1
    try:
        os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
        import errno
        import fcntl
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EAGAIN):
                os.close(fd)
                return None
            raise
        return fd
    except Exception:
        return -1


def main():
    global _cwd
    load_config()
    try:
        raw = sys.stdin.read()
        if not raw.strip() or len(raw) > MAX_PAYLOAD_BYTES:
            return
        payload = json.loads(raw)
    except Exception:
        return

    event = payload.get("hook_event_name", "")
    _cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id", "unknown")
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except Exception:
            tool_input = {}

    lock_fd = acquire_lock()
    if lock_fd is None:
        return  # a concurrent hook is mid-flight and will cover this instant
    try:
        state = normalize_state(load_json(STATE_FILE, {}))
        now = time.time()
        entities = state["entities"]
        projects = state["projects"]

        def last_project_entity():
            last = projects.get(_cwd)
            if not isinstance(last, dict):
                return None
            entity = last.get("entity")
            if (
                isinstance(entity, str)
                and isinstance(last.get("ts"), (int, float))
                and now - last["ts"] <= FRESH_ENTITY_SECONDS
                and os.path.isfile(entity)
            ):
                return entity
            return None

        entity, is_write, had_path = None, False, False
        if event in ("PostToolUse", "PostToolUseFailure"):
            entity, is_write, had_path = entity_from_tool(tool_name, tool_input)
            if event == "PostToolUseFailure":
                is_write = False  # a failed tool did not change the file
            if not entity and not had_path:
                # Bash/Grep/Agent etc. touch no single file; attribute the
                # activity to the project's most recent file when fresh.
                entity = last_project_entity()
        elif event in ("UserPromptSubmit", "Stop"):
            entity = last_project_entity()

        debug("%s session=%s tool=%s entity=%s" % (event, session_id, tool_name, entity))
        if not entity:
            return

        entry = entities.get(entity) if isinstance(entities.get(entity), dict) else {}
        last_sent = entry.get("ts", 0) if isinstance(entry.get("ts"), (int, float)) else 0
        pending_write = bool(entry.get("pending_write"))
        due = (now - last_sent) >= INTERVAL

        if not due:
            if is_write and not pending_write:
                # The write itself is throttled; remember it so the next
                # heartbeat for this file is reported as a write.
                entities[entity] = {"ts": last_sent, "pending_write": True}
                try:
                    write_state(state, now)
                except Exception as e:
                    debug("state write failed: %r" % (e,))
            return

        cli = find_cli()
        if not cli:
            debug("wakatime CLI not found; see README for install instructions")
            return
        try:
            send_heartbeat(cli, entity, is_write or pending_write)
        except Exception as e:
            debug("spawn failed: %r" % (e,))
            return  # do not record state on failure so the next event retries

        entities[entity] = {"ts": now}
        projects[_cwd] = {"entity": entity, "ts": now}
        try:
            write_state(state, now)
        except Exception as e:
            debug("state write failed: %r" % (e,))
    finally:
        if isinstance(lock_fd, int) and lock_fd >= 0:
            try:
                os.close(lock_fd)
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            debug("unhandled: %r" % (e,))
        except Exception:
            pass
    sys.exit(0)
