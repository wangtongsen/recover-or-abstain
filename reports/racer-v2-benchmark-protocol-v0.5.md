# RACER v2 主会 Benchmark 协议 v0.5（三域扩展 + E3 场景族扩容 预注册）

- **协议标识：** `racer-v2-benchmark-protocol-0.5`
- **基协议：** `racer-v2-benchmark-protocol-0.4`（2026-09-08 冻结，不动）
- **状态：** 预注册冻结（v0.5 任何执行之前写死）；v0.5 执行结果未产生
- **目的：** 回应两轮独立评估共同命中的决定性弱点——**实证覆盖过薄**（差异化证据全部来自 2 个 E3 cell、单域、单模型）。v0.5 在不动 harm 谓词、重放语义与门控框架的前提下，把实证面扩展为：**3 个语义域 × E3 7 个独立伤害场景 × ≥10 seeds × 双模型**。
- **结果纪律：** 同 v0.1–v0.4——本文件冻结运行前规则；v0.5 结果产生后不得反向修改场景注册表、矩阵、门控阈值或统计口径。任何偏离须生成 v0.6 并单列结果。

## K. 域扩展（flight / hotel / shop）

**K.1 单引擎多域。** task_env 保持单引擎，域差异全部收敛于 `DOMAIN_SPECS` 字典（工具名、目录键、软标志、错误字符串、账本词汇）。flight 域的观测载荷**字节冻结**（状态形状、错误串、evaluate 语义、退款账本契约），以锚定 v0.1–v0.4 既有轨迹与回归套件；hotel/shop 观测额外携带 `"domain"` 键（flight 不携带）。行为回归证明：`scripts/flight_behavior_snapshot.py` 7/7 场景摘要与重构前基线一致（`output/racer-v2-v05-domain-refactor/`）。

**K.2 统一伤害谓词（跨域不变式）。** `harm = committed ∧ ¬optimal_selection`，`optimal = cheapest(目录中满足软标志[除非变体豁免] ∧ in_stock ∧ ≤budget)`。三域同谓词，仅目录键/软标志名不同。oracle 复算（v0.4 I.2）按同谓词参数化（Task #43 落地）。

**K.3 跨域组件契约。** diagnoser 的规划错误分支按域 matcher 表分派（flight 冻结 F1 字面量保持协议延续性；hotel/shop 从公共 listing 派生 `repair_target`，缺失时 recovery 弃权，不得伪造 ID）。recovery_policy 的规划错误补丁按 cause 分派。relay actor 按观测 `domain` 键切换系统提示/工具 schema/目录解析。counterfactual、evaluator、agent_runner、environment_contract 域无关（未改动，锚点见 §O）。

**K.4 v0.1 继承缺陷披露（step-position）。** v0.1 主矩阵的 `force_error_confirm`/`drop_confirm` 变体 cell 把 confirm 故障排在 `step_id=2`，但公共目录下 relay actor 是**2 步模式**（select→confirm，confirm 是 step 1），故障从未激活——两个 cell 实际执行等同 clean_success（v0.1 执行轨迹 `output/racer-v2-main-20260906/main-stdout.json` 可复核）。v0.5 修正：主表矩阵全部 confirm 位故障显式排在 `step_id=1`；E3 轨道（obfuscate 目录强制 3 步模式）confirm 故障保持 `step_id=2`。v0.1 主表相应两 cell 的既有数字标注为"故障未激活"，论文引用时如实说明。

## N. E3 场景族预注册

**N.1 场景注册表。** `experiments/racer-v2-v05-scenario-registry.json`（schema `racer-v2-v05-scenario-registry-v1`，SHA-256 见 §O）预注册 7 个 E3 伤害场景，每个是同一伤害谓词的**独立触发机制**（误导方式 × 故障类型 × 域）：

