---
name: vlm-training-workflows
description: Implement and modify this repository's visual large model training module, including training resources, base models, training tasks, host resource collection, runtime integration, queue scheduling, reconcile workflows, callback handling, and training-related options endpoints. Use when changing app/models.py Training* types, app/schemas/training.py, app/crud/training.py, app/services/training_service.py, app/services/training_runtime.py, app/services/training_resource_collector.py, app/api/routes/training.py, training-related options endpoints, app/tasks/training.py, or training runtime environment configuration.
---

# VLM Training Workflows

Use this skill for repository-specific work on the visual large model optimization training module.

## Source of Truth

- Business rules, state transitions, API-facing requirements, and current TODO boundaries live in `requirements/面向风险图片发现的视觉大模型优化训练.md`.
- When the change involves dataset deletion, deleted-dataset historical task display, or deleted-dataset retry or resubmit limits, read `requirements/数据集删除与关联任务联动规则.md` first as the cross-module rule source.
- This skill defines how to implement or modify that module inside this repository without breaking the existing architecture.
- If requirement docs, algorithm-side assumptions, and current code disagree, follow the requirement doc first, then the current repository contract.

### Current Confirmed Resource-Management Contract

For training-resource management, product has currently accepted the implementation-level contract below. Use these rules when the requirement wording is broader or still ambiguous, and update the requirement doc later if needed:

- resource management is read-only in this iteration; no online create, edit, or delete APIs
- resource list, summary, and detail are visible to any authenticated user, not superuser-only
- automatically created or refreshed host resources keep the fixed owner name `admin`
- resource detail returns only resource base information and hardware detail; related tasks are exposed through a separate paginated child API
- task-detail navigation from resource-related tasks is frontend-owned; backend only needs to return stable task identifiers and task fields needed for jump parameters
- resource summary should keep the current service-layer aggregation semantics stable unless the requirement doc is explicitly updated again

## Scope

Use this skill when changing any of these files or behaviors:

- `app/models.py` training resources, base models, tasks, metrics, logs, model versions, and notifications
- `app/schemas/training.py`
- `app/crud/training.py`
- `app/services/training_service.py`
- `app/services/training_runtime.py`
- `app/services/training_resource_collector.py`
- `app/api/routes/training.py`
- training-related options endpoints
- `app/tasks/training.py`
- training runtime or collector env wiring in `app/core/config.py` and env docs

## Workflow

1. Start from the requirement document.
If the change touches task states, resource behavior, base-model lifecycle, task detail fields, notification semantics, or callback contract, read the relevant section in `requirements/面向风险图片发现的视觉大模型优化训练.md` first.

2. Trace the affected layer boundary.
Identify whether the change belongs to ORM or schema shape, CRUD query behavior, service orchestration, runtime or collector integration, router contract, options exposure, or Celery execution.

3. Keep the platform boundary clear.
This module currently implements platform capabilities first. Do not invent algorithm-specific hyperparameters or algorithm-side evaluation semantics unless the requirement doc or the user explicitly expands that area.

4. Keep runtime integration behind the runtime layer.
Container or workload start or stop or inspect logic belongs in `app/services/training_runtime.py`, not in routers, CRUD helpers, or generic services.

5. Keep host-resource collection behind the collector layer.
NVIDIA `nvidia-smi`, Ascend `npu-smi info`, CPU or memory sampling, and vendor-specific parsing belong in `app/services/training_resource_collector.py`, not in router or service entrypoints.

6. Preserve the repository's single-node compromise.
Long-running scheduling and reconcile logic stay on Celery tasks. Keep the Celery edge synchronous and bridge to Redis or service logic the same way the repository already does.

## Implementation Boundaries

- Keep the module centered on three platform objects: `TrainingResource`, `TrainingBaseModel`, and `TrainingTask`.
- Keep the training data source explicit. A training task is not identified by `dataset_id` alone; it must also point to one concrete `finetune_instruction_task_id` that defines which confirmed image-text instruction set is used for this training run.
- Keep the dataset-to-finetune relationship two-stage. One dataset may correspond to multiple finetune instruction tasks, so training flows must not infer "the latest" or "the only" finetune result from dataset scope alone.
- Keep finetune-task reuse permissive. One confirmed finetune instruction task may be reused by multiple training tasks because training consumes its already exported data artifact; do not add training-side uniqueness or exclusive-link checks unless the requirement document changes.
- Keep frontend option flows aligned with that data-source split:
  - dataset options answer "which datasets are eligible for training"
  - finetune-task options answer "for the selected dataset, which finetune result set is used"
