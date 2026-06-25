---
name: finetune-instruction-workflows
description: Implement and modify this repository's finetune-instruction module, including task/version/instruction modeling, selection and validation rules, algorithm-adapter integration boundaries, environment-driven model providers, and Celery-based generation, optimization, and augmentation workflows. Use when changing app/models.py Finetune* types, app/schemas/finetune_instruction.py, app/crud/finetune_instruction.py, app/services/finetune_instruction_service.py, app/services/finetune_instruction_algo_adapter.py, app/services/finetune_instruction_client.py, app/api/routes/finetune_tasks.py, related options endpoints, or finetune Celery tasks and environment configuration.
---

# Finetune Instruction Workflows

Use this skill for repository-specific work on the semi-automated image-text finetune instruction generation and validation module.

## Source of Truth

- Business rules, state transitions, API-facing requirements, and TODO boundaries live in `requirements/半自动化图文微调指令生成与校验模块.md`.
- When the change involves dataset deletion, deleted-dataset historical task display, or deleted-dataset retry or restart limits, read `requirements/数据集删除与关联任务联动规则.md` first as the cross-module rule source.
- This skill defines how to implement or modify that module inside this repository without breaking the existing architecture.
- If requirement docs, historical algorithm examples, and current code disagree, follow the requirement doc first, then the current repository contract.

## Scope

Use this skill when changing any of these files or behaviors:

- `app/models.py` finetune task, config, version, and instruction types
- `app/schemas/finetune_instruction.py`
- `app/crud/finetune_instruction.py`
- `app/services/finetune_instruction_service.py`
- `app/services/finetune_instruction_algo_adapter.py`
- `app/services/finetune_instruction_client.py`
- `app/api/routes/finetune_tasks.py`
- finetune-related options endpoints
- `app/tasks/finetune_instruction_task.py`
- `FINETUNE_MODEL_PROVIDERS` wiring in env docs

## Workflow

1. Start from the requirement document.
If the change touches task state, validation semantics, output export, prompt-template usage, or API contract, read the relevant section in `requirements/半自动化图文微调指令生成与校验模块.md` first.

2. Trace the affected layer boundaries.
Identify whether the change belongs to model or schema shape, CRUD query behavior, service orchestration, algorithm-adapter protocol assembly, router contract, options exposure, or Celery execution.

3. Keep the business object centered on the task.
Generation, optimization, augmentation, selection, validation, and export all belong to `FinetuneInstructionTask`. Do not introduce image-level standalone flows that bypass the task.

4. Keep algorithm integration inside the adapter.
Model HTTP or algorithm protocol assembly belongs in `app/services/finetune_instruction_algo_adapter.py`, not in routers, generic services, or Celery entrypoints.

5. Preserve the repository's async boundary.
Long-running generation, optimization, and augmentation stay on Celery tasks. Keep the Celery edge synchronous and bridge async service logic with `asyncio.run()`.

6. Keep temporary artifacts inside the repository.
When you need temporary scripts, debug logs, API captures, or one-off regression helpers for this module, write them under `/home/RealAI/cert_phase2_backend/.tmp/` instead of `/tmp`. After verification, delete the temporary artifacts that are no longer needed.

## Implementation Boundaries

- Preserve version snapshots. Execution should use stored config snapshots such as `model_name` and `prompt_content_snapshot`; do not rebuild history from current prompt-template rows.
- Keep finetune task business codes aligned with the platform-wide daily sequence style. The current task code format is `FTK-YYYYMMDD-NNN`; do not introduce ad hoc prefixes such as `FIT` or other temporary variants.
- Keep single-instruction business codes distinct from task codes. `FinetuneInstruction.instruction_code` uses `INST-YYYYMMDD-NNN`, while `FinetuneInstructionTask.task_code` stays `FTK-YYYYMMDD-NNN`; do not swap or merge those two namespaces.
- Keep the dataset-to-task relationship one-to-many. One dataset may have multiple `FinetuneInstructionTask` rows, each representing a different instruction-generation experiment or adopted-result set.
- Keep the training-source boundary task-scoped. Downstream training must identify a concrete finetune task result set, not infer a training corpus from `dataset_id` alone.
- Keep the distinction between task-level history and task-internal history clear:
  - multiple finetune tasks may exist under the same dataset
  - one finetune task may also accumulate multiple historical versions after core-config reruns
