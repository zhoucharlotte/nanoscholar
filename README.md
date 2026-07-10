# Nanoscholar

Nanoscholar 是一个面向本地运行场景的研究助手项目。它支持命令行交互、论文检索、arXiv PDF 下载与解析、知识库笔记沉淀、上下文压缩、工具路由，以及基于子 Agent 的研究协作流程。

这个项目的目标不是做一个完整的文献管理平台，而是提供一套偏实用、可扩展、可本地控制的研究工作流底座。

## 主要功能

- 论文检索：支持 `arxiv_search`、`semantic_scholar_search`
- 论文读取：支持 `ingest_paper` 一键检索、下载、提取、入库
- PDF 解析：基于 PyMuPDF 的正文提取，并带双栏阅读顺序修正
- 本地知识库：支持保存、检索、列出论文笔记
- 工具路由：根据用户问题裁剪工具 Schema，减少无关工具暴露
- 上下文管理：支持清空上下文、会话裁剪与渐进式压缩
- 子 Agent 协作：支持 Planner / Researcher 风格的多任务拆分
- 权限控制：支持沙箱、审批、只读安全命令自动放行
- CLI 使用：支持本地命令行直接运行

## 项目结构

```text
Nanoscholar/
├─ configs/                  # 配置文件
├─ docs/                     # 文档
├─ nanoscholar/              # 主包
│  ├─ core/                  # Agent、上下文、权限、审批等核心逻辑
│  ├─ interfaces/            # 外部接口层
│  ├─ knowledge/             # 本地知识库存储
│  ├─ mcp/                   # MCP 客户端
│  └─ tools/                 # 工具注册、路由、论文/系统工具
├─ tests/                    # 测试
├─ RESEARCH.md               # 研究工作流补充说明
├─ pyproject.toml            # 项目元信息
└─ README.md
```

## 安装

推荐使用 Python 3.10 及以上版本。

```bash
git clone https://github.com/zhoucharlotte/nanoscholar.git
cd nanoscholar
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

如果你需要 Telegram 支持：

```bash
pip install -e .[telegram]
```

## 配置

复制配置模板并填写自己的参数：

```bash
copy configs\config.example.yaml configs\config.yaml
```

核心配置项示例：

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  api_key: "YOUR_API_KEY_HERE"
  model: "gpt-4.1-mini"
```

其他常用配置：

- `db_name`：本地数据库文件名
- `logging.file`：日志文件路径
- `agent_loop_max_iterations`：单轮最大工具调用迭代数
- `max_context_messages` / `max_context_tokens`：上下文裁剪阈值
- `permissions.approval.mode`：审批模式
- `permissions.approval.bypass_safe_commands`：安全只读命令自动通过

## 启动方式

在仓库根目录运行：

```bash
python -m nanoscholar -c configs\config.yaml
```

如果你使用的是 Windows 虚拟环境：

```powershell
& .\.venv\Scripts\python.exe -m nanoscholar -c configs\config.yaml
```

启动后进入 CLI 模式，可以直接输入问题，例如：

```text
INTER: Mitigating Hallucination in Large Vision-Language Models by Interaction Guidance Sampling 找一下这篇论文并告诉我有什么启发
```

## CLI 命令

项目当前以自然语言交互为主，常见能力包括：

- 让系统查找某篇论文
- 让系统下载并解析指定 arXiv ID
- 查看知识库里已经沉淀的论文
- 清空当前会话上下文
- 使用子 Agent 做研究拆分

如果你需要扩展成显式命令模式，可以在 `nanoscholar/main.py` 和 `nanoscholar/core/agent.py` 上继续加入口命令。

## 研究工作流

当前论文相关任务的推荐路径是：

1. 优先使用 `ingest_paper`
2. 必要时调用 `arxiv_search` / `semantic_scholar_search`
3. 下载 PDF 到本地 `papers/`
4. 使用 `pdf_extract_text` 提取全文
5. 生成摘要并保存到 `knowledge_base/notes/`

其中 `ingest_paper` 已经负责把“搜索、下载、提取、知识库沉淀”串起来，适合处理：

- arXiv ID
- arXiv 链接
- DOI
- 比较明确的论文标题

## 数据存储位置

默认运行时会在仓库内生成这些数据：

- `nanoscholar.db`：本地数据库
- `nanoscholar.log`：主日志
- `mcp_server_debug.log`：MCP 调试日志
- `papers/`：下载的论文 PDF
- `knowledge_base/notes/`：论文笔记与知识卡片
- `knowledge_base/index.json`：知识库索引

这些内容默认已经加入 `.gitignore`，适合本地保留、远程仓库忽略。

## 工具召回机制

项目当前不是学习式检索，而是“规则 + 轻量匹配”的路由机制。

主要流程在 `nanoscholar/tools/router.py`：

1. 先做关键词和意图判断
2. 再做离线示例匹配
3. 按意图裁剪工具集合
4. 对研究类问题优先暴露论文相关工具
5. 对精确论文请求优先走 `ingest_paper`

对于“我的知识库里有哪些论文”这类请求，系统会优先召回 `list_my_notes`，而不是走命令执行工具。

## 测试与检查

你可以先做最基本的运行检查：

```bash
python -m nanoscholar -h
python -m compileall nanoscholar tests
```

也可以运行测试：

```bash
pytest
```

如果你只想验证导入链是否正常：

```bash
python -c "import nanoscholar, nanoscholar.main, nanoscholar.mcp.client, nanoscholar.tools.router; print('ok')"
```

## License

本项目使用 [MIT License](./LICENSE)。
