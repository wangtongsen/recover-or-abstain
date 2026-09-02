# Recover or Abstain：面向工具调用智能体的风险感知反事实修复原型

> **范围声明。** 本文报告的是一个 deterministic local flight prototype（确定性的本地航班原型），用于验证诊断、修复决策、反事实重放与结果评估的系统闭环。本文**不是** LLM benchmark，不声称代表任何大模型、公开基准或真实航空生产系统的性能。

## 摘要

工具调用智能体在执行过程中可能遭遇动作替换、工具错误、限流或动作丢失。仅给出一个根因标签并不足以保证恢复安全：错误修复可能造成副作用，而在证据不足时继续执行又可能放大损失。本文提出 RACER（Risk-Aware Counterfactual Repair，风险感知反事实修复）方法的一个确定性本地原型。RACER 将轨迹诊断、带置信度的恢复策略选择、隔离的反事实重放以及恢复后验证连接为闭环；当诊断置信度低于阈值或缺乏可验证补丁时，策略显式选择 abstain。系统通过公共轨迹与评估器专用真值清单隔离故障真值，避免智能体直接查询注入配置，并用状态哈希支持重放一致性检查。

最终结果采用冻结的 `reports/local-flight-results.json`，而非混入额外 smoke 运行的 `local-flight-evaluator.json`。冻结报告覆盖 5 类故障、3 个 seed、共 15 个唯一任务单元，并展开为 raw、recovery、explicit-patch oracle（patch-availability-conditional reference）三类基线的 45 条基线记录。在该确定性原型上，recovery 基线在 12 条原始失败中恢复 3 条（25.00%），记录的有害修复为 0；raw 基线不修复，explicit-patch oracle（patch-availability-conditional reference）仅对故障真值含显式可用补丁的情形执行参考上界修复。上述数字只描述当前固定任务、规则策略和故障注入设置，不构成 LLM benchmark、统计显著性或跨环境泛化结论。

## 1. 引言

工具调用智能体需要在外部环境中连续执行搜索、选择和确认等动作。一次错误的工具调用可能使后续状态偏离任务约束，且错误并不总能由单次重试消除。恢复系统因而需要回答两个问题：第一，当前轨迹中最可能的可干预根因是什么；第二，在不确定性、恢复成本和潜在副作用约束下，是否应当修复、重试、请求澄清，还是拒绝继续执行。

本文围绕上述问题实现一个最小但可审计的闭环。系统不依赖在线大模型推理，而使用确定性的本地服务模拟诊断器、恢复策略、反事实重放器和评估器。该设计有两个目的：其一，隔离“方法流程是否闭环”与“语言模型能力”这两个因素；其二，确保每次故障注入、轨迹记录和反事实执行均可复现。

本文的贡献限定为以下工程和方法学要点：

- 给出 RACER 的诊断—决策—重放—验证接口及其风险感知 abstain 规则；
- 实现公共轨迹与 evaluator-only oracle manifest 的真值隔离，防止评测真值泄漏给智能体；
- 在确定性的 local-flight 环境中定义 5 类故障、3 个 seed 的可复现实验矩阵，并提供可追溯的逐基线汇总；
- 明确区分 truth-guided fault replay 与 explicit-patch、patch-availability-conditional reference upper bound，避免将评估辅助信息误报为可用智能体能力。

## 2. 相关工作

