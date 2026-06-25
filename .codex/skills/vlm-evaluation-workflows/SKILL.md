---
name: vlm-evaluation-workflows
description: Implement and modify this repository's large-model evaluation module, including evaluation tasks, shared training-resource scheduling, training-model status writeback, runtime placeholders, and evaluation-related options endpoints.
---

# VLM Evaluation Workflows

Use this skill for repository-specific work on the large-model evaluation module.

## Source Of Truth

- Business rules, page behavior, and current TODO boundaries live in `requirements/大模型评估测试模块.md`.
- Raw contract wording and未整理补充项可追溯到 `note/大模型评估测试模块.md`，但实现时仍以 `requirements/大模型评估测试模块.md` 为准。
- 如果需求文档、训练模块现状和算法侧临时口径冲突，优先以 requirement 为准，再兼容现有训练模块状态机。

## Scope

Use this skill when changing any of these files or behaviors:

- `app/models.py` 中 `Evaluation*` 表、状态枚举以及与 `TrainingModel` / `TrainingResource` / `Dataset` / `PromptTemplate` 的关联
- `app/schemas/evaluation.py`
- `app/crud/evaluation.py`
- `app/services/evaluation_service.py`
- `app/services/evaluation_runtime.py`
- `app/api/routes/evaluation.py`
- `app/tasks/evaluation.py`
- `app/services/options_service.py` 和 `app/api/routes/options.py` 中评测相关下拉项
- `app/core/config.py` 中评测运行时和调度配置

## Current Confirmed Contract

- 当前版本只保留一种评测类测试任务，不再区分“测试任务 / 评测任务”两类。
- 评测任务只能选择 `DatasetType.EVALUATION` 且已标注、未禁用的数据集。
- 评测任务只能选择 `TrainingModelVersionStatus.PENDING_CONFIRMED` 的训练模型；`待测试（未确认）` 模型不能直接进入评测链路。
- 评测任务创建时不涉及“训练指令数据集”字段。
- 评测任务创建和编辑时不再由页面手动选择提示词模板；评测 `user.content` 需要沿训练链路自动解析。
- 评测提示词解析顺序固定为：
  - 优先使用来源训练任务当时显式指定的提示词模板内容。
  - 若训练任务未指定提示词模板，则回退使用其关联微调指令任务首组配置中的 `prompt_content`。
  - 若两者都缺失，则阻止评测任务创建或更新，避免生成空 prompt。
- 评测任务对外参数字段使用 `topP` 表示 Top-P；Service 和持久化层可继续使用 `top_p` 内部命名。
- 判定指标固定为 `Accuracy` 和 `Recall`，默认阈值均为 `0.85`，两者同时达标才算合格。
- `Precision` 和 `F1` 只展示，不参与合格/不合格判定。
- 评测 runtime 统一消费训练模型版本的 `model_path`，该路径应指向训练成功后标准化导出的 serving 目录：`{root_dir}/training/{train_task_id}/output/serving`。
- `adapter_path` 仅保留为 LoRA 原始 adapter 目录，不作为 vLLM 直接挂载目录；如果历史版本仍只保存了原始路径，Service 需要优先根据来源训练任务回推 `output/serving`。
- 评测任务标准工作目录统一为 `DATA_ROOT_DIR/evaluation/{task_code}`，其中：
  - `input/test_dataset.json` 为算法主输入
  - `input/images/*` 为后端复制后的稳定图片路径
  - `input/prompt_template.txt` 为任务级 prompt 快照文件
  - `output/manifest.json`、`output/predictions/predictions.json`、`output/metrics/metrics.json`、`output/logs/evaluation.log`、`output/config/evaluation_config.json` 为标准产物
