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

"""Select blog source, read local TeX inputs, and expand simple document macros.

Supported conditionals include the fixed blog/tex modes, true/false branches,
and simple booleans declared with newif. Command definitions are collected
document-wide; this is not a TeX interpreter with execution order and scoping.
"""
import re
from pathlib import Path


COMMAND = re.compile(r'\\(?:[A-Za-z]+|[^A-Za-z])')
DEFINITION = re.compile(r'\\(newcommand|renewcommand|providecommand|DeclareMathOperator|def)\b\*?\s*')


def strip_comments(source):
    """Remove unescaped percent comments while retaining line boundaries."""
    return re.sub(r'(?m)(?<!\\)((?:\\\\)*)%[^\n]*(?:\n|$)', r'\1\n', source)


def read_group(source, start, opening='{', closing='}'):
    """Read balanced delimiters, skipping TeX control sequences."""
    if start >= len(source) or source[start] != opening:
        raise ValueError(f'Expected {opening!r} near {source[start:start + 50]!r}')
    depth, pos = 1, start + 1
    while pos < len(source):
        if source[pos] == '\\':
            match = COMMAND.match(source, pos)
            pos = match.end() if match else pos + 1
            continue
        if source[pos] == opening:
            depth += 1
        elif source[pos] == closing:
            depth -= 1
            if depth == 0:
                return source[start + 1:pos], pos + 1
        pos += 1
    raise ValueError(f'Unclosed {opening!r} group')


class BlogSourceReader:
    """Select nested conditional branches and expand only active input files."""

    def __init__(self):
        self.conditions = {r'\ifblog': True, r'\iftex': False,
                           r'\iftrue': True, r'\iffalse': False}
        self.branches = []
        self.active = True

    def read(self, path, stack=()):
        path = Path(path).resolve()
        if path in stack:
            raise ValueError(f'Recursive TeX input: {path}')
        source = strip_comments(path.read_text(encoding='utf-8'))
        result, pos = [], 0
        while pos < len(source):
            match = COMMAND.search(source, pos)
            if match is None:
                if self.active:
                    result.append(source[pos:])
                break
            if self.active:
                result.append(source[pos:match.start()])
            command, pos = match.group(), match.end()
            if command == r'\newif':
                condition = COMMAND.match(source, skip_spaces(source, pos))
                if condition is None or not condition.group().startswith(r'\if'):
                    raise ValueError('Expected a conditional name after \\newif')
                pos = condition.end()
                if self.active:
                    self.conditions.setdefault(condition.group(), False)
            elif command in self.conditions:
                value = self.conditions[command]
                self.branches.append((self.active, value, False))
                self.active = self.active and value
            elif command == r'\else':
                if not self.branches:
                    raise ValueError('Unexpected \\else')
                parent, value, seen_else = self.branches[-1]
                if seen_else:
                    raise ValueError('Duplicate \\else in conditional')
                self.branches[-1] = parent, value, True
                self.active = parent and not value
            elif command == r'\fi':
                if not self.branches:
                    raise ValueError('Unexpected \\fi')
                self.active = self.branches.pop()[0]
            elif re.fullmatch(r'\\\w+(?:true|false)', command):
                toggle = re.fullmatch(r'\\(\w+?)(true|false)', command)
                condition = r'\if' + toggle.group(1)
                if condition in self.conditions:
                    # The document may select print mode for LaTeX compilation;
                    # conversion always keeps blog=true and tex=false.
                    if self.active and condition not in {r'\ifblog', r'\iftex'}:
                        self.conditions[condition] = toggle.group(2) == 'true'
                elif self.active:
                    result.append(command)
            elif command in {r'\input', r'\include'}:
                start = skip_spaces(source, pos)
                if source[start:start + 1] != '{':
                    if self.active:
                        result.append(command)
                    continue
                name, pos = read_group(source, start)
                if self.active:
                    name = name.strip()
                    if not name.endswith('.tex'):
                        name += '.tex'
                    result.append(self.read(path.parent / name, stack + (path,)))
            elif self.active:
                result.append(command)
        return ''.join(result)