- Keep finetune-task selection inside task create and edit payloads. Do not reintroduce standalone task-level link or unlink APIs, and do not put finetune link or unlink controls back into the training-task list contract unless the requirement document explicitly restores them.
- Keep the training-task list response focused on core summary fields. The strategy summary field on `TrainingTaskListItem` should be `training_type` / `training_type_label`, with the current narrow values `full_finetune` and `lora`; do not add finetune-task display fields, "关联指令数据集" aliases, or list-level link-state booleans back unless the requirement document explicitly changes again.
- Keep training prompt-template selection explicit but optional. A training task may point to one user-chosen training prompt template, and that template is not inferred from dataset, finetune task, or base model.
- Keep training prompt-template eligibility narrow:
  - the field name is `prompt_template_id`
  - create and edit flows may omit the field or explicitly clear it
  - only prompt templates with `template_type == training` and `status == available` are eligible
  - expose those choices through `/options/training-prompt-templates`
- Keep prompt-template snapshots resilient the same way as other history fields. Training-task detail and edit echo should rely on task-row snapshot fields such as template name and template id instead of trusting the current prompt-template row to stay unchanged forever; when a task selects a template, also persist its prompt content snapshot so downstream evaluation can reuse the training-time prompt rather than the template's latest edited content.
- Keep backend validation stronger than frontend filtering. Even when `/options/training-datasets` and `/options/training-finetune-tasks` already filter choices, create/update/submit flows must still re-check dataset type, dataset status, finetune-task ownership, dataset-task matching, and per-image confirmed-instruction completeness.
- Apply that same rule to prompt templates only when the user actually provides `prompt_template_id`: create and update flows must still re-check template existence, ownership visibility, template type, and available status.
- Keep training-resource selection explicit on task create and edit flows:
  - frontend gets selectable resources from `/options/training-resources`
  - that endpoint currently returns non-fault resources only; occupied resources remain selectable because tasks may queue on them
  - the current lightweight recommendation contract is: return the most suitable options first by `idle first -> more free accelerator memory -> lower current load`; frontend may default to the first option, but the scheduler still owns the real start decision
  - create and editable update payloads must carry one concrete `resource.preferred_resource_id`; do not fall back to "resource spec only" submission
  - backend must still re-check selected-resource existence, status, and capacity instead of trusting the options list alone
- Keep the current training-type contract narrow: only `full_finetune` and `lora` are supported. Use the field name `training_type` consistently across ORM, schema, API, options, and runtime integration. Do not reintroduce older training-type values unless the requirement document expands the scope again.
- Keep resource creation automatic in the local runtime model. There is no manual resource-create API; the default host resource row is created or refreshed by the reconcile flow, including startup-triggered and fallback-triggered reconcile execution.
- Keep the single-node resource owner contract simple: automatically created training resources use the fixed owner name `admin` unless the requirement doc changes.
- Keep resource-management access simple in the current iteration: all authenticated users may read resource summary, list, detail, and resource filter options.
- Keep resource accounting split into two layers:
  - host snapshot: CPU or memory or accelerator totals and busy devices from the collector
  - platform accounting: `used_gpu_count`, task allocation, and task-state-driven occupancy from the service layer
- Keep resource-detail and resource-related-task contracts split in the current iteration:
  - `GET /training/resources/{id}` returns only resource base information and hardware detail
  - `GET /training/resources/{id}/related-tasks` returns the paginated related-task list
  - the related-task child API defaults to page 1 and page size 5 unless the requirement explicitly changes again
  - do not add backend-owned navigation payloads such as URLs; only return stable task identifiers and display fields
