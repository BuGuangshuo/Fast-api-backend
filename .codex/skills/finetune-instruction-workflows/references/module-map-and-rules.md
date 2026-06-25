# Finetune Instruction Module Map And Rules

## File Map

- `app/models.py`
  Defines `FinetuneTaskStatus`, `FinetuneInstructionSource`, `FinetuneValidationStatus`, `FinetuneOptimizationRule`, `FinetuneInstructionTask`, `FinetuneInstructionTaskConfig`, `FinetuneInstructionTaskVersion`, `FinetuneInstructionTaskVersionConfig`, and `FinetuneInstruction`.
- `app/schemas/finetune_instruction.py`
  Defines API request and response schemas plus `FinetuneModelProvider` for environment-driven model config parsing.
- `app/crud/finetune_instruction.py`
  Contains pure database operations for task lookup, version creation, instruction selection, review queries, and pagination.
- `app/services/finetune_instruction_service.py`
  Owns task state transitions, version snapshot creation, selected-instruction export, manual validation, and Celery enqueueing.
- `app/services/finetune_instruction_algo_adapter.py`
  Owns generation, optimization, and augmentation adapter wiring, including business-line-specific readiness checks and request assembly for `app.algo.fine`.
- `app/services/finetune_instruction_client.py`
  Calls OpenAI-compatible external model services through `POST {base_url}/chat/completions`.
- `app/api/routes/finetune_tasks.py`
  Exposes task CRUD, task actions, instruction CRUD, validation endpoints, and optimization or augmentation enqueue endpoints.
- `app/tasks/finetune_instruction_task.py`
  Registers Celery tasks for generation, optimization, and augmentation.
- `app/core/consts/finetune_instruction.py`
  Stores all user-facing messages for this module.
- `app/services/options_service.py` and `app/api/routes/options.py`
  Expose finetune task status, model, instruction source, validation status, instruction safety, dataset, and prompt-template-related options. Optimization rules are free-text input and should not depend on a fixed enum options endpoint.

## State Model

If algorithm-side code or historical examples disagree with the latest repository business requirement docs, the repository business requirement docs and current backend contracts are authoritative.

### Task statuses

- `draft`: saved as draft and not ready to run yet.
- `pending`: configuration is ready and may be started.
- `running`: generation is executing asynchronously.
- `success`: generation finished and selected output can be exported.
- `half_failed`: generation produced usable output, but one or more model batches failed.
- `failed`: generation finished without usable output or hit unrecoverable errors.
- `linked`: selected output is associated with downstream training and core config is locked.
- `terminated`: running task was manually stopped.

### Task action matrix

| Status | Allowed task actions | Notes |
| --- | --- | --- |
| `draft` | `update`, `start`, `delete` | Initial submit path uses `start` |
| `pending` | `update`, `start`, `delete` | Ready-to-run state |
| `running` | `terminate` | No edit, copy, delete, start, or retry while executing |
| `success` | `copy`, `update`, `start`, `delete` | Regeneration after edits still uses `start` |
| `half_failed` | `update`, `start`, `retry`, `delete` | `retry` is for unchanged config; core edits should move back to `pending` before `start` |
| `failed` | `update`, `start`, `retry`, `delete` | Same rerun split as `half_failed` |
| `terminated` | `update`, `start`, `retry`, `delete` | Same rerun split as `half_failed` |
| `linked` | limited `update` only | Non-core fields may change, but no copy, rerun, terminate, or delete |

### Instruction source types

- `generated`: created by the base generation flow.
- `augmented`: created from a seed instruction.
- `optimized`: existing instruction text was rewritten by a model.
- `manual`: human-edited or human-validated final content.

### Validation statuses

- `pending`: the currently selected training instruction has not been manually labeled yet.
- `verified`: the currently selected training instruction has a final manual harmful or harmless label.

## Core Business Rules

1. A task is the only valid root object for this workflow.
2. A single image may have multiple instructions within one task.
3. Only one instruction per image may be selected at a time.
4. Manual validation decides the final harmful or harmless label for the selected training instruction.
5. Version snapshots are authoritative historical inputs.
6. Exported training output must be built from selected instructions only.
7. Long-running generation, optimization, and augmentation must run in Celery.
8. Generation should tolerate model-level or image-level partial failures and keep any valid candidates that were already produced.
9. Deleting a task is a physical delete. Remove the task row, cascade child rows, and clean task artifact directories before deleting from the database.

