# 同行评审意见：Recover or Abstain（v0.5，FCS 投稿版）

**评审对象**：`submission/fcs/recover-or-abstain-fcs.md`（9,877 words；摘要 299 words；27 引用；5 表 2 图）
**评审日期**：2026-09-13
**评审方式**：全文精读 + 引文溯源核验（arXiv/会议官方页逐条核对）+ 四方向相关文献调研
**评审立场**：与作者无利益关联。刻意以"熟悉该子领域的审稿人"视角切入——即那种会问"你和我读过的另一篇论文差在哪"的审稿人。
**前序基线**：`paper-evaluation-2026-09-07.md`（6.5）、`-09-08.md`（6.3）、`-09-13.md`（6.8，内部评估）

> 本次评审与前三轮内部评估的**方法学差异**：前三轮以"论文声明 vs 产物"的核对为主（数字层、结构层）。本轮换成"论文 vs 文献"的核对，因此暴露的外部效度与定位问题与前三轮**不重叠**。两套结论应合并使用。

---

## 0. 结论摘要（先给判断）

**核心结论**：论文的内部证据链（11,200 记录、零排除、双模型、独立 oracle、预注册）经得起核对，我抽查的一切数字与产物一致。**但论文存在一个此前四轮评估都没有触及的结构性问题：§2 相关工作缺失了与 RACER 最接近的整条研究线——Agent 恢复执行 / 回滚（rollback）。** 这不是"少引几篇"的礼貌问题，而是**定位问题**：论文的核心新颖性主张（"replay-verified recovery" vs. 既有的"检测后撤销"）只有在与这条研究线对标时才成立，而论文完全没有对标。

**好消息**：补上这条研究线之后，论文的定位**实际上被加强了**，不是被削弱。原因见 §3——所有回滚类工作都是**事后（reactive）撤销、且以环境可逆为前提**；RACER 是**事前（prospective）否决、且专门针对环境不可逆的场景**。这恰好是回滚研究线自陈的未解难题（GA-Rollback 明确要求环境可重放；DeltaBox 指出不可逆副作用必须走补偿而非回滚）。论文现在把这个最有利的差异化论据留在桌上没用。

**修正后的推荐意见**：**Major Revision**（前序内部评估的"稳进 *ACL Findings / JAIR / TIST"判断在补完 §2 后可以维持；若不做补充，则应下调——因为一个熟悉 rollback 文献的审稿人会给出"novelty partially anticipated"的判断）。

---

## 1. 相关文献调研结果

我按四个方向做了调研。每个方向先给**已核验**条目（条目信息来自 arXiv 官方摘要页或会议出版页，逐条核对），再给**未完全核验**条目（仅来自二手来源，不可直接引用）。

### 1.1 方向一：Agent 恢复执行与回滚（**论文完全缺失的方向**）

这是最重要的发现。论文 §2 引了失败**诊断/归因**（[1–4]）与 CausalFlow [5] 的**反事实修复**，但**完全没有引**"错误已经发生后如何恢复执行状态"这条线。

**【已核验】**