- Keep training-resource hardware detail semantics stable when auto-filling detail fields:
  - `gpu_interconnect` means the node's primary GPU interconnect type, such as `NVLink` or `PCIe`
  - `cpu_model` means the host CPU model string
  - for ARM / Ascend hosts, `cpu_model` auto-detection should not assume x86-only `model name`; support `/proc/cpuinfo` keys such as `Processor` and `Hardware`, with `lscpu` as fallback
  - `network` means the default business NIC plus its bandwidth label when detectable, such as `bond0 100GbE`
  - when `TRAINING_HOST_NETWORK_LABEL` is set, keep its format as `<iface> <bandwidth-label>`, for example `ens18f0np0 100GbE`
  - the recommended site-side derivation is: get the default-route interface from `ip route | awk '/default/ {print $5; exit}'`, read `/sys/class/net/<iface>/speed` in `Mb/s`, then format `>=1000` and divisible-by-`1000` values as `N GbE`, otherwise `N MbE`
  - `storage_type` means the storage media type for the training artifact filesystem rooted at `DATA_ROOT_DIR/training`, such as `NVMe`, `SSD`, `HDD`, or `NAS`
  - `storage_capacity_gb` means the total filesystem capacity for `DATA_ROOT_DIR/training`, not current free space
  - prefer `/proc` and `/sys` kernel views for host-detail collection where possible, and treat helper commands like `ip` or `ethtool` as fallback rather than hard requirements for minimal containers
  - when the service runs inside containers and auto-detected NIC data reflects container network namespace rather than the real host business NIC, allow explicit override through `TRAINING_HOST_NETWORK_LABEL`
  - NVIDIA interconnect should come from `nvidia-smi topo -m`; Ascend interconnect should come from `npu-smi info -t topo`
  - Ascend driver version should prefer `/usr/local/Ascend/driver/version.info`, then fall back to the `npu-smi info` header
  - current API detail still reuses the `cuda_version` field as the accelerator software-stack version; keep NVIDIA returning CUDA and Ascend returning CANN toolkit version until the API contract is explicitly split
- Keep scheduling decisions based on both task allocation and host busy devices, so the scheduler does not place tasks onto externally occupied cards.
- Keep Ascend busy-device detection conservative and aligned with real allocatable state:
  - prefer the `npu-smi info` process table for busy-card judgment; if a card has running processes, treat it as host-busy
  - keep `utilization_percent` primarily sourced from `AICore(%)`, with `HBM-Usage(MB)` after idle-baseline deduction as the fallback for long-running training workloads that report `AICore(%) = 0`
  - do not treat raw idle-card `HBM-Usage(MB)` baseline as busy, because 910B hosts may report several GB of reserved HBM even when no process is running
- Keep pending-task ordering strict across submit and scheduler paths. Submit or create-and-submit should only enqueue the task and optionally trigger the same scheduler task; they must not start runtime workloads directly.
- Keep runtime start decisions single-entry. Resource check, device allocation, and workload start should happen in the scheduler path only, with Beat providing fallback and event-triggered scheduler calls only accelerating the same code path.
- Keep scheduler fairness strict. Later pending tasks must not bypass an earlier pending queue head when that head cannot currently be allocated.
- Keep queue policy simple in this iteration. Effective behavior is FIFO; do not add role-based priority or resource preemption unless the requirement document changes.
- Keep accelerator allocation whole-device based in the current platform contract:
  - default `lora` tasks occupy 1 accelerator device
  - default `lora` tasks request 16 CPU cores and 64GB memory
  - default `full_finetune` tasks occupy 4 accelerator devices
  - default `full_finetune` tasks request 32 CPU cores and 128GB memory
  - allocation is by concrete device index, not by fractional memory slicing
  - if the remaining allocatable free-device count is lower than the task's requested device count, the task must stay pending even when some cards still show spare memory
- Keep task configuration snapshots on the task row. Base-model name, type, and version snapshots must remain readable even if the base model is later disabled or deleted. User-facing wording should use "停用"; internal enum values may remain `paused` for compatibility.
- Keep algorithm-container materialization backend-owned. Before runtime startup, export the selected finetune instructions into task-local `train.json`, `dataset_info.json`, and copied image files; do not make the algorithm container query business tables directly.
- Keep task-local input workdirs runtime-generated, not user-maintained. `training/{task_code}/input` is rebuilt by the backend before launch and then mounted read-only into the algorithm container; do not design flows that depend on users manually preserving files inside that directory.
- Keep prompt-content resolution resilient when exporting training data:
  - when `prompt_template_id` is absent, use each selected instruction's own `prompt_content_snapshot` as that row's `user.content`
  - when `prompt_template_id` is present, prefer the current template row content; if the live row disappears later, fall back to that instruction's `prompt_content_snapshot` instead of failing only because the template changed
- Keep assistant-content export aligned with the confirmed training-data contract:
  - prefer each selected instruction's `raw_response`
  - fall back to `instruction_text` when `raw_response` is missing