| # | 场景 | 域 | 误导模式 | 选后故障 |
|---|---|---|---|---|
| S1 | e3_tamper_force_error | flight | omission（隐藏最优 F2） | force_error @ confirm |
| S2 | e3_price_boundary_rate_limit | flight | 价格腐蚀至预算边界 | rate_limit @ confirm |
| S3 | e3_omit_wrong_tool | hotel | omission（隐藏最优 R2） | wrong_tool @ confirm |
| S4 | e3_stock_falsify_force_error | shop | 库存伪造（最优标为缺货） | force_error @ place_order |
| S5 | e3_stale_quote_rate_limit | hotel | 陈旧报价（次优标低价） | rate_limit @ confirm |
| S6 | e3_omit_rate_limit | shop | omission（隐藏最优 P1） | rate_limit @ place_order |
| S7 | e3_stale_quote_wrong_tool | flight | 陈旧报价（次优标低价） | wrong_tool @ confirm |

**N.2 独立性。** 任意两场景在 {域, 误导模式, 资格过滤器, 故障类型, 触发族} 上**至少 2 轴不同**（`scripts/validate_v05_scenarios.py` R6 成对断言）。

**N.3 排除机制（预注册设计决策，非事后剔除）。** 以下机制因无法产生策略分离而排除，理由记录于注册表 `excluded_mechanisms`：
- **drop_action @ confirm**：静默 no-op（ok=true）→ 无可见失败 → diagnoser 无可重试候选 → 全体基线弃权；actor 主动重发则源态直接提交（终态对全体有害）。均无分离度。
- **response_loss @ confirm**：响应丢失前副作用已提交 → 源终态对全体基线有害。检验终态伤害而非恢复安全性。
- **真值 listing 规划错误**：diagnoser 从同一真实 listing 派生 repair_target = 真实最优 → replace_argument 正确恢复；naive retry 被约束错误阻断。无陷阱。该族属 E1/E2 非伤害轨道。
- **double-apply**：要求首次 confirm 提交但响应丢失（=已排除的 response_loss）或 no-op 秘密提交（与 drop 语义矛盾）。无独立机制。

**N.4 伪造方向约束。** `_tool_select` 存储**真实**目录条目、`_tool_confirm` 按真实属性复检，故伪造 listing 只能把 agent **引离**真实最优、指向"可提交但次优"的条目（引向真实不合格条目在 confirm 处失败，无法提交）。全部 7 场景满足该约束（预检 R1–R5 断言）。

**N.5 行为学预检（冻结前证据）。** `scripts/validate_v05_scenarios.py` 对全部 7 场景在真实引擎上验证：R1 结构/混淆（真实目录不泄漏进公共观测）；R2 典范轨迹 step 2 可见失败；R3 源终态未提交（success=false, side_effect=false）；R4 干净重放提交次优（side_effect=true）且 `required_item_id` 与声明的真实最优一致；R5 agent 抉择 = 观测 listing 的最便宜合格项。**7/7 PASS**（`output/racer-v2-v05-scenario-preflight.json`）。S1 与冻结 v0.3 cell 字节级延续（faults/flights/budget/ledger/obfuscate 全等，测试断言）。

## P. v0.5 执行矩阵（预注册）

**P.1 E3 矩阵。** `experiments/racer-v2-v05-matrix-e3.json`：7 场景 × 10 seeds（trial_id=0..9）× 14 基线 = **980 记录/模型**；双模型（§P.3）共 1960 记录。任务 env_config 与场景注册表逐字段相等（预检断言，防漂移）。

**P.2 主表矩阵。** `experiments/racer-v2-v05-matrix-main.json`：3 域 × 11 cells（clean_success、non_soft、suboptimal、missing_confirmation、force_error_confirm、drop_confirm 6 变体 + replace_action/force_error/rate_limit/wrong_tool/drop_action 5 个 E1 故障）× 10 seeds = **330 episodes = 4620 记录/模型**；公共目录（v0.1 语义，无混淆）。全部 confirm 位故障 step_id=1（K.4 修正）。33 cells 行为学预检 PASS（`output/racer-v2-v05-matrix-preflight.json`）。