| 工作 | 标识 | 核验信息 | 与 RACER 的关系 |
|---|---|---|---|
| **AgentRewind: Recoverable Execution for Long-Horizon LLM Agents** | arXiv:2608.14380 | Zhuang Y, Chen K, Duan Y, Zheng S, Li J, Zhang X-Y；2026-08-14；19 pages, 5 figs | **最接近的邻居之一**。对齐的 context + environment checkpoint，rewind 后注入 recovery memory（"informed retry"）。自建 MettleBench（部分完成度评分）。 |
| **Generator-Assistant Stepwise Rollback Framework (GA-Rollback)** | arXiv:2503.02519 | Li X, Chen K, Long Y, Bai X, Xu Y, Zhang M；**EMNLP 2025 Main**；v1 2025-03-04, v4 2025-09-26 | 生成器执行、助手逐步审查、检出错误动作即回滚。自陈要求"replayable environments"。 |
| **AgentTether: Graph-Guided Diagnosis and Runtime Intervention** | arXiv:2607.06273 | Zhao C, Zhang S, Gu W, Sun Y, Pei D, Bansal C, Rajmohan S, Ma M；2026-07-07；cs.SE | **同时覆盖诊断与恢复**——这直接触及论文"诊断与修复是两个独立维度"的核心论断。τ-bench 261 任务，Banking 修复 59.04%/65.12%。 |
| **ACRFence: Preventing Semantic Rollback Attacks in Agent Checkpoint-Restore** | arXiv:2603.20625 | Zheng Y, Yang Y, Zhang W, Quinn A；2026-03-21；CoDAIM workshop 2026 | **最危险的邻居**。见 §3.2。记录不可逆工具效应 + "replay-or-fork" 语义 + analyzer LLM 语义比对。 |
| **DeltaBox: Millisecond-Level Sandbox Checkpoint/Rollback** | arXiv:2605.22781 | Dong Y, He J, Liu S, Hou Y, Du D, Xu Z, Yu S, Yang B, Xia Y, Chen H（上交 + 华为）；v1 2026-05-21, v2 2026-06-08；cs.OS | 系统层 C/R（14ms / 5ms）。明确区分"可逆回滚"与"不可逆副作用的补偿"。 |
| **From Faulty Memories to Corrected Actions: Dependency-Guided Rollback Repair** | arXiv:2608.10502 | Yu C, Wang Y, Zhang J, Duan Y, Zheng M, Wu Z, Shi K, Cai T；2026-08-12 | 依赖引导的选择性回滚修复。受控基准 85.3% vs 77.3%。其假设"副作用工具可通过可重置/幂等/补偿接口重执行"。 |

**【未完全核验，仅二手来源，暂不可引用】**
- **WebRollback**（浏览器导航回滚）、**DART**（结构化工具 agent 的 restore point）——均只在 AgentRewind 的 related work 段中被提及，我未找到独立的官方页。⚠️ **特别注意**：检索 "DART" 会命中一篇同名但完全无关的机器人学论文（Domain ARiThmetic, arXiv:2607.00666）。**若引用 DART 必须先确认正确的 arXiv 号，否则极易引错文献。**
- **SafeHarness**（2026-04）、**RFTC**（rollback-first transaction contracts）——二手来源。

### 1.2 方向二：失败分类与可靠性基准（论文部分覆盖）

**【已核验】**
- **Why Do Multi-Agent LLM Systems Fail?（MAST）** — Cemri M, Pan M Z, Yang S, Agrawal L A, Chopra B, Tiwari R, Keutzer K, Parameswaran A, Klein D, Ramchandran K, Zaharia M, Gonzalez J E, Stoica I；**NeurIPS 2025 Datasets & Benchmarks Track**；DOI `10.52202/085713-4082`。14 种失败模式 / 3 大类；其中"任务验证"一类占 21–23.5%。
- **Beyond the Leaderboard: A Synthesis of Tool-Use, Planning, and Reasoning Failures** — Albayaydh W, Zhao R, Flechais I；arXiv:2607.05775；2026-07-07。综合 27 篇 / 19 个基准，六大失败簇。

**与论文的关系**：MAST 的"task verification 21–23.5%"与 Beyond the Leaderboard 的"领导者榜单掩盖失败模式"**正好为论文的动机段提供了第三方量化依据**。论文 §2 第三段（Methodology of agent evaluation）目前只有 [8,9] 两个引用支撑预注册论述，而这个动机（"验证缺口是失败的主因之一"）恰恰可以引 MAST 来加固。这是一处**低成本、高回报**的改动。

### 1.3 方向三：安全过滤与弃权（论文已覆盖，覆盖良好）

论文 [26]（shielding, Alshiekh et al. AAAI 2018）与 [27]（selective classification, Geifman & El-Yaniv NeurIPS 2017）选择得当。核验中确认：
- Shielding 的标准形态是**由先验给定规约驱动**（safety model / LTL spec / reachability）。论文 §2 第四段已经准确指出这一点，并正确地说明 RACER 的证据标准不同（回执而非规约）。**这段的定位分析写得很好，无需改动。**
- Selective prediction / conformal abstention 这条线（reject option、risk–coverage trade-off、conformal abstention 的 `Pr[no-abstain ∧ error] ≤ α`）比 [27] 一篇走得更远。若审稿人来自 ML 安全方向，可能期待看到 conformal abstention 的近期工作。**这是可选的加分项，非必须。**

