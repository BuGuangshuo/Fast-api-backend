# Prompt Templates And Checklist

Use this reference when the raw requirement has already been identified and you need a concrete prompt shape.

## Mode Selection

Choose the mode before drafting the final output:

- `normalize-to-prompt`: default mode for implementation, debugging, testing, review, plan-first decomposition, and model execution
- `rewrite-to-requirement-md`: use when the user explicitly wants a formal requirement markdown document, especially a file under `requirements/*.md`

For this repository, prefer this content flow:

1. Raw chat notes or temporary markdown
2. `rewrite-to-requirement-md` to form a stable `requirements/*.md`
3. `normalize-to-prompt` when that requirement file later needs to drive implementation, review, or testing

## Extraction Checklist

Before drafting the prompt, extract these fields from the raw requirement:

- What is the input source: direct chat, chat task list, or markdown file?
- What is the end result?
- What artifact should be changed or produced?
- What context is already known from the repo or conversation?
- What is explicitly in scope?
- What is explicitly out of scope?
- What hard constraints cannot be violated?
- What evidence will prove the task is complete?
- What assumptions are being made because the user did not specify them?
- Should this be handled as direct execution or plan-first execution?
- Is the user asking for an executable prompt or a formal requirement markdown document?

If more than two critical fields are unknown and the task is high risk, ask clarifying questions before drafting the final prompt.

Use this explicit split for implementation tasks in `normalize-to-prompt` mode:

- direct execution: single feature or bug fix, bounded file/module impact, low ambiguity, low rollback risk, no need to coordinate multiple stages before coding
- plan-first execution: multiple sub-features, cross-module refactor, migration or data-shape impact, externally coupled behavior, or any task where the implementation order itself materially affects correctness

## Base Prompt Template

```text
请基于以下信息执行任务，不要擅自扩展范围。

任务目标:
{goal}

输入来源:
{source}

当前上下文:
{context}

本次范围:
{scope}

明确排除项:
{out_of_scope}

硬性约束:
{constraints}

期望产出:
{deliverables}

验收标准:
{acceptance_checks}

已知假设 / 待确认项:
{assumptions_or_questions}
```

## Implementation Prompt Template

Use this for simple or bounded code changes that do not need an explicit implementation plan first.

```text
请在当前代码库中实现以下需求，并直接完成必要修改。

执行模式:
- direct execution

需求目标:
{goal}

相关上下文:
{context}

建议关注的文件或模块:
{files_or_modules}

本次必须完成:
{required_changes}

不要做:
{out_of_scope}

必须遵守的约束:
{constraints}

完成标准:
{acceptance_checks}

输出要求:
- 先实现再说明
- 最后简要说明改动结果、验证情况、剩余风险
```

## Complex Implementation / Plan-First Template

Use this for complex implementation asks that should first be decomposed into an execution plan before coding.

```text
请先基于以下信息整理一个可执行计划，再按计划完成实现。不要跳过关键风险判断，也不要在范围未整理清楚时直接大面积修改。

执行模式:
- plan-first execution

需求目标:
{goal}

相关上下文:
{context}

建议关注的文件或模块:
{files_or_modules}

本次必须完成:
{required_changes}

不要做:
{out_of_scope}

必须遵守的约束:
{constraints}

先输出:
- 简要任务拆分
- 推荐执行顺序
- 关键风险或依赖点
- 需要确认的阻塞问题（如无则明确写无）

确认计划后或在无阻塞前提下继续完成实现，并满足以下完成标准:
{acceptance_checks}

最终输出要求:
- 先给计划摘要
- 再说明实际完成的修改
- 最后说明验证情况、剩余风险
```

## Markdown Requirement File Template

Use this when the user points Codex to a specific file such as `docs/xxx需求.md`.

```text
请先读取 `{requirement_file}`，基于文档中的已确认需求执行任务，不要忽略范围边界和验收条件。

任务目标:
{goal}

输入来源:
- 需求文档: `{requirement_file}`

当前上下文:
{context}

本次范围:
{scope}

明确排除项:
{out_of_scope}

建议关注的文件或模块:
{files_or_modules}

必须遵守的约束:
{constraints}

建议使用的 skills:
{skills}

完成标准:
{acceptance_checks}

已知假设 / 待确认项:
{assumptions_or_questions}
```

## Requirement Markdown Rewrite Template

Use this when the user wants Codex to rewrite raw notes, chat requirements, or an unstructured markdown file into a formal requirement document, especially under `requirements/*.md`.

```text
请基于以下原始需求整理一份正式的业务需求文档，输出为可直接写入 `{target_requirement_file}` 的 markdown。不要擅自补充未确认的业务规则，也不要把文档写成实现方案。

输出模式:
- rewrite-to-requirement-md

输入来源:
{source}

文档目标:
{goal}

已有上下文:
{context}

必须保留的事实:
{must_keep}

禁止擅自扩展的部分:
{out_of_scope}

必须遵守的约束:
{constraints}

输出要求:
- 使用稳定、清晰的 markdown 标题结构
- 优先写业务目标、范围、流程、约束、验收标准
- 明确区分已确认内容与待确认项
- 如涉及状态变化，单独写“状态流转 / 业务规则”
- 不默认写代码实现步骤、数据库设计或接口改造方案
```

