# AGENTS.md

This file provides guidance to Codex when working with code in this repository.

## Project Overview

Test Fast API 后端骨架项目。Python 3.10+，基于 FastAPI 异步架构，PostgreSQL (SQLModel ORM) + Redis (缓存/会话) + Celery (异步任务队列)。

本项目从 `cert_phase2_backend` 的工程约定抽取而来，只保留基础框架、目录分层、运行配置、AGENTS 规则和 `.codex/skills`，暂不包含具体业务功能实现。

完整项目结构和本地启动说明见 [README.md](README.md)。

## Design Principles

> **生成代码时，必须遵循以下约束。不要为超出这些约束的场景过度设计。**

1. **简单优于可扩展** — 本地开发优先；禁止引入分布式模式（saga、event sourcing、CQRS），除非明确要求。
2. **正确优于高性能** — 优先清晰、可审计的代码。不要为系统永远不会达到的吞吐量做过早优化。
3. **容错优于快速失败** — 记录错误并继续，而非崩溃。
4. **单仓库，共享代码** — Worker 与 API 共用 `app/` 包，不要拆分独立仓库或包。
5. **Worker 中同步 DB 可接受** — Celery 任务通过 `asyncio.run()` 桥接 async 代码，内部使用 `Session(engine)` (sync)。这是低吞吐量下的已知取舍；除非明确要求，不要重构为 AsyncSession。

### 系统规模

- **低并发**：内部团队工具，非公开高流量服务。
- **Backend**：本地 `uvicorn --reload` 进程，仅处理 HTTP 请求，无后台任务。
- **Celery worker**：本地 Celery worker 进程，开发默认 `--concurrency=1`。
- **Celery Beat**：本地 Celery Beat 进程，定时调度器（默认每 60 分钟触发框架健康检查任务）。
- **Flower**：本地 Flower 进程，Celery 任务监控 Web UI（端口 5555）。
- 预期峰值：数十并发 API 请求，每分钟个位数 Celery 任务。

## Commands

```bash
# 安装依赖
uv sync --dev

# 激活虚拟环境
source .venv/bin/activate

# 运行测试
bash ./scripts/test.sh

# 代码检查（mypy + ruff check + format check）
bash ./scripts/lint.sh

# 自动格式化
bash ./scripts/format.sh

# 运行单个测试
pytest tests/test_example.py -v
pytest tests/test_example.py::test_function -v

# 数据库迁移
alembic revision --autogenerate -m "Description"
alembic upgrade head

# 本地开发（需先按 .env.example 准备本机 PostgreSQL / Redis）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8083

# Celery Worker（本地开发）
celery -A app.core.celery_app:celery_app worker --loglevel=info --concurrency=1 --pool=prefork

# Celery Beat（本地开发，定时调度）
celery -A app.core.celery_app:celery_app beat --loglevel=info

# Flower 监控面板（本地开发）
celery -A app.core.celery_app:celery_app flower --port=5555

# Pre-commit hooks
pre-commit install
pre-commit run --all-files
```

## Architecture Rules

### 分层职责

```
HTTP Request → Router → Service → CRUD → PostgreSQL
                     ↘ Celery .delay() → Redis Broker → Celery Worker
              Celery Beat → Redis Broker → Celery Worker (定时清理)
```

- **Router** (`app/api/routes/`) — 输入验证 + 依赖注入，不含业务逻辑
- **Service** (`app/services/`) — 业务规则 + 编排 + 任务入队
- **CRUD** (`app/crud/`) — 纯数据库操作，不含业务逻辑
- **Tasks** (`app/tasks/`) — Celery 任务定义，通过 `asyncio.run()` 桥接 async 代码

### Models vs Schemas

**`app/models.py`** — ORM 层（单文件）

- 枚举：`DatasetType`、`DatasetStatus`、`LabelStatus`、`LabelActiveStatus`
- 关联表：`DatasetImageLabelLink`（table=True）
- Base 类：`UserBase`、`ItemBase`、`LabelBase`、`DatasetBase`、`DatasetImageBase`
- 数据库表模型：`User`、`Item`、`Label`、`Dataset`、`DatasetImportError`、`DatasetImage`、`PromptTemplate`、`PromptTemplateImage`、`FinetuneInstructionTask`、`FinetuneInstructionTaskConfig`、`FinetuneInstructionTaskVersion`、`FinetuneInstructionTaskVersionConfig`、`FinetuneInstruction`（均 table=True）
- 所有 ORM 模型在同一文件，使用 `from __future__ import annotations` 处理前向引用，无需 `TYPE_CHECKING`

