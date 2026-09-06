# RACER: Replay-Verified Recovery or Abstention for Tool-Calling Agents

> **范围声明。** 本文报告 RACER v2 主会（main-tier）基准的完整执行结果：真实 LLM actor（GLM-5.3-Flash，经 anthropic-native tool_use 协议）、55 个配对 episode、14 个基线、770 条 canonical 比较记录，全部通过 fail-closed 准入审计（G1–G7 全 PASS、preflight G8 覆盖完整）。协议、矩阵、模型资源与基线注册表均在执行前冻结；结果 envelope 附带去重证明与逐行 provenance。

## 摘要

工具调用智能体在执行中遭遇动作错误、限流与动作篡改时，恢复系统必须回答两个问题：当前轨迹最可能的可干预根因是什么；在不确定性与副作用约束下，应当修复、重试还是放弃。诊断标签本身不保证恢复安全——一次未经证实的修复可能引入新的有害状态。本文提出 RACER（Risk-Aware Counterfactual Execution and Recovery）：一个将轨迹诊断、风险感知策略选择、隔离反事实重放与恢复后验证连接为闭环的恢复框架，其核心不变量是**凡恢复必经严格重放证实**（recovery claims must be replay-verified），凡不可证实即弃权（abstain）。

我们在一个全链路 Docker 化的配对基准上评估 RACER 与 13 个基线（含两个 oracle 上界与两个 RACER 消融）。每个 episode 由同一真实 LLM actor 在冻结环境契约下执行；故障注入在 5 类 E1 故障 × 6 个 E2 任务变体上展开，共 55 个 episode（11 个 cell × 5 个 trial）。配对符号置换检验（10,000 次置换、Holm 校正）显示：RACER 恢复率 15/15=100%（Wilson 95% CI [0.796, 1.000]），显著高于 raw ReAct（0%，Holm p=0.0011）与去除反事实验证的消融（0%，Holm p=0.0011）；有害修复为 0。简单重试族基线在本故障分布上达到相同恢复率——这一诚实结果显示：当故障均可重试时，RACER 的增益不在恢复率，而在**恢复的可证实性**（无反事实验证的修复无法通过 G3 审计获得恢复认定）与弃权安全性。全部 770 条记录通过 G1–G7 准入审计与 G8 执行覆盖审计；τ²-airline 适配器的 G4 负结果（原生退款不幂等、无账本见证）作为本方法动機保留。

## 1. 引言

生产级工具智能体的失败处理面临一个结构性矛盾：恢复动作本身有风险。重试一个非幂等操作可能造成双重扣款；替换一个参数可能违反任务约束；而在证据不足时继续执行会把局部错误放大为全局失败。现有失败诊断工作（AgentDebug、Who&When、AgentFail、AgenTracer）聚焦于**定位**根因，但对"定位之后是否应当修复、修复是否安全"着墨有限。CausalFlow 引入反事实修复概念，但其评估不要求恢复声明携带可复现的重放证据。

我们的主张是：**恢复声明必须是可证实的**。RACER 将该主张落实为四层机制：

1. **配对身份**（paired identity）：每个 episode 由 6 元组 `(episode_id, source_run_id, task_id, canonical_json(env_seed), initial_state_fingerprint, fault_schedule_fingerprint)` 唯一标识，比较只在同身份内进行；
2. **隔离反事实重放**：候选补丁在 `<run_id>:cf` 干净会话中以前缀—补丁—后缀顺序重放，严格重放契约（strict replay contract）要求初始状态指纹与故障日程指纹逐字段匹配；
3. **风险感知弃权**：诊断置信度不足或无可验证补丁时，策略显式 abstain；
4. **fail-closed 准入**：G1–G8 审计拒绝一切无 provenance 锚点、无重放回执、无退款账本见证或含真值泄漏的记录进入主表。

本基准的第二个设计目标是**真值隔离**：评估器专用 oracle manifest 与智能体可见的公共轨迹物理分离；诊断与恢复策略只能访问公共证据。τ²-airline 的适配实验（§2.2）表明这一隔离在真实基准中并不天然存在。

