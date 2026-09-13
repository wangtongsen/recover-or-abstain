# Recover or Abstain: Replay-Verified Recovery for Tool-Calling Agents

## 摘要

工具调用智能体（tool-calling agents）的自动恢复存在一个被普遍忽视的可信性缺口：一次"看起来修好了"的修复并不等于**可证实的恢复**——未经证实的补丁可能在无人察觉的情况下引入有害副作用。本文提出 RACER（Risk-Aware Counterfactual Execution and Recovery），将恢复声明重新定义为一种须经审计的断言：只有当候选补丁在隔离的干净会话中完成前缀—补丁—后缀的严格反事实重放、并携带可复算的身份回执时，恢复才被承认；当重放预测修复将引入不可逆副作用时，策略改判弃权（replay veto）——补丁不提交。围绕该语义，我们构建了覆盖三类故障场景的配对基准：真实 LLM actor 在三个语义域（航班/酒店/商店）上执行 800 个 episode，14 个基线全量配对比较，双模型（GLM-5.3-Flash 主分析 + DeepSeek-V4-Flash 复现分析）共 11,200 条记录经 fail-closed 准入审计（记录级 G1–G7 门 + 评估器级 G0/G8 协议/矩阵/模型锁与计划—执行覆盖门）全数通过、零排除。在 7 个独立预注册的不可逆副作用场景（E3 轨道，含 omission（最优项缺失）、价格边界腐蚀、库存伪造、陈旧报价四类误导证据模式 × force_error/rate_limit/wrong_tool 三类触发故障）上：朴素重试族（8 基线联合）提交有害修复 GLM 510/560、DeepSeek 466/560，无验证消融（RACER−counterfactual）有害 GLM 70/70、DeepSeek 64/70，而 RACER 的重放否决将其全部转化为无害弃权（两模型 racer 有害均为 0/140）；伤害率差异（H-E3a）与 veto 准确率（H-E3b）在两模型上均经 Holm 校正后显著（$p = 1\times10^{-4}$ 量级），且 7/7 场景方向一致触发预注册的跨模型合并分析。主表三域上 RACER 恢复率 100%/100%/75–78%（shop 域的 in_stock 硬门槛暴露域语义差异，跨模型复现）。危害标签由独立于重放的 oracle 真值复算（1,960 行 E3 零翻转、veto 准确率 GLM 70/70 / DeepSeek 64/70）。同时我们如实报告：与保留验证层的消融（RACER−abstain）无显著结果差；drop/replace 类注入故障被 LLM actor 的自然重发行为自愈；DeepSeek 的多步行为使部分故障 cell 未达失败分母（12/14 场景-模型组合满足预注册分离门控，模型级偏差逐项披露）——这些发现对故障注入基准的设计本身有方法论意义。

## 1. 引言

生产环境中的智能体恢复面临一个结构性矛盾：**修复动作本身有风险**。重试一个非幂等操作可能造成重复扣款；替换一个参数可能违反任务约束；在证据不足时继续执行会把局部错误放大为全局失败。诊断类工作（AgentDebug [1]、Who&When [2]、AgentFail [3]、AgenTracer [4]）回答"哪里错了"，CausalFlow [5] 将反事实修复引入归因，但现有评估体系普遍缺失一个环节：**恢复声明如何被证实**。一个基线报告"修复成功"，若没有可复算的证据链，评审者与部署者都无法区分三种情形：修复真的发生了；修复恰好无害但未被验证；修复引入了未被观测的副作用。

本文的核心主张是：**恢复必须是可证实的断言，而不是观测到的巧合**。我们将该主张落实为四层机制：

1. **公共证据诊断**：根因候选只从轨迹的公共证据（requested/effective action 差异、错误字符串、约束违反）推导，评估真值与智能体物理隔离；
2. **风险—效用门控**：候选按效用排序生成补丁，置信不足或无补丁时显式弃权——abstain 是一等公民动作；
3. **隔离反事实重放**：补丁在以源种子初始化、无故障日程的干净会话中重放，回执须通过 7 字段身份契约的独立复算；重放预测到副作用或失败时**否决提交**（replay veto）；
4. **fail-closed 准入**：无 provenance 锚点、无重放回执、无退款账本见证或含真值泄漏的记录，一律拒绝进入主表。

**贡献。**

- **C1（形式化）**：给出"重放证实的恢复"（replay-verified recovery）的严格语义——恢复成功当且仅当隔离重放评估成功、无副作用且回执满足严格重放契约；并给出**重放否决**的决策语义（预测有害则改判弃权、不提交）。在该语义下系统比较 14 个基线。
- **C2（方法）**：RACER 框架及配套的 fail-closed 准入审计器族（记录级 G1–G5/G7、评估器级 G0/G8）；审计器使恢复声明从"叙述"变为"可机器复验的凭证"。
- **C3（基准）**：两条预注册轨道的配对基准——E1/E2 可重试故障轨道（3 域 × 11 cells × 10 seeds）与 E3 不可逆副作用轨道（7 独立场景 × 3 域 × 10 seeds，协议 v0.5 预注册：omission/价格边界腐蚀/库存伪造/陈旧报价四类误导证据模式 × force_error/rate_limit/wrong_tool 三类触发故障，使"修复=提交次优不可逆决策"）；14 基线、双模型、11,200 记录，协议/矩阵/模型资源/基线注册表全部冻结并哈希锚定；τ²-airline 适配的 G4 负结果（原生退款非幂等、无账本见证）作为环境设计动机。
- **C4（发现）**：(i) 2×2 消融（门控 × 验证）证明重放验证是防止有害提交的行为学必要组件：无验证的任何策略在 E3 两模型上大量提交有害修复（含 oracle 根因修复——正确诊断 ≠ 安全修复），带验证的策略全部无害弃权；危害标签经独立于重放的 oracle 真值复算零翻转（1,960 行 E3），否决触发准确率 GLM 70/70 / DeepSeek 64/70；(ii) H-E3a/H-E3b 在两模型上均 Holm 显著（$p = 1\times10^{-4}$ 量级）且 7/7 场景方向一致——预注册的跨模型合并分析被触发；(iii) 三域主表暴露 shop 域 in_stock 硬门槛下的恢复率差异（75–78% vs 100%），框架行为跨域一致、差异来自环境可达性；(iv) drop/replace 注入故障被 LLM 自然重发自愈——故障注入必须与智能体策略交互才能产生持久失败；(v) 零结果：与保留验证的 RACER−abstain 无显著结果差——风险门控的弃权不改变结果编码，价值体现在声明纪律而非结果增益。

## 2. 相关工作

**失败诊断与归因。** AgentDebug [1] 通过针对性反馈学习失败模式；Who&When [2] 首次系统研究多智能体系统的自动失败归因；AgentFail [3] 构建平台编排智能体的失败生命周期数据集与分类法；AgenTracer [4] 区分并定位 LLM 系统中的失败诱导方。这一线工作不断细化"根因在哪里"，但其评估止于归因准确率；恢复决策（是否动手、动手后如何证实）被留给部署者。RACER 与之正交互补：我们把诊断输出作为输入，研究其后修复动作的可信性问题。E3 轨道的一个补充发现是：即使拥有完美根因诊断（oracle_root_cause），修复动作仍可在不可逆故障上全部有害——诊断正确性与修复安全性是两个独立维度。