**`app/schemas/`** — API 请求/响应 Schema

- CRUD Schema：`UserCreate`、`UserUpdate`、`UserPublic`、`DatasetPublic` 等（继承 Base 类）
- 复杂请求/响应：`DatasetDetailResponse`、`DatasetCreateRequest` 等（Pydantic BaseModel）
- 非数据库业务：`UploadInitResponse`、`ChunkUploadResponse`（Redis 会话相关）
- Token、通用组件、分页、外部模型配置 Schema（如 `FinetuneModelProvider`）等

**导入规则：**

- ORM 模型、枚举、Base 类 → `from app.models import ...`
- API Schema → `from app.schemas import ...`

## Code Style Conventions

> **以下规则从 datasets 模块提取，新增模块时必须遵循相同风格。**

## Documentation Map

本仓库的文档分工如下：

- `README.md`
  面向人类读者的项目总览、目录结构、启动方式和环境变量说明。
- `AGENTS.md`
  面向 Codex 的仓库级通用规则，定义全局架构约束、代码风格、文档分工和 skill 查找顺序。
- `.codex/skills/*`
  仓库内置的 repo-specific skills，用于约束本仓库特定的实现方式。它们回答“这类修改在本仓库里应该怎么做”。
- `requirements/*.md`
  业务需求真源，用于描述模块边界、状态流转、范围、约束和 TODO。它们回答“业务到底要求什么”。

规则：

- `AGENTS.md` 只保留仓库级通用规则，不重复展开长篇专题细节。
- 业务模块的细业务规则优先写在 `requirements/*.md`。
- 原始聊天记录、零散笔记、未整理 markdown 不要直接视为 `requirements/*.md` 真源；应先经 `requirement-to-llm-prompt` 整理后再落正式需求文档。
- 某类修改任务的实施细则优先写在对应 `.codex/skills/*/SKILL.md`。
- 不要把运行环境中的全局 skill 清单完整复制到仓库文档中。

## Skill Lookup Order

当任务需要使用 skill 时，按以下顺序查找：

1. 先查找仓库内 skills：`.codex/skills/*`
2. 若仓库内没有匹配 skill，再查找 Codex 运行环境提供的通用 skills
3. 通用 skills 通常位于 `$CODEX_HOME/skills`；当前环境中可能映射到 `/root/.codex/skills`
4. 若仓库内 skill 与通用 skill 都能覆盖同一问题，优先使用仓库内 skill，因为它包含本仓库特定约束
5. 若仍无匹配 skill，则回退到 `AGENTS.md` 的全局规则和现有代码实现进行判断

说明：

- `/root/.codex/skills` 属于当前运行环境实现细节，不作为仓库稳定契约的一部分
- 仓库文档中只需要说明 skill 查找顺序，不需要维护环境级 skill 的完整名单

## Repo Skill Routing Index

遇到以下任务时，优先查看本仓库内置 skills：

- 需求整理、把聊天需求或 `xxx需求.md` 转成可执行 prompt，或重写成正式 `requirements/*.md`
  见 `.codex/skills/requirement-to-llm-prompt`
- FastAPI 路由、Service、CRUD、Schema、分页、Options、消息常量相关修改
  见 `.codex/skills/fastapi-service-crud`
- `app/models.py`、SQLModel 查询、枚举 label、Alembic 迁移相关修改
  见 `.codex/skills/sqlmodel-alembic-postgres`
- JWT、Redis 单点登录、当前用户依赖、登录登出、权限校验相关修改
  见 `.codex/skills/auth-jwt-redis-session`
- Celery 任务、`.delay()` 入队、Beat 调度、任务注册相关修改
  见 `.codex/skills/celery-redis-worker`
- 安全审查、鉴权/上传/任务边界风险评估
  见 `.codex/skills/security-review-fastapi`
- 微调指令任务、版本、配置、指令、算法适配边界、微调 Celery 任务相关修改
  见 `.codex/skills/finetune-instruction-workflows`
- 视觉大模型训练资源、基础模型、训练任务、单机资源采集、训练调度巡检相关修改
  见 `.codex/skills/vlm-training-workflows`