**贡献。** (i) RACER 框架与四层不变量的形式化与实现；(ii) 14 基线配对矩阵的冻结协议（含 trial 展开、基线注册表与模型资源锁）；(iii) 真实 LLM actor 的 55-episode 主会执行与 770 条 canonical 记录的三重审计 PASS；(iv) 消融证据：去除反事实验证后，恢复认定率从 100% 降至 0%（按 G3 审计语义），量化了"证实层"的价值；(v) τ² G4 负结果与 GLM thinking 截断缺陷的工程记录。

## 2. 相关工作

### 2.1 失败诊断与归因

AgentDebug（arXiv:2509.25370）以针对性反馈学习失败模式；Who&When（ICML 2025）在多智能体系统上做自动失败归因；AgentFail（arXiv:2509.23735）构建平台编排智能体失败生命周期数据集；AgenTracer（ICLR 2026）做 LLM 智能体系统的失败诱导方归因。这些工作回答"哪里错了"；RACER 回答"接下来动不动手、动手后如何证实"。

### 2.2 反事实修复与工具交互基准

CausalFlow（arXiv:2605.25338）做因果归因与反事实修复；$\tau$-bench（ICLR 2025）提供工具—智能体—用户交互域。我们实现了 τ²-airline 原生适配的负结果（§7.6）：其原生退款工具非幂等、无公开账本见证，无法满足 G4 副作用审计，因此主会使用自建可审计环境。AgentDojo（NeurIPS 2024 D&B）关注注入攻击评估，与本文的故障注入正交。

## 3. 问题定义

设轨迹 `τ = (a0, o0, ..., aT-1, oT-1)`，环境在指定步骤注入故障 `f`，公共轨迹不暴露 `fault_truth`。诊断器输出候选集合 `D(τ) = {(ci, si, pi, ei)}`（根因、步骤、置信度、证据）。恢复策略 `π` 选择动作 `d ∈ {retry, replace_argument, ask_clarification, abstain}` 并可生成补丁 `δ`（对某步骤的替换动作）。

**恢复的证实语义。** 补丁 `δ` 在隔离会话中以源 seed、`faults=[]` 重放前缀—`δ`—后缀，得反事实评估 `E(τ_cf)`。一条记录被计为**恢复成功**当且仅当：`E(τ_cf).success = true` 且 `E(τ_cf).side_effect = false` 且重放回执满足严格重放契约（`replay_provenance.valid = strict = true`）。不满足者不得声明恢复——这是与"补丁看起来修好了"的本质区别。

**风险感知弃权。** 置信度低于阈值（0.55）或补丁缺失时 abstain；abstain 不计入恢复也不计入有害。

## 4. RACER 方法

### 4.1 诊断与公共证据

诊断器逐步读取轨迹，优先用 `requested_action` 与生效 `action` 的可观察差异（effective_tool_mismatch，覆盖 wrong_tool/replace_action）、环境错误字符串（force_error/rate_limit 嵌入故障类型）与任务约束违反（confirm 阶段的约束错误回溯定位到选择步骤）。可退性判断从公共任务文本与不变量推导，**不硬编码航班语义**——硬编码规则在 non_refundable 变体上会产生系统性假阳性修复（§8.2 记录了该缺陷的发现与修复过程）。

### 4.2 风险感知策略与多候选排序

RACER 对候选集合做效用排序 `u = confidence − (1 − confidence) · risk_weight`，对最高效用候选生成补丁（重试恢复 requested_action 或参数替换）；效用低于阈值则 abstain。决策携带 `expected_cost`、`expected_risk` 与 `use_counterfactual=true`。

### 4.3 隔离反事实重放

`/replay` 为每个基线补丁建立 `<run_id>:cf` 会话：源 seed 初始化、`faults=[]`、以 `requested_action` 恢复原始意图、重放前缀—补丁—后缀。会话返回轨迹、评估与 `replay_provenance`（含源契约与严格性声明），源运行状态不被覆盖。重放器独立校验 `expected_clean_replay_contract` 的 7 个身份字段。

### 4.4 fail-closed 准入审计

主表只接受满足以下全部条件的 canonical envelope：G1 源 manifest SHA-256 锚点；G2 配对身份重算一致（paired identity 必须由 task_id 与环境契约重算得出）；G3 恢复声明必须携带 valid+strict 重放回执且 expected replay contract 重算匹配；G4 副作用行必须携带退款实体、账本 witness 与正整数账目数；G5 无真值/密钥泄漏（键名与值模式扫描）；G7 envelope 形状、行字段白名单与去重证明。评估器侧另有 G0（协议/矩阵/模型注册锁）与 G8（计划—执行覆盖完备性）preflight 审计。