### 1.4 方向四：副作用感知执行与可验证审计（论文部分覆盖）

**【已核验/半核验】**
- "Simulate Before Actuate" 模式（dry-run / digital twin / sandbox replay → 验证器签发 → 再提交）——与 RACER 的 replay-then-commit **在工程直觉上高度同构**，属于工业实践模式（agentpatternscatalog）。**论文未引任何此类工作**，而这是实践者最可能拿来质疑"这不就是 dry-run 吗"的对照物。建议在 §2 或 §7 加一句区分。
- **IETF COGITATOR Witness Protocol / SCITT**（`draft-noctem-cogitator-witness-protocol`）——hash-chained witness bundle + `witness_root` + **deterministic replay** + canonical JSON（RFC 8785）。这与 RACER 的 7 字段 identity contract 与"可复算回执"在**设计目标上完全一致**（cryptographic, recomputable audit record for agent execution）。**论文的 receipt 设计与这个标准化方向属于同一问题域，未引是明显的遗漏。** 这是全文最容易补、且最能提升"我们做的是一件业界正在标准化的事"体感的一条引用。

---

## 2. 引用完整性核验（逐条）

对现有 27 条引用的抽样核验结果：**未发现虚构引用**，条目信息与官方页一致。现有条目的准确性是可接受的。

发现两处**需要留意**的地方：

1. **参考 [1]（AgentDebug）作者写法**："Zhu K, et al." 使用 `et al.`，而 [19]、[27] 列出全部/部分作者。全套 27 条的作者字段风格不统一（有的 `et al.`，有的 2–4 人全列）。FCS 是顺序编码制、对参考文献格式有明确要求，**建议统一**（要么全部 `et al.`，要么按 FCS 要求的作者数上限截断）。
2. **参考 [5]（CausalFlow）的定位表述**：论文称其为"the closest work to ours"。在 ACRFence（arXiv:2603.20625）与 AgentRewind（arXiv:2608.14380）存在的情况下，**这个"最接近"的判断需要重新论证或改写**。至少应改为"the closest work in the counterfactual-repair line"，并在新增章节中说明为什么 rollback 类工作构成另一个（可能更接近的）对照类。

---

## 3. 基于文献的定位分析：RACER 的真正新颖性在哪

这一节是本次评审的核心贡献。补文献不是为了"显得读过书"，而是因为**补上之后论文的卖点变得更锋利**。

### 3.1 三个坐标轴上的定位

把 RACER 与相邻工作放在三个轴上：

| 维度 | 回滚/恢复执行类<br>（AgentRewind, GA-Rollback, DeltaBox, DART） | 反事实修复类<br>（CausalFlow [5]） | 系统防护类<br>（ACRFence, dry-run 模式, COGITATOR/SCITT） | **RACER** |
|---|---|---|---|---|
| **时机** | 事后（检出错误→撤销） | 事后（归因→修复） | 事前（拦截/模拟） | **事前（预测有害→不提交）** |
| **对环境可逆性的要求** | **要求可逆/可重放**（GA-Rollback 自陈要求 replayable env；DeltaBox 承认不可逆需补偿） | 隐含可回滚 | 要求有 faithful simulator | **不要求可逆——专门用于不可逆场景** |
| **证据标准** | 状态快照一致性 | 因果归因正确性 | 签名/哈希链 | **回执（7 字段 identity）+ fail-closed 准入** |
| **对"未验证成功"的处置** | 无此概念 | 无此概念 | 部分（回执缺失即拒） | **一等公民：不可验证的恢复不计为恢复** |

**这张表就是论文应该写进 §2 的东西。** 它把 RACER 的差异化从"我们多做了 7 个字段的校验"提升为"**在被回滚类工作明确放弃的场景（不可逆副作用）上，我们给出了可审计的恢复语义**"。

### 3.2 为什么 ACRFence 是最需要处理的一篇

ACRFence（arXiv:2603.20625）做的是：在 checkpoint-restore 之后，**记录不可逆工具效应，强制 "replay-or-fork" 语义**——重试的调用如果语义等价则直接返回缓存的响应（不二次触达外部服务），如果语义不同则阻断并要求显式 fork。它还用一个 analyzer LLM 做**语义比对**以区分"语法噪声"（trace_id）与"语义意图"（金额）。

