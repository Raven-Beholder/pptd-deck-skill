"""Strict rich-text subset -> DrawingML. See NATIVE_NOTICE.md.

Unsupported HTML/CSS and math syntax are errors, never silently flattened.
The intermediate paragraphs/runs are independent of the XML serializer.
"""
import re
from html.parser import HTMLParser
from html import unescape
from native_common import NativeExportError, boolean, choice, color, fields, node, number, string
from native_math import Formula, emit as emit_math, parse as parse_math
from native_effects import shadow
from native_fill import fill

STYLE_FIELDS = 'color fontSize fontFamily bold italic backgroundColor lineHeight lineHeightPx letterSpacing marginTop shadow gradient'
ALIGN = {'left': 'l', 'center': 'ctr', 'right': 'r', 'justify': 'just', 'distributed': 'dist'}


def css(text, tag):
    result = {}
    numeric = {'font-size': 'fontSize', 'letter-spacing': 'letterSpacing', 'margin-top': 'marginTop'}
    for declaration in text.split(';'):
        if not declaration.strip():
            continue
        key, separator, value = declaration.partition(':')
        key, value = key.strip(), value.strip()
        if not separator:
            raise NativeExportError(f'malformed CSS: {declaration}')
        if key in numeric:
            if (key == 'margin-top' and tag != 'p') or (key == 'letter-spacing' and tag != 'span'):
                raise NativeExportError(f'{key} is unsupported on <{tag}>')
            if not re.fullmatch(r'-?\d+(\.\d+)?px', value):
                raise NativeExportError(f'{key}: only px units supported')
            result[numeric[key]] = float(value[:-2])
        elif key == 'line-height' and tag == 'p':
            fixed = value.endswith('px')
            try:
                result['lineHeightPx' if fixed else 'lineHeight'] = float(value[:-2] if fixed else value)
            except ValueError as exc:
                raise NativeExportError('invalid CSS line-height') from exc
        elif key == 'text-align' and tag == 'p':
            result['horizontal'] = choice(value, ALIGN, 'text-align')
        elif key in ('color', 'background-color', 'font-family'):
            result[{'color': 'color', 'background-color': 'backgroundColor', 'font-family': 'fontFamily'}[key]] = value.strip('\'"')
        elif key == 'font-weight':
            result['bold'] = choice(value, {'normal': False, '400': False, 'bold': True, '700': True}, key)
        elif key == 'font-style':
            result['italic'] = choice(value, {'normal': False, 'italic': True}, key)
        else:
            raise NativeExportError(f'unsupported CSS property: {key}')
    return result


class RichText(HTMLParser):
    def __init__(self, source, style):
        super().__init__(convert_charrefs=True)
        self.base = style
        self.stack = []
        self.paragraphs = []
        self.current = None
        formulas = []
        if '\ue000' in source or '\ue001' in source:
            raise NativeExportError('reserved math delimiter in text')

        def protect(match):
            latex = unescape(match.group(1))
            if re.search(r'</?[a-zA-Z][^>]*>', latex):
                raise NativeExportError('rich-text tags inside formulas are not supported')
            formulas.append(parse_math(latex))
            return f'\ue000{len(formulas) - 1}\ue001'

        source = re.sub(r'\\\((.*?)\\\)', protect, source, flags=re.S)
        if any(delimiter in source for delimiter in ('\\(', '\\)', '\\[', '\\]')):
            raise NativeExportError('unbalanced/unsupported formula delimiters; use \\( ... \\)')
        if not re.search(r'</?[a-zA-Z][^>]*>', source):
            # Exactly one terminal newline is a YAML block-scalar convention.
            for line in source.removesuffix('\n').split('\n'):
                self.paragraphs.append((dict(style), [(line, dict(style))]))
        else:
            self.feed(source)
            self.close()
            if self.stack:
                raise NativeExportError('unclosed rich-text tag')
        if not self.paragraphs:
            self.paragraphs = [(dict(style), [])]
        for _, runs in self.paragraphs:
            expanded = []
            for text, run_style in runs:
                if text is None:
                    expanded.append((None, run_style))
                    continue
                for part in re.split(r'(\ue000\d+\ue001)', text):
                    if part.startswith('\ue000'):
                        expanded.append((formulas[int(part[1:-1])], run_style))
                    elif part:
                        expanded.append((part, run_style))
            runs[:] = expanded

    def effective(self):
        style = dict(self.base)
        for _, attributes in self.stack:
            style.update(attributes)
        # Semantic tags take priority over CSS, independent of nesting direction.
        for tag, _ in self.stack:
            style.update({'strong': {'bold': True}, 'em': {'italic': True},
                          'u': {'underline': True}, 's': {'strike': True},
                          'sup': {'baseline': 30000}, 'sub': {'baseline': -25000}}.get(tag, {}))
        return style

    def handle_starttag(self, tag, attrs):
        choice(tag, ('p', 'span', 'strong', 'em', 'u', 's', 'sup', 'sub', 'a', 'br'), 'HTML tag')
        attrs = dict(attrs)
        fields(attrs, 'href' if tag == 'a' else ('style' if tag in ('p', 'span') else ''), f'<{tag}>')
        if tag == 'br':
            if self.current is None:
                self.current = (self.effective(), [])
                self.paragraphs.append(self.current)
            self.current[1].append((None, self.effective()))
            return
        style = css(attrs.get('style', ''), tag)
        if tag == 'a':
            href = string(attrs.get('href'), 'hyperlink')
            if not re.match(r'^(https?://|mailto:)\S+$', href):
                raise NativeExportError('only http, https and mailto hyperlinks are supported')
            style.update(href=href, color='#0563C1', underline=True)
        if tag == 'p' and self.stack:
            raise NativeExportError('nested paragraphs are not supported')
        self.stack.append((tag, style))
        if tag == 'p':
            self.current = (self.effective(), [])
            self.paragraphs.append(self.current)

    def handle_endtag(self, tag):
        if tag == 'br':
            return
        if not self.stack or self.stack[-1][0] != tag:
            raise NativeExportError(f'mismatched rich-text tag: {tag}')
        self.stack.pop()
        if tag == 'p':
            self.current = None

    def handle_data(self, data):
        if self.current is None and not data.strip():
            return
        if self.current is None:
            self.current = (self.effective(), [])
            self.paragraphs.append(self.current)
        self.current[1].append((data, self.effective()))

    def handle_comment(self, data):
        raise NativeExportError('HTML comments are not supported')

    def handle_decl(self, decl):
        raise NativeExportError('HTML declarations are not supported')