相关工作覆盖失败诊断、归因、反事实修复、工具交互与安全评估。AgentDebug 对应 *Where LLM Agents Fail and How They can Learn From Failures*（arXiv:2509.25370，2025，预印本）；Who&When 对应 *Which Agent Causes Task Failures and When? On Automated Failure Attribution of LLM Multi-Agent Systems*（ICML 2025，PMLR 267:76583–76599）；AgentFail 当前 v2 对应 *Demystifying the Lifecycle of Failures in Platform-Orchestrated Agentic Workflows*（arXiv:2509.23735，2025；v1 标题为 *Diagnosing Failure Root Causes in Platform-Orchestrated Agentic Systems: Dataset, Taxonomy, and Benchmark*）；AgenTracer 对应 *AgenTracer: Who Is Inducing Failure in the LLM Agentic Systems?*（ICLR 2026；arXiv 预印本年份为 2025）；CausalFlow 对应 *CausalFlow: Causal Attribution and Counterfactual Repair for LLM Agent Failures*（arXiv:2605.25338，2026，预印本）；工具交互环境 `$\tau$-bench` 对应 *A Benchmark for Tool-Agent-User Interaction in Real-World Domains*（ICLR 2025；arXiv 预印本年份为 2024）；安全评估环境 AgentDojo 对应 *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents*（NeurIPS 2024，Datasets and Benchmarks Track）。本文仅据已核验的正式标题、venue 与版本信息定位这些工作，不引入其未在本项目中运行的 benchmark 数字或实验结论。与这些方向相比，本文关注点被限定在恢复决策而非单纯诊断准确率：在根因不确定时是否采取修复动作、如何用反事实重放验证候选补丁，以及如何将成本与风险纳入决策。

## 3. 问题定义

设智能体在环境中的动作轨迹为 `τ = (a0, o0, a1, o1, …, aT−1, oT−1)`，其中动作包括工具名及参数，观测包含环境状态摘要、可用工具、任务不变量和状态哈希。环境可能在指定步骤注入故障 `f`，但公共轨迹不得暴露 `fault_truth` 或 `faults_applied`。诊断器根据公共轨迹输出候选根因集合 `D(τ) = {(ci, si, pi, ei)}`，其中 `ci` 为根因，`si` 为关联步骤，`pi` 为置信度，`ei` 为可审计证据。恢复策略从候选集合中选择 `retry`、`replace_argument`、`ask_clarification` 或 `abstain`，并可生成补丁 `δ`。

对补丁的验证在隔离的干净会话中进行：重放原轨迹前缀、插入补丁、再重放后缀，得到反事实结果 `E(τcf)`。只有在满足任务成功条件、约束条件和无有害副作用时，修复才被视为有效。原型中，若最高置信度低于 0.55，策略默认 abstain；该阈值是当前实现参数，不是经过独立校准得到的普适阈值。

## 4. RACER 方法

### 4.1 诊断与证据

诊断器逐步读取轨迹，优先使用 `requested_action` 与实际生效的 `action` 之间的可观察差异。当工具名不一致时，生成 `effective_tool_mismatch` 候选；当环境返回违反任务约束的错误时，定位到导致约束违反的选择步骤，而不是仅将错误归因到最后一次确认动作。每个候选附带 `evidence`、`source` 和 `constraint` 字段，并按“根因—步骤”键去重。

### 4.2 风险感知恢复策略

恢复策略选取置信度最高的候选。对选择不可退款航班的候选，策略生成将航班参数替换为 F1 的补丁；对带有明确请求动作证据的工具错误，策略生成同一工具调用的 retry 补丁；对低置信度诊断，策略返回 abstain。每个决策可记录预期成本和预期风险，其中当前原型使用 `expected_risk = 1 - confidence` 作为简单代理，并不将其解释为校准概率。

### 4.3 隔离反事实重放

反事实重放器为每个源运行建立 `<run_id>:cf` 会话，以源 seed 初始化，但显式使用 `faults=[]`，从而在干净环境中执行前缀—补丁—后缀顺序。重放过程优先采用轨迹中的 `requested_action`，避免把故障注入后的生效动作再次当作智能体原始意图。每个会话返回轨迹、评估结果和状态哈希，源运行状态不会被覆盖。

### 4.4 验证与 abstain

评估器检查 `success`、约束满足、最优航班选择和 `side_effect`。在航班任务中，成功要求已确认、所选航班可退款、价格不超过预算，并且是符合约束的最低价格航班。若补丁无法定位到有效步骤、重放未成功或出现副作用，系统不将其计为安全恢复。raw 基线不执行修复；recovery 基线使用公共轨迹诊断；explicit-patch oracle 仅在评估器专用真值中存在可用显式补丁时执行，作为补丁可用性条件下的参考上界。

## 5. 系统实现