- Keep prompt templates as snapshot-driven seed material. `prompt_template_name` and `prompt_template_id` remain display snapshots rather than finetune-table foreign-key dependencies, but `prompt_content` and copied reference-image few-shot snapshots may still be execution inputs.
- Keep prompt-template display snapshots on instruction rows too, not only on task config rows. Generated instructions should copy the current config snapshots; optimized instructions should overwrite their snapshots with the newly submitted template metadata; augmented instructions should inherit the seed instruction's snapshots.
- Keep prompt-template reference images and `model_reply` snapshots task-owned. When a finetune prompt template contains few-shot examples, copy those files into task-owned or version-owned or instruction-owned snapshot directories instead of depending on the live prompt-template image directory.
- Keep the few-shot transport contract explicit. The algorithm-side request should serialize each reference image from its snapshot file into an OpenAI-compatible `image_url` data URL, pair it with the matching `assistant` `model_reply`, and then append the final user turn for the current business image and prompt. The assembly order should stay easy to reason about:

```text
prompt template reference images
  -> copied into task/version/instruction-owned snapshot files
  -> persisted as [{filename, storage_path, model_reply}, ...]
  -> adapter passes reference_examples into app.algo.fine
  -> algorithm reads each storage_path file
  -> image bytes -> base64 -> data:{mime};base64,...
  -> messages +=
       user:   "参考样例N" + image_url(data URL of snapshot image)
       assistant: model_reply
  -> after all reference examples:
       user: current business prompt + current business image
  -> POST {base_url}/chat/completions
```

Minimal `messages` demo:

```json
[
  {
    "role": "user",
    "content": [
      {
        "type": "text",
        "text": "以下是参考样例1，请学习图像判定标准和期望回复方式。"
      },
      {
        "type": "image_url",
        "image_url": {
          "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
        }
      }
    ]
  },
  {
    "role": "assistant",
    "content": "{\"msg\":\"画面存在风险引导文案\",\"keyword\":[\"返现\",\"扫码\"],\"is_harmful\":true,\"cate\":\"fraud\"}"
  },
  {
    "role": "user",
    "content": [
      {
        "type": "text",
        "text": "请根据要求分析当前业务图片，返回单个 JSON 对象。"
      },
      {
        "type": "image_url",
        "image_url": {
          "url": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD..."
        }
      }
    ]
  }
]
```
- Keep prompt-template few-shot inheritance explicit across the three execution paths:
  - generation should use the current task-config reference-example snapshot
  - optimization should reuse the current instruction snapshot when the same template is retained, or build a new instruction-owned snapshot when a new live template is selected
  - augmentation should inherit the seed instruction's reference-example snapshot instead of re-reading the live template
