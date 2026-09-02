# RACER v2 主会 Benchmark 协议

- **协议标识：** `racer-v2-benchmark-protocol-0.1`
- **状态：** 预注册冻结草案；当前 **NO-GO**（仅有离线/静态证据，尚无可用于主会结果表的 executed v2 artifact）
- **适用范围：** RACER（Risk-Aware Counterfactual Execution and Recovery）的失败诊断、选择性恢复与反事实验证。
- **结果纪律：** 本文件冻结运行前规则；不得根据结果反向修改任务、模型、超时、重试、排除或统计口径。任何偏离须生成新协议版本并单列结果。

## 1. 研究问题、假设与非主张

### 1.1 研究问题

1. 在失败根因不确定时，风险感知的恢复动作选择是否比无条件重试、反思或恢复更有效？
2. 严格的 checkpoint 反事实验证能否提高最终任务成功率并降低 harmful repair 与状态回归？
3. 将 `abstain` 作为合法动作，是否能在相近覆盖率下减少误修？
4. 上述收益是否能在 Task-OOD、Tool-OOD、Fault-OOD、Env-OOD 和 Model-OOD 中保持？

### 1.2 预注册假设

- **H1（主要）：** 在相同任务、故障、环境、模型资源和行动预算下，RACER 的 failure-conditioned recovery rate 高于 generic self-reflection。
- **H2（主要）：** RACER 的 harmful repair rate 不高于 generic self-reflection，且目标方向为更低。
- **H3（次要）：** RACER 的风险覆盖曲线、单位成功恢复成本和 P95 恢复延迟更优。
- **H4（次要）：** 严格反事实验证和 `abstain` 消融会分别改变恢复成功/副作用权衡；若没有收益，报告为负结果。

### 1.3 明确非主张

本 benchmark 不主张：

- 诊断准确率等价于恢复质量，或 RACER 是所有 Agent 任务的普遍最优策略；
- 任何未实际运行的 τ-bench/τ²-bench/τ³-bench 数字、模型比较或 pass@k；
- 离线 local-flight 原型结果代表公开环境结果；
- 环境指纹、reward 或 HTTP 成功本身证明了真实世界副作用已提交；
- seed 重复运行构成独立同分布总体样本；
- 访问或披露任何 provider/API 密钥、`model.json` 凭据或第三方私密数据。

## 2. 版本锁定与运行环境

### 2.1 Benchmark 版本

- **local-flight：** 仅使用仓库中已冻结的实验矩阵；矩阵 manifest、任务内容、故障配置和源码均保存 SHA-256。当前已有矩阵为 `local-flight-matrix.json`（5 类故障 × 3 seeds）和 `local-flight-extended-matrix.json`（6 个任务变体 × 3 seeds）。
- **公开环境候选：** 独立 adapter 使用 `sierra-research/tau2-bench`，版本 `1.0.1`、Git commit `fc0055dc4e0a316c3f83133267fbd6faaa770992`、Python `>=3.12,<3.14`，并保存源码归档 SHA-256。只使用锁定 tag/commit，不使用移动的 `main`；不与旧 `tau-bench` 结果混报。
- 公开环境在完成 adapter A–D 验收、真实环境单任务 smoke 和审计前，标记为 `planned`，不得进入结果表。
- 每次实验记录 `protocol_id`、代码 commit、benchmark commit、manifest hash、依赖 lock/pip freeze hash、容器 image digest、adapter version、生成时间（UTC）。

### 2.2 容器和主机

- Apple Silicon 优先 `arm64` 镜像；若使用 `amd64`，必须单独记录架构和兼容性。
- 记录 OS、Docker/Compose 版本、Python 版本、CPU 架构、可用内存、并发度和时区（统一 UTC）。
- 实验使用独立容器/virtualenv、独立 `run_id` 命名空间和不可变初始数据快照；不同 run 不共享可变数据库、文件卷或缓存写入空间。
- 首次正式运行前必须保存容器构建 provenance；当前离线确认报告中的 Compose 静态解析不等价于 build/run 证据。

## 3. 模型资源与秘密隔离

### 3.1 资源锁定

每个 `model_resource_id` 必须锁定并记录：