- 大模型评测任务、共享训练资源调度、评测运行时占位、评测相关 options/任务链路修改
  见 `.codex/skills/vlm-evaluation-workflows`
- commit message 生成、改写、拆分提交建议、提交规范解释
  见 `.codex/skills/commit-message-conventions`

## Source of Truth Order

当多个文档对同一问题都有描述时，按以下优先级判断：

1. 相关业务需求文档 `requirements/*.md`
2. 对应仓库内 skill：`.codex/skills/*/SKILL.md`
3. `AGENTS.md` 中的仓库级通用规则
4. Codex 运行环境提供的通用 skills

如果需求文档、skill、历史示例代码之间存在冲突：

- 业务规则以 `requirements/*.md` 为准
- 仓库实现约束以 repo-specific skill 为准
- 通用 skill 只作为补充，不覆盖本仓库既有约束

补充说明：

- `requirements/*.md` 应视为已经过整理和确认的结构化需求真源，而不是未经处理的原始笔记。
- 当输入还是聊天需求、任务清单或零散 markdown 时，优先先用 `requirement-to-llm-prompt` 做需求桥接；需要沉淀为正式需求文档时，使用其 `rewrite-to-requirement-md` 模式。

### Requirement Bridge Usage

- 原始聊天需求 / 会议纪要 / 临时 markdown
  先用 `requirement-to-llm-prompt` 的 `rewrite-to-requirement-md` 模式，整理成正式 `requirements/*.md`
- 已确认的 `requirements/*.md`
  再用 `requirement-to-llm-prompt` 的 `normalize-to-prompt` 模式，整理为实现、评审或测试可执行 prompt

常见触发语句：

- `把下面这段非结构化需求整理成 requirements/xxx需求.md，不要写实现方案`
- `读取 docs/xxx-raw.md，先重写成 requirements/xxx需求.md，我确认后再继续实现`
- `读取 requirements/xxx需求.md，先做 plan-first 整理，再开始实现`

## Communication Style

> **默认以高信噪比方式回答，先解决用户当前真正问到的问题，不把简单问题回答成文档，不把局部问题扩展成全链路教程。**

### 默认规则

1. 优先回答用户明确问到的点，不主动扩展到无关背景、相邻模块、历史演进或可选方案，除非这些信息会直接影响结论。
2. 先给结论，再补充必要上下文；不要先铺垫大段背景再进入答案。
3. 默认简洁，除非用户明确要求详细说明、方案比较、完整设计或深入分析。
4. 如果一个问题可以用 2~5 句说清，就不要展开成十几段。
5. 如果存在会影响理解或使用结果的关键前提、边界条件、状态流转或限制，可以额外补 1~3 句必要说明。
6. 不为了“看起来全面”而罗列用户没问到的大量信息。
7. 不重复用户上下文里已经明确的信息，除非为了得出结论必须重申。
8. 用户问局部问题时，默认按局部问题回答；只有在局部问题无法脱离整体理解时，才补最小必要范围。
9. 对不确定的部分要明确区分“已知结论”和“不确定点”，不要用冗长措辞掩盖不确定性。
10. 回答应优先帮助用户继续当前工作，而不是展示面面俱到的解释。

### 场景规则

#### 字段 / 参数 / 返回值 / 配置项含义

- 默认只解释该字段或该组字段的作用。
- 优先回答：
  - 它表示什么
  - 什么时候有值 / 什么时候为空 / 默认值是什么
  - 前端、后端或调用方如何使用
- 除非用户要求，不主动展开到整个接口、整条链路或历史设计原因。

#### 接口 / Spec / Schema 理解

- 先说接口职责或 spec 结论。
- 再补充请求、响应、约束、状态码中与用户问题直接相关的部分。
- 不默认做全量字段讲解，除非用户要求“逐字段说明”。

#### 代码解释

- 先解释这段代码“做什么”和“为什么这样做”。
- 再说明关键输入、输出、副作用、状态变化。
- 不默认按行翻译代码；只解释影响理解的关键逻辑。
- 如果用户只问一行或一个函数，不主动扩展到整个文件。

#### Bug 排查 / 报错分析

- 先给最可能原因和定位方向。
- 再给必要证据、影响范围和下一步建议。
- 不默认列一长串低概率可能性；优先排序最可能的 1~3 个原因。

