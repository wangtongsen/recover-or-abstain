# RACER v2 — v0.4 重标注执行与 GO/NO-GO 结论

- **执行时间：** 2026-09-08T09:17:39Z（协议 v0.4 冻结于 09:16:27Z 之后）
- **协议：** `racer-v2-benchmark-protocol-0.4`（评估层修正案，不重执行）
- **输入（冻结证据）：** v0.1 主表 55 轨迹（2026-09-06）+ v0.3 E3 10 轨迹（2026-09-09 执行版）

## GO/NO-GO 判定：**GO（全部条件满足）**

| # | 条件（协议 §J） | 结果 |
|---|---|---|
| 1 | v0.4 E3 140/140 通过审计器（含 G4_HARM_LABEL_NOT_ORACLE_SOURCED 门控） | PASS, 0 错误 |
| 2 | 标注一致性 910 行零翻转 | agree=910, disagree=0 |
| 3 | 行为字段零漂移 | BEHAVIOR_FIELDS 逐行相等 |
| 4 | 统计零漂移（仅 experiment 名变化） | 确认：全部分布/CI/p 值/Holm 不变 |
| 5 | veto 准确率 20/20 | racer 10 + racer_no_abstain 10，oracle 预测路径全部有害 |
| 6 | v0.1 主 envelope（770）回归 | PASS |
| 7 | v0.2 E3（140）历史快照 | NO-GO（20×G4_DIRECT_APPLY_RECEIPT_MISSING，v0.3 预期行为不变） |
| 8 | v0.3 E3（140）回归 | PASS |
| 9 | merged（910）审计 | PASS |

## 核心结论

1. **解耦完成**：harm 标签现由独立 oracle 计算（真值清单 = 冻结 spec 的真实目录+预算+变体；输入 = 轨迹原始 state + 哈希链验证），与运行时 evaluate / 否决触发完全分离。
2. **零翻转**：910 行 oracle 标签与旧 env-evaluate 标签全部一致。环境判定与独立真值复算**相互印证**——E3 的行为分离（重试族 10/10 有害、racer 族 10/10 否决弃权、racer_no_counterfactual 10/10 直接有害）在独立 oracle 下成立。
3. **veto 准确率 20/20**：所有否决的预测路径（cf 末态）经 oracle 复算均为真实有害终局。否决从未错误拦截无害补丁，也从未放过有害补丁（在 E3 全集上）。
4. **主表数字不变**：由于标签零翻转，全部统计（Wilson CI、bootstrap、置换检验、Holm 校正）与 v0.3 完全一致；改变的只是标签的**证明方式**（现在可独立复算）。

## 产物清单（output/racer-v2-v04-oracle/）

- `harm-oracle-annotation.json` — 逐 run 逐 baseline oracle 判定 + 真值绑定 + 哈希链验证
- `e3-v04-envelope.json`（140）— oracle 标签版 E3 envelope（protocol-0.4）
- `merged-envelope.json`（910）— v0.1 主表 + v0.4 E3 合并
- `e3-v04-statistics.json` / `merged-statistics.json` — 统计（与 v0.3 零漂移）
- `e3-v04-admission-audit.json` / `merged-admission-audit.json` — v0.4 审计 GO
- `regression-v01-main-audit.json`（PASS）/ `regression-v02-e3-audit.json`（NO-GO 预期）/ `regression-v03-e3-audit.json`（PASS）

测试：163 passed（136 原有 + 22 harm_oracle + 5 v0.4 审计门控）。