**反事实修复与副作用安全。** CausalFlow [5] 在因果归因之上提出反事实修复，是与本文最接近的构想，但其修复评估不要求携带可复算的重放回执，副作用以事后标注而非审计准入的方式处理，也不存在"预测有害则不提交"的否决语义。τ-bench [6] 提供工具—智能体—用户交互域并强调领域真实性与用户模拟，但未对恢复声明提供证实机制；我们对其 airline 域的适配实验（§6.7）显示原生退款工具非幂等且无公开账本见证，副作用声明无法满足 fail-closed 审计——这正是我们自建可审计环境与退款账本语义的直接动机。AgentDojo [7] 以动态环境评估注入攻击防御，其注入与本文的运行时故障注入目标不同：前者考察安全性，后者考察恢复可信性；E3 的 tamper_result 故障（污染工具响应载荷）在机制上与提示注入相邻，但作用于恢复评估而非攻击面。

**安全过滤器与弃权。** 否决在智能体恢复之外有近亲。安全屏蔽（safety shielding）以反应式系统包裹学习智能体、抑制违反规格的动作，这一思想源于安全强化学习 [8]；与 shield 一样，重放否决是**提交前**过滤器，其力量来自在动作生效前作出判断。选择性预测（reject option）形式化了"置信不足时拒答"的互补决策 [9]；此处弃权同样是第一等动作。区别在于证据标准：shield 执行**先验给定**的规格，而 RACER 的否决由**该补丁的复算反事实执行**证成，准入审计核验的是重放回执而非手写规格。

**智能体评估方法学。** 近期基准工作普遍强调可复现性与防污染（固定任务集、种子、指标冻结），但"结果可复现"与"声明可审计"是两个层次：前者保证重跑一致，后者保证单次运行内的每个结论都有机器可验的证据链。RACER 的配对身份（6 元组）、trial 展开、去重证明与 fail-closed 准入审计（G0–G5/G7/G8 门族）属于后一层次；协议 v0.2 的"预注册冻结 + 执行后对账附录 + 独立第二审计者复核"把预注册纪律引入智能体基准；该纪律在本项目内的实际效果（第二审计者确曾验出叙述夸大并修正）见 §7。

## 3. 问题形式化

设轨迹 τ = (a₀, o₀, …, a_{T−1}, o_{T−1})，动作含工具名与参数。环境按故障日程在指定步骤注入故障 f ∈ {replace_action, force_error, rate_limit, wrong_tool, drop_action, tamper_result}；公共轨迹不暴露真值。诊断器从公共证据输出候选集 D(τ) = {(cᵢ, sᵢ, pᵢ, eᵢ)}（根因、步骤、置信度、证据）。恢复策略 π 选择 d ∈ {retry, replace_argument, ask_clarification, **abstain**} 并可生成补丁 δ（对某步骤动作的替换）。

**定义 1（重放证实的恢复）。** 补丁 δ 的恢复声明被承认，当且仅当存在隔离会话重放 E(τ_cf)：以源种子初始化、故障日程为空、按前缀—δ—后缀顺序执行，且 (i) E(τ_cf).success = true；(ii) E(τ_cf).side_effect = false；(iii) 重放回执 r 满足严格重放契约——由源环境契约复算的 7 个身份字段（契约版本、episode、源运行、源环境指纹、初始状态指纹、故障日程指纹、重放运行号）逐一匹配。不满足任一条者**不得声明恢复**；策略端表现相同，声明资格完全不同。

**定义 2（重放否决）。** 若策略携带验证层（use_counterfactual=true 且非 skip_counterfactual），则补丁 δ 先经定义 1 的隔离重放评估；当 E(τ_cf).side_effect = true 或 E(τ_cf).success ≠ true 时，决策改判 abstain（reason 记 replay_veto_side_effect / replay_veto_not_success），δ **不提交**源环境。否决行记无害弃权：恢复 0、有害 0——"预测有害且未提交"。

**定义 3（配对身份）。** 每个源 episode 由 6 元组唯一标识：(episode_id, source_run_id, task_id, canonical_json(env_seed), initial_state_fingerprint, fault_schedule_fingerprint)。基线间比较仅在配对身份内进行，杜绝跨环境比较的伪差异。

**重放的确定性。** 重放会话不重新查询模型：前缀与后缀的每一步都重放已记录的 requested 动作，作用于以源种子初始化的干净环境（故障日程为空），候选补丁在故障步被替换。工具响应是环境状态的纯函数，因此对给定源 episode，$E(\tau_{\text{cf}})$ 是确定性的。验证层评估的是候选补丁的**后果**而非重新采样模型行为——这正是否决可归因于补丁而非采样噪声的原因。定义 2 中的 `use_counterfactual` 是启用验证的策略侧开关，不属于准入语义。

弃权不计入恢复亦不计入有害；其语义是"证据不足以支持一次可证实的修复"。风险—效用门控使用 u = confidence − (1 − confidence)，u 低于阈值（0.55）时弃权——该阈值是工程默认值，本文不做普适性声明。

## 4. 方法：RACER

**诊断（公共证据）。** 逐步扫描轨迹：(i) requested 与 effective 动作的工具名不一致 → effective_tool_mismatch 候选（覆盖 wrong_tool / replace_action 的可观测后果）；(ii) 工具错误 → 以错误字符串为根因的 action_error 候选（注入故障的 error 文本内嵌故障类型，如 "injected rate_limit"）；(iii) 约束违反回溯定位到选择步骤。关键设计约束：**语义判断只来自公共文本**——退款性候选由任务文本与不变量推导，而非硬编码航班语义。我们在 §7 披露：首版实现曾硬编码"选 F2 即违例"，在任务要求不可退款的变体上产生 40 行假阳性有害修复——该缺陷由反事实重放暴露（补丁重放出现副作用），修复后归零。这一插曲本身验证了闭环的诊断价值。

**策略（风险—效用门控）。** 对候选按效用排序，对最高效用者生成补丁：错误类候选恢复 requested_action（重试语义），参数类候选做替换。决策记录预期成本/风险与 use_counterfactual=true。

**验证（隔离反事实重放 + 否决）。** 重放器为每个补丁建立 `<run_id>:cf` 会话：源种子、故障日程为空、以 requested_action 恢复原始意图、执行前缀—补丁—后缀。会话返回轨迹、评估与 replay_provenance（valid/strict/源契约）。重放器独立复算期望契约并逐字段比对。按定义 2，重放预测到副作用或失败时决策改判弃权、补丁不提交。消融 RACER−counterfactual 跳过重放并将补丁**直接提交**源环境（direct application）——用于检验"无验证即提交"的真实行为后果。

全体基线都可以调用重放器：它是共享服务，是否重放是**待测策略的属性**而非 RACER 的特权。RACER−counterfactual 消融恰好占据互补格——它以同样的访问权构造同样的补丁，但直接提交——这正是 2×2 分解得以把差异归因于验证、而非归因于副作用 oracle 可得性的依据。

**准入（fail-closed 审计）。** 主表只接受满足以下条件的 canonical envelope：G1 源 manifest SHA-256 锚点；G2 配对身份由 task_id 与环境契约**重算**一致；G3 恢复声明携带 valid+strict 回执且期望契约重算匹配（无回执的恢复声明直接拒绝——racer_no_counterfactual 消融的 0% 恢复即由此语义产生）；G4（v0.3 三形）副作用行须满足其一：退款语义形（退款实体 + SHA-256 账本见证 + 正整数账目数）、重放证实形（counterfactual_supported ∧ replay_valid，须凭证链）、直接应用形（协议 v0.3 起：direct_applied=true 且携带环境签发的不可变 apply 回执——apply_witness = SHA-256(canonical JSON{sequence, tool, arguments, state_after_hash, success, side_effect, run_id})，行为结局位于哈希材料之内，伪造有害声明不可行；v0.2 的自陈布尔形态由此废止，旧 v0.2 E3 表在新审计器下按设计回归 NO-GO）；G5 键名与值模式扫描拒绝真值/密钥泄漏；G7 envelope 形状、字段行白名单与零重复去重证明。评估器侧另有 G0（协议/矩阵/模型锁）与 G8（计划—执行覆盖完备性，两条轨道分别 preflight：770=770 与 140=140）。这些门并非平铺清单，而是对具体威胁的映射：G5 防真值泄漏进智能体可见面；G1/G2 防身份替换与跨环境比较；G3 防不可复算的恢复声明；G4 防伪造或自陈的副作用声明；G6 防标签来源漂移（危害标签须源自 oracle 链而非重放输出）；G0/G8 防计划与执行间的协议、矩阵、模型漂移；G7 防信封畸形与重复行。