原型由六个可独立运行的服务组成：`task-env`、`agent-runner`、`diagnoser`、`recovery-policy`、`counterfactual` 和 `evaluator`，通过 Docker Compose 编排。所有服务使用 Python 标准库 HTTP 服务实现。`task-env` 提供 `/reset`、`/step`、`/observe` 和 `/evaluate` 接口；`agent-runner` 负责运行批量任务、保存轨迹和调用其余服务；`diagnoser` 暴露 `/diagnose`；`recovery-policy` 暴露 `/choose` 与 `/baseline`；`counterfactual` 暴露 `/replay`。

环境状态包含任务描述、预算、已选航班、确认标记和事件列表。状态哈希由排序后的 JSON 状态计算 SHA-256 截断值。公共 `/evaluate` 始终返回脱敏结果；`required_flight_id`、`fault_truth` 和 `faults_applied` 仅保存在 evaluator-only 的独立 oracle manifest 或受控进程内测试中。该隔离使诊断和恢复只能使用轨迹证据，而不能读取注入器配置。

## 6. 实验设置

### 6.1 任务与环境

任务为“预订从 A 到 B 的最低价可退款航班”。候选航班如下：

| 航班 | 价格 | 可退款 | 角色 |
|---|---:|:---:|---|
| F1 | 420 | 是 | 满足约束的最低价可退款航班 |
| F2 | 360 | 否 | 价格更低但违反可退款约束 |
| F3 | 480 | 是 | 可退款但不是最低价 |

预算为 500，确认动作要求显式用户确认。默认动作序列为 `search_flights`、选择 F2、`confirm_booking`；该序列用于制造可诊断的约束违反。

### 6.2 故障矩阵与基线

实验规范 `experiments/local-flight-matrix.json` 声明 5 类故障：`replace_action`、`force_error`、`rate_limit`、`wrong_tool` 和 `drop_action`，每类使用 seed 0、1、2，因此设计矩阵为 `5 × 3 = 15` 个任务单元。每个单元展开 raw、recovery 和 explicit-patch oracle（patch-availability-conditional reference）三类基线。冻结主结果由 `reports/local-flight-results.json` 与对应逐任务评估记录共同核验，覆盖 15 个 task、45 条 baseline rows（`trajectory_count=15`、`baseline_row_count=45`、`fault_type_count=5`、`baseline_count=3`），并为每个故障类型—基线组合保留任务、seed 与 run ID 列表。含额外 smoke 或重复任务的历史工程报告不纳入本文主表或汇总计算。

### 6.3 评估指标

- **原始失败数**：`original_success=false` 的记录数；
- **恢复率**：原始失败记录中 `recovered_success=true` 的比例；
- **有害修复率**：原始失败记录中 `harmful_repair=true` 的比例；
- **abstention rate**：选择 abstain 的记录占全部记录的比例；
- **诊断置信度**：报告提供的 `diagnosis_confidence`，用于描述策略输入，不等同于概率校准指标；
- **step exact、repair steps、latency**：逐任务评估记录包含这些字段；本文仅在有直接记录时引用，不据此添加未核验的 benchmark 数字；
- **LLM usage（仅准入预检）**：真实本地模型产物记录 `attempts`、`responses`、`terminal_responses`、`valid_actions`、`invalid_actions`、`endpoint_errors`、`failed_attempts`、token、cost 与 latency；这些字段用于审计调用开销和失败类型，不将单任务/少量 seed 的 admission preflight 当作性能 benchmark。

## 7. 结果

### 7.1 已核验的实验口径

本文的定量结果**仅**来自冻结文件 `reports/local-flight-results.json`。该文件覆盖 15 个唯一轨迹任务，展开为 45 条基线记录；每个故障类型—基线组合都列出 seed、`task_id` 和 `run_id`。以下工程性事实也由代码、实验规范或测试输出直接支持：

