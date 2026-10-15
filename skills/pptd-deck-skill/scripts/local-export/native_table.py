"""PPTD table style cascade and native DrawingML cells. See NATIVE_NOTICE.md."""
import math
from native_common import NS, NativeExportError, boolean, choice, emu, fields, node, number, string
from native_text import STYLE_FIELDS, text_body

CELL_STYLE = STYLE_FIELDS + ' fill border align'
TABLE_STYLE = 'cellStyle firstRowStyle lastRowStyle firstColumnStyle lastColumnStyle bodyStyles rowOverColumn'


def ratios(values, where):
    if not isinstance(values, list) or not values:
        raise NativeExportError(f'{where}: expected nonempty array')
    for value in values:
        number(value, where, 0.000001, 1)
    # Older projects contain rounded proportions whose sum differs from one.
    # Fit the declared bounds without changing the source or relative sizes.
    total = math.fsum(values)
    return [value / total for value in values]


def grid(rows, height, width):
    if not isinstance(rows, list) or len(rows) != height:
        raise NativeExportError('table rows must match rowHeights')
    occupied = {}
    for r, row in enumerate(rows):
        if not isinstance(row, list):
            raise NativeExportError('table row must be an array')
        column = 0
        for cell in row:
            # Legacy shorthand is equivalent to a text-only cell. Keep this
            # normalization local so opening/exporting never rewrites the page.
            if isinstance(cell, str):
                cell = {'text': cell}
            while (r, column) in occupied:
                column += 1
            if column >= width:
                raise NativeExportError(f'table row {r + 1} has too many cells')
            fields(cell, CELL_STYLE + ' text textStyle rowSpan colSpan', 'table cell')
            spans = []
            for key in ('rowSpan', 'colSpan'):
                value = number(cell.get(key, 1), key, 1)
                if int(value) != value:
                    raise NativeExportError(f'{key}: expected integer')
                spans.append(int(value))
            down, across = spans
            if r + down > height or column + across > width:
                raise NativeExportError('table merge exceeds grid')
            for rr in range(r, r + down):
                for cc in range(column, column + across):
                    if (rr, cc) in occupied:
                        raise NativeExportError('overlapping table merges')
                    occupied[rr, cc] = (r, column, down, across, cell)
            column += across
        if any((r, c) not in occupied for c in range(width)):
            raise NativeExportError(f'table row {r + 1} has missing cells')
    return occupied


def resolve_table_style(element, theme):
    style = element.get('style', {})
    if isinstance(style, str):
        if not style.startswith('$') or style[1:] not in theme.get('tableStyles', {}):
            raise NativeExportError(f'unknown table style: {style}')
        style = theme['tableStyles'][style[1:]]
    fields(style, TABLE_STYLE, 'table.style')
    boolean(style.get('rowOverColumn', True), 'rowOverColumn')
    for key, value in style.items():
        if key == 'rowOverColumn':
            continue
        entries = value if key == 'bodyStyles' else [value]
        if not isinstance(entries, list):
            raise NativeExportError('bodyStyles: expected array')
        for entry in entries:
            fields(entry, CELL_STYLE, f'table.style.{key}')
    return style


def cell_style(element, table_style, cell, row, column, nrows, ncols, theme, *, default_font=None):
    # Empirical legacy defaults; explicitly documented in the compatibility spec.
    style = dict(fontSize=16, fontFamily=default_font or 'Times New Roman', color='#333333',
                 lineHeight=1, align=['center', 'middle'], border=None, fill=element.get('fill'))
    style.update(table_style.get('cellStyle', {}))
    body = table_style.get('bodyStyles', [])
    if body and 0 < row < nrows - 1:
        style.update(body[(row - 1) % len(body)])
    row_keys = [key for key, condition in [('firstRowStyle', row == 0), ('lastRowStyle', row == nrows - 1)] if condition]
    column_keys = [key for key, condition in [('firstColumnStyle', column == 0), ('lastColumnStyle', column == ncols - 1)] if condition]
    for key in (column_keys + row_keys if table_style.get('rowOverColumn', True) else row_keys + column_keys):
        style.update(table_style.get(key, {}))
    if 'textStyle' in cell:
        reference = string(cell['textStyle'], 'cell.textStyle')
        if not reference.startswith('$') or reference[1:] not in theme.get('textStyles', {}):
            raise NativeExportError(f'unknown cell text style: {reference}')
        inherited = theme['textStyles'][reference[1:]]
        fields(inherited, STYLE_FIELDS, 'cell text style')
        style.update(inherited)
    style.update({key: value for key, value in cell.items() if key in CELL_STYLE.split()})
    return style


