---
name: requirement-to-llm-prompt
description: Convert raw business requirements, feature ideas, bug reports, review requests, questions, and implementation asks into either structured prompts or formal requirement markdown. Use when the input comes from ad hoc chat messages, a chat-based task list, or a markdown requirement document such as `xxx需求.md`, and Codex needs to normalize it into a model-ready prompt package or rewrite it into a repository-friendly `requirements/*.md` document.
---

# Requirement To LLM Prompt

Use this skill to normalize a raw requirement into one of two outputs:

- `normalize-to-prompt`: convert the input into a prompt package that another model can execute with less ambiguity and fewer follow-up questions
- `rewrite-to-requirement-md`: rewrite the input into a structured markdown requirement document suitable for `requirements/*.md`

Default to `normalize-to-prompt` unless the user explicitly asks to generate, rewrite, or update a formal requirement document.

This single skill should cover these three user patterns:

- small asks in chat, such as bug fixes, capability questions, flowchart generation, or one-off requirement cleanup
- medium asks where the user lists feature 1, feature 2, feature 3 directly in chat
- large asks where the user points Codex to a markdown requirement document and expects implementation from that file

## Workflow

1. Identify the delivery target and output mode.
Classify the request as implementation, debugging, code review, design, documentation, flowcharting, capability explanation, testing, generic prompt drafting, or requirement-document rewriting.

Pick the output mode explicitly:
- `normalize-to-prompt`: default for execution, planning, debugging, review, testing, and general requirement bridging
- `rewrite-to-requirement-md`: use when the user wants a formal markdown requirement document, especially for `requirements/*.md`

2. Identify the input source.
Distinguish between:
- direct chat request
- chat-based task list
- markdown file such as `docs/xxx需求.md` or `requirements/xxx需求.md`

Prefer the original source over a paraphrase. If a file is named, read that file first.

3. Separate confirmed facts from inferred context.
Keep user-stated constraints as hard requirements. Infer extra context only from local artifacts such as `AGENTS.md`, `README.md`, existing code, or active repository skills. Do not invent business rules or architecture.

4. Shape the output according to the chosen mode.

For `normalize-to-prompt`, rewrite the request into a compact execution structure:
- Goal
- Input source
- Current context
- In scope
- Out of scope
- Hard constraints
- Expected output
- Validation or acceptance checks
- Open questions or bounded assumptions

For `rewrite-to-requirement-md`, rewrite the request into a concise business requirement structure:
- Background
- Goal
- In scope
- Out of scope
- Key workflow or main scenarios
- State transitions or business rules when relevant
- Constraints
- Acceptance criteria
- Open questions or pending confirmation

5. Decide whether the task should go direct or plan-first.
Make the split explicit instead of leaving it implicit:
- direct execution: use when the ask is localized, low-risk, bounded to one clear outcome, and does not need phase breakdown before acting
- plan-first execution: use when the ask spans multiple modules, has ambiguous sequencing, carries migration or compatibility risk, or contains several sub-deliverables that should be ordered before implementation

If the user explicitly asks for a plan, always use a plan-first prompt. If the user explicitly says not to spend time on planning and the task is still safe to execute directly, use the direct path.

This step only applies to `normalize-to-prompt`. For `rewrite-to-requirement-md`, do not force direct-vs-plan wording into the final requirement document.

6. Pick the template shape that matches the task.
Use the templates in [prompt-templates-and-checklist.md](/home/RealAI/cert_phase2_backend/.codex/skills/requirement-to-llm-prompt/references/prompt-templates-and-checklist.md) instead of writing every output from scratch.

7. Make the output operational.

For `normalize-to-prompt`, use imperative instructions, concrete identifiers, explicit deliverables, and observable success criteria. Prefer “update `app/services/foo.py` and add tests” over vague directions such as “improve the backend”.

For `rewrite-to-requirement-md`, keep the document business-facing and stable. Do not turn the requirement doc into an implementation checklist unless the user explicitly wants that. Preserve decisions, boundaries, and acceptance conditions rather than coding steps.

8. Preserve source terminology.
Keep code identifiers, enum values, API paths, filenames, and domain terms verbatim. Translate only the surrounding explanation when it improves clarity.

9. Surface uncertainty deliberately.
If the request is blocked by missing information, produce a short clarification block first. If the task can proceed safely, state the assumptions explicitly and continue.

## Output Rules

- Prefer a structured output package over free-form prose.
- Put non-negotiable constraints before optional suggestions.
- Distinguish user facts from model assumptions.
- Keep prompts concise; remove motivational filler and generic reasoning instructions unless the user explicitly asks for them.
- When the request targets this repository, mention only the repository conventions that materially constrain the work.
- Default to `normalize-to-prompt` unless the user explicitly asks for a formal markdown requirement document.
- Never overwrite `requirements/*.md` unless the user explicitly asks to write or update that file.
- When producing `rewrite-to-requirement-md`, keep the content suitable as a business source of truth. Do not silently add speculative business rules or low-level implementation details.
- For implementation asks in `normalize-to-prompt`, explicitly state whether the prompt is `direct execution` or `plan-first execution`.

Use this default output shape for `normalize-to-prompt` unless a task-specific template fits better:

```text
任务目标:
输入来源:
上下文:
范围:
硬性约束:
期望产出:
验收标准:
假设与待确认:
```

Use this default output shape for `rewrite-to-requirement-md` unless a task-specific template fits better:

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

## Pairing With Existing Skills

Do not treat other skills as hard runtime dependencies for this skill. This skill should perform the normalization step on its own, then suggest or trigger repository-specific skills when the rewritten prompt clearly points to their domain.

If the user is asking for coding work, include likely code layers or file groups in the rewritten prompt and attach the relevant repository skills. If the user is only asking a question, requesting a flowchart, or asking what the system can do, do not force coding-specific routing.

When the user wants to formalize raw notes into `requirements/*.md`, use `rewrite-to-requirement-md` first. After that document is confirmed, use the resulting requirement file as the business source of truth for implementation, review, and testing.

Pair with these repository skills when relevant:

- `fastapi-service-crud` for router, service, CRUD, schema, pagination, options, and message-constant changes
- `sqlmodel-alembic-postgres` for `app/models.py`, SQLModel queries, or Alembic migrations
- `auth-jwt-redis-session` for login, token parsing, Redis session validation, or auth dependencies
- `celery-redis-worker` for task definitions, queueing, or beat scheduling
- `security-review-fastapi` when the normalized task is a code review or risk assessment
- `finetune-instruction-workflows` for the finetune instruction task/version/instruction domain

## Read Next

Read [prompt-templates-and-checklist.md](/home/RealAI/cert_phase2_backend/.codex/skills/requirement-to-llm-prompt/references/prompt-templates-and-checklist.md) when you need ready-to-use prompt skeletons, extraction checklists, markdown-file and chat-task-list templates, or repository skill routing hints.
