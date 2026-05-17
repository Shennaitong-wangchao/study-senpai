# 沈知微长期陪伴系统使用手册 / User Guide

## 中文优先

这份说明按“你一个人长期使用”的真实场景来写。

重点不是把她当作普通问答机器人跑起来，而是把下面这些能力一起跑顺：

- 私聊长期聊天
- 稳定人格与不同场景切换
- 长期记忆、候选记忆、摘要连续性
- 图片 / 语音 / 文档输入
- 学习模式
- 搜索型回复
- 绘图型回复
- 主动消息
- Dashboard 观察、记忆审核、任务和错误排查

如果你只想知道最短启动路径，可以直接先看：

- 第 2 节：环境变量
- 第 3 节：安装与启动
- 第 5 节：聊天内可用命令
- 第 10 节：如何验证功能真的存在

文档分工也建议一起记住：

- `README.md` 只保留最短入口和脚本索引
- 这份 `USER_GUIDE.md` 放启动、配置、聊天与 Dashboard 使用细节
- `docs/OPERATIONS_RUNBOOK.md` 专门放 log rotation、DB vacuum、备份恢复、容量治理和巡检

---

## 1. 先知道这套系统现在怎么工作

当前版本的正式入口是：

- Discord 私聊 DM

当前版本不是群聊 bot，也不是多用户运营平台。

默认工作方式是：

1. 你在 Discord 私聊她
2. 她写入原始消息
3. 拉取近期上下文、长期记忆、关系状态、摘要
4. 判断这一轮属于什么场景、该怎么回
5. 按普通聊天 / 搜索型回复 / 绘图型回复其中一种方式处理
6. 流式发出回复
7. 后台异步做记忆提取、摘要更新、任务记录、体验指标记录
8. Dashboard 上同步能看到最近一轮过程和系统状态

你可以把她理解成：

- 前台是一个长期陪伴聊天对象
- 后台是一套持续运转的记忆和运维系统

---

## 2. 环境变量怎么填

项目配置文件是根目录的 `.env`。

如果还没有：

```bash
cp .env.example .env
```

### 2.1 最低必填

这三个不填就跑不起来：

```env
DISCORD_BOT_TOKEN=你的 Discord Bot Token
LLM_API_KEY=你的模型 API Key
LLM_MODEL=你的默认模型
```

### 2.2 推荐的最小可用配置

如果你想尽快跑起来，建议先用这一套：

```env
DISCORD_BOT_TOKEN=你的 Discord Bot Token
DISCORD_APPLICATION_ID=你的 Discord Application ID

LLM_API_KEY=你的模型 API Key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini
LLM_REPLY_MODEL_FAST=
LLM_REPLY_MODEL_THINKING=
LLM_REPLY_MODEL_MODE=fast
LLM_REPLY_REASONING_EFFORT=
LLM_EXTRACTION_MODEL=
LLM_SUMMARY_MODEL=
LLM_BACKUP_MODEL=
LLM_SEARCH_MODEL=
LLM_NATIVE_SEARCH_ENABLED=true
LLM_NATIVE_SEARCH_TOOL_TYPE=web_search_preview
LLM_VISION_MODEL=
LLM_AUDIO_MODEL=whisper-1
LLM_IMAGE_MODEL=gpt-image-1
LLM_IMAGE_SIZE=1024x1024
LLM_TIMEOUT_SECONDS=60

DATABASE_PATH=data/shen_zhiwei.sqlite3
LOG_LEVEL=INFO
LOG_FILE_PATH=logs/shen_zhiwei.log

DEBUG_PROMPTS=false
SINGLE_USER_MODE=false
SINGLE_USER_ID=primary_user
BOT_TIMEZONE=Asia/Shanghai

DASHBOARD_ENABLED=true
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8099
DASHBOARD_SESSION_HTTPS_ONLY=false
DASHBOARD_PASSWORD_MIN_LENGTH=12

RUN_DISCORD_BOT=true
RUN_BACKGROUND_WORKER=true

BACKGROUND_POLL_SECONDS=2
BACKGROUND_TASK_TIMEOUT_SECONDS=180
BACKGROUND_TASK_MAX_ATTEMPTS=3
HEALTHCHECK_INTERVAL_MINUTES=20
HEALTHCHECK_DEEP_INTERVAL_HOURS=12

ENABLE_PROACTIVE_MESSAGES=true
PROACTIVE_OPT_IN_REQUIRED=false
PROACTIVE_IDLE_HOURS=18
PROACTIVE_SCAN_MINUTES=20
PROACTIVE_RESPONSE_WINDOW_HOURS=8
PROACTIVE_MIN_IDLE_MINUTES=12
PROACTIVE_MIN_INTERVAL_MINUTES=25
PROACTIVE_TRIGGER_DEDUPE_HOURS=6
PROACTIVE_FAILURE_BACKOFF_MINUTES=30

ATTACHMENT_TEXT_CHAR_LIMIT=2200
ATTACHMENT_TOTAL_CHAR_LIMIT=4200
STREAMING_FLUSH_CHARS=72
STREAMING_MAX_SILENCE_MS=2200
SEARCH_TIMEOUT_SECONDS=8
SEARCH_MAX_RESULTS=5
```

