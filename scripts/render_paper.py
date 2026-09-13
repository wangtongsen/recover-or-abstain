#!/usr/bin/env python3
"""Render the Chinese manuscript (Markdown) to the HTML and DOCX typeset versions.

Usage:
  /Users/infoflow/.workbuddy/binaries/python/envs/default/bin/python \
      scripts/render_paper.py

Input : recover-or-abstain-paper.md
Output: recover-or-abstain-paper.html   (A4 print stylesheet, three-line tables)
        recover-or-abstain-paper.docx   (python-docx, same section order)

Why a script: the typeset versions are derived artifacts. They had drifted four
days behind the Markdown because the original conversion was done ad hoc and the
converter was never committed. Keeping one converter in the tree means a
`render -> commit` pair, so the HTML and DOCX can never silently lag the source.
"""
from __future__ import annotations

import html as html_mod
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / 'recover-or-abstain-paper.md'
HTML_OUT = ROOT / 'recover-or-abstain-paper.html'
DOCX_OUT = ROOT / 'recover-or-abstain-paper.docx'

# --------------------------------------------------------------------------- #
# Markdown block parsing
# --------------------------------------------------------------------------- #

BULLET_RE = re.compile(r'^[-*]\s+(.*)$')
ORDERED_RE = re.compile(r'^(\d+)\.\s+(.*)$')
TABLE_SEP_RE = re.compile(r'^\|(?:\s*:?-{2,}:?\s*\|)+$')


def parse_blocks(md: str):
    """Yield (kind, payload) blocks.

    Kinds: h1, h2, h3, h4, p, ul, ol, table, hr.
    """
    lines = md.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if not s:
            i += 1
            continue

        if s == '---':
            yield 'hr', None
            i += 1
            continue

        m = re.match(r'^(#{1,4})\s+(.*)$', s)
        if m:
            level = len(m.group(1))
            yield f'h{level}', m.group(2).strip()
            i += 1
            continue

        # table: a header row followed by a separator row
        if s.startswith('|') and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1].strip()):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                rows.append(lines[i].strip())
                i += 1
            yield 'table', rows
            continue

        if BULLET_RE.match(s):
            items = []
            while i < len(lines) and BULLET_RE.match(lines[i].strip()):
                items.append(BULLET_RE.match(lines[i].strip()).group(1))
                i += 1
            yield 'ul', items
            continue

        if ORDERED_RE.match(s):
            items = []
            while i < len(lines) and ORDERED_RE.match(lines[i].strip()):
                items.append(ORDERED_RE.match(lines[i].strip()).group(2))
                i += 1
            yield 'ol', items
            continue

        # paragraph: consume until a blank line or the start of another block
        para = [s]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (not nxt or nxt == '---' or re.match(r'^#{1,4}\s', nxt)
                    or BULLET_RE.match(nxt) or ORDERED_RE.match(nxt)
                    or (nxt.startswith('|') and i + 1 < len(lines)
                        and TABLE_SEP_RE.match(lines[i + 1].strip()))):
                break
            para.append(nxt)
            i += 1
        yield 'p', '\n'.join(para)


# --------------------------------------------------------------------------- #
# Inline conversion
# --------------------------------------------------------------------------- #