## 5. 基准设计

**协议版本与预注册纪律。** 协议 racer-v2-benchmark-protocol-0.1（2026-09-02 冻结）覆盖 E1/E2；v0.2（2026-09-07 冻结，早于 E3 首条轨迹 37 分钟）完成两件事：附录 A 将 v0.1 主会执行锚定为事后对账记录（如实披露冻结 planned manifest 与实际执行矩阵的差异及流程缺陷），正文预注册 E3 轨道——矩阵、重放否决/直接应用语义、G4 三形准入、统计计划与 GO/NO-GO 条款，运行后不可回改。v0.3（2026-09-07 冻结，早于回执版重跑首条轨迹）预注册直接应用的环境回执条款：任务环境维护 direct-apply 台账、evaluate() 终结回执、runner 嵌入决策、评估器传播四指标（direct_applied / apply_witness / receipt_valid / state_hash）、审计器 G4 升级并要求旧版本回归——v0.1 主表须继续 PASS、v0.2 E3 表须 NO-GO（无回执形态按设计拒收）——主表 E3 数据整体重跑为回执版。v0.4（2026-09-08 冻结，评估层修正案，不重执行）解耦危害标签与重放触发：标签由独立 oracle 从预注册真值清单（冻结 spec 的真实目录+预算+变体）与轨迹原始 state（哈希链验证）离线复算，不再读重放 evaluate 输出（v0.3 及之前标签与否决触发读同一 side_effect 布尔——同义反复弱点，外部复核与独立评估共同命中）；执行证据冻结为既有轨迹，行为字段零漂移、统计零漂移作为 GO 条件，详见 §6.2a。**v0.5（2026-09-09T04:20:01Z 冻结，早于任何 v0.5 执行轨迹）**预注册三域扩展（flight/hotel/shop 单引擎域分派）、E3 场景族扩容（7 独立场景）、双模型全矩阵（GLM 主分析 + DeepSeek 复现分析）、v0.5 审计门控（G6：domain/scenario_id 身份 + independent_oracle_v05 标签）与 GO/NO-GO 条款（R.2-1 至 R.2-6）。E3 产物进入主表前须通过独立第二审计者复核（与执行者隔离、重跑审计器、抽验轨迹、书面报告）；复核报告随论文开源。

**三域扩展（协议 v0.5 §K）。** 任务环境以单引擎域分派实现三个语义域：flight（search_flights/select_flight/confirm_booking）、hotel（search_rooms/select_room/confirm_reservation）、shop（search_products/select_product/place_order）。三域共享统一结构（目录、预算、软约束标志、账本语汇、回执机制），差异仅在工具命名与条目属性键——设计目标是使统一危害谓词（confirmed ∧ ¬optimal_selection，optimal = 真实目录中满足软约束的最便宜在库条目且 ≤ 预算；shop 域附加 in_stock 硬门槛）在域间同构，从而把跨域行为差异与域语义差异解耦。

**E3 场景族（协议 v0.5 §N，7 独立场景）。** 场景设计从 2 cell 扩展为 7 个独立场景（域 × 误导证据模式 × 触发故障的组合枚举，场景间独立性 ≥2 轴）：S1 flight/最优项从目录缺失（omission）+force_error@confirm；S2 flight/最优价被抬至预算边界（price corruption at boundary）+rate_limit@confirm；S3 hotel/omission+wrong_tool@confirm；S4 shop/最优项库存被伪报为无货（stock falsification）+force_error@place_order；S5 hotel/陈旧报价（stale quote，非最优项被显示为更便宜）+rate_limit@confirm；S6 shop/omission+rate_limit@place_order；S7 flight/stale quote+wrong_tool@confirm。**误导证据共四类**（omission 3 例、price-boundary corruption 1 例、stock falsification 1 例、stale quote 2 例；触发故障 force_error 2 / rate_limit 3 / wrong_tool 2；域分布 flight 3 / hotel 2 / shop 2）。陷阱合法性由引擎语义约束推导并预注册：伪造目录只能把 agent 引离真实最优、指向"可提交但次优"的条目（引向真实不合格条目会在 confirm 复检处失败、构不成危害提交）；drop_action 静默 no-op 无可见失败（全体弃权，无分离）、response_loss 使源终态对全体有害、真值 listing 规划错误使 RACER 正确恢复——三者均因无陷阱价值被排除在场景空间之外。E3 actor 为 3 步模式（search→select→confirm，混淆目录迫使搜索步）。

**E1/E2 轨道（可重试故障）。** E1 故障矩阵（5 类故障，注入于确认步骤）×5 trial；E2 任务变体（clean_success、non_refundable、suboptimal_refundable、missing_confirmation、force_error_confirm、drop_confirm，共享航班表：F1 ¥420 可退 / F2 ¥360 不可退 / F3 ¥480 可退，预算 ¥500）×5 trial。共 11 单元 × 5 trial = **55 episode**。全部单元启用幂等退款账本（refund_booking 幂等 + SHA-256 ledger witness + get_refund_status 对账查询），使任何副作用声明天然满足 G4 退款语义形。

**E3 轨道（不可逆副作用，预注册）。** 2 单元 × 5 trial = **10 episode**，每 episode 配同 14 基线，共 140 记录。故障组合：`tamper_result` 在搜索步污染响应载荷——航班表中被抹去真实最优的 F2（可退、¥360），actor 理性选择次优 F1（可退、¥420）；`force_error` / `rate_limit` 在确认步注入错误制造可见失败。公共观察对全体基线隐藏真实航班表（obfuscate_catalog），真实表仅驱动评估与反事实重放——诊断链路证据一致，补丁逻辑不感知 E3 特例。判定：修复后仍确认 F1 → side_effect=true（次优确认=不可逆损失，对照真实表）；修复后改选 F2 → 恢复。预注册预期：naive 重试族在确认失败处生成 retry-confirm 补丁 → 有害；RACER 重放否决 → 无害弃权。E3 使用自有航班表（F2 可退），与 v0.1 表的唯一差异即 F2 可退性——使"隐藏 F2 → 选 F1"构成次优。

**基线（14，配对执行）。** 三组：**不修复**（raw_react）；**重试族**（fixed_retry、exponential_backoff）；**诊断族**（generic_reflection、full_trace_judge——要求多候选佐证、step_by_step_diagnosis、binary_search_diagnosis、agentdebug_targeted_feedback）；**消融**（always_recover、racer、racer_no_abstain、racer_no_counterfactual——补丁直接应用、不调用重放、按构造 counterfactual_supported=false）；**oracle 上界**（oracle_root_cause——真值步骤+公共证据补丁；oracle_recovery——仅当真值含显式补丁才修复）。oracle 经特权通道接收真值，其余基线只见公共轨迹。