### 2.3 这些字段分别管什么

#### Discord 相关

- `DISCORD_BOT_TOKEN`
  机器人登录凭据。
- `DISCORD_APPLICATION_ID`
  应用 id，主要用于 Discord 应用侧配置和你后面排查。

#### 回复模型相关

- `LLM_MODEL`
  默认模型。没特别切换时会走它。
- `LLM_REPLY_MODEL_FAST`
  快速模式优先模型。
- `LLM_REPLY_MODEL_THINKING`
  深度模式优先模型。
- `LLM_REPLY_MODEL_MODE`
  默认初始模式，用 `fast` 或 `thinking`。
- `LLM_REPLY_REASONING_EFFORT`
  深度模型的推理强度，如果你的接口支持可以填。
- `LLM_BACKUP_MODEL`
  主模型出问题时的备用模型。
- `LLM_SEARCH_MODEL`
  预留给后续搜索模型切换使用；当前默认搜索链路不依赖它。

#### 搜索相关

- `LLM_NATIVE_SEARCH_ENABLED`
  当前保留为兼容字段；现版本搜索型回复默认走内置 DuckDuckGo HTML 检索。
- `LLM_NATIVE_SEARCH_TOOL_TYPE`
  当前也是兼容保留字段，后续如果接回模型原生联网能力再启用。

#### 多模态相关

- `LLM_VISION_MODEL`
  看图模型。
- `LLM_AUDIO_MODEL`
  语音转文字模型。
- `LLM_IMAGE_MODEL`
  绘图模型。
- `LLM_IMAGE_SIZE`
  生成图片尺寸。

#### 记忆与系统相关

- `DATABASE_PATH`
  SQLite 数据库路径。
- `SINGLE_USER_MODE`
  是否使用单用户模式。
  默认是 `false`。只有你明确想把多会话合并进同一个主用户槽时才建议开启。
- `SINGLE_USER_ID`
  单用户槽位 id。
- `BOT_TIMEZONE`
  回复时注入给模型的本地时区，默认 `Asia/Shanghai`。如果你希望她正确理解“现在几点”“今天/明天/昨晚”这类时间表达，建议按你的实际使用时区设置。

#### Dashboard 与后台任务

- `DASHBOARD_ENABLED`
  是否开启管理面板。
- `DASHBOARD_HOST`
  面板监听地址。`127.0.0.1` 只允许服务器本机访问；如果你要从外部浏览器访问，要改成 `0.0.0.0`，并额外做好防火墙或反向代理鉴权。
- `DASHBOARD_PORT`
  面板端口。
- `DASHBOARD_SESSION_HTTPS_ONLY`
  是否给 Dashboard session cookie 强制 `Secure`。
- `DASHBOARD_PASSWORD_MIN_LENGTH`
  Dashboard 改密最小长度。
- `RUN_DISCORD_BOT`
  是否启动 Discord bot 进程。
- `RUN_BACKGROUND_WORKER`
  是否启动后台任务 worker；做拆分部署时很有用。
- `BACKGROUND_TASK_TIMEOUT_SECONDS`
  单个后台任务超时秒数。