- Keep multimodal ShareGPT export structurally valid for LLaMA-Factory. The count of `<image>` markers in `messages[0].content` must match the `images` list length; normalize missing or incorrect counts during export instead of assuming prompt templates are already correct.
- Keep training tasks free of a project dimension. Current platform contract does not persist or expose a `project_name` field.
- Keep LoRA-specific parameters minimal. The current confirmed contract adds only `rank`, with default `8` and supported range `1..128`, and this parameter applies only when `training_type == lora`.
- Keep algorithm-runtime hyperparameter mapping explicit and narrow. `TRAIN_PARAMS_JSON` currently carries `batch_size`, `gradient_accumulation_steps`, `learning_rate`, `num_train_epochs`, `warmup_ratio`, `lr_scheduler`, `max_samples`, `cutoff_len`, `save_steps`, and `logging_steps`; only LoRA tasks add `lora_rank`.
- Keep full-finetune launchability aligned with the configured Ascend runtime. In the current Ascend environment, full-parameter finetuning is launchable through the existing multi-card runtime path; do not regress that support back into "draft-only" or fail-fast rejection unless the requirement document changes again.
- Keep retry and resume runtime materialization fresh. When the scheduler starts a retried or resumed task and finds an old same-name runtime instance, it must remove non-running stale instances and recreate the runtime with the new env instead of starting the old instance.
- Keep base-model type as a platform string field rather than a hard enum. The current contract is "preset options + user-creatable custom names", so new base models may introduce a new `model_type` value directly without a separate dictionary write flow.
- Keep base-model permissions simple. Product has confirmed that all base models are shared by all users, so creation and update flows must not expose user-, role-, or project-scoped permission behavior.
- Keep base-model storage-path validation stronger than format-only checks. Besides requiring an absolute path, create flows must verify the path exists and that the target path is readable as a file or contains model files when it is a directory.
- Keep base-model deletion behavior requirement-driven:
  - enabled base models cannot be deleted
  - only disabled base models can be deleted; user-facing wording should use "停用", while internal enum values may remain `paused` if the API contract has not changed
  - deletion is blocked when related tasks are draft, pending, starting, running, or cancelling
  - deletion is allowed when all related tasks are succeeded, failed, or cancelled, and those historical tasks should display the deleted-model snapshot
- Keep training-model management inside this module. Training success should auto-create or auto-append platform-owned trained-model records and version history instead of leaving generated artifacts as unmanaged `TrainingModelVersion` rows only.
- Keep training-model delete behavior contract-tight:
  - models in `testing` status must not be deleted
  - logical delete only hides the record
  - permanent delete must remove both database rows and referenced artifact files or directories before commit
- Keep training-model action exposure aligned with the current product matrix:
  - `pending_unconfirmed`: show `confirm_model` and `delete_model`
  - `pending_confirmed`: show `edit_model`, `archive_model`, and `delete_model`
  - `testing`: show `detail` only
  - `tested_passed`: show `edit_model`, `archive_model`, and `delete_model`
  - `tested_failed`: show `retrain_model`, `edit_model`, `archive_model`, and `delete_model`
  - `archived`: show `restore_model` and `delete_model`
  - legacy `published` / `disabled`: keep `restore_model` and `delete_model` only for historical compatibility; do not expose them as normal forward states
- Keep training-model list query semantics aligned with the task list contract:
  - support `keyword`, `status`, `modelType`, `startTime`, and `endTime`
  - expose training-model status options through `/options/training-model-status`
  - do not expose legacy `published` / `disabled` values in that options endpoint
  - expose model-type options through `/options/training-base-model-types`
  - keep created-time sorting parameterized as `sortOrder=asc|desc`
  - default sort remains created-time descending, matching the training-task list
- Keep training-model test-state transitions owned by the evaluation module:
  - training-model management does not provide a manual `test-status` transition endpoint
  - only `pending_confirmed` models may enter the testing chain
  - `testing`, `tested_passed`, and `tested_failed` are driven by evaluation-task create/run/result writeback
  - do not reintroduce manual model-status mutation APIs for the testing chain inside the training module
- Keep training-model archive rules contract-tight:
  - archive is allowed only from `pending_confirmed`, `tested_passed`, and `tested_failed`
  - `pending_unconfirmed`, `testing`, `archived`, and legacy `published` / `disabled` must be rejected
- Keep restore behavior stable:
  - `archived` restores back to `pending_confirmed`
  - legacy `published` / `disabled` may also restore back to `pending_confirmed` for cleanup compatibility
- Keep task state transitions explicit and scheduler-owned:
  - `draft -> pending -> starting -> running -> succeeded/failed`
  - `starting/running -> cancelling -> cancelled` through terminate + runtime or reconcile convergence
  - only the scheduler path should move queued tasks from `pending` into real runtime startup
  - failed tasks may re-enter `pending` through retry or resume; cancelled tasks may re-enter `pending` through retry only