它与 RACER 的相似度：**都记录效应、都要判断重放的调用是否"是同一个动作"、都要在提交前做出放行/阻断决定。** 差异在于：ACRFence 的目标是**防止重复副作用**（幂等性/安全），RACER 的目标是**让恢复声明可被审计**（认识论/准入）。

**这必须在论文里明写。** 否则审稿人的第一反应是："这不就是 ACRFence 的 identity 字段加了个 veto 吗？"——而这个质疑在论文没有引用 ACRFence 的情况下**无法被反驳**，因为事实上的相似性确实存在，需要作者主动划界。

**推荐写法**（可直接用的差异化段落骨架）：
> 与 ACRFence 的 replay-or-fork 语义相比，二者都在提交前对重放动作做出判断，但证据目标不同：ACRFence 用效应日志与语义比对来**防止二次副作用**，其正确性判据是"这个调用是否已被执行过"；RACER 用严格重放回执来**决定一个恢复声明是否可被准入**，其正确性判据是"这个补丁在隔离重放中是否成功且无副作用"。前者是安全机制，后者是声明语义；两者正交，可叠加（用 ACRFence 防重复、用 RACER 决定是否承认恢复成功）。

### 3.3 论文未使用的最强论据

论文 §7 的"Deployment preconditions"（部署环境必须能在受控重放中评估副作用；不可观测时退化为"不可判定"→ 默认弃权）写得很好，但**它是作为局限写的**。换成文献视角，这其实是**与回滚类工作划清边界的正面论据**：

- GA-Rollback 明确要求环境可重放，因此在不可逆环境**不适用**；
- DeltaBox 指出不可逆副作用必须走补偿而非回滚；
- AgentRewind 的对齐检查点回滚在**外部副作用已发生**之后无法挽回；
- 依赖引导回滚修复的假设是"副作用工具可通过重置/幂等/补偿接口重执行"。

**共同点：这条线在"环境不可逆"处集体止步。RACER 恰好从这里开始。** 论文应当把这句写成 §2 的收束句，而不是把"需要可审计环境"只当作局限。

---

## 4. Major Points（必须修改）

### M1. §2 缺失"Agent 恢复执行/回滚"整条研究线（严重性：最高）

**问题**：§2 目前有四个小标题，覆盖诊断 [1–4]、反事实修复 [5]、评测方法论 [8,9]、LLM agent 综述 [10–25]、安全过滤 [26,27]。**没有任何一处讨论"错误发生后如何恢复执行状态"**——而这正是 RACER 所处的子领域。

**影响**：审稿人（尤其来自 systems 或 agent-reliability 方向）会立即识别出这是定位缺失，并给出"贡献被部分预见（novelty partially anticipated）"或"相关工作不完整"的负面判断。这是**本文目前最大的被拒风险来源**，且与实证质量无关——论文的实验做得再好也补不上这个缺口。

**建议**：在 §2 新增一个小节（建议置于"Counterfactual repair"之后），纳入 §1.1 表中 6 条已核验引用，并给出 §3.2/§3.3 的差异化论证。成本：约 250–350 词。

### M2. "replay verification 是必要组件"的结论需要限定条件（严重性：高）

**问题**：§6.5 与 C4 的表述是"**replay verification is a behaviorally necessary component for preventing harmful commits**"。但这个必要性是在**本文自建环境**中建立的——在该环境里，**有害性的唯一可见证据就是重放会话的 `evaluate().side_effect`**。因此"只有带验证层的策略才能避免有害提交"在相当程度上是**环境的构造性质**：如果唯一的 oracle 是重放，那么重放当然必要。

§6.3 的独立 oracle 修正解决了**标签循环性**（harm label 不再来自重放输出），但**没有解决决策循环性**——veto 触发仍然读环境 `evaluate().side_effect`。论文自己在 §7 "Deployment preconditions" 中承认了这一点，但 §6.5 的结论句没有随之限定。

**建议**（二选一或都做）：
1. 把 §6.5 / C4 的表述收窄为：*"in environments that expose a replayable side-effect oracle, replay verification is behaviorally necessary"*；
2. 增加一小段反事实讨论：如果换成**非重放的验证器**（例如学习式 harm 预测器、或 ACRFence 式的效应日志比对），必要性会如何变化。这会把当前的"构造性结论"变成"有条件的、可讨论的结论"，显著提升可信度。

