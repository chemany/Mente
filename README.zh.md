<p align="center">
  <img src="assets/mente-agent-banner.png" alt="Mente Agent" width="100%">
</p>

<p align="center">
  <a href="./README.md">English</a> · <strong>中文</strong>
</p>

# Mente Agent ☤

<p align="center">
  <a href="https://chemany.github.io/Mente/docs/"><img src="https://img.shields.io/badge/Docs-chemany.github.io%2FMente%2Fdocs-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="https://discord.gg/NousResearch"><img src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/chemany/Mente/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://github.com/chemany/Mente"><img src="https://img.shields.io/badge/GitHub-chemany%2FMente-111827?style=for-the-badge&logo=github&logoColor=white" alt="GitHub Repository"></a>
</p>

**Mente 是一个统一的 AI agent，覆盖编码、自动化、网关工作流和长期记忆。** 它会从经验中沉淀技能，在使用过程中持续优化，主动推动自己保留有价值的知识，检索历史对话，并在跨会话中逐步形成对你的长期理解。你可以把它跑在一台每月几美元的 VPS、GPU 集群，或者几乎闲置零成本的 serverless 基础设施上。它不被绑在你的本地电脑里，你甚至可以在 Telegram 上和它对话，同时让它在云端机器上持续工作。

这个分支还完成了一轮产品公开面的统一收边：

- **对外统一使用 Mente**，CLI、网关进度、消息平台和用户可见回复都不再混用旧品牌。
- **内部执行仍然使用 Codex 支撑的执行器**，这次调整是展示层收口，不是能力降级。
- **网关执行进度重新可见**，对外显示为 Mente 的步骤名称，同时保留底层命令和工具活动明细。
- **配置和管理类操作已经明确化**，通过专门的 Mente skill 处理 API key、provider 鉴权、`.env`、`config.yaml` 与网关重启边界。

<p align="center">
  <img src="assets/mente-stack.svg" alt="Mente product surface with Codex-backed core and npm bootstrap installer" width="100%">
</p>