#### 方案设计 / 实现建议

- 先给推荐方案。
- 再说明为什么推荐、主要 tradeoff、是否有更简单替代。
- 除非用户要求，不默认给出多个平级方案的大而全比较。

#### 需求 / Spec 讨论

- 先归纳用户当前真正要确认的决策点。
- 再围绕该决策点回答影响实现的关键信息。
- 不把一个局部需求讨论扩展成完整需求文档，除非用户明确要求整理。

### 长度控制

- 简单问答：默认 2~5 句。
- 中等复杂度问题：默认 1 个短结论 + 3~6 个高相关点。
- 只有在以下情况才主动展开：
  - 用户明确要求“详细说”
  - 问题本身涉及多个状态流转或跨模块约束
  - 如果不展开会导致答案误导或不完整

### 例外规则

如果简短回答会导致错误理解、错误实现或遗漏关键风险，可以适当展开；但仍应先给短结论，再补必要说明，而不是直接展开成长篇回答。

## Commit Message Conventions

仓库默认使用 Conventional Commits 风格，首行格式为：

```text
<type>(<scope>): <subject>
```

规则：

- `type` 必填，使用英文小写；允许值：`feat`、`fix`、`refactor`、`docs`、`test`、`chore`、`ci`、`build`、`perf`、`style`、`revert`
- `scope` 可选，但本仓库建议尽量填写，优先使用业务域或基础设施域，例如 `auth`、`dataset`、`finetune`、`celery`、`db`、`docs`
- `subject` 必填，可以写中文；保持简洁，描述单一改动，不以句号或感叹号收尾
- 破坏性变更使用 `!`，例如 `feat(api)!: 调整导出接口协议`
- 自动生成的 `Merge ...`、`Revert "..."`、`fixup! ...`、`squash! ...` 提交信息允许保留

示例：

- `feat(finetune): 支持微调任务批量删除`
- `fix(auth): 修复 Redis 单点登录续期失效问题`
- `docs(readme): 补充文档分工说明`
- `chore(pre-commit): 增加 commit message 校验`

需要生成、改写或解释 commit message 时，优先查看 `.codex/skills/commit-message-conventions`。

### 枚举与 Schema 标签规则

- 枚举 `.label`、模块级 `_XXX_LABELS` 映射、以及响应 Schema 中的 `xxx_label` 自动填充规则，统一以 `.codex/skills/sqlmodel-alembic-postgres` 为准。
- 涉及 `app/models.py`、枚举返回值、列表/详情 Schema label 字段时，先查看该 skill，再决定是否需要同步调整相关 CRUD 或迁移。

### 注释规范

注释风格以 `datasets` 模块为基准，尤其参考 `app/services/dataset_service.py`、`app/api/routes/datasets.py`、`app/crud/dataset.py`、`app/schemas/dataset.py`、`app/models.py` 中数据集相关部分。目标是让后来维护的人沿着“入口 → 校验 → 编排 → 持久化 → 导出 / 回写状态”的路径快速看懂，不需要反复跳转和猜测。

**总原则：**

- 注释解释“这一段在保证什么 / 为什么不能省略 / 业务顺序为什么是这样”，不要把代码逐行翻译成中文
- 优先写短的中文分段注释，把复杂流程拆成 3~8 个阶段；不要给每一行都写注释
- 同一层使用稳定的注释颗粒度，新增模块时要和同层已有模块保持一致，不要一个文件极详细、另一个文件几乎没有说明

**按分层的写法要求：**

`app/api/routes/*.py`

- 文件顶部保留模块 docstring，例如“数据集管理路由”“微调指令任务路由”
- 每个端点必须有简洁 docstring
- 简单端点写一句话即可；复杂端点按 `datasets` 模块风格写 3~5 行说明，交代接口职责、关键筛选项、返回内容或调用后的副作用

`app/api/routes/options.py`

- 把同一业务域的 options 端点放在同一分组，并加分隔注释
- 每个端点都要有一句 docstring，说明这是哪个枚举 / 数据来源的下拉项
- 若选项并非数据库枚举，而是环境配置或动态来源，docstring 或紧邻注释要说明来源，例如“模型列表来自 settings / 环境变量”

`app/services/*.py`

