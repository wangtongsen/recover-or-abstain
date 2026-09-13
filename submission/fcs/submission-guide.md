# FCS 投稿指南（RACER 论文 · 投稿版）

**目标期刊：** Frontiers of Computer Science（FCS，《计算机科学前沿》）
**主办/发行：** 高等教育出版社 + 北京航空航天大学 主办；Springer 发行
**投稿系统：** http://mc.manuscriptcentral.com/hepfcs
**要求依据：** FCS *Instructions for Authors*（2025 版 PDF）+ 官方 Overleaf 模板 "FCS LaTeX Template 2026"

## 0. 投稿包清单

| 文件 | 状态 | 说明 |
|---|---|---|
| `cover-letter.md` | ✅ 待填作者信息 | 含"为何需要完整篇幅"段，用于规避被要求改成 Letter（3 页，等同拒稿） |
| `recover-or-abstain-fcs.md` | ✅ | Markdown 投稿正文（英文），9,012 words |
| `recover-or-abstain-fcs.tex` | ✅ 未编译 | 官方 `fcs` 模板版，booktabs 三线表 + 图浮动体 + 25 条参考文献（引用键已校验） |
| `figures/fig1-racer-loop.{eps,pdf,tiff,png}` | ✅ | 闭环框架图，4 种格式 |
| `figures/fig2-scenario-separation.{eps,pdf,tiff,png}` | ✅ | 七场景×双模型分离图，4 种格式 |
| `figures/make_figures.py` | ✅ | 图的可复现生成脚本 |
| `md2fcs_tex.py` | ✅ | Markdown → LaTeX 转换脚本（改 md 后重跑） |

**仍缺作者提供：** 作者姓名与上标标记、单位（精确到院系+邮编）、通讯作者邮箱、基金名称与编号。

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
| Figure captions | ✅ Fig. 1/2 已**实际绘制**（矢量 PDF + 600 dpi PNG），captions 已按图定稿 | 文末 + `figures/` |
| Tables | ✅ Table 1–3（**须转三线表**） | §6 |

---

## 3. 提交前必须完成的事项（待办）

### 3.1 硬性缺失（不补无法投稿）

1. **作者与单位**：姓名（Given-name Family-name 格式）、单位（精确到院系）、邮编、国籍/城市、通讯作者邮箱。
2. **基金信息**：Acknowledgements 中的基金名称与编号（若无基金则整句删除）。
3. **英文全文润色**：投稿版为初译，建议经母语级润色（FCS 明确要求"较好的英语表达水平"）。
4. **表格转三线表**：Table 1–3 在 Word/LaTeX 中改为**仅三条横线**（表题下、列头下、表体下），**不使用竖线**。
5. **参考文献核对**：已完成——4 条含卷期/页码的条目于 2026-09-13 逐条对官方记录核实通过（见下表）；其余为预印本/会议论文（"venue + year + arXiv 编号"形式，本无卷期页），需用 DBLP/Scholar 确认编号与标题对应后删除文末 Author note。

### 3.1a 参考文献核验状态（2026-09-13）

| 条目 | 内容 | 核验结果 |
|---|---|---|
| [2] Who&When | ICML 2025, PMLR 267: 76583–76599 | ✅ 已对 PMLR 官方页面核实（作者 Zhang S, Yin M, Zhang J, et al. 正确） |
| [7] AgentDojo | NeurIPS 37, 2024: 82895–82920 | ✅ 已核实，补 DOI 10.52202/079017-2636 |
| [9] Preregistration revolution | PNAS, 2018, 115(11): 2600–2606 | ✅ 已对 PNAS 核实，补 DOI 10.1073/pnas.1708274114 |
| [19] LLM autonomous agents survey | FCS, 2024, 18(6): 186345 | ✅ 已对高教社 FCS 官网核实，补 DOI 10.1007/s11704-024-40231-1（**目标期刊自引**） |
| [1][3][4][5][6] 及 [8][10]–[18][20]–[25] | arXiv 预印本 / 顶会论文 | ⚠️ 无卷期页（arXiv 编号为唯一标识）；**建议用 DBLP 一次性确认编号与标题** |

> 说明：FCS 采用顺序编码制，会议/预印本条目按"会议名 + 年份 + arXiv 编号"给出即符合惯例；仅期刊论文才需要卷期页，上表前 4 条即为全部此类条目。

### 3.2 建议补充（提升命中率）