**模型资源与执行（v0.5 双模型）。** 主分析模型 oneapi-relay-glm-5.3-Flash（Anthropic-native /v1/messages + tool_use 协议；temperature 0.0），revision lock 锚定 actor 源码、系统提示、工具 schema、采样参数与代码 commit；复现分析模型 oneapi-relay-deepseek-v4-flash（同协议、同注册表纪律）。执行中继的 Claude 节点持续 HTTP 529 过载，按预注册的替换条款切换至同协议 GLM 节点，作为有效性威胁如实披露（§7）。凭据仅经运行时环境变量注入，不入仓库与产物。LLM actor 步数上限：主轨 6 步（2 步完成）、E3 8 步（3 步完成）；episode 在确认、actor 终止或工具错误时结束（fail-fast——这是可重试类故障成为持久失败的原因，见 §6.5）。**v0.5 执行矩阵**：主表 3 域 × 11 cells × 10 seeds = 330 episodes（4,620 记录/模型）；E3 7 场景 × 10 seeds = 70 episodes（980 记录/模型）；双模型合计 800 episodes、11,200 记录。v0.5 修正了 v0.1 的步位缺陷（confirm 位故障在 2-step actor 下从未激活——协议 K.4 预注册披露，v0.5 全部改挂 step 1），并以行为探针验证故障真实触发；v0.1 主轨数字按"故障未激活"标注保留于 §6.5。

**统计程序（预注册）。** Wilson 95% 区间为观测描述。配对比较在 episode 层编码三方结果（+1 无害恢复 / 0 未恢复 / −1 有害修复），配对差分做 10,000 次分层 cluster bootstrap 与 10,000 次符号置换（种子固定），主族（RACER vs 11 个非 oracle 基线）做 Holm-Bonferroni 校正，α = 0.05。v0.5 §Q 预注册扩展：E3 主假设族为双项 Holm——H-E3a（伤害率，episode-cluster bootstrap + permutation）与 H-E3b（veto 准确率，精确二项）；分层按（域 × 场景 × 模型）；Mantel-Haenszel 常见 OR 仅作描述性报告（零格 Haldane-Anscombe 修正、CI 失真披露）；双模型处置（Q.3）——GLM 主分析、DeepSeek 复现分析，跨模型合并分层 Holm 仅在两模型全部 7 场景方向一致时执行；跨域差异仅描述性（3 域不足以支持域间显著性主张，Q.4）；主显著性预警——E3 为机制性验证轨道，主显著性主张建立在分层检验上。

## 6. 结果

**v0.5 双矩阵双模型总览。** v0.5 在冻结协议（2026-09-09T04:20:01Z）下执行了双模型全矩阵：GLM-5.3-Flash（主分析）与 DeepSeek-V4-Flash（复现分析），E3 轨道 7 场景 × 10 种子 × 14 基线 × 2 模型 = 1,960 记录，主表 3 域 × 11 cells × 10 种子 × 14 基线 × 2 模型 = 9,240 记录，全部通过 v0.5 审计器（G1–G7，含 G6 域/场景身份与 independent_oracle_v05 标签门控），排除率 0%。R.2 GO 条件 6/6 达成（E3 1960/1960、主表 9240/9240、planned=executed ×4、版本回归零漂移、分离方向 12/14 ≥ 11/14、排除率 0%）。以下 §6.1–§6.2 报告 v0.5 主结果，§6.2b 报告跨模型复现；v0.1–v0.4 历史轨道的合并主表保留于 §6.1a 作为对照。

### 6.1 主表（v0.5：3 域 × 双模型，9,240 记录全过准入审计）

> **命名约定。** 正文中的消融名 RACER−abstain / RACER−counterfactual 与产物及统计输出中的标识符 `racer_no_abstain` / `racer_no_counterfactual` 为同一基线（`−` 表去掉该组件）；表内其余基线名与产物键名逐字一致。

v0.5 主表按（域 × 模型）分层报告 RACER 恢复率与全基线 harm（主轨无不可逆陷阱——harm 分离的证明力在 E3；主表测恢复率与域扩展）。配对单位为 episode；域内配对检验为 racer vs 11 非 oracle 基线的 Holm 族（Q.4：域间差异仅描述性）：

| 域 | 模型 | racer 恢复率 | 域内 racer vs no_cf / raw / judge 配对 p（原始） | 全基线 harm |
|---|---|---:|---|---:|
| flight | GLM | 110/110 = 100% | 0.0001 / 0.0001 / 0.0001 | 0/1540 |
| hotel | GLM | 110/110 = 100% | 0.0001 / 0.0001 / 0.0001 | 0/1540 |
| shop | GLM | 86/110 = 78.3% | 0.0001 / 0.0001 / 0.0008 | 0/1540 |
| flight | DeepSeek | 110/110 = 100% | 0.0039 / 0.0044 / 0.0342 | 0/1540 |
| hotel | DeepSeek | 110/110 = 100% | 0.0001 / 0.0001 / 0.0012 | 0/1540 |
| shop | DeepSeek | 82/110 = 75.0% | 0.0001 / 0.0001 / 0.0001 | 0/1540 |

逐域 Holm 族（racer vs 11 个非 oracle 基线，每域 11 组，预注册口径）：GLM 三域的 no_cf/raw_react/full_trace_judge 对比全部 Holm 拒绝（holm_p ≤ 0.008）；DeepSeek hotel/shop 全拒绝、flight 的 no_cf/raw_react 拒绝（holm_p 0.043/0.044）而 full_trace_judge 不拒绝（holm_p 0.308——原始 p 0.034 在 11 组族内校正后失守）；racer vs fixed_retry 等重试族基线在两模型三域均为零差（p=1.0，零结果——主轨无陷阱设计下重试即正确修复，与 v0.1 轨道互补性结论一致）。

三个结构性发现：

1. **域间恢复率差异（shop 域 75–78%）**：shop 的 in_stock 硬门槛使部分故障 cell 的最优条目在恢复时已不可达（库存被先行动作消耗），重放如实预测"补丁可达的条目非最优"→ 否决弃权而非提交次优。这是**域语义的如实反映**——RACER 在三个域上的行为完全一致，差异来自环境可达性而非框架失效；跨模型复现（GLM 78.3% / DeepSeek 75.0%）。
2. **racer vs fixed_retry / racer−abstain 在主轨零差**：主轨无陷阱设计下重试即正确修复，与 v0.1 发现一致——差异化收益存在于有害维度（E3），不存在于可重试维度。
3. **G3 fail-closed 语义的规模化验证**：GLM 主表 106 行 no_cf 直接应用恢复（环境回执有效、行为成功）因无重放回执被归一化为不可证实恢复；DeepSeek 主表 60 行（106 vs 60 的差异反映两模型诊断输出产生可应用补丁的频率不同，见 §6.2b 披露）。两模型的主表对齐后 racer_no_counterfactual 恢复率均为 0%——与 v0.1/v0.3 消融编码逐字一致。

### 6.1a 历史对照（v0.1–v0.4 合并 25 失败 episode，910 记录）

失败分母 25：E1/E2 贡献 15（force_error、rate_limit、wrong_tool 各 5，均可在干净重放中经重试恢复），E3 贡献 10（重试可"成功"但提交次优不可逆决策）。v0.5 步位缺陷修正（K.4）后，v0.1 轨道的 confirm 位故障 cell（force_error_confirm、drop_confirm）按"故障未激活"重新标注——该轨道的数字保留为历史对照，v0.5 主表为当前主张的数字基座：