**为何是 Major**：这是论文的中央主张，且是审稿人最容易一句话命中的点（"你的必要性是循环的"）。限定它不损失贡献，反而显示作者理解自己证据的边界。

### M3. 危害语义单一，且未与"更丰富的危害族"文献对话（严重性：高）

**问题**：7 个场景共享**同一个**危害谓词（`confirmed ∧ ¬optimal_selection`，即"提交次优不可逆决策"）。论文的诚实之处在于自陈"场景变化的是诱导方式而非危害含义"，但**如果引入 §1.1 的文献，这个局限可以被正确定位并部分弥补**——因为回滚类工作已定义了更丰富的危害族：

- 重复副作用（ACRFence：duplicate payments）
- 已消费凭据的未授权重用（ACRFence：Authority Resurrection）
- 部分进度丢失（AgentRewind/MettleBench：partial checklist progress）
- 记忆污染导致的下游状态失效（dependency-guided rollback repair）

**建议**：在 §7 Limitations 中扩写"危害语义单一"那段，明确承认当前只覆盖"次优不可逆确认"一种，并用上述四条**具体指明未来工作应覆盖哪些危害类型**。这把一个"被审稿人攻击的短板"转化为"作者已定位的路线图"。成本极低，收益明显。

### M4. §2 第三段（评测方法论）的论证缺少支撑引用（严重性：中）

**问题**："Recent benchmark work emphasizes reproducibility and contamination resistance..."这一段除 [8,9]（预注册）外**没有任何引用**，而它承载着"results are reproducible ≠ claims are auditable"这一关键区分。

**建议**：引入 MAST（验证类失败占 21–23.5%）与 Beyond the Leaderboard（arXiv:2607.05775，榜单掩盖失败模式）作为第三方量化依据。这两条正好证明"验证缺口是可测量的主要失败来源"，直接支撑论文的动机。低成本、高回报。

---

## 5. Minor Points（建议修改）

- **m1. 图 2 caption 与表 3 的口径不一致。** 表 3 只报告 8 个非验证基线（分母 80）与 2 个 RACER 基线（分母 20）；图 2 caption 明确说还画了 `RACER−counterfactual` 消融（10 行/场景）。图与表覆盖的基线集合不同，读者会困惑。**建议**：要么在表 3 增加消融列，要么在 caption 中说明图比表多出消融项。
- **m2. `submission-guide.md` 存在陈旧数字。** 手册第 49 行写摘要"284 words"，第 168 行写"~270 words"，实际为 **299 words**（仍在 <300 硬限内）。摘要本身没问题，但手册是三处数字不一致的出产物，应统一更新。
- **m3. §2 对 CausalFlow 的"closest work"表述需改写。** 见 §2 第 2 点。建议改为在该子线内最接近，并说明 rollback 线构成另一对照类。
- **m4. 参考 [1] 作者字段风格与其他条目不一致。** 见 §2 第 1 点。
- **m5. §6.8 的 "τ²-airline" 与 [6] "τ-bench" 的关系应说明。** τ 与 τ² 是不同的基准谱系，读者可能误以为是同一基准的两个版本。建议首次出现处加一句界定。
- **m6. 可选：区分"dry-run / digital twin"工业模式。** 实践者最容易提出的质疑是"这不就是 dry-run 吗"。建议在 §2 或 §7 用一句区分：dry-run 是**环境提供的模拟能力**，RACER 是**在此之上附加的可审计准入语义**（回执 + fail-closed 门控），二者可叠加而非替代。
- **m7. 可选：引入可验证审计的标准化方向。** IETF COGITATOR Witness Protocol / SCITT（hash-chained witness bundle + deterministic replay + canonical JSON）与本文的 identity contract 属同一问题域。引用它可以把工作放进"业界正在标准化"的叙事，提升影响力体感。
- **m8. 附录 A 的 v0.5 时间戳为 `2026-09-09T04:20:01Z`。** 建议确认所有 v0.5 执行产物均晚于此（论文声称如此），并在数据可用性中给出该断言的可核对方式（例如 manifest 的时间戳范围）。这是论文自己立下的标准，做到即加分。

---