- Keep task restart semantics aligned with the confirmed status flow.
  - re-submit / retry means clearing execution snapshots and checkpoint reference, then starting again from zero
  - resume means restarting from the latest persisted checkpoint after a failed run, not resuming an in-process pause
  - resume recovery point is the latest saved checkpoint only; do not promise exact-step recovery between checkpoint intervals
  - cancelled tasks currently restart from zero; they do not resume from checkpoint
  - `POST /training/tasks/{id}/retry` is allowed only from `failed` and `cancelled`
  - `POST /training/tasks/{id}/retry` must clear checkpoint and prior execution snapshots, then re-enter `pending`
  - `POST /training/tasks/{id}/resume` is allowed only from `failed`
  - `POST /training/tasks/{id}/resume` should prefer the latest readable checkpoint when available; when `checkpoint_path` is missing or unreadable, it should compatibly fall back to retry-from-zero, clear the stale checkpoint reference, and make that downgrade explicit in the returned message and operation log
  - failed-task action exposure should show `retry` broadly and show `resume` only when checkpoint recovery is actually available
  - cancelled-task action exposure should not show `resume`
- Keep task termination single-path. The terminate API should only mark the task as `cancelling` and send the runtime stop request; the final `cancelled` transition should be closed by runtime callback or reconcile logic instead of being forced synchronously in the HTTP handler.
- Keep task delete behavior logical in this iteration:
  - deleting a training task must not physically delete checkpoints, output models, or other training artifacts
  - the task record stays in the database with terminal hidden state `deleted`
  - default task queries, task detail reads, and task-linked counts should exclude deleted rows unless a call site explicitly opts in
  - when a logically deleted task was the last live task linking a finetune instruction task, release that finetune-link marker
- Keep checkpoint resume gated by real artifact durability for action exposure. Only expose the `resume` action when the task still has a checkpoint path and that artifact is expected to remain readable after container restart; if a caller still hits `/resume` without a valid checkpoint, compatibly downgrade to retry-from-zero instead of hard-failing.
- Keep runtime resume wiring explicit. If resume is supported, pass a dedicated runtime signal such as `RESUME_FROM_CHECKPOINT`; do not rely on the algorithm container inferring resume intent from generic output directories alone.
- Keep callback compatibility tolerant at the runtime boundary. The current contract accepts algorithm callback status alias `success` and maps it to platform `succeeded`.
- Keep callback payload compatibility tolerant at the runtime boundary. Besides platform-style fields such as `progress_percent`, `log_message`, `raw_metrics`, `output_model_path`, and `adapter_path`, the backend must also accept the current algorithm-image payload style: `progress` (0..1), `message`, `metrics`, and `artifact_path`.
- Keep callback artifact backfill semantics explicit.
  - When the algorithm image only returns a single `artifact_path`, first map it to the raw task artifact field: `adapter_path` for LoRA tasks and `output_model_path` for full-parameter tasks.
  - Before marking success and creating model-version records, always prefer the standardized serving directory `training/{task_code}/output/serving` as the model version `model_path` whenever `output/serving/serving_manifest.json` exists with `serving_ready = true`.
  - Keep that rule identical for both `full_finetune` and `lora`: downstream evaluation and inference consume `model_path = output/serving`; only LoRA keeps `adapter_path = output/final` as the raw adapter archive.
  - Treat `output/final` as the raw final artifact directory. For LoRA tasks, keep it through `adapter_path`; for full tasks, do not expose it as the primary evaluation/inference model path once `output/serving` is ready.
- Keep callback auth compatibility tolerant. `CALLBACK_TOKEN` may still be passed through to algorithm containers, but the backend callback endpoint must not hard-fail solely because the algorithm side omitted that field.
- Keep callback artifact paths host-readable. If the algorithm callback reports container paths under `TRAINING_CONTAINER_OUTPUT_DIR`, normalize them back to `DATA_ROOT_DIR/training/{task_code}/output/...` before storing them on the task row.
- Keep user-facing strings in `app/core/consts/training.py`. Do not hardcode task action labels, notification titles, success messages, or callback responses in services or routers.
- Keep resource list and detail APIs platform-owned. Do not push live collector parsing into request handlers; they should call service-layer orchestration only.
- Keep callback ingestion append-only for logs and metrics while the task row stores the latest execution snapshot.
- Keep training-monitor and performance-comparison fields aligned with the current product contract:
  - do not expose or rely on accuracy in training-task detail, performance-comparison, or monitor-oriented API shapes unless the requirement document adds it back
  - use `step` as the primary progress iteration concept for monitor display
  - do not present `current_epoch` as a required monitor field in API-facing training detail contracts unless the requirement document explicitly restores it