- `provider`、`model_name`、精确 `model_version`/revision、API 契约版本；
- 本地模型权重/镜像的 SHA-256（不上传权重时记录受控存储引用）；
- tokenizer 版本、system prompt hash、developer prompt hash、tool schema hash、代码 commit；
- `temperature`、`top_p`、`max_tokens`、停止词、响应格式和工具调用模式；
- endpoint 的非敏感别名（不得记录带凭据的 URL）、region（如适用）；
- `credential_source`（仅写密钥管理器/环境变量的**名称**）、`secret_fingerprint`（可选的不可逆审计指纹），绝不写密钥值、Authorization header、完整 token 或 `model.json` 内容。

模型清单、provider 配置和密钥在仓库外的密钥管理器/运行时环境注入；日志、轨迹、报告、提交物和缓存中不得出现秘密。实验脚本不得打印环境变量全量。模型调用失败因缺少凭据时记为前置条件 blocker，不通过修改协议绕过。

### 3.2 用量与隔离字段

每次请求和每个 run 记录：`request_id`（脱敏）、`model_resource_id`、`input_tokens`、`output_tokens`、`cached_input_tokens`、`total_tokens`、provider 返回的 usage 原文哈希、`estimated_cost`、`cost_currency`、`latency_ms`、`cache_hit`、`retry_count`、`termination_reason`。成本无法可靠取得时为 `null`，不得填零。

模型用量按 `run_id`、`baseline_id`、`trial_id` 和 `model_resource_id` 分桶；诊断、恢复、反事实分支与评测器的 token/延迟分别计数。不得把 oracle 调用、缓存命中或重试隐藏在 RACER 成本之外。

## 4. 任务、故障与 split

### 4.1 任务轨道

local-flight 的状态机为 `search_flights → select_flight → confirm_booking`，并保留如下任务变体：`clean_success`、`non_refundable`、`suboptimal_refundable`、`missing_confirmation`、`force_error_confirm`、`drop_confirm`。故障轨道至少覆盖 `replace_action`、`force_error`、`rate_limit`、`wrong_tool`、`drop_action`；扩展公开实验可使用 `timeout`、`429`、`500/503`、`invalid_json`、`schema_drift`、`stale_state`、`memory_poisoning`、`policy_violation` 等，但每种故障必须有稳定 `fault_id`、注入位置、时间、工具和状态 hash。

每个公开 τ² airline 任务按官方 task list 的 split 和 index 生成 `task_id=airline-{split}-{index}`，不使用 `user_id`、`reservation_id` 作为任务身份。公开任务、policy、数据库和历史轨迹不得改写后冒充官方数据。

### 4.2 Split 定义

- **IID：** 训练/调参和测试任务来自同一分布，但测试 block 不重复。
- **Task-OOD：** 测试任务模板/语义簇未出现在训练或调参集合。
- **Tool-OOD：** 测试工具名或 schema 族未出现；不得仅重命名同一 schema 冒充 OOD。
- **Fault-OOD：** 测试故障类型组合或级联结构未出现。
- **Env-OOD：** 在一个环境开发，在另一环境只做冻结测试；例如 local-flight 开发、τ² airline 测试。
- **Model-OOD：** 开发可使用锁定的 teacher 资源，测试使用预先登记的本地 actor；测试后不得调参。

split manifest 在运行前冻结。按任务语义 hash、工具 schema hash、故障日程 hash 和环境版本 hash 做去重；发现近重复时以较早登记的 split 为准并记录。所有 prompt、few-shot 示例、诊断规则和 oracle patch 均只能使用训练/开发 split；测试 fault truth 不进入 agent-visible observation、prompt、缓存 key 可见内容或错误文本。

## 5. Paired block identity

### 5.1 Block 单位

一个 paired block 是同一 `task_id`、同一初始状态、同一 `env_seed`、同一 evaluator-only 故障日程下的一个不可变源 episode 及其各 baseline 分支。所有方法从同一源前缀或等价的独立初始快照开始；不得用某一方法已经改变过的可变环境给另一方法复用。