## 6. 引用补全建议（可直接使用的条目）

以下 6 条为**已核验**条目，可直接加入参考文献（bibtex 骨架，需按 FCS 格式调整）：

```bibtex
@article{zhuang2026agentrewind,
  title  = {AgentRewind: Recoverable Execution for Long-Horizon LLM Agents},
  author = {Zhuang, Yu and Chen, Kefei and Duan, Yitong and Zheng, Shuxin and Li, Jian and Zhang, Xu-Yao},
  journal = {arXiv preprint arXiv:2608.14380},
  year   = {2026},
  doi    = {10.48550/arXiv.2608.14380}
}

@inproceedings{li2025garollback,
  title     = {Generator-Assistant Stepwise Rollback Framework for Large Language Model Agent},
  author    = {Li, Xingzuo and Chen, Kehai and Long, Yunfei and Bai, Xuefeng and Xu, Yong and Zhang, Min},
  booktitle = {Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing (EMNLP)},
  year      = {2025},
  eprint    = {2503.02519},
  archivePrefix = {arXiv}
}

@article{zhao2026agenttether,
  title  = {AgentTether: Graph-Guided Diagnosis and Runtime Intervention for Reliable LLM Agent Operation},
  author = {Zhao, Chenyu and Zhang, Shenglin and Gu, Wenwei and Sun, Yongqian and Pei, Dan and Bansal, Chetan and Rajmohan, Saravan and Ma, Minghua},
  journal = {arXiv preprint arXiv:2607.06273},
  year   = {2026},
  doi    = {10.48550/arXiv.2607.06273}
}

@inproceedings{zheng2026acrfence,
  title     = {ACRFence: Preventing Semantic Rollback Attacks in Agent Checkpoint-Restore},
  author    = {Zheng, Yusheng and Yang, Yiwei and Zhang, Wei and Quinn, Andi},
  booktitle = {CoDAIM Workshop},
  year      = {2026},
  note      = {arXiv:2603.20625},
  eprint    = {2603.20625},
  archivePrefix = {arXiv}
}

@inproceedings{dong2026deltabox,
  title     = {DeltaBox: Scaling Stateful AI Agents with Millisecond-Level Sandbox Checkpoint/Rollback},
  author    = {Dong, Yunpeng and He, Jingkai and Liu, Shiqi and Hou, Yuze and Du, Dong and Xu, Zhonghu and Yu, Si and Yang, Baochuan and Xia, Yubin and Chen, Haibo},
  year      = {2026},
  note      = {arXiv:2605.22781},
  eprint    = {2605.22781},
  archivePrefix = {arXiv}
}

@inproceedings{cemri2025whydo,
  title     = {Why Do Multi-Agent {LLM} Systems Fail?},
  author    = {Cemri, Mert and Pan, Melissa Z. and Yang, Shuyi and Agrawal, Lakshya A. and Chopra, Bhavya and Tiwari, Rishabh and Keutzer, Kurt and Parameswaran, Aditya and Klein, Dan and Ramchandran, Kannan and Zaharia, Matei and Gonzalez, Joseph E. and Stoica, Ion},
  booktitle = {Advances in Neural Information Processing Systems 38 (NeurIPS), Datasets and Benchmarks Track},
  year      = {2025},
  doi       = {10.52202/085713-4082}
}
```

**可选第 7–8 条**（需先完成核验再引）：
- `From Faulty Memories to Corrected Actions`（arXiv:2608.10502）— 已在官方页核验，可用；
- IETF COGITATOR Witness Protocol（`draft-noctem-cogitator-witness-protocol-00`）— 属工作草案，引用时须标注 "Internet-Draft, work in progress"。

⚠️ **不要引用**：WebRollback、DART、SafeHarness、RFTC——目前只有二手来源，且 DART 存在**同名不同领域**的高风险（arXiv:2607.00666 是机器人学论文）。

---

## 7. 建议审稿人（承接上一轮遗留事项）

FCS 投稿系统需推荐审稿人。以下按"领域对口、无利益冲突"筛选，并**明示潜在冲突**供老板决定：

