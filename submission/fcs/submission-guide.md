# FCS 投稿指南（RACER 论文 · 投稿版）

**目标期刊：** Frontiers of Computer Science（FCS，《计算机科学前沿》）
**主办/发行：** 高等教育出版社 + 北京航空航天大学 主办；Springer 发行
**投稿系统：** http://mc.manuscriptcentral.com/hepfcs
**投稿正文：** `submission/fcs/recover-or-abstain-fcs.md`
**要求依据：** FCS *Instructions for Authors*（2025 版 PDF）+ 官方 Overleaf 模板 "FCS LaTeX Template 2026"

---

## 1. 文章类型选择

选 **RESEARCH ARTICLES**（原创研究）。其余类型均不适用：

| 类型 | 限制 | 是否适用 |
|---|---|---|
| Research Article | 无正式篇幅上限 | ✅ **本文投这个** |
| Letter | ≤3 印刷页、**无摘要**、参考文献 ≤10 | ❌ 篇幅与文献数都不够 |
| Review Article | 需为领域综述 | ❌ |
| Perspective / Viewpoint / Comment / News | 观点短文 | ❌ |

> ⚠️ **避坑**：有作者反馈 FCS 会要求长文"改成 Letter（缩至 3 页）"，实质等同拒稿。投稿信（cover letter）中应主动强调本文是**完整实证研究**（800 episodes / 11,200 records / 双模型），并说明为何需要完整篇幅。

---

## 2. 必备组件合规核对

FCS 要求的完整常规稿件组件，逐项对照投稿版：

| FCS 要求 | 投稿版状态 | 位置 |
|---|---|---|
| Title | ✅ 已英译 | 首行 |
| Author(s) | ⚠️ **占位符，需填** | `[Given-name Family-name]` |
| Author affiliation(s) | ⚠️ **占位符，需填**（含邮编） | `[Department, …]` |
| Corresponding author e-mail | ⚠️ **占位符，需填** | `[xxx@xxx.edu.cn]` |
| Abstract | ✅ 已改为英文单段，**约 270 words（<300 上限）** | 标题页 |
| Keywords | ✅ 8 个（上限 8） | 标题页 |
| Nomenclature | ➖ 不需要（符号量少，随文解释） | — |
| Main text | ✅ §1–§8 | — |
| Acknowledgements | ⚠️ **占位符，需填基金号** | 文末 |
| Competing interests | ✅ 已声明无利益冲突 | 文末 |
| References | ✅ 25 条，顺序编码制，期刊名全称 | 文末 |
| Appendices | ✅ Appendix A（协议版本）、Appendix B（历史轨道） | 文末 |
| Figure captions | ✅ 已给 Fig. 1/2 的说明与绘制建议（**图待绘制**） | 文末 |
| Tables | ✅ Table 1–3（**须转三线表**） | §6 |

---

## 3. 提交前必须完成的事项（待办）

### 3.1 硬性缺失（不补无法投稿）

1. **作者与单位**：姓名（Given-name Family-name 格式）、单位（精确到院系）、邮编、国籍/城市、通讯作者邮箱。
2. **基金信息**：Acknowledgements 中的基金名称与编号（若无基金则整句删除）。
3. **英文全文润色**：投稿版为初译，建议经母语级润色（FCS 明确要求"较好的英语表达水平"）。
4. **表格转三线表**：Table 1–3 在 Word/LaTeX 中改为**仅三条横线**（表题下、列头下、表体下），**不使用竖线**。
5. **参考文献核对**：正文已标注需作者核实 [8]–[25] 的卷期页/DOI；投稿前**逐条核实**，并删除文末给作者的 note。

### 3.2 建议补充（提升命中率）

6. **补图**：本文目前无图。建议按 §"Figure captions" 的说明补 Fig. 1（RACER 闭环框架图）与 Fig. 2（分场景分离条形图）。FCS 明确要求"有图、有表、有公式"，且图能显著提升可读性与审稿印象。
   - 格式：TIFF / EPS / JPEG；彩色 ≥300 dpi、黑白 ≥500 dpi、线条图 ≥1000 dpi；单文件 ≤20 MB；线宽 0.25–1.5 pt。
7. **参考文献增至 25–35 条**：当前恰为 25 条（FCS 惯例要求 ≥25、近 5 年过半）。若审稿人要求补充，可再加 agent 可靠性/审计方向的近期工作。

