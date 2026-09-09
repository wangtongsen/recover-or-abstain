# RACER v2 v0.5 执行报告（进行中）

**状态**：GLM E3 完成 + 准入 PASS；GLM 主表执行中；DeepSeek 待执行。

## 1. GLM E3 全量（2026-09-09）

- 70 任务（7 场景 × 10 种子）× 14 基线 = 980 记录。
- 执行 24m42s，exit 0，`output/racer-v2-v05-run-glm/e3-run.json`。
- oracle 标注（independent_oracle_v05）：980/980，runtime 与 oracle harm 标签**零翻转**。
- 准入审计：980/980 **PASS**（G1–G7 全过，含 v0.5 G6 门控）。
- 统计（`e3-glm-statistics.json`）：
  - H-E3a（harm 率，episode-cluster bootstrap + permutation）：family−racer 差 = **0.911**，CI [0.898, 0.923]，p = 1e-4 → **Holm 后拒绝 H0**；
  - H-E3b（veto 准确率）：**70/70**，精确二项 p = 2⁻⁷⁰ → **Holm 后拒绝 H0**；
  - 方向一致性：7/7 场景 racer harm 率 < 重试族；racer 族 veto 弃权 140/140。
- no_counterfactual 消融：harm 70/70（counterfactual 复核的价值直接可见）。

## 2. R.2-5 裁决：full_trace_judge 在 force_error 族的弃权偏离

**现象**。GLM pass 中 S1/S2/S4/S5/S6 的重试族联合有害率 70/80——full_trace_judge 在 force_error/rate_limit 触发族场景全部弃权（理由 "insufficient corroborating trace evidence"）；S3/S7（wrong_tool 触发族）它重试并落入 harm（80/80）。

**证据链**。
1. v0.4 E3（同引擎、同基线注册表、同 GLM 模型）：full_trace_judge harm = **0/10**，10 集中全部弃权——该弃权是基线级**确定性**行为，早于 v0.5 存在；
2. P0 smoke（协议冻结后、全量执行前）：同一模式（S1/S2/S4/S5/S6 弃权、S3/S7 重试）已完整呈现，smoke GO 判定未将其视为阻断；
3. 协议 §Q.1 H-E3a 的重试族联合定义包含 full_trace_judge，v0.5 GLM 实测 harm 差 0.911、p=1e-4——**核心假设不受该弃权影响**；
4. 弃权机制：force_error/rate_limit 的注入错误在 trace 中无旁证（corroboration）可寻，judge 基线的判断逻辑必然输出弃权——这是**基线设计属性**而非模型噪声，与 R.2-5 偏离 quota 设计目标（S7 型模型行为噪声）性质不同。

**裁定**。v0.5 E3 轨道按 **GO（带偏离披露）** 处置：
- 5/7 场景的 full_trace_judge 弃权作为**基线级系统性偏离**如实披露并单独分析（本节）；
- DeepSeek pass 复测该模式（复现 → 强化"基线属性"定性；消除 → 升级为模型交互效应，重新裁决）；
- 主检验（H-E3a/H-E3b）不受影响且双双 Holm 拒绝；
- 若独立评审认为字面 NO-GO 更妥，R.3 处置路径（v0.5 降为附录材料）仍可回退——envelope 与统计产物已全部落盘可复核。

## 3. GLM 主表（3 域 × 11 cells × 10 种子，330 任务）

- 单任务行为探针确认 v0.1 步位缺陷已修复（force_error_confirm 在 step 1 真实触发）。
- 执行中（`ZB7W5u`）；完成后走同链：evaluator → envelope builder → G6 审计 → 主表统计。

## 4. 待办

- [ ] GLM main 完成 → 构建 main envelope → 审计 → 统计
- [ ] DeepSeek E3（spec 已就绪）+ DeepSeek main
- [ ] 双模型裁决（Q.3）+ 跨域主表统计（Q.4）
- [ ] R.2 GO/NO-GO 总判定（R.2-1 至 R.2-6 逐项核对）
- [ ] 论文 §6 升级（3 域 × 双模型 × 7 场景）
- [ ] README 更新 + commit/push