每个源/重放事件至少保存：`episode_id`、`source_run_id`、`run_id`、`task_id`、`env_seed`、`initial_state_fingerprint`、`fault_schedule_fingerprint`、`environment_fingerprint`、`contract_version`。指纹由稳定 JSON 编码后 SHA-256 计算；指纹不能替代快照。

### 5.2 Canonical identity 与去重

v2 canonical `paired_identity` 为：

```text
(episode_id, source_run_id, task_id, canonical_json(env_seed),
 initial_state_fingerprint, fault_schedule_fingerprint)
```

统计行的唯一键为 `paired_identity + baseline_id + trial_id + model_resource_id`。只有六字段齐全且 `paired_identity_complete=true` 的行才允许按配对键去重；缺 provenance 的 legacy 行保留并单独标记，禁止猜测性合并。发现完整配对键重复时，保留确定的第一份并记录 dropped duplicate；主会 GO 要求重复数为零。

## 6. Trial、温度、缓存与随机性

- 每个 split × task/fault block × baseline × model resource 至少运行 **3 个预注册环境 seeds `{0,1,2}`**；主会比较使用 **5 个 trial（`trial_id=0..4`）**，不足时只能作为 pilot，不得进入主表。
- 默认 `temperature=0`、`top_p=1`；若 provider 不支持，必须在运行前登记替代值并将该资源单独分析，不作未经校准的跨 provider 结论。
- 记录环境 seed、Python/NumPy（如使用）seed、模型请求 seed、trial seed 和生成顺序。trial seed 从冻结的 block identity 与 trial index 确定性派生，不能按结果挑选。
- 缓存只允许命中完全相同的 provider/model revision、prompt/tool schema hash、采样参数、输入内容 hash、请求 seed 和协议版本；缓存分 baseline/model namespace，命中与否、读写时间和响应 hash 均记录。不得以缓存掩盖失败请求、重试或真实 token 成本。
- 反事实 replay 必须使用独立环境实例和受验证的快照/契约；后缀重放 agent 的 `requested_action`，不能把受故障影响的 `effective_action` 当作 agent 原意。

## 7. Baseline 与消融

每个 block 使用相同预算、工具 schema、超时、重试和模型资源；baseline id 固定如下：

1. `raw_react`：原始 ReAct，不做诊断/恢复；
2. `fixed_retry`：固定重试；
3. `exponential_backoff`：指数退避重试；
4. `generic_reflection`：通用 self-reflection；主要比较基线；
5. `full_trace_judge`：完整轨迹 judge；
6. `step_by_step_diagnosis`：逐步诊断；
7. `binary_search_diagnosis`：二分诊断；
8. `agentdebug_targeted_feedback`：AgentDebug 风格 targeted feedback；
9. `always_recover`：总是选择恢复，不允许 abstain；
10. `racer`：完整 RACER（多根因、风险效用、反事实、abstain）；
11. `racer_no_abstain`：移除 abstain；
12. `racer_no_counterfactual`：移除反事实验证；
13. `oracle_root_cause`、`oracle_recovery`：仅作为上限，不代表可部署方法。

消融必须在运行前冻结，包括无置信度、固定诊断策略、不计算副作用、整轨迹重生成而非局部修复等。Oracle 可以读取 oracle manifest；任何非 oracle baseline 不得读取 fault truth、未来状态、目标 patch 或 oracle witness。

### 7.1 Pilot matrix 与主会 baseline registry 的边界

当前 E1/E2 `local-flight` matrix 中的 `raw`、`recovery`、`oracle` 仅是**本地 deterministic pilot 的占位 baseline**，不能被重命名为或汇入本节主会 registry。它们的用途分别是：`raw`（无恢复参考）、`recovery`（当前本地策略回归）和 `oracle`（evaluator-side 上限）。每个计划 cell 必须额外标记 `evaluation_tier="pilot"`、`baseline_registry_version="local-flight-pilot-v1"` 与 `main_comparison=false`；矩阵顶层还必须写明 `experiment_role="pilot"` 和 `baseline_catalog`，其中每个 pilot baseline 的 `maps_to_protocol_id=null`、`eligible_for_main=false`。除非在执行前由新的、无密钥的 model registry 与主会 baseline manifest 明确映射到本节固定 id，否则不得升级。

