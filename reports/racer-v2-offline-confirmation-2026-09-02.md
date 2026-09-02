# RACER v2 离线确认链收敛报告

- **日期：** 2026-09-02
- **范围：** 仅本地静态与离线验证。
- **明确未执行：** 远程模型调用、`model.json` 中的 provider、Docker runtime、τ-bench / τ²-bench live smoke、正式 benchmark。
- **放行结论：** **NO-GO（正式主会结果表）**。

## 本轮已收敛的 v2 契约

1. **环境与配对身份。** 新增 `services/common/environment_contract.py`，为每个源运行构造 `episode_id`、`source_run_id`、seed、初始环境指纹、故障日程指纹与完整环境指纹。指纹使用稳定 JSON 编码与 SHA-256；故障日程仍保持 evaluator-only，不向 agent 可见轨迹泄漏。
2. **严格反事实 replay。** `counterfactual` 支持 `strict_replay=true`：必须提供并逐字段匹配源契约派生的 replay provenance；缺失或不一致时 fail closed，返回 `counterfactual_supported=false`、`replay_valid=false`，不会把该分支计为恢复。后缀也统一重放 `requested_action`，不再将受故障影响的 effective action 当作 agent 原意。
3. **E2 退款证据闭环。** local task environment 新增 opt-in 的 refund ledger：以 `refund_entity_id` / `idempotency_key` / `refund_id` 为去重实体，而不是全局交易标记。每个提交写入可复算 `ledger_witness`；同一实体重试返回相同 witness 与 `idempotent_replay=true`，不同实体允许独立退款。`response_loss` 在副作用提交后仅丢失响应，要求经 `get_refund_status` 显式对账。
4. **adapter 边界。** τ² airline adapter 新增 `refund_entity_id()` 与 `validate_refund_witness()`，拒绝“HTTP 成功但无 witness”的退款响应；遇到 response loss/retryable 响应不推断未提交，要求上层走对账路径。
5. **evaluator/analyzer 对齐。** evaluator 输出唯一 canonical `racer-v2-results-envelope.records`；多 alias container 直接拒绝，baseline map 必须展平为一行一个 baseline。主比较 row 的 `paired_identity` 由任务和环境契约重算，统计层对 v2 recovery claim 强制 `strict_replay=true`、`counterfactual_supported=true`、`replay_valid=true`，缺任一项不计恢复成功。
6. **Docker 构建可见性。** 为使用 v2 shared contract 的 agent-runner、counterfactual、evaluator 更新 Compose build context 和 Dockerfile COPY 路径；新增静态集成测试确保三个镜像均复制同一契约文件。本轮只做 Compose 静态解析，未 build/run。
7. **runner 交接证明。** 新增离线集成级测试，验证 runner 在 strict mode 向 counterfactual 传递一致的 `episode_id`、源环境契约和由源契约派生的 replay provenance，而非由下游猜测配对身份。
8. **主表 metadata、Oracle、baseline catalog 与 admission 闭环。** runner 现传播 `protocol_id`、`trial_id`、`model_resource_id`、`strict_replay`、`evaluation_tier`、baseline registry version、`source_manifest_sha256`、`main_comparison` 与 `legacy`；未知 baseline ID fail closed，且只有 catalog 显式 oracle baseline 可接收 evaluator-only fault truth。evaluator 仅在 `run_id/task_id/source_run_id/episode_id/env_seed` 及完整 environment contract 精确一致时接纳 oracle manifest，拒绝 `None==None` 和错误/缺失 manifest。admission v2 检查唯一 `records`、顶层/嵌套泄漏、契约重算、replay receipt、dedup proof 与 pilot/main 分界；此前旧 synthetic fixtures 因缺少新 provenance 被预期拒绝，不能再作为 PASS 证据。

## 离线验证证据