你可以接任意模型和任意推理服务：[Nous Portal](https://portal.nousresearch.com)、[OpenRouter](https://openrouter.ai)（200+ 模型）、[NVIDIA NIM](https://build.nvidia.com)（Nemotron）、[Xiaomi MiMo](https://platform.xiaomimimo.com)、[z.ai/GLM](https://z.ai)、[Kimi/Moonshot](https://platform.moonshot.ai)、[MiniMax](https://www.minimax.io)、[Hugging Face](https://huggingface.co)、OpenAI，或者你自己的兼容端点。通过 `mente model` 就能切换，不需要改代码，也不会被供应商锁定。

<table>
<tr><td><b>真正可用的终端界面</b></td><td>完整 TUI，支持多行输入、斜杠命令补全、会话历史、打断并改向，以及实时工具输出流。</td></tr>
<tr><td><b>跟着你工作的入口</b></td><td>Telegram、Discord、Slack、WhatsApp、Signal 和 CLI 共用同一个网关进程。支持语音转写，也支持跨平台连续对话。</td></tr>
<tr><td><b>闭环学习能力</b></td><td>带周期性提醒的 agent 记忆系统；复杂任务后自动产出技能；技能在使用中持续改进；基于 FTS5 的会话检索与 LLM 摘要；集成 <a href="https://github.com/plastic-labs/honcho">Honcho</a> 用户建模；兼容 <a href="https://agentskills.io">agentskills.io</a> 开放标准。</td></tr>
<tr><td><b>定时自动化</b></td><td>内置 cron 调度，可把结果投递到任意平台。日报、夜间备份、每周审计都能用自然语言配置后无人值守执行。</td></tr>
<tr><td><b>委派与并行</b></td><td>可以生成隔离子代理并行工作，也可以写 Python 脚本通过 RPC 调工具，把多步流程压缩成零上下文成本的单回合执行。</td></tr>
<tr><td><b>不只跑在你的笔记本上</b></td><td>内置六种终端后端：local、Docker、SSH、Daytona、Singularity、Modal。Daytona 和 Modal 支持类 serverless 持久环境，空闲时休眠、需要时唤醒，几乎不花闲置成本。既能跑在 $5 VPS，也能跑在 GPU 集群。</td></tr>
<tr><td><b>适合研究与训练</b></td><td>支持批量轨迹生成、Atropos RL 环境，以及用于训练下一代工具调用模型的轨迹压缩。</td></tr>
</table>

---

## 快速安装

### 方案 1：直接使用安装脚本

```bash
curl -fsSL https://raw.githubusercontent.com/chemany/Mente/main/scripts/install.sh | bash
```

支持 Linux、macOS、WSL2，以及 Android 的 Termux。这个一键安装器默认按 release 版本固定安装，也能通过 `--runtime-artifact-manifest` 和 `--runtime-wheel` 从本地或离线资源引导匹配的 vendored runtime。

### 方案 2：npm 引导安装

```bash
npm install -g mente-agent
mente
```

这个 npm 包刻意保持 **很薄**。它只发布 launcher 和 installer 脚本，第一次运行时再自动引导完整的 Mente runtime。默认会从仓库的 `main` 分支完成 bootstrap，你也可以通过 `MENTE_BOOTSTRAP_RELEASE=<tag> mente` 强制安装某个发布版本。它 **不会** 把你本机的 `.env`、`auth.json`、`~/.mente`、`~/.hermes`、sessions、logs 或其它机器私有状态打进包里。

现在，引导出来的私有 Codex runtime 默认会把 `model_auto_compact_token_limit` 设为 `160000`，让长会话更早、更稳定地触发压缩。如果你要手动覆盖这个阈值，可以在 Mente 配置里写：

```yaml
codex:
  model_auto_compact_token_limit: 120000
```

目前仓库里的 npm 包已经 **具备可发布状态，但还没有真正发布到 npm registry**。在首个公开 npm 版本上线前，请先使用上面的方案 1。等包真正发布后，`npm install -g mente-agent` 才是对外的一键安装主路径。

如果你是发布操作人，最短 npm 发布说明见：[docs/releasing/npm.md](docs/releasing/npm.md)。

> **Android / Termux：** 已验证的手动安装路径见 [Termux 指南](https://chemany.github.io/Mente/docs/getting-started/termux)。在 Termux 上，Mente 会安装精简过的 `.[termux]` 依赖集合，因为完整的 `.[all]` 目前会拉到 Android 不兼容的语音依赖。
>
> **Windows：** 暂不支持原生 Windows。请先安装 [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install)，再在 WSL2 里执行上面的命令。
>
> **开发者 / 源码用户：** 如果你是手动克隆仓库，请使用 `./setup-hermes.sh`。这是面向可编辑开发环境的路径，不是面向最终用户的冻结发布安装方式。

安装完成后：

```bash
source ~/.bashrc    # 重新加载 shell（或 source ~/.zshrc）
mente               # 开始对话
```

---

## 快速开始

```bash
mente               # 启动交互式 CLI
mente model         # 选择 LLM provider 和模型
mente tools         # 配置启用哪些工具
mente config set    # 设置单个配置项
mente gateway       # 启动消息网关（Telegram、Discord 等）
mente setup         # 跑完整初始化向导
mente claw migrate  # 从 OpenClaw 迁移（如有）
mente update        # 更新到最新版本
mente doctor        # 检查并诊断问题
```

📖 **[完整文档 →](https://chemany.github.io/Mente/docs/)**

## 这一轮刷新带来了什么

当前 README 反映的是 Mente 最新的打包和 runtime 方向：

- **GitHub 访客当前可用的一条安装命令：** `curl -fsSL https://raw.githubusercontent.com/chemany/Mente/main/scripts/install.sh | bash`
- **npm 发布后的目标一条安装命令：** `npm install -g mente-agent`
- **统一的可见 agent 身份：** 对外回复和进度统一呈现为 `Mente`
- **同样深度的底层执行能力：** 复杂编码和工具执行仍然走 Codex-backed executor
- **更安全的运维表面：** 打包采用白名单方式，配置/管理操作也有 API key、provider 鉴权和重启边界的明确处理

如果你是从 GitHub 第一次接触 Mente，最实用的理解方式是：

1. 先通过直接安装脚本安装 Mente。
2. 执行 `mente`。
3. 让 bootstrap 流程完成完整 runtime 的准备。
4. 再从 CLI 或消息网关里正常使用 Mente。

## CLI 与消息网关速查

Mente 有两个主要入口：直接运行 `mente` 打开终端 UI，或者启动网关后从 Telegram、Discord、Slack、WhatsApp、Signal、Email 等入口和它对话。进入会话后，很多斜杠命令在两类入口中是共通的。

| 操作 | CLI | 消息平台 |
|---------|-----|---------------------|
| 开始聊天 | `mente` | 运行 `mente gateway setup` + `mente gateway start`，然后给机器人发消息 |
| 开启全新会话 | `/new` 或 `/reset` | `/new` 或 `/reset` |
| 切换模型 | `/model [provider:model]` | `/model [provider:model]` |
| 设置人格 | `/personality [name]` | `/personality [name]` |
| 重试或撤销上一轮 | `/retry`, `/undo` | `/retry`, `/undo` |
| 压缩上下文 / 查看用量 | `/compress`, `/usage`, `/insights [--days N]` | `/compress`, `/usage`, `/insights [days]` |
| 浏览技能 | `/skills` 或 `/<skill-name>` | `/<skill-name>` |
| 打断当前工作 | `Ctrl+C` 或直接发新消息 | `/stop` 或直接发新消息 |
| 平台侧状态 | `/platforms` | `/status`, `/sethome` |

完整命令列表见 [CLI 指南](https://chemany.github.io/Mente/docs/user-guide/cli) 和 [消息网关指南](https://chemany.github.io/Mente/docs/user-guide/messaging)。

---

## 文档导航

所有文档都在 **[chemany.github.io/Mente/docs](https://chemany.github.io/Mente/docs/)**：

| 板块 | 内容 |
|---------|---------------|
| [Quickstart](https://chemany.github.io/Mente/docs/getting-started/quickstart) | 2 分钟完成安装、配置和第一次对话 |
| [CLI Usage](https://chemany.github.io/Mente/docs/user-guide/cli) | 命令、快捷键、人格、会话 |
| [Configuration](https://chemany.github.io/Mente/docs/user-guide/configuration) | 配置文件、provider、模型与全部选项 |
| [Messaging Gateway](https://chemany.github.io/Mente/docs/user-guide/messaging) | Telegram、Discord、Slack、WhatsApp、Signal、Home Assistant |
| [Security](https://chemany.github.io/Mente/docs/user-guide/security) | 命令审批、私聊绑定、容器隔离 |
| [Tools & Toolsets](https://chemany.github.io/Mente/docs/user-guide/features/tools) | 40+ 工具、toolset 系统、终端后端 |
| [Skills System](https://chemany.github.io/Mente/docs/user-guide/features/skills) | 程序化记忆、Skills Hub、技能创建 |
| [Memory](https://chemany.github.io/Mente/docs/user-guide/features/memory) | 持久记忆、用户画像、最佳实践 |
| [MCP Integration](https://chemany.github.io/Mente/docs/user-guide/features/mcp) | 连接任意 MCP server 扩展能力 |
| [Cron Scheduling](https://chemany.github.io/Mente/docs/user-guide/features/cron) | 支持跨平台投递的定时任务 |
| [Context Files](https://chemany.github.io/Mente/docs/user-guide/features/context-files) | 影响每次对话的项目上下文 |
| [Architecture](https://chemany.github.io/Mente/docs/developer-guide/architecture) | 项目结构、agent loop、关键类 |
| [Contributing](https://chemany.github.io/Mente/docs/developer-guide/contributing) | 开发环境、PR 流程、代码风格 |
| [CLI Reference](https://chemany.github.io/Mente/docs/reference/cli-commands) | 全量命令与参数说明 |
| [Environment Variables](https://chemany.github.io/Mente/docs/reference/environment-variables) | 完整环境变量参考 |

---

## 从 OpenClaw 迁移

如果你来自 OpenClaw，Mente 可以自动导入你的配置、记忆、技能和 API key。

**第一次 setup 时：** `mente setup` 会自动检测 `~/.openclaw`，并在正式配置前询问是否迁移。

**任意时间手动迁移：**

```bash
mente claw migrate              # 交互式迁移（完整预设）
mente claw migrate --dry-run    # 先预览会迁移什么
mente claw migrate --preset user-data   # 不迁移 secrets
mente claw migrate --overwrite  # 覆盖已有冲突项
```

会导入的内容包括：

- **SOUL.md**：人格文件
- **Memories**：MEMORY.md 与 USER.md 记录
- **Skills**：用户自建技能，导入到 `~/.hermes/skills/openclaw-imports/`
- **命令白名单**：审批模式和允许规则
- **消息平台配置**：平台设置、允许用户、工作目录
- **API keys**：允许迁移的 secrets（Telegram、OpenRouter、OpenAI、Anthropic、ElevenLabs）
- **TTS 资源**：工作区音频文件
- **工作区指令**：AGENTS.md（支持 `--workspace-target`）

更多参数见 `mente claw migrate --help`，或者直接使用 `openclaw-migration` skill，让 agent 以带 dry-run 预览的方式引导你完成迁移。

---

## 贡献

欢迎贡献。开发环境、代码风格和 PR 流程请看 [Contributing Guide](https://chemany.github.io/Mente/docs/developer-guide/contributing)。

贡献者的快速开始路径如下，克隆后直接跑 `setup-hermes.sh`：

```bash
git clone https://github.com/chemany/Mente.git
cd Mente
./setup-hermes.sh     # 安装 uv、创建 venv、安装 .[all]、把 ~/.local/bin/mente 软链好
./mente               # 会自动识别 venv，不需要先 source
```

手动安装路径如下，效果等同：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv venv --python 3.11
source venv/bin/activate
uv pip install -e ".[all,dev]"
scripts/run_tests.sh
```

> **RL Training（可选）：** `environments/` 下的 RL / Atropos 集成会通过 `.[all,dev]` 自动拉入 `atroposlib` 和 `tinker`，不需要额外处理 submodule。

---

## 社区

- 💬 [Discord](https://discord.gg/NousResearch)
- 📚 [Skills Hub](https://agentskills.io)
- 🐛 [Issues](https://github.com/chemany/Mente/issues)
- 🔌 [HermesClaw](https://github.com/AaronWong1999/hermesclaw) — 社区维护的微信桥接工具，可让 Mente 和 OpenClaw 共用同一个微信账号。

---

## 许可证

MIT，见 [LICENSE](LICENSE)。

为 Mente 项目而构建。
