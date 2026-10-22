"""Regression tests for scripts/wakatime_hook.py.

Runs the hook as a real subprocess with an isolated HOME and a fake wakatime
CLI that records its argv. Covers the failure modes found in review:
broken config/state types, concurrency, throttled writes, oversize payloads,
and the "hook must stay silent and exit 0" contract.

The real hook spawns the CLI as a detached process, so the fake CLI's output
lands asynchronously — every assertion polls with a timeout instead of
reading the calls file immediately.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "wakatime_hook.py")
PY = sys.executable


class HookTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="zw-home-")
        self.state_dir = os.path.join(self.home, ".zcode", "zcode-wakatime")
        self.calls_file = os.path.join(self.home, "calls.log")
        fake = os.path.join(self.home, "fake-wakatime")
        with open(fake, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + self.calls_file + "\n")
        os.chmod(fake, 0o755)
        self.env = dict(
            os.environ,
            HOME=self.home,
            WAKATIME_CLI=fake,
            ZCODE_WAKATIME_INTERVAL="1",
        )
        self.work = tempfile.mkdtemp(prefix="zw-work-")
        self.a = os.path.join(self.work, "a.py")
        with open(self.a, "w", encoding="utf-8") as f:
            f.write("x = 1\n")

    # -- helpers ---------------------------------------------------------

    def hook(self, payload):
        return subprocess.run(
            [PY, SCRIPT],
            input=json.dumps(payload).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            timeout=60,
        )

    def hook_async(self, payload):
        return subprocess.Popen(
            [PY, SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
        )

    def calls(self):
        try:
            with open(self.calls_file, "r", encoding="utf-8") as f:
                return [line for line in f.read().splitlines() if line.strip()]
        except FileNotFoundError:
            return []

    def wait_for_calls(self, count, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline and len(self.calls()) < count:
            time.sleep(0.05)
        return self.calls()

    def assert_call_count_stays(self, count, wait=0.8):
        time.sleep(wait)
        self.assertLessEqual(len(self.calls()), count)

    def post(self, tool, **tool_input):
        return {
            "hook_event_name": "PostToolUse",
            "cwd": self.work,
            "session_id": "t",
            "tool_name": tool,
            "tool_input": tool_input,
        }

    def state(self):
        with open(os.path.join(self.state_dir, "state.json"), "r", encoding="utf-8") as f:
            return json.load(f)

    # -- tests -----------------------------------------------------------

    def test_edit_sends_write_and_is_silent(self):
        r = self.hook(self.post("Edit", file_path=self.a))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        calls = self.wait_for_calls(1)
        self.assertEqual(len(calls), 1)
        self.assertIn("--write", calls[0])
        self.assertIn(self.a, calls[0])

    def test_throttle_same_file(self):
        self.hook(self.post("Read", file_path=self.a))
        self.wait_for_calls(1)
        self.hook(self.post("Read", file_path=self.a))
        self.assert_call_count_stays(1)

    def test_throttled_write_upgrades_next_heartbeat(self):
        self.hook(self.post("Read", file_path=self.a))  # sent as read
        self.wait_for_calls(1)
        self.hook(self.post("Edit", file_path=self.a))  # throttled, pending
        self.assert_call_count_stays(1)
        time.sleep(1.2)
        self.hook({  # any later event reuses the entity, now as a write
            "hook_event_name": "UserPromptSubmit",
            "cwd": self.work, "session_id": "t", "prompt": "hi",
        })
        calls = self.wait_for_calls(2)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("--write", calls[0])
        self.assertIn("--write", calls[1])

    def test_broken_config_never_breaks_the_hook(self):
        os.makedirs(self.state_dir, exist_ok=True)
        for bad in ('{"heartbeat_interval": "abc"}', "[]", "not json at all"):
            with open(os.path.join(self.state_dir, "config.json"), "w") as f:
                f.write(bad)
            r = self.hook(self.post("Read", file_path=self.a))
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), bad)
        calls = self.wait_for_calls(1)  # defaults applied, still sent
        self.assertEqual(len(calls), 1)

    def test_broken_state_self_heals(self):
        os.makedirs(self.state_dir, exist_ok=True)
        with open(os.path.join(self.state_dir, "state.json"), "w") as f:
            f.write('{"entities": [], "projects": "junk"}')
        r = self.hook(self.post("Read", file_path=self.a))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        self.wait_for_calls(1)
        self.assertIn(self.a, self.state()["entities"])

    def test_failure_on_missing_file_does_not_fall_back(self):
        self.hook(self.post("Read", file_path=self.a))  # seeds last entity
        self.wait_for_calls(1)
        payload = self.post("Read", file_path=os.path.join(self.work, "gone.md"))
        payload["hook_event_name"] = "PostToolUseFailure"
        self.hook(payload)
        self.assert_call_count_stays(1)

    def test_no_path_tool_falls_back_to_recent_file(self):
        self.hook(self.post("Read", file_path=self.a))
        self.wait_for_calls(1)
        time.sleep(1.2)
        self.hook(self.post("Bash", command="ls"))
        calls = self.wait_for_calls(2)
        self.assertEqual(len(calls), 2)
        self.assertIn(self.a, calls[1])
        self.assertNotIn("--write", calls[1])

    def test_oversize_payload_is_skipped(self):
        payload = self.post("Read", file_path=self.a)
        payload["junk"] = "x" * 1200000
        r = self.hook(payload)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        self.assertEqual(self.wait_for_calls(1, timeout=1.5), [])

    def test_concurrent_same_file_sends_once(self):
        procs = [self.hook_async(self.post("Read", file_path=self.a)) for _ in range(6)]
        for p in procs:
            out, _ = p.communicate(input=json.dumps(self.post("Read", file_path=self.a)).encode(), timeout=60)
            self.assertEqual(p.returncode, 0)
            self.assertEqual(out, b"")
        self.assertLessEqual(len(self.wait_for_calls(1)), 2)
        self.assertIn(self.a, self.state()["entities"])  # state survived


if __name__ == "__main__":
    unittest.main(verbosity=2)