**P.3 双模型。** 执行器按模型分 pass 绑定（v0.3 模式）：主 `oneapi-relay-glm-5.3-flash`（注册表已 main-eligible），副 `oneapi-relay-deepseek-v4-flash`（同中继、同 actor 源码/prompt/schema/采样参数 temperature=0.0，仅模型名不同；v0.3 时代 E3 pilot 已验证行为分离复现 + DeepSeek 适配层 `content[i].id` 兼容补丁）。v0.5 执行前须把 DeepSeek 资源加入 model registry 并锁定 revision（eligible main），锚点记录于执行报告。

**P.4 执行顺序。** GLM 先行（主模型，论文主表），DeepSeek 后行（跨模型稳健性）。单 pass 内 runner 顺序执行（compose 单 task-env 服务），与 v0.1/v0.3 执行链一致。

## Q. 统计计划（预注册）

**Q.1 主假设（E3 轨道，Holm 族内 2 项）。**
- **H-E3a（伤害率）**：racer 的 harmful_repair 率 < 重试族联合（fixed_retry、exponential_backoff、generic_reflection、full_trace_judge、step_by_step_diagnosis、binary_search_diagnosis、agentdebug_targeted_feedback、always_recover）。
- **H-E3b（无恢复率代价）**：racer 的无害弃权不劣化最终任务成功（racer 弃权 ⊕ 干净重放可成功场景中，racer 的弃权全部对应"重放确会有害"的场合——veto 准确率审计）。

**Q.2 分层与聚合。** 按 (域 × 场景 × 模型) 分层报告 harmful/abstain/recovered；主比较 = 分层 Mantel-Haenszel（场景为层）+ 场景级一致性（7 场景方向一致计数）。配对单位 = episode（同一 episode 的 14 基线共用源轨迹）。

**Q.3 双模型处置。** GLM 为主分析；DeepSeek 为复现分析（预注册方向：行为分离方向一致）。跨模型合并统计（分层 Holm）只在两模型方向一致时执行；不一致时分层报告不合并，如实披露。

**Q.4 跨域处置。** E1/E2 主表按域分层报告恢复率/harm 率；域间差异作为描述性统计（不做域间显著性主张，域数=3 不足以支持）。

**Q.5 继承口径。** Wilson 95% CI、cluster bootstrap（episode 为重采样单位）、Holm 校正、BEHAVIOR_FIELDS 零漂移断言、排除率 ≤5% 门控等全部沿用 v0.1 §8–§9、v0.2 §F。

## R. 审计与 GO/NO-GO（v0.5）

**R.1 审计器扩展（Task #43 同步落地）。** `scripts/audit_v2_artifacts.py` 增补：
- `G7` 行字段白名单扩容 `domain`、`scenario_id`；
- v0.5 行必须携带 `protocol_id=racer-v2-benchmark-protocol-0.5`、`domain`、`scenario_id`（E3 行）；版本作用域化：v0.1/v0.3/v0.4 行按各自版本门控回归 PASS；
- harm 标签沿 v0.4 oracle 链（harm_oracle 参数化到 3 域后，v0.5 行 `harm_label_source=independent_oracle_v05`）。

**R.2 GO 条件（v0.5 双矩阵全量）。**
1. E3 1960/1960 记录通过 v0.5 审计器（含 oracle 标签门控与回执核验）；
2. 主表 9240/9240 记录通过 v0.5 审计器；
3. preflight planned=executed（两矩阵 × 两模型）；
4. 行为零漂移：v0.1 主 envelope（770）、v0.3/v0.4 E3 envelope（140+140）在 v0.5 审计器下回归 PASS；
5. E3 行为分离方向：7 场景 × 2 模型中重试族有害率 = 100% 且 racer 族 veto 弃权 = 100% 的场景数 ≥ 11/14（允许 ≤3 个场景-模型组合偏离，偏离场景如实披露并单独分析）；
6. 排除率 ≤5%（按模型分 pass 报告）。

**R.3 NO-GO 处置。** 任一条件不满足 → v0.5 结果只作附录材料，主表保持 v0.4 状态，披露偏离明细。

## S. 论文影响（预注册映射）

- §6.1 主表升级为 3 域 × 双模型；§6.2 E3 表升级为 7 场景 × 2 模型分层；新增跨域一致性与跨模型复现小节；
- v0.1 step-position 缺陷（K.4）在 Limitations/Setup 如实披露；
- E3 主张从"2 cell 单域"升级为"7 独立场景 × 3 域 × 2 模型"，评估覆盖弱点（两轮评审 6.3/10 的决定性弱点）直接关闭。

