"""Bounded LaTeX subset parser and editable Office Math serializer.

This is deliberately not a TeX interpreter. Unknown commands, malformed groups,
and excessive nesting fail before publishing. No macros, files or shell escapes
are executed. See NATIVE_NOTICE.md and docs/native-exporter.md.
"""
from dataclasses import dataclass
from functools import wraps
import re
from native_common import NativeExportError, color, node, number

SYMBOLS = dict(zip(
    'alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi pi rho sigma tau upsilon phi chi psi omega'.split(),
    'αβγδεζηθικλμνξπρστυφχψω'))
SYMBOLS.update(dict(zip('Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega'.split(), 'ΓΔΘΛΞΠΣΥΦΨΩ')))
SYMBOLS.update(times='×', cdot='·', pm='±', mp='∓', le='≤', leq='≤', ge='≥', geq='≥',
               ne='≠', neq='≠', approx='≈', infty='∞', partial='∂', nabla='∇',
               to='→', rightarrow='→', leftarrow='←', in_='∈', notin='∉', forall='∀', exists='∃')
SYMBOLS['in'] = SYMBOLS.pop('in_')

SYMBOLS.update(dict(zip('varepsilon vartheta varpi varrho varsigma varphi'.split(), 'ϵϑϖϱςϕ')))
SYMBOLS.update(
    parallel='∥', nparallel='∦', perp='⊥', mid='∣', nmid='∤', sim='∼', simeq='≃',
    equiv='≡', cong='≅', propto='∝', ll='≪', gg='≫', prec='≺', succ='≻',
    subset='⊂', supset='⊃', subseteq='⊆', supseteq='⊇', nsubseteq='⊈',
    cup='∪', cap='∩', setminus='∖', emptyset='∅', varnothing='∅', ni='∋',
    land='∧', wedge='∧', lor='∨', vee='∨', neg='¬', lnot='¬',
    Rightarrow='⇒', Leftarrow='⇐', Leftrightarrow='⇔', leftrightarrow='↔',
    Longrightarrow='⟹', Longleftarrow='⟸', Longleftrightarrow='⟺',
    longrightarrow='⟶', longleftarrow='⟵', longleftrightarrow='⟷',
    implies='⟹', iff='⟺', mapsto='↦', hookrightarrow='↪', hookleftarrow='↩',
    uparrow='↑', downarrow='↓', updownarrow='↕', nearrow='↗', searrow='↘',
    div='÷', ast='∗', star='⋆', circ='∘', bullet='∙', otimes='⊗', oplus='⊕',
    odot='⊙', cdots='⋯', ldots='…', dots='…', vdots='⋮', ddots='⋱',
    ell='ℓ', hbar='ℏ', Re='ℜ', Im='ℑ', aleph='ℵ', angle='∠', triangle='△',
    degree='°', prime='′', backslash='∖', lbrace='{', rbrace='}',
    langle='⟨', rangle='⟩', lvert='|', rvert='|', vert='|', Vert='‖',
    lVert='‖', rVert='‖', lfloor='⌊', rfloor='⌋', lceil='⌈', rceil='⌉')
FUNCTIONS = set('sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh coth log ln exp lim limsup liminf max min sup inf det gcd arg deg dim ker Pr'.split())
NARY = dict(sum='∑', prod='∏', coprod='∐', int='∫', iint='∬', iiint='∭', oint='∮', bigcup='⋃', bigcap='⋂', bigvee='⋁', bigwedge='⋀')
ACCENTS = dict(hat='̂', widehat='̂', bar='̅', vec='⃗', dot='̇', ddot='̈', tilde='̃', widetilde='̃', breve='̆', check='̌', acute='́', grave='̀')
ENVIRONMENTS = {'matrix', 'pmatrix', 'bmatrix', 'Bmatrix', 'vmatrix', 'Vmatrix', 'cases', 'aligned', 'gathered'}
STYLES = {'mathrm', 'mathbf', 'mathit', 'mathbb', 'mathcal', 'mathscr', 'mathfrak', 'mathsf', 'mathtt'}
DELIMITERS = {'(', ')', '[', ']', '{', '}', '|', '‖', '⟨', '⟩', '⌊', '⌋', '⌈', '⌉', ''}