- `BACKGROUND_TASK_MAX_ATTEMPTS`
  失败重试上限。

#### 主动消息

- `ENABLE_PROACTIVE_MESSAGES`
  是否允许系统主动发消息。
- `PROACTIVE_OPT_IN_REQUIRED`
  是否要求用户先发送 `/proactive on` 才开启主动消息。
- `PROACTIVE_IDLE_HOURS`
  多久没聊后，才考虑主动找你。
- `PROACTIVE_SCAN_MINUTES`
  多久扫描一次是否该主动发。
- `PROACTIVE_RESPONSE_WINDOW_HOURS`
  主动发出后，多长时间内算“有效响应窗口”。
- 运行时可用 `/proactive on/off` 和 `/proactive low|normal|high` 调整当前会话；Dashboard 和 iOS 设置页也会写同一份偏好。

#### 附件与流式体验

- `ATTACHMENT_TEXT_CHAR_LIMIT`
  单个附件最多抽多少文字进上下文。
- `ATTACHMENT_TOTAL_CHAR_LIMIT`
  一轮附件合计最多进多少文字。
- `STREAMING_FLUSH_CHARS`
  流式释放阈值。
- `STREAMING_MAX_SILENCE_MS`
  模型一直不换行时，最多静默多久就先释放一段。

### 2.4 关于“搜索型回复”现在怎么配

你刚刚提的要求已经改进去了：

- 搜索型回复已经接入真实外部检索
- 默认走内置 DuckDuckGo HTML 搜索
- Dashboard 的 turn trace / 搜索上下文会保留来源标题和链接摘要

所以推荐做法是：

1. 直接保留默认搜索配置
2. 视情况调整 `SEARCH_TIMEOUT_SECONDS`
3. 视情况调整 `SEARCH_MAX_RESULTS`

例如：

```env
SEARCH_TIMEOUT_SECONDS=8
SEARCH_MAX_RESULTS=5
```

---

## 3. 安装与启动

### 3.1 Python 版本

当前本地已验证在 Python 3.9 环境下能跑通基本装配和 Dashboard API 冒烟。

但如果你准备长期维护，还是建议：

```text
Python 3.11+
```

### 3.2 安装依赖

推荐：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

### 3.3 本地冒烟验证

这一步不会真的登录 Discord，也不会真的调用你的线上模型，只是检查系统装配和 Dashboard API 是否正常：

```bash
python3 scripts/verify_product.py
```

你应该能看到类似：

- `Runtime objects: ...`
- `/api/overview: 200`
- `/api/health: 200`
- `/api/tasks: 200`

### 3.4 正式启动

```bash
python3 -m src.main
```

启动后会同时发生这些事：

- Discord bot 登录
- Dashboard 启动
- 后台任务 worker 启动
- 健康检查任务开始定期跑
- 主动消息扫描任务开始定期跑

### 3.5 Dashboard 地址

默认：

```text
http://127.0.0.1:8099
```

---

## 4. 现在真正支持哪些输入方式

### 4.1 文字聊天

最基础的私聊形式。

例如：

- “我今天一直拖延。”
- “你以后叫我阿微。”
- “我最近最卡的是数学函数。”
- “我现在不想被说教。”

### 4.2 图片

你可以直接发图，不写字也可以。

系统会：

- 识别这是图片输入
- 提炼和当前聊天最相关的图像信息
- 把识别结果当成这一轮上下文
- 再按陪伴式口吻回复

例如：

- 发一道题的截图，让她继续讲
- 发你的日程表截图，让她帮你判断节奏
- 发一张今天状态相关的照片，让她顺着聊

### 4.3 语音

支持把语音先转成文字，再纳入这一轮理解。

适合：

- 你懒得打字时
- 你想更自然地说一长段状态
- 你想让她先把语音内容吃进去再接你

### 4.4 文档

支持：

- `txt`
- `pdf`
- `docx`

系统会：

- 提取文档文字
- 按长度做截断
- 将清洗后的文本放入这一轮上下文

适合：

- 讲义
- 作业题
- 读书笔记
- 项目说明

### 4.5 搜索型请求

例如：