禁止任何自动 mapping：特别是 `recovery` 不等于 `racer` 或 `generic_reflection`，`raw` 不等于 `raw_react`，`oracle` 也不等于可部署 baseline。runner 对未知 baseline ID 必须 fail closed，不允许过滤后静默降级为 `recovery`；只有 catalog 明确定义的 oracle ID（pilot `oracle`；主会 `oracle_root_cause` / `oracle_recovery`）可以接收 evaluator-only fault truth，其他 baseline payload 只能包含诊断和公开字段。主会前必须单独冻结 `baseline_registry`，逐项记录 `baseline_id`、实现/配置 SHA-256、是否 oracle、模型资源/预算与 `matrix_id`；preflight 只有在 planned cell 的 registry id 全部存在且非 oracle 主比较集合完整时，才可通过 G0。E1/E2 现有计划数始终只报告为 pilot planned cells，绝不作为主会 coverage 或结果。

## 8. 指标与统计口径

### 8.1 指标定义

- **Failure-conditioned recovery rate：** `original_success=false` 的 block 中，最终任务成功且 replay valid 的比例；`counterfactual_supported=false` 不计恢复成功。
- **First-repair success：** 首次恢复动作后成功并满足全部终态 invariant 的比例。
- **Final task success：** 所有任务（含原本成功任务）最终成功比例；与 failure-conditioned 指标分开。
- **Harmful repair rate：** 原始失败且尝试恢复的 block 中，出现副作用、状态回归、不可逆错误或 policy violation 的比例；同时报告以全部原始失败为分母的敏感性版本。
- **State regression / policy violation / unintended tool call：** 由 evaluator 的 invariant 和 side-effect oracle 逐 block 判定。
- **Abstention precision：** abstain 中被 oracle 判定为无安全可验证恢复动作的比例；oracle 不可用时为 `null`，不以“未成功”替代。
- **Risk-coverage curve：** coverage=`1-abstain_rate`；按冻结置信度/风险阈值扫描，报告曲线和 AUC，并保留每个阈值的分子分母。
- **Regret：** 与 oracle recovery 的 utility 差值；utility 的 `λ, μ, ν` 在运行前固定并记录，不能事后调权。
- **成本/延迟：** 每成功恢复 token、API cost、恢复步骤数、P50/P95 latency；缺失值保持 `null`，不得当作零。
- **诊断：** root-cause accuracy、step hit@1/hit@3、macro-F1、ECE、Brier；fault truth 只在 evaluator/oracle 侧 join。

### 8.2 聚合层级

首先按 `trial_id` 在 paired block 内汇总，再按 task/fault/split/model 聚合；重复 trial 不能被当成独立 block。必须同时报告：总体、每 fault type、每任务变体、每 split、每 model resource、每 baseline 的原始计数和有效分母。原始成功任务不进入 failure-conditioned 恢复分母；timeout、infrastructure_error 和排除数单独列出。

### 8.3 CI、检验与多重比较

- 二项比例附 **95% Wilson CI** 作为描述性区间。
- 方法差值（RACER−`generic_reflection`）以完整 paired block 为重采样单位，进行 10,000 次有放回 cluster bootstrap，报告 95% percentile CI；不得对 trial 行做伪独立 bootstrap。
- 主要假设比较使用 paired sign-flip/permutation（10,000 次或可复现精确枚举），双侧 `α=0.05`；主要端点的多重比较使用预注册 Holm 校正。p 值不是 GO 的唯一条件。
- seed 是可复现标识，不是 iid 样本；CI 只描述已观测 block。报告 block 数、trial 数、排除数和缺失字段率。
- 统计脚本版本、随机种子、输入 envelope hash、CI 方法和参数写入 summary；同一 raw 输入必须可重生成完全相同的 derived/summary。

## 9. Timeouts、retries、exclusions

### 9.1 冻结上限

- 单次模型请求：120 s；单次工具调用：30 s；诊断阶段：60 s；单次 counterfactual branch：120 s；单 episode 总墙钟：300 s。
- 传输级暂时错误最多重试 2 次，退避 1 s、2 s；重试计入 token（若发生）、成本和 latency。语义错误、schema 错误、policy violation 不重试。
- 任何可能已提交副作用的 `response_loss`/不确定响应不得推断“未提交”；必须调用领域 status/reconcile endpoint。退款重试前必须有实体级 `refund_entity_id`/`idempotency_key`/`refund_id` 与可验证 `ledger_witness`。

