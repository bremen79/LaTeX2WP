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


# This converter handles a supported subset of TeX; it does not execute TeX.
# Math delimiters inside text arguments are not parsed recursively.

import re
import argparse
import base64
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from html import escape, unescape
from urllib.parse import quote, urlencode
from urllib.request import urlopen
from latex2wp_macros import (COMMAND, read_group, skip_spaces, strip_comments,
                             read_inputs, collect_macros, expand_macros)
from latex2wp_html import WORDPRESS_MATH_RE, render_paragraphs

from latex2wpstyle import *

__version__ = "0.7.0"

# Initialize counters from the style configuration; shared IDs share numbering.
count = dict()
for thm in ThmEnvs:
  count[T[thm]] = 0
count["section"] = count["subsection"] = count["equation"] = 0

ref={}

endlatex = "&fg="+textcolor
if HTML : endproof = "<img src=\"http://l.wordpress.com/latex.php?latex=\\Box&fg=000000\">"

inthm = ""

# Bibliographies are loaded only when a citation is encountered.
bib_database = None
bibliography_paths = []
current_section_ref = "0"


def find_bibliographies(source, inputfile):
    # Read the whole document, including declarations in the preamble.
    source = re.sub(r'(?m)(?<!\\)(?:\\\\)*%[^\n]*', '', source)
    declarations = re.findall(r'\\bibliography\s*\{([^{}]*)\}', source)
    paths = []
    for declaration in declarations:
        for name in declaration.split(','):
            name = name.strip()
            if not name:
                continue
            if not name.endswith('.bib'):
                name += '.bib'
            path = (inputfile.resolve().parent / name).resolve()
            if path not in paths:
                paths.append(path)
    return paths


def load_bibliography():
    global bib_database
    if bib_database is None:
        if not bibliography_paths:
            raise ValueError(r"Citations require a \bibliography{path} declaration in the TeX file")
        entries = {}
        try:
            import bibtexparser
            for path in bibliography_paths:
                with path.open(encoding="utf-8") as source:
                    entries.update(bibtexparser.bparser.BibTexParser(
                        common_strings=True).parse_file(source).entries_dict)
        except (OSError, ImportError) as error:
            raise ValueError(f"Cannot load bibliography: {error}") from error
        bib_database = entries
    return bib_database


# Each entry contains the source symbol, temporary placeholder, prose HTML,
# and math replacement. Protect symbols after expanding document macros, then
# restore them after processing prose and math separately.

esc = [["\\$","_dollar_","&#36;","\\$"],
       ["\\%","_percent_","&#37;","\\%"],
       ["\\&","_amp_","&amp;","\\&"],
       [">","_greater_","&gt;","&gt;"],
       ["<","_lesser_","&lt;","&lt;"]]

M = M + [ ["\\more","<!--more-->"],
          ["\\newblock","\\\\"],
          ["\\sloppy",""],
          ["\\S","&sect;"]]

Mnomath =[["\\\\","<br/>\n"],
          ["\\ "," "],
          ["\\`a","&agrave;"],
          ["\\'a","&aacute;"],
          ["\\\"a","&auml;"],
          ["\\aa ","&aring;"],
          ["{\\aa}","&aring;"],
          ["\\`e","&egrave;"],
          ["\\'e","&eacute;"],
          ["\\\"e","&euml;"],
          ["\\`i","&igrave;"],
          ["\\'i","&iacute;"],
          ["\\\"i","&iuml;"],
          ["\\`o","&ograve;"],
          ["\\'o","&oacute;"],
          ["\\\"o","&ouml;"],
          ["\\`o","&ograve;"],
          ["\\'o","&oacute;"],
          ["\\\"o","&ouml;"],
          ["\\H o","&ouml;"],
          ["\\`u","&ugrave;"],
          ["\\'u","&uacute;"],
          ["\\\"u","&uuml;"],
          ["\\`u","&ugrave;"],
          ["\\'u","&uacute;"],
          ["\\\"u","&uuml;"],
          ["\\v{C}","&#268;"]]


cb = re.compile("\\{|}")
sb = re.compile("\\[|]")