| 项目 | 已核验内容 | 证据来源 |
|---|---|---|
| 实验矩阵 | 5 种故障 × 3 个 seed = 15 个设计单元 | `experiments/local-flight-matrix.json` |
| 结果展开 | 15 条轨迹 × 3 条基线 = 45 条基线记录 | `reports/local-flight-results.json` |
| 基线接口 | raw、recovery、explicit-patch oracle（patch-availability-conditional reference）三类基线均被声明 | 实验规范与 `agent_runner` |
| LLM 准入边界 | Gemma 三 seed clean admission preflight 通过，但该结果不是 fault-recovery benchmark；Qwen、云 provider 和 tau2 live 均未形成可报告 benchmark 指标 | `reports/local-llm-admission-clean-gemma4-e2b-20260901-summary.json`、阻塞报告 |
| 真值隔离 | 公共轨迹与公共 HTTP 评估接口不暴露 `fault_truth` | `task_env`、`agent_runner`、测试 |
| 反事实会话 | 使用 `<run_id>:cf`、源 seed 与 `faults=[]` | `counterfactual`、测试 |
| 工程回归 | 90 项标准库单元测试通过 | 本稿更新时执行的 `python3 -B -m unittest discover -s tests -p 'test_*.py'` |
| 本地 Gemma 准入试点 | 单任务、单 seed 的 force-error fault activation 已验证；recovery 与 explicit-patch reference 均在 clean counterfactual 中成功，side effect=0；该结果不是 benchmark | `experiments/output/reports/gemma-fault-admission-pilot-20260901T060841Z-summary.json` |

### 7.2 冻结主结果

| 基线 | 任务数 | 原始失败数 | 原始成功数 | 恢复成功数（仅原始失败） | 恢复率 | 有害修复数 | 有害修复率 | abstain 数 | abstention rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| raw | 15 | 12 | 3 | 0 | 0.00% | 0 | 0.00% | 15 | 100.00% |
| recovery（RACER） | 15 | 12 | 3 | 3 | 25.00% | 0 | 0.00% | 3 | 20.00% |
| explicit-patch oracle / patch-availability-conditional reference | 15 | 12 | 3 | 0 | 0.00% | 0 | 0.00% | 12 | 80.00% |

表中恢复率的分母为原始失败数。recovery 基线的 3 个恢复成功均来自 `drop_action` 故障的 3 个 seed；其余 `force_error`、`rate_limit`、`wrong_tool` 三类故障在当前规则和轨迹条件下均未恢复成功。`replace_action` 的 3 个冻结单元原始执行已成功，故不构成恢复率分母。所有基线在冻结报告中记录的有害修复数均为 0。

该表应被解释为原型的诊断与反事实恢复链路在一组固定、确定性故障上的行为记录，而非对智能体总体能力的排序。样本量很小，且运行之间仅改变预先指定的 seed；本文不报告显著性检验，统计脚本中的 Wilson 区间仅作观测行的描述性信息，不作总体推断。

### 7.3 真值重放与 explicit-patch 条件性参考的严格区分

本文中的 oracle 相关术语包含两类不同机制，必须分开：

1. **Truth-guided fault replay（真值引导的故障重放）**：评估器从独立 oracle manifest 读取注入故障真值，用于标注故障、在受控评测中核对诊断，并确保反事实会话在相同 seed 下以 `faults=[]` 进行干净重放。这是评估和实验控制机制，不是智能体可查询的信息，也不是一种修复策略。
2. **Explicit-patch oracle / patch-availability-conditional reference（显式补丁 oracle／补丁可用性条件下的参考上界）**：oracle 基线只在故障真值中存在显式可用补丁（如 `patch`、`replacement` 或 `action`）时执行该补丁；没有可用补丁时，该基线 abstain。因而它是“当前显式真值补丁接口”的条件参考上界，而不是保证能修复所有故障的万能 oracle。

在冻结报告中，explicit-patch oracle（补丁可用性条件参考）的 0 个恢复成功、12 个 abstain 反映了当前故障规范中多数 `force_error`、`rate_limit`、`wrong_tool` 和 `drop_action` 条目不携带可用显式补丁；这不能被解释为真值引导的故障重放失败，也不能据此推导 RACER 优于理论完美修复器。含 smoke、历史或重复任务的工程报告均明确排除在本节所有汇总和比较之外。

## 8. 消融、威胁与局限