### 9.2 分类与排除

终止原因至少区分 `success`、`agent_failure`、`timeout`、`retry_exhausted`、`policy_violation`、`counterfactual_unsupported`、`replay_invalid`、`infrastructure_error`、`auth_blocked`。已发出可能改变状态的动作后发生 timeout/response loss，计入分母并按 side effect unknown 处理，不得排除。

只有以下预注册条件允许从某个指标的有效分母排除：在 agent 首次动作前环境无法 reset、容器/进程崩溃、artifact 损坏或版本/manifest 不匹配；每次排除必须保留 raw 证据、原因、时间和责任方。`replay_invalid`、缺 witness、truth isolation 失败、超时和重试耗尽不是“好结果”，不得静默删除。任一 planned cell 缺 run 时主会表标 `NO-GO`；排除率 >5% 或任一 split 完全缺失时不得宣称正式比较。

## 10. 数据布局与字段

### 10.1 文件布局

```text
raw/<benchmark>@<version>/<split>/<block_id>/<run_id>.jsonl
raw/<benchmark>@<version>/<split>/<block_id>/<run_id>.manifest.json
oracle/<benchmark>@<version>/<split>/<block_id>/<source_run_id>.json
 derived/<benchmark>@<version>/<split>.jsonl
summary/<benchmark>@<version>/<split>.json
summary/<benchmark>@<version>/all.json
checksums/<benchmark>@<version>.sha256
```

`oracle/` 仅 evaluator 账户/旁车可读，不能挂载到 agent、diagnoser 或 recovery-policy 容器。公开 raw 轨迹不得包含密钥；必要时保存字段 hash/脱敏值并标注 `redacted=true`。

### 10.2 Raw event 最小 schema

每个事件记录：

```json
{
  "schema_version": "racer-v2-trajectory",
  "protocol_id": "racer-v2-benchmark-protocol-0.1",
  "run_id": "…",
  "episode_id": "…",
  "source_run_id": "…",
  "task_id": "…",
  "split": "…",
  "trial_id": 0,
  "baseline_id": "racer",
  "model_resource_id": "…",
  "env_seed": 0,
  "step_id": 0,
  "agent_id": "actor|diagnoser|policy|counterfactual|evaluator",
  "observation": "…",
  "requested_action": {"tool": "…", "arguments": {}},
  "effective_action": {"tool": "…", "arguments": {}},
  "tool_result": {},
  "state_before_hash": "…",
  "state_after_hash": "…",
  "checkpoint_id": "…",
  "environment_contract": {
    "contract_version": "racer-v2-environment-contract",
    "episode_id": "…",
    "source_run_id": "…",
    "env_seed": 0,
    "initial_state_fingerprint": "…",
    "fault_schedule_fingerprint": "…",
    "environment_fingerprint": "…"
  },
  "latency_ms": 0,
  "input_tokens": 0,
  "output_tokens": 0,
  "estimated_cost": null,
  "cache_hit": false,
  "retry_count": 0,
  "termination_reason": null
}
```

`fault_truth`、oracle patch、完整故障日程和 side-effect 真值不进入 agent-visible raw；它们只写 oracle manifest。derived 行必须包含 `paired_identity`、`paired_identity_complete`、`baseline_id`、`original_success`、`recovered_success`、`harmful_repair`、`abstained`、`replay_valid`、`counterfactual_supported`、`refund_witness_valid`、各成本/延迟字段及其缺失标记。summary 必须包含版本、环境指纹、planned/executed/valid/excluded counts、去重报告、CI 和统计脚本 hash。

## 11. 审计关卡（Audit Gates）

以下关卡全部通过前不得生成主会主表：