- “帮我查一下最近这个模型还有没有 API 限流问题”
- “搜一下现在 iOS 上这类 app 的主流订阅价位”
- “查一下这题涉及的定理”

现在这类请求会走内置 DuckDuckGo HTML 检索。

它会：

- 先把这一轮判断成搜索型回复
- 抓取外部结果标题、摘要和链接
- 再把结果以“同一个人”的口吻说出来

### 4.6 绘图型请求

例如：

- “给我画一张海边夜景，偏电影感”
- “把这张图的气质改成更安静一点”

系统会：

- 先回一句自然承接
- 再调用绘图模型出图
- 最后把图作为附件发回去

---

## 5. 聊天里可以直接用的控制命令

这些命令都是直接在 Discord 私聊里发。

### 5.1 查看状态

```text
/status
```

会返回：

- 当前模式
- 学习模式是否开启
- 当前主模型
- 当前备用模型
- 最近一小时请求数
- Dashboard 地址

### 5.2 切模式

```text
/model
/model auto
/model fast
/model think
/model custom gpt-4.1-mini
```

含义：

- `/model`
  直接查看当前模型模式，不切换。
- `auto`
  让系统根据场景自行选取倾向。
- `fast`
  更偏轻量、更快。
- `think`
  更偏分析、讲题、长推理。
- `custom`
  你手动指定模型名。

### 5.3 开关学习模式

```text
/study
/study on
/study off
```

学习模式开启后：

- `/study`
  直接查看学习模式当前是否开启。
- 回复更偏讲题、解释、分步骤
- 对数学、概念、推理类问题更积极
- 仍然保留人格感，不会直接变成题库

---

## 6. 第一次对话建议你怎么喂信息

如果你想让她更快进入“长期陪伴”状态，第一天建议主动说清楚这些。

### 6.1 基础身份与称呼

- 你希望她叫你什么
- 你不希望被怎么叫
- 你们关系里你更喜欢她偏近一点，还是偏克制一点

示例：

```text
以后你叫我阿微。
别频繁换来换去叫法，稳定一点就行。
```

### 6.2 你真正想让她长期盯的主线

- 学习
- 作息
- 项目推进
- 情绪稳定
- 某个长期目标

示例：

```text
你现在最该帮我盯的是作息和数学。
项目那边你可以记，但提醒别太密。
```

### 6.3 你不喜欢的互动方式

- 不喜欢太客服
- 不喜欢模板安慰
- 不喜欢连续追问
- 不喜欢一上来列清单

示例：

```text
我状态不好时别一上来列建议。
也别太像客服或者咨询师。
```

### 6.4 你希望她怎么督促你

- 轻一点
- 直接一点
- 只抓一个点
- 可以管作息，但别太硬

示例：

```text
你可以直接一点提醒我早睡。
但别一口气说很多条。
```

---

## 7. 这套记忆系统到底记什么

### 7.1 原始消息 `messages`

这是事实层。

你和她每一轮实际说了什么，都会先落在这里。

### 7.2 会话记忆 `session_memories`

这是短期层。

它存：

- 这一轮正在聊什么
- 当前短期情绪
- 当前学习节点
- 还没收完的话头

它的特点是：

- 有过期概念
- 更偏当前会话
- 不代表一定要进长期记忆

### 7.3 长期记忆 `long_term_memories`

这是“她以后还能记得你”的关键层。

会存：

- 长期目标
- 稳定偏好
- 经常出现的问题
- 她答应要继续盯的事
- 对你重要的关系线索

### 7.4 候选记忆 `candidate_memories`

不是所有提到的东西都会立刻进长期记忆。

现在系统会把一部分“可能值得记，但还没必要立刻入库”的内容先放候选区。

候选区可以在 Dashboard 里做两种处理：

- 确认保存
- 拒绝

### 7.5 结构化事实 `structured_facts`

适合稳定、高优先级、能直接影响回复的内容。

例如：

- 你的 preferred name
- 长期目标
- 明确边界
- 你能接受的提醒方式

### 7.6 关系状态 `relationship_states`

它不只是记“事情”，还记“怎么相处”。

例如：

