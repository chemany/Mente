---
title: Mente 正式上 GitHub：一个真正能写代码、会记忆、还能跨平台执行的 AI Agent
cover: ./cover.jpg
summary: Mente 最近完成了一轮集中优化，并正式发布到 GitHub。它不是“再做一个聊天框”，而是把编码、自动化、消息网关、长期记忆和云端执行整合成一套真正能长期交付的统一 Agent。
tags: Mente, AI Agent, GitHub, 自动化, 长期记忆
---

# Mente 正式上 GitHub：一个真正能写代码、会记忆、还能跨平台执行的 AI Agent

很多 AI 产品第一次看很惊艳，但一落到真实工作里就会暴露问题。

它也许能回答问题，却接不住任务；也许能写几行代码，却不能持续执行；也许在一个窗口里看起来很强，一换平台、一换会话，它就像“失忆”了一样。

这也是我们最近集中优化 Mente 的原因。

现在，**Mente 已经正式发布到 GitHub**。这次我们不是简单做了一层包装，而是把一个真正能工作的 Agent 产品面，重新梳理得更清楚、更完整，也更适合公开交付给外部用户。

![Mente 横幅](./banner.jpg)

## 我们不是在做“又一个聊天框”

Mente 的目标从一开始就不是只陪你对话，而是**替你完成工作**。

它能写代码，能调工具，能跨平台继续上下文，能在本地和云端环境里持续执行，也能把值得保留的经验沉淀成长期记忆和技能。你可以把它理解成一个统一的 AI Agent 入口，而不是一个只能临时回答问题的模型壳。

这次发布到 GitHub 的版本，重点也不在“更会说”，而在“更能交付”。

## 这轮优化，核心做对了什么

### 1. 对外产品面彻底统一

CLI、消息平台、执行进度、用户可见回复，现在统一都以 **Mente** 的身份呈现。

这听起来像是品牌层面的事情，但对真实用户非常重要。以前很多 agent 产品的问题，不是能力不够，而是入口太碎、表述太乱，用户根本分不清自己面对的是不是同一个系统。现在这层已经收口了。

### 2. 外层更清楚，底层执行能力没有缩水

这次统一对外展示，并不意味着能力变轻。复杂编码、工具调用和执行流程，仍然由 **Codex-backed executor** 提供支撑。

简单说就是：**外面看起来更像一个完整产品，里面仍然是硬执行能力。**

### 3. 执行过程重新变得可见

很多 agent 不是不会做，而是用户看不见它在做什么。

Mente 现在会把对外步骤整理成更容易理解的 Mente 进度，同时保留底层命令和工具活动明细。对于实际落地来说，这一点非常关键，因为它决定了你能不能信任系统，也决定了出问题时能不能快速定位。

### 4. 安装和公开使用路径更明确

如果你是第一次从 GitHub 接触 Mente，现在最直接的安装方式已经很清楚：

```bash
curl -fsSL https://raw.githubusercontent.com/chemany/Mente/main/scripts/install.sh | bash
```

npm 的公开路径也已经准备好，后续发布后会切到：

```bash
npm install -g mente-agent
mente
```

这意味着 GitHub 访客不需要先理解大量内部背景，就能把 Mente 拉起来试用。

![Mente 特点概览](./images/features-overview.jpg)

## 为什么说 Mente 的特点，不只是“模型更强一点”

真正拉开差距的，不是它单轮回答有多漂亮，而是它能不能组成一条可持续工作的链路。

### 统一入口，覆盖整条工作流

Mente 不是只擅长某一个点。它把编码、自动化、消息网关、记忆、技能和调度放在了同一个系统里。你不需要在多个工具之间来回拼接上下文。

### 会记住值得记住的东西

复杂任务结束后，Mente 不只是“做完就忘”。它可以沉淀长期记忆，也可以把反复出现的经验整理成技能，在后续使用中继续优化。

这件事的价值在于：你不是每次都从零开始教它做同一件事。

### 不被绑在你的笔记本上

Mente 可以跑在本地，也能跑在 Docker、SSH、Daytona、Singularity、Modal 这些后端上。你可以把它放到一台便宜的 VPS，也可以放到近似 serverless 的环境里，空闲休眠，需要时唤醒。

它更像一个常驻在线的 worker，而不是“只有你电脑开着它才存在”的助手。

### 多平台连续工作，而不是换个入口就断掉

CLI、Telegram、Discord、Slack、WhatsApp、Signal 等入口可以共用同一个网关进程。你在不同平台上，不是在跟不同机器人重新开始，而是在和同一个 Mente 连续协作。

### 模型和推理服务不被锁定

OpenAI、OpenRouter、Nous Portal、NVIDIA NIM、GLM、Kimi、MiniMax、Hugging Face，或者你自己的兼容端点，都可以接进来。通过 `mente model` 就能切换，不需要改代码。

### 不只是帮你回答，而是帮你持续运行

Mente 内置 cron 调度、子代理并行、RPC 工具调用和跨平台投递能力。日报、备份、审计、内容整理、定时推送，这些事情都可以逐步从“问一次”变成“长期自动运行”。

![Mente 工作流示意](./images/workflow-map.jpg)

## 为什么我们选择现在上 GitHub

因为 Mente 已经不只是内部可用的一套工具堆栈，而是一个对外部用户也有明确价值的产品面。

它现在已经具备了几个关键条件：

- 有统一的产品身份
- 有足够硬的底层执行能力
- 有清晰的安装路径
- 有长期记忆和技能系统
- 有消息网关和多环境执行能力
- 有可以直接上手的文档与公开仓库

当这些链路被打通之后，GitHub 就不再只是代码托管平台，而是让更多人真正跑起来、判断它值不值得长期使用的入口。

## 如果你第一次认识 Mente，最短上手路径是这样的

1. 打开 GitHub 仓库：<https://github.com/chemany/Mente>
2. 用安装脚本把 Mente 跑起来
3. 执行 `mente`
4. 用 `mente model` 选择 provider 和模型
5. 再用 `mente tools`、`mente gateway`、`mente setup` 把你自己的工作流接进去

几个最常用的命令如下：

```bash
mente
mente model
mente tools
mente gateway
mente setup
mente doctor
```

完整文档可以从这里进入：<https://chemany.github.io/Mente/docs/>

## 最后想说

我们这次做的，不是把几个 AI 能力堆在一起，而是把它们整理成一个**真正能长期工作、能跨平台交付、能不断积累经验的统一 Agent**。

如果你也在找一个不是“只能聊天”，而是能持续替你做事的 AI Agent，Mente 现在已经到了值得你亲自试一遍的时候。

GitHub 仓库：<https://github.com/chemany/Mente>  
文档入口：<https://chemany.github.io/Mente/docs/>  
当前推荐安装方式：`curl -fsSL https://raw.githubusercontent.com/chemany/Mente/main/scripts/install.sh | bash`

*发布日期：2026-05-09*
