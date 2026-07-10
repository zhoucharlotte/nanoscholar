# Nanoscholar

Nanoscholar 是一个本地研究助手，主要面向论文检索、PDF 解析、知识库沉淀、工具调用式分析，以及小型多 Agent 协作流程。它默认以 CLI 方式运行，也可以按配置接入 Telegram。

这个项目的核心目标不是做一个泛用聊天机器人，而是把一条更稳定的研究工作流串起来：

- 从标题、arXiv ID 或关键词检索论文
- 下载并解析 PDF
- 将结构化结果写入本地知识库
- 后续追问直接复用知识库，而不是反复下载和提取

## 主要功能

- 论文一体化入库：`ingest_paper`
  - 优先搜索 arXiv
  - 必要时回退到 Semantic Scholar
  - 自动下载 arXiv PDF
  - 自动提取正文
  - 自动写入 `knowledge_base/notes`
- 零模型依赖 PDF 解析
  - 基于 PyMuPDF 文本块坐标
  - 几何驱动的阅读顺序恢复
  - 双栏检测与分离
  - 页眉页脚过滤
- 工具路由与裁剪
  - 关键词意图识别
  - 示例查询匹配
  - 最近工具历史继承
  - 对研究类请求自动收窄工具集合，减少错误 detour
- 本地记忆与知识库
  - SQLite 持久化记忆
  - 去重和噪声过滤
  - 本地 Markdown 知识库
  - 支持列出知识库中的论文条目
- 多 Agent 支持
  - 子 Agent 独立进程运行
  - `Planner -> Researcher` 协作链路
  - 支持并发子任务
- 后台调度
  - 让助手在未来某个时间点自动执行自然语言任务

## 项目结构

```text
nanoscholar/
  core/            Agent 主循环、上下文、权限、子 Agent 运行时
  interfaces/      CLI 和 Telegram 入口
  knowledge/       知识库索引与检索
  mcp/             MCP client/server 协议层
  tools/           工具注册、工具路由、系统工具与领域工具
configs/
docs/
knowledge_base/
papers/
tests/
RESEARCH.md
```

## 运行环境

- Python 3.10+
- Windows、macOS 或 Linux
- 可以访问论文检索和 PDF 下载所需网络
- 一个兼容 OpenAI Chat Completions API 的模型服务

## 安装

```powershell
cd D:\Projects\nanoscholar
python -m venv .venv
& .\.venv\Scripts\activate
pip install -e .
```

如果你需要 Telegram 支持：

```powershell
pip install -e .[telegram]
```

## 配置

仓库内提供了一个公开可提交的模板配置：

```text
configs/config.example.yaml
```

建议先复制一份：

```powershell
Copy-Item configs\config.example.yaml configs\config.yaml
```

然后重点填写这些字段：

- `llm.base_url`
- `llm.api_key`
- `llm.model`
- `workspace.path`
- `logging.file`
- `permissions.approval.mode`
- `telegram.token`

当前模板默认使用：

- `https://api.openai.com/v1`
- `gpt-4.1-mini`
- 工作区限制模式
- 对 `execute_command` 和 `write_file` 启用审批
- 对明显安全的只读命令启用自动放行

## 启动方式

CLI：

```powershell
cd D:\Projects\nanoscholar
& .\.venv\Scripts\python.exe -m nanoscholar -c configs\config.yaml
```

查看帮助：

```powershell
& .\.venv\Scripts\python.exe -m nanoscholar -h
```

## CLI 命令

```text
/clear          清空当前对话上下文
/clear-all      清空所有保存的对话上下文
/compact        压缩旧上下文，仅保留最近工作窗口
/rewind         恢复压缩前的上下文
/memory-stats   查看持久化记忆统计
/memory-clear   清空持久化记忆
/exit           退出
```

## 推荐研究工作流

### 1. 搜索某个方向的相关论文

示例：

```text
找一下 agent memory compression 相关论文
你找找 agent 自进化相关的论文
```

典型工具链：

- `arxiv_search`
- `semantic_scholar_search`

### 2. 分析某一篇明确论文

示例：

```text
2510.07985v3 你下载来分析分析
Lightweight LLM Agent Memory with Small Language Models 帮我看看
```

典型工具链：

- `ingest_paper`

对于这类明确论文请求，只要 `ingest_paper` 成功，系统会优先基于入库结果直接回答，而不是继续发散到无关搜索。

### 3. 对已入库论文继续追问

示例：

```text
这篇论文的方法细节是什么
它的实验结果怎么样
```

典型工具链：

- `search_my_notes`
- 或直接复用已缓存的 `ingest_paper` 结果

### 4. 查看知识库里已经有哪些论文

示例：

```text
我的知识库里有哪些论文
列出知识库里的笔记
```

典型工具链：

- `list_my_notes`

这样做的目的是避免为了“列清单”而错误地调用 shell 去枚举目录。

## 数据存储位置

Nanoscholar 主要把运行状态存到三个位置：

- `nanoscholar.db`
  - SQLite 数据库，保存记忆和调度任务
- `papers/`
  - 下载下来的 arXiv PDF
- `knowledge_base/`
  - `notes/`：结构化 Markdown 笔记
  - `index.json`：知识库索引

## 工具召回机制

模型不是每轮都看到全部工具，而是先经过一层工具路由：

1. 关键词意图匹配
2. 示例查询相似度匹配
3. 最近工具历史继承
4. 针对特定上下文做工具裁剪

例如在论文研究场景下，系统会主动隐藏一些容易带偏的工具路径，比如不必要的 shell detour 或直接抓原始学术搜索页。

## 测试与检查

基础检查：

```powershell
& .\.venv\Scripts\python.exe -m compileall nanoscholar tests
pytest
```

快速入口检查：

```powershell
& .\.venv\Scripts\python.exe -m nanoscholar -h
```

## 当前限制

- arXiv 和 Semantic Scholar 依然可能独立失败，例如 API 不稳定、超时或限流。
- 当前工具路由主要是规则驱动，不是学习式检索，所以极端措辞仍可能导致不理想召回。
- 旧知识库笔记如果内容不完整或误匹配，可能需要手动清理，或者使用 `force_refresh=true` 重建。
- 这个项目偏重“实用研究助手”，不是完备的论文管理平台，也不是严格意义上的文献数据库系统。

## 发布到 GitHub 前的注意事项

仓库当前已经做了两层公开化处理：

- `configs/config.yaml` 已去敏
- `.gitignore` 已忽略本地运行数据、PDF、知识库内容、数据库和日志

但你在公开前仍然建议检查这些内容是否还需要清理：

- `nanoscholar.db`
- `nanoscholar.log`
- `mcp_server_debug.log`
- `papers/`
- `knowledge_base/notes/`
- `knowledge_base/index.json`

## License

见 [LICENSE](LICENSE)。