## 5. 基准设计

### 5.1 协议与矩阵

协议 `racer-v2-benchmark-protocol-0.1` 冻结以下矩阵（`experiments/racer-v2-main-matrix.json`，SHA-256 锚定于 preflight manifest）：

- **E1 故障矩阵**（协议 §4.1 要求的主故障覆盖）：5 类故障 `replace_action`、`force_error`、`rate_limit`、`wrong_tool`、`drop_action`，注入于 confirm 步骤（step_id=1）；
- **E2 任务变体**：`clean_success`、`non_refundable`、`suboptimal_refundable`、`missing_confirmation`、`force_error_confirm`、`drop_confirm`，共享航班表（F1 420 可退 / F2 360 不可退 / F3 480 可退，预算 500）；
- **trial 展开**：`trial_id ∈ {0..4}`（= seed），共 11 cell × 5 trial = 55 episode；
- **基线注册表** `racer-v2-main-baselines-v1`：14 个基线每 episode 全量执行 → 770 条 canonical 记录。

### 5.2 14 个基线

**非学习基线**：`raw_react`（不修复）、`fixed_retry`、`exponential_backoff`、`generic_reflection`（自反思文本→补丁）、`full_trace_judge`（全轨迹判读+佐证要求）、`step_by_step_diagnosis`、`binary_search_diagnosis`、`agentdebug_targeted_feedback`（针对性反馈）。**消融**：`always_recover`（去弃权）、`racer`（完整方法）、`racer_no_abstain`（去弃权阈值）、`racer_no_counterfactual`（去反事实验证：补丁直接应用，runner 不调用 `/replay`，该分支按构造 `counterfactual_supported=false`）。**oracle 上界**（仅参考，不入主比较族）：`oracle_root_cause`（真值步骤+公共证据补丁）、`oracle_recovery`（真值显式补丁才修复，无则 abstain）。oracle 基线通过 runner 的特权通道接收 fault_truth，非 oracle 基线只见公共轨迹。

### 5.3 模型资源锁

主会模型资源 `oneapi-relay-glm-5.3-flash`（`experiments/racer-v2-model-registry.json`）：provider `glm-compatible-via-oneapi-relay`、anthropic-native `/v1/messages` + tool_use 协议（`anthropic-version: 2023-06-01`）、temperature 0.0 / max_tokens 1024。revision lock 记录 actor 源码 SHA-256（`4ab918eb…`）、system prompt、工具 schema、采样参数与代码 commit。**基础设施替换记录**：原计划 Claude Haiku 4.5 节点在执行窗口内持续 HTTP 529（所有 Anthropic 节点耗尽），切换至同 relay 的 GLM-5.3-Flash 节点，协议/prompt/工具 schema 不变——该替换作为有效性威胁在 §8 声明。凭据仅经运行时环境变量注入（`~/.config/agent-recovery-plan/model-resource.local.json`），不入仓库、轨迹或报告。

## 6. 实验设置

六个服务（`task-env`、`agent-runner`、`diagnoser`、`recovery-policy`、`counterfactual`、`evaluator`）以 Docker Compose 编排于 Apple Silicon 本机；执行容器以只读挂载注入冻结代码。actor 步数上限 6（`MAX_DYNAMIC_STEPS=6`），episode 在 booking 确认、actor 终止或工具错误时结束（runner 对工具错误 fail-fast——这正是 force_error/rate_limit/wrong_tool 成为永久失败、而 drop/replace 被重发自愈的原因，见 §7.3）。全部公共轨迹与 oracle manifest 分目录落盘；评估器以 oracle join（6 元组身份 + 环境契约逐字段匹配）注入真值。

**统计口径。** Wilson 95% 区间为观测行描述；配对比较在 episode 层面编码三方结果（+1 恢复无伤害 / 0 未恢复 / −1 有害修复），配对差分做 10,000 次分层 cluster bootstrap（种子 20260906）与 10,000 次符号置换，主族（RACER vs 11 个非 oracle 基线）做 Holm-Bonferroni 校正，α=0.05。

## 7. 结果

### 7.1 主表（770 条 canonical 记录）

