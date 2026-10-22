# zcode-wakatime

English | [中文](#中文)

[WakaTime](https://wakatime.com) time tracking for **ZCode**. It hooks into ZCode's
tool events and reports your agent-session coding activity to WakaTime as
heartbeats through the official `wakatime` CLI, following the same approach
as [wakatime/claude-code-wakatime](https://github.com/wakatime/claude-code-wakatime):
hooks feed the CLI, which owns transport, offline queueing and language
detection.

## How it works

- `PostToolUse` / `PostToolUseFailure` → the file the tool touched (Edit/Write
  count as writes, everything else as reads; tools without a file path fall
  back to the project's most recent file)
- `UserPromptSubmit` / `Stop` → re-send the project's most recent file while
  it is fresh, so prompting and wrap-up time is counted
- Each file sends at most one heartbeat per 120 s (configurable), far below
  WakaTime's rate limits. Durations are assembled by WakaTime from heartbeats
  inside 15-minute windows — you don't need to do anything.
- Heartbeats go through the `wakatime` CLI, which brings offline queueing
  (`~/.wakatime/offline_heartbeats.bdb`), automatic retries and language
  detection for free.

The hook script finishes in ~50 ms and detaches the CLI, so it never slows
down your session.

## Requirements

- ZCode ≥ 0.17.0 (verified against 0.17.0)
- Python 3.9+ — any working `python3` (on a fresh macOS, install Xcode
  Command Line Tools first: `xcode-select --install`)
- The `wakatime` CLI:

  ```bash
  pipx install wakatime          # preferred
  pip3 install --user wakatime   # alternative
  ```

  ⚠️ `brew install wakatime` installs the menu-bar app, **not** the CLI.

- A WakaTime account. If you have never used the CLI here, set your API key
  once (`wakatime --config-write api_key=...`; key from
  [wakatime.com/settings/api-key](https://wakatime.com/settings/api-key)).

## Install

In ZCode: **Plugin Marketplace → Add → Add Plugin Marketplace**, paste
`https://github.com/sljeff/zcode-wakatime`, then install **zcode-wakatime**
from the *Personal* tab. That's all — plugin hooks are active immediately, no
extra configuration.

CLI equivalent:

```bash
zcode plugins marketplace add <repo-or-path>
zcode plugins install zcode-wakatime
```

Then work normally in ZCode and check
[your dashboard](https://wakatime.com/dashboard); use the `/waka` command in
ZCode for a self-check (CLI found? hooks firing? today's total).

## Privacy

What is sent to WakaTime (api.wakatime.com), per heartbeat:

- the absolute path of the file the tool touched
- the project folder (WakaTime derives the project name from it)
- a timestamp and whether the activity was a write
- the plugin tag `ZCode zcode-wakatime/<version>`

What the plugin itself **never** sends: prompt text, tool output, file contents.

The wakatime CLI additionally attaches standard metadata to every heartbeat
(machine name, OS, language, branch, line counts), and by default also syncs
AI activity derived from local AI-tool session logs (Claude Code, Cursor,
ZCode itself, ...) — a built-in CLI behavior; add `--sync-ai-disabled` in
`scripts/wakatime_hook.py` if you do not want it. The CLI's `hide_file_names`
/ `hide_project_names` settings are respected automatically. Throttle state
(file paths) stays local in `~/.zcode/zcode-wakatime/state.json`.

## Configuration

Optional `~/.zcode/zcode-wakatime/config.json`:

```json
{ "heartbeat_interval": 120, "debug": true }
```

- `heartbeat_interval` — minimum seconds between heartbeats per file
- `debug` — append diagnostics to `~/.zcode/zcode-wakatime/debug.log`
- `WAKATIME_PYTHON` env var — force the python3 used by the hook wrapper
- `WAKATIME_CLI` env var — force the wakatime CLI path
- `ZCODE_WAKATIME_INTERVAL` env var — override the interval for
  debugging/testing (bypasses the 30 s floor)

## Troubleshooting

Run `/waka`. It checks the CLI, prints today's total and the last heartbeat,
and names the fix for each problem it finds. Common cases:

- *CLI missing* → `pip3 install --user wakatime`
- *No heartbeats* → plugin disabled? Check **Settings → Plugins**.
- *Need detail* → set `"debug": true`, work a minute, read
  `~/.zcode/zcode-wakatime/debug.log`.

## Uninstall

Uninstall the plugin in **Settings → Plugins** (or
`zcode plugins uninstall zcode-wakatime`), optionally remove the marketplace,
then delete leftover state:

```bash
rm -rf ~/.zcode/zcode-wakatime
```

## Development

Single-file hook in [`scripts/wakatime_hook.py`](scripts/wakatime_hook.py),
shim wrapper in `scripts/run`, hook declarations in `hooks/hooks.json`.
Real (redacted) hook payloads from ZCode 0.17.0 are kept in
[docs/payload-samples/](docs/payload-samples/) for future maintainers.

License: BSD-3-Clause — see [LICENSE](LICENSE).

---

## 中文

**ZCode 的 WakaTime 编码时间统计插件**。通过 ZCode 的工具事件 hook，把你在
agent 会话里的编码活动经官方 `wakatime` CLI 以心跳形式上报给 WakaTime——
与官方 Claude Code 插件（wakatime/claude-code-wakatime）同一路线：hook 喂给
CLI，传输、离线队列、语言识别都由 CLI 负责。

### 工作原理

- `PostToolUse` / `PostToolUseFailure` → 上报工具涉及的文件（Edit/Write 记为
  写操作，其余记为读操作；无文件路径的工具回退到项目内最近活动的文件）
- `UserPromptSubmit` / `Stop` → 项目最近文件仍在活跃期内时补一次心跳，
  让提问与收尾时间也被计入
- 每个文件最短 120 秒才发一次心跳（可配置）；WakaTime 按 15 分钟窗口内的
  心跳拼出时长，无需额外操作
- 心跳走 `wakatime` CLI：离线自动排队（`~/.wakatime/offline_heartbeats.bdb`）、
  自动重试、按后缀识别语言

hook 脚本约 50 ms 内结束并 detach CLI，不影响会话速度。

### 环境要求

- ZCode ≥ 0.17.0（已在 0.17.0 验证）
- Python 3.9+——任意可用的 `python3`（全新 macOS 需先装 Xcode Command Line
  Tools：`xcode-select --install`）
- `wakatime` CLI：

  ```bash
  pipx install wakatime          # 首选
  pip3 install --user wakatime   # 备选
  ```

  ⚠️ `brew install wakatime` 装的是菜单栏 App，不是 CLI。
- WakaTime 账号；首次使用 CLI 需
  `wakatime --config-write api_key=你的key`（[获取 API key](https://wakatime.com/settings/api-key)）

### 安装

ZCode 中：**插件市场 → 添加 → 添加插件市场**，粘贴
`https://github.com/sljeff/zcode-wakatime`，然后在「个人」页安装
**zcode-wakatime**。装完即生效，无需任何额外配置。之后在 ZCode 里正常干活，去
[dashboard](https://wakatime.com/dashboard) 查看；也可用 `/waka` 命令自检。

CLI 等价操作：

```bash
zcode plugins marketplace add <仓库地址或路径>
zcode plugins install zcode-wakatime
```

### 隐私说明

每条心跳发送给 WakaTime（api.wakatime.com）的内容：工具涉及文件的绝对路径、
项目目录（WakaTime 据此推导项目名）、时间戳、是否为写操作、插件标识
`ZCode zcode-wakatime/<版本>`。

**插件本身不会**发送：提示词、工具输出、文件内容。

wakatime CLI 还会为每条心跳附加标准元数据（机器名、操作系统、语言、分支、
行数），且默认会同步从本机 AI 工具会话日志（Claude Code、Cursor、ZCode 自身
等）解析出的 AI 活动数据——这是 CLI 的内建行为，不想要可在
`scripts/wakatime_hook.py` 中加 `--sync-ai-disabled` 参数关闭。CLI 的
`hide_file_names` / `hide_project_names` 设置自动生效；节流状态（含文件路径）
保存在本地 `~/.zcode/zcode-wakatime/state.json`。

### 配置

可选 `~/.zcode/zcode-wakatime/config.json`：

```json
{ "heartbeat_interval": 120, "debug": true }
```

`heartbeat_interval` 为每文件最短心跳间隔秒数（30–86400）；`debug` 开启后诊断写入
`~/.zcode/zcode-wakatime/debug.log`。环境变量 `WAKATIME_PYTHON`、`WAKATIME_CLI`、
`ZCODE_WAKATIME_INTERVAL`（调试用，绕过下限）可分别强制指定 python3、wakatime CLI
路径与心跳间隔。

### 排障

先跑 `/waka`（检查 CLI、今日统计、最近心跳，并给出修复指引）。常见问题：
CLI 缺失 → 重新安装 CLI；无心跳 → 到「设置 → 插件」确认插件已启用；
需要细节 → 开 `"debug": true` 后读 debug 日志。

### 卸载

在「设置 → 插件」卸载插件（或 `zcode plugins uninstall zcode-wakatime`），
可一并移除市场源，最后清理残留状态：`rm -rf ~/.zcode/zcode-wakatime`。

### 开发

核心逻辑在单文件 [`scripts/wakatime_hook.py`](scripts/wakatime_hook.py)；
ZCode 0.17.0 的真实（脱敏）hook payload 样本在
[docs/payload-samples/](docs/payload-samples/)，供后续维护者参考。

许可证：BSD-3-Clause，见 [LICENSE](LICENSE)。