def inline_html(text: str) -> str:
    """Markdown inline -> HTML.

    Math is protected first so that the escaping and emphasis passes never touch
    it; the manuscript uses `$...$` for a handful of statistical expressions.
    """
    store: list[str] = []

    def keep(value: str) -> str:
        store.append(value)
        return f'\x00{len(store) - 1}\x00'

    text = re.sub(r'\$([^$\n]+)\$', lambda m: keep(
        '<span class="math">' + html_mod.escape(m.group(1)) + '</span>'), text)
    text = html_mod.escape(text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<em>\1</em>', text)
    for n, value in enumerate(store):
        text = text.replace(f'\x00{n}\x00', value)
    return text


def split_row(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip('|').split('|')]


def table_html(rows: list[str]) -> str:
    header = split_row(rows[0])
    body = [split_row(r) for r in rows[2:]]
    out = ['<table class="three-line-table">', '<thead>', '<tr>']
    for j, cell in enumerate(header):
        style = ' style="text-align: right;"' if j == 0 and cell == '#' else ''
        out.append(f'<th{style}>{inline_html(cell)}</th>')
    out += ['</tr>', '</thead>', '<tbody>']
    for r in body:
        out.append('<tr>')
        for cell in r:
            out.append(f'<td>{inline_html(cell)}</td>')
        out.append('</tr>')
    out += ['</tbody>', '</table>']
    return '\n'.join(out)


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #

CSS = """  @page { @bottom-center { content: counter(page); } }
  @page cover { @bottom-center { content: none; } }
  section[role="cover"] { page: cover; }
  :root {
    --typography-fontFamily-heading: "黑体", SimHei, sans-serif;
    --typography-fontFamily-body: "宋体", SimSun, serif;
    --typography-fontFamily-bodyLatin: "Times New Roman", serif;
    --typography-fontFamily-code: "Courier New", Consolas, monospace;
    --fs-body: 12pt;
    --ff-body: "宋体", SimSun, serif;
    --typography-fontSize-title: 18pt;
    --typography-fontSize-h1: 15pt;
    --typography-fontSize-h2: 14pt;
    --typography-fontSize-h3: 12pt;
    --typography-fontSize-body: 12pt;
    --typography-fontSize-abstract: 11pt;
    --typography-fontSize-caption: 10.5pt;
    --typography-fontSize-footnote: 9pt;
    --typography-lineHeight-body: 1.5;
    --typography-lineHeight-heading: 1.5;
    --typography-fontWeight-heading: 700;
    --typography-fontWeight-body: 400;
    --color-primary: #000000;
    --color-text: #000000;
    --color-muted: #555555;
    --color-tableHeaderBg: #f0f0f0;
    --color-tableBorder: #000000;
    --color-background: #ffffff;
    --color-scopeBg: #f7f7f7;
    --spacing-paragraph: 0.5em;
    --spacing-sectionGap: 1.5em;
    --spacing-block: 1em;
    --spacing-indent: 2em;
    --spacing-coverTop: 8em;
    --spacing-cell: 0.4em;
    --spacing-cellX: 0.6em;
    --border-scope: 3px;
    --border-tableTop: 1.5pt;
    --border-tableMid: 0.75pt;
    --border-tableBottom: 1.5pt;
    --page-content-width: 16cm;
    --margin-page-top: 3cm;
    --margin-page-bottom: 2.5cm;
    --margin-page-left: 2.5cm;
    --margin-page-right: 2.5cm;
  }
  * { box-sizing: border-box; }
  body { max-width: var(--page-content-width); margin-left: auto; margin-right: auto; padding: var(--margin-page-top) var(--margin-page-right) var(--margin-page-bottom) var(--margin-page-left); font-family: var(--ff-body); font-size: var(--fs-body); line-height: var(--typography-lineHeight-body); color: var(--color-text); background: var(--color-background); }
  section[role="cover"] { min-height: 22cm; }
  .cover-body { text-align: center; padding-top: var(--spacing-coverTop); }
  .cover-title { text-align: center; font-family: var(--typography-fontFamily-heading); font-size: var(--typography-fontSize-title); line-height: var(--typography-lineHeight-heading); font-weight: var(--typography-fontWeight-heading); color: var(--color-primary); margin-bottom: var(--spacing-sectionGap); }
  .cover-subtitle { text-align: center; font-family: var(--typography-fontFamily-bodyLatin); font-size: var(--typography-fontSize-abstract); margin-bottom: var(--spacing-sectionGap); }
  .paper-body { text-align: left; }
  h1 { text-align: left; font-family: var(--typography-fontFamily-heading); font-size: var(--typography-fontSize-title); line-height: var(--typography-lineHeight-heading); font-weight: var(--typography-fontWeight-heading); color: var(--color-primary); margin-bottom: var(--spacing-sectionGap); }
  h2 { text-align: left; font-family: var(--typography-fontFamily-heading); font-size: var(--typography-fontSize-h1); line-height: var(--typography-lineHeight-heading); font-weight: var(--typography-fontWeight-heading); color: var(--color-primary); margin-top: var(--spacing-sectionGap); margin-bottom: var(--spacing-paragraph); }
  h3 { text-align: left; font-family: var(--typography-fontFamily-heading); font-size: var(--typography-fontSize-h2); line-height: var(--typography-lineHeight-heading); font-weight: var(--typography-fontWeight-heading); color: var(--color-primary); margin-top: var(--spacing-block); margin-bottom: var(--spacing-paragraph); }
  h4 { text-align: left; font-family: var(--typography-fontFamily-heading); font-size: var(--typography-fontSize-h3); line-height: var(--typography-lineHeight-heading); font-weight: var(--typography-fontWeight-heading); color: var(--color-primary); margin-top: var(--spacing-block); margin-bottom: var(--spacing-paragraph); }
  p { text-align: left; font-family: var(--typography-fontFamily-body); font-size: var(--typography-fontSize-body); line-height: var(--typography-lineHeight-body); color: var(--color-text); margin-bottom: var(--spacing-paragraph); text-indent: var(--spacing-indent); }
  strong { font-weight: var(--typography-fontWeight-heading); }
  em { font-family: var(--typography-fontFamily-bodyLatin); }
  code { font-family: var(--typography-fontFamily-code); font-size: var(--typography-fontSize-abstract); }
  .math { font-family: var(--typography-fontFamily-bodyLatin); font-style: italic; }
  ul, ol { text-align: left; font-family: var(--typography-fontFamily-body); font-size: var(--typography-fontSize-body); line-height: var(--typography-lineHeight-body); margin: 0 0 var(--spacing-paragraph) var(--spacing-indent); padding-left: var(--spacing-indent); }
  li { text-align: left; font-family: var(--typography-fontFamily-body); font-size: var(--typography-fontSize-body); line-height: var(--typography-lineHeight-body); margin-bottom: var(--spacing-paragraph); }
  .three-line-table { width: 100%; border-collapse: collapse; margin: var(--spacing-block) 0 var(--spacing-sectionGap); font-family: var(--typography-fontFamily-body); font-size: var(--typography-fontSize-abstract); line-height: var(--typography-lineHeight-body); color: var(--color-text); page-break-inside: avoid; }
  .three-line-table thead tr:first-child { border-top: var(--border-tableTop) solid var(--color-tableBorder); }
  .three-line-table thead tr:last-child { border-bottom: var(--border-tableMid) solid var(--color-tableBorder); }
  .three-line-table tbody tr:last-child { border-bottom: var(--border-tableBottom) solid var(--color-tableBorder); }
  .three-line-table th { text-align: left; font-family: var(--typography-fontFamily-heading); font-size: var(--typography-fontSize-abstract); font-weight: var(--typography-fontWeight-heading); background: var(--color-tableHeaderBg); padding: var(--spacing-cell) var(--spacing-cellX); }
  .three-line-table td { text-align: left; font-family: var(--typography-fontFamily-body); font-size: var(--typography-fontSize-abstract); padding: var(--spacing-cell) var(--spacing-cellX); vertical-align: top; }
  .three-line-table th:nth-child(n+2), .three-line-table td:nth-child(n+2) { text-align: center; }
  .references p { text-indent: 0; margin-bottom: 0.25em; font-size: var(--typography-fontSize-abstract); }"""


def render_html(md: str) -> str:
    title = re.search(r'^#\s+(.+)$', md, re.M).group(1).strip()
    parts = [f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="docx-page-size" content="A4">
<title>{html_mod.escape(title)}</title>
<style>
{CSS}
</style>
</head>
<body>
<section role="cover">
  <div class="cover-body">
    <h1 class="cover-title">{html_mod.escape(title)}</h1>
    <p class="cover-subtitle">RACER v2 · 三域 × 七场景 × 双模型 · 预注册基准（协议 v0.5）</p>
  </div>
</section>
<main class="paper-body">"""]

    in_refs = False
    for kind, payload in parse_blocks(md):
        if kind == 'hr':
            continue
        if kind in ('h1', 'h2', 'h3', 'h4'):
            level = int(kind[1])
            if level == 1:
                continue  # the title is on the cover and repeated below only once
            if payload.strip() == '参考文献':
                in_refs = True
                parts.append('<h2>参考文献</h2>')
                parts.append('<div class="references">')
                continue
            parts.append(f'<{kind}>{inline_html(payload)}</{kind}>')
            continue
        if in_refs and kind == 'p':
            parts.append(f'<p>{inline_html(payload)}</p>')
            continue
        if kind == 'p':
            parts.append(f'<p>{inline_html(payload)}</p>')
        elif kind == 'ul':
            parts.append('<ul>')
            parts += [f'<li>{inline_html(it)}</li>' for it in payload]
            parts.append('</ul>')
        elif kind == 'ol':
            parts.append('<ol>')
            parts += [f'<li>{inline_html(it)}</li>' for it in payload]
            parts.append('</ol>')
        elif kind == 'table':
            parts.append(table_html(payload))

    if in_refs:
        parts.append('</div>')
    parts.append('</main>\n</body>\n</html>')
    return '\n'.join(parts) + '\n'


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #

def inline_runs(paragraph, text: str):
    """Emit bold/italic/code runs into a python-docx paragraph."""
    token = re.compile(r'(\*\*.+?\*\*|\*[^*\n]+?\*|`[^`]+`|\$[^$\n]+\$)')
    for piece in token.split(text):
        if not piece:
            continue
        if piece.startswith('**') and piece.endswith('**'):
            paragraph.add_run(piece[2:-2]).bold = True
        elif piece.startswith('`') and piece.endswith('`'):
            run = paragraph.add_run(piece[1:-1])
            run.font.name = 'Courier New'
        elif piece.startswith('$') and piece.endswith('$'):
            run = paragraph.add_run(piece[1:-1])
            run.italic = True
        elif piece.startswith('*') and piece.endswith('*'):
            paragraph.add_run(piece[1:-1]).italic = True
        else:
            paragraph.add_run(piece)


def render_docx(md: str):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, Cm

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(3)
    section.bottom_margin = Cm(2.5)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)

    style = doc.styles['Normal']
    style.font.name = '宋体'
    style.font.size = Pt(12)
    style.paragraph_format.line_spacing = 1.5

    title = re.search(r'^#\s+(.+)$', md, re.M).group(1).strip()
    heading = doc.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run('RACER v2 · 三域 × 七场景 × 双模型 · 预注册基准（协议 v0.5）')
    doc.add_page_break()

    for kind, payload in parse_blocks(md):
        if kind == 'hr':
            continue
        if kind == 'h1':
            continue
        if kind in ('h2', 'h3'):
            doc.add_heading(payload, level=int(kind[1]) - 1)
            continue
        if kind == 'h4':
            doc.add_heading(payload, level=3)
            continue
        if kind == 'p':
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Pt(24)
            inline_runs(p, payload)
            continue
        if kind in ('ul', 'ol'):
            for it in payload:
                p = doc.add_paragraph(style='List Bullet' if kind == 'ul' else 'List Number')
                inline_runs(p, it)
            continue
        if kind == 'table':
            rows = payload
            header = split_row(rows[0])
            body = [split_row(r) for r in rows[2:]]
            table = doc.add_table(rows=1, cols=len(header))
            table.style = 'Table Grid'
            for j, cell in enumerate(header):
                table.rows[0].cells[j].text = re.sub(r'[*`]', '', cell)
                for run in table.rows[0].cells[j].paragraphs[0].runs:
                    run.bold = True
            for r in body:
                cells = table.add_row().cells
                for j, cell in enumerate(r[:len(header)]):
                    cells[j].text = re.sub(r'[*`]', '', cell)
            doc.add_paragraph()

    doc.save(DOCX_OUT)
    return DOCX_OUT


# --------------------------------------------------------------------------- #

def main():
    md = SRC.read_text(encoding='utf-8')
    HTML_OUT.write_text(render_html(md), encoding='utf-8')
    render_docx(md)
    # sanity: no unresolved markup leaked into the HTML body
    html_out = HTML_OUT.read_text(encoding='utf-8')
    leftovers = re.findall(r'\*\*|(?<!\w)\*\s', html_out)
    print(f'wrote {HTML_OUT.name} ({len(html_out)} chars) and {DOCX_OUT.name}')
    if '**' in html_out:
        raise SystemExit('FATAL: unconverted bold markup in HTML')


if __name__ == '__main__':
    main()
