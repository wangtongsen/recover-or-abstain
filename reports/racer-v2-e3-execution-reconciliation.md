# RACER v2 E3 执行对账（Protocol v0.2 附录 A2）

- **协议标识：** `racer-v2-benchmark-protocol-0.2`；预注册文本 `reports/racer-v2-benchmark-protocol-v0.2.md` SHA-256 `743ab1747dcf18fb6f94423ae10811e3730bd4d1eb589db7f9878585e209359c`（文件冻结于 2026-09-07 14:57:27，早于 E3 首条轨迹生成时间 15:34:39——预注册时序成立）
- **性质：** 执行后对账记录（附录 A2，非规则）。协议冻结文本未回改；本文件是对账锚点。
- **结果纪律：** 同协议"结果纪律"节——对账不修改任何预注册任务、故障、门控阈值、重放语义或统计口径。

## A2.1 执行环境

| 项 | 值 |
|---|---|
| 执行日期 | 2026-09-07 |
| E3 矩阵 | `experiments/racer-v2-main-matrix-e3.json` SHA-256 `88fea38b90070c2f3102c227ecbae9b7e7d87e00c043b861ad31f64e6b09b4c0` |
| 模型注册表（E3 执行时） | `experiments/racer-v2-model-registry.json` SHA-256 `1e42f9c582e866e5f3f1abb97fff4fddc9d31495c8f2f2401a11b86402a7c6c4`（与 §A 锚定的 v0.1 版本 `4f869328…` 不同，原因见 A2.3-2） |
| Relay actor | `experiments/actors/remote-relay-actor.py` SHA-256 `34299953f571c83c52a096b5efb8f50d6f8b2a3a276b68f88269c8782a53b494`（与 v0.1 主矩阵执行所用 `4ab918eb…` 不同，原因见 A2.3-3） |
| 模型 | `oneapi-relay-glm-5.3-flash`（同 v0.1 主矩阵，无替换） |

## A2.2 执行产物锚点

| 产物 | SHA-256 |
|---|---|
| E3 envelope（140 records） | `c73ecdcd60292690f1114f0deb4acf6cc7ff3260a2a17e42d84038907053622f` |
| evaluator 输出 | `8d7585bf87b68d189234e521e2bca69858ae143dc0af0d9bc28846712be782be` |
| admission-audit（140 行，审计器实现的 6 道门 G1/G2/G3/G4/G5/G7 全 PASS，0 errors） | `30b96134d2931c3cf7715b9c33ed3518adcdf455ca0acf04f022bcb347937fcf` |
| preflight-manifest（planned=executed=140，verdict PASS） | `4cea6414018507ea9be9ca6774fe7cb49c004089683de6a39eb520abc32eb00a` |
| e3-statistics | `f26776a406c1de0761c792e102e3ea3039a0276b1de3810d5aa0abdc9ec4f2a8` |
| merged-envelope（910 records = v0.1 770 + E3 140） | `b38d606eb1be871a60cb40d26bc114b9d2c4953e84eaf246fed8c71b0d389011` |
| merged-statistics（25 失败 episode 配对） | `0f61cc419340fe4adbff9bcb6b6dc3d13b051feec1b8f9999bcc42873d012071` |

## A2.3 与预注册的偏离（如实披露）

无功能性偏离（任务、故障、门控、重放语义、统计口径均与 §C–§G 预注册一致）。三处执行期差异均发生在 E3 轨迹生成之前，不触及冻结规则，但属执行前未登记的工程调整，在此事后如实披露：

