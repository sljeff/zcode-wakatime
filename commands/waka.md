---
description: Check WakaTime tracking status (CLI, hooks, today's stats)
---

Run a WakaTime self-check with Bash and report the results. Checks:

1. **wakatime CLI**: `command -v wakatime || ls "$HOME/.local/bin/wakatime" "$HOME/.wakatime/wakatime-cli" 2>/dev/null`
2. **python3** (the hook runs on it): `command -v python3 || ls /usr/bin/python3`, plus `$WAKATIME_PYTHON` if the user set it
3. **API key**: `grep -q '^[[:space:]]*api_key' "$HOME/.wakatime.cfg" && echo present || echo missing` — never print the value; if missing, send the user to https://wakatime.com/settings/api-key and `wakatime --config-write api_key=<key>`
4. **Today's total**: run the discovered CLI with `--today` (needs the key)
5. **Last heartbeat**: read `~/.zcode/zcode-wakatime/state.json`; find the newest entry under `entities` and convert its `ts` (unix seconds) to local time (`date -r <ts>` on macOS, `date -d @<ts>` on Linux). The file is only written when a heartbeat is actually sent — right after install it is empty until some tool touches a file.
6. **Debug log**: read the last line of `~/.zcode/zcode-wakatime/debug.log` if it exists

Report format:

- Today's total coding time (from step 4)
- Time of the last heartbeat and which file it was for
- If anything is broken, one fix instruction per problem:
  - CLI missing → "Install it with `pipx install wakatime` (or `pip3 install --user wakatime`)"
  - python3 missing or broken → suggest installing python3, or setting `WAKATIME_PYTHON` to a working interpreter
  - API key missing → see step 3
  - state.json missing while tools have touched files this session → hooks are not firing: check the zcode-wakatime plugin is installed and enabled in Settings → Plugins
  - debug.log exists and its last lines contain errors → quote at most two of them

Never print the API key, and never dump state.json wholesale; name only the one most recent file path.