- When instruction-level snapshot fields are introduced or repaired, keep old data readable. Prefer backfilling generated rows from matching task-config snapshots and augmented child rows from their parent instruction snapshots.
- Keep optimization request shape aligned with the latest requirement doc: one user-entered optimization-rule text plus a reconfiguration area for prompt-template reselection, edited prompt content, and model reselection. Do not reintroduce fixed optimization-rule enums as the primary contract.
- Keep optimization enqueue and execution payloads aligned. If optimization can reselect a prompt template, the request and Celery payload must carry `prompt_template_name` and `prompt_template_id` together with `model_name` and `prompt_content`.
- Keep optimization state display derived in the response layer. `optimization_status` should be computed from existing fields such as `is_processing`, `last_operation_error`, and `optimized_at`; do not add a dedicated persisted optimization-status field unless the requirement doc explicitly changes.
- Keep response contracts lean. Do not add derived display-only fields such as `display_text` or `config_display_text` when the frontend can already compose the text from `model_name`, `prompt_content`, and prompt-template snapshot fields.
- Keep generation, optimization, and augmentation on the real model-call path. Do not reintroduce `fake` or mock execution branches in the service, adapter, or algorithm modules unless the requirement doc explicitly adds that capability again.
- Keep invalid algorithm payloads out of successful finetune results. Structured-result parsing failures such as `parse_error=true`, non-object payloads, or missing core content must not be treated as valid generated or optimized or augmented instructions.
- Keep optimization fallback payloads out of success overwrites too. If the algorithm returns a fallback object carrying `optimize_error`, treat the optimization as failed and preserve the pre-optimize instruction row instead of overwriting it with a fake success.
- Keep execution prompt handling compatible with raw prompt snapshots. `prompt_content_snapshot` may be a long user-edited text block, not only a template name or file path; algorithm-side prompt resolution must safely fall back to raw text instead of assuming filesystem-path semantics.
- Keep generation-time output constraints enforced by the backend. Even if the submitted `prompt_content_snapshot` does not explicitly require JSON, the final prompt sent to the generation model should still append a backend-owned hard requirement that the reply must be a single JSON object containing `msg`, `keyword`, `is_harmful`, `cate`, and `image_path`.
- Keep task progress counters frontend-usable during long-running generation. `processed_count` should advance incrementally in batches while a model batch is still running, instead of only jumping after one full model configuration finishes.
- Keep the default generation progress batch small enough for large datasets. Unless one call path explicitly overrides it, the repository default save or progress interval should stay at `10` so Huawei-style long tasks do not remain at `0 / total_count` for too long.
- Keep task instruction visibility aligned with incremental progress. If the algorithm side has already checkpointed valid rows into `generated.json`, the backend may incrementally persist those rows before the whole model batch finishes so the task detail page can show partial results while status is still `running`.
- Keep incremental generated-result persistence idempotent. When syncing partially completed `generated.json` back into `FinetuneInstruction`, deduplicate by the current task execution scope such as task, config snapshot, image, source type, and current version to avoid duplicate rows from repeated file reads.
- Keep generation-failure visibility first-class. Image-level parse failures, model-returned `error` rows, and model-batch exceptions should be queryable through a dedicated task-scoped failure list instead of being left only in `task.errors` summary text.
- Keep generation-failure persistence aligned with task snapshots. Failure rows should carry the same task version and config snapshot context needed by the frontend list and by later debugging, instead of relying on reverse lookup from mutable current task config.
- Keep incremental failure persistence idempotent too. When syncing partially completed `generated.json` back into failure rows, deduplicate within the current task execution scope so repeated file reads do not duplicate the same failure detail.
- Keep terminated-task visibility and rerun cleanup compatible. A task stopped mid-generation may retain already persisted partial instructions for readback, but `start` or `retry` must still clear both raw algorithm outputs and previously persisted instructions before the next full rerun begins.
- Keep rerun cleanup symmetric for failures. `start` or `retry` must also clear previously persisted generation-failure rows before the next full rerun begins, otherwise old failure rows will leak into the new execution view.
- Keep task-action semantics aligned with the requirement doc. `start` is the generic submit or rerun entry for first launch, draft or pending submission, and resubmission after core-config edits; `retry` is the failure-only entry and should only accept failure states such as `half_failed`, `failed`, and `terminated`.
- Keep `half_failed` edit behavior explicit. That state still allows instruction-side follow-up work and core-config edits; if a core config change is saved, the task should fall back to `pending` before the next `start`.
- Keep copy-action gating aligned with the current requirement doc. Task copy is only available for `success`; do not leave copy open to `half_failed`, `draft`, `pending`, or `terminated` unless the requirement doc changes again.
- Keep the task-action matrix coherent as a whole: `running` is terminate-only, `linked` is frozen for core actions, `draft/pending` use `start`, `success` is the only copyable state, and `half_failed/failed/terminated` may rerun either by `retry` with unchanged config or by `start` after core-config edits move them back to `pending`.
- Keep task-version detail reads task-scoped. When exposing a single historical version detail API, query by both `task_id` and `version_id`; do not expose a version lookup that can cross task boundaries by `version_id` alone.
- Keep one-image-many-instructions but one selected result within the same task.
- Keep validation states aligned with the requirement doc. The current contract is three-state: `current_adopted`, `history_adopted`, `unadopted`.
- Keep `is_selected` as the current training-candidate marker. It is not redundant with `validation_status`: a row may be `is_selected=true` while still being `unadopted` before re-validation completes.
- When selection changes, the new selected row should reset to `unadopted`; previously validated rows that are replaced should become `history_adopted`.
- Manual validation should promote the final chosen row to `current_adopted`; non-selected siblings should fall back to `history_adopted` if they have validation history, otherwise `unadopted`.
- Optimization and manual edits invalidate previous confirmation. After either action, reset the affected row to `unadopted`.
- Keep augmentation request shape aligned with the latest requirement doc: one user-entered `dimension_description` text plus `count`. Do not reintroduce multi-select augmentation dimensions or `code / label / prompt` request structures unless the requirement doc changes again.
- Keep augmentation count limits aligned across schema, settings, and docs. The current repository contract is a single-seed augmentation upper bound of `20`, with the backend defaulted by `FINETUNE_MAX_AUGMENT_COUNT=20`.
- Keep augmentation result cardinality strict. If the backend requests `count=N`, the algorithm result must yield exactly `N` valid augmented rows; partial returns must be treated as a failed augmentation instead of being silently persisted as a smaller success set.
- Keep augmentation traceability explicit. Do not repurpose `prompt_content_snapshot` to store the augmentation dimension text; new augmented rows should keep the seed instruction's execution prompt snapshot, and the dimension text should be carried in raw-response trace data instead.
- Keep validation-detail navigation aligned with the task instruction list filters. `prev` or `next` ids in validation detail should be computed from the caller's current instruction-list filter set, not hardwired to the default re-validation list unless the caller explicitly requests that filter.
- Keep validation-candidate pagination focused on sibling comparison. The child candidates API for one instruction should exclude the current anchor instruction itself and return only the other same-image candidates, because the anchor context is already carried by the parent validation detail payload.
- Keep instruction-facing response contracts explicit about identifiers. Instruction list, detail, validation list, validation detail, and validation candidates should return both the row UUID `id` and the business code `instruction_code`; route path params such as `{instruction_id}` still use the UUID primary key.
- Optimization overwrites the original instruction row. Augmentation appends new rows and keeps the seed instruction.
- Selected-output export must stay derived from the current selected instructions only, and export is allowed only when every selected row is `current_adopted`.
- Keep `output_path` semantics narrow. It represents the task-scoped training export rebuilt from the current selected-and-confirmed instructions, not the raw algorithm `generated.json` intermediate output.
- `FINETUNE_MODEL_PROVIDERS` remains environment-driven. Do not add a database-backed model-provider table unless explicitly required.
- Keep provider display names and request model ids decoupled. `FinetuneModelProvider.name` remains the task-config and UI-facing identifier, while the actual model-service `model` field may come from a separate env-driven alias such as `api_model_name`.
- Keep provider exposure aligned with the local environment. If a model service is not actually available locally, do not leave that provider enabled in `FINETUNE_MODEL_PROVIDERS`.
- Dataset readiness checks and training-export readiness checks must remain enforced in the backend even if the frontend already filters options.
- Keep training-task linking first-class. Once a finetune task is referenced by downstream training, treat it as a linked data-source object whose core config and destructive actions remain constrained by the linked-state rules.
- Keep task-list downstream-usage visibility lightweight but explicit. When the frontend needs to show linked training usage, prefer returning a task-level aggregate together with a lightweight linked-task summary list such as `id`, `task_code`, and `name`, instead of forcing per-row detail lookups or embedding full training-task detail payloads.