1. **E3 矩阵任务级 `protocol_id` 字段沿用了 `racer-v2-benchmark-protocol-0.1` 字符串**（矩阵生成代码的任务模板惰性字段；矩阵**顶层** `protocol_id` 为 v0.2，任务级与 envelope 记录级携带 v0.1 字符串）。E3 实际遵守的规则集为 v0.2 预注册文本；preflight manifest 已显式声明 `protocol_id=racer-v2-benchmark-protocol-0.2`。已运行产物不改。
2. **模型注册表更新**（v0.1 锚定 `4f869328…` → E3 执行时 `1e42f9c5…`）：为在 agent-runner 中实现 v0.2 §D.1/§D.2 的 replay-veto / direct-apply 语义并路由到活模型节点，注册表新增 `env_overlay`（`RELAY_LLM_MODEL=glm-5.3-flash`、`RELAY_LLM_MAX_TOKENS=2048`、`RELAY_LLM_MAX_ACTOR_STEPS=6`）并更新 actor 哈希。注册表是非密钥元数据文件，非 v0.2 冻结对象（冻结对象为协议文本与 E3 矩阵、基线注册表，均已哈希锚定）。
3. **Relay actor 修订**（max_tokens 1024→2048 解决 thinking 截断；system prompt 规定"trace 中已有航班列表时禁止重复 search"）：E3 运行前的工程稳定性修复，修订后哈希 `34299953…` 已登记于模型注册表。v0.1 主矩阵执行使用的是修订前 actor（`4ab918eb…`）。

## A2.4 E3 行为学结果（预注册方向得到确认）

全部 10 episode 原始失败（tool_error @ confirm）；每基线 10 行：

| 基线 | E3 harm | 弃权 | 机制 |
|---|---|---|---|
| fixed_retry / exponential_backoff / generic_reflection / step_by_step_diagnosis / binary_search_diagnosis / agentdebug_targeted_feedback / always_recover | 10/10 | 0/10 | retry-confirm 补丁经干净重放，暴露次优 F1 确认 |
| oracle_root_cause | 10/10 | 0/10 | 真值补丁同为 retry-confirm，次优确认 |
| racer / racer_no_abstain | 0/10 | 10/10 | replay veto：原始决策均为 retry（20/20），重放预测 side_effect=true → 改判弃权，补丁未提交 |
| racer_no_counterfactual | 10/10 | 0/10 | 补丁直接应用到源环境（direct_applied 10/10），真实次优确认 |
| raw_react | 0/10 | 10/10 | 不修复（无害失败） |
| full_trace_judge / oracle_recovery | 0/10 | 10/10 | 证据不足 / 真值无可用补丁 → 弃权 |

## A2.5 统计结果（按 §F 预注册执行）

- **E3 单独**（10 失败 episode）：racer vs 重试/诊断族 7 个基线及 racer_no_counterfactual 共 8 组配对比较 mean_diff=+1.00、Holm 校正后 p=0.0209–0.0210，全部显著；vs 三个无害弃权基线（raw_react、full_trace_judge、racer_no_abstain）差分 0。
- **合并 v0.1+E3**（25 失败 episode）：racer vs 11 个非 oracle 基线中 **10 组** Holm 后显著（p=0.0011–0.0152）；**唯一不显著的是 racer_no_abstain（holm p=1.0，差分恒 0）**——与论文"诚实结果"一致：保留验证层的消融与 racer 结果编码相同，差异来源被归因于验证层。最大差异为 racer_no_counterfactual（mean_diff=+0.462, holm p=0.0011）——验证层必要性由 G3 语义升级为行为学证据。
- **2×2 消融分解**（门控 × 验证，合并 25 失败）：

| 配置 | 基线 | recovery | harm |
|---|---|---|---|
| 门控+验证 | racer | 0.60 | 0.00 |
| 无门控+验证 | racer_no_abstain | 0.60 | 0.00 |
| 门控+无验证 | racer_no_counterfactual | 0.00 | 0.40 |
| 无门控+无验证 | fixed_retry | 0.60 | 0.40 |

## A2.6 残余风险与下一步

- 修订/注册表变更的"执行前登记"流程缺陷已在 A2.3 披露；v0.2 冻结产物（协议文本、E3 矩阵、审计/统计工件）哈希全部锚定。
- 下一步（协议 §E/§G 条款）：独立第二审计者复核（重跑审计器 + 抽验 ≥3 条轨迹 + v0.1 回归确认 + 书面报告），通过后 E3 进主表并改写论文。

