# AI Agent 全链路自动化开发系统

> 2026"歌尔杯"香港城市大学（东莞）第二届黑客马拉松参赛项目

给定一份 Markdown 产品规格说明书，本系统自动调用三个 AI Agent 依次完成**概要设计 → 代码生成 → 测试生成**，输出可立即运行的完整应用程序（后端 + 前端 + 单元测试）。

核心 Orchestrator、Agent 基类、状态机、Artifact 协议、重试机制、质量验证器均为本项目自研实现，**不依赖 LangChain、CrewAI、AutoGen、LangGraph 等 Agent 框架**。

---

## 系统架构

```
Markdown 产品规格说明书
        │
        ▼
  FastAPI 上传接口 / Streamlit 控制台
        │
        ▼
  Orchestrator（批次管理 · 状态机 · 执行日志）
        │
        ├─ DesignAgent  ──►  overview_design.md  +  design_manifest.json
        │
        ├─ CodeAgent    ──►  src/  +  frontend/  +  code_manifest.json
        │
        └─ TestAgent    ──►  tests/generated/  +  test_plan.md
        │
        ▼
  Validator（设计完整性 · 代码可运行性 · 覆盖率 ≥ 80%）
        │
        ▼
  output/{batch_id}/   ←  可下载的完整应用包（.zip）
```

### 目录结构

```
app/
  adapters/      LLMAdapter 协议 · OpenAIAdapter · MockLLMAdapter
  agents/        DesignAgent · CodeAgent · TestAgent（含确定性模板回退）
  api/           FastAPI 流水线管控接口
  orchestrator/  Orchestrator 引擎 · Pydantic 状态模型 · 执行日志 · BestOfSelector
  storage/       FileStore（文件读写 · SHA-256 · ArtifactRef）
  validators/    DesignArtifactValidator · CodeValidator · TestValidator
ui/
  streamlit_app.py   可视化控制台（上传 · 状态 · 日志 · 重试 · 下载）
prompts/             各 Agent 系统提示词
docs/待生成/          上传的规格说明书
docs/已生成/          各批次状态文件 · 日志 · Artifact 引用
output/              各批次生成的可运行代码
```

---

## 三 Agent 职责与通信契约

Agent 之间**禁止**通过内存传递内容；全部通信通过持久化 Artifact 文件（`ArtifactRef` 引用）进行。

### DesignAgent

- **输入**：产品规格说明书（`spec.md`）
- **输出**：`overview_design.md`（八章结构概要设计）+ `design_manifest.json`（结构化清单）
- `design_manifest.json` 必须包含：`system_name`、`modules`、`entities`、`business_rules`、`api_endpoints`、`csv_tables`、`validation_rules`、`frontend_requirements`、`pages`、`acceptance_criteria`

### CodeAgent

- **输入**：`overview_design.md` + `design_manifest.json`（设计文档为主权威）
- **输出**：`src/*.py`（FastAPI 后端）+ `frontend/`（规格书要求 Web 界面时）+ `code_manifest.json`
- 生成代码写入 `output/{batch_id}/`，快照同步到 `docs/已生成/{batch_id}/代码生成/`
- 无法调用 LLM 时自动回退到确定性内置模板，**无 API Key 也可完整演示**

### TestAgent

- **输入**：`overview_design.md` + `design_manifest.json` + `code_manifest.json` + 源文件路径索引
- **输出**：`tests/generated/` 下四类 pytest 文件 + `test_plan.md`
  - `test_api_routes.py`：每条路由的正常路径 + 每个错误场景
  - `test_business_rules.py`：每条业务规则的满足 + 违反
  - `test_storage.py`：写操作后验证 CSV 行内容
  - `test_frontend_contract.py`：前端文件存在性 + HTML 控件检查

---

## Orchestrator 状态机

### 批次状态

| 状态 | 含义 |
|------|------|
| `queued` | 批次已创建，等待启动 |
| `running` | 正在执行某个节点 |
| `paused` | 手动模式下等待用户审批 |
| `succeeded` | 全部节点执行成功 |
| `failed` | 某节点超出重试次数后失败 |

### 节点重试

从任意失败节点重试时，该节点及其所有下游节点自动重置为 `queued` 并重新执行。重试次数上限由 `MAX_RETRIES` 控制（默认 2 次）。

### 持久化产物

每个批次写入 `docs/已生成/{batch_id}/`：

- `batch_status.json`：当前状态、各节点状态、重试次数、质量检查结果
- `execution_log.json`：时间戳、事件类型、节点 ID、耗时（ms）、LLM 模型信息、错误类名

---

## 质量验证器

每个节点成功执行后自动运行对应验证器，结果写入 `batch_status.json` 的 `quality_check_result` 字段。