### 8.1 计划中的消融

当前冻结报告已形成 raw、recovery、explicit-patch oracle（patch-availability-conditional reference）三类基线的可比汇总；由于样本规模有限，仍不足以支撑完整消融。后续应至少完成以下消融：

- 去除 abstain 阈值，比较强制修复与风险感知策略的恢复率和有害修复率；
- 禁用 requested/effective action 差异证据，测量 `wrong_tool` 诊断与恢复的下降；
- 禁用 clean counterfactual suffix replay，仅验证补丁单步结果，比较验证充分性；
- 比较 raw、recovery 与 explicit-patch oracle / patch-availability-conditional reference 的恢复率、修复步数、延迟和副作用；
- 在相同 fault matrix 上改变 seed，并报告置信区间或至少报告每 seed 的结果。

### 8.2 威胁有效性

首先，当前环境只有三个航班和一个短动作序列，根因模式与约束均为人工设计，不能代表真实工具 API 的复杂分布。其次，故障在指定步骤注入，可能使定位问题比自然发生的生产故障更容易。再次，冻结主表按 15 个唯一任务和三类基线汇总；其他含 smoke、历史或重复任务标识的工程报告已明确排除，若后续混用仍会产生重复计数。最后，诊断置信度是规则系统输出，尚未通过独立校准集验证。

### 8.3 局限

本原型不包含 LLM、学习参数或在线策略优化，因此不能回答模型能力、提示设计或跨模型迁移问题。它也没有覆盖多智能体协作、长时程依赖、部分可观测状态、真实网络波动、支付副作用或人工审批流程。当前实验任务数量较小，seed 主要用于可复现而非独立同分布抽样；explicit-patch oracle / patch-availability-conditional reference 只覆盖带显式补丁的故障形式，且尚未完成独立置信度校准和成本统计；统计脚本已提供描述性 Wilson 区间与置信度分桶。恢复策略中的 F1 补丁是任务特定规则，不应外推为通用航班推荐算法。

## 9. 结论

本文实现并记录了 RACER 的 deterministic local flight prototype：公共轨迹驱动诊断，风险感知策略在低置信度下 abstain，候选补丁在隔离 clean session 中进行前缀—补丁—后缀反事实重放，并由任务约束和副作用检查验证。冻结主结果口径为 **15 tasks、45 baseline rows、recovery 3/12=25.00%、harmful repair=0**；其中 recovery 基线在 12 条原始失败中恢复 3 条，raw 不修复，而当前 explicit-patch oracle / patch-availability-conditional reference 接口只覆盖具备可用真值补丁的故障形式，冻结报告中未产生恢复成功。这些结果只说明固定规则和固定故障矩阵下的原型行为，不能解释为 LLM benchmark、oracle 理论上限、显著性结论或跨环境性能。

后续工作应在扩大任务、增加自然故障和完善 evaluator-only 真值清单中的 explicit-patch 规范的同时，基于现有 15 tasks、45 baseline rows 的逐基线结果继续补充可核验的 step/latency/repair-cost 汇总，并对已生成的描述性统计开展消融；Gemma 的三 seed clean admission 只验证本地 actor 的基础协议和成功后停止安全性，尚未验证 fault recovery，仍需受控 fault pilot；Gemma 已通过一次 force_error_confirm fault activation admission pilot：单任务、单 seed，recovery 在 clean counterfactual 中恢复成功且无 side effect；该结果仅证明当前故障链路可运行，不构成模型性能 benchmark。Qwen、云 provider 与 `$\tau$-bench` live 仍须满足各自准入条件后才可报告模型或 benchmark 指标。

## 10. 复现说明

在项目根目录执行：

```bash
cd /Users/infoflow/WorkBuddy/2026-08-31-17-40-04
python scripts/local_experiment.py --write-spec experiments/local-flight-matrix.json
```

使用 Docker Compose 构建并启动服务：

```bash
docker compose --profile analysis build
docker compose --profile analysis up -d task-env diagnoser recovery-policy counterfactual
```

将批量规范传给 `agent-runner`：

