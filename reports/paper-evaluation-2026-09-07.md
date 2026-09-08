# 论文独立评审报告：Recover or Abstain (RACER v2, E3 回执版)

**评审立场**：资深程序委员（顶会 + 期刊双背景），LLM Agent 可靠性/安全评测方向。
**评审日期**：2026-09-07
**评审对象**：`recover-or-abstain-paper.md`（"Recover or Abstain: Replay-Verified Recovery for Tool-Calling Agents"）
**核验范围**：仅读取仓库内协议/产物/报告/测试，未改动任何代码或产物。
**总体印象**：一篇**方法学纪律扎实、写作诚实、但科学增量有限且实验规模偏小**的基准/方法论论文。当前水平定位为 **workshop / arXiv / 中文二区期刊**，尚不足以进入 ICLR/NeurIPS/ICML/ACL 主会。

---

## 1. 执行摘要

RACER v2 把"智能体恢复"重新定义为一种须经审计的断言，并配套了覆盖预注册冻结、fail-closed 准入、三重回归、独立第二审计者的实验纪律。这套"临床级流程纪律"在智能体基准里罕见且真实有效——第二审计者确实验出了叙述性夸大（"11 个非 oracle 基线全部显著"实为 10/11，G 门标签虚标），作者已据实修正。这是本文最大的优点：**它用可追溯的证据链约束了自己**。

然而，论文的核心科学贡献是**增量性**的：反事实重放（CausalFlow 已有）、abstain（风险规避策略的常识）、沙箱先验证再提交（软件工程的经典范式）三件单拿出来都不新；真正的新意是"重放否决→改判弃权"的决策语义、让有害声明不再依赖自陈布尔的**环境回执**，以及上述审计基础设施。E3 轨道的"验证层使有害提交从 10/10 降为 0/10"结论**真实但部分由定义驱动**（危害标签与否决触发是同一 `side_effect` 变量），且方向为预注册、n=10，惊喜价值有限。

最重的短板是**实验规模与环境玩具化**：单域（航班预订）、3 个候选动作、2–3 步轨迹、65 个 episode、主表单一 LLM actor（GLM-5.3-Flash）。流程纪律的严谨度远高于数据本身的统计力度，二者不匹配。

---

## 2. 数字核验结果

逐项抽查了论文的关键数字与仓库产物，结论如下（✓ = 与产物一致；⚠ = 有出入/需注意）。

| # | 论文主张 | 产物核验 | 结果 |
|---|---|---|---|
| 1 | 910 记录（770 主 + 140 E3），65 episode | `merged-statistics.json`: record_count=910, episode_count=65；main 770 / E3 140 | ✓ |
| 2 | 每基线 25 个失败 episode（15 E1/E2 + 10 E3） | 各基线 `n_failures=25` | ✓ |
| 3 | E3 有害 10/10（重试/诊断族 7 个 + oracle_root_cause） | `e3-v03-statistics.json`：上述基线 harm_rate=1.0 | ✓ |
| 4 | E3 RACER/RACER−abstain 否决弃权 0/10 | racer / racer_no_abstain harm_rate=0.0, abstention=1.0 | ✓ |
| 5 | E3 直接应用 10/10 且回执 receipt_valid | racer_no_counterfactual harm_rate=1.0（自陈+环境回执双证据，见 §4 G4） | ✓ |
| 6 | 合并 Holm 10/11 显著，p=0.0011–0.0152 | `holm_correction` 11 组，10 组 rejected_h0=true；最小 holm_p=0.00110，最大=0.01520 | ✓ |
| 7 | racer_no_counterfactual 平均配对差分 +0.462 | mean_paired_difference=0.461538… | ✓ |
| 8 | 第二模型 pilot 5/5 复现，p≈0.06 | `p1-statistics.json`：重试族 harm 5/5、RACER 弃权 5/5、直接应用 5/5；permutation p≈0.057–0.065 | ✓ |
| 9 | 136 项单元测试通过 | `pytest tests/ -q` → **136 passed** | ✓ |
| 10 | 三重回归：v0.1 PASS / v0.2 NO-GO / v0.3 PASS | `regression-v01-main-audit.json`=PASS；`regression-v02-e3-audit.json`=NO-GO（20 errors，10 条 direct-apply 行各 2 错）；e3-v03 admission=PASS | ✓ |
| 11 | preflight G8：770=770、140=140 | 两个 `preflight-audit.json`：planned=executed=770 / 140，G0/G8 PASS | ✓ |