### 3.3 若走 LaTeX 路线

官方模板：Overleaf 搜索 **"FCS LaTeX Template 2026"**（`\documentclass[review]{fcs}`）。
需要将 Markdown 正文转为该模板；模板已内置 `\author[1,*]{}`、`\address[1]{}`、`\corremail{}`、`\fcssetup{}`、`\begin{abstract}`、`\keywords{}` 等结构，与本投稿版的字段一一对应。

---

## 4. 投稿流程

1. 在 http://mc.manuscriptcentral.com/hepfcs 注册账号（**全部作者的联系方式与单位都需在系统中填写**，仅当所有作者确认后稿件才会送审）。
2. 首次投稿：**上传 PDF**（单文件，含正文+图表）。
3. 编辑部与主编初筛（不符合领域/质量者直接拒稿）。
4. 送审后通常邀请 **3 位审稿人**。
5. 录用后：按要求提交**全部原始源文件**（Word/LaTeX + 图片源文件），并签署版权声明。
6. **版权/出版模式选择**：FCS 为 hybrid 期刊，录用后需选择
   - **Traditional（订阅制）：无需版面费** ← **选这个**（符合 ≤5000 元预算）
   - Open Access：APC 为 £2390 / $3350 / €2740（约 2.4 万元，**超预算**）
   > 注：OA 的 APC 按接受日期定价；选订阅制不影响 SCI/EI/Scopus 收录与检索。

---

## 5. 其他注意事项

- **查重**：建议控制在 10% 以内；勿一稿多投、勿投已发表会议的扩展版（FCS 一般**不接受**已发表会议论文的扩展版本）。
- **补充材料**：FCS 支持随刊发布不限长度的补充文件（如完整证明、详细实验数据）。本文的 **11,200 条记录 envelope、审计 JSON、统计输出、协议全文**非常适合作为 supplementary files 提交——既满足复现性主张，又不必挤压正文篇幅。
- **数据可用性**：正文已含 Data availability 段，列出了产物；建议同时把产物仓库地址（GitHub: wangtongsen/recover-or-abstain）写入该段或补充材料。
- **预印本**：FCS 未禁止预印本，可先发 arXiv 建立时间戳（审稿人普遍接受）。

---

## 6. 结构改写说明（相对中文原稿的调整）

投稿版不是直译，做了以下结构化调整，原因如下：

| 调整 | 原稿 | 投稿版 | 原因 |
|---|---|---|---|
| 协议演进史 | §5 首段逐版详述 v0.1→v0.5 | 压缩为一段 + **Appendix A 表格** | 期刊读者不需要内部版本迭代细节，但预注册纪律是卖点需保留 |
| 历史轨道数据 | §6.1a（25-episode 表）、§6.2c（2-cell E3 表） | 压缩为 **Appendix B 一段** | 避免"内部审计痕迹"稀释主结果；当前矩阵才是数字基座 |
| 摘要 | 约 800 中文字，含大量括号细节 | **英文单段 ~270 words** | FCS 硬性 ≤300 words 且须可独立阅读 |
| 写作缺陷披露 | 散落各处 | 集中到 §7 (iii) | 期刊重视 Threats to Validity 的系统性 |
| 新增章节 | — | **§2 增 "LLM agents and their reliability"** | 期刊读者需要 LLM agent 领域的定位，原稿相关工作偏诊断线 |
| 引用编号 | 7 条 | 25 条，顺序编码、期刊名全称 | FCS 明确要求顺序编码制 + 期刊名全称 + 惯例 ≥25 条 |

---

## 7. 语言与术语对照（保证全文一致）

| 中文 | 英文（投稿版统一用） |
|---|---|
| 重放证实的恢复 | replay-verified recovery |
| 重放否决 | replay veto |
| 配对身份 | paired identity |
| 弃权 | abstention (abstain) |
| 有害修复 | harmful repair |
| 准入审计 | admission audit（G1–G7 / G0, G8） |
| 故障日程 | fault schedule |
| 隔离反事实重放 | isolated counterfactual replay |
| 预注册 | pre-registration |
| 危害谓词 | harm predicate |
| 失败分母 | failure denominator |
| 自愈 | self-healing |
| 误导证据模式 | misleading-evidence mode |
| 触发故障 | trigger fault |
| 可证实恢复 | verified recovery |
| 门槛（硬/软） | hard gate / soft flag |