def borders(value):
    if value is None or isinstance(value, dict):
        return [value] * 4
    if isinstance(value, list) and len(value) in (2, 4):
        return value * 2 if len(value) == 2 else value
    raise NativeExportError('cell.border: expected null, mapping, or two/four sides')


def write_table(writer, tree, element, index, owner, bounds, math_mode=True):
    fields(element, 'elementId elementType bounds columnWidths rowHeights rows style fill', 'table')
    widths = ratios(element.get('columnWidths'), 'columnWidths')
    heights = ratios(element.get('rowHeights'), 'rowHeights')
    cells = grid(element.get('rows'), len(heights), len(widths))
    table_style = resolve_table_style(element, writer.theme)
    frame = node('p:graphicFrame', tree)
    nv = node('p:nvGraphicFramePr', frame)
    node('p:cNvPr', nv, id=index, name=string(element['elementId'], 'elementId'))
    node('p:cNvGraphicFramePr', nv)
    node('p:nvPr', nv)
    transform = node('p:xfrm', frame)
    node('a:off', transform, x=emu(bounds[0]), y=emu(bounds[1]))
    node('a:ext', transform, cx=emu(bounds[2]), cy=emu(bounds[3]))
    data = node('a:graphicData', node('a:graphic', frame), uri=NS['a'].rsplit('/', 1)[0] + '/table')
    table = node('a:tbl', data)
    node('a:tblPr', table)
    columns = node('a:tblGrid', table)
    # Difference-of-rounded-boundaries keeps the exact declared outer bounds.
    start = 0
    for ratio in widths:
        end = start + ratio
        node('a:gridCol', columns, w=emu(bounds[2] * end) - emu(bounds[2] * start))
        start = end
    start = 0
    for r, ratio in enumerate(heights):
        end = start + ratio
        row = node('a:tr', table, h=emu(bounds[3] * end) - emu(bounds[3] * start))
        start = end
        for c in range(len(widths)):
            ar, ac, down, across, source = cells[r, c]
            anchor = (ar, ac) == (r, c)
            attrs = {}
            if anchor:
                if down > 1:
                    attrs['rowSpan'] = down
                if across > 1:
                    attrs['gridSpan'] = across
            else:
                if c > ac:
                    attrs['hMerge'] = '1'
                if r > ar:
                    attrs['vMerge'] = '1'
            cell = node('a:tc', row, **attrs)
            style = cell_style(element, table_style, source if anchor else {}, r, c, len(heights), len(widths), writer.theme,
                               default_font=writer.package.default_font if any(font.role == 'text' for font in writer.fonts) else None)
            content = {key: value for key, value in style.items() if key in (STYLE_FIELDS + ' align').split()}
            content['text'] = source.get('text', '') if anchor else ''
            text_body(cell, content, writer.theme, writer.package, owner, body_tag='a:txBody', math_mode=math_mode)
            # Cell margins belong to tcPr; a:bodyPr must not override them.
            body = cell.find('a:txBody/a:bodyPr', NS)
            for key in ('lIns', 'rIns', 'tIns', 'bIns'):
                body.attrib.pop(key, None)
            align = choice(style['align'][1], {'top': 't', 'middle': 'ctr', 'bottom': 'b'}, 'cell alignment')
            props = node('a:tcPr', cell, marL=91440, marR=91440, marT=45720, marB=45720, anchor=align)
            sides = borders(style['border'])
            for tag, side in zip(('lnL', 'lnR', 'lnT', 'lnB'), (sides[3], sides[1], sides[0], sides[2])):
                writer.draw_border(props, side)
                props[-1].tag = '{' + NS['a'] + '}' + tag
            cell_width = bounds[2] * sum(widths[ac:ac + across])
            cell_height = bounds[3] * sum(heights[ar:ar + down])
            writer.draw_fill(props, style['fill'], owner, [0, 0, cell_width, cell_height])
    return frame
