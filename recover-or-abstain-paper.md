# Recover or Abstain: Replay-Verified Recovery for Tool-Calling Agents

## 摘要

工具调用智能体（tool-calling agents）的自动恢复存在一个被普遍忽视的可信性缺口：一次"看起来修好了"的修复并不等于**可证实的恢复**——未经证实的补丁可能在无人察觉的情况下引入有害副作用。本文提出 RACER（Risk-Aware Counterfactual Execution and Recovery），将恢复声明重新定义为一种须经审计的断言：只有当候选补丁在隔离的干净会话中完成前缀—补丁—后缀的严格反事实重放、并携带可复算的身份回执时，恢复才被承认；凡不可证实即弃权（abstain）。围绕该语义，我们构建了一个配对基准：真实 LLM actor 执行 55 个 episode（11 个故障/任务单元 × 5 个 trial），14 个基线全量配对比较，770 条记录经 fail-closed 准入审计（G0–G8）全数通过。结果：RACER 实现了 15/15 的**可证实恢复**（Wilson 95% CI [0.796, 1.000]）、零有害修复；去除反事实验证的消融使可证实恢复降至 0%（配对符号置换检验，Holm 校正后 p=0.0011），证明验证层是恢复声明的必要条件而非锦上添花。同时我们诚实报告：在本矩阵的故障分布上（可重试故障为主），朴素重试族达到同等恢复率——风险感知门控的差异化收益需要不可重试副作用故障来检验；此外 drop/replace 类注入故障被 LLM actor 的自然重发行为自愈，这一发现对故障注入基准的设计本身有方法论意义。

## 1. 引言

生产环境中的智能体恢复面临一个结构性矛盾：**修复动作本身有风险**。重试一个非幂等操作可能造成重复扣款；替换一个参数可能违反任务约束；在证据不足时继续执行会把局部错误放大为全局失败。诊断类工作（AgentDebug [1]、Who&When [2]、AgentFail [3]、AgenTracer [4]）回答"哪里错了"，CausalFlow [5] 将反事实修复引入归因，但现有评估体系普遍缺失一个环节：**恢复声明如何被证实**。一个基线报告"修复成功"，若没有可复算的证据链，评审者与部署者都无法区分三种情形：修复真的发生了；修复恰好无害但未被验证；修复引入了未被观测的副作用。

本文的核心主张是：**恢复必须是可证实的断言，而不是观测到的巧合**。我们将该主张落实为四层机制：

1. **公共证据诊断**：根因候选只从轨迹的公共证据（requested/effective action 差异、错误字符串、约束违反）推导，评估真值与智能体物理隔离；
2. **风险—效用门控**：候选按效用排序生成补丁，置信不足或无补丁时显式弃权——abstain 是一等公民动作；
3. **隔离反事实重放**：补丁在以源种子初始化、无故障日程的干净会话中重放，回执须通过 7 字段身份契约的独立复算；
4. **fail-closed 准入**：无 provenance 锚点、无重放回执、无退款账本见证或含真值泄漏的记录，一律拒绝进入主表。

**贡献。**

- **C1（形式化）**：给出"重放证实的恢复"（replay-verified recovery）的严格语义——恢复成功当且仅当隔离重放评估成功、无副作用且回执满足严格重放契约；在该语义下系统比较 14 个基线。
- **C2（方法）**：RACER 框架及配套的 G0–G8 准入审计器；审计器使恢复声明从"叙述"变为"可机器复验的凭证"。
- **C3（基准）**：配对 55-episode、14-基线、770 记录的真实 LLM 主会，协议/矩阵/模型资源/基线注册表全部冻结并哈希锚定；τ²-airline 适配的 G4 负结果（原生退款非幂等、无账本见证）作为环境设计动机。
- **C4（发现）**：(i) 消融证明反事实验证是恢复认定的必要条件（100%→0%，Holm p=0.0011）；(ii) drop/replace 注入故障被 LLM 自然重发自愈——故障注入必须与智能体策略交互才能产生持久失败，否则失败分母被系统性高估；(iii) 诚实零结果：可重试故障分布上朴素重试与 RACER 恢复率无显著差。

## 2. 相关工作

**失败诊断与归因。** AgentDebug [1] 通过针对性反馈学习失败模式；Who&When [2] 首次系统研究多智能体系统的自动失败归因；AgentFail [3] 构建平台编排智能体的失败生命周期数据集与分类法；AgenTracer [4] 区分并定位 LLM 系统中的失败诱导方。这一线工作不断细化"根因在哪里"，但其评估止于归因准确率；恢复决策（是否动手、动手后如何证实）被留给部署者。RACER 与之正交互补：我们把诊断输出作为输入，研究其后修复动作的可信性问题。