- 复杂流程函数必须按步骤写 docstring + 分段注释，风格参考 `create_dataset_service()` / `process_import()`
- 复杂函数 docstring 至少交代三件事：此函数做什么、关键参数 / 调用上下文、函数步骤
- 典型写法：

```python
# 完整导入流程（由消费者调用）
# 参数: dataset_id / upload_id / skip_errors / session / redis
# 1. 获取上传会话信息
# 2. 遍历临时目录文件
# 3. 处理 ZIP、CSV、图片
# 4. 回写状态并清理资源
```

```python
# 1. 校验权限与前置状态
# 2. 解析请求并固定执行快照
# 3. 调用 CRUD / 入队 Celery
# 4. 回写状态并生成返回
```

- 涉及状态流转时，必须解释为什么要重置 `status`、`is_selected`、`validation_status`、`is_processing`、`stop_requested` 等字段
- “看起来像多余但其实不能删”的逻辑必须标明原因，例如重新导出选中结果、删除后兜底重选、任务重跑前清理旧结果、版本快照复用 / 重建
- 可以用分隔注释整理文件结构，例如“基础工具函数”“Route Service Layer”“后台任务执行”

`app/services/options_service.py`

- 每个 options service 函数至少写一句 docstring，说明返回的是哪类下拉项
- 若选项来自数据库查询，注释要说明筛选条件；若来自环境配置，注释要说明来源和为什么不落库
- 简单枚举映射可以不写分步注释，但涉及额外拼装、补充选项或动态来源时要补关键说明

`app/crud/*.py`

- 列表查询、聚合查询、批量查询必须有 docstring，说明筛选条件、返回值和查询目的
- 查询内部按 `dataset.py` 风格写关键步骤注释：权限过滤、状态过滤、时间范围修正、总数统计、排序分页、`selectinload` 预加载、批量聚合避免 N+1
- 简单的 `create/update/delete/get_by_id` 可以保持轻量，只写一句 docstring

`app/schemas/*.py`

- 文件顶部用分区注释组织结构，参考 `dataset.py` 的“API Request/Response Schemas”“标注相关”风格
- 请求 / 响应 / 列表项 / 详情项类应有清晰分组；复杂 Schema 写一句 docstring
- 含枚举标签填充的 Schema，继续通过 `xxx_label: str = ""` + `model_validator` 自动填充，并让注释能看出它属于列表还是详情响应

`app/core/consts/*.py`

- 常量文件保持轻量，但至少要让读者一眼看出该文件负责哪个业务域
- 命名空间类可用一句 docstring 说明用途；动态消息方法不需要额外注释，除非其语义不直观

`app/models.py`

- 保持按业务域的分隔注释，例如 `# ==================== Dataset ====================`
- 新增业务枚举前写一句用途注释，例如“任务状态枚举”“指令来源枚举”
- 对表结构中不直观的字段或关系，使用类级 docstring 或紧邻的短注释说明职责，例如“任务配置快照”“历史版本快照”“同图多候选指令”

`app/tasks/*.py`

- 文件顶部保留模块 docstring，例如“数据集导入 Celery 任务”“微调指令 Celery 任务”
- task helper 和 Celery task 函数都要有 docstring；复杂 task 的 docstring 同样要交代“做什么 / 关键参数 / 执行步骤”
- task 内部按 `dataset` 任务风格写关键步骤注释：初始化资源、参数转换、调用 async service、异常兜底、为何不重试
- 使用 `asyncio.run()`、Redis 初始化 / 关闭、分布式锁、UUID / Enum 参数转换等桥接逻辑时，必须说明其目的，避免后续维护时被误删

**必须加注释的场景：**

- Service / Task 中超过 20~30 行的复杂流程函数
- 涉及跨层业务约束的状态联动和回退
- 容易误解的兜底逻辑、兼容逻辑、顺序依赖、历史快照逻辑
- 批量查询、聚合查询、预加载关系、去 N+1 的数据库查询
- options 动态来源、Celery 桥接、环境配置驱动的逻辑

**可以不加注释的场景：**

- 简单字段映射、纯 CRUD 转发、命名已经足够清晰的一两行辅助函数
- 明显的语法性动作（如 `session.add(...)`、`return ...`）且没有额外业务语义

### API / CRUD 实施索引

