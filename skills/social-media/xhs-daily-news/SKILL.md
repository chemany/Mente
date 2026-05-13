---
name: xhs-daily-news
description: "Use when you want to turn daily global headlines into Xiaohongshu-ready assets and optionally publish them with rednote."
version: 1.0.0
author: openclaw + Hermes + Mente
license: MIT
platforms: [linux, macos]
prerequisites:
  commands: [python3]
metadata:
  hermes:
    tags: [xiaohongshu, rednote, social-media, news, workflow]
    related_skills: [wechat-publisher]
---

# 小红书每日新闻自动发布

## Overview

这个技能把“每日国际要闻”整理成一套可发布的小红书素材：
1. Tavily 抓取新闻并生成摘要 Markdown。
2. 输出纵版 / 横版封面图。
3. 转换成小红书风格文案。
4. 渲染成多张图片卡片。
5. 调用 `rednote` 做 dry-run 或实际发布。

它已经从 Hermes 风格路径改成了 Mente 兼容运行方式，不再依赖硬编码的 `~/.hermes` 或 `/home/jason/clawd/daily-news`。

## When to Use

- 需要把每日新闻批量整理成小红书图文素材。
- 需要完整的“抓取 -> 配图 -> 卡片 -> 发布”流水线。
- 你已经有 `TAVILY_API_KEY`，并准备好本机 `rednote` 登录状态。

不要用于：
- 只需要纯文本新闻摘要。
- 没有 `playwright` / `markdown` / `pyyaml` / `Pillow` 依赖时的即时发布。

## Runtime Paths

先定义运行时变量：

```bash
AGENT_HOME="${HERMES_HOME:-${MENTE_HOME:-$HOME/.mente}}"
SKILL_DIR="${XHS_DAILY_NEWS_SKILL_DIR:-$AGENT_HOME/skills/social-media/xhs-daily-news}"
NEWS_DIR="${XHS_DAILY_NEWS_DIR:-$AGENT_HOME/xhs-daily-news}"
```

如果你是在 Mente 仓库里直接调试，而不是从已安装技能目录执行，把 `SKILL_DIR` 改成仓库里的 `skills/social-media/xhs-daily-news` 绝对路径。

脚本默认行为：
- `TAVILY_API_KEY` 优先从环境变量读取。
- 如果环境变量没有，再回退到 `${AGENT_HOME}/.env`。
- 如果没有传 `--output-dir`，则默认用 `${NEWS_DIR}`。

## Workflow

### 1. 生成每日新闻

```bash
python3 "$SKILL_DIR/scripts/generate_daily_news.py" \
  --date 2026-05-11 \
  --output-dir "$NEWS_DIR"
```

输出：`$NEWS_DIR/daily-briefing-2026-05-11.md`

### 2. 生成封面图

```bash
python3 "$SKILL_DIR/scripts/generate_news_image.py" \
  --input "$NEWS_DIR/daily-briefing-2026-05-11.md" \
  --output-dir "$NEWS_DIR" \
  --layout both
```

输出：
- `$NEWS_DIR/daily-briefing-20260511_portrait.png`
- `$NEWS_DIR/daily-briefing-20260511_landscape.png`

### 3. 转换为小红书文案

```bash
python3 "$SKILL_DIR/scripts/convert_to_xhs.py" \
  --input "$NEWS_DIR/daily-briefing-2026-05-11.md" \
  --output "$NEWS_DIR/xhs_daily_2026-05-11.md"
```

### 4. 渲染卡片

```bash
python3 "$SKILL_DIR/scripts/render_xhs_cards.py" \
  "$NEWS_DIR/xhs_daily_2026-05-11.md" \
  --output-dir "$NEWS_DIR/xhs_output_2026-05-11" \
  --style xiaohongshu
```

### 5. 发布到小红书

先做 dry-run：

```bash
python3 "$SKILL_DIR/scripts/publish_to_xhs.py" \
  --date 2026-05-11 \
  --output-dir "$NEWS_DIR" \
  --instance seller-main \
  --dry-run
```

确认素材和登录状态没问题后，再去掉 `--dry-run`。

## One-Shot Recipe

```bash
python3 "$SKILL_DIR/scripts/run_full_workflow.py" \
  --date 2026-05-11 \
  --output-dir "$NEWS_DIR" \
  --dry-run
```

这个入口会依次执行：
1. 新闻抓取
2. 封面图生成
3. 小红书文案转换
4. 卡片渲染
5. 发布命令预演或正式发布

## Common Pitfalls

1. `TAVILY_API_KEY` 还只配在旧的 `~/.hermes/.env`。迁移后默认读 `${AGENT_HOME}/.env`，或者直接导出环境变量。
2. 只迁移了 `SKILL.md`，没同步 `scripts/` 和 `assets/`。这个技能依赖完整目录。
3. 只安装了 `playwright` Python 包，但没执行 `playwright install chromium`。
4. 改了输出目录，却忘了给 `publish_to_xhs.py` 和 `run_full_workflow.py` 传同一个 `--output-dir`。
5. `rednote` 没登录时，发布步骤会失败；先用 `--dry-run` 验证素材。

## Verification Checklist

- [ ] `python3 "$SKILL_DIR/scripts/generate_daily_news.py" --help` 正常输出帮助。
- [ ] `python3 "$SKILL_DIR/scripts/publish_to_xhs.py" --help` 出现 `--output-dir`。
- [ ] `python3 "$SKILL_DIR/scripts/run_full_workflow.py" --help` 出现 `--output-dir`。
- [ ] `${AGENT_HOME}/.env` 或当前环境中已配置 `TAVILY_API_KEY`。
- [ ] `playwright install chromium` 已执行。
- [ ] `rednote status --instance <name>` 与 `rednote check-login --instance <name>` 已通过，再做正式发布。