**核验结论**：所有可量化的主表数字与产物**完全一致，未发现数字虚报**。

### 需注意的不一致（非数字虚报，属打磨问题）
- **命名不一致**：论文正文用 `RACER−abstain` / `RACER−counterfactual`，但所有 `statistics.json` 键名为 `racer_no_abstain` / `racer_no_counterfactual`。审稿人会要求统一。
- **README 陈旧**：`README.md`（中/英）写"91 项测试/91 offline tests"，而实际 `pytest` 为 **136 passed**、论文正文"136 项单元测试通过"正确。README 与论文脱节，但不影响论文主张。
- **第二审计者 D1 暴露的旧夸大**：初稿曾写"11 个非 oracle 基线全部显著"，实测 10/11。当前论文已改为准确的"10/11，唯一不显著组 racer_no_abstain"，**修正到位**。该插曲本身是流程纪律有效的证据，但提示：论文曾出现过叙述快于产物的倾向，作者已自我纠正。

---

## 3. 分维度评分（各 1–10）

### (a) 技术新颖性 — 5/10
- **公允性**：相关工作对 AgentDebug / Who&When / AgentFail / AgenTracer / CausalFlow / τ-bench / AgentDojo 的定位基本公允，且明确把 CausalFlow 标为"最接近构想"并区分了"重放回执 / 否决语义"的差异。✓
- **增量判断**：
  - 反事实重放 ← CausalFlow 已有；
  - abstain 作为一等动作 ← 风险规避策略的常识；
  - "沙箱先验证再提交" ← 软件工程的经典范式（canary / shadow test）。
  - **真增量**是：(i) replay-veto 决策语义（预测有害即改判弃权、不提交）；(ii) 环境签发不可伪造的 apply 回执（apply_witness=SHA-256(...)），使"有害"不再依赖自陈布尔；(iii) 把上述封装为可复用的 fail-closed 审计基础设施（G0–G8）。
- **扣分点**：没有任何一个组件是"从无到有"的突破；组合 + 审计框架是贡献，但属于工程化整合。另外，E3 的否决触发变量与危害标签是**同一个 `side_effect`**，使"验证层必要且充分"在 RACER 自身零有害上部分是**定义性**的（见 §4.c）。
- **引用核验提醒**：核心新颖性论据建立在与 CausalFlow [5] 的区分上，审稿人必须核实 CausalFlow 真实内容与本文声称的差异；本文无法替审稿人背书该引用。

### (b) 实验严谨性 — 7/10
- **真实强点**（罕见且有效）：
  - 协议版本纪律（v0.1→v0.2 预注册 E3→v0.3 回执条款，先冻结后执行）；
  - fail-closed 准入（G1–G5/G7）+ 评估器级 G0/G8；
  - **三重回归**真实发生：`regression-v02-e3-audit.json` 在 v0.3 审计器下对旧 E3 表给出 **NO-GO（20 错误）**，证明审计器不是"橡皮图章"；
  - **独立第二审计者**确实验出了夸大（D1"全显著"→10/11、D3"G1–G7"标签虚标），作者据实修正——这是"流程即方法学贡献"的**实证**，而非包装。
  - 136 项单元测试全过，产物可机复验。
- **这是方法学贡献还是流程包装？** 主要是**真实的方法学贡献**（它把临床试验式预注册 + 审计落地为可运行代码与冻结产物），但存在**比例失衡**：对 65-episode 玩具级研究投入了接近顶刊临床实验的流程密度。
- **扣分点**：主表单模型（GLM-5.3-Flash）；5 个 trial 是"可复现性种子"而非 iid 样本（论文已声明）；统计功效薄——主显著性建立在 25 个失败 episode 上。