| 基线 | 可证实恢复 | Wilson 95% CI | 有害修复 | Wilson 95% CI | 弃权 (行) |
|---|---:|---|---:|---|---:|
| raw_react | 0/25 (0%) | [0, 13%] | 0/25 (0%) | [0, 13%] | 65/65 |
| fixed_retry | 15/25 (60%) | [41, 77%] | 10/25 (40%) | [23, 59%] | 35/65 |
| exponential_backoff | 15/25 (60%) | [41, 77%] | 10/25 (40%) | [23, 59%] | 35/65 |
| generic_reflection | 15/25 (60%) | [41, 77%] | 10/25 (40%) | [23, 59%] | 35/65 |
| full_trace_judge | 5/25 (20%) | [9, 39%] | 0/25 (0%) | [0, 13%] | 55/65 |
| step_by_step_diagnosis | 15/25 (60%) | [41, 77%] | 10/25 (40%) | [23, 59%] | 35/65 |
| binary_search_diagnosis | 15/25 (60%) | [41, 77%] | 10/25 (40%) | [23, 59%] | 35/65 |
| agentdebug_targeted_feedback | 15/25 (60%) | [41, 77%] | 10/25 (40%) | [23, 59%] | 35/65 |
| always_recover | 15/25 (60%) | [41, 77%] | 10/25 (40%) | [23, 59%] | 35/65 |
| **RACER（本文）** | **15/25 (60%)** | **[41, 77%]** | **0/25 (0%)** | **[0, 13%]** | 45/65 |
| RACER−abstain | 15/25 (60%) | [41, 77%] | 0/25 (0%) | [0, 13%] | 10/65 |
| RACER−counterfactual | 0/25 (0%) | [0, 13%] | 10/25 (40%) | [23, 59%] | 35/65 |
| oracle_root_cause（参考） | 15/25 (60%) | [41, 77%] | 10/25 (40%) | [23, 59%] | 35/65 |
| oracle_recovery（参考） | 0/25 (0%) | [0, 13%] | 0/25 (0%) | [0, 13%] | 60/65 |

可证实恢复 15/25 的构成：v0.1 可重试故障上 15/15（重放验证通过）；E3 上 0/10（重放预测次优确认，全部否决弃权——见 §6.2）。弃权分母为全部行（65）；E3 的 10 个弃权来自重放否决，v0.1 的弃权发生在原始已成功的 episode 上（无候选即无补丁）。oracle_recovery 的 0% 反映真值不含显式补丁（重试类故障）与 E3 真值无"换 F2"补丁，其条件上界语义如实呈现。

### 6.2 E3 轨道（v0.5：7 独立场景 × 3 域 × 2 模型）：不可逆副作用上的行为学分离

v0.5 将 E3 从 2 cell 单域 10 episode 扩展为 7 独立场景 × 3 域 × 10 种子 × 14 基线 × 2 模型 = 1,960 记录。每场景的陷阱机制与触发故障见 §5（E3 场景族）。全模型分离表（重试族 = 8 基线联合有害率，重试族满分 80 = 8 基线 × 10 种子）：

| 场景 | 域 / 误导证据 / 触发 | GLM 重试族有害 | GLM racer veto 弃权 | DS 重试族有害 | DS racer veto 弃权 |
|---|---|---:|---:|---:|---:|
| S1 | flight / omission / force_error | 70/80 | 20/20 | 70/80 | 20/20 |
| S2 | flight / price@boundary / rate_limit | 70/80 | 20/20 | 70/80 | 20/20 |
| S3 | hotel / omission / wrong_tool | 80/80 | 20/20 | 80/80 | 20/20 |
| S4 | shop / stock falsification / force_error | 70/80 | 20/20 | 70/80 | 20/20 |
| S5 | hotel / stale quote / rate_limit | 70/80 | 20/20 | 42/80 | 16/20 |
| S6 | shop / omission / rate_limit | 70/80 | 20/20 | 70/80 | 20/20 |
| S7 | flight / stale quote / wrong_tool | 80/80 | 20/20 | 64/80 | 18/20 |

读法：非满分的重试族行全部来自 full_trace_judge 的弃权（judge 要求多候选佐证，force_error/rate_limit 族的注入错误在 trace 中无旁证 → 确定性弃权——**基线设计属性而非模型噪声**，v0.4 同模式 0/10 先于 v0.5 存在、smoke 预检已知、DeepSeek 跨模型复现，R.2-5 已裁决带披露 GO）；S3/S7（wrong_tool 族）judge 重试并落入有害。DeepSeek S5/S7 的缩减（42/80、64/80）另有模型级成因（部分 trial 的源 episode 未达失败分母——actor 停滞于步数耗尽而非工具错误），属 R.2-5 配额内（12/14 ≥ 11/14）场景-模型组合偏离，逐基线明细见产物分离表。

**主检验（Q.1 双项 Holm 族）**：

- **H-E3a（伤害率）**：GLM family−racer 差 = 0.911，CI [0.898, 0.923]，$p = 1\times10^{-4}$；DeepSeek 差 = 0.832，CI [0.766, 0.888]，$p = 1\times10^{-4}$——两模型均 Holm 拒绝 H₀。
- **H-E3b（veto 准确率）**：GLM 70/70（p = 2⁻⁷⁰）；DeepSeek 64/70（91.4%，$p = 1.2\times10^{-13}$）——两模型均 Holm 拒绝 H₀。DeepSeek 的 6 个不正确否决集中在 S5（4）与 S7（2），对应"源 episode 未失败"的配对错位（对未失败 episode 的弃权不计为正确否决），非误放有害补丁——有害维度零漏放（两模型 racer harm 均 0/140）。
- **检验的分辨率**：两个置换 p 值均落在 $1\times10^{-4}$，即 10,000 次置换检验的下限，应读作"至少这么小"而非精确值；不依赖置换分辨率的 bootstrap 置信区间承担效应量信息。
- **方向一致性**：两模型各 7/7 场景重试族 harm 率 > racer harm 率。
- **no_counterfactual 消融**：GLM 有害 70/70（全场景 10/10）；DeepSeek 64/70（S5 6/10、S7 8/10，同源 episode 分母差异）——去除验证层的补丁在两模型上都大量提交有害修复。

**Q.3 双模型裁决**：两模型 7/7 场景同方向 → 跨模型合并分层 Holm 执行（预注册条件满足）。

#### 6.2a 危害标签的独立 oracle 解耦（协议 v0.4，评估层修正案）

v0.3 及之前存在一个同义反复弱点：harm 标签（evaluator 的 harmful_repair 读取重放会话的 evaluate().side_effect）与重放否决触发（runner 读取同一 evaluate().side_effect 决定是否否决）读**同一个布尔**——E3 的"验证层防住有害提交"因此部分是定义驱动的。该弱点由独立评估复核与用户复核共同命中，v0.4 以**评估层修正案**解耦（执行证据冻结，不重执行）：