1. **G0 预注册锁定：** 协议、矩阵、split、模型资源、采样参数、预算、超时、重试、排除和统计配置均有 hash，且运行后未改写。
2. **G1 版本/环境：** benchmark commit、依赖、容器 digest、架构、代码和 manifest 可复核；每个 run 有完整 provenance。
3. **G2 paired identity：** 每个声称可比较的 row 六字段完整，源/分支初始状态和故障日程匹配；完整键重复为零，legacy 行不混入主比较。
4. **G3 strict replay：** prefix/patch/suffix 重放逐字段核对，replay provenance 与 `expected_clean_replay_contract` 完全匹配；缺失/不一致必须 fail closed，写 `counterfactual_supported=false`、`replay_valid=false`，不计恢复成功。
5. **G4 refund witness：** 对退款/取消等副作用，逐实体验证 `refund_entity_id`、`ledger_witness` 和 `ledger_entry_count`；同一实体重试必须返回一致 witness 和 `idempotent_replay=true`，不同实体不得被全局标记错误合并。response loss 必须经 `get_refund_status` 对账。
6. **G5 truth isolation：** 静态检查、运行时挂载和 adversarial probe 证明 agent/diagnoser/policy 看不到 oracle、fault truth、目标 patch、未来状态或 evaluator-only 日程；truth 只能在 evaluator 旁车 join。
7. **G6 usage/cache：** 每个请求 usage、cost、latency、retry、cache hit 可追溯至资源和 baseline；无跨方法污染、隐藏 oracle 调用或秘密泄漏。
8. **G7 serializer/stat replay：** 主表 canonical `racer-v2-results-envelope` 必须且只能使用 `records` list；`rows/results/entries` 只允许旧输入兼容读取，不能作为主表 admission，且任一多 alias envelope 直接 `NO-GO`。唯一键为完整 paired identity + baseline + trial + model；canonical `deduplication` 必须声明 `dropped_count=0`、无 legacy retained row。从 raw 重建 derived/summary 的 hash 与发布文件必须一致。
9. **G8 端到端证据：** 至少一次隔离容器中的 runner→adapter→counterfactual→evaluator live smoke；其结果不能被 smoke 数字冒充正式 benchmark，但必须证明接口、隔离、原子写入和终止分类有效。

### 11.1 离线 artifact 准入审计器

在生成任何主表前，必须对 canonical derived envelope 运行只读审计器：

```bash
python scripts/audit_v2_artifacts.py derived/<benchmark>@<version>/<split>.jsonl --output summary/<benchmark>@<version>/<split>-admission.json
```

实现文件为 `scripts/audit_v2_artifacts.py`，只依赖 Python 标准库；它不会启动容器、调用模型、导入 benchmark 包或读取 provider 配置。输入必须是 JSON 形式的 `racer-v2-results-envelope`，并以**唯一的** `records` list 作为 canonical container；任一 `entries/results/rows` alias、多个容器、未知顶层字段或 nested baseline map 都是 `NO-GO`。输出为 `racer-v2-artifact-admission-v2`，包含 `verdict`、各 G1/G2/G3/G4/G5/G7 检查、行计数与可定位 issue；退出码 `0=PASS`，`2=NO-GO`，不可读输入为 `64`。

该检查 fail-closed：主比较行必须有完整 paired identity、非空 baseline、trial、model resource、`evaluation_tier="main"`、冻结 baseline registry version 与 64 位 source-manifest SHA-256 anchor；`paired_identity` 必须可从 `task_id + environment_contract` 重算。恢复成功必须有 `strict_replay=true`、`counterfactual_supported=true`、`replay_valid=true`，并提供严格 replay receipt、源契约和由 `replay_run_id` 重算的 expected replay contract。退款或 response loss 必须有对账后的实体级 witness；任何**顶层或嵌套** oracle truth/完整 fault schedule/未来状态/秘密字段或值模式都会拒绝 artifact。canonical `deduplication` 必须完整、`dropped_count=0`、无 legacy retained row；因此 serializer 预先静默丢弃的重复也不能进入主表。legacy/pilot 行不再被本审计器接纳为主表输入。runner 必须在源 artifact 写入 `protocol_id`、`trial_id`、`model_resource_id`、`strict_replay`、`evaluation_tier`、baseline registry version、source-manifest anchor、`main_comparison` 与 `legacy`；evaluator 必须将这些字段及 replay/refund public evidence 传播到每个 baseline-derived row，canonical serializer 将 baseline map 展开成一行一个 baseline。审计器不能替代 G0/G1/G6/G8 或实际环境验证，`PASS` 也不等价于主会放行。

