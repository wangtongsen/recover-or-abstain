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
t, n = re.subn(r'\\documentclass\[review\]\{fcs\}',
               r'\\documentclass[10pt]{article}\n\\usepackage[margin=2.2cm]{geometry}', t)
assert n == 1, 'documentclass not found'
t = re.sub(r'\\author\[[^\]]*\]\{([^}]*)\}', r'\\author{\1}', t)
t = re.sub(r'\\address\[[^\]]*\]\{[^}]*\}\n?', '', t)
t = re.sub(r'\\corremail\{[^}]*\}\n?', '', t)
t = re.sub(r'\\fcssetup\{.*?\n\}\n?', '', t, flags=re.S)
t = re.sub(r'\\keywords\{[^}]*\}\n?', '', t)
# fcs allows a preamble abstract; article requires it after \begin{document}
t = t.replace('\\begin{document}\n\\maketitle\n', '')
t = t.replace('\\begin{abstract}', '\\begin{document}\n\\maketitle\n\n\\begin{abstract}', 1)
Path('_compile-test.tex').write_text(t, encoding='utf-8')
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
