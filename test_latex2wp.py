# Copyright (C) 2026 Francesco Orabona
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This file is part of LaTeX2WP.
#
# LaTeX2WP is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# LaTeX2WP is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with LaTeX2WP. If not, see <https://www.gnu.org/licenses/>.

"""Regression checks for conversion and source-file protection."""
import os
import re
import base64
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from latex2wp import convertmacros, make_preview
from latex2wp_html import WORDPRESS_MATH_RE, render_paragraphs

SCRIPT = Path(__file__).with_name('latex2wp.py').resolve()


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='latex2wp-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'post.tex'
        self.output = self.root / 'post.html'
        self.bib = self.root / 'refs.bib'
        self.bib.write_text('@article{known, author={Smith, Alice}, year={2024}}')

    def convert(self, source):
        self.source.write_text(source, encoding='utf-8')
        result = subprocess.run(
            [sys.executable, '-B', str(SCRIPT), str(self.source),
             str(self.output)],
            cwd='/tmp', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.output.read_text(encoding='utf-8'), result.stderr

    def test_extensionless_input_is_preserved(self):
        source = self.root / 'draft'
        source.write_text('$x$')
        result = subprocess.run([sys.executable, '-B', str(SCRIPT), str(source)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_text(), '$x$')
        self.assertTrue(source.with_suffix('.html').exists())

    def test_same_output_and_hardlink_are_rejected(self):
        self.source.write_text('$x$')
        linked = self.root / 'linked.html'
        os.link(self.source, linked)
        for output in [self.source, linked]:
            result = subprocess.run([sys.executable, '-B', str(SCRIPT),
                                     str(self.source), str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('must be different', result.stderr)
            self.assertEqual(self.source.read_text(), '$x$')

    def test_align_labels_preserve_expression_and_numbering(self):
        html, _ = self.convert(
            r'\begin{align}a&=b\label{eq:a}+c\\d&=e\label{eq:b}\end{align}'
            r'\eqref{eq:a},\eqref{eq:b}')
        self.assertIn('a&=b+c', html)
        self.assertIn('href="#eqa">(1)', html)
        self.assertIn('href="#eqb">(2)', html)
        self.assertNotIn(r'\label', html)
        self.assertNotIn(r'\\\end{aligned}', html)
        self.assertIn('name="eqb"', html)

    def test_single_row_align_and_equation(self):
        for environment in ['align', 'equation']:
            with self.subTest(environment=environment):
                html, _ = self.convert(
                    '\\begin{' + environment + r'}a=b\label{eq:x}+c\end{'
                    + environment + r'}\eqref{eq:x}')
                self.assertIn('a=b+c', html)
                self.assertIn('href="#eqx">(1)', html)
                self.assertNotIn(r'\label', html)

    def test_parenthesis_math_matches_dollar_math_and_stays_inline(self):
        expected, _ = self.convert(r'Before $a=\frac{b}{c}$ after.')
        actual, _ = self.convert(r'Before \(a=\frac{b}{c}\) after.')
        self.assertEqual(actual, expected)
        self.assertNotIn('<p align=center>', actual)

    def test_parenthesis_math_inside_theorem_preserves_emphasis(self):
        expected, _ = self.convert(r'\begin{theorem}For $x>0$, this holds.\end{theorem}')
        actual, _ = self.convert(r'\begin{theorem}For \(x>0\), this holds.\end{theorem}')
        self.assertEqual(actual, expected)

    def test_equation_star_is_displayed_without_affecting_numbering(self):
        html, _ = self.convert(
            r'\begin{equation*}a=\frac{b}{c}\end{equation*}'
            r'\begin{equation}x=y\label{eq:x}\end{equation}\eqref{eq:x}')
        self.assertIn(r'<p align=center>$latex \displaystyle a=\frac{b}{c}&fg=', html)
        self.assertNotIn(r'\begin{equation', html)
        self.assertEqual(html.count(r'\quad (1)'), 1)
        self.assertNotIn('(2)', html)
        self.assertIn('href="#eqx">(1)', html)

    def test_notag_and_nonumber_preserve_terms(self):
        html, _ = self.convert(
            r'\begin{align}a&=b\notag+c\\d&=e\nonumber+f\\'
            r'g&=h\label{eq:h}\\\end{align}\eqref{eq:h}')
        self.assertIn('a&=b+c', html)
        self.assertIn('d&=e+f', html)
        self.assertIn('href="#eqh">(1)', html)
        self.assertNotIn('(2)', html)
        self.assertNotIn(r'\notag', html)
        self.assertNotIn(r'\nonumber', html)

    def test_nested_matrix_rows_do_not_increment_outer_counter(self):
        html, _ = self.convert(
            r'\begin{align}A&=\begin{matrix}a&b\\c&d\end{matrix}\label{eq:a}'
            r'\\B&=C\label{eq:b}\end{align}\eqref{eq:a},\eqref{eq:b}')
        self.assertIn('href="#eqb">(2)', html)

    def test_only_referenced_equations_are_numbered_consecutively(self):
        html, stderr = self.convert(
            r'See \eqref{eq:first} and \ref{eq:last}.'
            r'\begin{equation}a=b\end{equation}'
            r'\begin{equation}c=d\label{unused}\end{equation}'
            r'\begin{equation}e=f\label{eq:first}\label{alias}\end{equation}'
            r'\begin{align}g&=h\label{unused-row}\\i&=j\label{eq:last}\end{align}')
        self.assertIn('href="#eqfirst">(1)', html)
        self.assertIn('href="#eqlast">2</a>', html)
        self.assertEqual(html.count(r'\quad (1)'), 1)
        self.assertEqual(html.count(' & (2)'), 1)
        self.assertNotIn('(3)', html)
        self.assertNotIn('name="unused', html)
        self.assertIn('g&=h', html)
        self.assertNotIn('unresolved reference', stderr)

    def test_commented_and_excluded_references_do_not_trigger_numbers(self):
        html, _ = self.convert(
            '% \\eqref{eq:x}\n'
            r'\iftex\ref{eq:x}\fi'
            r'\begin{equation}x=y\label{eq:x}\end{equation}')
        self.assertNotIn(r'\quad (', html)
        self.assertNotIn('name="eqx"', html)
        self.assertIn('x=y', html)

    def test_nested_headings_and_subsection_labels(self):
        html, _ = self.convert(
            r'\section{A \emph{useful} title}\subsection{B \textbf{bold}}'
            r'\label{sec:b}\subsection*{Aside}\subsection{C}\label{sec:c}'
            r'\ref{sec:b},\ref{sec:c}')
        self.assertIn('A <em>useful</em> title', html)
        self.assertIn('B <b>bold</b>', html)
        self.assertIn('href="#secb">1.1', html)
        self.assertIn('href="#secc">1.2', html)

    def test_trailing_comment_and_escaped_percent(self):
        html, _ = self.convert('Keep 50\\%. % remove me')
        self.assertIn('50&#37;', html)
        self.assertNotIn('remove me', html)

    def test_bordered_table_with_short_row_and_final_break(self):
        html, _ = self.convert(r'\begin{tabular}{|l|r|}\hline a&b\\c\\\hline\end{tabular}')
        self.assertIn('border="1"', html)
        self.assertEqual(html.count('<tr>'), 2)
        self.assertEqual(html.count('<td '), 4)
        self.assertIn('<td align="right"></td>', html)

    def test_btabular_has_rows(self):
        html, _ = self.convert(r'\begin{btabular}{lr}a&b\end{btabular}')
        self.assertIn('><tr><td', html)

    def test_theorem_and_lemma_do_not_add_empty_paragraphs_or_emphasis(self):
        for environment in ['theorem', 'lemma', 'definition', 'proposition',
                            'corollary', 'claim', 'remark', 'example', 'exercise']:
            with self.subTest(environment=environment):
                html, _ = self.convert(
                    'Before.\n\n\\begin{' + environment + '}'
                    r'Claim.\[x=y\]'
                    '\\end{' + environment + '}\n\nAfter.')
                self.assertNotRegex(html, r'<p>\s*<p>')
                self.assertNotRegex(html, r'<p>\s*<blockquote>')
                self.assertNotRegex(html, r'<em>\s*</em>')
                self.assertIn('Claim.', html)
                self.assertIn('After.', html)

    def test_theorem_and_proof_headings_share_the_first_body_paragraph(self):
        for environment, heading in [('lemma', 'Lemma 1.'), ('proof', 'Proof:')]:
            with self.subTest(environment=environment):
                html, _ = self.convert(
                    '\\begin{' + environment + '}\n\nFirst sentence.\n\n'
                    'Second paragraph.\n\n\\end{' + environment + '}')
                first_paragraph = html[html.index('<p>'):html.index('</p>')]
                self.assertIn(heading, first_paragraph)
                self.assertIn('First sentence.', first_paragraph)
                self.assertIn('Second paragraph.', html)
                self.assertNotIn('<latex2wp-', html)

    def test_blank_lines_at_environment_boundaries_do_not_add_empty_blocks(self):
        cases = {environment: 'Content.' for environment in
                 ['proof', 'quote', 'center', 'red', 'green', 'blue']}
        cases.update({
            'itemize': r'\item First.\item Second.',
            'enumerate': r'\item First.\item Second.',
            'tabular': r'a&b\\c&d',
            'btabular': r'a&b\\c&d',
            'equation': 'x=y',
            'align': r'x&=y\\z&=w',
            'align*': r'x&=y\\z&=w',
        })
        for environment, content in cases.items():
            with self.subTest(environment=environment):
                columns = '{lr}' if environment in ['tabular', 'btabular'] else ''
                html, _ = self.convert(
                    'Before.\n\n\\begin{' + environment + '}' + columns
                    + '\n\n' + content + '\n\n\\end{' + environment + '}\n\nAfter.')
                self.assertNotRegex(html, r'<p>\s*(?:</?(?:p|ul|ol|li|div|blockquote|table|tr|td)\b|$)')
                self.assertIn('Before.', html)
                self.assertIn('After.', html)
                for formula in re.findall(r'\$latex (.*?)\$', html, re.S):
                    self.assertNotIn('<p>', formula)

    def test_center_and_color_blocks_preserve_multiple_paragraphs(self):
        for environment, style in [('center', 'text-align: center;'), ('red', 'color:#ff0000;')]:
            with self.subTest(environment=environment):
                html, _ = self.convert(
                    '\\begin{' + environment + '}\n\nFirst.\n\nSecond.\n\n\\end{'
                    + environment + '}')
                self.assertIn('<div style="' + style + '">', html)
                self.assertIn('First.', html)
                self.assertIn('Second.', html)
                self.assertIn('<p>', html)
                self.assertNotRegex(html, r'<p>\s*</div>')

    def test_missing_citation_is_visible_and_warns(self):
        html, stderr = self.convert(r'\cite{missing,known}\bibliography{refs}')
        self.assertIn('[missing citation: missing]', html)
        self.assertIn('Smith, 2024', html)
        self.assertIn("missing or incomplete citation 'missing'", stderr)

    def test_no_citations_needs_no_bibliography(self):
        html, _ = self.convert('No citations.')
        self.assertIn('No citations.', html)

    def test_missing_bibliography_preserves_existing_output(self):
        self.source.write_text(r'\cite{known}\bibliography{absent}')
        self.output.write_text('Existing output')
        result = subprocess.run(
            [sys.executable, '-B', str(SCRIPT), str(self.source),
             str(self.output)],
            cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Cannot load bibliography', result.stderr)
        self.assertEqual(self.output.read_text(), 'Existing output')

    def test_bibliography_in_preamble_and_multiple_files(self):
        directory = self.root / 'bibliographies'
        directory.mkdir()
        (directory / 'other.bib').write_text(
            '@article{other, author={Jones, Bob}, year={2025}}')
        html, stderr = self.convert(
            '% \\bibliography{absent}\n'
            r'\bibliography{ refs.bib, bibliographies/other }'
            r'\begin{document}\cite{known,other}\end{document}')
        self.assertIn('Smith, 2024', html)
        self.assertIn('Jones, 2025', html)
        self.assertNotIn('missing citation', stderr)
        self.assertNotIn(r'\bibliography', html)

    def test_missing_declaration_has_clear_error(self):
        self.source.write_text(r'\cite{known}')
        result = subprocess.run(
            [sys.executable, '-B', str(SCRIPT), str(self.source), str(self.output)],
            cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(r'\bibliography{path}', result.stderr)
        self.assertFalse(self.output.exists())

    def test_unresolved_reference_warns(self):
        html, stderr = self.convert(r'See \ref{missing}.')
        self.assertIn('See ??.', html)
        self.assertIn('unresolved reference', stderr)

    def test_macros_from_recursive_inputs_and_local_operators(self):
        (self.root / 'numbers.tex').write_text(
            r'\newcommand{\field}[1]{\mathbb{#1}}\newcommand{\R}{\field{R}}')
        (self.root / 'symbols.tex').write_text(
            '% Ignored: \\newcommand{\\bP}{wrong}\n'
            r'\input{numbers}\newcommand{\bP}{\boldsymbol{P}}'
            r'\newcommand\norm[1]{\left\|#1\right\|}')
        html, _ = self.convert(
            r'\input{symbols}\DeclareMathOperator{\range}{range}'
            r'\begin{document}$\norm{\bP}\in\R;\range(\bP)$\end{document}')
        self.assertIn(r'\left\|\boldsymbol{P}\right\|\in\mathbb{R}', html)
        self.assertIn(r'\mathop{\mathrm{range}}\nolimits(\boldsymbol{P})', html)
        for command in [r'\bP', r'\norm', r'\range', r'\field', r'\input']:
            self.assertNotIn(command, html)

    def test_link_labels_preserve_nested_formatting_and_escape_url_attributes(self):
        for command in ['href', 'hrefnosnap']:
            with self.subTest(command=command):
                html, _ = self.convert(
                    '\\' + command + r'{https://example.com/?a=1&b="two"}'
                    r'{\textbf{Click \emph{here}}}')
                self.assertIn('<b>Click <em>here</em></b></a>', html)
                self.assertIn('href="https://example.com/?a=1&amp;b=&quot;two&quot;"', html)
                self.assertNotIn(r'\textbf', html)

    def test_formatted_link_labels_can_include_inline_math(self):
        html, _ = self.convert(
            r'\href{https://example.com}{\textbf{For $x>0$, \emph{read this}}}')
        self.assertIn('<b>For $latex {x&gt;0}&fg=000000$, <em>read this</em></b></a>', html)
        self.assertEqual(len(WORDPRESS_MATH_RE.findall(html)), 1)

    def test_references_in_link_labels_do_not_create_nested_anchors(self):
        html, _ = self.convert(
            r'\href{https://example.com}{\textbf{Equation \eqref{eq:x}}}'
            r'\begin{equation}x=y\label{eq:x}\end{equation}')
        self.assertIn('<a href="https://example.com"><b>Equation (1)</b></a>', html)
        self.assertEqual(html.count('<a href='), 1)

    def test_currency_macro_does_not_corrupt_following_equations(self):
        html, _ = self.convert(
            r'\newcommand{\money}{\$}\begin{document}'
            r'\money 10 and $x$, then \money 20 and \(y\).\end{document}')
        self.assertIn('&#36; 10', html)
        self.assertIn('&#36; 20', html)
        self.assertEqual(WORDPRESS_MATH_RE.findall(html),
                         ['$latex {x}&fg=000000$', '$latex {y}&fg=000000$'])

    def test_macro_escaped_symbols_work_inside_math_and_prose(self):
        html, _ = self.convert(
            r'\newcommand{\symbols}{\$\%\&}\begin{document}'
            r'\symbols $\text{\symbols}$ and $x$.\end{document}')
        self.assertIn('&#36;&#37;&amp;', html)
        formulas = WORDPRESS_MATH_RE.findall(html)
        self.assertEqual(len(formulas), 2)
        self.assertIn(r'\text{\$\%\&}', formulas[0])
        self.assertNotIn('_dollar_', html)

    def test_excluded_definitions_do_not_change_blog_macros(self):
        html, _ = self.convert(
            r'\newcommand{\myvalue}{Original}'
            r'\iftex\renewcommand{\myvalue}{Print}\fi'
            r'\iffalse\renewcommand{\myvalue}{Hidden}\fi'
            r'\begin{document}$\myvalue$\end{document}')
        self.assertIn('$latex {Original}&fg=000000$', html)
        self.assertNotIn('Print', html)
        self.assertNotIn('Hidden', html)

    def test_nested_blog_conditionals_and_else_select_the_correct_text(self):
        html, _ = self.convert(
            r'Before \ifblog Blog \iffalse Hidden \else Visible \fi'
            r'\iftex Print \else Online \fi EndBlog \else Offline \fi After')
        self.assertIn('Before Blog Visible Online EndBlog After', html)
        for excluded in ['Hidden', 'Print', 'Offline', r'\else', r'\fi']:
            self.assertNotIn(excluded, html)

    def test_skipped_inputs_are_not_read_and_included_definitions_are_filtered(self):
        (self.root / 'blog.tex').write_text(
            r'\newcommand{\myvalue}{Blog}'
            r'\iftex\renewcommand{\myvalue}{Print}\else'
            r'\renewcommand{\myvalue}{Online}\fi')
        html, _ = self.convert(
            r'\iftex\input{missing-print-file}\else\input{blog}\fi'
            r'\begin{document}$\myvalue$\end{document}')
        self.assertIn('$latex {Online}&fg=000000$', html)

    def test_source_print_mode_switches_do_not_disable_blog_output(self):
        html, _ = self.convert(
            r'\newif\ifblog\newif\iftex\blogfalse\textrue'
            r'\begin{document}\ifblog Online\else Print\fi\end{document}')
        self.assertIn('Online', html)
        self.assertNotIn('Print', html)

    def test_malformed_conditional_fails_clearly(self):
        self.source.write_text(r'Before \ifblog Missing ending')
        result = subprocess.run(
            [sys.executable, '-B', str(SCRIPT), str(self.source), str(self.output)],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing \\fi', result.stderr)

    def test_forward_references_inside_math_are_plain_tex_numbers(self):
        html, stderr = self.convert(
            r'$x_{\ref{eq:a}}$ and \eqref{eq:a}.'
            r'\begin{equation}a=b\label{eq:a}\end{equation}'
            r'\begin{align*}x&=y\quad\text{by \eqref{eq:a}}\end{align*}')
        formulas = WORDPRESS_MATH_RE.findall(html)
        self.assertIn('$latex {x_{1}}&fg=000000$', formulas)
        self.assertIn(r'\text{by (1)}', formulas[-1])
        self.assertTrue(all('<a' not in formula for formula in formulas))
        self.assertIn('href="#eqa">(1)</a>', html)
        self.assertNotIn('unresolved reference', stderr)

    def test_math_references_to_later_equations_and_prose_labels(self):
        html, _ = self.convert(
            r'\section{Introduction}\label{sec:intro}'
            r'\begin{equation}x=\ref{eq:next}+\ref{sec:intro}\label{eq:first}\end{equation}'
            r'\begin{equation}y=\eqref{eq:first}\label{eq:next}\end{equation}')
        formulas = WORDPRESS_MATH_RE.findall(html)
        self.assertIn('x=2+1', formulas[0])
        self.assertIn('y=(1)', formulas[1])
        self.assertTrue(all('<a' not in formula for formula in formulas))

    def test_def_and_optional_macro_arguments(self):
        html, _ = self.convert(
            r'\def\pair#1#2{\langle #1,#2\rangle}'
            r'\newcommand{\norm}[2][2]{\|#2\|_{#1}}'
            r'\begin{document}$\pair{x}{y};\norm{x};\norm[1]{y}$\end{document}')
        self.assertIn(r'\langle x,y\rangle;\|x\|_{2};\|y\|_{1}', html)

    def test_recursive_macro_has_clear_error(self):
        self.source.write_text(r'\newcommand{\loop}{\loop}\begin{document}$\loop$\end{document}')
        result = subprocess.run(
            [sys.executable, '-B', str(SCRIPT), str(self.source), str(self.output)],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Recursive macro expansion', result.stderr)

    def test_nested_calls_to_same_macro_are_not_recursive_definitions(self):
        html, _ = self.convert(
            r'\newcommand{\norm}[1]{\|#1\|}'
            r'\begin{document}$\norm{\norm{x}}$\end{document}')
        self.assertIn(r'\|\|x\|\|', html)

    def test_title_urls_and_bibliography_commands(self):
        html, _ = self.convert(
            r'\title{Example}\begin{document}\maketitle'
            r'\url{https://example.com/~alice}\appendix'
            r'\bibliographystyle{plainnat}\bibliography{refs}\end{document}')
        self.assertIn('<h1>Example</h1>', html)
        self.assertIn('href="https://example.com/~alice"', html)
        self.assertNotIn(r'\url', html)
        self.assertNotIn(r'\appendix', html)
        self.assertNotIn(r'\bibliographystyle', html)

    def test_multiline_bibtex_names_and_url_tildes(self):
        self.bib.write_text('@article{known, author={Alice Smith and\nBob Jones and\nCarol Miller}, year={2024}, url={https://example.com/~alice}}')
        html, _ = self.convert(r'\cite{known}\bibliography{refs}')
        self.assertIn('Smith et al., 2024', html)
        self.assertIn('href="https://example.com/~alice"', html)

    def test_preview_cli_creates_separate_file_without_changing_output(self):
        expected, _ = self.convert('A paragraph.')
        result = subprocess.run(
            [sys.executable, '-B', str(SCRIPT), str(self.source),
             str(self.output), '--preview'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(), expected)
        preview = self.root / 'post_preview.html'
        self.assertIn('<!doctype html>', preview.read_text())
        self.assertIn('A paragraph.', preview.read_text())

    def test_preview_cannot_overwrite_input(self):
        source = self.root / 'post_preview.html'
        source.write_text('Original source')
        result = subprocess.run(
            [sys.executable, '-B', str(SCRIPT), str(source),
             str(self.output), '--preview'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must be different', result.stderr)
        self.assertEqual(source.read_text(), 'Original source')


class PreviewTests(unittest.TestCase):
    image = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
    error_image = b'GIF89aWordPress parse error'

    def test_preview_embeds_deduplicated_images_and_decodes_entities(self):
        requests = []

        def response(url, timeout):
            query = parse_qs(urlsplit(url).query)
            requests.append(query)
            return BytesIO(self.error_image if 'UndefinedCommand' in query['latex'][0] else self.image)

        with patch('latex2wp.urlopen', side_effect=response):
            html = make_preview(
                '<p>$latex x&lt;y&fg=123456$ and $latex x&lt;y&fg=123456$</p>',
                'An <example>')
        formulas = [q for q in requests if q['latex'] == ['x<y']]
        self.assertEqual(len(formulas), 1)
        self.assertEqual(formulas[0]['fg'], ['123456'])
        self.assertEqual(html.count('src="data:image/png;base64,'), 2)
        self.assertIn('An &lt;example&gt;', html)
        self.assertNotIn('$latex', html)

    def test_renderer_error_images_and_non_images_fail_clearly(self):
        for bad_response in [self.error_image, b'<html>Service unavailable</html>']:
            with self.subTest(response=bad_response):
                def response(url, timeout):
                    if 'UndefinedCommand' in parse_qs(urlsplit(url).query)['latex'][0]:
                        return BytesIO(self.error_image)
                    return BytesIO(bad_response)
                with patch('latex2wp.urlopen', side_effect=response):
                    with self.assertRaisesRegex(ValueError, 'could not render|non-image'):
                        make_preview('$latex invalid&fg=000000$', 'Example')

    def test_network_failure_is_reported_with_formula(self):
        def response(url, timeout):
            if 'UndefinedCommand' in parse_qs(urlsplit(url).query)['latex'][0]:
                return BytesIO(self.error_image)
            raise OSError('Connection unavailable')
        with patch('latex2wp.urlopen', side_effect=response):
            with self.assertRaisesRegex(ValueError, "request failed for 'x'"):
                make_preview('$latex x&fg=000000$', 'Example')


class ParagraphTests(unittest.TestCase):
    def test_prose_has_explicit_paragraphs_without_empty_boundary_paragraphs(self):
        self.assertEqual(render_paragraphs('\n\nFirst.\n\nSecond.\n\n'),
                         '<p>First.</p>\n<p>Second.</p>\n')

    def test_emphasis_is_reopened_inside_paragraphs_and_display_blocks(self):
        html = render_paragraphs(
            '<blockquote><b>Lemma.</b> <em>First.\n\nSecond.'
            '<p align="center">$latex x=y&fg=000000$</p>Last.</em></blockquote>')
        self.assertIn('<p><b>Lemma.</b> <em>First.</em></p>', html)
        self.assertIn('<p><em>Second.</em></p>', html)
        self.assertIn('<p align="center"><em>$latex x=y&fg=000000$</em></p>', html)
        self.assertIn('<p><em>Last.</em></p>', html)
        self.assertNotRegex(html, r'<em>\s*<p')

    def test_nested_list_items_close_without_paragraphs_for_tight_lists(self):
        html = render_paragraphs('<ul><li>First.<ol><li>Nested.</ol><li>Second.</ul>')
        self.assertEqual(html.count('<li>'), 3)
        self.assertEqual(html.count('</li>'), 3)
        self.assertNotIn('<p>', html)
        self.assertIn('Nested.</li>\n</ol>\n</li>', html)

    def test_formula_entities_and_escaped_dollars_are_not_parsed_as_html(self):
        formula = r'$latex {\text{\$5}\quad x&lt;y}&fg=000000$'
        html = render_paragraphs('Cost: ' + formula + ' and &amp;.')
        self.assertIn(formula, html)
        self.assertIn(' and &amp;.</p>', html)

    def test_trailing_labels_do_not_create_empty_paragraphs(self):
        html = render_paragraphs('<a name="eqx"></a><p align="center">$latex x$</p>')
        self.assertTrue(html.startswith('<a name="eqx"></a><p align="center">'))
        self.assertEqual(html.count('<p'), 1)

    def test_proof_square_joins_last_paragraph_even_after_source_blank_line(self):
        html = render_paragraphs('Last sentence.\n\n<span class="qed">$latex \\Box$</span>\n\nAfter.')
        self.assertIn('Last sentence.<span class="qed">$latex \\Box$</span></p>', html)
        self.assertIn('<p>After.</p>', html)


class CommandDispatchTests(unittest.TestCase):
    def test_macro_lookup_preserves_ordered_aliases_and_duplicate_rules(self):
        rules = [(r'\first', r'\second'), (r'\first', 'unused'), (r'\second', 'expanded')]
        with patch('latex2wp.M', rules):
            self.assertEqual(convertmacros(r'\first \second \firstExtra'),
                             r'expanded expanded \firstExtra')

    def test_macro_lookup_preserves_line_breaks_and_escaped_commands(self):
        self.assertEqual(convertmacros(r'\\E\E'), r'\\E\mathop{\mathbb E}')


if __name__ == '__main__':
    unittest.main()