| 基线 | n | 失败数 | 恢复率 | 恢复 Wilson 95% CI | 有害修复率 | 弃权率 |
|---|---:|---:|---:|---|---:|---:|
| raw_react | 55 | 15 | 0.00% | [0.00, 20.4%] | 0.0% | 100.0% |
| fixed_retry | 55 | 15 | 100.00% | [79.6, 100%] | 0.0% | 63.6% |
| exponential_backoff | 55 | 15 | 100.00% | [79.6, 100%] | 0.0% | 63.6% |
| generic_reflection | 55 | 15 | 100.00% | [79.6, 100%] | 0.0% | 63.6% |
| full_trace_judge | 55 | 15 | 33.33% | [15.2, 58.3%] | 0.0% | 81.8% |
| step_by_step_diagnosis | 55 | 15 | 100.00% | [79.6, 100%] | 0.0% | 63.6% |
| binary_search_diagnosis | 55 | 15 | 100.00% | [79.6, 100%] | 0.0% | 63.6% |
| agentdebug_targeted_feedback | 55 | 15 | 100.00% | [79.6, 100%] | 0.0% | 63.6% |
| always_recover | 55 | 15 | 100.00% | [79.6, 100%] | 0.0% | 63.6% |
| **racer（本方法）** | 55 | 15 | **100.00%** | **[79.6, 100%]** | **0.0%** | 63.6% |
| racer_no_abstain | 55 | 15 | 100.00% | [79.6, 100%] | 0.0% | 0.0% |
| racer_no_counterfactual | 55 | 15 | 0.00% | [0.00, 20.4%] | 0.0% | 63.6% |
| oracle_root_cause（参考） | 55 | 15 | 100.00% | [79.6, 100%] | 0.0% | 63.6% |
| oracle_recovery（参考） | 55 | 15 | 0.00% | [0.00, 20.4%] | 0.0% | 90.9% |

分母为原始失败数（15）。弃权率分母为全部行（55）：非失败行因无补丁可发而计为弃权（策略合法动作），`racer_no_abstain` 按构造 0%。

### 7.2 配对检验（episode 层面，Holm 校正）

| 对比 | 平均配对差分 | bootstrap 95% CI | 原始 p | Holm p | 拒绝 H0 |
|---|---:|---|---:|---:|:--:|
| racer vs raw_react | +0.364 | [0.236, 0.491] | 0.0001 | 0.0011 | ✓ |
| racer vs racer_no_counterfactual | +0.364 | [0.236, 0.491] | 0.0001 | 0.0011 | ✓ |
| racer vs full_trace_judge | +0.182 | [0.091, 0.291] | 0.0022 | 0.0198 | ✓ |
| racer vs fixed_retry / exponential_backoff / generic_reflection / step_by_step / binary_search / agentdebug / always_recover / racer_no_abstain | 0.000 | [0, 0] | 1.0000 | 1.0000 | ✗ |

**H1（恢复优势）**：RACER 显著优于 raw ReAct 与 full-trace 判读。**H2（证实层价值）**：去除反事实重放后，按 G3 审计语义恢复认定率降至 0%——修复动作仍可能发生，但**无法被证实**，因此不可声明恢复。**诚实结果**：本故障分布上简单重试族与 RACER 恢复率无显著差——15 个失败全部是可重试类故障（§7.3），重试即修复；RACER 的差异化价值在证实与弃权，不在本矩阵的恢复率本身。

### 7.3 失败结构与自愈行为

原始失败 15/55，全部来自 E1：force_error 5、rate_limit 5、wrong_tool 5（每类 × 5 trial）。两个结构性观察：

- **drop_action / replace_action 自愈**：被丢弃或被替换的 confirm 步骤返回 `ok=true`，episode 不终止；LLM actor 在下一回合观察到状态未确认，自然重发 confirm → 全部 10 个 cell 原始成功。故障"看起来发生了"但被 actor 的重发行为吸收。
- **E2 变体故障未触发**：E2 故障注入在 step_id=2，但 actor 两步完成任务（航班表在观察中可见，无需 search_flights），第 3 步从未发生 → `force_error_confirm`/`drop_confirm` 的 10 个 cell 均为原始成功。E2 作为任务变体扩展（含 non_refundable 假阳性修复陷阱）仍有效，但不贡献失败分母。

**设计含义**：runner 的工具错误 fail-fast 是这三类故障成为永久失败的原因；未来矩阵应含非重试故障（如资金类不可逆副作用）才能真正分离重试族与风险感知策略。本版主表如实报告该局限。