def run_properties(parent, style, theme, package, owner, opacity, tag='a:rPr'):
    attrs = dict(lang='en-US', sz=round(number(style['fontSize'], 'fontSize', 1, 4000) * 100))
    for key, attribute in [('bold', 'b'), ('italic', 'i')]:
        if boolean(style[key], key):
            attrs[attribute] = '1'
    if style.get('underline'):
        attrs['u'] = 'sng'
    if style.get('strike'):
        attrs['strike'] = 'sngStrike'
    if 'baseline' in style:
        attrs['baseline'] = style['baseline']
    if 'letterSpacing' in style:
        attrs['spc'] = round(number(style['letterSpacing'], 'letterSpacing', -4000, 4000) * 100)
    props = node(tag, parent, **attrs)
    if style.get('gradient') is not None:
        choice(style['gradient'].get('type') if isinstance(style['gradient'], dict) else None,
               ('gradient',), 'text gradient type')
        fill(props, style['gradient'], theme, opacity)
    else:
        color(node('a:solidFill', props), style['color'], theme, opacity)
    shadow(props, style.get('shadow'), theme)
    if 'backgroundColor' in style:
        color(node('a:highlight', props), style['backgroundColor'], theme, opacity)
    family = style['fontFamily']
    if isinstance(family, dict):
        fields(family, 'latin ea', 'fontFamily')
        if set(family) != {'latin', 'ea'}:
            raise NativeExportError('fontFamily requires latin and ea')
    else:
        family = {'latin': family, 'ea': family}
    for key in ('latin', 'ea'):
        node('a:' + key, props, typeface=string(family[key], 'fontFamily'))
    if 'href' in style:
        rid = package.relate(owner, style['href'], 'hyperlink', external=True)
        node('a:hlinkClick', props, **{'r:id': rid})


def text_body(parent, content, theme, package, owner, opacity=1, *, math_mode=True, body_tag='p:txBody'):
    fields(content, STYLE_FIELDS + ' text style textDirection wrap align', 'text.content')
    # Observed legacy defaults differ from the prose PPTD reference (18/black/1).
    style = dict(color='#333333', fontSize=16, fontFamily='MiSans', bold=False, italic=False, lineHeight=1.2)
    if 'style' in content:
        reference = string(content['style'], 'text style')
        if not reference.startswith('$') or reference[1:] not in theme.get('textStyles', {}):
            raise NativeExportError(f'unknown text style: {reference}')
        inherited = theme['textStyles'][reference[1:]]
        fields(inherited, STYLE_FIELDS, 'theme text style')
        style.update(inherited)
    style.update(content)
    # An explicit relative spacing replaces an inherited absolute spacing.
    if 'lineHeight' in content and 'lineHeightPx' not in content:
        style.pop('lineHeightPx', None)
    align = content.get('align', ['left', 'top'])
    if not isinstance(align, list) or len(align) != 2:
        raise NativeExportError('align: expected [horizontal, vertical]')
    style['horizontal'] = choice(align[0], ALIGN, 'horizontal alignment')
    anchor = choice(align[1], {'top': 't', 'middle': 'ctr', 'bottom': 'b'}, 'vertical alignment')
    direction = choice(content.get('textDirection', 'horizontal'), {'horizontal': 'horz', 'vertical': 'vert'}, 'textDirection')
    body = node(body_tag, parent)
    node('a:bodyPr', body, lIns=0, rIns=0, tIns=0, bIns=0, anchor=anchor, vert=direction,
         wrap='square' if boolean(content.get('wrap', True), 'wrap') else 'none')
    node('a:lstStyle', body)
    parsed = RichText(string(content.get('text'), 'text'), style)
    for paragraph_style, runs in parsed.paragraphs:
        paragraph = node('a:p', body)
        props = node('a:pPr', paragraph, algn=paragraph_style['horizontal'])
        spacing = node('a:lnSpc', props)
        if 'lineHeightPx' in paragraph_style:
            node('a:spcPts', spacing, val=round(number(paragraph_style['lineHeightPx'], 'lineHeightPx', 0.01, 21474836.47) * 100))
        else:
            node('a:spcPct', spacing, val=round(number(paragraph_style['lineHeight'], 'lineHeight', 0.01, 21474.83647) * 100000))
        if 'marginTop' in paragraph_style:
            node('a:spcPts', node('a:spcBef', props), val=round(number(paragraph_style['marginTop'], 'marginTop', 0, 21474836.47) * 100))
        for text, run_style in runs:
            if isinstance(text, Formula):
                if math_mode:
                    emit_math(paragraph, text, run_style, theme, opacity)
                    continue
                text = '\\(' + text.source + '\\)'
            run = node('a:br' if text is None else 'a:r', paragraph)
            run_properties(run, run_style, theme, package, owner, opacity)
            if text is not None:
                node('a:t', run, text=string(text, 'run text'))
        run_properties(paragraph, paragraph_style, theme, package, owner, opacity, 'a:endParaRPr')
