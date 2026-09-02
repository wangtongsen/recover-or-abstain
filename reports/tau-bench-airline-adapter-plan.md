# τ-bench airline adapter 接入方案（设计报告）

> 本文件仅描述后续 adapter 方案，不代表已接入、已安装或已运行 τ-bench。当前 local-flight 论文实验独立交付；任何未运行的公开 benchmark 数字不得写入论文。

## 1. 当前状态与边界

当前仓库没有 τ-bench、τ²-bench/τ³-bench adapter，也没有外部 Python 依赖声明；现有实现是 deterministic local-flight 原型。Adapter 应作为独立客户端层，不修改现有 `task-env`、`agent-runner`、`diagnoser`、`recovery-policy`、`counterfactual` 或 `evaluator` 的默认行为。

推荐优先支持维护中的 τ³-bench 非语音 airline，暂不接 voice、banking knowledge、retail、telecom。公开仓库 `sierra-research/tau2-bench` 在 `v1.0.1` release（2026-07-22）中声明项目版本 `1.0.1`、Python `>=3.12,<3.14`、MIT 许可证；其发布说明明确指出 banking_knowledge 的评分修复影响可比性，而其他域不受该次修复影响。Airline 任务仍需以锁定的 release/tag 和本地校验结果为准，不使用移动 `main` 作为论文口径。

旧 `sierra-research/tau-bench` 仓库当前 README 明确警告 airline/retail 任务过时，并指向 `tau2-bench` 的 τ³-bench；因此不应默认使用旧仓库。若因复现实验必须使用旧版本，须另建版本标识，不与 τ³-bench 结果混报。

## 2. 推荐锁定清单

- 仓库：`sierra-research/tau2-bench`。
- 版本：`v1.0.1`；tag 对象 SHA-256 不适用，记录 Git commit SHA `fc0055dc4e0a316c3f83133267fbd6faaa770992`，并保存源码归档 SHA-256。
- 包：`tau2==1.0.1`，Python `>=3.12,<3.14`。
- 安装策略：单独 virtualenv/容器；不要把其依赖写入本仓库默认镜像。其基础依赖包含 `litellm>=1.80.15,<1.82.7`、`fastapi>=0.115.11`、`uvicorn>=0.34.0`、`pandas>=2.2.3`、`numpy>=1.24.0` 等；airline 仅按官方最小安装路径验证，knowledge/voice extra 不安装。
- 许可证：MIT；保留上游 LICENSE、版权声明和引用。任务数据、policy、数据库和历史轨迹视为上游发布内容，不能改写后冒充官方数据。
- 版本审计：记录 `git rev-parse HEAD`、`python --version`、`pip freeze`、任务 split、运行参数、模型及 provider 的精确版本；保存原始结果和日志。

## 3. 接口映射（待实现）

Adapter 对外提供与现有 runner 相同的窄接口：

```text
reset(task_index, task_split, seed) -> observation, opaque run_id
observe(run_id) -> state summary, tools, state_hash
step(run_id, tool, arguments) -> requested_action, result, observation, state hashes
evaluate(run_id) -> success/reward, side_effect metadata when available
```

映射原则：

1. τ³ airline 的 task 使用列表索引/官方任务字段，不把 `user_id`、`reservation_id` 当 task ID；adapter 生成稳定 `task_id = airline-{split}-{index}`。
2. 环境初始化通过官方 `MockAirlineDomainEnv`/公开环境工厂；工具调用保留官方工具名和参数，不将工具 schema 硬编码进 local-flight `task-env`。
3. 轨迹统一转换为当前 JSONL 字段：`task_id,run_id,seed,step_id,requested_action,result,observation,state_hash_before,state_hash_after`；无法从公开环境可靠取得的字段写 `null`，不得臆造 `fault_truth` 或 `side_effect`。
4. τ-bench 原生 reward 是任务完成判定；adapter 将 reward 作为 `original_evaluation.success = (reward >= 1-epsilon)`，同时保留原始 reward、终止原因和 `info`。
5. RACER 的 fault injection 不直接改写上游数据库。若做故障实验，使用隔离 wrapper/录制回放层，并将注入配置放在 evaluator-only oracle manifest；公开任务运行只作为无故障 baseline。
6. Counterfactual 必须新建独立环境实例，以 task index、初始数据快照和版本信息重放；若无法保证 prefix/patch/suffix 的状态等价，标记 `counterfactual_supported=false`，不报告恢复成功。

## 4. 分阶段实施与验收

**阶段 A：不影响 local-flight。** 仅做独立目录/虚拟环境的 import smoke test；确认 airline 环境构造、一个 task 的工具 schema、单步调用和原生 reward。失败只记录为 adapter blocker，不改变 local-flight Compose 或论文结果。

**阶段 B：离线轨迹转换。** 使用上游 historical trajectory 或已授权的本地结果，验证字段映射、state hash、任务索引和原生 reward 一致性；不得把历史轨迹当新实验数字。

**阶段 C：小规模 live smoke。** 只运行 1 个明确 task、单并发、固定 split 和固定模型/用户模拟器版本；检查终止分布、工具调用、重置隔离、结果文件原子写入。任何 API key、第三方服务或网络要求均作为外部前置条件，不写入默认配置。

**阶段 D：RACER 接入。** 将 adapter 作为 `TASK_ENV_URL` 兼容层，复用 runner 的 `baselines`、oracle 旁车和 evaluator schema；先只读诊断，再启用 patch/counterfactual。通过最小验收后才允许进入正式 benchmark 实验：同一 task 多 trial 可重放、公共轨迹无 oracle 泄漏、原生 reward 与转换后 success 一致、失败/超时/infrastructure_error 可区分。

## 5. 论文与数据使用纪律

当前论文只报告已运行的 local-flight 结果。τ-bench adapter 在未完成 A–D、未锁版本、未实际运行并审计结果前，不得出现任何 pass^k、成功率或模型比较数字。后续公开结果必须单列 benchmark、版本、task split、模型/provider、用户模拟器、trial 数、超时/重试规则和有效样本排除规则，不能与 local-flight 汇总。

建议结果文件：`raw/airline-v1.0.1/<run_id>.json`（原始轨迹）、`oracle/airline-v1.0.1/<run_id>.json`（仅授权真值/注入配置）、`derived/airline-v1.0.1.jsonl`（一行一个 run×baseline）、`summary/airline-v1.0.1.json`（统计、CI、版本和环境指纹）。所有文件包含 `schema_version`、`adapter_version`、`benchmark_commit`、`task_split`、`task_index`、`run_id`、`seed` 和 `generated_at`。
