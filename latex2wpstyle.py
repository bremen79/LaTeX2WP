# SPDX-License-Identifier: GPL-3.0-or-later
"""
 Copyright 2009 Luca Trevisan
 Copyright (C) 2018-2026 Francesco Orabona

 Additional contributors: Radu Grigore

 Based on LaTeX2WP version 0.6.2.
 Modified and maintained by Francesco Orabona, 2018-2026.

 This file is part of LaTeX2WP, a program that converts
 a LaTeX document into a format that is ready to be
 copied and pasted into WordPress.

 You are free to redistribute and/or modify LaTeX2WP under the
 terms of the GNU General Public License (GPL), version 3
 or (at your option) any later version.

 I hope you will find LaTeX2WP useful, but be advised that
 it comes WITHOUT ANY WARRANTY; without even the implied warranty
 of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GPL for more details.

 You should have received a copy of the GNU General Public
 License along with LaTeX2WP.  If you can't find it,
 see <http://www.gnu.org/licenses/>.
"""

# Lines starting with #, like this one, are comments

# Set True for image-based HTML instead of WordPress $latex shortcodes.
HTML = False

# color of LaTeX formulas
textcolor = "000000"

# colors that can be used in the text
colors = { "red" : "ff0000" , "green" : "00ff00" , "blue" : "0000ff" }
# list of colors defined above
colorchoice = ["red","green","blue"]


# Counter identifiers for known theorem-like environments. Environments using
# the same identifier share numbering. Supported shared-counter declarations
# in the source document can override these defaults.

T = { "theorem" : 0 , "lemma" : 0 , "proposition" : 0, "definition" : 0,
               "corollary" : 0, "remark" : 3 , "example" : 1, "claim" : 4,
               "exercise" : 2  }

# list of theorem-like environments
ThmEnvs = ["theorem","definition","lemma","proposition","corollary","claim",
           "remark","example","exercise"]

# the way \begin{theorem}, \begin{lemma} etc are translated in HTML
# the string _ThmType_ stands for the type of theorem
# the string _ThmNumb_ is the theorem number
beginthm = "\n<blockquote><b>_ThmType_ _ThmNumb_.</b> <em>"

# Translation of \begin{theorem}[...]. _ThmName_ is the optional title.
beginnamedthm = "\n<blockquote><b>_ThmType_ _ThmNumb_ (_ThmName_).</b> <em>"

# Translation of \end{theorem}, \end{lemma}, etc.
endthm = "</em></blockquote>\n"


# The converter places endproof in an inline, right-floating span.
beginproof = "<em>Proof:</em> "
endproof = "$latex \\Box&fg=000000$\n\n"

section = "<p><b>_SecNumb_. _SecName_ </b></p>"
sectionstar = "<p><b> _SecName_ </b></p>"
subsection = "<p><b>_SecNumb_._SubSecNumb_. _SecName_ </b></p>"
subsectionstar = "<p><b> _SecName_ </b></p>"

# Font-command prefixes and their HTML tag names. Each prefix consumes an
# opening brace; its matching closing brace ends the generated HTML element.
fontstyle = {
  r'{\em ' : 'em',
  r'{\bf ' : 'b',
  r'{\it ' : 'i',
  r'{\sl ' : 'i',
  r'\textit{' : 'i',
  r'\textsl{' : 'i',
  r'\emph{' : 'em',
  r'\paragraph{' : 'b',
  r'\textbf{' : 'b',
}

# Fixed replacements for complete TeX command tokens, applied after document
# macro expansion. These are not substring replacements. Listed rule order is
# preserved: a replacement that exactly matches a later command entry is
# substituted again. Add entries here rather than editing convertmacros().
# Raw strings, e.g. r"\command", avoid doubling backslashes in Python strings.

M = [     ["\\to","\\rightarrow"] ,
          [r"\coloneqq", r"\triangleq"],
          ["\\B","\\{ 0,1 \\}" ],
          ["\\E","\\mathop{\\mathbb E}"],
          ["\\Pr","\\mathop{\\mathbb P}"],
          ["\\Var","\\mathrm{Var}"],
          ["\\N","{\\mathbb N}"],
          ["\\Z","{\\mathbb Z}"],
          ["\\C","{\\mathbb C}"],
          ["\\R","{\\mathbb R}"],
          ["\\Nat","{\\mathbb N}"],
          ["\\bA","{\\boldsymbol A}"],
          ["\\bC","{\\boldsymbol C}"],
          ["\\bQ","{\\boldsymbol Q}"],
          ["\\bX","{\\boldsymbol X}"],
          ["\\bI","{\\boldsymbol I}"],
          ["\\bM","{\\boldsymbol M}"],
          ["\\bSigma","{\\boldsymbol \\Sigma}"],
          ["\\bS","{\\boldsymbol S}"],
          ["\\be","{\\boldsymbol e}"],
          ["\\bg","{\\boldsymbol g}"],
          ["\\bm","{\\boldsymbol m}"],
          ["\\bp","{\\boldsymbol p}"],
          ["\\bq","{\\boldsymbol q}"],
          ["\\bu","{\\boldsymbol u}"],
          ["\\bv","{\\boldsymbol v}"],
          ["\\bw","{\\boldsymbol w}"],
          ["\\bx","{\\boldsymbol x}"],
          ["\\by","{\\boldsymbol y}"],
          ["\\bz","{\\boldsymbol z}"],
          ["\\bxi","{\\boldsymbol \\xi}"],
          ["\\balpha","{\\boldsymbol \\alpha}"],
          ["\\bbeta","{\\boldsymbol \\beta}"],
          ["\\btheta","{\\boldsymbol \\theta}"],
          ["\\bdelta","{\\boldsymbol \\delta}"],
          ["\\bpi","{\\boldsymbol \\pi}"],
          ["\\Q","{\\mathbb Q}"],
          ["\\xor","\\oplus"],
          ["\\sign","\\rm sign"],
          ["\\argmin","\\mathop{\\mathrm{argmin}}"],
          ["\\argmax","\\mathop{\\mathrm{argmax}}"],
          ["\\conv","\\mathop{\\mathrm{conv}}"],
          ["\\interior","\\mathop{\\mathrm{int}}"],
          ["\\dom","\\mathop{\\mathrm{dom}}"],
          ["\\qedhere"," "],
          ["\\eps","\\epsilon"],
          ["\\Prox","\\text{Prox}"],
          ["\\Regret","\\text{Regret}"],
          ["\\DRegret","\\text{D-Regret}"],
          ["\\SARegret","\\text{SA-Regret}"],
          ["\\Risk","\\text{Risk}"],
          ["\\Gen","\\text{Gen}"],
          ["\\barGen","\\overline{\\text{Gen}}"],
          ["\\Wealth","\\text{Wealth}"],
          ["\\dist","\\text{dist}"],
          ["\\KL","\\text{KL}"],
          ["\\Tr","\\text{Tr}"],
          ["\\wh","\\widehat"],
          ["\\defeq","\\stackrel{\\text{def}}{=}"]
    ]