| 验证器 | 检查内容 |
|--------|----------|
| `DesignArtifactValidator` | `overview_design.md` 非空；`design_manifest.json` 包含全部 7 个必需字段 |
| `CodeValidator` | `src/` 存在且含 `__init__.py` + `api.py`；所有 `.py` 文件语法正确；`src.api.app` 可导入；规格书要求前端时检查 `frontend/index.html` 含 `form` 和 `button` |
| `TestValidator` | `tests/generated/test_*.py` 存在；执行 `pytest --cov`，覆盖率 ≥ 80%；低于阈值节点标记 `failed` |

---

## 流水线管控 API

后端：`http://127.0.0.1:8000` · Swagger 文档：`http://127.0.0.1:8000/docs`

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/v1/batches` | 列出所有批次（最新优先） |
| `POST` | `/api/v1/batches` | 上传规格说明书，创建新批次 |
| `POST` | `/api/v1/batches/{id}/run` | 启动批次（自动模式） |
| `GET` | `/api/v1/batches/{id}` | 查询批次完整状态 |
| `GET` | `/api/v1/batches/{id}/logs` | 获取执行日志 |
| `GET` | `/api/v1/batches/{id}/artifacts` | 列出批次全部 Artifact |
| `GET` | `/api/v1/batches/{id}/download?path=...` | 下载单个 Artifact 文件 |
| `GET` | `/api/v1/batches/{id}/package` | 打包下载完整生成代码（.zip） |
| `POST` | `/api/v1/batches/{id}/advance` | 手动模式：审批并执行下一节点 |
| `POST` | `/api/v1/batches/{id}/retry/{node_id}` | 从指定节点重试（下游自动重置） |
| `POST` | `/api/v1/validate` | 对已完成批次执行烟雾验证 |
| `GET` | `/api/v1/batches/{id}/score` | 对设计产物打分（0–100） |
| `POST` | `/api/v1/batches/best-of` | 多批次竞选：取设计评分最高者重新生成代码与测试 |

---

## 快速开始

### 1. 安装依赖

Python 3.12+ 必须。

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，按需填入以下变量
```

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | 留空则使用 MockLLMAdapter，无 key 仍可完整演示 |
| `OPENAI_BASE_URL` | 可选，兼容任意 OpenAI 协议接口 |
| `DESIGN_MODEL` / `CODE_MODEL` / `TEST_MODEL` | 各节点使用的模型，留空由适配器决定 |
| `MAX_RETRIES` | 每节点最大重试次数，默认 `2` |
| `LLM_STRICT` | 有 key 时默认 `true`；`false` 表示 LLM 失败时降级到内置模板 |

> API Key 仅从环境变量读取，禁止写入任何源文件；执行日志已过滤 key/token 类字段。

### 3. 启动后端

```bash
uvicorn app.api.main:app --reload --reload-dir app
```

### 4. 启动控制台 UI（新开一个终端）

```bash
source .venv/bin/activate        # Windows: .venv\Scripts\activate
streamlit run ui/streamlit_app.py
```

浏览器访问：`http://localhost:8501`

---

## 演示流程

1. 在 Streamlit 控制台上传产品规格说明书（`.md` 文件）
2. 选择运行模式：
   - **auto**：三个节点自动依次执行
   - **manual**：每个节点执行前暂停，需点击"审批"后继续，适合现场讲解
3. 点击"Create batch"，观察节点状态依次变为 `succeeded`
4. 节点完成后可查看执行日志、各 Artifact 内容，或一键下载完整代码包（.zip）
5. 运行生成的应用：

```bash
cd output/<batch_id>
uvicorn src.api:app --reload      # 启动生成的后端
# 用浏览器直接打开 frontend/index.html（如有前端）
```

> 演示用验证用例：赛题提供的《员工临时车辆预约程序》产品规格说明书，位于 `problem/` 目录。

---

## 测试

### 测试流水线平台本身

```bash
pytest tests/test_state_and_storage.py tests/test_orchestrator_and_api.py -q
```

### 测试流水线生成的业务系统

```bash
cd output/<batch_id>
pytest tests/generated -q --cov=src --cov-branch --cov-report=term-missing
```

大部分测试无需 API Key，MockLLMAdapter 即可运行。

---

## 开源依赖

| 库 | 用途 |
|----|------|
| FastAPI | 流水线管控 API |
| Uvicorn | ASGI 服务器 |
| Streamlit | 可视化控制台 |
| Pydantic v2 | 状态模型与数据验证 |
| OpenAI Python SDK | LLM 调用（可选） |
| python-dotenv | 环境变量加载 |
| pytest + pytest-cov | 测试与覆盖率 |
| requests | Streamlit 调用后端 |