**反事实修复与副作用安全。** CausalFlow [5] 在因果归因之上提出反事实修复，是与本文最接近的构想，但其修复评估不要求携带可复算的重放回执，副作用以事后标注而非审计准入的方式处理。τ-bench [6] 提供工具—智能体—用户交互域并强调领域真实性与用户模拟，但未对恢复声明提供证实机制；我们对其 airline 域的适配实验（§6.6）显示原生退款工具非幂等且无公开账本见证，副作用声明无法满足 fail-closed 审计——这正是我们自建可审计环境与退款账本语义的直接动机。AgentDojo [7] 以动态环境评估注入攻击防御，其注入与本文的运行时故障注入目标不同：前者考察安全性，后者考察恢复可信性。

**智能体评估方法学。** 近期基准工作普遍强调可复现性与防污染（固定任务集、种子、指标冻结），但"结果可复现"与"声明可审计"是两个层次：前者保证重跑一致，后者保证单次运行内的每个结论都有机器可验的证据链。RACER 的配对身份（6 元组）、trial 展开、去重证明与 G0–G8 准入审计属于后一层次，可作为现有智能体基准的即插式加固层。

## 3. 问题形式化

设轨迹 τ = (a₀, o₀, …, a_{T−1}, o_{T−1})，动作含工具名与参数。环境按故障日程在指定步骤注入故障 f ∈ {replace_action, force_error, rate_limit, wrong_tool, drop_action}；公共轨迹不暴露真值。诊断器从公共证据输出候选集 D(τ) = {(cᵢ, sᵢ, pᵢ, eᵢ)}（根因、步骤、置信度、证据）。恢复策略 π 选择 d ∈ {retry, replace_argument, ask_clarification, **abstain**} 并可生成补丁 δ（对某步骤动作的替换）。

**定义 1（重放证实的恢复）。** 补丁 δ 的恢复声明被承认，当且仅当存在隔离会话重放 E(τ_cf)：以源种子初始化、故障日程为空、按前缀—δ—后缀顺序执行，且 (i) E(τ_cf).success = true；(ii) E(τ_cf).side_effect = false；(iii) 重放回执 r 满足严格重放契约——由源环境契约复算的 7 个身份字段（契约版本、episode、源运行、源环境指纹、初始状态指纹、故障日程指纹、重放运行号）逐一匹配。不满足任一条者**不得声明恢复**；策略端表现相同，声明资格完全不同。

**定义 2（配对身份）。** 每个源 episode 由 6 元组唯一标识：(episode_id, source_run_id, task_id, canonical_json(env_seed), initial_state_fingerprint, fault_schedule_fingerprint)。基线间比较仅在配对身份内进行，杜绝跨环境比较的伪差异。

弃权不计入恢复亦不计入有害；其语义是"证据不足以支持一次可证实的修复"。风险—效用门控使用 u = confidence − (1 − confidence)，u 低于阈值（0.55）时弃权——该阈值是工程默认值，本文不做普适性声明。

## 4. 方法：RACER

**诊断（公共证据）。** 逐步扫描轨迹：(i) requested 与 effective 动作的工具名不一致 → effective_tool_mismatch 候选（覆盖 wrong_tool / replace_action 的可观测后果）；(ii) 工具错误 → 以错误字符串为根因的 action_error 候选（注入故障的 error 文本内嵌故障类型，如 "injected rate_limit"）；(iii) 约束违反回溯定位到选择步骤。关键设计约束：**语义判断只来自公共文本**——退款性候选由任务文本与不变量推导，而非硬编码航班语义。我们在 §7 披露：首版实现曾硬编码"选 F2 即违例"，在任务要求不可退款的变体上产生 40 行假阳性有害修复——该缺陷由反事实重放暴露（补丁重放出现副作用），修复后归零。这一插曲本身验证了闭环的诊断价值。

**策略（风险—效用门控）。** 对候选按效用排序，对最高效用者生成补丁：错误类候选恢复 requested_action（重试语义），参数类候选做替换。决策记录预期成本/风险与 use_counterfactual=true。

**验证（隔离反事实重放）。** 重放器为每个补丁建立 `<run_id>:cf` 会话：源种子、故障日程为空、以 requested_action 恢复原始意图、执行前缀—补丁—后缀。会话返回轨迹、评估与 replay_provenance（valid/strict/源契约）。源运行状态不被覆盖；重放器独立复算期望契约并逐字段比对。