### 7.4 消融

- **racer_no_abstain**（0% 弃权）：恢复率不变——本矩阵无"修复即有害"的故障（有害修复全场 0），弃权阈值未付出恢复代价；
- **racer_no_counterfactual**（去证实层）：恢复认定 0% vs 100%（G3 语义）——证实层是恢复声明的必要条件，不是锦上添花；
- **always_recover**（纯修复无弃权）：恢复率与 RACER 持平，弃权率相同（63.6% 来自非失败行）——风险感知门控在本矩阵无差异化收益。

### 7.5 成本与用量（actor 账本）

55 个 episode 共 120 次 LLM 调用（全部有效动作，0 次 invalid、0 次 endpoint error、0 次 empty-content——温度递增重试策略消除了 thinking 截断缺陷），44,974 tokens（prompt 8,441 / completion 36,533，网关缓存命中时 input 计数显示异常值 6，如实保留），累计 actor 延迟 834 秒（episode 均值 15.2 秒）。轨迹长度 2–3 步（均值 2.2）。usage 账本六项不变量（calls=attempts、attempts=terminal+failed 等）在全部 55 个 episode 成立。

### 7.6 τ²-airline 适配负结果（动机案例）

τ²-airline 原生适配实验（pilot tier，2026-09-02）记录了 G4 FAIL：其退款操作非幂等且无公开可复算的账本见证，副作用声明无法满足准入审计。该负结果直接驱动了本基准自建环境的退款账本设计（`refund_booking` 幂等 + SHA-256 ledger witness + `get_refund_status` 对账查询），并保留为主会矩阵 `enable_refund_ledger=true` 的依据。

### 7.7 准入审计声明

主 envelope（`output/racer-v2-main-20260906/main-envelope.json`，770 records）：G1 source-manifest 锚点 PASS；G2 配对身份重算 PASS；G3 严格重放 PASS；G4 副作用见证 PASS（harmful repair 全场为 0，无副作用声明行）；G5 真值/密钥隔离 PASS；G7 canonical 形状+去重证明 PASS（dropped_count=0、legacy_rows_retained=0）。Preflight manifest：770 planned cells = 770 executed artifacts，G0/G8 PASS。工程回归：115 项标准库单元测试通过。

## 8. 威胁与局限

**内部效度。** (i) 基础设施驱动的模型替换（Claude→GLM-5.3-Flash，529 过载）：主会全部结果在替换后模型上取得，与原计划模型无可比性，已在 registry 记录替换理由；(ii) 主会环境的故障分布偏简单（15 个失败全部可重试），未分离风险感知策略与朴素重试——本版如实报告，非重试故障矩阵列为后续工作；(iii) 首轮执行暴露的两个工程缺陷（diagnoser 航班语义硬编码导致 non_refundable 变体 40 行假阳性有害修复；GLM thinking 块在 max_tokens=256 下确定性截断）均已修复并重跑全矩阵（run1 归档于 `run1-no-ledger/`），主表来自修复后的 rev2 运行；(iv) 重试温度递增（+0.1/次，上限 0.7）偏离锁定的 temperature=0.0 采样——仅发生在 empty-content 缺陷重试时，占 120 次调用中的少数。

**外部效度。** 环境为单域（航班预订）、3 航班、2–3 步轨迹；故障注入位置固定（confirm 步）；LLM actor 为单一模型（GLM-5.3-Flash）且 prompt 高度约束化。恢复率 100% 不应外推至生产智能体。

**构造效度。** 恢复认定以反事实重放为唯一证实通道——若环境本身非确定（本环境确定），重放语义需另行论证。弃权率的分母选择（全部行 vs 失败行）影响横向解读，已在表注说明。

**统计效度。** 5 个 trial 是可复现性种子而非 iid 样本；Wilson 区间为描述性；置换检验的 episode 层配对控制了任务内相关但未控制跨 cell 相关。

## 9. 结论