- Keep training-task progress and file sourcing aligned with the current product contract:
  - task-list progress should default to the task-row snapshot fields `progress_percent`, `current_step`, and `total_steps`, so list polling does not depend on scanning output files
  - when algorithm callbacks omit `current_steps` or `total_steps`, the backend may backfill those task-row snapshot fields from the latest `trainer_log.jsonl` row during callback ingestion, instead of making the list API read files directly
  - for the currently paged active tasks only, the backend may do a lightweight pre-response backfill from the latest `trainer_log.jsonl` row and persist it, so the list does not visibly lag behind detail for long-running tasks
  - `estimated_finished_at` is a lightweight detail-header summary for active tasks only; estimate it from elapsed runtime and current progress ratio, preferring `progress_percent` and falling back to `current_step / total_steps` when needed
  - when callback ingestion or active-task progress backfill refreshes step or progress snapshots, it may also refresh the task-row `estimated_finished_at` snapshot; terminal tasks should clear that field
  - the main task-detail API should stay lightweight: it may use finer-grained file-backed progress for header summaries, but it must not inline monitor curves, log lists, resource-usage payloads, performance-comparison arrays, or operation logs
  - the task-monitor child API should prefer `trainer_log.jsonl` rather than only DB callback snapshots
  - the display-oriented task-logs child API should prefer formatted `trainer_log.jsonl` lines and stay paginated
  - raw log export should prefer `llamafactory_train.log`
  - the task-performance-comparisons child API should prefer `train_results.json` and `trainer_state.json`, then fall back to `trainer_log.jsonl` and stored task snapshot fields
- Keep task resource-usage child-API semantics task-scoped and real-time:
  - CPU usage should come from the training runtime view, with semantics aligned to runtime stats; in the current platform implementation this is read through a structured runtime stats snapshot rather than shell-text parsing
  - accelerator usage should come from collector-side per-device sampling for the task's allocated cards, instead of reusing node-level average utilization directly
- Keep training notifications creator-scoped and unread-persistent:
  - notify queue, start, failure, completion, and termination for the task creator only
  - persist training notifications in the database with read or unread state
  - page-facing notification lifetime is 3 seconds on the frontend only; backend persistence must outlive page close or relogin until the notification is marked read
  - keep notification retrieval and read semantics explicit at the API or service layer, including single-read and read-all flows when the current requirement doc asks for them
  - termination wording must distinguish user-requested stop from abnormal stop
  - persisted notification payload is minimal: `task_id`, `notification_type`, `message`, read state, and timestamps; do not add backend-owned `title`, `action_url`, or `action_items`
  - frontend owns button rendering and navigation; backend only provides stable `task_id` plus notification `type`
  - keep notification `type` fixed to the current five values: `queued`, `started`, `failed`, `succeeded`, and `cancelled`, unless the requirement document explicitly expands the matrix
  - when a task succeeds and model ingestion also completes, keep one user-facing success notification for the task instead of reintroducing a second "model ingested" notification
