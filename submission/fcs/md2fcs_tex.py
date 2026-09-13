#!/usr/bin/env python3
"""Convert the FCS submission manuscript (Markdown) to the journal's official LaTeX template.

Usage:
  /Users/infoflow/.workbuddy/binaries/python/envs/default/bin/python \
      submission/fcs/md2fcs_tex.py

Input : submission/fcs/recover-or-abstain-fcs.md
Output: submission/fcs/recover-or-abstain-fcs.tex

Why a script rather than hand-conversion: the manuscript is ~9k words with three
tables, inline math, and 25 sequentially numbered references. A repeatable
converter keeps the .tex in sync if the Markdown is edited, and the escaping
rules (underscores in identifiers such as in_stock, percent signs in rates,
en dashes, arrows, §) are easy to get wrong by hand.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / 'recover-or-abstain-fcs.md'
DST = HERE / 'recover-or-abstain-fcs.tex'

# Unicode -> LaTeX. Order matters: longer/dash forms first.
UNICODE_MAP = [
    ('\u2014', '---'), ('\u2013', '--'), ('\u2212', '$-$'),
    ('\u201c', '``'), ('\u201d', "''"), ('\u2018', '`'), ('\u2019', "'"),
    ('\u00b7', '$\\cdot$'), ('\u2248', '$\\approx$'),
    ('\u2264', '$\\le$'), ('\u2265', '$\\ge$'), ('\u00d7', '$\\times$'),
    ('\u207b', '$^{-}$'), ('\u00b2', '$^{2}$'), ('\u03c4', '$\\tau$'),
    ('\u2026', '\\ldots{}'), ('\u00a7', '\\S'), ('\u2192', '$\\to$'),
    ('\u2713', '\\checkmark{}'), ('\u2717', '$\\times$'),
]

CITE_RE = re.compile(r'\[(\d+(?:\s*[,\u2013-]\s*\d+)*)\]')


def extract(md: str):
    """Split the manuscript into the template's required components."""
    abstract = re.search(r'\*\*Abstract\*\*\s*(.+?)\s*\*\*Keywords\*\*\s*(.+)', md, re.S)
    title = re.search(r'^#\s+(.+)$', md, re.M).group(1)
    body_start = md.index('## 1 Introduction')
    refs_at = md.index('## References')
    appendix_at = md.index('## Appendix A')
    return {
        'title': title.strip(),
        'abstract': abstract.group(1).strip(),
        'keywords': abstract.group(2).strip(),
        'body': md[body_start:refs_at].rstrip(),
        'refs': md[refs_at:appendix_at].rstrip(),
        'tail': md[appendix_at:].rstrip(),
    }


PH = '@@{0}@@'


def protect_inline(text: str):
    """Pull out spans that must not be escaped, replacing them with placeholders.

    The placeholder must be plain ASCII: an earlier revision used NUL bytes, which
    survived the pipeline whenever a line held more than a few dozen spans and also
    made the output file look binary to grep. '@@n@@' cannot collide with the
    manuscript text and is inert with respect to every later substitution.
    """
    store: list[str] = []

    def keep(value: str) -> str:
        store.append(value)
        return PH.format(len(store) - 1)

    # display math first, so its $$ delimiters are not consumed by the inline rule
    text = re.sub(r'\$\$(.+?)\$\$', lambda m: keep('\\[' + m.group(1).strip() + '\\]'), text, flags=re.S)
    text = re.sub(r'``(.+?)``', lambda m: keep(f'\\texttt{{{escape_plain(m.group(1))}}}'), text)
    text = re.sub(r'`([^`]+)`', lambda m: keep(f'\\texttt{{{escape_plain(m.group(1))}}}'), text)
    text = re.sub(r'\$([^$]+)\$', lambda m: keep(f'${m.group(1)}$'), text)
    return text, store


def restore(text: str, store: list[str]) -> str:
    for i, value in enumerate(store):
        text = text.replace(PH.format(i), value)
    return text


def escape_plain(text: str) -> str:
    for a, b in (('\\', r'\textbackslash{}'), ('&', r'\&'), ('%', r'\%'), ('#', r'\#'),
                 ('_', r'\_'), ('{', r'\{'), ('}', r'\}'),
                 ('~', r'\textasciitilde{}'), ('^', r'\textasciicircum{}')):
        text = text.replace(a, b)
    return text


def _cite(m: re.Match) -> str:
    """Expand a Markdown citation group into \\cite keys.

    Handles comma lists ("[13, 25]") and en-dash / hyphen ranges ("[15-18]").
    Leaving a range unexpanded would emit \\cite{ref15--18}, a key that does not
    exist in the bibliography.
    """
    keys: list[str] = []
    for part in re.split(r'\s*,\s*', m.group(1)):
        part = part.strip()
        rng = re.match(r'^(\d+)\s*[\u2013-]\s*(\d+)$', part)
        if rng:
            keys += [f'ref{i}' for i in range(int(rng.group(1)), int(rng.group(2)) + 1)]
        elif part.isdigit():
            keys.append(f'ref{part}')
    return '\\cite{' + ','.join(keys) + '}' if keys else m.group(0)