| 检查 | 结果 |
|---|---|
| v2 定向/集成级契约测试 | 通过（含 runner→replayer provenance、Oracle 完整身份绑定、truth 隔离和 Docker shared-contract COPY 路径） |
| 实验规范 strict-replay 预置测试 | 2 项通过（E1/E2 每个 cell 均显式携带 `episode_id` 与 `strict_replay=true`） |
| artifact admission 审计器 | v2 fail-closed 单测通过：多 alias、schema+entries、顶层泄漏、契约/paired mismatch、replay receipt、serializer-hidden duplicate、legacy/pilot 主表混入均拒绝 |
| canonical → admission 衔接 | 旧合成 fixture 因缺少 source anchor、完整契约与 strict replay receipt 被预期拒绝；主表尚无可 PASS 的 executed artifact |
| metadata / Oracle / truth-isolation 定向回归 | 通过 |
| 全量 Python 单元测试 | 90 tests 通过 |
| 核心模块 `py_compile` | 通过（6 个本轮修改的核心模块/脚本） |
| E1 matrix 生成 dry-run | 成功（5 fault types × 3 seeds = 15 planned task cells；3 baselines 后为 45 planned offline baseline runs） |
| E2 extended matrix 生成 dry-run | 成功（6 task variants × 3 seeds = 18 planned task cells；3 baselines 后为 54 planned offline baseline runs） |
| `docker compose config --quiet` | 通过（静态校验；未启动 runtime） |
| Docker 镜像构建 | 6 个 v2 服务镜像全部构建成功（python:3.13-slim 基底；镜像 ID 记录于 output/smoke-v2/run-record.json） |
| 隔离容器端到端 smoke（G8） | **通过**：deterministic actor 单任务 replace_action；轨迹无 truth（G5）、Oracle 完整身份 join 成功、oracle 分支 strict replay receipt 有效（replay_run_id=smoke-v2-ra-0:cf）、pilot envelope 被 admission 正确拒绝；全程未调用远程模型 |
| planned manifest / preflight 审计 | 新增 8 项单测通过；E1+E2 共 495 个 planned baseline-trial cell，审计 `NO-GO/2`（符合预期） |
| τ² airline adapter 阶段 A（锁定安装 + 工具语义实证） | **完成，G4 前置判定 FAIL**：tau2==1.0.1（fc0055d）隔离安装成功，50 任务加载通过；但重复 cancel 实证发现原生环境账本不幂等（1→2→4→8 指数膨胀）、无 witness 字段、收据对象被原地污染、用户余额不结算、无对账工具。退款分支必须 `counterfactual_supported=false` 或引入外部 witness 层。证据：`output/tau2-airline-adapter-smoke-2026-09-02.json` |
| relay paired pilot（真实远程模型，pilot tier） | **完成**：Claude Haiku 4.5 经 oneapi relay 真实执行，故障精确激活，recovery 反事实回放成功（state hash 与 Gemma pilot 收敛），usage 恒等式全成立，admission 审计 pilot-tier 预期 NO-GO、其余五关卡全 PASS。证据：`output/relay-llm-paired-pilot-20260902/pilot-summary.json` |

## 已冻结的主会运行协议

新增 `reports/racer-v2-benchmark-protocol.md`（`racer-v2-benchmark-protocol-0.1`），预先冻结模型秘密隔离、版本/环境、OOD split、防泄漏、完整 paired identity、5 trial 主表门槛、基线、统计、超时/重试、数据布局和 G0–G8 审计关卡。`scripts/audit_v2_artifacts.py` 现为离线、fail-closed 的 `racer-v2-artifact-admission-v2`：验证 G1 source anchor、G2 paired/contract 重算、G3 strict replay receipt、G4 refund witness、G5 truth/secret isolation 与 G7 唯一 canonical envelope/dedup proof，输出 machine-readable `PASS` 或 `NO-GO`。

## 无密钥 registry 与凭据卫生（本轮新增）

- `experiments/racer-v2-model-registry.json`（`racer-v2-model-registry-v1`）：登记 active 的 `deterministic-local-actor-v1`（仅限 pilot tier，附配置 SHA-256）与 planned 的 `anthropic-oneapi-relay`（revision 未锁定，不可绑定 planned cell；凭据仅声明环境变量来源，不含值）。
- `experiments/racer-v2-baseline-registry.json`（`racer-v2-main-baselines-v1`）：冻结协议第 7 节 14 个主会 baseline 目录；除共享服务哈希外，所有 LLM baseline 均为 `implemented=false`，不可进入主会 planned cell。
- 真实凭据已从项目目录迁出至 `~/.config/agent-recovery-plan/model-resource.local.json`（仅运行时经环境变量注入）；`model.json` 改为无密钥模板。原 token 长期明文存放，建议在 provider 侧轮换/撤销。

进一步新增 `scripts/benchmark_preflight.py`，从冻结 matrix 生成 planned-only manifest，并审计协议/矩阵 hash、planned paired provenance、5-trial 覆盖、pilot/main tier、无密钥 model registry 与 executed artifact registry。生成物为 `output/racer-v2-preflight-planned-2026-09-02.json` 和 `output/racer-v2-preflight-audit-2026-09-02.json`：E1 225、E2 270，合计 495 个 `evaluation_tier=pilot`、`main_comparison=false` 的 **planned** baseline-trial cell；在无 registry 时其 `model_resource_id=null` 被明确标记为未绑定，审计预期返回 `NO-GO/2`，唯一 blocker 为 `G0_MODEL_REGISTRY_MISSING` 和 `G8_EXECUTED_ARTIFACTS_MISSING`。该协议、manifest 和审计器是**运行前/运行后控制**，不是 executed evidence；当前无 v2 artifact，因此不改变本报告的 NO-GO 状态。

## 仍阻止正式 benchmark/主会主表的事项