```bash
docker compose --profile analysis run --rm \
  -v "$PWD/experiments/local-flight-matrix.json:/tmp/local-flight-matrix.json:ro" \
  -e BATCH_SPEC=/tmp/local-flight-matrix.json agent-runner
```

完成运行后，轨迹写入同一 Compose project 的 named volumes（公共轨迹与 evaluator-only oracle manifest 分开保存）。随后启动分析 profile：

```bash
docker compose --profile analysis run --rm evaluator
```

也可使用本地汇总脚本读取结果目录：

```bash
python scripts/local_experiment.py \
  --summarize trajectories reports/local-flight-summary.json
```

当前代码还提供标准库测试套件；本稿更新时执行 `python3 -B -m unittest discover -s tests -p 'test_*.py'`，结果为 90 项测试通过。复现时应保留 `run_id`、seed、fault matrix、代码版本和报告生成时间，并单独保存公共轨迹与 evaluator-only oracle manifest；禁止将 `fault_truth` 写入智能体可见轨迹或通过公共 HTTP `/evaluate` 查询。

### 10.1 冻结主表的推荐流程

当前主表使用 `reports/local-flight-results.json`，其报告元数据为 15 个唯一任务、45 条基线记录、5 种故障和 3 个基线。为防止后续 smoke 或历史文件混入，应在空的结果目录中仅运行冻结矩阵，随后以 run manifest 对照 `task_id`、seed 和 baseline 集合，确认恰有 15 个唯一任务单元及其三类基线，再生成新报告。不要将历史 `local-flight-evaluator.json` 或 `docker-evaluator.json` 的行级输出直接拼接到主表；这两份文件在本文中仅作为工程调试历史。报告中应注明该次运行的 Compose 镜像版本、矩阵文件哈希、运行时间与输出目录。

## 11. 参考文献与核验说明

以下参考文献条目仅采用工作区书目核验文件中已确认的正式标题、venue、版本和出版信息；除书目定位所需信息外，不引入这些工作的 benchmark 数字或实验结论。

1. Zhu, Kunlun, et al. *Where LLM Agents Fail and How They can Learn From Failures*. arXiv preprint arXiv:2509.25370, 2025（AgentDebug；截至核验时未核到正式会议/期刊 venue）。
2. Zhang, Shaokun, et al. *Which Agent Causes Task Failures and When? On Automated Failure Attribution of LLM Multi-Agent Systems*. In *Proceedings of the 42nd International Conference on Machine Learning*, PMLR 267:76583–76599, 2025（Who&When）。
3. Ma, Xuyan, et al. *Demystifying the Lifecycle of Failures in Platform-Orchestrated Agentic Workflows*. arXiv preprint arXiv:2509.23735, 2025（AgentFail，当前 v2；v1 标题为 *Diagnosing Failure Root Causes in Platform-Orchestrated Agentic Systems: Dataset, Taxonomy, and Benchmark*）。
4. Zhang, Guibin, et al. *AgenTracer: Who Is Inducing Failure in the LLM Agentic Systems?* In *International Conference on Learning Representations* (ICLR 2026), 2026（AgenTracer；arXiv 预印本 arXiv:2509.03312，2025）。
5. Bonagiri, Akash, et al. *CausalFlow: Causal Attribution and Counterfactual Repair for LLM Agent Failures*. arXiv preprint arXiv:2605.25338, 2026（截至核验时未核到正式会议/期刊 venue）。
6. Yao, Shunyu, et al. *$\tau$-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains*. In *The Thirteenth International Conference on Learning Representations* (ICLR 2025), 2025（预印本 arXiv:2406.12045，2024）。
7. Debenedetti, Edoardo, et al. *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents*. In *Advances in Neural Information Processing Systems 37* (NeurIPS 2024), Datasets and Benchmarks Track, pp. 82895–82920, 2024。

正式投稿时应以 `reports/related-work-bibliography.md` 中的完整作者、链接和 BibTeX 为准；其中 AgentFail 的 v1/v2 标题、AgenTracer 与 `$\tau$-bench` 的预印本年份和正式 venue 年份均应按上述版本区分。