## File Map

- `app/models.py`
  Task, config, version, and instruction persistence model.
- `app/schemas/finetune_instruction.py`
  Request and response contracts, filter fields, validation payloads, and options-facing schema types.
- `app/crud/finetune_instruction.py`
  Query helpers, paginated lists, version data loading, and instruction retrieval utilities.
- `app/services/finetune_instruction_service.py`
  Main business orchestration: task create or update or delete, generation lifecycle, selection, validation, export, and enqueueing.
- `app/services/finetune_instruction_algo_adapter.py`
  Adapter boundary to algorithm-side generation, optimization, and augmentation.
- `app/services/finetune_instruction_client.py`
  Environment-driven model configuration loading and validation helpers.
- `app/api/routes/finetune_tasks.py`
  HTTP contracts for task CRUD, task actions, task-version list or detail APIs, instruction operations, validation pages, and optimize or augment enqueue APIs.
- `app/tasks/finetune_instruction_task.py`
  Celery bridge for generation, optimization, and augmentation execution.

## Change Checklist

- Re-check whether the change affects status transitions, selection semantics, validation resets, or export invalidation.
- Re-check whether `start` and `retry` still have distinct state gates and semantics after the change.
- Re-check whether any version-facing API still keeps task scoping intact, especially single-version detail reads that should validate `task_id + version_id` together.
- Re-check whether frontend-facing validation status options, labels, counters, and default validation list queries still match the three-state semantics.
- Re-check whether task instruction list filters, detail navigation filters, and validation-detail navigation filters still use the same filter set, including `is_harmful` when that筛选 is exposed to the frontend.
- Re-check whether optimization and augmentation request contracts still match the latest requirement doc, especially free-text rule inputs, prompt-template snapshot handling, and model-selection fields.
- Re-check whether generation, optimization, and augmentation are all persisting or inheriting instruction-level prompt-template snapshots consistently enough for detail-page echo.
- Re-check whether any frontend-facing optimization-status field is still derived consistently from existing persistence fields, instead of drifting into duplicated stored state.
- Re-check whether the change affects adapter readiness checks for `generate`, `optimize`, and `augment`; keep those boundaries separate.
- Re-check whether prompt-template fields are still treated as display snapshots rather than execution dependencies.
- Re-check whether any temporary regression scripts or logs for this module are written under repo `.tmp/` rather than `/tmp`, and remove throwaway artifacts after verification.
- Re-check whether task artifact cleanup and output-path invalidation still happen when selected results or generation runs change.
- Re-check whether any change still preserves the task-scoped training-export contract: dataset alone is insufficient, and the selected export belongs to one concrete finetune task.
- Re-check whether task-list aggregate fields and linked training-task summaries, such as generation failure count, linked training-task count, and lightweight linked-task lists, are still computed in batch rather than via N+1 per-row queries.
- Re-check whether new finetune筛选条件 have matching `/api/v1/options/...` endpoints when the frontend depends on a dropdown instead of free text, especially for instruction source, validation status, and instruction safety.
- Re-check whether env docs need updates when model-provider behavior changes.
- Add or update tests for service, schema, CRUD, or adapter behavior when the contract changes.

## Pairing

Use this skill together with:

- `fastapi-service-crud` for route or service or CRUD shape
- `sqlmodel-alembic-postgres` for model and migration work
- `celery-redis-worker` for task execution changes

## Read Next

- Read `requirements/半自动化图文微调指令生成与校验模块.md` for the business source of truth.
- Read [module-map-and-rules.md](/home/RealAI/cert_phase2_backend/.codex/skills/finetune-instruction-workflows/references/module-map-and-rules.md) for the detailed file map, review rules, environment wiring, and Celery entry points.