1. **没有 executed v2 artifact。** 本轮没有启动 Docker runtime、远程模型或 τ² live 环境，因此不存在可用于结果表的 v2 run、原始轨迹、oracle manifest、derived rows 或统计量。
2. **E2 仍是本地契约。** refund ledger / response-loss 用 deterministic local environment 与 fake adapter 边界验证。τ² airline 阶段 A 实证（2026-09-02）已确认原生环境**不提供**实体级退款 witness：若后续要在 τ² 上验证恢复，必须先在 adapter 层构建外部 witness 包裹（阶段 D），或对退款分支显式 `counterfactual_supported=false`。
3. **完整 runner→adapter→counterfactual→evaluator 尚未 live 验证。** 本轮已在隔离容器完成 runner→task-env→diagnoser→recovery-policy→counterfactual→oracle/evaluator 的 local v2 端到端 smoke（G8 证据，见 `output/smoke-v2/`），但 τ² airline adapter 的 live smoke 仍未执行；smoke 数字不构成任何结果。
4. **无密钥模型资源、主会 baseline registry 与实际协议执行仍未完成。** protocol/matrix/planned manifest 已锁定，但 `model_registry=[]`，也尚未冻结独立的主会 `baseline_registry`：实际 `model_resource_id`、provider/model revision、baseline 实现 hash、容器 image digest、代码 commit 和已执行 manifest 均未登记；`model.json` 中包含凭据，必须只以本地环境变量/密钥管理方式读取，不能进入代码、轨迹、报告或提交物。
5. **没有 executed artifact。** preflight 已明确登记 495 个 `evaluation_tier=pilot` 的 planned baseline-trial cell，但 `executed_artifacts=[]`；planned 数量不能写成结果表、主会 coverage 或性能数字。
6. **旧 synthetic PASS 证据已撤销。** admission v2 要求 source anchor、精确环境契约、严格 replay receipt、clean dedup proof 与 main-tier registry；旧 fixture 不满足这些字段，现被预期拒绝。需在真实、隔离的 v2 执行链产出后新建 artifact 才能尝试 PASS。
7. **主会证据尚不足。** 当前 local-flight 固定规则原型不能支持 LLM/benchmark 比较；需先形成 v2 executed artifact，并运行 admission 审计、完成数据泄漏、重放一致性、模型调用使用量隔离、成本与风险指标审计。

## 恢复放行的最小序列

1. ~~建立无密钥 model registry 与 baseline registry~~ **已完成**（`experiments/racer-v2-model-registry.json`、`experiments/racer-v2-baseline-registry.json`；凭据已迁出仓库）。
2. ~~Docker build + 隔离容器端到端 smoke~~ **已完成**（`output/smoke-v2/`，G8 接口/隔离证据，verification PASS；未调用远程模型）。
3. ~~对 τ² airline 完成单任务、固定版本、无正式汇总的 adapter smoke~~ **已完成（阶段 A），结论为负**：真实 refund 语义不提供实体级 witness——账本不幂等、无 witness 字段、收据被原地污染、用户余额不结算、无对账工具（`output/tau2-airline-adapter-smoke-2026-09-02.json`）。退款/取消分支必须 `counterfactual_supported=false`，或在 adapter 阶段 D 引入外部 witness 层后再评估。此实证可作为论文中"公开 benchmark 副作用语义不足以支撑恢复审计"的论据。
4. ~~执行预注册 paired pilot（真实远程模型）~~ **已完成（2026-09-02，pilot tier）**：`experiments/relay-llm-paired-pilot-20260902.json`（v2，task-level provenance）经 Docker 隔离链路（task-env→diagnoser→recovery-policy→counterfactual→oracle/evaluator）执行，模型为 Claude Haiku 4.5（oneapi relay，anthropic-native `/v1/messages` + `tool_use` 协议，凭据仅经运行时环境变量注入）。故障在第二步精确激活（`force_error` on `confirm_booking` @ step_id=1），轨迹形状与 Gemma pilot 一致（`[select_flight F1, confirm_booking]`）；recovery 基线经严格反事实回放成功恢复（counterfactual state hash `0537d007a5fcaedf`，与 Gemma pilot 完全一致——确定性回放跨模型收敛）；raw 弃权、oracle 修复，三基线行为符合设计。actor usage 记账 6 条恒等式全部成立（2 calls，11,240+322 tokens，无 empty tool_use 缺陷）。admission 审计按设计返回 NO-GO（pilot tier 被 G2 主表门拒绝），但全部内容质量关卡 PASS：G1 anchor / G3 strict replay receipt / G4 witness / G5 truth-secret isolation / G7 canonical envelope。产物归档于 `output/relay-llm-paired-pilot-20260902/`（`pilot-summary.json` 为入口）。**这是首个真实远程模型的 executed v2 artifact；不构成任何 benchmark 结果**（`evaluation_tier=pilot`, `main_comparison=false`）。runner 同步增强：`actor_usage` 落盘 + `MAX_DYNAMIC_STEPS` 步数上限（`services/agent_runner/app.py` 与根目录副本一致，91/91 单测通过）。
5. 锁定主会 LLM 资源 revision（`anthropic-oneapi-relay` 已附 pilot 执行证据，但 revision/schema hash 未锁定，仍不可绑定 planned cell），实现主会 baseline（当前 14 个 ID 全部 `implemented=false`）。
6. 完整主会执行：全部 baseline × 5 trial × 全 split；admission + preflight 双审计通过后出结果表，补第二审计者对 G0–G8 的复核。