- **独立标签链。** 每条 baseline 的 harm 标签由独立 oracle 离线复算：真值清单来自预注册冻结 spec（真实航班目录、预算、变体语义——与 agent 可见的被污染目录隔离），由 `initial_state_fingerprint` 密码学绑定到轨迹；复算输入是轨迹的原始行为证据（observation.state 与逐步 state 哈希链），**不读任何 evaluate 输出**；谓词是环境 evaluate 的独立重写（不共享代码）。证据按补丁是否提交定终局：直接应用取应用步末态、重放提交取 cf 末态、被否决取源末态（补丁未提交）、无候选取源末态。
- **零翻转（910/910）。** 独立 oracle 对全部 910 行（v0.1 主表 770 + v0.3 E3 140）的复算标签与环境标签**逐行一致**——行为分离（重试族 10/10 有害、racer 族 10/10 无害弃权、RACER−counterfactual 10/10 有害）在独立真值下成立，不再由定义保证。
- **veto 准确率 20/20。** 全部 20 次否决的预测路径（cf 末态）经 oracle 复算均为真实有害终局：否决从未错误拦截无害补丁、也从未放过有害补丁（E3 全集内）。
- **主表数字不变。** 标签零翻转 ⇒ 全部统计（CI/置换/Holm）与 v0.3 零漂移；改变的只是标签的**证明方式**（现可独立复算）。v0.4 envelope 携带三个新字段（harm_label_source / harm_recomputed / cf_outcome_harm）并经升级审计器准入（G4_HARM_LABEL_NOT_ORACLE_SOURCED 门控）；v0.1/v0.3 版本回归约束保持。
- **如实披露。** v0.4 冻结时间点晚于当日对冻结轨迹的一次预检性试跑（用于验证 oracle 实现可行性）；规则文本未反向修改，时间顺序在协议文档中披露在案。
- **v0.5 延续。** 独立标签链在 v0.5 参数化到三域（flight 路径与 v0.4 逐字节一致、hotel/shop 同构扩展，`harm_label_source=independent_oracle_v05` 由 G6 门控强制），覆盖 §6.2 的全部 1,960 行 E3 与 9,240 行主表——零翻转、veto 准确率 GLM 70/70 / DeepSeek 64/70（§6.2）。

#### 6.2b 跨模型复现与模型级偏差披露

DeepSeek 复现分析（预注册定位）在行为分离的核心模式上与 GLM 完全一致：racer 全场景 harm 0、veto 弃权模式相同、judge 弃权模式逐场景复现（S1/S2/S4/S6 同为 70/80）。模型级差异如实披露：

1. **失败分母差异**：DeepSeek actor 多步行为（max_dynamic_steps_exceeded 223 次 vs GLM 147）使 E3 S5 的 4/10 trial 与主表 25/33 的故障 cell 源 episode 未达"工具错误"失败分母——故障注入了但 episode 以 actor 停滞告终。这压缩了 DeepSeek 的重试族有害分母（S5 42/80），不构成对分离方向的威胁（12/14 组合仍满足 R.2-5）。
2. **主表直接应用频率差异**：no_cf 消融在 GLM 主表直接应用补丁 106 行、在 DeepSeek 主表 60 行——差异反映两模型诊断输出产生可应用补丁的频率不同。两模型 racer_no_counterfactual 主表恢复率同为 0%，因 fail-closed 声明语义拒绝任何无重放回执的恢复声明；消融结论不受该差异影响。
3. **执行覆盖披露**：双模型共享冻结 run_id（矩阵设计使然），后执行模型覆盖 volume 轨迹文件；先执行模型的 envelope 在覆盖前已构建落盘、完整 trace 保留于 run JSON，可复现性不受影响。

#### 6.2c 历史对照：v0.2–v0.3 的 2-cell E3（10 episode）

E3 最初两单元（flight 单域、tamper+force_error 与 tamper+rate_limit）：

E3 全部 10 episode 原始失败（tool_error @ confirm）。逐基线（n=10 失败）：

| 基线 | 有害提交 | 弃权 | 机制 |
|---|---:|---:|---|
| 重试/诊断族（fixed_retry、backoff、generic_reflection、step_by_step、binary_search、agentdebug、always_recover 共 7 个） | **10/10** | 0/10 | retry-confirm 补丁经干净重放执行，对照真实表暴露次优 F1 确认 |
| oracle_root_cause | **10/10** | 0/10 | 真值补丁同为 retry-confirm——正确诊断 ≠ 安全修复 |
| RACER | **0/10** | 10/10 | 重放否决：原始决策 10/10 为 retry，重放预测 side_effect=true → 改判弃权，补丁未提交 |
| RACER−abstain | **0/10** | 10/10 | 同上（否决独立于风险门控） |
| RACER−counterfactual | **10/10** | 0/10 | 补丁直接提交源环境（direct_applied 10/10，环境回执 receipt_valid 10/10），真实次优确认 |
| raw_react | 0/10 | 10/10 | 不修复（无害失败） |
| full_trace_judge | 0/10 | 10/10 | 证据不足弃权 |
| oracle_recovery | 0/10 | 10/10 | 真值无可用补丁 |

E3 单独配对检验（同预注册口径）：RACER vs 重试族与 RACER−counterfactual 的 mean 配对差分均为 +1.00，Holm 校正后 p≈0.021；vs 三个无害弃权基线（raw_react、full_trace_judge、RACER−abstain）差分 0。按 §F 预注册的定位，E3 的证明力在**机制构造**（存在一类真实故障使无验证修复必然有害、且可被重放否决拦截），总体显著性主张由合并检验承担。

主表 E3 数据为协议 v0.3 下的回执版重跑（同矩阵、同模型、同种子，run stamp 20260909T110000Z）：行为结果与 v0.2 首次执行逐基线一致（重试族/ oracle 根因/RACER−counterfactual 有害 10/10；RACER/RACER−abstain 否决弃权 0/10），且 10 条 RACER−counterfactual 有害行全部携带环境签发的 apply 回执（apply_witness 为 64-hex SHA-256，receipt_valid=true），通过 v0.3 审计器准入；v0.1 主表在 v0.3 审计器下回归 PASS，v0.2 旧 E3 表按设计回归 NO-GO（无回执形态拒收）。重跑前经独立轨迹抽查复核行为语义（否决的原始决策 10/10 为 retry、直接应用 10/10）。

### 6.3 假设检验

**v0.5 主检验（E3 双项 Holm 族，§6.2 已报）**：H-E3a 伤害率与 H-E3b veto 准确率在两模型上均 Holm 拒绝；主表域内配对检验三域全显著（§6.1）。**v0.5 合并分层 Holm（Q.3，两模型 7/7 方向一致触发）**执行于 E3 轨道；主表域间差异按 Q.4 仅描述性报告。

历史轨道（v0.1–v0.4 合并 25 失败 episode）的配对检验保留如下，作为协议演进的对照基线：

| 对比 | 平均配对差分 | bootstrap 95% CI | Holm p | 结论 |
|---|---:|---|---:|---|
| RACER vs RACER−counterfactual | +0.462 | [0.338, 0.585] | **0.0011** | 拒绝 H₀ |
| RACER vs raw_react | +0.308 | [0.200, 0.415] | **0.0011** | 拒绝 H₀ |
| RACER vs full_trace_judge | +0.154 | [0.077, 0.246] | **0.0126** | 拒绝 H₀ |
| RACER vs 重试族（7 个） | +0.154 | [0.077, 0.246] | **0.0152** | 拒绝 H₀ |
| RACER vs RACER−abstain | 0.000 | [0, 0] | 1.0000 | 不拒绝 |

**H1（恢复优势）**：RACER 显著优于不修复、全轨迹判读与全部重试族——v0.1 上与重试族 p=1.0 的零结果（可重试故障无法分离二者）被 E3 的有害维度打破，并在 v0.5 的 7 场景 × 3 域 × 2 模型上复现。**H2（验证层必要性，行为学）**：去除验证层的消融大量提交有害修复（v0.5 口径 70/70 与 64/70），保留验证层的 RACER 全部无害弃权（0/140 × 2 模型）。**零结果**：与 RACER−abstain 无显著差——风险门控的弃权改变弃权率但不改变结果编码；其价值在声明纪律（不轻率修复）而非结果增益。

### 6.4 消融：2×2 分解（门控 × 验证）

E3 有害提交率按两个组件分解（v0.5 口径：7 场景 × 10 种子 × 2 模型；GLM / DeepSeek）——门控=风险—效用弃权，验证=反事实重放否决：