def read_inputs(path):
    """Read braced input/include paths and require balanced conditionals."""
    reader = BlogSourceReader()
    source = reader.read(path)
    if reader.branches:
        raise ValueError('Unclosed TeX conditional (missing \\fi)')
    return source


def collect_macros(source):
    """Remove definitions and map commands to (argument count, default, body)."""
    macros, result, offset = {}, [], 0
    for match in DEFINITION.finditer(source):
        if match.start() < offset:
            continue
        pos = match.end()
        kind = match.group(1)
        if source[pos:pos + 1] == '{':
            name, pos = read_group(source, pos)
            name = name.strip()
        else:
            command = COMMAND.match(source, pos)
            if command is None:
                raise ValueError('Expected macro name after ' + match.group())
            name, pos = command.group(), command.end()
        pos = skip_spaces(source, pos)
        nargs, default = 0, None
        if kind == 'def':
            start = pos
            while pos < len(source) and source[pos] != '{':
                pos += 1
            parameters = source[start:pos].strip()
            if not re.fullmatch(r'(?:#[1-9])*', parameters):
                raise ValueError(f'Delimited macro arguments are unsupported: {name}')
            nargs = len(parameters) // 2
        elif kind != 'DeclareMathOperator' and source[pos:pos + 1] == '[':
            count, pos = read_group(source, pos, '[', ']')
            nargs = int(count)
            pos = skip_spaces(source, pos)
            if source[pos:pos + 1] == '[':
                default, pos = read_group(source, pos, '[', ']')
        pos = skip_spaces(source, pos)
        body, end = read_group(source, pos)
        if kind == 'DeclareMathOperator':
            body = r'\mathop{\mathrm{' + body + '}}' + ('' if '*' in match.group() else r'\nolimits')
        # These commands have special meanings in the WordPress converter.
        if name not in {r'\image', r'\more', r'\em', r'\emph'}:
            if kind != 'providecommand' or name not in macros:
                macros[name] = (nargs, default, body)
        result.append(source[offset:match.start()])
        offset = end
    return ''.join(result) + source[offset:], macros


def skip_spaces(source, pos):
    while pos < len(source) and source[pos].isspace():
        pos += 1
    return pos


def expand_macros(source, macros, active=()):
    """Expand collected commands recursively, retaining unknown commands."""
    result, pos = [], 0
    while pos < len(source):
        match = COMMAND.search(source, pos)
        if match is None:
            result.append(source[pos:])
            break
        result.append(source[pos:match.start()])
        name, pos = match.group(), match.end()
        if name not in macros:
            result.append(name)
            continue
        if name in active or len(active) > 100:
            raise ValueError('Recursive macro expansion: ' + ' -> '.join(active + (name,)))
        nargs, default, body = macros[name]
        arguments = []
        if default is not None:
            pos = skip_spaces(source, pos)
            if source[pos:pos + 1] == '[':
                arg, pos = read_group(source, pos, '[', ']')
            else:
                arg = default
            arguments.append(arg)
        while len(arguments) < nargs:
            pos = skip_spaces(source, pos)
            if pos >= len(source):
                raise ValueError(f'Missing argument for {name}')
            if source[pos] == '{':
                arg, pos = read_group(source, pos)
            elif source[pos] == '\\':
                command = COMMAND.match(source, pos)
                arg, pos = command.group(), command.end()
            else:
                arg, pos = source[pos], pos + 1
            arguments.append(arg)
        arguments = [expand_macros(arg, macros, active) for arg in arguments]
        body = re.sub(r'#([1-9])', lambda m: arguments[int(m.group(1)) - 1], body)
        result.append(expand_macros(body, macros, active + (name,)))
    return ''.join(result)
