# Test Fast API

基于原 `cert_phase2_backend` 技术栈搭建的 FastAPI 后端骨架项目。当前只保留基础框架、目录约定、运行配置、内置 Codex skills 和最小健康检查接口，不包含业务功能实现。

## 技术栈

| 组件       | 技术                      |
| ---------- | ------------------------- |
| Web 框架   | FastAPI + Uvicorn         |
| ORM        | SQLModel (SQLAlchemy 2.x) |
| 数据库     | PostgreSQL 17             |
| 缓存/会话  | Redis 8                   |
| 异步任务   | Celery + Redis Broker     |
| 任务调度   | Celery Beat               |
| 任务监控   | Flower                    |
| 数据库迁移 | Alembic                   |
| 配置管理   | pydantic-settings         |
| 代码规范   | Ruff + MyPy strict        |
| 包管理     | uv                        |

## 项目结构

```text
.
├── AGENTS.md
├── README.md
├── .codex/skills/
├── app/
│   ├── api/routes/          # Router 层
│   ├── core/                # 配置、DB、Redis、Celery
│   ├── crud/                # CRUD 层占位
│   ├── schemas/             # Pydantic / SQLModel Schema
│   ├── services/            # Service 层
│   ├── tasks/               # Celery task
│   ├── alembic/             # Alembic 迁移目录
│   └── main.py              # FastAPI 入口
├── scripts/
├── hooks/
└── tests/
```

## 启动

```bash
uv sync --dev
bash ./scripts/start-all.sh
```

启动前需先在本机准备 PostgreSQL 和 Redis，默认连接信息见 `.env.example`：

- PostgreSQL: `localhost:5433`
- Redis: `localhost:6380`

## 常用命令

```bash
bash ./scripts/start-all.sh
bash ./scripts/test.sh
bash ./scripts/lint.sh
bash ./scripts/format.sh
alembic revision --autogenerate -m "description"
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8083
celery -A app.core.celery_app:celery_app worker --loglevel=info --concurrency=1 --pool=prefork
celery -A app.core.celery_app:celery_app beat --loglevel=info
celery -A app.core.celery_app:celery_app flower --port=5555
```

## 当前接口

- `GET /api/v1/utils/health-check/`
- `GET /api/v1/options/framework`
- `POST /api/v1/test-redis/cache/set`
- `GET /api/v1/test-redis/cache/get/{key}`
- `DELETE /api/v1/test-redis/cache/delete/{key}`
- `POST /api/v1/ai/chat/stream`
- `GET /api/v1/ai/chat/generations/{generation_id}`
- `GET /api/v1/ai/chat/generations/{generation_id}/stream`
- `GET /api/v1/ai/chat/conversations/{conversation_id}/generation`
- `GET /api/v1/ai/chat/sessions/{session_id}`
- `DELETE /api/v1/ai/chat/sessions/{session_id}`

## AI 对话服务

前端通过后端接口 `POST /api/v1/ai/chat/stream` 进行 SSE 流式对话；后端代理 OpenAI-compatible 服务，默认地址为 `http://127.0.0.1:1104/v1`，默认模型为 `Qwen3.5-9B-MLX-4bit`，启动时直接读取配置中的 `LLM_API_KEY` 和 `LLM_CHAT_MODEL`。

需要浏览器刷新后继续显示生成过程时，请在请求中传 `resumable=true`。后端会返回 `generation` 事件并由 Celery 在后台继续生成；前端重新进入会话后，可先按 `conversation_id` 查询 generation 快照，再使用当前 `reasoning_content` / `content` 字符长度作为 `reasoningOffset` / `contentOffset` 重新订阅 SSE。

## Codex 约束

仓库保留了原项目的 `AGENTS.md` 和 `.codex/skills/`，用于后续新增业务模块时继续沿用 Router → Service → CRUD、SQLModel + Alembic、Celery + Redis、本地开发等约定。