def extractbody(m) :
    """Extract the document body and strip comments, retaining whitespace.

    Without document delimiters, treat the whole input as a fragment.
    """
    begin = re.compile("\\\\begin\\s*")
    m= begin.sub("\\\\begin",m)
    end = re.compile("\\\\end\\s*")
    m = end.sub("\\\\end",m)
    
    beginenddoc = re.compile("\\\\begin\\{document}"
                          "|\\\\end\\{document}")
    parse = beginenddoc.split(m)
    if len(parse)== 1 :
       m = parse[0]
    else :
       m = parse[1]

    return strip_comments(m)


def protect_escapes(source):
    """Protect escaped symbols after expanding document macros."""
    for original, placeholder, _, _ in esc:
        source = source.replace(original, placeholder)
    return source


def normalize_math_delimiters(m):
    """Normalize display delimiters after escaped dollars are protected."""

    doubledollar = re.compile("\\$\\$")
    L=doubledollar.split(m)
    m=L[0]
    for i in range(1,(len(L)+1)//2) :
        m = m+ "\\[" + L[2*i-1] + "\\]" + L[2*i]

    m=m.replace("\\begin{eqnarray*}","\\[ \\begin{array}{rcl} ")
    m=m.replace("\\end{eqnarray*}","\\end{array} \\]")

    return m

def convertsqb(m):
    """Rewrite optional item labels and environment titles as braced tokens."""
    r = re.compile("\\\\item\\s*\\[.*?\\]", re.S)

    Litems = r.findall(m)
    Lrest = r.split(m)

    m = Lrest[0]
    for i in range(0,len(Litems)) :
      s= Litems[i]
      s=s.replace("\\item","\\nitem")
      s=s.replace("[","{")
      s=s.replace("]","}")
      m=m+s+Lrest[i+1]

    r = re.compile("\\\\begin\\s*\\{\\w+}\\s*\\[.*?\\]", re.S)
    Lthms = r.findall(m)
    Lrest = r.split(m)

    m = Lrest[0]
    for i in range(0,len(Lthms)) :
      s=Lthms[i]
      s=s.replace("\\begin","\\nbegin")
      s=s.replace("[","{")
      s=s.replace("]","}")
      m=m+s+Lrest[i+1]

    return m


def converttables(m) :
    retable = re.compile("\\\\begin\\s*\\{tabular}.*?\\\\end\\s*\\{tabular}"
                         "|\\\\begin\\s*\\{btabular}.*?\\\\end\\s*\\{btabular}", re.S)
    tables = retable.findall(m)
    rest = retable.split(m)

    m = rest[0]
    for i in range(len(tables)) :
        if tables[i].find("{btabular}") != -1 :
            m = m + convertonetable(tables[i],True)
        else :
            m = m + convertonetable(tables[i],False)
        m = m + rest[i+1]
    return m


def convertmacros(m) :
    # Resolve the ordered rules once. A replacement may name a later rule;
    # walking backwards preserves their forward substitution order.
    replacements = {}
    for command, replacement in reversed(M):
        replacements[command] = replacements.get(replacement, replacement)
    return re.sub(r'\\(?:[A-Za-z]+|[^A-Za-z])',
                  lambda match: replacements.get(match.group(), match.group()), m)


def convertonetable(m, border):
    opening = re.match(r"\\begin\{(b?tabular)\}\s*", m)
    spec_start = opening.end()
    spec, content_start = read_group(m, spec_start)
    columns = [char for char in spec if char != '|' and not char.isspace()]
    if not columns or any(char not in 'lcr' for char in columns):
        raise ValueError(f"Unsupported table column specification: {spec!r}")
    align = {'l': 'left', 'c': 'center', 'r': 'right'}
    content = re.sub(r"\\end\{b?tabular\}\s*$", '', m[content_start:])
    content = re.sub(r"\\hline\b", '', content)
    # Split separators outside brace groups and dollar-delimited math.
    rows, row, cell = [], [], []
    depth, math_mode, pos = 0, False, 0
    while pos < len(content):
        char = content[pos]
        if char == '\\':
            if content.startswith('\\\\', pos) and depth == 0 and not math_mode:
                row.append(''.join(cell))
                rows.append(row)
                row, cell = [], []
                pos += 2
                continue
            if pos + 1 < len(content) and content[pos + 1] in '{}$&':
                cell.append(content[pos:pos + 2])
                pos += 2
                continue
        if char == '$':
            math_mode = not math_mode
        if not math_mode:
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
        if char == '&' and depth == 0 and not math_mode:
            row.append(''.join(cell))
            cell = []
        else:
            cell.append(char)
        pos += 1
    if row or ''.join(cell).strip():
        rows.append(row + [''.join(cell)])
    result = ['<table align="center"' + (' border="1"' if border or '|' in spec else '') + '>']
    for row in rows:
        if len(row) > len(columns):
            raise ValueError("Table row has more cells than declared columns")
        row += [''] * (len(columns) - len(row))
        result.append('<tr>' + ''.join(
            f'<td align="{align[column]}">{cell}</td>'
            for column, cell in zip(columns, row)) + '</tr>')
    return ''.join(result) + '</table>'


def separatemath(m) :
    mathre = re.compile("\\$.*?\\$"
                   r"|\\\(.*?\\\)"
                   "|\\\\begin\\{equation}.*?\\\\end\\{equation}"
                   r"|\\begin\{equation\*\}.*?\\end\{equation\*\}"
                   "|\\\\begin\\{align}.*?\\\\end\\{align}"
                   "|\\\\begin\\{align\\*}.*?\\\\end\\{align\\*}"
                   "|\\\\\\[.*?\\\\\\]", re.S)
    math = [re.sub(r'\s+', ' ', part) for part in mathre.findall(m)]
    text = mathre.split(m)
    return(math,text)


def processmath(math_parts, referenced_labels):
    prepared = []
    label_pattern = re.compile(r"\\label\s*\{([^{}]+)\}")
    suppress_pattern = re.compile(r"\\(?:nonumber|notag)\b")
    for part in math_parts:
        inline = part.startswith(('$', r'\('))
        anchors = []
        if inline:
            body = part[1:-1] if part.startswith('$') else part[2:-2]
        else:
            opening = re.match(r"\\begin\{(equation\*?|align\*?)\}", part)
            if opening:
                environment = opening.group(1)
                body = part[opening.end():-len('\\end{' + environment + '}')]
            else:
                environment, body = '', part[2:-2]
            numbered = environment in ('equation', 'align')
            if environment.startswith('align'):
                # Do not split row breaks belonging to nested matrices/cases.
                rows, start, depth = [], 0, 0
                for token in re.finditer(r"\\begin\{[^}]+\}|\\end\{[^}]+\}|\\\\(?:\s*\[[^\]]*\])?", body):
                    if token.group().startswith('\\begin'):
                        depth += 1
                    elif token.group().startswith('\\end'):
                        depth -= 1
                    elif depth == 0:
                        rows.append(body[start:token.start()])
                        start = token.end()
                rows.append(body[start:])
                if len(rows) > 1 and not rows[-1].strip():
                    rows.pop()
            else:
                rows = [body]
            rendered = []
            for row in rows:
                labels = label_pattern.findall(row)
                suppress = bool(suppress_pattern.search(row))
                row = suppress_pattern.sub('', label_pattern.sub('', row))
                referenced = any(name.replace(':', '') in referenced_labels for name in labels)
                if numbered and not suppress and referenced:
                    count['equation'] += 1
                    for name in labels:
                        name = name.replace(':', '')
                        ref[name] = [count['equation'], name]
                        anchors.append('<a name="' + escape(name, quote=True) + '"></a>')
                    row += (' & ' if environment == 'align' else r'\quad ') + '(' + str(count['equation']) + ')'
                rendered.append(row)
            body = r' \\ '.join(rendered)
            if environment.startswith('align'):
                body = r'\begin{aligned}' + body + r'\end{aligned}'
        prepared.append((inline, body, anchors))

    # All equation labels must be registered before resolving forward
    # references. References inside math become TeX text, never HTML links.
    result = []
    for inline, body, anchors in prepared:
        body = convertref(body, math_mode=True)
        if HTML:
            formula = ('{' + body + '}') if inline else r'\displaystyle ' + body
            rendered = '<img src="https://l.wordpress.com/latex.php?latex=' + quote(formula, safe='') + endlatex + '">'
        else:
            rendered = '$latex ' + (('{' + body + '}') if inline else r'\displaystyle ' + body) + endlatex + '$'
        if not inline:
            rendered = '<p align=center>' + rendered + '</p>\n'
        result.append(''.join(anchors) + rendered)
    return result


def convertbeginnamedthm(thname,thm) :
  global inthm

  count[T[thm]] +=1
  inthm = thm
  t = beginnamedthm.replace("_ThmType_",thm.capitalize())
  t = t.replace("_ThmNumb_",str(count[T[thm]]))
  t = t.replace("_ThmName_",thname)
  return t + '<latex2wp-body></latex2wp-body>'


def convertbeginthm(thm):
  global inthm

  count[T[thm]] +=1
  inthm = thm
  t = beginthm.replace("_ThmType_",thm.capitalize())
  t = t.replace("_ThmNumb_",str(count[T[thm]]))
  return t + '<latex2wp-body></latex2wp-body>'

 
def convertendthm(thm):
  global inthm

  inthm = ""
  return(endthm)


def convertlab(m):
    global inthm
    global ref

    m=cb.split(m)[1]
    m=m.replace(":","")
    if inthm != "":
        ref[m]=[count[T[inthm]], m]
    else:
        ref[m]=[current_section_ref, m]
    return("<a name=\""+m+"\"></a>")
        


def convertproof(m) :
    if m.find("begin") != -1 :
        return('\n\n' + beginproof + '<latex2wp-body></latex2wp-body>')
    else:
        return('<span class="qed" style="float: right; margin-left: 1em;">'
               + endproof.strip() + '</span>\n\n')
    

def convertsection (m) :
      global current_section_ref
      L=cb.split(m)

      # Heading text is protected by a token before this brace split.

      if L[0].find("*") == -1 :
          t=section
          count["section"] += 1
          count["subsection"]=0
          current_section_ref = str(count["section"])

      else :
          t=sectionstar

      t=t.replace("_SecNumb_",str(count["section"]) )
      t=t.replace("_SecName_",L[1])
      return(t)

def convertsubsection (m) :
        global current_section_ref
        L=cb.split(m)

        if L[0].find("*") == -1 :
            t=subsection
            count["subsection"] += 1
            current_section_ref = str(count["section"]) + "." + str(count["subsection"])
        else :
            t=subsectionstar
        
        t=t.replace("_SecNumb_",str(count["section"]) )
        t=t.replace("_SubSecNumb_",str(count["subsection"]) )
        t=t.replace("_SecName_",L[1])     
        return(t)


def control_arguments(control, count):
    command = COMMAND.match(control)
    pos = command.end()
    if control[pos:pos + 1] == '*':
        pos += 1
    arguments = []
    for _ in range(count):
        argument, pos = read_group(control, skip_spaces(control, pos))
        arguments.append(argument)
    return arguments


def converturl(control):
    url, label = control_arguments(control, 2)
    return '<a href="' + escape(url, quote=True) + '">' + label + '</a>'


def converturlnosnap(control):
    url, label = control_arguments(control, 2)
    return '<a class="snap_noshots" href="' + escape(url, quote=True) + '">' + label + '</a>'


def convertimage(m):
    L = cb.split(m)
    return ("<p align=center><img " + L[1] + " src=\"" + L[3] + "\"></p>")


def convertstrike(m):
    L=cb.split(m)
    return("<s>" + L[1] + "</s>")


def convert_named_item(control):
    label = cb.split(control)[1]
    return '<li>' + label


def convert_text_url(control):
    url = cb.split(control)[1]
    return '<a href="' + escape(url, quote=True) + '">' + escape(url) + '</a>'


def convert_named_theorem(control, environment):
    start = control.index('}', control.index('{')) + 1
    start = re.match(r'\s*', control[start:]).end() + start
    name, _ = read_group(control, start)
    name = re.sub(r'^\((.*?)\)$', r'\1', name)
    name = re.sub(r'>\((.*?)\)<', r'>\1<', name)
    return convertbeginnamedthm(name, environment)


# Registration is by exact command and environment name. Handlers receive the
# complete token so argument parsing remains separate from dispatch.
ENVIRONMENT_HANDLERS = {
    'begin': {'proof': convertproof},
    'nbegin': {'proof': convertproof},
    'end': {'proof': convertproof},
}
for environment, tags in {
        'itemize': ('<ul>', '</ul>'),
        'enumerate': ('<ol>', '</ol>'),
        'quote': ('<blockquote>', '</blockquote>'),
        'center': ('<div style="text-align: center;">', '</div>'),
        **{name: (f'<div style="color:#{colors[name]};">', '</div>')
           for name in colorchoice},
}.items():
    for action, tag in [('begin', tags[0]), ('nbegin', tags[0]), ('end', tags[1])]:
        ENVIRONMENT_HANDLERS[action][environment] = lambda token, tag=tag: tag
for environment in ThmEnvs:
    ENVIRONMENT_HANDLERS['begin'][environment] = (
        lambda token, environment=environment: convertbeginthm(environment))
    ENVIRONMENT_HANDLERS['nbegin'][environment] = (
        lambda token, environment=environment: convert_named_theorem(token, environment))
    ENVIRONMENT_HANDLERS['end'][environment] = (
        lambda token, environment=environment: convertendthm(environment))


def convert_environment(control):
    action, environment = re.match(r'\\(nbegin|begin|end)\s*\{([^{}]+)\}', control).groups()
    handler = ENVIRONMENT_HANDLERS[action].get(environment)
    return handler(control) if handler else ''


TEXT_HANDLERS = {
    'begin': convert_environment,
    'nbegin': convert_environment,
    'end': convert_environment,
    'item': lambda token: '<li>',
    'nitem': convert_named_item,
    'href': converturl,
    'hrefnosnap': converturlnosnap,
    'url': convert_text_url,
    'section': convertsection,
    'section*': convertsection,
    'subsection': convertsubsection,
    'subsection*': convertsubsection,
    'label': convertlab,
    'image': convertimage,
    'sout': convertstrike,
}
TEXT_ARGUMENT_COUNTS = dict.fromkeys(TEXT_HANDLERS, 1)
TEXT_ARGUMENT_COUNTS.update(item=0, nbegin=2, href=2, hrefnosnap=2, image=3)


def text_controls(text):
    """Yield complete command tokens, including nested brace arguments."""
    offset = 0
    for match in COMMAND.finditer(text):
        if match.start() < offset:
            continue
        command, end = match.group()[1:], match.end()
        if text[end:end + 1] == '*' and command + '*' in TEXT_HANDLERS:
            command += '*'
            end += 1
        if command not in TEXT_HANDLERS:
            continue
        for _ in range(TEXT_ARGUMENT_COUNTS[command]):
            _, end = read_group(text, skip_spaces(text, end))
        yield match.start(), end, command, text[match.start():end]
        offset = end


def processtext(text):
    headings = {}
    heading_pattern = re.compile(r"\\(?:subsection|section)\*?\s*(?=\{)")
    protected, offset = [], 0
    for match in heading_pattern.finditer(text):
        if match.start() < offset:
            continue
        title, end = read_group(text, match.end())
        token = f"__heading_{len(headings)}__"
        headings[token] = title
        protected.append(text[offset:match.end()] + "{" + token + "}")
        offset = end
    text = "".join(protected) + text[offset:]

    for source, replacement in Mnomath:
        text = text.replace(source, replacement)

    parts, offset = [], 0
    for start, end, command, control in text_controls(text):
        parts.append(text[offset:start])
        parts.append(TEXT_HANDLERS[command](control))
        offset = end
    parts.append(text[offset:])
    result = ''.join(parts)

    for token, title in headings.items():
        result = result.replace(token, title)
    # Apply TeX typography to prose while preserving links and attributes.
    result = ''.join(
        part if part.startswith('<') else part.replace('``', '&ldquo;')
            .replace("''", '&rdquo;').replace('---', '&mdash;').replace('--', '&ndash;')
        for part in re.split(r'(<a\b[^>]*>.*?</a>|<[^>]*>)', result, flags=re.S))
    return processfontstyle(result)


def processfontstyle(w) :
        close = dict()
        ww = ""
        level = i = 0
        while i < len(w):
          special = False
          for k, v in list(fontstyle.items()):
            l = len(k)
            if w[i:i+l] == k:
              level += 1
              ww += '<' + v + '>'
              close[level] = '</' + v + '>'
              i += l
              special = True
          if not special:
            if w[i] == '{':
              ww += '{'
              level += 1
              close[level] = '}'
            elif w[i] == '}' and level > 0:
              ww += close[level]
              level -= 1
            else:
              ww += w[i]
            i += 1
        return ww
    

def convertref(source, math_mode=False):
    if not math_mode:
        # A reference in an existing hyperlink is its label text; wrapping it
        # in a second anchor would produce invalid nested links.
        source = re.sub(r'<a\b[^>]*>.*?</a>',
                        lambda match: convertref(match.group(), math_mode=True),
                        source, flags=re.S)

    def replace(match):
        command, label = match.groups()
        lab = label.replace(':', '')
        if lab not in ref:
            print(f"Warning: unresolved reference {lab!r}", file=sys.stderr)
            return '??'
        number = str(ref[lab][0])
        if command == 'eqref':
            number = '(' + number + ')'
        if math_mode:
            return number
        return '<a href="#' + escape(ref[lab][1], quote=True) + '">' + number + '</a>'

    return re.sub(r'\\(eqref|ref)\s*\{([^{}]+)\}', replace, source)


def convertciteall(m):
    r = re.compile("\\{?\\\\cite.*?\\{.*?}\\}?|\\{?\\\\citet.*?\\{.*?}\\}?|\\{?\\\\citep.*?\\{.*?}\\}?", re.S)
    Lthms = r.findall(m)
    Lrest = r.split(m)

    m = Lrest[0]
    for i in range(0,len(Lthms)) :
      s=Lthms[i]
      
      if s.find("\\citep") != -1 :
        citationtext = convertcite(s,"p")
      elif s.find("\\citet") != -1 :
        citationtext = convertcite(s,"t")
      elif s.find("\\cite") != -1 :
        citationtext = convertcite(s,"p")
     
      m=m+citationtext+Lrest[i+1]

    return m


def extract_surnames(authors_str):
    from bibtexparser.customization import splitname
    authors = re.split(r'\s+and\s+', authors_str.strip())
    surnames = []
    for author in authors:
        name = splitname(author)
        surnames.append(' '.join(name['von'] + name['last']))
    if len(surnames)==1:
        return surnames[0]
    elif len(surnames)==2:
        return ' &amp; '.join(surnames)
    else: 
        return surnames[0] + ' et al.'


def convertcite(m,flag):
    global bib_database
    load_bibliography()
    
    p=re.compile("\\\\cite.*?\\{.*?}|\\\\citet.*?\\{.*?}|\\\\citep.*?\\{.*?}", re.S)

    M=p.findall(m)
    
    for i in range(len(M)):
        t=M[i]
        bibentries=cb.split(t)[1]
        opt_thm=sb.split(t) # Optional citation locator, e.g. a theorem or page number.
        if len(opt_thm)==1:
            opt_thm_str=""
        else:
            opt_thm_str=", " + opt_thm[1]
        
        cit_list = bibentries.split(",")
        if flag == "t":
            w=""
        else:
            w="("
        for idx,cit in enumerate(cit_list):
            cit=cit.strip()
            entry = bib_database.get(cit)
            if entry is None or "author" not in entry or "year" not in entry:
                print(f"Warning: missing or incomplete citation {cit!r} in {', '.join(map(str, bibliography_paths))}", file=sys.stderr)
                w += "[missing citation: " + escape(cit) + "]"
                if idx != len(cit_list) - 1:
                    w += ", "
                continue
            surnames=extract_surnames(bib_database[cit]["author"])
            if flag == "t":
                if "url" in bib_database[cit]:
                    w=w+"<a href=\""+bib_database[cit]["url"]+"\">"+surnames+" ("+bib_database[cit]["year"]+opt_thm_str+")</a>"
                else:
                    w=w+surnames+" ("+bib_database[cit]["year"]+opt_thm_str+")"
            else:
                if "url" in bib_database[cit]:
                    w=w+"<a href=\""+bib_database[cit]["url"]+"\">"+surnames+", "+bib_database[cit]["year"]+opt_thm_str+"</a>"
                else:
                    w=w+surnames+", "+bib_database[cit]["year"]+opt_thm_str
            if idx!=len(cit_list)-1:
                w=w+", "
            
        
        if flag != "t":
            w=w+")"
        # Keep the citation's generated HTML on one line.
        w=w.replace('\n', ' ').replace('\r', '')
    
    return w

# Conversion stages (orchestrated by main):
# 1. Select blog conditional branches, expand active inputs, and collect macros
#    and bibliography paths from the selected source, including its preamble.
# 2. Extract the body, expand document macros, protect escapes, and normalize
#    display delimiters before converting tables, citations, and fixed macros.
# 3. Separate math from prose; text handlers record section/theorem labels.
# 4. Number only referenced equation/align rows unless explicitly suppressed.
#    Register all equation labels before resolving references inside math.
# 5. Restore escapes and resolve prose references before reinserting math.
# 6. Generate explicit HTML paragraphs and optionally download formula images
#    for a preview with embedded math images.


def make_preview(content, title):
    """Embed WordPress-rendered formula images in an HTML preview."""
    formula_pattern = WORDPRESS_MATH_RE

    def request_key(match):
        parts = re.split(r'&(?=(?:fg|bg|s)=)', unescape(match.group()[7:-1]))
        options = {'bg': 'ffffff', 'fg': textcolor, 's': '1'}
        options.update(part.split('=', 1) for part in parts[1:])
        return parts[0], tuple(sorted(options.items()))

    def download(formula, options):
        url = 'https://s0.wp.com/latex.php?' + urlencode({'latex': formula, **dict(options)})
        try:
            with urlopen(url, timeout=30) as response:
                data = response.read()
        except OSError as error:
            raise ValueError(f'WordPress preview request failed for {formula!r}: {error}') from error
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        elif data.startswith((b'GIF87a', b'GIF89a')):
            mime = 'image/gif'
        else:
            raise ValueError(f'WordPress returned a non-image response for {formula!r}')
        return data, mime

    keys = list(dict.fromkeys(request_key(match) for match in formula_pattern.finditer(content)))
    rendered = {}
    if keys:
        print(f'Rendering {len(keys)} distinct formulas for the preview...', file=sys.stderr)
        # Parse failures can be returned as images too. Detect the service's
        # standard error image by comparing its response bytes.
        error_data, _ = download(r'\LatexTwoWordPressUndefinedCommand', ())
        with ThreadPoolExecutor(max_workers=4) as executor:
            pending = {executor.submit(download, *key): key for key in keys}
            for future in as_completed(pending):
                key = pending[future]
                data, mime = future.result()
                if data == error_data:
                    raise ValueError(f'WordPress could not render preview formula: {key[0]}')
                rendered[key] = (mime, base64.b64encode(data).decode('ascii'))
                if len(rendered) % 25 == 0 or len(rendered) == len(keys):
                    print(f'Rendered {len(rendered)}/{len(keys)} formulas', file=sys.stderr)

    def replace_formula(match):
        key = request_key(match)
        mime, data = rendered[key]
        return ('<img style="vertical-align:middle;max-width:100%;height:auto"'
                f' alt="{escape(key[0], quote=True)}" src="data:{mime};base64,{data}">')

    body = formula_pattern.sub(replace_formula, content)
    return ('<!doctype html>\n<html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(title)} — WordPress preview</title>'
            '<style>body{max-width:1100px;margin:40px auto;font:18px/1.6 Georgia;padding:0 20px}'
            'blockquote{border-left:3px solid #aaa;margin-left:0;padding-left:24px}'
            'img{background:white}</style></head><body>' + body + '</body></html>\n')


def same_file(first, second):
    return first.resolve() == second.resolve() or (
        first.exists() and second.exists() and first.samefile(second))


def main():
    global bibliography_paths, bib_database
    parser = argparse.ArgumentParser(description="Convert LaTeX to WordPress HTML")
    parser.add_argument("--version", action="version",
                        version=f"LaTeX2WP {__version__} (maintained fork; based on 0.6.2)")
    parser.add_argument("input", nargs="?", default="wpress.tex")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--preview", action="store_true",
                        help="also create OUTPUT_preview.html with embedded WordPress-rendered formulas (requires internet)")
    args = parser.parse_args()
    inputfile = Path(args.input)
    outputfile = Path(args.output) if args.output else inputfile.with_suffix(".html")
    if same_file(inputfile, outputfile):
        parser.error("Input and output must be different files")
    previewfile = outputfile.with_name(outputfile.stem + '_preview.html')
    if args.preview and (same_file(inputfile, previewfile) or same_file(outputfile, previewfile)):
        parser.error("Preview, input, and output must be different files")
    s = read_inputs(inputfile)
    bibliography_paths = find_bibliographies(s, inputfile)
    bib_database = None
    s, document_macros = collect_macros(s)
    title_match = re.search(r'\\title\s*(?=\{)', s)
    title = read_group(s, title_match.end())[0] if title_match else ''
    # Honor shared theorem counters declared by the source document.
    for environment, shared in re.findall(
            r'\\newtheorem\s*\{(\w+)\}\s*\[(\w+)\]', s):
        if environment in T and shared in T:
            T[environment] = T[shared]
    for key in count:
        count[key] = 0
    ref.clear()


    s=extractbody(s)
    s = re.sub(r'\\bibliography(?:style)?\s*\{[^{}]*\}', '', s)
    s = re.sub(r'\\appendix\b', '', s)
    s = expand_macros(s, document_macros)
    s = normalize_math_delimiters(protect_escapes(s))
    s = re.sub(r'\\maketitle\b',
               lambda _: '<h1>' + protect_escapes(expand_macros(title, document_macros)) + '</h1>'
               if title else '', s)

    # Convert table structure before restoring escaped ampersands.
    s=converttables(s)

    # Render author/year citations using the declared bibliographies.
    s=convertciteall(s)

    # Normalize optional labels/titles for the text command handlers.
    s=convertsqb(s)

    # Apply the fixed WordPress compatibility replacements from the style file.
    s=convertmacros(s)
    # Collect references throughout the selected body, including forward and
    # math-internal references, before assigning equation numbers.
    referenced_labels = {
        name.replace(':', '')
        for name in re.findall(r'\\(?:eqref|ref)\s*\{([^{}]+)\}', s)
    }

    # Protect math with placeholders while text handlers generate prose HTML.
    (math,text) = separatemath(s)

    s = text[0] + ''.join(f'__math{i}__' + text[i + 1] for i in range(len(math)))

    # Replace prose spacing markers without changing URLs or HTML attributes.
    s = re.sub(r'<[^>]*>|\\(?:url|href(?:nosnap)?)\s*\{[^{}]*\}|~',
               lambda m: ' ' if m.group() == '~' else m.group(), s)

    s = processtext(s)
    math = processmath(math, referenced_labels)

    # Restore prose entities and math escapes after table separators have been
    # parsed, so entity ampersands cannot be mistaken for column separators.

    for e in esc :
        s=s.replace(e[1],e[2])
        for i in range ( len ( math ) ) :
            math[i] = math[i].replace(e[1],e[3])

    # Resolve prose references while math is still protected by placeholders.
    s=convertref(s)

    # Reinsert the rendered math after prose references have been resolved.
    s = re.sub(r'__math(\d+)__', lambda match: math[int(match.group(1))], s)

    # Generate paragraph structure after combining prose and rendered math.
    s = render_paragraphs(s)

    if HTML :
        s="<head><style>body{max-width:55em;}a:link{color:#4444aa;}a:visited{color:#4444aa;}a:hover{background-color:#aaaaFF;}</style></head><body>"+s+"</body></html>"

    outputfile.write_text(s, encoding="utf-8")
    if args.preview:
        previewfile.write_text(make_preview(s, title or inputfile.stem), encoding="utf-8")
        print(f'Preview saved to {previewfile}', file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        sys.exit(f"Error: {error}")