Recommended markdown structure:

```text
# {需求标题}

## 背景

## 目标

## 本次范围

## 非范围

## 关键流程 / 主要场景

## 状态流转 / 业务规则

## 约束

## 验收标准

## 待确认项
```

## Chat Task List Template

Use this when the user lists feature 1, feature 2, feature 3 directly in chat.

```text
请基于当前对话中的任务清单执行任务。先整理实现范围，再开始工作。

任务目标:
{goal}

输入来源:
- 当前对话中的需求清单

已整理的任务项:
{normalized_tasks}

当前上下文:
{context}

本次范围:
{scope}

明确排除项:
{out_of_scope}

建议关注的文件或模块:
{files_or_modules}

必须遵守的约束:
{constraints}

建议使用的 skills:
{skills}

完成标准:
{acceptance_checks}

已知假设 / 待确认项:
{assumptions_or_questions}
```

## Debugging Prompt Template

Use this when the user describes a failure, error, or regression.

```text
请定位并修复以下问题，先收集证据再修改代码，不要凭空假设根因。

问题表现:
{symptoms}

复现线索:
{repro_steps}

已知上下文:
{context}

优先排查范围:
{suspected_area}

约束:
{constraints}

完成标准:
- 找到可解释问题现象的根因
- 完成必要修复
- 说明如何验证修复
```

## Review Prompt Template

Use this when the user asks for a review or risk assessment.

```text
请对以下改动做代码审查，重点找出缺陷、行为回归、风险点和缺失测试。

审查对象:
{review_scope}

业务上下文:
{context}

重点关注:
{focus_areas}

输出要求:
- 先给 findings，按严重程度排序
- 每条包含文件定位、问题原因、影响
- 如果没有发现问题，明确说明并指出剩余测试风险
```

## Design Prompt Template

Use this when the user is asking for方案设计 rather than direct edits.

```text
请基于以下约束给出一个可落地的实现方案，不要过度设计。

设计目标:
{goal}

现有上下文:
{context}

约束:
{constraints}

需要回答:
{questions_to_answer}

输出要求:
- 先给推荐方案
- 说明为什么这样取舍
- 标出风险、边界条件、后续工作
```

## Capability Question Template

Use this when the user is asking what the system can do, whether a feature exists, or what is currently supported.

```text
请基于当前代码库和已知上下文回答以下能力问题。先确认现状，再说明结论，不要把未实现能力说成已支持。

问题:
{question}

输入来源:
{source}

相关上下文:
{context}

输出要求:
- 明确区分“已支持”“部分支持”“未支持”
- 如果需要，指出相关模块、接口或限制条件
- 如果用户下一步可能要实现该能力，补一个简短建议
```

## Flowchart Template

Use this when the user wants a process or feature flowchart.

```text
请基于以下需求整理流程，并输出 Mermaid 流程图。

流程主题:
{goal}

输入来源:
{source}

当前上下文:
{context}

关键步骤:
{steps}

约束或分支条件:
{constraints}

输出要求:
- 先给简短文字说明
- 再给 Mermaid 流程图
- 不凭空补不存在的业务分支
```

## Repository Skill Routing Hints

When the normalized prompt targets this repository, attach only the skills that materially match the task:

- Router, service, schema, CRUD, options, pagination: `fastapi-service-crud`
- SQLModel model or migration changes: `sqlmodel-alembic-postgres`
- JWT, Redis session, current user dependency: `auth-jwt-redis-session`
- Celery task, `.delay()`, beat schedule: `celery-redis-worker`
- Local startup, tests, and lint: use the commands documented in `README.md` and `AGENTS.md`
- Security-focused review: `security-review-fastapi`
- Finetune instruction module: `finetune-instruction-workflows`

Do not attach unrelated skills just because they are available.

## Example

Raw requirement:

```text
帮我把“新增项目接口”这个需求整理成适合 Codex 干活的提示词，要求符合这个仓库的 router/service/crud 分层，还要补 options。
```

Normalized prompt:

```text
请在当前 FastAPI 仓库中实现“项目管理”基础接口，遵循现有 router -> service -> CRUD 分层，不要跳过 schema、consts 和 options 接口。

任务目标:
新增 project 业务模块的基础 CRUD 能力，并补齐前端下拉所需的状态 options。

当前上下文:
- 仓库使用 FastAPI + SQLModel + PostgreSQL
- API 风格要求遵循现有 datasets 模块
- 用户侧提示文本需要放在 app/core/consts/<domain>.py

本次范围:
- 新增模型、schemas、crud、service、router、consts
- 注册路由
- 暴露 /options/project-status

明确排除项:
- 不要引入新的分布式架构
- 不要额外设计训练模块或消息总线

硬性约束:
- 遵循分页、枚举 label、message 常量、注释风格约定
- Router 保持薄层，业务逻辑放 service
- 列表查询返回 tuple[list[T], int]

期望产出:
- 直接完成代码修改
- 必要时补 migration
- 最后说明改动点和验证情况

验收标准:
- 接口结构与现有模块风格一致
- options 接口可返回状态枚举下拉
- 没有硬编码用户提示文案

已知假设 / 待确认项:
- 若字段定义未明确，可先按最小可用项目实体设计，并在说明中列出假设
```