- Keep task-detail success actions aligned with the current product scope: keep `view_evaluation`, but do not expose export-model actions or export-queue semantics in this iteration.
- Keep training action payloads frontend-owned in navigation terms: return stable `action key`, task or model ids, and related summary fields, but do not add backend-owned route URLs such as `detail_url` or action `url`.
- Keep task operation logs timeline-oriented in the current product scope: `GET /training/tasks/{id}/operation-logs` should return the full ordered list instead of forcing pagination, unless the requirement document explicitly changes again.
- Keep startup fallback and empty-list fallback lightweight and non-blocking. Do not make API startup depend on collector success.
- Keep startup-triggered resource refresh queue-only at the API edge. On startup, enqueue the existing reconcile Celery task instead of running host collector commands such as `nvidia-smi` directly inside API worker processes.
- Keep reconcile execution single-path and lock-protected. Startup-triggered refresh and Beat-triggered refresh should converge on the same `reconcile_training_resources_task` path so they share the existing Redis reconcile lock instead of introducing a second direct execution path.
- Keep reconcile self-healing for handleless active tasks. If a `starting` task still has no runtime handle after the configured grace period, close it as failed; if a `cancelling` task still has no runtime handle after the grace period, close it as cancelled, so single-node worker crashes do not leave tasks stuck forever.
- Keep collector failures tolerant. Prefer marking the resource faulted and logging, not crashing the API or worker.
- Keep environment-driven runtime choices in config. Do not add a database-backed runtime-provider registry unless explicitly required.
- Keep algorithm-container mount points config-driven. Use config for container dataset dir, output dir, base-model root, dataset name, training stage, Ascend driver mount, and model-to-template mapping instead of hardcoding site-specific values across service code.
- Keep base-model mount behavior aligned with the current local runtime contract. Prefer exposing the whole host model root such as `/data/realai_cert2/models` to the runtime model root such as `/models`, and set `BASE_MODEL_PATH` to the specific subdirectory under that root, for example `/models/Qwen3-VL-8B-Instruct`; only fall back to single-model-directory mounts for legacy records outside the agreed root.
- Keep Ascend launch wiring explicit in runtime:
  - expose allocated cards through `ASCEND_RT_VISIBLE_DEVICES`
  - for multi-card tasks also set `FORCE_TORCHRUN`, `NPROC_PER_NODE`, `MASTER_ADDR`, and `MASTER_PORT`
  - mount Ascend runtime directories only when the configured host path actually exists
  - if runtime conditionally exposes host-side tools such as `npu-smi`, remember that the existence check happens inside the process that launches the runtime; keep the related paths visible there before expecting runtime to pass them into algorithm workloads
- Keep terminal failure messages actionable. When runtime state or callback payload only contains wrapper text such as `See log: /workspace/output/llamafactory_train.log`, prefer extracting the last actionable error line from task-local `llamafactory_train.log` so task detail and notifications show the real OOM / dtype / parameter error.
- Keep runtime network selection local-environment-safe. If `TRAINING_CONTAINER_NETWORK` contains an environment-specific logical name, prefer resolving it to the actual runtime network before falling back to a same-named standalone network.
- Keep NVIDIA runtime behavior conservative until the algorithm side publishes a concrete multi-card startup contract. The current platform only allocates GPU visibility through runtime device allocation; do not invent `torchrun` envs for NVIDIA by default.
- Keep reconcile scope narrow unless product explicitly expands it. The current reconcile task closes task terminal states and refreshes resource accounting, but it does not automatically remove exited training containers.
- Keep runtime extra-kwargs config additive only. Protected launch fields such as image, environment, network, runtime, devices, device requests, and volumes remain owned by `training_runtime.py` and must not be overridden through config injection.
- Keep training base-model type options merged from two sources:
  - product presets from config, currently `InternVl` and `Qwen3-VL`
  - distinct `model_type` values already present in `training_base_model`
- Keep the training-type options endpoint singular and explicit: `/options/training-type` returns only `full_finetune` and `lora`.
- Keep training dataset and finetune-task options explicit and separate:
  - `/options/training-datasets` returns eligible datasets only
  - `/options/training-finetune-tasks?datasetId=...` returns eligible finetune tasks only for that dataset
- Keep training base-model options aligned with list filtering and create flows:
  - `/options/training-base-models` returns base-model select options for both task filters and task-create/edit forms
  - `enabledOnly=true` may be used when the frontend only needs currently enabled choices; `enabledOnly=false` may be used for broader historical filtering
  - task list filtering must continue supporting both `baseModelId` and `baseModelType`, so frontend can filter by concrete base-model rows or by model-type group
- Keep training-resource options explicit and create-flow-ready:
  - `/options/training-resources` returns resource select options for task-create/edit forms
  - option `value` is the concrete `TrainingResource.id` and should map directly to request field `resource.preferred_resource_id`
  - option labels and descriptions should stay UI-ready so the frontend does not need to reconstruct GPU model / GPU config / CPU / memory summary text from multiple APIs
- Keep training resource CPU and memory filter options threshold-based and separate:
  - `/options/training-cpu-core-levels` returns CPU lower-bound levels such as `128`, `64`, `32` that are actually satisfiable by current resources
  - `/options/training-memory-gb-levels` returns memory lower-bound levels such as `1024`, `512`, `256` that are actually satisfiable by current resources
  - labels should remain UI-ready, such as `128核+` and `1TB+`, while values stay numeric for direct reuse in `cpuCoreLevel` and `memoryGbLevel` query params
- Keep the model-type options endpoint searchable by keyword for frontend combobox use, but do not let the search contract restrict create or update payloads. Search only filters the returned suggestion list.