- 你更吃什么风格的安抚
- 你不喜欢什么说话方式
- 她什么时候该更接住，什么时候该更收住

### 7.7 摘要 `conversation_summaries`

当聊天拉长后，只靠原始消息会越来越贵，也越来越容易散。

所以系统会维护滚动摘要，用来保持：

- 关系连续感
- 最近真实状态
- 还没收掉的长期线索

---

## 8. 如何让记忆更准、少脏记忆

### 8.1 尽量说“稳定信息”，少说“噪音”

更适合长期记的是：

- “我一熬夜就容易整个人散掉”
- “我不喜欢被连续追问”
- “我更吃平静一点但直接一点的提醒”

不太适合长期记的是：

- “我今天有点烦”
- “我现在先不想动”

除非它反复出现并形成模式。

### 8.2 重要信息尽量说完整

例如不要只说：

```text
我最近在学数学
```

更好的是：

```text
我最近在补数学，最卡的是函数和数列，想在下次月考前拉回来。
```

### 8.3 记错了就直接纠正

示例：

- “这个你记错了，我不是不想被提醒，我是不想被催得太急。”
- “这个不用记成长线。”
- “这个边界你重新记一下。”

### 8.4 做大实验前最好换测试库

如果你要反复乱测，建议在 `.env` 临时换：

```env
DATABASE_PATH=data/shen_zhiwei_test.sqlite3
```

这样不会把正式长期数据弄脏。

---

## 9. Dashboard 每个页面怎么看

Dashboard 默认地址：

```text
http://127.0.0.1:8099
```

### 9.1 首页概览

看这些指标：

- 消息总数
- 长期记忆数量
- 候选记忆数量
- 任务积压数
- 开放错误数
- 主动消息接受率

### 9.2 最近对话

这里适合看：

- 最近一轮属于什么场景
- 当前回复目标是什么
- 用了哪个模型
- 体验指标怎么打的

### 9.3 实时日志

适合排查：

- 为什么没回
- 后台任务有没有跑
- DuckDuckGo HTML 检索有没有失败
- 健康检查有没有报错

### 9.4 性能体验

会看到两大块：

- 性能摘要
- 体验指标摘要

重点关注：

- 平均延迟
- fallback rate
- 人格一致性
- 记忆命中质量
- 过度解释率
- 工具痕迹泄漏率

### 9.5 后台任务

会看到：

- `pending`
- `running`
- `retrying`
- `completed`
- `failed`
- `timed_out`

适合看：

- 记忆提取有没有积压
- 健康检查有没有在定时跑
- 主动消息扫描有没有执行

### 9.6 长期记忆

这里可以看：

- 具体长期记忆内容
- 类型
- 分类
- hit count
- 最近命中时间

也支持：

- 归档某条长期记忆

### 9.7 候选记忆

这里是人工审核区。

你可以：

- 确认保存
- 拒绝

适合定期清理：

- 重复候选
- 一次性噪音
- 不适合长期保留的内容

### 9.8 分层记忆快照

这是看“某一轮回复前系统脑子里到底有什么”的地方。

适合检查：

- 最近消息
- session memory
- long-term memory
- structured facts
- relationship state
- summary

### 9.9 错误

这里会显示：

- 哪个组件报错
- 严重级别
- 错误内容
- 附带细节

### 9.10 健康

这里会看：

- database
- auth
- chat
- fallback
- dashboard
- document_parser

---

## 10. 如何验证这些功能真的存在

这里给你一套按顺序的验证清单。

### 10.1 先验证结构层

执行：

```bash
python3 scripts/verify_product.py
python3 scripts/dashboard_contracts.py
```

通过标准：

- API 回归脚本通过
- Dashboard 契约测试通过
- 关键响应结构不会漂移

### 10.2 再验证 Dashboard

启动主程序后打开：

```text
http://127.0.0.1:8099
```

你应该能看到：

- Overview
- 全局搜索
- 日志
- 性能成本
- 后台任务
- 长期记忆
- 候选记忆
- Turn Trace
- 附件工件
- 主动消息
- Structured Facts
- Relationship States
- Summary
- 分层记忆快照 / diff
- 错误
- 健康趋势

然后执行：

