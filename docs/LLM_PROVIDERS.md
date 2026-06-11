# LLM 提供商配置指南 / LLM Providers Configuration

本项目通过 `LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL` 三个环境变量对接任意 **OpenAI 兼容 API**，也原生支持 **Anthropic Messages API**（当 `LLM_BASE_URL` 含 `anthropic` 字样时自动切换）。

换一个提供商只需改这三个变量，其余功能（流式输出、记忆提取、摘要、图像、音频）无需修改。

---

## 目录

1. [OpenAI](#1-openai)
2. [Anthropic Claude（原生 API）](#2-anthropic-claude-原生-api)
3. [Ollama 本地运行](#3-ollama-本地运行)
4. [Groq（超快速推理）](#4-groq-超快速推理)
5. [DeepSeek（中文优化）](#5-deepseek-中文优化)
6. [SiliconFlow（国内快速访问）](#6-siliconflow-国内快速访问)
7. [自定义 OpenAI 兼容端点](#7-自定义-openai-兼容端点)
8. [多模型分工配置](#8-多模型分工配置)
9. [提示缓存配置](#9-提示缓存配置)
10. [常见问题排查](#10-常见问题排查)

---

## 1. OpenAI

官网：<https://platform.openai.com>

```env
LLM_API_KEY=sk-<your-openai-api-key>
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1

# 可选：快速回复用小模型，节省费用
LLM_REPLY_MODEL_FAST=gpt-4.1-mini

# 可选：联网搜索（需 Responses API）
LLM_NATIVE_SEARCH_ENABLED=true
LLM_NATIVE_SEARCH_TOOL_TYPE=web_search_preview
```

**常用模型参考：**

| 模型 ID | 定位 | 上下文 |
|---------|------|--------|
| `gpt-4.1` | 旗舰，综合最强 | 1M tokens |
| `gpt-4.1-mini` | 快速 / 低成本 | 1M tokens |
| `gpt-4.1-nano` | 极速提取任务 | 1M tokens |
| `o1` | 深度推理 | 200k tokens |
| `o3` | 最强推理 | 200k tokens |
| `o4-mini` | 推理 + 低成本 | 200k tokens |

> **推理模型（o 系列）** 不支持 `temperature`，`reasoning_effort` 可设为 `low` / `medium` / `high`。
> 项目会在后端自动重试去掉不支持的字段，无需手动处理。

---

## 2. Anthropic Claude（原生 API）

官网：<https://console.anthropic.com>

当 `LLM_BASE_URL` 包含 `anthropic`，客户端自动切换到 **Anthropic Messages API**，使用 `x-api-key` 鉴权并启用提示缓存。

```env
LLM_API_KEY=sk-ant-<your-anthropic-api-key>
LLM_BASE_URL=https://api.anthropic.com
LLM_MODEL=claude-opus-4-5

# 提示缓存（Anthropic 原生支持，可显著降低 token 消耗）
LLM_PROMPT_CACHING_ENABLED=true
```

**常用模型参考：**

| 模型 ID | 定位 |
|---------|------|
| `claude-opus-4-5` | 旗舰，最强理解力 |
| `claude-sonnet-4-5` | 均衡，速度 / 质量最佳比 |
| `claude-haiku-4-5` | 最快 / 最低成本 |

> **注意：** 原生 Anthropic API 不支持联网搜索工具（`/responses` 端点），请将 `LLM_NATIVE_SEARCH_ENABLED=false`。

---

## 3. Ollama 本地运行

官网：<https://ollama.com>

适合离线使用、隐私敏感场景或低成本实验。

**第一步：安装并拉取模型**

```bash
# 安装 Ollama（macOS）
brew install ollama

# 拉取模型
ollama pull llama3.1:8b
ollama pull qwen2.5:7b
ollama pull deepseek-r1:7b

# 启动服务
ollama serve
```

**第二步：配置 .env**

```env
LLM_API_KEY=ollama
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2.5:7b

# 本地模型推理较慢，适当调大超时
LLM_TIMEOUT_SECONDS=120

# 本地模型不支持联网搜索
LLM_NATIVE_SEARCH_ENABLED=false

# 本地模型通常不支持 JSON response_format，项目会自动重试
```

**推荐本地模型：**

| 模型 | 适用场景 | VRAM 需求 |
|------|----------|-----------|
| `qwen2.5:7b` | 中文对话，效果好 | ~6 GB |
| `qwen2.5:14b` | 中文对话，更强 | ~10 GB |
| `llama3.1:8b` | 英文对话，通用 | ~6 GB |
| `deepseek-r1:7b` | 推理任务 | ~6 GB |
| `deepseek-r1:14b` | 推理任务，更强 | ~10 GB |

---

## 4. Groq（超快速推理）

官网：<https://console.groq.com>

Groq 使用专用 LPU 芯片，推理速度极快（通常 200+ tokens/s），免费额度较大。

```env
LLM_API_KEY=gsk_<your-groq-api-key>
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.3-70b-versatile

# 可配快速模型处理提取任务
LLM_EXTRACTION_MODEL=llama-3.1-8b-instant
LLM_SUMMARY_MODEL=llama-3.1-8b-instant

# Groq 不支持联网搜索
LLM_NATIVE_SEARCH_ENABLED=false
```

**常用模型参考：**

| 模型 ID | 特点 |
|---------|------|
| `llama-3.3-70b-versatile` | 综合最强 |
| `llama-3.1-8b-instant` | 极速，适合提取 |
| `mixtral-8x7b-32768` | 长上下文 |
| `gemma2-9b-it` | Google 出品 |

> Groq 有**速率限制**（RPM/TPM），高并发场景请关注错误日志。

---

## 5. DeepSeek（中文优化）

官网：<https://platform.deepseek.com>

DeepSeek 对中文对话效果很好，价格极低（主力模型约 ¥1/1M tokens）。

```env
LLM_API_KEY=sk-<your-deepseek-api-key>
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# 推理模型（适合需要深度思考的场景）
# LLM_MODEL=deepseek-reasoner
```

**常用模型参考：**

| 模型 ID | 定位 |
|---------|------|
| `deepseek-chat` | 通用对话，支持函数调用 |
| `deepseek-reasoner` | 深度推理（R1），内置思维链 |

> `deepseek-reasoner` 对应 R1，不支持 `temperature`；项目会自动降级重试。

---

## 6. SiliconFlow（国内快速访问）

官网：<https://siliconflow.cn>

国内节点，延迟低，支持多个开源模型，有免费额度。

```env
LLM_API_KEY=sk-<your-siliconflow-api-key>
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=Qwen/Qwen2.5-72B-Instruct

# 可用更小的模型做提取 / 摘要
LLM_EXTRACTION_MODEL=Qwen/Qwen2.5-7B-Instruct
LLM_SUMMARY_MODEL=Qwen/Qwen2.5-7B-Instruct

# SiliconFlow 不支持联网搜索
LLM_NATIVE_SEARCH_ENABLED=false
```

**常用模型参考：**

| 模型 ID | 定位 |
|---------|------|
| `Qwen/Qwen2.5-72B-Instruct` | 中文旗舰 |
| `Qwen/Qwen2.5-7B-Instruct` | 中文快速 |
| `deepseek-ai/DeepSeek-V3` | 深度求索旗舰 |
| `deepseek-ai/DeepSeek-R1` | 深度推理 |
| `meta-llama/Meta-Llama-3.1-70B-Instruct` | 英文通用 |

---

## 7. 自定义 OpenAI 兼容端点

任何实现了 `/v1/chat/completions` 的服务都可以接入，例如：
- LM Studio（本地 GUI）
- vLLM（生产级推理服务）
- LocalAI
- Azure OpenAI

```env
LLM_API_KEY=<your-api-key-or-any-string>
LLM_BASE_URL=http://localhost:1234/v1     # 替换为实际地址
LLM_MODEL=<model-name-as-listed-by-server>
LLM_TIMEOUT_SECONDS=120
LLM_NATIVE_SEARCH_ENABLED=false
```

**Azure OpenAI 示例：**

```env
LLM_API_KEY=<your-azure-api-key>
LLM_BASE_URL=https://<your-resource>.openai.azure.com/openai/deployments/<deployment-id>
LLM_MODEL=<deployment-name>
```

---

## 8. 多模型分工配置

项目支持为不同任务指定不同模型，在质量和成本之间取得平衡。

```env
# ── 主模型（默认后备）──────────────────────
LLM_MODEL=gpt-4.1

# ── 回复模型分工 ───────────────────────────
# 普通快速回复
LLM_REPLY_MODEL_FAST=gpt-4.1-mini

# 深度思考回复（如用户要求推理）
LLM_REPLY_MODEL_THINKING=o4-mini
LLM_REPLY_REASONING_EFFORT=medium      # low / medium / high

# 切换模式：fast（默认）或 thinking
LLM_REPLY_MODEL_MODE=fast

# ── 后台任务模型 ───────────────────────────
# 记忆提取、结构化事实解析
LLM_EXTRACTION_MODEL=gpt-4.1-mini

# 对话摘要生成
LLM_SUMMARY_MODEL=gpt-4.1-mini

# 主模型失败时的备用
LLM_BACKUP_MODEL=gpt-4.1-mini

# 联网搜索场景
LLM_SEARCH_MODEL=gpt-4.1

# ── 多模态模型 ─────────────────────────────
# 图像理解
LLM_VISION_MODEL=gpt-4.1-mini

# 语音转文字（Whisper 兼容）
LLM_AUDIO_MODEL=whisper-1

# 图像生成
LLM_IMAGE_MODEL=gpt-image-1
LLM_IMAGE_SIZE=1024x1024
```

**模型优先级说明：**

- 各 `*_MODEL` 变量未设置时，自动回退到 `LLM_MODEL`
- 备用链：`LLM_BACKUP_MODEL` → `LLM_REPLY_MODEL_FAST` → `LLM_MODEL`

---

## 9. 提示缓存配置

```env
# 是否启用提示缓存（默认：true）
LLM_PROMPT_CACHING_ENABLED=true
```

**各提供商支持情况：**

| 提供商 | 缓存支持 | 说明 |
|--------|----------|------|
| Anthropic | 原生支持 | 系统提示静态部分自动打上 `cache_control` |
| OpenAI | 自动缓存 | 平台侧透明缓存，无需额外配置 |
| Groq / Ollama / 其他 | 不支持 | 设为 `false` 可避免无效请求头 |

---

## 10. 常见问题排查

### 超时（Timeout）

```
LLMClientError: LLM request failed [...]
httpx.ReadTimeout
```

**解决方案：**

```env
# 默认 60 秒，本地模型或慢速 API 需要调大
LLM_TIMEOUT_SECONDS=120
```

---

### 速率限制（Rate Limit）

```
LLM request failed [429]: Too Many Requests
```

**解决方案：**

- 降低 `PROACTIVE_SCAN_MINUTES` 减少后台轮询频率
- 升级提供商套餐或切换到限制更宽松的端点
- Groq 免费层 RPM 较低，高频使用建议切换付费

---

### 模型名称错误

```
LLM request failed [404]: model not found
```

**排查步骤：**

```bash
# 查询当前端点支持的模型列表
curl -H "Authorization: Bearer $LLM_API_KEY" \
     "$LLM_BASE_URL/models" | python3 -m json.tool | grep '"id"'
```

确认 `LLM_MODEL` 的值与列表中的 `id` 完全一致（区分大小写）。

---

### JSON response_format 不支持

部分本地模型不支持 `response_format: {"type": "json_object"}`。项目会自动重试去掉该字段，无需手动处理。如果日志中频繁出现此警告，可以忽略，不影响功能。

---

### Anthropic API 联网搜索报错

```
Native search requires an OpenAI Responses-compatible backend
```

Anthropic 原生 API 不支持 `/responses` 端点，请禁用联网搜索：

```env
LLM_NATIVE_SEARCH_ENABLED=false
```