| 候选 | 机构/方向 | 对口理由 | 冲突提示 |
|---|---|---|---|
| **Mert Cemri**（或 Ion Stoica 组） | UC Berkeley；MAST 失败分类 | 失败验证缺口的量化权威 | 方向对口但非直接竞争，风险低 |
| **Dong Du / Haibo Chen** | 上海交大 IPADS；DeltaBox | Agent checkpoint/rollback 的系统视角 | 与 RACER 同一问题域的不同层次，风险低 |
| **Yusheng Zheng** | ACRFence；checkpoint-restore 语义 | 最贴近的对照工作 | ⚠️ **属直接竞争/最邻近工作**，审稿意见可能偏严。若需避开，改选 DeltaBox 团队 |

**建议**：推荐 Cemri 与 Du 两人即可（第三位可填 Stoica 或另找一位 agent 安全性方向的学者），**避开 ACRFence 作者**以降低"最邻近工作评审自己的对照物"的摩擦。最终人选请老板确认，我不掌握完整的利益冲突信息。

---

## 8. 逐维度评分（基于文献定位重评，与前序内部评估对照）

| 维度 | 前序内部评估（09-13） | 本次（文献视角） | 变化说明 |
|---|---:|---:|---|
| 新颖性 Novelty | 6.5 | **5.5** | 与 ACRFence / AgentRewind 对标后，核心机制的新颖性被稀释；但**若按 §3 正确划界，可回到 6.5–7.0** |
| 技术深度 TechDepth | 5.5 | 5.5 | 持平 |
| 实验严谨性 Rigor | 7.0 | 7.0 | 持平；M2 的限定说明可再 +0.2 |
| 证据可信度 Credibility | 7.5 | 7.5 | 持平；独立 oracle 是真实优点 |
| 写作与呈现 Writing | 7.5 | **7.0** | §2 缺整条研究线、图/表口径不一致 |
| 影响力 Impact | 6.5 | **6.0** | 未引可验证审计标准化方向（SCITT 等），错失叙事加成 |

**综合**：**6.2 / 10**（本次文献视角），低于内部评估的 6.8。差异完全来自"相关工作缺失"这一项——**这也是为什么本次评审值得独立成文**：内部评估看不到文献层，文献层看不到产物层的核对，两者必须合并。

**补完 M1–M4 后的预估**：**7.0–7.3**。此时"稳进 *ACL Findings / JAIR / TIST"的判断成立；顶会主会仍不建议直投（危害语义单一为硬伤）。

---

## 9. 修改优先级（按投入产出比排序）

1. **补 §2 回滚研究线 + 差异化段落（M1）** — 半天工作量，关闭最大被拒风险。**最高优先**。
2. **限定 §6.5 必要性主张（M2）** — 半天，关闭中央主张的循环性质疑。
3. **§7 扩写危害语义局限 + 指明未来危害类型（M3）** — 2 小时，把短板转为路线图。
4. **§2 第三段补引用（M4）** — 1 小时。
5. **图 2 / 表 3 口径统一（m1）、手册数字更新（m2）** — 1 小时。
6. 其余 minor（引用风格、τ/τ² 界定、dry-run 区分、SCITT 引用）— 按需。

---

## 10. 评审人总结陈述

这篇论文的**实证工程质量是同位体量工作中的标杆**：11,200 记录零排除、双模型全矩阵、独立 oracle 重算零翻转、预注册 + 第二审计人纪律、以及对自身缺陷（40 条假阳性、step-position 缺陷、模型替换、分母差异）的主动披露——这些我都核对过，均属实。

**它的问题不在实验室里，而在图书馆里。** 论文提出的问题（"恢复声明如何被证明"）恰好落在一条活跃的研究线上——Agent 恢复执行与回滚——而论文对这条线完全没有对话。这导致：(i) 核心新颖性主张缺少必要的对照坐标；(ii) 论文最强的论据（专门处理不可逆场景，而回滚类工作在不可逆处集体止步）没有被使用；(iii) 最邻近的 ACRFence 未被处理，留下了无法反驳的"部分预见"质疑。

好消息是**这个缺口补起来不难，而且补完之后论文会更强**——因为它把一个看起来像"只是加了校验"的工作，重新定位为"在被同行明确放弃的不可逆场景上给出了可审计的恢复语义"。我建议按 §9 的优先级做一轮修订。

**推荐意见：Major Revision**（补完 M1–M3 后可接受）。
