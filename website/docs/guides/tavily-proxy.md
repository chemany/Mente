---
sidebar_position: 10
title: "Tavily 代理服务"
description: "部署和使用本地 Tavily 多 key 代理，为技能提供稳定的搜索 API"
---

# Tavily 代理服务

## 概述

Tavily Proxy 是一个本地部署的多 key 代理服务，对外暴露统一的 `POST /search` 接口，内部负责：

- 多个 Tavily key 轮询
- 遇到限流、额度耗尽、`5xx` 或网络异常时自动切换到下一个 key
- 统一 Bearer 鉴权
- 保持与 Tavily 原生 `/search` 请求体兼容

## 部署位置

```bash
~/tavily-proxy/
```

## 快速启动

```bash
cd ~/tavily-proxy
./run.sh
```

默认监听 `127.0.0.1:18080`。

## 配置

编辑 `~/tavily-proxy/.env`：

```bash
TAVILY_KEY_1_LABEL='account-a'
TAVILY_KEY_1='tvly-dev-xxx'

TAVILY_KEY_2_LABEL='account-b'
TAVILY_KEY_2='tvly-dev-yyy'

PROXY_BEARER_TOKEN='your-strong-token'
TAVILY_TIMEOUT_SECONDS='15'
HOST='0.0.0.0'    # 局域网访问用 0.0.0.0
PORT='18080'
```

## 供 Mente 技能使用

在 `~/.mente/.env` 中配置：

```bash
TAVILY_API_KEY=<PROXY_BEARER_TOKEN>
TAVILY_API_URL=http://<host>:18080/search
```

支持 `TAVILY_API_URL` 的技能会自动使用代理而非直连 Tavily 官方 API。

## 验证

```bash
# 健康检查
curl http://127.0.0.1:18080/healthz

# 搜索测试
curl -X POST http://127.0.0.1:18080/search \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer your-proxy-token' \
  -d '{"query": "test", "search_depth": "basic"}'
```