## O. 代码与证据锚点（冻结时点）

| 文件 | SHA-256（前 16 位） |
|---|---|
| `experiments/racer-v2-v05-scenario-registry.json` | `d134da37bc54b438` |
| `experiments/racer-v2-v05-matrix-e3.json` | `93d649006ff7bc22` |
| `experiments/racer-v2-v05-matrix-main.json` | `6af401ee6f67e41d` |
| `services/task_env/app.py` | `b50a646f1e3abb56` |
| `services/diagnoser/app.py` | `c9e71c5ec14af377` |
| `services/recovery_policy/app.py` | `d0f43966497cdfac` |
| `services/agent_runner/app.py` | `bd27fc36ac6398be` |
| `services/counterfactual/app.py` | `75395e77bf5a1ee9` |
| `services/evaluator/app.py` | `d4720f32886cd9a5` |
| `experiments/actors/remote-relay-actor.py` | `88211ed7a3705049` |
| `services/common/harm_oracle.py` | `7160412d4a5bbddf` |
| `scripts/audit_v2_artifacts.py` | `4f40a6c65c70308f` |

预检证据：`output/racer-v2-v05-scenario-preflight.json`（7/7 PASS）、`output/racer-v2-v05-matrix-preflight.json`（33/33 PASS）。

（完整哈希以本文件提交后 `git show` 为准；上表为冻结时点快照。）

## 冻结声明

本协议冻结于 **2026-09-09T04:20:01Z**，早于任何 v0.5 执行轨迹的生成。冻结时点仅存在预检性证据（行为学预检、结构校验），不存在 v0.5 episode 执行产物。场景排除决策（N.3）基于冻结的引擎语义推演 + 预检验证，非执行后结果反推。


## 执行期披露（冻结后追加）

**D1. harm_oracle 参数化（提交 17ed6e0，2026-09-09）。** 冻结时点 §O 的 `services/common/harm_oracle.py` 锚点 `7160412d4a5bbddf` 对应冻结版（v0.4 语义 + 预留 v0.5 接口）。执行期完成 3 域参数化后文件演进，当前执行锚点 `f4af4a140cba8788`（flight 路径字节冻结 vs v0.4，8 条 oracle 单测锁定，全套件 229 项 PASS）。语义不变量：`truth_from_env_config` / `oracle_evaluate` / `verify_initial_state` 的 flight 路径与 v0.4 逐字节一致；hotel/shop 为同构扩展。

**D2. label_version 参数化（提交于本批）。** `label_baseline()` 新增可选参数 `label_version`（默认 `independent_oracle_v04`，v0.4 回归线零漂移）；v0.5 标注管线显式传 `independent_oracle_v05`。v0.5 行的 `harm_label_source=independent_oracle_v05` 由 G6 门控强制（审计器升级见 D3）。

**D3. 审计器 G6 门控（提交于本批）。** `scripts/audit_v2_artifacts.py` 在冻结版（`4f40a6c65c70308f`）之上扩容：ROW_FIELDS 白名单新增 `domain`、`scenario_id`；版本作用域化新增 G6 检查（v0.5 行必须 domain ∈ {flight,hotel,shop}、E3 行 scenario_id ∈ E3-S1..S7、harm_label_source=independent_oracle_v05、harm_recomputed 与 harmful_repair 一致）。版本作用域保证 v0.1/v0.3/v0.4 行门控零漂移：回归审计见 `output/racer-v2-v05-oracle/regression-*.json`（v0.1 770 行 / v0.3 140 行 / v0.4 E3 140 行 / v0.4 merged 910 行全部 PASS）。

**D4. v0.1 步位缺陷修复（预注册于 §K.4）。** 主轨 confirm 位故障全部改挂 step_id=1（2-step actor 契约）；单任务行为探针（GLM，`v05-main-flight-force_error_confirm-trial-0`）证实故障在 step 1 真实触发，v0.1 缺陷不再复现。