def fenced(left, right, child):
    return MathNode('delimiter', left + '\x00' + right, (child,))


@dataclass(frozen=True)
class MathNode:
    kind: str
    value: str = ''
    children: tuple = ()


@dataclass(frozen=True)
class Formula:
    source: str
    expression: MathNode


def bounded(method):
    """Bound every recursive route, including unbraced fractions and n-aries."""
    @wraps(method)
    def call(self, *args):
        self.depth += 1
        try:
            if self.depth > 64:
                raise NativeExportError('formula parser nesting exceeds 64')
            return method(self, *args)
        finally:
            self.depth -= 1
    return call


class Parser:
    def __init__(self, source):
        if len(source) > 10000:
            raise NativeExportError('formula exceeds 10000 characters')
        self.source, self.offset, self.depth = source, 0, 0

    def whitespace(self):
        while self.offset < len(self.source) and self.source[self.offset].isspace():
            self.offset += 1

    def at(self, token):
        if not self.source.startswith(token, self.offset):
            return False
        last = self.offset + len(token)
        return not (token[-1].isalpha() and last < len(self.source) and self.source[last].isalpha())

    @bounded
    def sequence(self, end=None, stops=()):
        result = []
        while True:
            self.whitespace()
            if self.offset == len(self.source):
                if end is not None:
                    raise NativeExportError(f'unclosed formula group, expected {end}')
                break
            if any(self.at(stop) for stop in stops):
                break
            if end and self.source[self.offset] == end:
                self.offset += 1
                break
            result.append(self.scripted())
        return MathNode('sequence', children=tuple(result))

    def argument(self):
        self.whitespace()
        if self.offset < len(self.source) and self.source[self.offset] == '{':
            self.offset += 1
            return self.sequence('}')
        return self.atom()

    @bounded
    def scripted(self):
        base = self.atom()
        scripts = {}
        while True:
            self.whitespace()
            if self.offset >= len(self.source) or self.source[self.offset] not in '^_':
                break
            operator = self.source[self.offset]
            self.offset += 1
            if operator in scripts:
                raise NativeExportError('duplicate formula superscript/subscript')
            scripts[operator] = self.argument()
        empty = MathNode('sequence')
        if base.kind == 'nary':
            self.whitespace()
            body = self.scripted() if self.offset < len(self.source) and self.source[self.offset] not in '}]&' and not any(self.at(stop) for stop in (r'\right', r'\end', r'\\')) else empty
            return MathNode('nary', base.value, (scripts.get('_', empty), scripts.get('^', empty), body))
        if scripts:
            if base.kind == 'upright' and base.value in ('lim', 'limsup', 'liminf', 'sup', 'inf', 'max', 'min'):
                for operator in '_^':
                    if operator in scripts:
                        base = MathNode('over' if operator == '^' else 'under', children=(base, scripts[operator]))
                return base
            return MathNode('script', ''.join(k for k in '_^' if k in scripts), (base, scripts.get('_', empty), scripts.get('^', empty)))
        return base

    def raw_group(self):
        self.whitespace()
        if self.offset >= len(self.source) or self.source[self.offset] != '{':
            raise NativeExportError('expected a braced formula argument')
        self.offset += 1
        depth, result = 1, []
        while self.offset < len(self.source):
            char = self.source[self.offset]
            self.offset += 1
            if char == '\\':
                if self.offset < len(self.source) and self.source[self.offset] in '{}%_#&\\ ':
                    result.append(self.source[self.offset])
                    self.offset += 1
                    continue
                raise NativeExportError(r'commands inside \text or environment names are not supported')
            if char == '{':
                depth += 1
                if depth > 64:
                    raise NativeExportError('formula parser nesting exceeds 64')
            elif char == '}':
                depth -= 1
                if not depth:
                    return ''.join(result)
            else:
                result.append(char)
        raise NativeExportError('unclosed formula text/group')

    def delimiter(self):
        self.whitespace()
        if self.offset >= len(self.source):
            raise NativeExportError('missing formula delimiter')
        char = self.source[self.offset]
        self.offset += 1
        if char == '.':
            return ''
        if char == '\\':
            match = re.match(r'[A-Za-z]+|.', self.source[self.offset:])
            if not match:
                raise NativeExportError('missing formula delimiter')
            command = match.group()
            self.offset += len(command)
            char = SYMBOLS.get(command, command if command in '{}' else None)
        if char not in DELIMITERS:
            raise NativeExportError('unsupported formula delimiter')
        return char

    @bounded
    def environment(self, name):
        if name not in ENVIRONMENTS:
            raise NativeExportError(f'unsupported LaTeX environment: {name}')
        rows, cells, expecting_cell = [], [], False
        while True:
            self.whitespace()
            if self.at(r'\end'):
                self.offset += 4
                if self.raw_group() != name:
                    raise NativeExportError('mismatched LaTeX environment')
                if cells:
                    if expecting_cell:
                        cells.append(MathNode('sequence'))
                    rows.append(MathNode('row', children=tuple(cells)))
                break
            cells.append(self.sequence(None, ('&', r'\\', r'\end')))
            expecting_cell = False
            self.whitespace()
            if len(cells) > 32 or len(rows) >= 64:
                raise NativeExportError('formula matrix exceeds 64 rows or 32 columns')
            if self.offset >= len(self.source):
                raise NativeExportError(f'unclosed LaTeX environment: {name}')
            if self.source[self.offset] == '&':
                self.offset += 1
                expecting_cell = True
            elif self.source.startswith(r'\\', self.offset):
                self.offset += 2
                rows.append(MathNode('row', children=tuple(cells)))
                cells = []
            elif not self.at(r'\end'):
                raise NativeExportError('invalid matrix separator')
        if not rows or len({len(row.children) for row in rows}) != 1:
            raise NativeExportError('formula matrix rows must have equal column counts')
        width = len(rows[0].children)
        if name == 'cases' and width != 2:
            raise NativeExportError('cases requires two columns separated by &')
        if name == 'gathered' and width != 1:
            raise NativeExportError('gathered requires one column')
        value = MathNode('matrix', name, tuple(rows))
        delimiters = {'pmatrix': ('(', ')'), 'bmatrix': ('[', ']'), 'Bmatrix': ('{', '}'),
                      'vmatrix': ('|', '|'), 'Vmatrix': ('‖', '‖'), 'cases': ('{', '')}
        return fenced(*delimiters[name], value) if name in delimiters else value

    @bounded
    def atom(self):
        self.whitespace()
        if self.offset >= len(self.source):
            raise NativeExportError('missing formula operand')
        char = self.source[self.offset]
        self.offset += 1
        if char == '{':
            return self.sequence('}')
        if char in '}^_$&#':
            raise NativeExportError(f'unexpected formula character: {char}')
        if char != '\\':
            return MathNode('symbol', char)
        match = re.match(r'[A-Za-z]+|.', self.source[self.offset:])
        if not match:
            raise NativeExportError('incomplete formula command')
        command = match.group()
        self.offset += len(command)
        if command in SYMBOLS:
            return MathNode('symbol', SYMBOLS[command])
        if command in ('frac', 'dfrac', 'tfrac'):
            return MathNode('fraction', children=(self.argument(), self.argument()))
        if command == 'sqrt':
            self.whitespace()
            degree = MathNode('sequence')
            if self.offset < len(self.source) and self.source[self.offset] == '[':
                self.offset += 1
                degree = self.sequence(']')
            return MathNode('root', children=(degree, self.argument()))
        if command in NARY:
            return MathNode('nary', NARY[command])
        if command in STYLES:
            return MathNode('style', command, (self.argument(),))
        if command in FUNCTIONS:
            return MathNode('upright', command)
        if command in (',', ';', ' ', 'quad', 'qquad'):
            return MathNode('upright', {'quad': '\u2003', 'qquad': '\u2003\u2003'}.get(command, '\u2009'))
        if command in ('{', '}', '%', '_', '#'):
            return MathNode('symbol', command)
        if command in ('text', 'operatorname', 'mbox'):
            return MathNode('text' if command != 'operatorname' else 'upright', self.raw_group())
        if command == 'left':
            left = self.delimiter()
            body = self.sequence(None, (r'\right',))
            if not self.at(r'\right'):
                raise NativeExportError(r'unclosed \left delimiter, expected \right')
            self.offset += 6
            return fenced(left, self.delimiter(), body)
        if command == 'begin':
            return self.environment(self.raw_group())
        if command in ('binom', 'dbinom', 'tbinom'):
            return fenced('(', ')', MathNode('fraction', 'noBar', (self.argument(), self.argument())))
        if command in ACCENTS:
            return MathNode('accent', ACCENTS[command], (self.argument(),))
        if command in ('overline', 'underline'):
            return MathNode('bar', 'top' if command == 'overline' else 'bot', (self.argument(),))
        if command in ('overset', 'underset', 'stackrel'):
            annotation, base = self.argument(), self.argument()
            return MathNode('under' if command == 'underset' else 'over', children=(base, annotation))
        if command in ('!', ':', 'enspace', 'thinspace'):
            return MathNode('space', {'!': '-0.167em', ':': '0.222em', 'enspace': '0.5em', 'thinspace': '0.167em'}[command])
        raise NativeExportError(f'unsupported LaTeX command: \\{command}')