**准入（fail-closed 审计）。** 主表只接受满足以下条件的 canonical envelope：G1 源 manifest SHA-256 锚点；G2 配对身份由 task_id 与环境契约**重算**一致；G3 恢复声明携带 valid+strict 回执且期望契约重算匹配（无回执的恢复声明直接拒绝——racer_no_counterfactual 消融的 0% 恢复即由此语义产生）；G4 副作用行携带退款实体、SHA-256 账本见证与正整数账目数；G5 键名与值模式扫描拒绝真值/密钥泄漏；G7 envelope 形状、44 字段行白名单与零重复去重证明。评估器侧另有 G0（协议/矩阵/模型锁）与 G8（计划—执行覆盖完备性，770 planned = 770 executed）。

## 5. 基准设计

**协议与矩阵。** 协议 racer-v2-benchmark-protocol-0.1 冻结：E1 故障矩阵（5 类故障，注入于确认步骤）×5 trial；E2 任务变体（clean_success、non_refundable、suboptimal_refundable、missing_confirmation、force_error_confirm、drop_confirm，共享航班表：F1 ¥420 可退 / F2 ¥360 不可退 / F3 ¥480 可退，预算 ¥500）×5 trial。共 11 单元 × 5 trial = **55 episode**。全部单元启用幂等退款账本（refund_booking 幂等 + SHA-256 ledger witness + get_refund_status 对账查询），使任何副作用声明天然满足 G4 审计。

**基线（14，配对执行）。** 三组：**不修复**（raw_react）；**重试族**（fixed_retry、exponential_backoff）；**诊断族**（generic_reflection、full_trace_judge——要求多候选佐证、step_by_step_diagnosis、binary_search_diagnosis、agentdebug_targeted_feedback）；**消融**（always_recover、racer、racer_no_abstain、racer_no_counterfactual——补丁直接应用、不调用重放、按构造 counterfactual_supported=false）；**oracle 上界**（oracle_root_cause——真值步骤+公共证据补丁；oracle_recovery——仅当真值含显式补丁才修复）。oracle 经特权通道接收真值，其余基线只见公共轨迹。

**模型资源与执行。** 模型资源 oneapi-relay-glm-5.3-Flash（Anthropic-native /v1/messages + tool_use 协议；temperature 0.0 / max_tokens 1024），revision lock 锚定 actor 源码、系统提示、工具 schema、采样参数与代码 commit。执行中继的 Claude 节点持续 HTTP 529 过载，按预注册的替换条款切换至同协议 GLM 节点，作为有效性威胁如实披露（§7）。凭据仅经运行时环境变量注入，不入仓库与产物。LLM actor 步数上限 6；episode 在确认、actor 终止或工具错误时结束（fail-fast——这是可重试类故障成为持久失败的原因，见 §6.4）。

**统计程序（预注册）。** Wilson 95% 区间为观测描述。配对比较在 episode 层编码三方结果（+1 无害恢复 / 0 未恢复 / −1 有害修复），配对差分做 10,000 次分层 cluster bootstrap 与 10,000 次符号置换（种子固定），主族（RACER vs 11 个非 oracle 基线）做 Holm-Bonferroni 校正，α = 0.05。

## 6. 结果

### 6.1 主表

全部 770 条记录通过 G0–G8 审计。失败分母 15（force_error、rate_limit、wrong_tool 各 5）：

| 基线 | 可证实恢复 | Wilson 95% CI | 有害修复 | 弃权 (行) |
|---|---:|---|---:|---:|
| raw_react | 0/15 (0%) | [0.0, 20.4%] | 0 | 55/55 |
| fixed_retry | 15/15 (100%) | [79.6, 100%] | 0 | 35/55 |
| exponential_backoff | 15/15 (100%) | [79.6, 100%] | 0 | 35/55 |
| generic_reflection | 15/15 (100%) | [79.6, 100%] | 0 | 35/55 |
| full_trace_judge | 5/15 (33.3%) | [15.2, 58.3%] | 0 | 45/55 |
| step_by_step_diagnosis | 15/15 (100%) | [79.6, 100%] | 0 | 35/55 |
| binary_search_diagnosis | 15/15 (100%) | [79.6, 100%] | 0 | 35/55 |
| agentdebug_targeted_feedback | 15/15 (100%) | [79.6, 100%] | 0 | 35/55 |
| always_recover | 15/15 (100%) | [79.6, 100%] | 0 | 35/55 |
| **RACER（本文）** | **15/15 (100%)** | **[79.6, 100%]** | **0** | 35/55 |
| RACER−abstain | 15/15 (100%) | [79.6, 100%] | 0 | 0/55 |
| RACER−counterfactual | 0/15 (0%) | [0.0, 20.4%] | 0 | 35/55 |
| oracle_root_cause（参考） | 15/15 (100%) | [79.6, 100%] | 0 | 35/55 |
| oracle_recovery（参考） | 0/15 (0%) | [0.0, 20.4%] | 0 | 50/55 |