## A2.7 独立第二审计者复核（协议 §E 条款履行记录）

**复核者：** 与执行者隔离的独立审计 agent（无执行角色、无预置上下文，全部证据自行从磁盘重算）；复核时间 2026-09-07 15:51–16:00；运行时长 9m10s。

**复核范围与方法：** 协议冻结时序与哈希锚点核对；自行重跑 `audit_v2_artifacts.py`（E3 envelope 与 v0.1 回归）；自行重跑 `benchmark_preflight.py --audit`；从 envelope 原始记录独立重算 E3 逐基线行为学数字；抽验首/中/末 3 条轨迹与 envelope 一致性（含 replay_veto/direct_applied 机制字段）；协议 §C–§F 文本与 E3 矩阵逐项比对；独立重跑合并统计并核对配对检验结论；审计器可博弈性（gameability）检查。

**结论摘要（复核者原文要点）：**

- 通过：协议冻结时序（14:57 < 15:34）与全部 SHA 锚点吻合；E3 admission audit 重跑 PASS；preflight 重跑 PASS（planned=executed=140）；E3 行为学数字独立重算与 A2.4 表逐行一致（重试族 10/10 有害、racer 0/10 有害 10/10 弃权、racer_no_counterfactual 10/10 有害）；3 条轨迹抽检与 envelope 完全一致（replay_veto=true + original_decision=retry；direct_applied=true）；协议预注册内容与执行矩阵吻合；v0.1 主 envelope（770 行）在 v0.2 审计器下回归 PASS。
- 发现（D1–D4，均为对账报告叙述性错误，数据产物本身无误）：
  - D1（严重）：初版 A2.5 声称"11 个非 oracle 基线全部显著"——实测 10/11，racer_no_abstain holm_p=1.0 未拒绝 H0。统计产物诚实，叙述夸大。**已修正**：A2.5 现表述为 10 组显著 + 明示 racer_no_abstain 不显著及原因。
  - D2：初版 A2.3-1 声称矩阵 `protocol_id` 误用 v0.1——实测矩阵顶层为 v0.2；实际差异仅在任务级/envelope 记录级字段。**已修正**：A2.3-1 现精确表述为"矩阵顶层 v0.2、任务级与 envelope 记录级携带 v0.1 字符串"。
  - D3：初版 A2.2 声称"G1–G7 PASS"——审计器实现 6 道门（G1/G2/G3/G4/G5/G7，无 G6 usage/cache 门）。**已修正**：A2.2 现表述为"审计器实现的 6 道门"。
  - D4（轻微）：初版 E3 单独统计行"8 个重试族"实际含 racer_no_counterfactual（非重试族）。**已修正**：A2.5 现表述为"重试/诊断族 7 个基线及 racer_no_counterfactual 共 8 组"。
  - 可博弈性（低危，设计弱点披露）：`direct_applied_form` 准入仅凭 4 个自陈布尔（counterfactual_supported=false / replay_valid=false / strict_replay=false / decision ∈ {retry, replace_argument}）接受有害行，无独立 witness，且审计器不读轨迹文件——本项目数据经轨迹抽验为真，但后续版本应为 direct-apply 增加独立环境回执。已列入后续工作。
- 复核者总体判定：初版 **FAIL**（对账叙述错误）；修正后按协议 §G"无未解决 blocker"口径复核闭环见 A2.8。

## A2.8 复核闭环

- D1–D4 修正后，对账文件与数据产物一致；论文摘要/正文中的"全部 11 个基线显著"表述同步改为"11 个中 10 组显著、唯一不显著组为 racer_no_abstain 且为预期诚实结果"。
- 复核者对修正版文件的重验记录：见 `reports/racer-v2-second-auditor-review.md`（复核者重验修正版对账与论文后的书面确认）。
- 结论：协议 §G 四条件全部满足——140 记录过审计器、preflight 140=140、复核无未解决 blocker、v0.1 回归 PASS——E3 结果进主表。