def inline(text: str) -> str:
    """Markdown inline -> LaTeX.

    Order is critical. Escaping runs BEFORE any markup is inserted; if markup came
    first, escape_plain would rewrite the backslashes and braces of \\cite{} and
    \\textbf{}, and the mangled form (\\textbackslash{}\\{\\}textbf\\{...\\}) would
    land in the .tex file. Protected spans (code, math) are held aside meanwhile.
    """
    text, store = protect_inline(text)
    text = escape_plain(text)
    text = CITE_RE.sub(_cite, text)
    text = re.sub(r'\*\*(.+?)\*\*', lambda m: '\\textbf{' + m.group(1) + '}', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', lambda m: '\\emph{' + m.group(1) + '}', text)
    text = restore(text, store)
    for a, b in UNICODE_MAP:
        text = text.replace(a, b)
    return text


def table_to_latex(rows: list[str], caption: str, label: str) -> str:
    parsed = []
    for row in rows:
        cells = [c.strip() for c in row.strip().strip('|').split('|')]
        if all(re.fullmatch(r':?-{2,}:?', c) for c in cells if c):
            continue
        parsed.append(cells)
    ncols = max(len(r) for r in parsed)
    align = 'l' * ncols
    lines = [r'\begin{table}[t]', r'\centering', f'\\caption{{{inline(caption)}}}',
             f'\\label{{{label}}}', f'\\begin{{tabular}}{{{align}}}', r'\toprule']
    header, body = parsed[0], parsed[1:]
    lines.append(' & '.join(inline(c) for c in header) + r' \\')
    lines.append(r'\midrule')
    for row in body:
        lines.append(' & '.join(inline(c) for c in row) + r' \\')
    lines += [r'\bottomrule', r'\end{tabular}', r'\end{table}', '']
    return '\n'.join(lines)


def convert_body(body: str, star_sections: bool = False) -> str:
    out: list[str] = []
    lines = body.split('\n')
    i = 0
    pending_caption = None
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        if not line:
            i += 1
            continue

        # table caption line: "**Table N** ..."
        cap = re.match(r'^\*\*Table (\d)\*\*\s*(.+)$', line)
        if cap:
            pending_caption = cap.group(2).strip()
            i += 1
            continue

        if line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                rows.append(lines[i])
                i += 1
            n = len(re.findall(r'\*\*Table (\d)\*\*', body[:body.index(raw)])) + 1
            out.append(table_to_latex(rows, pending_caption or '', f'tab:{n}'))
            pending_caption = None
            continue

        m = re.match(r'^(#{2,4})\s+(.+)$', line)
        if m:
            hashes = len(m.group(1))
            heading = m.group(2).strip()
            # LaTeX numbers sections itself; drop the manuscript's manual numbering
            # ("4 ", "6.2 ", "6.2a ") or the two schemes would both appear.
            heading = re.sub(r'^\d+(?:\.\d+)*[a-z]?\s+', '', heading)
            cmd = {2: 'section', 3: 'subsection', 4: 'subsubsection'}[hashes]
            star = '*' if star_sections else ''
            out.append(f'\\{cmd}{star}{{{inline(heading)}}}')
            i += 1
            continue

        if line.startswith('- '):
            out.append(r'\begin{itemize}')
            while i < len(lines) and lines[i].strip().startswith('- '):
                out.append(f'  \\item {inline(lines[i].strip()[2:])}')
                i += 1
            out.append(r'\end{itemize}')
            continue

        if re.match(r'^\d+\.\s', line):
            out.append(r'\begin{enumerate}')
            while i < len(lines) and re.match(r'^\d+\.\s', lines[i].strip()):
                out.append(f'  \\item {inline(re.sub(r"^\d+\.\s+", "", lines[i].strip()))}')
                i += 1
            out.append(r'\end{enumerate}')
            continue

        if line.startswith('> '):
            out.append(r'\begin{quote}\small')
            while i < len(lines) and lines[i].strip().startswith('> '):
                out.append(inline(lines[i].strip()[2:]))
                i += 1
            out.append(r'\end{quote}')
            continue

        out.append(inline(line))
        i += 1
    return '\n\n'.join(out)


def convert_refs(refs: str) -> str:
    items = re.findall(r'^\[(\d+)\]\s+(.+)$', refs, re.M)
    lines = [r'\begin{thebibliography}{99}']
    for num, text in items:
        lines.append(f'\\bibitem{{ref{num}}} {inline(text)}')
    lines.append(r'\end{thebibliography}')
    return '\n'.join(lines)


def main() -> None:
    md = SRC.read_text(encoding='utf-8')
    parts = extract(md)
    body = convert_body(parts['body'])
    refs = convert_refs(parts['refs'])
    # Appendices are unnumbered; the "Figure captions" list is dropped because each
    # caption already lives inside its figure float.
    tail_md = parts['tail'].split('## Figure captions')[0].rstrip()
    tail = convert_body(tail_md, star_sections=True)

    # two figure floats, placed where the manuscript first refers to each
    fig1 = (r'\begin{figure}[t]' '\n' r'\centering'
            '\n' r'\includegraphics[width=\textwidth]{figures/fig1-racer-loop.eps}'
            '\n' r'\caption{The RACER loop. A recovery claim passes through public-evidence diagnosis, '
            r'risk--utility gating, and an isolated counterfactual replay. When the replay predicts a side '
            r'effect or a failure, the policy vetoes the commit and abstains; otherwise the patch is committed '
            r'with a strict replay receipt. Every admitted record must additionally pass the fail-closed '
            r'admission audit (G1--G7 at record level; G0 and G8 at evaluator level).}'
            '\n' r'\label{fig:loop}' '\n' r'\end{figure}')
    fig2 = (r'\begin{figure}[t]' '\n' r'\centering'
            '\n' r'\includegraphics[width=\textwidth]{figures/fig2-scenario-separation.eps}'
            '\n' r'\caption{Behavioral separation on the irreversible-side-effect track, per scenario and model. '
            r'Each scenario shows the harmful-commit rate of the retry family (8 baselines, 80 rows per scenario) '
            r'and of the unverified ablation RACER$-$counterfactual (10 rows per scenario) against RACER '
            r'(10 rows per scenario), whose harmful-commit rate is zero in every scenario under both models. '
            r'Exact rates are plotted without error bars.}'
            '\n' r'\label{fig:sep}' '\n' r'\end{figure}')

    body = body.replace('\\section{The RACER Framework}', '\\section{The RACER Framework}\n\n' + fig1, 1)
    body = body.replace('\\subsection{Irreversible-side-effect track: seven scenarios, two models}',
                        '\\subsection{Irreversible-side-effect track: seven scenarios, two models}\n\n' + fig2, 1)

    tex = f"""% !TeX program = pdflatex
% Frontiers of Computer Science submission --- generated from recover-or-abstain-fcs.md
% by submission/fcs/md2fcs_tex.py. Edit the Markdown, not this file.
\\documentclass[review]{{fcs}}
\\usepackage{{booktabs}}
\\usepackage{{graphicx}}
\\usepackage{{amsmath}}
\\usepackage{{amssymb}}
\\usepackage{{url}}

\\title{{{parts['title']}}}

% * equal contribution; + corresponding author
\\author[1,*]{{[Given-name Family-name]}}
\\author[2]{{[Given-name Family-name]}}
\\author[1,+]{{[Given-name Family-name]}}
\\address[1]{{[Department, University/Institution, City Postal-code, China]}}
\\address[2]{{[Department, University/Institution, City Postal-code, China]}}
\\corremail{{[xxx@xxx.edu.cn]}}

\\fcssetup{{
  received = {{month dd, yyyy}},
  accepted = {{month dd, yyyy}},
  article-id = {{1}},
  first-page = {{1}},
}}

\\begin{{abstract}}
{inline(parts['abstract'])}
\\end{{abstract}}

\\keywords{{{inline(parts['keywords']).replace(';', ',')}}}

\\begin{{document}}

{body}

\\section*{{Acknowledgements}}
This work was supported by [funding agency, grant number]. The authors thank [names] for [contribution].

\\section*{{Competing interests}}
The authors declare that they have no competing interests.

\\section*{{Data availability}}
The frozen protocols, execution reconciliation appendices, matrices, model-resource registry (without
credentials), baseline registry, and all artifacts---including the 800 trajectories, oracle manifests,
evaluation outputs, the 11{{,}}200-record envelopes, the admission and version-regression audit files, the
statistical outputs, and the independent second-auditor report---are released with the paper. The
implementation uses the Python standard library only and passes 229 unit tests. Credentials are injected
exclusively through runtime environment variables and never enter the repository or the artifacts; public
trajectories and evaluation ground truth are physically separated, and fault\\_truth never appears in any
agent-visible interface.

{refs}

{tail}

\\end{{document}}
"""
    DST.write_text(tex, encoding='utf-8')
    leftovers = sorted({int(m) for m in re.findall(r'@@(\d+)@@', tex)})
    if leftovers:
        raise SystemExit(f'FATAL: unresolved placeholders remain: {leftovers}')
    if '\x00' in tex:
        raise SystemExit('FATAL: NUL byte in output')
    print(f'wrote {DST} ({len(tex)} chars, {len(tex.split())} words)')


if __name__ == '__main__':
    main()
