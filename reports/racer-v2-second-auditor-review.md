# RACER v2 E3 第二审计者复核报告（书面记录）

## 复核基本信息

- **角色：** 独立第二审计者（与执行者隔离的独立审计 agent，无执行角色、无预置上下文，全部证据自行从磁盘重算）
- **复核时间：** 2026-09-07 15:51–16:00（初次全量复核）；D1–D4 修正后闭环重验另记（见文末）
- **触发条款：** 协议 v0.2 §E（"E3 产物进主表前，须由与执行者隔离的独立审计者重跑审计器、抽验 ≥3 条轨迹与 envelope 一致性、并输出书面复核报告"）与 §G GO/NO-GO 条件三
- **利益冲突声明：** 复核者未参与 E3 的设计、实现、执行与首次审计；与执行者无共享上下文

## 初次全量复核（2026-09-07 15:51–16:00，运行 9m10s）

### 复核方法

9 项任务全部完成：协议冻结时序与 SHA-256 锚点核对；自行重跑 `audit_v2_artifacts.py`（E3 envelope + v0.1 主 envelope 回归）；自行重跑 `benchmark_preflight.py --audit`；从 envelope 原始记录独立重算 E3 逐基线行为学数字；抽验首/中/末 3 条轨迹与 envelope 一致性（含 replay_veto/direct_applied 机制字段）；协议 §C–§F 预注册文本与 E3 矩阵逐项比对；独立重跑合并统计并核对配对检验结论；审计器可博弈性检查。

### 核验通过项

| 任务 | 结论 | 关键证据 |
|---|---|---|
| T1 协议冻结时序 | PASS | 协议 SHA-256 `743ab174…` 吻合；mtime 14:57:27 < 首条轨迹 mtime 15:34:39 |
| T2 审计器重跑（E3） | PASS | admission audit verdict=PASS；preflight exit 0、planned=executed=140 |
| T3 E3 数字独立重算 | PASS | 重试族 harm=10/10；racer harm=0/10、abstain=10/10；racer_no_counterfactual harm=10/10——与对账 A2.4 逐行一致 |
| T4 轨迹抽验（首/中/末） | PASS | racer decision 含 replay_veto=true + original_decision=retry + replay_veto_reason=replay_veto_side_effect；envelope 行 abstained=true/harmful=false/side_effect=false；racer_no_counterfactual direct_applied=true，envelope 行 harmful=true/side_effect=true |
| T5 协议预注册内容 | PASS | §C 矩阵结构（2 cell × 5 trial × 14 基线 = 140；F1 ¥420 可退 / F2 ¥360 可退 / F3 ¥480；tamper step_id=0 search_flights + force_error/rate_limit step_id=2 confirm_booking）、§D 重放否决/直接应用语义、§E G4 三形、§F 统计计划与矩阵文件/执行一致 |
| T6 v0.1 回归 | PASS | 770 行主 envelope 在 v0.2 审计器下 verdict=PASS |
| T7 合并统计独立重跑 | PASS（见 D1） | record_count=910；racer vs racer_no_counterfactual n=65、mean_diff=0.462、holm p=0.0011；**11 组配对中 10 组 rejected_h0=true；racer_no_abstain holm_p=1.0 未拒绝** |
| T8 利益冲突 | 无冲突 | 复核者无执行角色 |

### 发现（D1–D4 + 1 项设计弱点）

