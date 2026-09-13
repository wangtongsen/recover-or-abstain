#!/bin/sh
# Compile-check the submission .tex without the journal's fcs.cls.
#
# fcs.cls is not distributed on CTAN, so a stock article class is substituted for
# the local check. This validates everything that is independent of the journal's
# layout: citation keys, cross-references, tabular column counts, figure inclusion,
# maths, escaping and non-ASCII characters. Typesetting itself still has to be
# confirmed on Overleaf with the real class.
#
# Requires TinyTeX (installed at ~/Library/TinyTeX by tools/install steps):
#   curl -sL "https://yihui.org/tinytex/install-bin-unix.sh" | sh
set -e
PATH="$HOME/Library/TinyTeX/bin/universal-darwin:$PATH"
cd "$(dirname "$0")"

python3 - <<'PY'
import re
from pathlib import Path
t = Path('recover-or-abstain-fcs.tex').read_text(encoding='utf-8')

# The journal class is swapped for a stock one: fcs.cls is not on CTAN, so this
# checks the body (citations, tables, figures, maths, escaping) rather than the
# journal layout.
t, n = re.subn(r'\\documentclass\[review\]\{fcs\}',
               r'\\documentclass[10pt]{article}\n\\usepackage[margin=2.2cm]{geometry}', t)
assert n == 1, 'documentclass not found'

# Journal-only front matter that the stock class does not define.
t = re.sub(r'\\author\[[^\]]*\]\{([^}]*)\}', r'\\author{\1}', t)
t = re.sub(r'\\address\[[^\]]*\]\{[^}]*\}\n?', '', t)
t = re.sub(r'\\corremail\{[^}]*\}\n?', '', t)
t = re.sub(r'\\fcssetup\{.*?\n\}\n?', '', t, flags=re.S)
t = re.sub(r'\\keywords\{[^}]*\}\n?', '', t)

# fcs accepts \begin{abstract} in the preamble; the stock class requires it after
# \begin{document}. Lift the block out and re-place it behind the document start
# (fcs supplies \maketitle itself, so the generated file has no \maketitle to key
# on -- matching on one would silently fail and emit two \begin{document}).
abs_block = re.search(r'\\begin\{abstract\}.*?\\end\{abstract\}', t, re.S)
assert abs_block, 'abstract block not found in the preamble'
t = t[:abs_block.start()] + t[abs_block.end():]

t, n = re.subn(r'\\begin\{document\}',
               '\\\\begin{document}\n\\\\maketitle\n\n' + abs_block.group(0).replace('\\', '\\\\'), t)
assert n == 1, f'expected exactly one \\begin{{document}}, found {n}'
assert t.count('\\begin{document}') == 1, 'document env duplicated'
assert t.count('\\begin{abstract}') == 1, 'abstract duplicated'

Path('_compile-test.tex').write_text(t, encoding='utf-8')
print('prepared _compile-test.tex from recover-or-abstain-fcs.tex')
PY

pdflatex -interaction=nonstopmode _compile-test.tex > /tmp/pass1.log 2>&1 || true
pdflatex -interaction=nonstopmode _compile-test.tex > /tmp/pass2.log 2>&1 || true

errs=$(grep -cE '^! ' /tmp/pass2.log || true)
undef=$(grep -cE 'Citation.*undefined|Reference.*undefined' /tmp/pass2.log || true)
echo "errors=$errs undefined_refs=$undef"
if [ "$errs" != "0" ] || [ "$undef" != "0" ]; then
  echo "FAILED - see /tmp/pass2.log"; exit 1
fi
echo "OK: body compiles clean (journal layout still to be confirmed on Overleaf)"
