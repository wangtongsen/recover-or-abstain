# Recover or Abstain：面向工具调用智能体的风险感知反事实修复

> **Scope / 范围声明**
>
> 本仓库包含两个阶段：
>
> 1. **v1 确定性原型**（`services/` 六服务闭环）：验证「诊断 → 恢复决策 → 反事实重放 → 结果评估」的系统闭环；
> 2. **v2 配对真实 LLM 基准**（RACER v2）：真实 LLM actor 执行预注册双轨道矩阵（E1/E2 可重试故障 55 episode + E3 不可逆副作用 10 episode）× 14 基线 = 910 记录，全部经 fail-closed 准入审计（G0–G8）。v2 结论限定于本矩阵，不外推至生产智能体。

---

## 中文文档

### 项目简介

工具调用智能体在执行中可能遭遇动作替换、工具错误、限流或动作丢失。仅给出一个根因标签并不足以保证恢复安全：错误的修复本身可能造成副作用，而在证据不足时继续执行则可能放大损失。

本仓库实现 **RACER（Risk-Aware Counterfactual Repair，风险感知反事实修复）** 的一个确定性本地原型。RACER 将四段能力连接为闭环：

```text
任务执行 → 失败轨迹 → 根因候选与置信度 → 恢复动作候选
        → 隔离的反事实重放 → 成功 / 副作用 / 成本验证 → 恢复 或 abstain
```

当诊断置信度低于阈值，或缺乏可验证补丁时，策略**显式选择 abstain**——这是方法的核心设计，而非兜底行为。

### 关键设计

- **故障真值隔离**：公共轨迹与评估器专用真值清单分离，智能体无法直接查询注入配置
- **状态哈希重放**：支持重放一致性检查，避免重放过程本身引入偏差
- **副作用优先**：恢复动作需通过反事实重放验证，有害修复被显式记录与计数

### 冻结结果

采用冻结产物 `reports/local-flight-results.json`（而非混入额外 smoke 运行的 `local-flight-evaluator.json`）。

| 项 | 值 |
| --- | --- |
| 故障类别 × seed | 5 类 × 3 seed |
| 唯一任务单元 | 15 |
| 基线展开 | raw / recovery / explicit-patch oracle，共 45 条基线记录 |
| recovery 基线恢复率 | 12 条原始失败中恢复 3 条（25.00%） |
| 记录的有害修复 | 0 |

> `explicit-patch oracle` 是 patch-availability-conditional reference：仅对故障真值中含显式可用补丁的情形执行参考上界修复。

### 仓库结构

```text
services/      六个核心服务（各自独立镜像）
  task_env /           任务环境：执行轨迹、注入故障、维护状态
  agent_runner /       执行器：按策略推进任务
  diagnoser /          诊断器：输出根因候选与置信度
  recovery_policy /    恢复策略：在恢复动作与 abstain 之间决策
  counterfactual /     反事实重放：隔离重放并给出验证证据
  evaluator /          评估器：持有真值清单，产出统计（analysis profile）
adapters/      外部 benchmark 适配层（τ² airline adapter）
experiments/   实验规格、模型/基线注册表、actor 定义
scripts/       实验执行、结果分析、产物审计、预检脚本
tests/         离线回归测试（163 项）
reports/       冻结结果、统计、基准协议与离线确认报告
output/        运行产物与证据（smoke、preflight、admission fixture）
```

### 快速开始

**路径一：Docker（推荐，无需本地依赖）**

```bash
docker compose up --build          # 启动 task-env / agent-runner / diagnoser / recovery-policy / counterfactual
docker compose --profile analysis up evaluator   # 额外启动评估器
```

**路径二：本地测试**

```bash
python3 -m pytest tests/           # 需要 pytest，当前 163 项全通过
```

### 审计与可复现

研究产物在写入结果表前需通过一系列 fail-closed 审计关卡（G0–G8），覆盖：

- 模型秘密隔离与版本锁定
- split / paired identity 一致性
- canonical envelope 契约与去重证明
- strict replay receipt
- main tier 与 registry 登记

相关脚本：

```bash
python3 scripts/audit_v2_artifacts.py     # 产物 fail-closed 审计，输出 PASS / NO-GO
python3 scripts/benchmark_preflight.py    # 从冻结矩阵生成 planned-only manifest / 审计 manifest
python3 scripts/main_statistics.py        # Wilson CI + 配对 bootstrap + 符号置换 + Holm
python3 scripts/build_e3_manifest.py      # E3 executed preflight manifest
```

### RACER v2 主会（预注册双轨道）