- Router / Service / CRUD 分层、分页参数、Options 端点、响应模型、命名惯例、`__init__.py` 导出规范，统一以 `.codex/skills/fastapi-service-crud` 为准。
- 涉及 `app/api/routes/`、`app/services/`、`app/crud/`、`app/schemas/`、`app/services/options_service.py`、`app/api/routes/options.py` 的结构化修改时，优先按对应 skill 的 checklist 执行。

### 认证流程

- JWT + Redis 单点登录链路、当前用户依赖、滑动续期、登出失效等细节，统一以 `.codex/skills/auth-jwt-redis-session` 为准。
- 修改 `app/api/deps.py`、`app/services/auth_service.py`、登录路由或 `RedisKey.access_token(...)` 相关逻辑前，先查看该 skill。

### 业务常量与提示消息

所有跨 Router / Service / CRUD 复用的**业务语义常量**，统一放在 `app/core/consts/`，**按业务域拆文件**。

当前目录风格：

```python
app/core/consts/
├── auth.py          # AuthMsg, AuthTokenType, 其他 auth 常量
├── dataset.py       # DatasetMsg, DatasetLimit, DatasetField ...
├── file.py          # FileMsg
├── item.py          # ItemMsg
├── label.py         # LabelMsg, LabelImportConst ...
├── prompt_template.py
├── redis_keys.py    # RedisKey（跨域基础设施常量）
├── upload.py        # UploadErrorType, UploadMsg, 上传相关共享常量
├── user.py          # UserMsg
└── __init__.py      # 统一导出
```

这样组织更合理：

- 业务域边界更清晰，新增模块不需要频繁改一个超大文件
- 常量、动态拼接方法、业务类型值可以放在同一域文件里维护
- 后续模块增多时，冲突和查找成本更低

#### 常量书写规则

**1. 纯业务值常量：使用命名空间类属性，不使用 Enum**

适用于：

- 用户提示消息
- 业务类型值
- 状态判断字符串
- 字段名、导出列名、默认排序字段
- 跨层复用的数量/大小/名称限制

示例：

```python
class DatasetConst:
    __slots__ = ()

    MAX_EXPORT_ROWS = 1000
    DEFAULT_SORT_ORDER = "desc"
    CSV_IMAGE_COLUMN = "image"
```

**2. 动态拼接字符串：使用命名空间类上的 `@staticmethod`**

适用于：

- 带参数的用户提示消息
- 业务文案模板
- 动态文件名
- 动态缓存 key / topic / 标识符

示例：

```python
class DatasetMsg:
    __slots__ = ()

    NOT_FOUND = "数据集不存在"

    @staticmethod
    def permission_denied(action: str) -> str:
        return f"您没有权限{action}此数据集"
```

**3. 仅模块内部使用、且没有跨层复用价值的实现细节常量，可以留在本模块顶部**

例如：

- `_LABEL_IMPORT_TTL`
- `_CSV_MAX_ROWS`
- `_CODE_PATTERN`

这类常量不是业务共享语义，不强制放进 `app/core/consts/`。

#### 用户侧提示消息

所有 `api/routes/` 和 `services/` 中面向用户的提示文本（`HTTPException.detail`、`Message.message`、`error_message` 等）**必须使用 `app/core/consts/` 下对应业务域文件中的常量**，禁止硬编码字符串。日志消息（logger）不受此约束。

推荐命名：

| 类                       | 职责                                         |
| ------------------------ | -------------------------------------------- |
| `AuthMsg`                | 登录、Token、认证                            |
| `UserMsg`                | 用户管理                                     |
| `ItemMsg`                | Item CRUD                                    |
| `UploadMsg`              | 上传会话                                     |
| `DatasetMsg`             | 数据集操作                                   |
| `FileMsg`                | 文件处理（图片校验、ZIP、CSV、去重）         |
| `TemplateMsg`            | 提示词模板                                   |
| `LabelMsg`               | 标签管理                                     |
| `FinetuneInstructionMsg` | 微调指令任务、指令、校验、优化、扩增         |
| `TrainingMsg`            | 训练资源、基础模型、训练任务、通知与操作文案 |

**用法：**

- 静态消息 → 类变量：`detail=DatasetMsg.NOT_FOUND`
- 动态消息 → `@staticmethod` 方法：`detail=DatasetMsg.permission_denied("修改")`

**导入：** `from app.core.consts import DatasetMsg, FileMsg`

**导出规则：**

