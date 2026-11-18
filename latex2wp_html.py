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

"""Generate explicit HTML paragraphs from prose and block elements."""
import re
from html.parser import HTMLParser


WORDPRESS_MATH_RE = re.compile(r'\$latex (?:\\.|[^\\$])*\$', re.S)


class ParagraphWriter(HTMLParser):
    """Keep paragraph boundaries separate from inline formatting and math.

    Inline tags are opened lazily and reopened inside subsequent paragraphs.
    This also lets display equations interrupt emphasized theorem text without
    putting block elements inside an emphasis tag.
    """

    block_tags = {'blockquote', 'div', 'ul', 'ol', 'li', 'table', 'thead',
                  'tbody', 'tfoot', 'tr', 'td', 'th', 'h1', 'h2', 'h3',
                  'h4', 'h5', 'h6', 'pre', 'hr'}
    compact_tags = {'li', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
    void_tags = {'img', 'br', 'hr', 'input', 'meta', 'link', 'wbr'}

    def __init__(self, formulas):
        super().__init__(convert_charrefs=False)
        self.formulas = formulas
        self.output = []
        self.buffer = []
        self.has_content = False
        self.pending_break = False
        self.explicit_paragraph = None
        self.containers = []
        self.inline = []
        self.empty_anchor = False
        self.initial_body = False

    def open_inline(self):
        for frame in self.inline:
            if not frame['open']:
                self.buffer.append(frame['markup'])
                frame['open'] = True

    def flush(self, reason='block'):
        for frame in reversed(self.inline):
            if frame['open']:
                self.buffer.append('</' + frame['tag'] + '>')
                frame['open'] = False
        content = ''.join(self.buffer).strip()
        if self.has_content:
            container = self.containers[-1] if self.containers else None
            compact = container is not None and container['tag'] in self.compact_tags
            if reason == 'paragraph' and container is not None:
                container['paragraphs'] = True
            wrap = (self.explicit_paragraph is not None or not compact
                    or (container is not None and container['paragraphs']))
            if wrap:
                self.output.extend([self.explicit_paragraph or '<p>', content, '</p>\n'])
            else:
                self.output.append(content)
        elif content:
            # Labels may stand alone immediately before a display equation.
            self.output.append(content)
        self.buffer = []
        self.has_content = False
        self.pending_break = False
        self.initial_body = False

    def append_content(self, content):
        if self.pending_break:
            self.flush('paragraph')
        self.initial_body = False
        self.open_inline()
        self.buffer.append(content)
        self.has_content = True

    def handle_data(self, data):
        for part in re.split(r'(\n[ \t]*\n(?:[ \t]*\n)*)', data):
            if re.fullmatch(r'\n[ \t]*\n(?:[ \t]*\n)*', part):
                self.pending_break = self.has_content and not self.initial_body
            elif part.strip():
                self.append_content(re.sub(r'\s+', ' ', part))
            elif self.has_content and not self.pending_break:
                self.buffer.append(' ')

    def handle_starttag(self, tag, attrs):
        markup = self.get_starttag_text()
        attributes = dict(attrs)
        if tag == 'latex2wp-body':
            # A theorem/proof heading shares its paragraph with the body.
            self.initial_body = True
        elif tag == 'latex2wp-math':
            self.append_content(self.formulas[int(attributes['data-index'])])
        elif tag == 'p':
            self.flush()
            self.explicit_paragraph = markup
        elif tag in self.block_tags:
            if tag == 'li' and self.containers and self.containers[-1]['tag'] == 'li':
                self.handle_endtag('li')
            self.flush()
            self.explicit_paragraph = None
            self.output.append(markup)
            if tag not in self.void_tags:
                self.containers.append({'tag': tag, 'paragraphs': False})
        elif tag in self.void_tags:
            self.append_content(markup)
        elif tag == 'a' and 'href' not in attributes:
            self.buffer.append(markup + '</a>')
            self.empty_anchor = True
        else:
            if 'qed' in attributes.get('class', '').split():
                # A proof's closing square belongs to its final text paragraph,
                # even if the source has blank lines before the end delimiter.
                self.pending_break = False
            self.inline.append({'tag': tag, 'markup': markup, 'open': False})

    def handle_endtag(self, tag):
        if tag in {'latex2wp-math', 'latex2wp-body'}:
            return
        if tag == 'a' and self.empty_anchor:
            self.empty_anchor = False
        elif tag == 'p':
            self.flush()
            self.explicit_paragraph = None
        elif tag in self.block_tags:
            if tag in {'ul', 'ol'} and self.containers and self.containers[-1]['tag'] == 'li':
                self.handle_endtag('li')
            self.flush()
            self.explicit_paragraph = None
            if self.containers and self.containers[-1]['tag'] == tag:
                self.containers.pop()
            self.output.append('</' + tag + '>\n')
        else:
            for index in range(len(self.inline) - 1, -1, -1):
                if self.inline[index]['tag'] == tag:
                    for frame in reversed(self.inline[index:]):
                        if frame['open']:
                            self.buffer.append('</' + frame['tag'] + '>')
                    del self.inline[index:]
                    break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void_tags:
            self.handle_endtag(tag)

    def handle_entityref(self, name):
        self.append_content('&' + name + ';')

    def handle_charref(self, name):
        self.append_content('&#' + name + ';')

    def handle_comment(self, data):
        self.flush()
        self.output.append('<!--' + data + '-->')

    def finish(self):
        self.close()
        self.flush()
        return ''.join(self.output)


def render_paragraphs(content):
    """Render blank-line paragraph breaks while keeping formulas opaque."""
    formulas = []

    def protect(match):
        formulas.append(match.group())
        return f'<latex2wp-math data-index="{len(formulas) - 1}"></latex2wp-math>'

    writer = ParagraphWriter(formulas)
    writer.feed(WORDPRESS_MATH_RE.sub(protect, content))
    return writer.finish()
