---
name: commit-message-conventions
description: Write, rewrite, review, and validate repository commit messages using the Conventional Commits format adopted by this repository. Use when the user asks for a commit message, wants help splitting changes into commits, wants a commit title for staged changes, or needs an explanation of the repository's commit message policy.
---

# Commit Message Conventions

Use this skill when the task is about commit messages rather than code behavior.

## Source of Truth

- Repository-wide commit message rules live in `AGENTS.md` under `Commit Message Conventions`.
- Local validation is enforced by `hooks/validate_commit_msg.py` through the `commit-msg` pre-commit hook.

## Format

Use Conventional Commits for the first line:

```text
<type>(<scope>): <subject>
```

`scope` is optional, but recommend it whenever the change clearly belongs to one module or subsystem.

## Allowed Types

- `feat` for new functionality
- `fix` for bug fixes
- `refactor` for internal restructuring without intended behavior change
- `docs` for documentation
- `test` for tests
- `chore` for repository maintenance
- `ci` for CI/CD pipeline changes
- `build` for dependency, packaging, image, or build-system changes
- `perf` for performance improvements
- `style` for formatting-only changes
- `revert` for reverting a previous change

## Scope Guidance

Prefer repository domain or infrastructure scopes such as:

- `auth`
- `user`
- `dataset`
- `label`
- `upload`
- `prompt-template`
- `finetune`
- `celery`
- `redis`
- `db`
- `api`
- `docs`
- `ci`
- `pre-commit`
- `deps`

If a change clearly spans multiple domains, either omit `scope` or recommend splitting the work into multiple commits.

## Subject Rules

- The subject may be Chinese or English.
- Keep it concise and action-oriented.
- Describe one logical change only.
- Do not end the subject with `.`, `。`, `!`, `！`, `?`, or `？`.
- Use `!` after `type` or `scope` for breaking changes, for example `feat(api)!: 调整导出接口协议`.

## Workflow

1. Identify the primary change.
Choose the dominant intent before writing the message. Do not default everything to `chore`.

2. Pick the narrowest useful scope.
Use the module or subsystem that best matches the change. If the change is cross-cutting, consider whether it should be split.

3. Write the subject from the user-facing or maintainer-facing outcome.
Prefer concrete summaries such as `支持微调任务批量删除` over vague summaries like `调整代码`.

4. Keep one commit message per one logical change.
If the staged diff mixes unrelated work, say so and propose a split instead of forcing an overloaded subject.

## When Reviewing

- Reject messages that do not follow the repository format.
- Suggest a better `type` if the chosen one does not match the actual change.
- Suggest splitting commits when a single message has to describe unrelated work.

## Examples

- `feat(finetune): 支持微调任务批量删除`
- `fix(auth): 修复 Redis 单点登录续期失效问题`
- `refactor(dataset): 拆分导入状态回写逻辑`
- `docs(readme): 补充文档分工说明`
- `chore(pre-commit): 增加 commit message 校验`

## Read Next

- Read `AGENTS.md` for the repository-wide wording of the policy.
- Read `hooks/validate_commit_msg.py` for the exact local validation rules.