## Versioning Rules

- Core config is stored as ordered task config rows and version config rows. Each row contains `model_name` and `prompt_content_snapshot`.
- Prompt templates are only used by the frontend to seed editable prompt text before submission. Finetune task config, version config, and instruction rows may keep `prompt_template_name` and `prompt_template_id` as display snapshots, but they must not persist prompt-template foreign keys as historical dependencies.
- Finetune task create or edit requests should submit the final `prompt_content` together with `prompt_template_name` and `prompt_template_id` display snapshots for each config item. Optimization requests should now submit one user-entered optimization-rule text together with reconfiguration fields for prompt-template reselection, final edited prompt content, new model selection, plus the new `prompt_template_name` and `prompt_template_id` display snapshots that should be written back onto the optimized instruction row. Augmentation requests submit only one `dimension_description` text plus `count`, use that description as the actual augmentation prompt, and reuse the seed instruction's model configuration and template snapshots. If a template contains reference images, persist their copied snapshot paths together with `model_reply`, and pass them to the algorithm as few-shot turns with this exact assembly shape:

```text
reference_examples snapshot list
  = [{filename, storage_path, model_reply}, ...]

for each example in order:
  1. read snapshot file from storage_path
  2. detect mime type
  3. encode image bytes as base64
  4. build one OpenAI-compatible user turn:
     {
       "role": "user",
       "content": [
         {"type": "text", "text": "以下是参考样例N，请学习图像判定标准和期望回复方式。"},
         {"type": "image_url", "image_url": {"url": "data:<mime>;base64,<payload>"}}
       ]
     }
  5. append one assistant turn:
     {"role": "assistant", "content": model_reply}

after all examples:
  append final current-task user turn
  = current business prompt + current business image

final messages order:
  [ref user 1, ref assistant 1, ref user 2, ref assistant 2, ..., current user]
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
- Algorithm-side visual payloads should read the snapshot image file and serialize it into an OpenAI-compatible `image_url` data URL payload instead of depending on the live template file path at request time.
- Repository-local temporary regression scripts and debug artifacts for this module should live under `/home/RealAI/cert_phase2_backend/.tmp/`, not `/tmp`, and throwaway artifacts should be deleted after verification.
- The current augmentation adapter is wired to the algorithm `main(record=..., output=..., model=..., instruction=..., count=..., api_url=..., api_key=...)` shape. The backend assembles `record` from the seed instruction's structured analysis payload plus `image_path`, and writes the algorithm output under `FINETUNE_RESULT_DIR/tasks/<task_id>/augment/<instruction_id>/result_augmented.json`.
- Adapter readiness should follow business-line boundaries instead of a shared "algo" bucket. Keep `ensure_generate_adapter_ready()`, `ensure_optimize_adapter_ready()`, and `ensure_augment_adapter_ready()` separate, and keep the matching service-layer `_ensure_xxx_adapter_ready_or_503()` helpers aligned with those names.
- When core config changes and the task is re-used, create or reuse a task version snapshot rather than mutating history invisibly.
- Execution should read snapshot fields, not the current prompt template row.
- If instruction-level prompt-template snapshot columns are added later, backfill old generated rows from matching task-config snapshots when `task_id + config_sort_order + model_name + prompt_content_snapshot` still line up, and backfill augmented child rows from their parent instruction snapshots.
- Before a task is restarted or retried, clear its raw generation artifact directory under `FINETUNE_RESULT_DIR/tasks/<task_id>` so algorithm-side resume behavior cannot reuse stale `generated.json` from an older version.
- Versioned selected-output exports such as `selected_<version_code>.jsonl` are separate artifacts; they may be retained for history unless the business requirement explicitly asks for cleanup.

## API Shape Notes

- Finetune task business codes should follow the same daily sequence style as other business modules, with the current format fixed to `FTK-YYYYMMDD-NNN`.
- Single instruction business codes should use their own namespace `INST-YYYYMMDD-NNN`; do not reuse `FTK` on `FinetuneInstruction`.
- Frontend task-create or task-edit payloads should submit ordered `config_items[]` with `model_name`, final `prompt_content`, `prompt_template_name`, and `prompt_template_id`.
- The backend should treat `prompt_template_name` and `prompt_template_id` as required display snapshots for task config items, while still using only `model_name + prompt_content` as the executable config combination.
- Frontend template selection should use `GET /api/v1/options/finetune-prompt-templates` and then fetch prompt-template detail to read `prompt_content`.
- Task config responses should return list items that expose model name, prompt content, prompt-template name, and prompt-template id for frontend table rendering and select echo.
- Task config, instruction list, instruction detail, generation-failure detail, and validation-candidate responses should not add derived fields such as `display_text` or `config_display_text`; the frontend should compose any combined display copy from the raw fields it already receives.
- Task instruction list should be sorted by created time descending and support filtering by instruction id, model name, and `is_harmful`.
- "instruction id" filtering should stay compatible with both the UUID primary key and the business code `instruction_code`, because the UI may display or search by either form.
- When `is_harmful` is exposed as a list filter, keep instruction detail and validation detail navigation aligned with the same filtered result set instead of only fixing the list query.
- Instruction list and detail responses should expose the instruction row's own `prompt_template_name` and `prompt_template_id` snapshots so the UI can show which template was actually used for that generated, optimized, or augmented record.
- Instruction-facing responses should return both the UUID primary key and `instruction_code`; validation detail should also return `selected_instruction_code` when the same-image group already has a selected row.
- Instruction list and detail responses may expose a frontend-facing `optimization_status` field, but that status should be derived in the response layer rather than stored as a dedicated database column.
- Instruction detail should expose structured analysis fields such as `msg`, `keyword`, `is_harmful`, `cate`, and `image_path`.
- Frontend dropdowns for instruction list filters should use:
  - `GET /api/v1/options/finetune-instruction-source`
  - `GET /api/v1/options/finetune-validation-status`
  - `GET /api/v1/options/finetune-instruction-safety`, where the current repository contract is `false = 安全`, `true = 有害`
- `GET /api/v1/finetune-tasks/{task_id}/validation-items/{instruction_id}/candidates` should return only the other candidates for the same image; the current anchor instruction itself is part of the parent validation detail payload and should not be duplicated in the candidates list.
- Task detail responses should keep `processed_count` and `total_count` usable for frontend polling during generation. For long-running generation, update `processed_count` incrementally in batches while the model call loop is still running, instead of only after the full model batch finishes.
- Unless one caller explicitly overrides the batch interval, the repository default generation save or progress interval should stay at `10` so large tasks surface progress early enough in the UI.
- Task creation only needs draft or start-now behavior; draft does not enqueue generation.
- `start` is the generic task submission action: use it for first launch after create, for draft or pending tasks, and after saving core-config edits that move a task back to `pending`.
- `retry` is the failure-only action: use it only for rerunning tasks already in failure-like end states such as `half_failed`, `failed`, or `terminated`.
- `copy` is a success-only action. Keep it unavailable for `half_failed`, `draft`, `pending`, and `terminated` unless the requirement doc explicitly changes.
- Finetune dataset options should already be filtered to labeled and non-disabled datasets, but create and start must still reject invalid datasets with `409`.
- Task delete should support both single-delete and batch-delete endpoints. Batch delete must de-duplicate repeated ids, reuse single-delete permission and state checks, and stay all-or-nothing.

## Augmentation Notes

- Augmentation now accepts one user-entered dimension description string instead of a fixed enum dropdown.
- The backend should trim that description and pass it to the algorithm adapter as the actual augmentation prompt.
- The backend should derive the algorithm `record` from the seed instruction itself rather than asking the frontend to submit raw annotation JSON.
- Augmentation keeps only `count` as the extra input control in the request contract; dedup-threshold and required-field-lock controls are removed.
- Augmentation remains additive only; it stores new instruction rows and keeps the seed instruction unchanged.
- Augmented rows should inherit the seed instruction's `model_name`, `prompt_content_snapshot`, `prompt_template_name_snapshot`, and `prompt_template_id_snapshot`. The user-entered dimension text belongs in traceable raw-response metadata, not in `prompt_content_snapshot`.

## Optimization Notes

- Optimization now accepts one user-entered rule text instead of a fixed enum option such as compliance enhancement, model adaptation, or length compression.
- The backend should trim that rule text and keep its length limit aligned with augmentation `dimension_description`.
- Optimization may reconfigure the execution context with a newly selected prompt template, the final edited prompt content, and a newly selected model name.
- Optimization still overwrites the original instruction row instead of creating a sibling candidate row.
- When optimization overwrites the row, it should also overwrite the row's prompt-template display snapshots so instruction detail echo stays aligned with the latest optimized content.
- Frontend-facing optimization status should be derived from the persisted fields with this priority: `processing > failed > success > idle`.
- Concretely, derive from `is_processing`, `last_operation_error`, and `optimized_at`; do not introduce a standalone persisted `optimization_status` field unless the business requirement expands.
- Prompt-template fields used during optimization remain display snapshots or editable seed material; execution should still read the final prompt content snapshot instead of treating the template row as a runtime dependency.

## Selection And Validation Logic

- Group generated instructions by `dataset_image_id`.
- After generation, select the instruction produced by the first task config item as the default training instruction for that image.
- When default selection is established after generation, reset the whole image group to `pending` and clear old validation metadata.
- Only records with a usable `msg` should become instructions; records with image-level `error` should be summarized into task `errors`.
- When generation creates instruction rows, copy `prompt_template_name_snapshot` and `prompt_template_id_snapshot` from the matched config row so later detail queries do not need to guess from current task config.
- If at least one valid instruction is created, attempt to export the selected-instruction training file and keep the task `success` or `half_failed` depending on whether any model batch failed. In practice, `output_path` should still be `null` right after generation because selected instructions are still `pending`.
- Validation list should be built from selected instructions whose `validation_status` is `pending`.
- Validation detail should separate "current anchor instruction" from "other candidates": the currently opened instruction stays in the top-level detail object, while the candidates list is used only for sibling comparison and reselection.
- When a human saves validation, keep only the chosen instruction selected, set its `validation_status` to `verified`, and store the manual `is_harmful` result.
- If selection changes or optimization overwrites the selected instruction text, reset that selected instruction back to `pending`.
- Manual edits on a selected instruction should also reset that selected instruction back to `pending`.
- Deleting a selected instruction should immediately reselect a remaining sibling and reset that new selected sibling to `pending`.
- Augmented instructions are additive candidates only and do not delete the seed instruction.

## Jsonl Export Rules

- `output_path` should be treated as the training-readiness marker for the task.
- Export rows must contain only the current selected instructions, one row per image.
- The backend must not keep a stale jsonl file around if any selected instruction is still pending.
- `_export_selected_instructions()` should delete the old file and clear `output_path` whenever:
  - there are no selected instructions, or
  - at least one selected instruction is not `verified`.
- A jsonl file may only exist when every selected instruction is manually verified.
- Start or retry should clear `output_path` before enqueueing a new generation run.

## Environment Wiring

The module depends on `FINETUNE_MODEL_PROVIDERS`.

Example:

```json
[
  {
    "name": "Qwen3-32B",
    "base_url": "http://172.18.1.128:30977/v1",
    "api_key": "",
    "host": "6cd859d7-9e39-46cd-9924-c3d40a557c27",
    "enabled": true
  }
]
```

Apply this configuration at minimum to:

- `backend`
- `celery-worker`

For environment consistency in this repository, it is also acceptable to mirror it into:

- `prestart`
- `celery-beat`
- `flower`

## Celery Entry Points

- `start_task_service()` -> `generate_finetune_instructions_task.delay()`
- `retry_task_service()` should remain a thin state-gate wrapper around `start_task_service()` instead of duplicating rerun cleanup logic.
- `queue_optimize_instruction_service()` -> `optimize_finetune_instruction_task.delay()`
- `queue_augment_instruction_service()` -> `augment_finetune_instruction_task.delay()`

Keep the Celery task function sync and bridge into async service logic with `asyncio.run()`.
