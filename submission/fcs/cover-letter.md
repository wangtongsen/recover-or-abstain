# Cover Letter — Frontiers of Computer Science

**To:** The Editor-in-Chief, *Frontiers of Computer Science*
**Date:** [DD Month YYYY]
**Manuscript type:** Research Article
**Title:** Recover or Abstain: Replay-Verified Recovery for Tool-Calling Agents
**Corresponding author:** Tongsen Wang, [Affiliation], wangtongsen@baidu.com

---

Dear Editor,

We submit for your consideration the manuscript entitled **"Recover or Abstain: Replay-Verified Recovery for Tool-Calling Agents"** as a **Research Article** in *Frontiers of Computer Science*.

**The problem we address.** Recovery in tool-calling agents has a trust gap that current evaluation practice does not close. When a system reports "the repair succeeded", a reviewer or deployer cannot distinguish three very different situations: the repair genuinely happened; it happened to be harmless but was never verified; or it silently introduced an irreversible side effect. Diagnosis-oriented work answers *where* the failure is, but the trustworthiness of the subsequent repair action is treated as an implementation detail. We argue that recovery must be an *auditable assertion* rather than an observed coincidence, and we make that claim operational.

**What the manuscript contributes.** (i) A strict semantics for replay-verified recovery plus a *replay veto* decision rule: when an isolated counterfactual replay predicts a side effect or a failure, the policy abstains and never commits the patch. (ii) A fail-closed admission auditor family (G1–G7 at record level, G0/G8 at evaluator level) that turns a recovery claim into a machine-checkable credential rather than a narrative. (iii) A pre-registered paired benchmark spanning three semantic domains, with a seven-scenario irreversible-side-effect track and two LLM actors, comprising 800 episodes and 11,200 records that all pass admission auditing with zero exclusions. (iv) A 2×2 ablation showing that replay verification is *behaviorally necessary*: without it, every strategy—including one given perfect root-cause diagnosis—commits harmful repairs at scale, whereas with it every strategy produces only harmless abstention. We report honest negatives as well, including a null result against the verification-preserving ablation and the self-healing of injected faults.

**Why we request a full Research Article rather than a Letter.** The central claim is a claim about *auditability*, so its evidence must itself be auditable; the argument runs from the formal definitions, through the admission gates, to the behavioral separation, and every link depends on material that cannot be compressed into three printed pages. Concretely, the paper must present the seven-scenario design and its pre-registered validity constraints, the stratified statistical plan and results under two models, the 2×2 ablation, the independent oracle that recomputes every harm label without reading replay output, the limitations and the disclosed infrastructure deviations, and two appendix tables recording the protocol revision chain and the superseded historical runs. Should the editors consider the manuscript longer than necessary, we are glad to move detail to the supplementary material, which FCS supports without length limitation—we have prepared the complete artifact set (all 11,200 records, the admission and regression audit reports, the statistical outputs, and the full protocol text) for release alongside the paper. We would, however, respectfully note that the core chain of reasoning (definitions → gates → separation evidence) is not reducible to a Letter-length article without collapsing the very auditability the work is about.

**Originality and exclusivity.** This manuscript is original, has not been published previously, and is not under consideration by any other journal or conference. It is **not** an extended version of a previously published conference paper. All authors have approved the submission and agree to its contents. The authors declare no competing interests. All experimental artifacts, protocols, and audit records are prepared for open release; credentials are injected only through runtime environment variables and appear neither in the repository nor in the artifacts.

**Suggested reviewers.** We suggest the following experts, none of whom has a conflict of interest with the authors: [Name, affiliation, e-mail], [Name, affiliation, e-mail]. We respectfully leave the final choice to the editors.

Thank you for considering our work. We look forward to your response.

Sincerely,

Tongsen Wang
[Affiliation]
wangtongsen@baidu.com

---

> **Author note (to be deleted before submission).**
> 1. Fill in the date, corresponding-author block, and suggested reviewers; delete this note.
> 2. The paragraph "Why we request a full Research Article rather than a Letter" is the part that pre-empts a request to cut the paper down to Letter length (three printed pages, no abstract, ≤10 references), which for this manuscript would amount to rejection. Keep it, but keep it polite—the offer of supplementary material is what makes it work.
> 3. The "not an extended version of a previously published conference paper" sentence is deliberate and important: FCS states it will not generally accept extended conference papers, and this manuscript is not one.