- 每个业务域常量文件在 `app/core/consts/__init__.py` 中统一导出
- 导入侧一律从 `app.core.consts` 导入，不直接从子文件深路径导入

**新增模块时：**

- 在 `app/core/consts/<domain>.py` 中新增对应的 `XxxMsg`、`XxxConst` 等
- 在 `app/core/consts/__init__.py` 中统一导出

### Celery 异步任务

- Celery 任务注册、`app/tasks/__init__.py` 显式导入、`.delay()` 生产者位置、Beat 调度、`asyncio.run()` 桥接和无 result backend 约束，统一以 `.codex/skills/celery-redis-worker` 为准。
- 新增或修改 `app/tasks/`、`app/core/celery_app.py`、service 层入队逻辑时，先查看该 skill。

### 微调指令模块约束

- 微调指令模块的业务真源在 `requirements/半自动化图文微调指令生成与校验模块.md`。
- 微调模块的代码改动边界、文件入口、状态联动注意点，统一以 `.codex/skills/finetune-instruction-workflows` 为准。
- 修改 `app/models.py` 中 `Finetune*` 类型、`app/services/finetune_instruction_service.py`、`app/services/finetune_instruction_algo_adapter.py`、`app/api/routes/finetune_tasks.py`、相关 options 端点或 Celery 任务前，先查看 requirement 和对应 skill。

### 视觉大模型训练模块约束

- 训练模块的业务真源在 `requirements/面向风险图片发现的视觉大模型优化训练.md`。
- 训练模块的代码改动边界、文件入口、状态联动注意点，统一以 `.codex/skills/vlm-training-workflows` 为准。
- 修改 `app/models.py` 中 `Training*` 类型、`app/schemas/training.py`、`app/crud/training.py`、`app/services/training_service.py`、`app/services/training_runtime.py`、`app/services/training_resource_collector.py`、`app/api/routes/training.py`、训练相关 options 端点或 `app/tasks/training.py` 前，先查看 requirement 和对应 skill。

### 大模型评测模块约束

- 评测模块的业务真源在 `requirements/大模型评估测试模块.md`。
- 评测模块的代码改动边界、共享资源调度和 runtime 占位规则，统一以 `.codex/skills/vlm-evaluation-workflows` 为准。
- 修改 `app/models.py` 中 `Evaluation*` 类型、`app/schemas/evaluation.py`、`app/crud/evaluation.py`、`app/services/evaluation_service.py`、`app/services/evaluation_runtime.py`、`app/api/routes/evaluation.py`、评测相关 options 端点或 `app/tasks/evaluation.py` 前，先查看 requirement 和对应 skill。

### Redis 集成

`RedisService` (`app/core/redis.py`) 提供：

- Key-Value（JSON 序列化）
- 分布式锁（Lua 脚本）
- Pipeline 批量操作

#### Redis Key 定义规范

Redis key **统一定义在** `app/core/consts/redis_keys.py`，使用“**命名空间常量类 + key builder 方法**”风格，**不要使用 Enum，也不要在业务代码中硬编码 Redis key 字符串**。

- 纯业务值常量（可同时用于 JWT、状态判断、其他业务语义）使用类属性，如 `AuthTokenType.ACCESS_TOKEN`
- 需要拼接动态参数的 Redis key 使用 `RedisKey.xxx(...)` 方法，如 `RedisKey.access_token(user_id)`
- 固定不带参数的 key 使用 `RedisKey` 类属性，如 `RedisKey.CLEANUP_EXPIRED_UPLOADS_LOCK`
- 禁止在 service/router/task 中定义局部 `_KEY_PREFIX`、`f"xxx:{id}"` 一类 Redis key 拼接逻辑

这种方式比 Enum 更适合当前仓库：

- Redis key 本质是字符串模板，不是有限枚举集合
- 很多 key 需要动态参数（`user_id`、`session_id`、`file_md5`），builder 方法比 Enum 更自然
- 同一套常量既能复用于 Redis key，也能复用于其他业务场景，避免把“业务类型”和“Redis key 前缀”混在一起

示例：

```python
class AuthTokenType:
    ACCESS_TOKEN = "access_token"
    REFRESH_TOKEN = "refresh_token"


class RedisKey:
    @staticmethod
    def access_token(user_id: uuid.UUID | str) -> str:
        return f"{AuthTokenType.ACCESS_TOKEN}:{user_id}"
```