### (c) 主张-证据匹配度 — 6/10
- **诚实度很高**：§7 局限章节罕见地坦诚披露了模型替换（Claude→GLM）、首版硬编码缺陷（40 行假阳性）、流程偏离、自陈布尔弱点、单模型单域——这是优点。
- **主张—证据缺口（真实存在，与诚实披露并存）**：
  1. **单域单模型窄支撑 vs "tool-calling agents" 泛化主张**：航班域、3 动作、2–3 步轨迹，无法支撑对"工具调用智能体"的普遍结论。论文用 §7 自我限定，但主标题与摘要的泛化措辞仍偏宽。
  2. **E3 部分由定义驱动**：危害标签（`side_effect`，由真实航班表对照判定）与否决触发（重放 `E(τ_cf).side_effect=true`）是同一变量。因此"RACER 自身 0/10 有害"在内部是预期的；真正有信息量的是**跨基线对比**（无验证基线确实 10/10 提交有害），该对比是真实的、非同义反复。但"验证层必要且充分"的措辞需谨慎——其"充分性"在定义上成立。
  3. **否决的能力假设**：重放否决要生效，环境必须能独立评估 `side_effect`（真实表驱动重放）。这要求部署环境具备"干净会话 + 反事实最优可知"的强假设，生产环境未必满足。论文仅在 G4 回执层面触及，未充分讨论该部署前提。
  4. **惊喜价值低**：E3 方向与预期均为预注册，结果符合预期；"存在有害且可被否决"是构造性命题，n=10。
  5. **"60%/0%" 不可外推**：论文已声明，但读者仍易被大数字吸引。

### (d) 写作与定位 — 8/10
- **强**：逻辑清晰、贡献（C1–C4）与形式化（定义 1–3）明确、局限披露质量在同级论文中属上乘。
- **弱（打磨）**：
  - 命名不一致（见 §2）：`RACER−abstain` vs `racer_no_abstain`；
  - 流程措辞略带自我褒扬（"临床试验式""即插式加固层"），与 modest 结论的基调略有张力；
  - README 与论文测试数脱节（91 vs 136）；
  - 个别 G 门历史标签（D3 已指出早版"G1–G7"虚标），现稿已修正为"G1–G5/G7 + G0/G8"，一致。

**加权总分 ≈ (5+7+6+8)/4 = 6.5/10**。

---

## 4. 致命伤与修复成本（投顶会主会会被拒的 top 理由）

| # | 致命伤 | 对主会（ICLR/NeurIPS/ICML/ACL）的影响 | 修复成本 |
|---|---|---|---|
| F1 | **环境玩具化**：单域（航班）、3 动作、2–3 步轨迹，对照 τ-bench / AgentDojo 的真实多步多工具域明显偏弱 | 主会 realism/breadth 门槛直接不达标 | **高**（2–3 月）：新增 ≥3 域、≥6–8 工具、≥5–10 步轨迹、真实副作用语义 |
| F2 | **主表单模型**（GLM-5.3-Flash），泛化性无证据 | "tool-calling agents" 主张站不住 | **高-中**：补 ≥4 个跨家族模型（含一个 frontier + 一个开源权重） |
| F3 | **组件单独看不新**；E3 "必要且充分"部分由定义驱动 | 新颖性被质疑为"组合而非突破" | **中**：重定位为"审计基础设施 + 基准 + 首份实证"，并用**独立危害 oracle** 与否决触发解耦 |
| F4 | **E3 预注册方向 + n=10**，惊喜价值低；主显著性仅建于 25 失败 ep | 结果被视作 confirmatory，缺乏 discovery | **中**：增加未注册探索性分析、扩大矩阵到 ≥10 trial/cell |
| F5 | **统计功效薄**：5 trial 为种子非 iid，Wilson CI 宽 | 审稿人质疑效应量可靠性 | **中**：增加 trial 数 / 跨单元独立重复 |
| F6 | **流程纪律 ≫ 数据规模**的观感 | 易被批"流程包装" | **低-中**：重述叙事，使流程投入与结论规模匹配，不夸大 |

---

## 5. 投稿定位建议（务实分级）