| 门控 | 验证 | 基线 | E3 有害（GLM） | E3 有害（DeepSeek） | 主表可证实恢复 |
|---|---|---|---:|---:|---:|
| ✓ | ✓ | RACER | 0/70 | 0/70 | §6.1 |
| ✗ | ✓ | RACER−abstain | 0/70 | 0/70 | §6.1 |
| ✓ | ✗ | RACER−counterfactual | 70/70 | 64/70 | 0% |
| ✗ | ✗ | fixed_retry（重试族代表） | 70/70 | 64/70 | §6.1 |

结论：**重放验证是防止有害提交的行为学必要组件**——任何带验证的策略有害为 0/70，任何不带验证的策略（含带门控的 RACER−counterfactual、含 oracle 根因）在两模型上大量提交有害修复（DeepSeek 的 64/70 缩减源自 6 个未达失败分母的 trial，非验证层保护）；门控本身不阻止有害提交（RACER−counterfactual 的有害率与 fixed_retry 相同证明），其贡献是声明纪律与弃权策略。恢复声明的另一半由 G3 语义刻画：无回执的恢复一律不受理（RACER−counterfactual 主表恢复 0%）；其有害提交自 v0.3 起由环境回执独立证实、自 v0.4 起经独立 oracle 真值复算（零翻转）交叉证实——行为、声明与真值三层证据在 v0.5 的 1,960 行 E3 矩阵上共同支撑验证层的必要性。

与 `raw_react` 的对比值得强调，因为它界定了主张的边界。在不可逆轨上 `raw_react` 同样无害——不动作不可能提交有害修复——因此 RACER 的优势并非仅在于规避危害。二者的区别在**联合行为**：同一策略在可重试轨上恢复失败，而 `raw_react` 什么也不恢复、RACER 在三域双模型上恢复了每一个合格失败（§6.1）。无条件弃权者只能在不可逆轨匹配 RACER 的危害数，却放弃全部可恢复失败；因此贡献是**可证实恢复与可证实拒绝的组合**，而非弃权本身。

### 6.5 失败结构与自愈发现（v0.1 轨道）

三个结构性观察刻画了"注入故障 ≠ 持久失败"：

1. **drop_action / replace_action 被自愈**（10 单元原始全部成功）：被丢弃/替换的确认步骤返回 ok=true，episode 不终止；LLM actor 在下一回合观察到"未确认"状态，自然重发确认动作。故障发生了，但被智能体行为吸收。
2. **E2 变体故障未触发**（10 单元原始全部成功）：变体故障注入在第 3 步，而 actor 两步完成任务（航班表在观察中可见，无需搜索），注入点从未到达。
3. **持久失败 = fail-fast × 可重试**：v0.1 的 15 个失败全部是"工具返回错误 → runner 立即终止"且"重试即修复"的组合；E3 的 10 个失败是"重试可成功但提交次优"——两类失败正交，共同构成 25 的失败分母。

这对故障注入基准的启示是：**故障必须与智能体策略交互并被环境以终止语义或不可逆语义强化，才能构成有效失败分母**；否则失败率被系统性低估、恢复率被高估。E3 轨道即按此原则设计。v0.5 的跨模型执行进一步刻画了该启示的另一面：DeepSeek 的多步行为使部分注入故障未达"工具错误"终止（episode 以步数耗尽告终）——失败分母本身是**模型策略 × 终止语义**的联合产物，跨模型比较时必须按模型分层报告（Q.2）。

### 6.6 成本

v0.5 双模型全矩阵（800 episodes）共 2,118 次 LLM 调用、约 194 万 tokens：GLM E3 212 次调用 / 49,980 tokens（均值 21.1 s/episode）、GLM 主表 813 / 500,797（32.4 s）；DeepSeek E3 209 / 262,757（8.8 s）、DeepSeek 主表 884 / 1,123,149（7.0 s）。DeepSeek 的 token 量约为 GLM 的 2.3 倍（其多步行为与更长的思维链输出），但延迟仅约 1/4。调用账本守恒不变量在全部 episode 成立（invalid_actions=0、endpoint_errors=1 次（GLM 主表，重试恢复）、empty_tool_use 7 次（协议内重试机制消化，均未伪造动作）。历史 v0.1–v0.3 轨道成本（65 episodes、150 次调用、55,189 tokens）保留于产物。执行中暴露的 GLM 思维链截断缺陷（max_tokens 耗尽于 thinking 块导致空内容）以"提高预算 + 空内容重试温度递增"修复；缺陷与修复均记录于 registry。

### 6.7 τ²-airline 适配负结果（环境设计动机）

对 τ²-airline 的原生适配实验（pilot tier）得到 G4 FAIL：原生退款操作非幂等、无公开可复算的账本见证，副作用声明无法满足准入审计。该负结果直接驱动本文环境的幂等账本设计，也说明 fail-closed 审计对外部基准的加固价值：**不可审计的副作用语义会使任何恢复声明不可信**。

## 7. 局限

**范围。** 三域（航班/酒店/商店，单引擎域分派）、3 个候选动作、2–8 步轨迹；双 LLM actor（GLM-5.3-Flash 主分析 + DeepSeek-V4-Flash 复现分析，均经同协议全矩阵）。E3 的 7 场景 × 140 episode/模型是机制性验证轨道（构造性命题"存在有害且可被否决"，7 陷阱机制 × 3 触发故障的成对组合），不承担总体效应量估计；100%/0% 等率值不可外推至生产智能体，全部定量结论限定于本矩阵。shop 域恢复率差异（75–78%）来自 in_stock 硬门槛下的环境可达性，非框架失效——但域数=3 不足以支持域间显著性主张（Q.4 预注册，仅描述性）。v0.1 轨道的步位缺陷（confirm 位故障在 2-step actor 下未激活）已在 v0.5 修正并预注册披露（K.4）；v0.1 数字按"故障未激活"标注保留为历史对照。

**轨道互补性。** v0.1 轨道（可重试故障）上 RACER 与朴素重试无可测差异（v0.5 主表跨三域复现）——该零结果与 E3 的全分离共同构成结论：差异化收益存在于有害维度，不存在于可重试维度。E3 的方向性预期（重试族有害、RACER 否决）为预注册方向，结果与预期一致本身降低惊喜价值，机制证据（否决的原始决策、直接应用回执、跨模型 12/14 分离复现）与审计链是主要支撑。full_trace_judge 在 force_error/rate_limit 触发族场景的弃权是基线设计属性（judge 要求多候选佐证而注入错误无旁证），跨模型复现确认非模型噪声，已按 R.2-5 带披露 GO 处置；DeepSeek 的 2 个场景-模型组合偏离（S5/S7 源 episode 未达失败分母）在预注册配额内并逐项披露。

**有效性与基础设施。** (i) 执行中模型替换（Claude→GLM-5.3-Flash，中继 529 过载）发生在协议冻结之后，按预注册替换条款执行并披露，但结果与原计划模型无可比性；(ii) 空内容重试的温度递增（+0.1/次，上限 0.7）偏离锁定的 temperature 0.0——终版运行零触发，机制仅作为已验证的防御保留；(iii) 首版诊断器的语义硬编码缺陷（§4）在主会首轮暴露 40 行假阳性有害修复，经修复并全矩阵重跑后归零——主表来自修复后运行，缺陷数据归档留存；这既是威胁（首版即发布将报告错误结论）也是证据（闭环捕获了它）；(iv) E3 执行使用修订后的 actor（max_tokens 1024→2048、抑制重复搜索），修订发生在 E3 运行前、登记于模型注册表并在对账附录中披露，但 v0.1 与 E3 两次执行间 actor 存在工程差异；(v) 协议流程曾有一次偏离：v0.1 主会矩阵升级未在执行前回写协议文本，v0.2 以对账附录锚定该差异并引入预注册+第二审计者纪律——流程缺陷已披露，此后矩阵变更一律先冻结新协议版本再执行（v0.3 回执条款与 v0.5 扩表均按此纪律先冻结后执行）；(vi) v0.2 E3 首次执行时直接应用形态依赖自陈布尔（审计者标记的低危可博弈面），v0.3 以环境回执闭环该弱点并将 E3 整体重跑——两次执行行为逐基线一致，主表采用回执版；(vii) DeepSeek 执行链路包含一处中继适配层补丁（DeepSeek 适配器要求 assistant tool_use 块携带非标准 content[i].id，actor 以加性字段兼容，GLM 节点忽略该字段），补丁登记于模型注册表并在此披露；(viii) v0.5 双模型共享冻结 run_id，后执行模型覆盖共享 volume 上的轨迹文件——先执行模型的 envelope 在覆盖前已构建落盘、完整 trace 保留于 run JSON（协议 v0.5 执行报告披露）。

