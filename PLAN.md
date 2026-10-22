# zcode-wakatime 开源插件开发计划

## 一、定位

为 ZCode 做一个 WakaTime 时间统计插件：通过 ZCode hooks 把编码活动以心跳形式上报给 wakatime CLI，让 agent IDE 里的工作时间进入 WakaTime 统计。模式复刻官方的 Claude Code 插件，宿主换成 ZCode（目前空白，无任何现存插件）。

## 二、已核实的事实与来源

| 结论 | 来源 |
|---|---|
| ZCode 无官方/社区 WakaTime 插件（列表里只有 Zed，是另一个产品） | https://wakatime.com/plugins |
| 官方先例：用 Claude Code hooks 发心跳，含 AI 用量/生成行数统计 | https://github.com/wakatime/claude-code-wakatime 、https://wakatime.com/claude-code |
| 插件用 API key（Basic auth）上报；正常应调 wakatime CLI 而非直接调 API；durations 由 15 分钟内的心跳拼接而成；全局限速 10 req/s | https://wakatime.com/developers |
| 新插件收录方式：放 GitHub → 把仓库发给 WakaTime → 进 Community plugins 列表 | https://wakatime.com/help/creating-plugin |
| wakatime CLI 安装：PyPI 有（当前 14.0.1）；**注意 `brew install wakatime` 装的是桌面托盘 App，不是 CLI**，别写错文档 | https://pypi.org/project/wakatime/ 、https://github.com/wakatime/wakatime-cli |
| ZCode 插件规范：`.zcode-plugin/plugin.json`（兼容识别 `.claude-plugin/`），可贡献 hooks/commands/skills/mcpServers/agents；插件自带的 hook 自动启用 hook runner；7 个事件：`SessionStart` `UserPromptSubmit` `PreToolUse` `PermissionRequest` `PostToolUse` `PostToolUseFailure` `Stop`；marketplace 支持从 GitHub 仓库/Git URL/本地目录添加 | ZCode 内置文档（`zcode-guide:zcode-configuration-guide`，无公开网页；开发时用 `/plugin-creator` 起骨架） |

两个关键点：**ZCode 的 hook 事件与 Claude Code 完全同名**，官方插件的 hook 逻辑可近乎 1:1 移植；**hook payload 的具体 JSON 结构没有公开文档**，必须先实测（这是计划里第一个里程碑）。

## 三、架构设计

**事件 → 心跳映射：**

| ZCode 事件 | 处理 | 心跳参数 |
|---|---|---|
| `PostToolUse` | 核心信号。Edit/Write → 写操作；Read/Bash/Grep 等 → 读操作 | `entity` = 工具入参里的文件路径（无文件路径时取 cwd 下最近活动文件），`is_write` 按工具类型置位 |
| `UserPromptSubmit` | 你在主动工作 | 复用最近 entity 发一次心跳 |
| `Stop` | 一轮任务结束 | 收尾心跳（保证最后一段活动被计入） |
| `SessionStart` | 可选 | 记录会话开始，不发心跳 |

**上报方式：** 调 `wakatime` CLI（官方建议，CLI 自带断网离线队列 `~/.wakatime/offline_heartbeats.bdb`、自动重试、按后缀识别 language），不自己实现 HTTP 上报。`project` 取 git 仓库根目录名（无 git 时取目录名）。API key 沿用 `~/.wakatime.cfg`，插件场景用 API key 正是新政策允许的用法。

**节流：** 每 entity 至少间隔 120 秒才发（状态存 `~/.zcode/zcode-wakatime/state.json`），与官方编辑器插件节奏一致，远低于 10 req/s 限速。

**性能红线：** hook 不能拖慢会话。脚本只做“读 stdin → 查节流 → detached 方式拉起 CLI（`nohup ... &`）”三件事，自身执行控制在 ~50ms 内，任何异常静默退出、绝不向 ZCode 报错。