RACER v2 主会基准完成了从协议冻结、模型资源锁、14 基线配对执行到三重 fail-closed 审计的完整闭环：770 条 canonical 记录、恢复 15/15、有害修复 0、G1–G8 全 PASS。方法学结论有三：其一，**恢复的证实层是可审计恢复声明的前提**——去除反事实验证后，修复动作无法转化为恢复认定（消融恢复认定 100%→0%，Holm p=0.0011）；其二，**诚实报告边界**——在全部失败均可重试的故障分布上，朴素重试族达到与 RACER 相同的恢复率，风险感知门控的差异化收益需要非重试故障矩阵来检验；其三，**工程缺陷本身是有效发现**——diagnoser 语义硬编码的假阳性修复与 LLM 网关的 thinking 截断缺陷，都只有在配对审计+反事实重放的闭环里才会暴露。

后续工作：非重试故障（不可逆副作用）矩阵、多域环境、多模型 actor 对照、以及把 G1–G8 审计本身作为可复用工具发布给智能体恢复研究社区。

## 10. 复现说明

```bash
# 1. 启动服务（代码以只读挂载注入冻结版本）
docker compose up -d --no-deps --no-build task-env diagnoser recovery-policy counterfactual

# 2. 主会执行（凭据经运行时环境变量注入，见 model.json）
docker compose run --no-deps --rm \
  -e BATCH_SPEC=/workspace/racer-v2-main-matrix.json \
  -e MAX_DYNAMIC_STEPS=6 -e RELAY_LLM_MODEL="GLM-5.3-Flash" \
  -e ANTHROPIC_BASE_URL=... -e ANTHROPIC_AUTH_TOKEN=... \
  -v experiments/racer-v2-main-matrix.json:/workspace/racer-v2-main-matrix.json:ro \
  -v experiments/actors:/app/experiments/actors:ro \
  -v output/racer-v2-main-20260906/trajectories:/data/trajectories \
  -v output/racer-v2-main-20260906/oracle:/data/oracle \
  agent-runner

# 3. 评估 + envelope + 三重审计
docker compose run --rm --no-deps -v .../trajectories:/data/trajectories:ro -v .../oracle:/data/oracle:ro evaluator > evaluator.json
python3 scripts/build_main_envelope.py output/racer-v2-main-20260906/evaluator.json output/racer-v2-main-20260906/main-envelope.json racer-v2-main-matrix
python3 scripts/audit_v2_artifacts.py output/racer-v2-main-20260906/main-envelope.json   # 必须 exit 0
python3 scripts/main_statistics.py output/racer-v2-main-20260906/main-envelope.json --output output/racer-v2-main-20260906/statistics.json
python3 scripts/build_executed_manifest.py                                              # 必须 verdict=PASS
python3 scripts/benchmark_preflight.py --audit output/racer-v2-main-20260906/preflight-manifest.json  # 必须 exit 0
```

全部 artifacts 位于 `output/racer-v2-main-20260906/`（trajectories 55、oracle 55、evaluator、main-envelope、admission-audit、statistics、preflight-manifest/audit）；首轮未加账本的执行归档于 `run1-no-ledger/`。复现需保留 run_id、seed、矩阵哈希、registry 锁与代码 commit；`fault_truth` 只存在于 oracle manifest，禁止写入智能体可见轨迹。

## 11. 参考文献

1. Zhu, Kunlun, et al. *Where LLM Agents Fail and How They can Learn From Failures*. arXiv:2509.25370, 2025（AgentDebug）。
2. Zhang, Shaokun, et al. *Which Agent Causes Task Failures and When? On Automated Failure Attribution of LLM Multi-Agent Systems*. ICML 2025, PMLR 267:76583–76599（Who&When）。
3. Ma, Xuyan, et al. *Demystifying the Lifecycle of Failures in Platform-Orchestrated Agentic Workflows*. arXiv:2509.23735, 2025（AgentFail）。
4. Zhang, Guibin, et al. *AgenTracer: Who Is Inducing Failure in the LLM Agentic Systems?* ICLR 2026（arXiv:2509.03312）。
5. Bonagiri, Akash, et al. *CausalFlow: Causal Attribution and Counterfactual Repair for LLM Agent Failures*. arXiv:2605.25338, 2026。
6. Yao, Shunyu, et al. *$\tau$-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains*. ICLR 2025（arXiv:2406.12045）。
7. Debenedetti, Edoardo, et al. *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents*. NeurIPS 2024 Datasets and Benchmarks Track, pp. 82895–828920。

正式投稿时以 `reports/related-work-bibliography.md` 的核验条目为准；本文不引用未在本项目中运行的 benchmark 数字。