```bash
python3 scripts/dashboard_e2e.py
python3 scripts/dashboard_visual_regression.py
```

通过标准：

- 真实浏览器登录、tab 切换、scope 切换和关键按钮链路通过
- 登录页、总览页、候选记忆页的视觉快照 hash 通过

### 10.3 验证普通聊天

在 Discord DM 里发：

```text
我最近总是拖延，晚上又容易熬夜。
```

你应该观察到：

- 她能正常回复
- 回复是分段流出的，不是死等很久后整块吐出来
- Dashboard 最近对话里能看到这轮 trace

### 10.4 验证学习模式

先发：

```text
/study on
```

再发：

```text
你给我讲一下函数单调性怎么判断，别只给结论。
```

你应该观察到：

- 她的讲法明显更像陪学
- 更有步骤感
- 仍然不是冰冷题库风格

### 10.5 验证搜索型回复

直接发：

```text
帮我查一下最近 iOS 上这类订阅产品大概怎么定价。
```

你应该观察到：

- 她不是按普通闲聊乱答
- Dashboard 最近对话里会显示这一轮是搜索型回复
- 搜索上下文里会出现外部来源标题和链接摘要

### 10.6 验证绘图型回复

发：

```text
给我画一张偏电影感的海边夜景。
```

你应该观察到：

- 她会先自然接一句
- 然后发回图片

### 10.7 验证图片 / 语音 / 文档

分别发：

- 一张题目截图
- 一段语音
- 一个 pdf 或 docx

你应该观察到：

- 她会把附件内容纳入当前轮理解
- Dashboard 的最近一轮 trace 里能看到附件信息

### 10.8 验证记忆写入与候选区

连续几轮告诉她：

```text
以后你叫我阿微。
我状态不好时别一上来列建议。
你主要盯我的作息和数学。
```

然后去 Dashboard 看：

- 长期记忆
- 候选记忆
- 分层快照

你应该能看到：

- 有些信息已经进了长期层
- 有些信息会先进候选区

### 10.9 验证主动消息

把系统开着，超过你设置的空闲时长后，看她是否会主动 DM。

然后观察：

- `proactive_messages`
- Dashboard 概览里的主动接受率

### 10.10 直接查数据库

数据库默认在：

```text
data/shen_zhiwei.sqlite3
```

你可以直接查：

```bash
sqlite3 data/shen_zhiwei.sqlite3 ".tables"
sqlite3 data/shen_zhiwei.sqlite3 "select id,sender_type,substr(content,1,80) from messages order by id desc limit 10;"
sqlite3 data/shen_zhiwei.sqlite3 "select memory_type,category,substr(content,1,120),importance,confidence from long_term_memories order by updated_at desc limit 20;"
sqlite3 data/shen_zhiwei.sqlite3 "select candidate_uid,memory_type,category,substr(content,1,120),status from candidate_memories order by updated_at desc limit 20;"
sqlite3 data/shen_zhiwei.sqlite3 "select component,status,message,checked_at from health_checks order by id desc limit 20;"
sqlite3 data/shen_zhiwei.sqlite3 "select task_type,status,attempts,last_error from background_tasks order by id desc limit 20;"
sqlite3 data/shen_zhiwei.sqlite3 "select turn_uid,request_type,scene,reply_goal,mode_text from turn_traces order by id desc limit 20;"
```

---

## 11. 日常使用建议

### 11.1 最好固定一个聊天入口

现在正式入口就是 DM。

最稳的使用方式就是：

- 只在 Discord 私聊她

### 11.2 重要设定说清楚 1 到 2 次就够

不要每轮都重复。

她如果已经记住了，就让系统自然使用。

### 11.3 真想测试边界时，别拿正式库乱灌

尤其不要反复喂：

- 假偏好
- 假称呼
- 相互冲突的人设要求
- 明显与你无关的垃圾测试文本

### 11.4 搜索型请求尽量写具体

比起：

```text
帮我搜一下这个
```

更好的是：

```text
帮我查一下 2026 年现在 iOS 上 AI 陪伴类 app 的常见订阅价格区间。
```

这样搜索模型更容易稳定发挥。

---

## 12. 常见问题