6. **补图 —— 已完成**：`figures/fig1-racer-loop.pdf`（RACER 闭环框架图：诊断 → 门控 → 隔离重放 → 否决/准入，底部为 G1–G8 审计带）与 `figures/fig2-scenario-separation.pdf`（七场景 × 双模型的结果分离点图，重试族/无验证消融/RACER 三点对比）。两图均已用英文标注、无嵌入 caption（caption 按 FCS 要求在正文单独给出）。
   - **提交格式**：FCS 要求 TIFF/EPS/JPEG，彩色 ≥300 dpi。当前提供矢量 PDF（可无损转 EPS）与 600 dpi PNG。若上传系统不接受 PDF，用 `epstopdf`/Illustrator/Inkscape 转 EPS，或导出 600 dpi TIFF。
   - Fig. 2 采用点图而非条形图的原因：RACER 的比率为 0，条形图长度为零会导致该系列**不可见**，读者无法区分"0"与"缺数据"；点图在 0 处仍清晰可辨。
7. **参考文献增至 25–35 条**：当前恰为 25 条（FCS 惯例要求 ≥25、近 5 年过半）。若审稿人要求补充，可再加 agent 可靠性/审计方向的近期工作。

### 3.3 LaTeX 路线（已生成，推荐）

**产物：** `recover-or-abstain-fcs.tex` —— 已套用官方 `fcs` 文档类结构，正文/表格/图/参考文献全部就绪。

**已包含的 LaTeX 化处理：**
- `\documentclass[review]{fcs}` + `\title` / `\author[1,*]` / `\address[1]` / `\corremail` / `\fcssetup` / `abstract` / `\keywords`
- **Table 1–4 全部转为 booktabs 三线表**（`\toprule`/`\midrule`/`\bottomrule`，无竖线），列数一致性已校验
- **Fig. 1/2 以 `figure` 浮动体插入**（`\includegraphics` 指向 `figures/*.eps`），caption 内嵌，无需再单独提供 caption 列表
- 参考文献 25 条转为 `thebibliography` + `\bibitem{refN}`；正文引用为 `\cite{refN}`，**已校验 25/25 全部匹配、无未定义键、无未引用项**（范围引用 `[15–18]` 已自动展开为 `ref15,ref16,ref17,ref18`）
- 章节编号交由 LaTeX 自动生成（已剥离 Markdown 里手写的 "4 …" "6.2 …" 编号，避免双重编号）
- 附录 A/B 用 `\section*`（不编号）

**编译方法（二选一）：**
1. **Overleaf（最省事）**：新建项目 → 上传 `recover-or-abstain-fcs.tex` 与 `figures/` 整个目录 → 把 Overleaf 上的 **"FCS LaTeX Template 2026"** 模板里的 `fcs.cls` 一并加入项目 → 编译。
2. **本地**：取得 `fcs.cls`（Overleaf 模板或期刊官网）后
   ```bash
   pdflatex recover-or-abstain-fcs      # 模板头为 % !TeX program = pdflatex
   pdflatex recover-or-abstain-fcs      # 第二遍生成引用与交叉引用
   ```
   > 本机没有 TeX 发行版，也无 `fcs.cls`，因此**该 .tex 尚未实际编译过**；若报错请先把日志发我。

**可复现性：** `.tex` 由 `md2fcs_tex.py` 从 Markdown 生成——**请改 Markdown 后重跑脚本**，不要直接编辑 .tex：
```bash
/Users/infoflow/.workbuddy/binaries/python/envs/default/bin/python submission/fcs/md2fcs_tex.py
```
脚本内置两项断言（未恢复占位符 / NUL 字节残留即报错），并在转换时先转义纯文本、后插入 `\cite`/`\textbf` 等标记（顺序颠倒会把标记本身转义成乱码——该缺陷已在开发中修复）。

### 3.4 图片格式（已全部导出）

`figures/` 下每张图均有 4 种格式，按上传系统要求任选：

| 格式 | 文件 | 用途 |
|---|---|---|
| **EPS** | `*.eps` | 期刊首选（矢量），图内文字可缩放无损 |
| PDF | `*.pdf` | 预览 / LaTeX 编译（`.tex` 已指向 .eps，如需改 PDF 请替换 `\includegraphics` 后缀） |
| TIFF | `*.tiff` | 600 dpi、**LZW 压缩**（未压缩时单文件达 40–62 MB，超期刊 20 MB 上限；压缩后约 1 MB） |
| PNG | `*.png` | 600 dpi 位图，本地预览用 |

重新生成全部格式：
```bash
/Users/infoflow/.workbuddy/binaries/python/envs/default/bin/python submission/fcs/figures/make_figures.py
```


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