- **协议：** v0.1（E1/E2 冻结，2026-09-02）+ v0.2（E3 预注册 + v0.1 执行对账，2026-09-07 冻结于 E3 执行前）+ v0.3（direct-apply 环境回执条款，2026-09-07 冻结于 E3 回执版重跑前）+ v0.4（独立危害 oracle 评估层修正案，2026-09-08 冻结，不重执行）——`reports/racer-v2-benchmark-protocol*.md`
- **矩阵：** E1/E2 55 episode + E3 10 episode × 14 基线，GLM-5.3-Flash actor，模型/基线注册表无密钥
- **产物：** `output/racer-v2-main-20260906/`（770 记录，v0.1）、`output/racer-v2-e3-v03-20260909/`（E3 回执版重跑 140 记录）与 `output/racer-v2-v04-oracle/`（v0.4 独立 oracle 重标注：910 行标签零翻转、veto 准确率 20/20、统计零漂移，GO 报告见 `reports/racer-v2-v04-execution-report.md`）；v0.4 审计器下四重回归：v0.1 主表 PASS / v0.2 旧 E3 表 NO-GO（无回执形态按设计拒收）/ v0.3 重跑表 PASS / v0.4 oracle 标签表 PASS
- **v0.3 回执机制：** direct-apply 补丁由任务环境签发不可变回执（apply_witness = SHA-256(canonical JSON{sequence, tool, arguments, state_after_hash, success, side_effect, run_id})），行为结局位于哈希材料内——消除 v0.2 自陈布尔的残余可博弈面
- **v0.4 独立危害 oracle：** harm 标签与重放否决触发解耦（此前二者读同一 side_effect 布尔——同义反复弱点）。标签由独立 oracle 从预注册真值清单（冻结 spec 的真实目录+预算+变体，`initial_state_fingerprint` 密码学绑定）与轨迹原始 state（哈希链验证）离线复算，不读任何 evaluate 输出；v0.4 envelope 携带 harm_label_source/harm_recomputed/cf_outcome_harm 三字段，审计器新增 G4_HARM_LABEL_NOT_ORACLE_SOURCED 门控
- **核心结果：** E3 不可逆故障上无验证策略 10/10 有害提交（RACER−counterfactual 的有害行 10/10 携带有效环境回执）、RACER 重放否决 0/10；合并 25 失败 episode 配对检验 RACER vs 11 个非 oracle 基线中的 10 组 Holm 显著（p=0.0011–0.0152，唯一不显著组为 racer_no_abstain——预期诚实结果）
- **第二模型 pilot（探索性，不进主表）：** DeepSeek-V4-Flash 在 E3 单 cell × 5 episode 上逐基线复现行为分离（重试族有害 5/5、RACER 否决弃权 5/5、直接应用回执 5/5 有效）——`reports/racer-v2-second-model-pilot.md`、`output/racer-v2-e3-v03-second-model-pilot/`

### 关于 τ² airline adapter

阶段 A 的锁定安装与工具语义实证已完成，结论为**负**：τ² airline 原生环境**不支持** RACER G4 要求的实体级幂等退款账本——重复 cancel 的 ledger 条目按 1→2→4→8 指数膨胀、无唯一退款标识/幂等键/witness 字段、返回对象被原地污染、用户侧余额不结算、无对账工具。

因此退款/取消相关的 counterfactual 分支必须标记 `counterfactual_supported=false`，除非在 adapter 边界引入外部 witness 层。该实证可作为论文中「公开 benchmark 副作用语义不足以支撑恢复审计」的论据。

### 论文

- Markdown：`recover-or-abstain-paper.md`
- 排版版：`recover-or-abstain-paper.html` / `.docx`

### 许可证

MIT，见 `LICENSE`。

---

## English (condensed)

**Recover or Abstain: Risk-Aware Counterfactual Repair for Tool-Calling Agents**

> **Not an LLM benchmark.** This repository reports a deterministic local flight prototype that validates the closed loop of *diagnosis → recovery decision → counterfactual replay → outcome evaluation*. Reported numbers describe only the fixed task set, rule-based policies, and fault-injection setup used here. They are **not** LLM benchmark results, and imply no statistical significance or cross-environment generalization.

**Method.** RACER links four stages into a closed loop:

```text
execution → failure trajectory → root-cause candidates + confidence → recovery candidates
         → isolated counterfactual replay → success / side-effect / cost verification → recover or abstain
```

When diagnostic confidence falls below threshold, or no verifiable patch exists, the policy **explicitly abstains**. Ground-truth fault configuration is isolated from the agent: public trajectories and the evaluator's private manifest are separated, and state hashing supports replay-consistency checks.

**Frozen results** (`reports/local-flight-results.json`):

| Item | Value |
| --- | --- |
| Fault classes × seeds | 5 × 3 |
| Unique task units | 15 |
| Baselines | raw / recovery / explicit-patch oracle — 45 baseline records |
| Recovery baseline | 3 of 12 original failures recovered (25.00%) |
| Recorded harmful repairs | 0 |

**Repository layout.** `services/` holds six independently built services (`task_env`, `agent_runner`, `diagnoser`, `recovery_policy`, `counterfactual`, `evaluator`); `adapters/` holds external-benchmark adapters; `experiments/`, `scripts/`, `tests/`, `reports/`, and `output/` hold specs, tooling, offline regression, frozen results, and run artifacts.

**Getting started.**

```bash
docker compose up --build                          # core services
docker compose --profile analysis up evaluator      # evaluator
python3 -m pytest tests/                            # 163 offline tests, requires pytest
```

**Reproducibility.** Artifacts must pass fail-closed audit gates (G0–G8) before entering any results table, covering model-secret isolation, version pinning, split/paired identity, canonical envelope contracts, dedup proofs, strict replay receipts, and registry registration. See `scripts/audit_v2_artifacts.py` and `scripts/benchmark_preflight.py`.

**τ² airline adapter (stage A, negative result).** The native τ² airline environment does **not** provide the entity-level idempotent refund ledger required by RACER G4: repeated cancel inflates ledger entries exponentially (1→2→4→8), there is no unique refund id / idempotency key / witness field, returned receipts are mutated in place, user balance is never settled, and no reconciliation tool is exposed. Refund/cancel counterfactual branches must therefore be marked `counterfactual_supported=false` unless an external witness layer is introduced.

**Paper.** `recover-or-abstain-paper.md` (also `.html` / `.docx`).

**License.** MIT — see `LICENSE`.