### 12.1 她不回复

优先检查：

- 主程序是不是还在跑
- `DISCORD_BOT_TOKEN` 是否正确
- 你是不是在 Discord 私聊里发的
- 日志里有没有异常

### 12.2 Dashboard 打不开

检查：

- `DASHBOARD_ENABLED=true`
- 端口有没有被占
- 启动日志里有没有 uvicorn 报错

### 12.3 搜索型回复像没联网

检查：

- 服务器是不是能访问 DuckDuckGo HTML
- `SEARCH_TIMEOUT_SECONDS` 是否太短
- `SEARCH_MAX_RESULTS` 是否被配得太小
- 日志和错误页里有没有 `duckduckgo_html` 检索失败信息

### 12.4 图片 / 语音 / 文档没理解好

检查：

- 视觉模型、音频模型是否可用
- 附件内容是否过长被截断
- 日志里有没有附件处理失败

### 12.5 她记错了

最直接做法：

1. 在聊天里纠正
2. 到 Dashboard 里看长期记忆和候选记忆
3. 必要时归档错误长期记忆，或拒绝错误候选

### 12.6 原来的历史记忆会不会丢

不会。

现在这次升级是增量扩表，不会清空原有：

- `messages`
- `long_term_memories`
- `structured_facts`
- `relationship_states`

---

## 13. 推荐的一套日常工作流

如果你想把这套系统用成长期正式产品，建议按这个节奏：

### 每天

- 正常在 DM 里聊
- 学习时开学习模式
- 需要查资料时直接自然说，不用切别的工具

### 每 2 到 3 天

- 看一眼 Dashboard 的候选记忆
- 确认或拒绝明显需要处理的候选

### 每周

- 看一次长期记忆区
- 归档明显过期或记错的记忆
- 看一次错误页和健康页

### 做重要升级前

- 先备份数据库

例如：

```bash
cp data/shen_zhiwei.sqlite3 data/shen_zhiwei.backup.sqlite3
```

更完整的备份 / 导出 / 恢复步骤见 `docs/SQLITE_BACKUP_AND_RECOVERY.md`。

---

## 14. 最短启动清单

如果你现在只想立刻开始，按这个顺序来：

1. `cp .env.example .env`
2. 填 `DISCORD_BOT_TOKEN`、`LLM_API_KEY`、`LLM_MODEL`
3. 如果你要拆分部署，按需设置 `RUN_DISCORD_BOT` / `RUN_BACKGROUND_WORKER`
4. `python3 -m pip install -r requirements.txt`
5. `python3 scripts/verify_product.py`
6. `python3 -m src.main`
7. 本机部署时打开 `http://127.0.0.1:8099`
8. 如果是服务器部署，先确认 `.env` 里的 `DASHBOARD_HOST` 不是 `127.0.0.1`
9. 去 Discord DM 她，先发一句：

```text
以后你叫我阿微。你先帮我盯作息和数学。
```

10. 再发一句：

```text
/status
```

11. 最后开始正常聊

---

## English fallback

This guide is written primarily for a single long-term user running Study Senpai as a personal companion system.

The shortest path is:

1. Copy `.env.example` to `.env`.
2. Fill `DISCORD_BOT_TOKEN`, `LLM_API_KEY`, and `LLM_MODEL`.
3. Install dependencies with `python3 -m pip install -r requirements.txt`.
4. Run `python3 scripts/verify_product.py`.
5. Start with `python3 -m src.main`.
6. Open the local Dashboard at `http://127.0.0.1:8099`.
7. Use Discord DM as the primary chat entry.

The system supports long-term DM chat, stable persona behavior, memory candidates, summaries, images, audio, documents, study mode, search-style replies, image generation, proactive messages, and Dashboard-based observation/review.

Key safety notes:

- Keep secrets in `.env`, never in git.
- Use a test database when experimenting with memory behavior.
- Review candidate and long-term memories in Dashboard.
- Back up `data/shen_zhiwei.sqlite3` before major upgrades.
- See `docs/OPERATIONS_RUNBOOK.md` for operational checks and `docs/SQLITE_BACKUP_AND_RECOVERY.md` for backup/restore details.