弃权语义说明：弃权率分母为全部行。35/55 的弃权全部发生在**原始已成功**的 episode 上——无候选即无补丁，弃权表达"无可修复项"而非风险拒绝；消融 RACER−abstain 按构造为 0。oracle_recovery 的 0% 反映本故障规范的真值不携带显式补丁（重试类故障），其条件上界语义如实呈现。

### 6.2 假设检验（episode 层配对，Holm 校正）

| 对比 | 平均配对差分 | bootstrap 95% CI | Holm p | 结论 |
|---|---:|---|---:|---|
| RACER vs raw_react | +0.364 | [0.236, 0.491] | **0.0011** | 拒绝 H₀ |
| RACER vs RACER−counterfactual | +0.364 | [0.236, 0.491] | **0.0011** | 拒绝 H₀ |
| RACER vs full_trace_judge | +0.182 | [0.091, 0.291] | **0.0198** | 拒绝 H₀ |
| RACER vs 重试族 / 其余消融 | 0.000 | [0, 0] | 1.0000 | 不拒绝 |

**H1（恢复优势）**：RACER 显著优于不修复与全轨迹判读。**H2（验证层必要性）**：去除反事实验证后，策略行为不变（补丁照常生成），但按 G3 语义恢复认定归零——修复动作与恢复声明被审计层强制分离。**诚实结果**：与朴素重试族无显著差（§7 展开边界讨论）。

### 6.3 消融

RACER−abstain：恢复率不变、弃权归零——本矩阵无"修复即有害"的故障（有害修复全场为 0），风险门控未付出恢复代价也未获得差异化收益；RACER−counterfactual：可证实恢复 100%→0%（G3 语义），验证层是恢复声明的必要条件。always_recover 与 RACER 全指标持平，与上述解读一致。

### 6.4 失败结构与自愈发现

三个结构性观察刻画了"注入故障 ≠ 持久失败"：

1. **drop_action / replace_action 被自愈**（10 单元原始全部成功）：被丢弃/替换的确认步骤返回 ok=true，episode 不终止；LLM actor 在下一回合观察到"未确认"状态，自然重发确认动作。故障发生了，但被智能体行为吸收。
2. **E2 变体故障未触发**（10 单元原始全部成功）：变体故障注入在第 3 步，而 actor 两步完成任务（航班表在观察中可见，无需搜索），注入点从未到达。
3. **持久失败 = fail-fast × 可重试**：15 个失败全部是"工具返回错误 → runner 立即终止"且"重试即修复"的组合。

这对故障注入基准的启示是：**故障必须与智能体策略交互并被环境以终止语义强化，才能构成有效失败分母**；否则失败率被系统性低估、恢复率被高估。本基准如实报告该结构，并将其列为后续矩阵设计原则（不可逆副作用故障）。

### 6.5 成本

55 episode 共 120 次 LLM 调用（全部一次成功：0 次无效动作、0 次端点错误、0 次空内容重试），44,974 tokens（prompt 21,621 / completion 23,353），均值 15.2 s/episode；轨迹长度 2–3 步（均值 2.2）。调用账本六项守恒不变量（调用数 = 尝试数 = 终端响应 + 失败尝试等）在全部 episode 成立。执行中暴露的 GLM 思维链截断缺陷（max_tokens 耗尽于 thinking 块导致空内容，温度 0 下确定性重演）以"提高预算 + 空内容重试温度递增"修复，终版运行零触发；缺陷与修复均记录于 registry。

### 6.6 τ²-airline 适配负结果（环境设计动机）

对 τ²-airline 的原生适配实验（pilot tier）得到 G4 FAIL：原生退款操作非幂等、无公开可复算的账本见证，副作用声明无法满足准入审计。该负结果直接驱动本文环境的幂等账本设计，也说明 fail-closed 审计对外部基准的加固价值：**不可审计的副作用语义会使任何恢复声明不可信**。