- **D1（严重）：** 初版对账 A2.5 及论文中"11 个非 oracle 基线全部显著"叙述与统计产物不符——实测 10/11 显著，racer_no_abstain holm_p=1.0 未拒绝 H0。统计产物本身诚实，叙述夸大。
- **D2：** 初版对账 A2.3-1 声称矩阵 `protocol_id` 误用 v0.1——实测矩阵顶层为 v0.2；实际差异仅在任务级/envelope 记录级字段。初版披露不精确。
- **D3：** 初版对账 A2.2 声称"G1–G7 PASS"——审计器实际实现 6 道门（G1/G2/G3/G4/G5/G7，无 G6 usage/cache 门），标签夸大。
- **D4（轻微）：** 初版"8 个重试族"的分组实际含 racer_no_counterfactual（消融基线，非重试族）。
- **设计弱点披露（低危，非数据问题）：** `direct_applied_form` 准入仅凭 4 个自陈布尔（counterfactual_supported=false / replay_valid=false / strict_replay=false / decision ∈ {retry, replace_argument}）接受有害行，无独立环境回执 witness，且审计器不读轨迹文件。本项目数据经 T4 轨迹抽验为真实；该弱点属 v0.2 审计器设计边界，已建议后续版本为 direct-apply 补丁增加独立环境回执。

### 初次判定

**FAIL**（对账报告叙述错误）——底层 envelope / trajectories / matrix / preflight / statistics 产物全部自洽、可复现、无数据层问题；问题集中在 `reports/racer-v2-e3-execution-reconciliation.md` 的叙述性错误。

## 修正与闭环重验

执行者收到 D1–D4 后完成 4 处修正（全部为叙述层，数据产物未动）：

1. D1 → 对账 A2.5 与论文摘要/C4/§6.3/§7 稳健性声明/§8 结论/README：改为"11 个非 oracle 基线中的 10 组 Holm 显著（p=0.0011–0.0152），唯一不显著组为 racer_no_abstain（holm p=1.0，预期诚实结果）"。
2. D2 → 对账 A2.3-1：改为"矩阵顶层 protocol_id 为 v0.2，任务级与 envelope 记录级携带 v0.1 字符串"。
3. D3 → 对账 A2.2 与论文各处："G1–G7/G0–G8"改为"审计器实现的 6 道门（G1/G2/G3/G4/G5/G7）+ 评估器级 G0/G8"。
4. D4 → 对账 A2.5 E3 单独行："重试/诊断族 7 个基线及 racer_no_counterfactual 共 8 组"。
5. direct_applied_form 可博弈面 → 已写入论文 §8 后续工作与对账 A2.7"设计弱点披露"。

### 闭环重验结论

复核闭环：**PASS**（2026-09-07，第二审计者对修正版文件的重验回复，执行者誊录）：

> D1 修正确认：对账 A2.5 与论文摘要/C4/§6.3/§7/§8/README 均改为"11 个非 oracle 基线中 10 组显著，唯一不显著组 racer_no_abstain（holm p=1.0，预期诚实结果）"——与统计产物一致，夸大已消除。
> D4 修正确认：A2.5 E3 单独行改为"重试/诊断族 7 个基线及 racer_no_counterfactual 共 8 组"——分组准确。
> D2 撤回误报：复核者初次重验时只读了矩阵顶层 protocol_id（v0.2）即断言偏离不存在；执行者以 tasks[0].protocol_id 与 envelope 记录级字段实测举证（两者确携带 v0.1 字符串）后，复核者确认原披露在任务级层面属实，D2 撤回；修正后的 A2.3-1 同时澄清顶层与任务级两层事实。
> D3 补正：初次复核指出的"G1–G7 标签夸大"成立；第一次修正编辑曾因工具写入未持久化漏改 A2.2 行，执行者重新应用并经 grep 验证落盘（admission-audit 行现表述为"审计器实现的 6 道门 G1/G2/G3/G4/G5/G7 全 PASS"）。复核者确认 D3 闭环。
> 无新增问题。协议 §G"复核报告无未解决 blocker"满足——E3 结果进主表，判定 GO。

残余观察（不构成 blocker，均已披露）：direct_applied_form 的自陈布尔可博弈面作为 v0.2 设计边界记录在案，建议 v0.3 引入独立环境回执；G6 usage/cache 门在协议文本中定义但未实现为产物审计门，沿用 v0.1 既有状态。

---

*本报告为协议 v0.2 §E 第二审计者条款的履行记录，随论文开源。初次复核与闭环重验均由独立审计 agent 完成；执行者仅负责誊录本报告与落实 D1–D4 修正。*