### 11.2 运行前 planned manifest 与 NO-GO 预检

运行前先从冻结的 E1/E2 matrix 生成 **planned-only** manifest；此操作只读取本地 JSON 和 protocol 文本，不启动 Docker、模型或 benchmark，也不读取 `model.json`：

```bash
python scripts/benchmark_preflight.py --build \
  experiments/local-flight-matrix.json \
  experiments/local-flight-extended-matrix.json \
  --protocol reports/racer-v2-benchmark-protocol.md \
  --output output/racer-v2-preflight-planned-2026-09-02.json

python scripts/benchmark_preflight.py --audit \
  output/racer-v2-preflight-planned-2026-09-02.json \
  --output output/racer-v2-preflight-audit-2026-09-02.json
```

`benchmark_preflight.py` 只依赖 Python 标准库。manifest 固定记录 protocol hash、每个 matrix hash、`episode_id`、`source_run_id`、baseline、`trial_id=0..4`、`strict_replay=true` 的 planned cells；当无无密钥 model registry 时，cell 的 `model_resource_id=null` 被明确标记为未绑定，绝不从 provider 配置猜测资源。它绝不把 planned cell 写成 executed artifact。审计输出 `racer-v2-preflight-audit-v1`，退出码为 `0=PASS`、`2=NO-GO`、`64=invalid input`。在真实无密钥 model registry、完整 5-trial 覆盖和 executed artifact 缺失时，审计必须 fail-closed，至少报告 `G0_MODEL_REGISTRY_MISSING`、`G8_EXECUTED_ARTIFACTS_MISSING`。

当前生成的 manifest 是 `output/racer-v2-preflight-planned-2026-09-02.json`：E1 为 15 个 task cell × 3 baseline × 5 trial = 225 个 planned baseline-trial cell，E2 为 18 × 3 × 5 = 270 个，总计 495 个。它们均显式标为 `evaluation_tier="pilot"`、`baseline_registry_version="local-flight-pilot-v1"`、`main_comparison=false`，不构成 benchmark 结果、主会 baseline coverage 或主会数字。

## 12. 明确 GO 条件

正式主会结果表仅在以下条件**全部**满足时标记 `GO`：

- 每个预注册 split、task/fault cell、baseline、model resource 和 5 个 trial 均有 executed artifact；planned 与 executed 清单逐项相等。
- G0–G8 全部通过并由第二位审计者复核；无未解决 blocker。
- 100% 主比较行具备完整 paired identity；完整配对重复为 0；所有 legacy/incomplete 行排除在主表之外并单列。
- 所有宣称支持的反事实分支 `replay_valid=true`；不支持或不一致分支全部 fail closed 且不计恢复成功。
- 所有退款/取消副作用尝试均有实体级可验证 witness；witness 缺失、HTTP 成功但无 witness 或 response loss 未对账时为 `NO-GO`。
- truth isolation probe 无可利用泄漏；oracle 目录不可被 agent 侧读取；模型密钥、`model.json` 凭据和授权 header 未进入任何 artifact。
- 公开环境版本、adapter、Python、依赖和容器 digest 已锁定；原生 reward 与转换后的 success 在验收样本上一致；无法证明状态等价的 τ² counterfactual 标记 unsupported，不报告恢复数字。
- 排除率不超过 5%，且无 split 完全缺失；所有 timeout、retry exhaustion、infrastructure_error 和 unknown side effect 已按本协议计数并披露。
- derived/summary 可由 raw 在干净环境重建；CI、统计检验、去重和成本总账可复现，且结果 envelope/checksum 通过审计。

若任一条件不满足，发布状态必须为 **NO-GO**，只能报告 blocker、审计证据或 pilot，不得写成主会 benchmark 结论。当前依据 2026-09-02 离线确认链，状态保持 **NO-GO**：protocol、planned manifest 与离线审计已冻结，但尚无无密钥 model registry、executed v2 artifact、live τ² adapter 或隔离容器端到端证据。