#### Redis 临时会话模式

需要跨请求保持临时状态时（上传会话、导入预览等），统一使用 Redis 临时会话：

**Key 命名规范：** `{业务域}:{session_id}`

- 上传会话：`RedisKey.upload_session(upload_id)`、`RedisKey.upload_files(upload_id)`
- 模板上传：`RedisKey.pt_upload_session(session_id)`、`RedisKey.pt_upload_files(session_id)`
- 标签导入：`RedisKey.label_import(session_id)`

**session_id 生成规范：**

- 复杂会话（需临时目录）：带业务前缀 `f"{prefix}_{uuid.uuid4().hex}"`（如 `upload_xxx`、`pt_session_xxx`）
- 简单缓存（仅 Redis 数据）：纯 UUID `str(uuid.uuid4())`

**标准流程：**

1. 生成 session_id → `await redis.set(key, data, ttl=TTL)` 缓存数据
2. 返回 session_id 给前端
3. 后续请求携带 session_id → `await redis.get(key)` 取回数据
4. 操作完成后 → `await redis.delete(key)` 清理缓存
5. 未清理的 key 由 TTL 自动过期

**TTL 常量：** 在 Service 文件顶部定义为模块常量（如 `_LABEL_IMPORT_TTL = 1800`），或使用 `settings.UPLOAD_SESSION_TTL`

**Service 函数须声明为 `async`**（因为 `RedisService` 的方法都是 async），Router 端点也对应为 `async def`。

#### 两步操作模式（预览 + 确认）

当批量操作需要用户确认才能生效时，拆为两个接口：

| 步骤 | 接口                                  | 职责                                                                        |
| ---- | ------------------------------------- | --------------------------------------------------------------------------- |
| 预览 | `POST /{resource}/import-csv`         | 解析 + 校验，有效数据存 Redis，返回 `session_id` + 校验结果                 |
| 确认 | `POST /{resource}/import-csv/confirm` | 根据 `session_id` 从 Redis 取数据，**重新校验唯一性**后写库，删除 Redis key |

**关键规则：**

- 预览接口**不写数据库**，只读校验 + 缓存到 Redis
- 确认接口**必须重新校验**数据库唯一性（预览到确认期间可能有其他操作新增了数据）
- 确认接口执行完毕后**必须删除** Redis key（防止重复确认）
- session_id 不存在或过期 → HTTP 400 + `XxxMsg.IMPORT_SESSION_EXPIRED`

**Schema 约定：**

- `XxxPreviewResponse` — 包含 `session_id: str` + 校验结果
- `XxxConfirmRequest` — 包含 `session_id: str`
- `XxxConfirmResponse` — 包含 `success_count`、`fail_count`、`message`

### 新增业务模块

以添加 `project` 模块为例：

1. `app/models.py` — 新增枚举（`ProjectStatus` + `_PROJECT_STATUS_LABELS`）、`ProjectBase`、`Project`
2. `app/schemas/project.py` — 请求/响应 Schema（`ListItem` 含 `_fill_labels` validator）
3. `app/schemas/__init__.py` — 导出新 Schema
4. `app/crud/project.py` — 数据库操作
5. `app/crud/__init__.py` — 导出新 CRUD 函数
6. `app/services/project_service.py` — 业务逻辑
7. `app/services/options_service.py` — 新增枚举的下拉选项函数
8. `app/api/routes/projects.py` — 资源路由
9. `app/api/routes/options.py` — 新增枚举的 `/options/project-status` 端点
10. `app/api/main.py` — 注册路由
11. `app/core/consts/project.py` — 新增 `ProjectMsg` / `ProjectConst` 等业务常量 + `__init__.py` 导出
12. `alembic revision --autogenerate -m "add project table"` + `alembic upgrade head`

## Code Quality

- **MyPy strict** — 所有 `dict`、`list`、`tuple` 必须带类型参数（如 `dict[str, Any]`）
- **Ruff** — lint + format，禁止 `print`，禁止模糊变量名 `l`（用 `label`、`code` 等）
- **Pre-commit hooks** — 提交前强制检查；`commit-msg` hook 校验 Conventional Commits 格式
- **类型注解** — 全代码库必须添加
- UUID 主键 + UTC 时间戳贯穿所有模型