**实现语言：** 单文件 Python 3（macOS/Linux 系统自带，零第三方依赖）。官方 Claude Code 插件用 TypeScript + Node，ZCode 侧没必要引入 Node 依赖。

## 四、目录结构

```
zcode-wakatime/
├── .zcode-plugin/plugin.json      # 插件清单（name + hooks + commands）
├── hooks/hooks.json               # 声明 PostToolUse / UserPromptSubmit / Stop
├── scripts/wakatime_hook.py       # 核心脚本（解析 payload、节流、调 CLI）
├── commands/waka.md               # /waka 命令：查今日统计、自检（CLI 是否安装、最近心跳）
├── README.md                      # 双语：是什么/截图/安装/隐私说明（发了什么数据给 WakaTime）
├── LICENSE                        # BSD-3-Clause（与官方插件一致）或 MIT
└── PLAN.md                        # 本计划
```

## 五、里程碑

**M0 准备（半小时）**：建目录、`git init`；精读参考实现 `wakatime/claude-code-wakatime` 的 `hooks/` 与 `src/`，抄它的字段映射和节流策略。
验收：能说出它的 PostToolUse 处理逻辑每一行在干什么。

**M1 实测 payload（关键，1 小时）**：写一个只落日志的临时 hook（`tee` 到文件），挂到 `~/.zcode/cli/config.json`（记得 `hooks.enabled: true`），在 ZCode 里正常干活几分钟，收集 `PostToolUse` / `UserPromptSubmit` / `Stop` 的真实 JSON。
验收：拿到三种事件的完整 payload 样本，确定文件路径、工具名、cwd 字段的确切位置。

**M2 核心脚本（2 小时）**：实现 `wakatime_hook.py`（先装 CLI：`pip3 install --user wakatime` 或 `pipx install wakatime`）；继续用配置文件方式挂载，手动触发工具调用。
验收：WakaTime dashboard（https://wakatime.com/dashboard ）出现 ZCode 会话的项目/语言/时长；断网后恢复网络，离线心跳被补传。

**M3 插件化（2 小时）**：用 `/plugin-creator` 生成骨架，迁入脚本，声明 hooks 与 `/waka` 命令；从本地目录 marketplace 安装验证（插件 hook 应自动启用 hook runner，无需 `hooks.enabled`）。
验收：以“用户身份”从本地 marketplace 一键安装后，不改任何配置即可产生心跳。

**M4 打磨（半天）**：README（双语、截图、隐私说明：明确只发文件路径/项目名/语言/时间戳给 WakaTime）、错误处理（CLI 缺失时 `/waka` 给出安装指引而非报错）、卸载说明。
验收：找一台没装过 wakatime 的环境（或删掉 CLI）走一遍安装文档，全程无卡点。

**M5 发布（1 小时）**：推 GitHub 公开仓库 → 按 ZCode 文档把仓库添加为 marketplace 供安装 → 按 https://wakatime.com/help/creating-plugin 把仓库发给 WakaTime，申请收入 Community plugins 列表。
验收：GitHub 仓库公开可装；WakaTime 列表收录（或至少提交申请）。

## 六、风险与对策

- **payload 结构未知**：M1 首先实测，不猜字段；样本存进仓库 `docs/payload-samples/`（脱敏），也方便后续维护者。
- **ZCode 版本升级改 hooks 行为**：README 写明验证过的 ZCode 版本；`/waka` 命令内置自检（事件是否触发、CLI 是否在 PATH）。
- **受众小**：零依赖 + 复用 wakatime CLI（协议层不自己维护），把长期维护成本压到最低。
- **心跳噪音**：120 秒/entity 节流硬编码，配置文件可调。

## 七、总验收

你在 ZCode 里正常干活一天 → WakaTime dashboard 出现当天项目与语言分布 → 第二天早上你的 GitHub README waka-box 自动恢复统计（现有 workflow 无需任何改动）。