## File Map

- `app/models.py`
  Persistence model for resources, base models, tasks, metrics, logs, model versions, and training notification records.
- `app/schemas/training.py`
  Request and response contracts for resource views, base-model lifecycle, task CRUD, callback payloads, and persisted notification payloads with read state.
- `app/crud/training.py`
  Query helpers, paginated lists, lightweight task-detail preloading, and child-interface data retrieval; default task queries should hide logically deleted tasks.
- `app/services/training_service.py`
  Main business orchestration: summaries, CRUD flows, lightweight detail assembly, child-interface data loading, queue submission, callback handling, startup or empty-list reconcile triggering, scheduling, and reconcile logic.
- `app/services/training_runtime.py`
  Runtime boundary to local or future workload backends.
- `app/services/training_resource_collector.py`
  Host collector boundary for CPU or memory and accelerator probing.
- `app/api/routes/training.py`
  HTTP contracts for resources, base models, lightweight task detail, monitor, logs, resource usage, performance comparison, operation logs, callback, and notifications.
- `app/tasks/training.py`
  Celery bridge for periodic scheduling and reconcile execution.

## Change Checklist

- Re-check whether the change affects task status transitions, especially `draft`, `pending`, `starting`, `running`, `failed`, `cancelling`, and `cancelled`.
- Re-check whether base-model snapshot fields still behave correctly after model updates or deletion.
- Re-check whether base-model deletion blocks non-terminal related tasks and only disconnects succeeded, failed, or cancelled historical tasks.
- Re-check whether base-model type changes preserve the "preset suggestions + custom names" contract, including keyword search on the options endpoint and direct create with a new string value.
- Re-check whether resource summary, resource list, and resource detail still match the current platform contract instead of leaking runtime internals directly.
- Re-check whether resource read permissions still follow the current contract of "all authenticated users can view".
- Re-check whether resource detail stays lightweight and whether resource-related tasks remain on the dedicated paginated child API with the default page size 5 contract.
- Re-check whether resource-related task responses still expose stable task identifiers for frontend jump handling, without backend-owned navigation payloads unless explicitly required.
- Re-check whether collector updates and platform accounting updates still have separate responsibilities.
- Re-check whether any new user-facing string belongs in `TrainingMsg` or `TrainingConst`.
- Re-check whether queue, start, failure, success, or terminate notifications still follow the minimal payload contract of `type + task_id + message`, without reintroducing backend-owned button or route fields.
- Re-check whether terminate flows still expose a real intermediate `cancelling` state before `cancelled`, instead of collapsing both states inside the same request.
- Re-check whether failed-task actions clearly distinguish retry-from-zero versus resume-from-checkpoint, including detail actions, notification copy, and user-facing labels.
- Re-check whether training-task list changes keep finetune-task selection confined to create or edit flows instead of reintroducing list-level link or unlink APIs and booleans.
- Re-check whether the main task-detail response stays lightweight and does not re-inline monitor curves, logs, resource-usage arrays, performance comparisons, or operation logs.
- Re-check whether task-log and operation-log child APIs remain paginated after the change.
- Re-check whether host-resource fallback remains non-blocking and throttled.
- Re-check whether vendor-specific parsing stays in the collector instead of spreading into services.
- Re-check whether training-related options still come from enums or DB-backed distinct values rather than ad hoc literals.
- Re-check whether task-list filtering still supports the requirement-facing base-model-type filter contract, even if legacy `baseModelId` filtering is retained for compatibility.
- Re-check whether any training-task change still preserves the "dataset + finetune task" two-part data-source contract, instead of silently falling back to dataset-only inference.
- Re-check whether any training-task change still preserves the optional prompt-template contract, including create/update clearing behavior, options exposure, detail/edit snapshot echo, and `train.json` export fallback.
- Re-check whether monitor/detail/performance fields still match the current requirement wording around step-based progress and omitted accuracy.
- Re-check whether resume action exposure still validates both checkpoint presence and checkpoint artifact existence, while the `/resume` execution path compatibly downgrades to retry-from-zero when that checkpoint is missing at call time.
- Add or update tests for service, schema, CRUD, or collector behavior when the contract changes.

## Pairing

Use this skill together with:

- `fastapi-service-crud` for route or service or CRUD shape
- `sqlmodel-alembic-postgres` for model and migration work
- `celery-redis-worker` for scheduling or reconcile task changes

## Read Next

- Read `requirements/面向风险图片发现的视觉大模型优化训练.md` for the business source of truth.