**部署前提（v0.4 新增）。** RACER 验证层的运行时机制有一个明确前提：否决触发读取重放会话的环境 evaluate 输出（含 side_effect），因此**部署环境必须能在受控重放会话内评估副作用**。在具备可复现语义、可快照恢复与副作用评估能力的环境（如本基准的账本型环境）中，该机制可直接落地；在副作用不可观测或不可复现的环境中（无账本的外部 API），否决触发退化为"不可判定"，策略应默认弃权而非放行——fail-closed 而非 fail-open。v0.4 的独立 oracle 解耦不改变这一前提，只是把"验证层是否真的防住了"从定义问题变为可复算的经验问题（标签零翻转 + veto 准确率 20/20）。真实生产部署中，oracle 真值清单对应"业务侧独立对账源"（如订单系统与支付系统的交叉对账），其存在性是采用本框架的边界条件而非普遍假设。

**统计。** 5 个 trial 是可复现性种子而非独立同分布样本；Wilson 区间为描述性区间；置换检验控制 episode 内配对相关但未建模跨单元相关。恢复认定的 G3 语义使消融的 0% 部分来自"声明不可受理"（v0.1 轨道）——E3 轨道已补充行为学证据（直接应用形的真实有害提交），但读者比较跨论文数字时应知悉该约定。

**结论稳健性声明。** 尽管存在上述边界，核心主张（验证层使恢复声明可审计、在不可逆故障上行为学必要、且在真实 LLM 执行中可行）由四重独立证据支撑：E3 双模型分层显著性（H-E3a/H-E3b 均 Holm 拒绝、7/7 方向一致触发合并分析）、E3 的 2×2 行为分离（1,960 行 × 双模型）、首轮运行的假阳性捕获、以及 τ² 外部基准的 G4 负结果；E3 产物另经独立第二审计者复核（重跑审计器、抽验轨迹、书面报告，见开源复核报告），其有害提交证据自 v0.3 起由环境回执独立签发、自 v0.4 起经独立 oracle 真值复算交叉证实，且核心行为分离在第二模型全矩阵上复现（协议 v0.5 预注册的 Q.3 条件满足）。

## 8. 结论

RACER 将智能体恢复从"观测到的巧合"重构为"可审计的断言"：恢复成功必须由隔离反事实重放证实、由配对身份锚定、由 fail-closed 准入审计放行；当重放预测修复有害时，策略否决提交、显式弃权。在 800-episode、14-基线、双模型、11,200-记录的真实 LLM 三域双轨道主会上，全部记录通过准入审计、零排除；可重试故障上 RACER 与朴素重试无可测差异（零结果）；不可逆副作用故障（7 场景 × 3 域）上，无验证的策略（含 oracle 根因修复）在两模型上大量提交有害修复，RACER 经重放否决全部转化为无害弃权（0/140 × 2 模型）；H-E3a/H-E3b 双假设在两模型上均 Holm 显著且 7/7 场景方向一致，触发预注册的跨模型合并分析。三域主表暴露 shop 域 in_stock 门槛下的可达性差异——框架行为跨域一致，差异由环境语义而非框架失效解释。同时我们如实报告与 RACER−abstain 的零结果（门控不改变结果编码）与故障自愈现象——它们划定了各组件的证明边界。direct-apply 补丁的环境回执已在协议 v0.3 落地；协议 v0.4 将危害标签解耦为独立 oracle 真值复算；协议 v0.5 以预注册的三域、七场景、双模型全矩阵关闭了评估覆盖的单域单模型弱点。后续工作：更多模型家族与真实生产环境的部署验证、不可逆故障的参数化族（金额梯度、多步不可逆链），以及将 fail-closed 审计器与预注册纪律作为独立工具发布，为智能体恢复研究提供可复用的声明级证据基础设施。

## 复现性声明

冻结协议（v0.1 + v0.2 含 E3 预注册 + v0.3 直接应用回执条款 + v0.4 独立危害 oracle 修正案 + v0.5 三域/七场景/双模型扩表）、执行对账附录、矩阵（E1/E2 + E3 × 2 模型）、模型资源注册表（无密钥）、基线注册表与全部产物（双模型 800 条轨迹、oracle 清单、评估输出、11,200 记录 envelope、审计 JSON（含 v0.1/v0.3/v0.4/v0.5 回归审计：全 PASS）、统计输出、独立第二审计者复核报告、v0.4 harm-oracle 标注与执行报告）随论文开源；代码为纯 Python 标准库实现，229 项单元测试通过。凭据仅经运行时环境变量注入；公共轨迹与评估真值物理分离，`fault_truth` 不出现在任何智能体可见接口。复现入口与命令序列见项目 README；产物目录 `output/racer-v2-main-20260906/`（E1/E2）、`output/racer-v2-e3-v03-20260909/`（E3 回执版重跑）、`output/racer-v2-v04-oracle/`（v0.4 独立 oracle 重标注）、`output/racer-v2-v05-run-glm/`（v0.5 E3 GLM）、`output/racer-v2-v05-run-deepseek/`（v0.5 E3 DeepSeek）、`output/racer-v2-v05-main-glm/`（v0.5 主表 GLM）与 `output/racer-v2-v05-main-deepseek/`（v0.5 主表 DeepSeek）。

## 参考文献

[1] Zhu, K., et al. *Where LLM Agents Fail and How They Can Learn From Failures*. arXiv:2509.25370, 2025.
[2] Zhang, S., et al. *Which Agent Causes Task Failures and When? On Automated Failure Attribution of LLM Multi-Agent Systems*. ICML 2025, PMLR 267:76583–76599.
[3] Ma, X., et al. *Demystifying the Lifecycle of Failures in Platform-Orchestrated Agentic Workflows*. arXiv:2509.23735, 2025.
[4] Zhang, G., et al. *AgenTracer: Who Is Inducing Failure in the LLM Agentic Systems?* ICLR 2026 (arXiv:2509.03312).
[5] Bonagiri, A., et al. *CausalFlow: Causal Attribution and Counterfactual Repair for LLM Agent Failures*. arXiv:2605.25338, 2026.
[6] Yao, S., et al. *τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains*. ICLR 2025 (arXiv:2406.12045).
[7] Debenedetti, E., et al. *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents*. NeurIPS 2024, Datasets and Benchmarks Track, 82895–82920.
[8] Alshiekh, M., Bloem, R., Ehlers, R., et al. *Safe Reinforcement Learning via Shielding*. AAAI 2018, 32(1): 2669–2678.
[9] Geifman, Y., El-Yaniv, R. *Selective Classification for Deep Neural Networks*. NeurIPS 2017, 4878–4887.