| 去向 | 适配度 | 预期接收概率 | 说明 |
|---|---|---|---|
| **顶会主会**（ICLR/NeurIPS/ICML/ACL） | 低 | **10–15%** | F1/F2/F3 任一都足以 reject；除非先完成大规模扩表 |
| **顶会 workshop**（agent safety / evaluation / agentic AI @ NeurIPS·ICML·ICLR；evalbench 类） | **高** | **50–65%** | 最契合：方法论 + 基准 + 安全取向，且纪律故事对 workshop 有吸引力 |
| **arXiv 先行** | 强推荐 | — | 尽早放出，确立优先级并开源审计基础设施 |
| **CCF 中文期刊（一/二区，如《软件学报》《计算机学报》《计算机研究与发展》）** | 中-高 | **40–55%** | 严谨的预注册 + 审计纪律 + 基准贡献符合中文期刊口味；通常仍会要求补域/补模型 |
| **NeurIPS D&B / ICLR（扩表后）** | 中（需先投入） | 30–45%（扩表后可达 50%+） | 完成 F1+F2 后可达 datasets/benchmark 轨道水平 |

### 首选推荐
**先 arXiv 预印本，再投 agent-safety / evaluation 方向顶会 workshop，并同步按 CCF 二区中文期刊准备扩表版。**

- **理由**：本文最强的资产是"可审计的恢复声明 + 预注册纪律 + fail-closed 审计基础设施"，这恰恰是 workshop（重方法学、重可复现、重安全）最欢迎的叙事；而主会因 F1/F2 的尺度与泛化硬伤几乎必然被拒，强行投主会只是消耗一轮周期。arXiv 先行可保住方法论优先级，中文期刊则能吃下其"基准 + 纪律"的扎实度。
- **预期接收概率（首选路径）**：workshop 50–65%；若扩表后再战主会/ D&B 轨道，可升至 45–55%。

### "再补什么就能上一档"的具体路径
1. **主表扩域 + 扩模型（解 F1/F2）**：新增 ≥2 个真实域（如预订类之外的"数据操作/API 编排"），主表纳入 ≥4 个跨家族模型；E3 类不可逆副作用轨道在每域复现。
2. **解耦危害 oracle 与否决触发（解 F3）**：用独立于重放的环境真值 oracle 定义 `side_effect`，并显式讨论"否决依赖环境可评估副作用"的部署前提；把"必要且充分"改为"在可审计环境下，验证层是防止可观测有害提交的必要组件"。
3. **扩大统计基底（解 F4/F5）**：每 cell ≥10 trial，至少 2 个独立任务单元族，使主显著性不再仅依赖 25 失败 ep。
4. 完成上述三项后，目标可上移到 **NeurIPS Datasets & Benchmarks / ICLR 主会**。

---

## 6. 给作者的三条最高优先级建议

1. **修正"必要且充分"的措辞并解耦 oracle**：E3 的危害标签与否决触发是同一变量，使 RACER 自身零有害在定义上成立。请用**独立于重放的环境真值 oracle** 定义危害，并补一段"否决能力依赖环境可评估副作用"的部署前提讨论。否则任何严谨审稿人都会把 E3 判为近同义反复。

2. **主表必须扩域 + 扩模型再谈泛化**：单域（航班）、3 动作、2–3 步、单模型（GLM-5.3-Flash）是当前投任何主会的头号阻断项。在 MAIN 表（而非 5-ep pilot）中加入 ≥2 个新域与 ≥4 个跨家族模型；否则"tool-calling agents"的标题主张缺乏支撑，只能诚实地降级为"单域试点"。

3. **统一命名并消除陈旧/自褒表述**：论文用 `RACER−abstain`/`RACER−counterfactual`，而所有 `statistics.json` 键是 `racer_no_abstain`/`racer_no_counterfactual`——必须统一，否则被批"产物与正文对不上"；同步把 README 的"91 测试"更正为 136；将"临床试验式""即插式加固层"等自褒措辞收敛为实证语气，使流程投入与结论规模读起来匹配。

---

*核验所用关键产物路径*：
`output/racer-v2-main-20260906/{main-envelope.json,statistics.json,admission-audit.json,preflight-audit.json}`、
`output/racer-v2-e3-v03-20260909/{e3-v03-statistics.json,merged-statistics.json,admission-audit.json,merged-admission-audit.json,regression-v01-main-audit.json,regression-v02-e3-audit.json}`、
`output/racer-v2-e3-v03-second-model-pilot/{p1-statistics.json,p1-admission-audit.json}`、
`reports/racer-v2-second-auditor-review.md`、`reports/racer-v2-second-model-pilot.md`。
测试核验命令：`python -m pytest tests/ -q` → 136 passed。