def parse(source):
    return Formula(source, Parser(source).sequence())


def emit(parent, formula, style, theme, opacity, *, math_family='Cambria Math'):
    math = node('m:oMath', node('a14:m', parent))
    size = round(number(style['fontSize'], 'formula fontSize', 1, 4000) * 100)

    def properties(parent, italic=False, bold=False):
        props = node('a:rPr', parent, sz=size, i=int(italic), b=int(bold))
        color(node('a:solidFill', props), style['color'], theme, opacity)
        # Math requires a font with OpenType MATH metrics. It only inherits size
        # and color from the surrounding text, as the PPTD interface specifies.
        node('a:latin', props, typeface=math_family)

    def visit(parent, value, italic=None, bold=False, script=None):
        kind = value.kind
        if kind == 'sequence':
            for child in value.children:
                visit(parent, child, italic, bold, script)
        elif kind in ('symbol', 'upright', 'text', 'space'):
            run = node('m:r', parent)
            use_italic = (kind == 'symbol' and value.value.isalpha()) if italic is None else italic
            # OMML defaults to italic independently of DrawingML a:rPr. Both
            # layers are required, notably for \\mathrm and function names.
            run_props = node('m:rPr', run)
            if script:
                node('m:scr', run_props, **{'m:val': script})
            node('m:sty', run_props, **{'m:val':
                 ('bi' if use_italic else 'b') if bold else ('i' if use_italic else 'p')})
            properties(run, use_italic, bold)
            spaces = {'-0.167em': '', '0.222em': '\u2005', '0.5em': '\u2002', '0.167em': '\u2009'}
            node('m:t', run, text=spaces.get(value.value, value.value) if kind == 'space' else value.value)
        elif kind == 'style':
            alphabets = {'mathbb': 'double-struck', 'mathcal': 'script', 'mathscr': 'script', 'mathfrak': 'fraktur', 'mathsf': 'sans-serif', 'mathtt': 'monospace'}
            visit(parent, value.children[0], value.value == 'mathit', value.value == 'mathbf', alphabets.get(value.value, script))
        elif kind == 'fraction':
            fraction = node('m:f', parent)
            props = node('m:fPr', fraction)
            if value.value == 'noBar':
                node('m:type', props, **{'m:val': 'noBar'})
            properties(node('m:ctrlPr', props))
            for tag, child in zip(('num', 'den'), value.children):
                visit(node('m:' + tag, fraction), child, italic, bold, script)
        elif kind == 'root':
            root = node('m:rad', parent)
            props = node('m:radPr', root)
            node('m:degHide', props, **{'m:val': int(not value.children[0].children)})
            properties(node('m:ctrlPr', props))
            for tag, child in zip(('deg', 'e'), value.children):
                visit(node('m:' + tag, root), child, italic, bold, script)
        elif kind == 'script':
            tag = {'_': 'sSub', '^': 'sSup', '_^': 'sSubSup'}[value.value]
            target = node('m:' + tag, parent)
            properties(node('m:ctrlPr', node('m:' + tag + 'Pr', target)))
            visit(node('m:e', target), value.children[0], italic, bold, script)
            for operator, tag, index in (('_', 'sub', 1), ('^', 'sup', 2)):
                if operator in value.value:
                    visit(node('m:' + tag, target), value.children[index], italic, bold, script)
        elif kind == 'nary':
            nary = node('m:nary', parent)
            props = node('m:naryPr', nary)
            node('m:chr', props, **{'m:val': value.value})
            node('m:limLoc', props, **{'m:val': 'subSup'})
            for tag, child in zip(('subHide', 'supHide'), value.children):
                node('m:' + tag, props, **{'m:val': int(child.kind == 'sequence' and not child.children)})
            properties(node('m:ctrlPr', props))
            for tag, child in zip(('sub', 'sup', 'e'), value.children):
                visit(node('m:' + tag, nary), child, italic, bold, script)
        elif kind == 'delimiter':
            delimiter = node('m:d', parent)
            props = node('m:dPr', delimiter)
            left, right = value.value.split('\x00')
            node('m:begChr', props, **{'m:val': left})
            node('m:endChr', props, **{'m:val': right})
            node('m:grow', props, **{'m:val': 1})
            properties(node('m:ctrlPr', props))
            visit(node('m:e', delimiter), value.children[0], italic, bold, script)
        elif kind == 'matrix':
            matrix = node('m:m', parent)
            props = node('m:mPr', matrix)
            columns = node('m:mcs', props)
            for index in range(len(value.children[0].children)):
                col = node('m:mcPr', node('m:mc', columns))
                node('m:count', col, **{'m:val': 1})
                align = ('right' if index % 2 == 0 else 'left') if value.value == 'aligned' else 'left' if value.value == 'cases' else 'center'
                node('m:mcJc', col, **{'m:val': align})
            properties(node('m:ctrlPr', props))
            for row in value.children:
                target = node('m:mr', matrix)
                for child in row.children:
                    visit(node('m:e', target), child, italic, bold, script)
        elif kind in ('accent', 'bar'):
            tag = 'acc' if kind == 'accent' else 'bar'
            target = node('m:' + tag, parent)
            props = node('m:' + tag + 'Pr', target)
            node('m:chr' if kind == 'accent' else 'm:pos', props, **{'m:val': value.value})
            properties(node('m:ctrlPr', props))
            visit(node('m:e', target), value.children[0], italic, bold, script)
        elif kind in ('over', 'under'):
            tag = 'limUpp' if kind == 'over' else 'limLow'
            target = node('m:' + tag, parent)
            properties(node('m:ctrlPr', node('m:' + tag + 'Pr', target)))
            for tag, child in zip(('e', 'lim'), value.children):
                visit(node('m:' + tag, target), child, italic, bold, script)
        else:
            raise NativeExportError(f'unknown math AST node: {kind}')
    visit(math, formula.expression)
