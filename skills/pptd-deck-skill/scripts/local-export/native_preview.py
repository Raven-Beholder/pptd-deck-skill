"""Bounded editor previews using the exporter's own data/style semantics.

Geometry/text measurement remains browser-specific; this is not Office rendering.
"""
from native_chart_model import model
from native_common import NativeExportError, fields
from native_table import cell_style, grid, ratios, resolve_table_style


def table(element, theme, *, default_font=None):
    fields(element, 'elementId elementType bounds columnWidths rowHeights rows style fill', 'table')
    widths = ratios(element.get('columnWidths'), 'columnWidths')
    heights = ratios(element.get('rowHeights'), 'rowHeights')
    if len(widths) * len(heights) > 2000:
        raise NativeExportError('表格预览最多支持 2000 个网格单元；源码和导出数据保留。')
    cells = grid(element.get('rows'), len(heights), len(widths))
    styles = resolve_table_style(element, theme)
    anchors = []
    for r, row in enumerate(element['rows']):
        source_index = 0
        for c in range(len(widths)):
            ar, ac, down, across, source = cells[r, c]
            if (ar, ac) != (r, c):
                continue
            anchors.append(dict(row=r, column=c, rowSpan=down, colSpan=across,
                                sourceIndex=source_index, text=source.get('text', ''),
                                style=cell_style(element, styles, source, r, c, len(heights), len(widths), theme, default_font=default_font)))
            source_index += 1
    return dict(kind='table', widths=widths, heights=heights, cells=anchors)


def preview(page, theme, *, default_font=None):
    result = {}
    for element in page['elements']:
        kind = element['elementType']
        if kind not in ('chart', 'table'):
            continue
        try:
            if kind == 'table':
                result[element['elementId']] = table(element, theme, default_font=default_font)
            else:
                chart = model(element, theme, default_font=default_font or 'MiSans')
                if len(chart['series']) * len(chart['data']['rows']) > 2000:
                    raise NativeExportError('图表预览最多支持 2000 个数据点；源码和导出数据保留。')
                result[element['elementId']] = dict(kind='chart', model=chart)
        except (ValueError, TypeError, KeyError) as exc:
            result[element['elementId']] = dict(error=str(exc))
    return result