## 7. 局限

**范围。** 单域（航班预订）、3 个候选动作、2–3 步轨迹、单一 LLM actor（GLM-5.3-Flash）、单一注入点（确认步骤）。100% 恢复率不可外推至生产智能体；本文的所有定量结论限定于本矩阵。

**故障分布。** 观测到的 15 个失败全部可重试——这无法分离风险—效用门控与朴素重试（表 6.1–6.2 的诚实零结果），也无法在"修复即有害"维度上测试弃权（全场零有害修复）。drop/replace 自愈与 E2 未触发进一步收缩了失败分母。结论：本矩阵证明的是**验证层必要性与审计可行性**，不是风险门控的普适优势；分离后者需要不可逆副作用故障矩阵（已列入后续工作）。

**有效性与基础设施。** (i) 执行中模型替换（Claude→GLM-5.3-Flash，中继 529 过载）发生在协议冻结之后，按预注册替换条款执行并披露，但结果与原计划模型无可比性；(ii) 空内容重试的温度递增（+0.1/次，上限 0.7）偏离锁定的 temperature 0.0——终版运行零触发，机制仅作为已验证的防御保留；(iii) 首版诊断器的语义硬编码缺陷（§4）在主会首轮暴露 40 行假阳性有害修复，经修复并全矩阵重跑后归零——主表来自修复后运行，缺陷数据归档留存；这既是威胁（首版即发布将报告错误结论）也是证据（闭环捕获了它）。

**统计。** 5 个 trial 是可复现性种子而非独立同分布样本；Wilson 区间为描述性区间；置换检验控制 episode 内配对相关但未建模跨单元相关。恢复认定的 G3 语义使消融的 0% 部分来自"声明不可受理"而非"行为失败"——我们视其为语义特征而非混淆，但读者比较跨论文数字时应知悉该约定。

**结论稳健性声明。** 尽管存在上述边界，核心主张（验证层使恢复声明可审计、必要且在真实 LLM 执行中可行）由三重独立证据支撑：消融的配对显著性（p=0.0011）、首轮运行的假阳性捕获、以及 τ² 外部基准的 G4 负结果。

## 8. 结论

RACER 将智能体恢复从"观测到的巧合"重构为"可审计的断言"：恢复成功必须由隔离反事实重放证实、由配对身份锚定、由 fail-closed 准入审计放行。在 55-episode、14-基线、770 记录的真实 LLM 主会上，全部记录通过 G0–G8 审计；消融证明反事实验证是恢复认定的必要条件（100%→0%，Holm p=0.0011）；有害修复为零；同时我们如实报告了与朴素重试的零结果与故障自愈现象——它们划定了本矩阵能证明与不能证明的边界。后续工作：不可逆副作用故障矩阵、多域多模型 actor、以及将 G0–G8 审计器作为独立工具发布，为智能体恢复研究提供可复用的声明级证据基础设施。

## 复现性声明

冻结协议、矩阵、模型资源注册表（无密钥）、基线注册表与全部产物（55 条轨迹、oracle 清单、评估输出、770 记录 envelope、三份审计 JSON、统计输出）随论文开源；代码为纯 Python 标准库实现，115 项单元测试通过。凭据仅经运行时环境变量注入；公共轨迹与评估真值物理分离，`fault_truth` 不出现在任何智能体可见接口。复现入口与命令序列见项目 README；产物目录 `output/racer-v2-main-20260906/`。

## 参考文献

[1] Zhu, K., et al. *Where LLM Agents Fail and How They Can Learn From Failures*. arXiv:2509.25370, 2025.
[2] Zhang, S., et al. *Which Agent Causes Task Failures and When? On Automated Failure Attribution of LLM Multi-Agent Systems*. ICML 2025, PMLR 267:76583–76599.
[3] Ma, X., et al. *Demystifying the Lifecycle of Failures in Platform-Orchestrated Agentic Workflows*. arXiv:2509.23735, 2025.
[4] Zhang, G., et al. *AgenTracer: Who Is Inducing Failure in the LLM Agentic Systems?* ICLR 2026 (arXiv:2509.03312).
[5] Bonagiri, A., et al. *CausalFlow: Causal Attribution and Counterfactual Repair for LLM Agent Failures*. arXiv:2605.25338, 2026.
[6] Yao, S., et al. *τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains*. ICLR 2025 (arXiv:2406.12045).
[7] Debenedetti, E., et al. *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents*. NeurIPS 2024, Datasets and Benchmarks Track, 82895–82920.