- 当前算法运行任务标识环境变量以 `EVAL_TASK_ID` 为准，backend runtime 需传业务任务编号 `task_code`，不要传数据库 UUID，也不要自行扩展未被算法脚本消费的 `EVALUATION_TASK_CODE`。
- 评测 prompt 运行时优先消费任务快照文件 `input/prompt_template.txt`；只有任务未携带快照时，算法脚本才允许回退到 `PROMPT_VERSION` 默认模板。
- 评测任务参数 `temperature` / `topP` 需要在任务快照中持久化，并由 backend runtime 传给算法运行环境变量，同时落入 `output/config/evaluation_config.json` 作为运行配置快照。
- 评测任务与训练任务共用 `TrainingResource` 资源池，并使用相同优先级；统一按任务创建时间 FIFO 调度。
- 终止后的恢复运行语义是“从头重新执行”，不复用中间结果。
- 测试失败后的“重新配置”是基于原任务保留配置进入编辑态；编辑完成后仍需支持再次提交运行。
- 任务描述长度按需求限制为最多 `500` 字符。
- 当前已确认的最小真实执行闭环是：后端通过 evaluation runtime 拉起算法评测运行环境，轮询标准 `output/` 产物回写结果，而不是依赖算法回调闭环。
- 评测成功收口前必须同时满足两件事：
  - `manifest.status == completed`
  - 全部 5 个标准产物存在：`manifest.json`、`predictions/predictions.json`、`metrics/metrics.json`、`logs/evaluation.log`、`config/evaluation_config.json`
- 任一条件不满足都按失败链路收口，不允许仅凭容器退出码或局部文件存在就伪装成功。

## TODO Boundaries

- 算法运行版本、vLLM 额外参数、Ascend 挂载细节和站点级网络配置不在本 skill 中固化成单一现场值。
- 若后续算法运行环境重新调整标准输入输出字段、启动脚本路径或 vLLM 就绪判定方式，需要先更新 `requirements/大模型评估测试模块.md` 和本 skill，再改 runtime。
- 若要让 `temperature` / `topP` 真正影响推理结果，算法运行环境仍需消费 backend 传入的环境变量或 `evaluation_config.json`；在算法脚本尚未接通前，不要把“参数已持久化 / 已传入 runtime”误判为“已端到端生效”。
- 模型状态联动和跨模块整合流程尚未完全梳理。
  - 当前已确认的最小闭环是：评测任务启动时将模型置为 `TESTING`，评测完成后回写 `TESTED_PASSED` 或 `TESTED_FAILED`，失败或提前终止时恢复到评测前状态。
  - 不要自行扩展“可发布 / 重新训练 / 自动发布”等后续联动。
- 模型大小、一致性、安全性不属于当前页面化版本。
  - 不要在当前模块里新增这些指标字段、接口或可视化逻辑。

## Workflow

1. 先读 `requirements/大模型评估测试模块.md`，确认本次变更是否触及已确认规则还是 TODO 区。
2. 再看训练模块现有实现，尤其是 `TrainingModelVersionStatus`、`TrainingResource` 和调度链路，避免评测模块单独实现一套不兼容的资源逻辑。
3. 路由、Service、CRUD、Schema 分层沿用仓库既有风格，不把业务判断塞进 Router 或 CRUD。
4. 涉及共享资源和排队顺序时，必须同时检查训练任务和评测任务两条队列，而不是只在单模块内排序。
5. 涉及真实算法执行时，把 vLLM 启动、标准任务目录构建、算法脚本入口和产物轮询都隔离在 `evaluation_runtime.py`，不要把运行环境、挂载和启动命令硬编码进 Service。
6. 如果算法侧协议再次变化，优先先更新 `requirements/大模型评估测试模块.md` 和本 skill，明确新的标准目录、环境变量和产物契约，再改 runtime。

## Implementation Boundaries

- `EvaluationTask` 是评测模块的核心对象；当前不额外引入“评测资源”“评测模型”新表，直接复用训练模块已有资产。
- 任务详情优先展示任务行上的快照字段，不依赖关联对象始终存在。
- 评测提示词展示优先读取任务快照字段，不依赖模板当前内容，避免历史任务被后续模板修改污染。
- 删除评测任务采用逻辑删除；结果字段保留在表内，不做级联物理清理。
- 资源创建、编辑、删除不属于评测模块职责，继续复用训练资源读模型。
- 操作日志要覆盖“创建”和“提交”两个动作；创建即提交时也不要把两者合并成一条模糊日志。
- 真实执行入口固定为：
  - 从 Service 层投递 Celery
  - 在 Task 层进入 runtime 抽象
  - 由 evaluation runtime 构建标准 `input/output` 目录、挂载训练 serving 模型目录、启动算法评测脚本并轮询标准产物回写
- `PlaceholderEvaluationRuntime` 仅保留为配置降级和本地未接通环境的兜底实现，不再代表当前主流程能力。

## Read Next

- `.codex/skills/fastapi-service-crud/SKILL.md`
- `.codex/skills/sqlmodel-alembic-postgres/SKILL.md`
- `.codex/skills/celery-redis-worker/SKILL.md`
