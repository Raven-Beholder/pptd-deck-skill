"""Validate/normalize PPTD charts before serialization or independent preview.

Based on the public interface and OOXML, not on a third-party chart engine.
The exact first-stage boundaries are in docs/native-charts.md.
"""
import math
import re
from native_common import NativeExportError, boolean, choice, fields, number, string, vector

TEXT_STYLE = 'fontFamily fontSize color'
COMMON_SERIES = 'type encode name xAxisIndex yAxisIndex dataLabels'
SERIES_FIELDS = {
    'bar': COMMON_SERIES + ' stack fill border',
    'line': COMMON_SERIES + ' smooth lineStyle width marker nullHandling lineColor',
    'pie': 'type encode innerRadius startAngle fill border dataLabels',
}
PALETTE = ('#2563EB', '#F59E0B', '#16A34A', '#9333EA', '#DC2626', '#0891B2')
FORMATS = ('0', '0.0', '0%', '0.0%', '#,##0', '0.0E+00')


def merge(base, override):
    result = dict(base)
    for key, value in override.items():
        result[key] = {**base[key], **value} if isinstance(value, dict) and isinstance(base.get(key), dict) else value
    return result


def font_family(value):
    if isinstance(value, dict):
        fields(value, 'latin ea', 'chart.fontFamily')
        if not value:
            raise NativeExportError('chart.fontFamily must not be empty')
        for item in value.values():
            string(item, 'chart.fontFamily')
    else:
        string(value, 'chart.fontFamily')
    return value


def text_style(value):
    fields(value, TEXT_STYLE, 'chart text style')
    if 'fontSize' in value:
        number(value['fontSize'], 'chart fontSize', 1, 4000)
    if 'fontFamily' in value:
        font_family(value['fontFamily'])
    if 'color' in value:
        string(value['color'], 'chart text color')
    return value


def title(value):
    if isinstance(value, str):
        return dict(text=string(value, 'chart title'))
    fields(value, 'text ' + TEXT_STYLE, 'chart title')
    string(value.get('text'), 'chart title.text')
    text_style({key: v for key, v in value.items() if key != 'text'})
    return dict(value)


def stroke(value, where, arrows=False):
    fields(value, 'style width color' + (' arrow' if arrows else ''), where)
    choice(value.get('style', 'solid'), ('solid', 'dash', 'dot'), where + '.style')
    number(value.get('width', 1), where + '.width', 0, 1000)
    if 'color' in value:
        string(value['color'], where + '.color')
    if arrows:
        choice(value.get('arrow', False), (False, True, 'start', 'end', 'both'), where + '.arrow')
    return dict(value)


def paint(value, where):
    if isinstance(value, str):
        return string(value, where)
    fields(value, 'type gradientType stops angle', where)
    choice(value.get('type'), ('gradient',), where + '.type')
    choice(value.get('gradientType'), ('linear', 'radial'), where + '.gradientType')
    stops = value.get('stops')
    if not isinstance(stops, list) or len(stops) < 2:
        raise NativeExportError(where + ': gradient needs at least two stops')
    last = -1
    for stop in stops:
        fields(stop, 'position color', where + '.stop')
        position = number(stop.get('position'), where + '.stop.position', 0, 1)
        if position < last:
            raise NativeExportError(where + ': gradient stops must be ordered')
        last = position
        string(stop.get('color'), where + '.stop.color')
    number(value.get('angle', 0), where + '.angle', 0, 360)
    return value


def label(value, kind):
    fields(value, 'show content numberFormat ' + TEXT_STYLE, 'chart.dataLabels')
    boolean(value.get('show', False), 'dataLabels.show')
    choice(value.get('content', 'value'), ('value', 'percentage', 'category') if kind == 'pie' else ('value',), 'dataLabels.content')
    if 'numberFormat' in value:
        choice(value['numberFormat'], FORMATS, 'dataLabels.numberFormat')
    text_style({k: v for k, v in value.items() if k in TEXT_STYLE.split()})
    return dict(value)


def axis(value, kind):
    if isinstance(value, list):
        if len(value) != 1:
            raise NativeExportError('native charts support exactly one axis on each side')
        value = value[0]
    fields(value, 'show type min max reverse title label axisLine gridLine', 'chart axis')
    result = dict(value, type=choice(value.get('type', kind), ('category', 'value'), 'axis.type'))
    boolean(value.get('show', True), 'axis.show')
    boolean(value.get('reverse', False), 'axis.reverse')
    if 'min' in value or 'max' in value:
        if result['type'] != 'value':
            raise NativeExportError('axis min/max are only supported on a value axis')
        for key in ('min', 'max'):
            if key in value:
                number(value[key], 'axis.' + key)
        if 'min' in value and 'max' in value and value['min'] >= value['max']:
            raise NativeExportError('axis.min must be less than axis.max')
    if 'title' in value:
        result['title'] = title(value['title'])
    config = value.get('label', True)
    if not isinstance(config, bool):
        fields(config, TEXT_STYLE + ' numberFormat', 'axis.label')
        text_style({k: v for k, v in config.items() if k != 'numberFormat'})
        if 'numberFormat' in config:
            if result['type'] != 'value':
                raise NativeExportError('category axis numberFormat is not supported')
            choice(config['numberFormat'], FORMATS, 'axis numberFormat')
    for key in ('axisLine', 'gridLine'):
        if not isinstance(value.get(key, True), bool):
            stroke(value[key], 'axis.' + key, key == 'axisLine')
    return result


def numeric(value, where):
    if value is None:
        return None
    if isinstance(value, str):
        # Limit numeric syntax explicitly, rather than accepting Python's nan,
        # inf, underscores or language-specific spellings in a spreadsheet.
        if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value.strip()):
            raise NativeExportError(where + ': expected numeric value or null')
        value = float(value)
    return number(value, where)


def category(value):
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return str(int(value)) if float(value).is_integer() else str(value)


def model(element, theme):
    fields(element, 'elementId elementType bounds rotation opacity flip data series seriesDefaults xAxis yAxis '
           'barWidth barGap categoryGap title legend dataLabels fontFamily fill border shadow', 'chart')
    bounds = vector(element.get('bounds'), 4, 'chart.bounds')
    if min(bounds[2:]) <= 0:
        raise NativeExportError('chart bounds must have positive width and height')
    if number(element.get('rotation', 0), 'chart.rotation') % 360 != 0:
        raise NativeExportError('native charts cannot rotate as a whole')
    if number(element.get('opacity', 1), 'chart.opacity', 0, 1) != 1:
        raise NativeExportError('native charts cannot have whole-chart opacity')
    flip = element.get('flip', [False, False])
    if not isinstance(flip, list) or len(flip) != 2 or any(boolean(v, 'chart.flip') for v in flip):
        raise NativeExportError('native charts cannot flip as a whole')
    data = element.get('data')
    fields(data, 'cols rows', 'chart.data')
    cols, rows = data.get('cols'), data.get('rows')
    if not isinstance(cols, list) or not 1 <= len(cols) <= 100 or any(not isinstance(c, str) or not c for c in cols):
        raise NativeExportError('chart.data.cols must be 1–100 nonempty strings')
    for col in cols:
        string(col, 'chart column')
    if len(set(cols)) != len(cols):
        raise NativeExportError('chart columns must be unique')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        raise NativeExportError('chart.data.rows must contain 1–10000 rows')
    for row in rows:
        if not isinstance(row, list) or len(row) != len(cols):
            raise NativeExportError('chart row length must equal column count')
        for value in row:
            if isinstance(value, str):
                string(value, 'chart cell')
            elif value is not None:
                number(value, 'chart cell')
    rows = [list(row) for row in rows]
    source = element.get('series')
    if not isinstance(source, list) or not 1 <= len(source) <= 100:
        raise NativeExportError('chart.series must contain 1–100 series')
    defaults = element.get('seriesDefaults', {})
    fields(element.get('dataLabels', {}), 'show content numberFormat ' + TEXT_STYLE, 'chart.dataLabels')
    fields(defaults, 'bar line', 'seriesDefaults')
    for kind, config in defaults.items():
        fields(config, ' '.join(k for k in SERIES_FIELDS[kind].split() if k not in ('type', 'encode')), 'seriesDefaults.' + kind)
    series = []
    for index, item in enumerate(source):
        if not isinstance(item, dict):
            raise NativeExportError('chart series must be a mapping')
        kind = choice(item.get('type'), tuple(SERIES_FIELDS), 'chart series type')
        fields(item, SERIES_FIELDS[kind], 'chart series')
        item = merge(defaults.get(kind, {}), item)
        fields(item.get('encode'), 'category value' if kind == 'pie' else 'x y', 'series.encode')
        encode = item['encode']
        for key in (('category', 'value') if kind == 'pie' else ('x', 'y')):
            if encode.get(key) not in cols:
                raise NativeExportError('series.encode references unknown column')
        for key in ('xAxisIndex', 'yAxisIndex'):
            if number(item.get(key, 0), key, 0) != 0:
                raise NativeExportError('native charts do not yet support secondary axes')
        if 'name' in item:
            string(item['name'], 'series.name')
        for key in ('fill', 'lineColor'):
            if key in item:
                values = item[key] if isinstance(item[key], list) and kind == 'pie' else [item[key]]
                if not values:
                    raise NativeExportError('pie fill array must not be empty')
                for value in values:
                    paint(value, 'series.' + key)
        if 'border' in item:
            stroke(item['border'], 'series.border')
        if kind == 'bar':
            choice(item.get('stack'), (None, 'value', 'percent'), 'series.stack')
        if kind == 'line':
            boolean(item.get('smooth', False), 'line.smooth')
            choice(item.get('lineStyle', 'solid'), ('solid', 'dash', 'dot'), 'line.lineStyle')
            number(item.get('width', 2), 'line.width', 0, 1000)
            choice(item.get('nullHandling', 'gap'), ('zero', 'gap', 'connect'), 'line.nullHandling')
            marker = item.get('marker', False)
            if marker is not False:
                fields(marker, 'shape fill border size', 'line.marker')
                choice(marker.get('shape', 'circle'), ('circle', 'rect', 'diamond', 'triangle'), 'marker.shape')
                size = number(marker.get('size', 6), 'marker.size', 2, 72)
                if int(size) != size:
                    raise NativeExportError('native marker size must be an integer')
                if 'fill' in marker:
                    paint(marker['fill'], 'marker.fill')
                if 'border' in marker:
                    stroke(marker['border'], 'marker.border')
        item['index'] = index
        item['dataLabels'] = label(merge(element.get('dataLabels', {}), item.get('dataLabels', {})), kind)
        series.append(item)
    pie = any(item['type'] == 'pie' for item in series)
    if pie and len(series) != 1:
        raise NativeExportError('pie requires exactly one series and cannot mix with other types')
    if pie:
        if any(k in element for k in ('xAxis', 'yAxis', 'barWidth', 'barGap', 'categoryGap')):
            raise NativeExportError('cartesian axis/spacing fields are not supported on pie charts')
        axes, horizontal = {}, False
    else:
        first = series[0]['encode']
        x_values, y_values = [[r[cols.index(first[key])] for r in rows if r[cols.index(first[key])] is not None] for key in ('x', 'y')]
        def has_text(values):
            return any(isinstance(v, str) and not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', v.strip()) for v in values)
        horizontal_hint = has_text(y_values) and not has_text(x_values)
        # Numeric strings in a value channel are legal. Preserve string years
        # as x categories while recognizing textual y categories for bars.
        kinds = ['value' if horizontal_hint else ('category' if not x_values or any(isinstance(v, str) for v in x_values) else 'value'),
                 'category' if horizontal_hint else 'value']
        axes = {key: axis(element.get(key, {}), inferred) for key, inferred in zip(('xAxis', 'yAxis'), kinds)}
        if {axes['xAxis']['type'], axes['yAxis']['type']} != {'category', 'value'}:
            raise NativeExportError('native bar/line charts need one category axis and one value axis')
        horizontal = axes['yAxis']['type'] == 'category'
        if horizontal and any(s['type'] == 'line' for s in series):
            raise NativeExportError('horizontal line/mixed charts are not yet supported')
    numeric_columns = set()
    for item in series:
        encode = item['encode']
        cat_key, val_key = ('category', 'value') if pie else (('y', 'x') if horizontal else ('x', 'y'))
        item['categoryColumn'] = cols.index(encode[cat_key])
        item['valueColumn'] = cols.index(encode[val_key])
        numeric_columns.add(item['valueColumn'])
        item['name'] = item.get('name', encode.get('y', encode.get('value')))
    for r, row in enumerate(rows):
        for column in numeric_columns:
            row[column] = numeric(row[column], f'chart.data row {r + 1}, {cols[column]}')
    for item in series:
        item['categories'] = [category(row[item['categoryColumn']]) for row in rows]
        item['values'] = [row[item['valueColumn']] for row in rows]
    if not pie and any(s['categories'] != series[0]['categories'] for s in series):
        raise NativeExportError('native cartesian series must share category labels')
    bars = [s for s in series if s['type'] == 'bar']
    modes = {s.get('nullHandling', 'gap') for s in series if s['type'] == 'line'}
    if len(modes) > 1:
        raise NativeExportError('line series must share nullHandling: ChartML stores it for the whole chart')
    if len({s.get('stack') for s in bars}) > 1:
        raise NativeExportError('native bar series must share a stacking mode')
    if bars and bars[0].get('stack') == 'percent' and any(v is not None and v < 0 for s in bars for v in s['values']):
        raise NativeExportError('native percent stacks require nonnegative values')
    if bars and bars[0].get('stack'):
        for row in range(len(rows)):
            number(sum(abs(s['values'][row] or 0) for s in bars), 'bar stacked total')
    if not bars and any(k in element for k in ('barWidth', 'barGap', 'categoryGap')):
        raise NativeExportError('bar spacing is only supported when a bar series exists')
    result = dict(element, data=dict(cols=cols, rows=rows), series=series, horizontal=horizontal, **axes)
    result['valueFormat'] = '0%' if bars and bars[0].get('stack') == 'percent' else 'General'
    if bars:
        stacked = bars[0].get('stack') is not None
        gap = number(element.get('barGap', 0), 'barGap', 0, .999999)
        if stacked and gap:
            raise NativeExportError('barGap is not supported on stacked bars')
        category_gap = number(element.get('categoryGap', .2), 'categoryGap', 0, .999999)
        count = 1 if stacked else len(bars)
        occupied = count + (count - 1) * gap
        width = (1 - category_gap) / occupied
        if 'barWidth' in element:
            if 'categoryGap' in element:
                raise NativeExportError('explicit barWidth cannot combine with categoryGap')
            width = number(element['barWidth'], 'barWidth', .000001, 1)
        gap_width = (1 / width - occupied) * 100
        if not -1e-8 <= gap_width <= 500:
            raise NativeExportError('bar width/gaps exceed native OOXML gapWidth range 0–500')
        result.update(gapWidth=round(max(0, gap_width)), overlap=100 if stacked else -round(gap * 100), barWidth=width, categoryGap=category_gap)
    if pie:
        item = series[0]
        radius = number(item.get('innerRadius', 0), 'pie.innerRadius', 0, 1)
        if radius and (not .1 <= radius <= .9 or not math.isclose(radius * 100, round(radius * 100), abs_tol=1e-8)):
            raise NativeExportError('native doughnut hole must be 10–90 whole percent')
        angle = number(item.get('startAngle', 0), 'pie.startAngle')
        if int(angle) != angle:
            raise NativeExportError('native pie startAngle must be an integer degree')
        if any(v is not None and v < 0 for v in item['values']) or not any(v is not None and v > 0 for v in item['values']):
            raise NativeExportError('pie requires nonnegative values and a positive total')
        number(sum(v or 0 for v in item['values']), 'pie total')
        item.update(innerRadius=radius, startAngle=int(angle) % 360)
    legend = element.get('legend', True)
    if isinstance(legend, bool):
        legend = dict(show=legend)
    fields(legend, 'show position ' + TEXT_STYLE, 'chart.legend')
    boolean(legend.get('show', True), 'legend.show')
    choice(legend.get('position', 'bottom'), ('top', 'bottom', 'left', 'right'), 'legend.position')
    text_style({k: v for k, v in legend.items() if k in TEXT_STYLE.split()})
    result['legend'] = legend
    if 'title' in element:
        result['title'] = title(element['title'])
    result['fontFamily'] = font_family(element.get('fontFamily', 'MiSans'))
    result['fontSize'] = max(10, min(18, bounds[3] / 24))
    result['titleFontSize'] = max(14, min(28, bounds[3] / 16))
    result['nullHandling'] = next((s['nullHandling'] for s in series if s['type'] == 'line' and 'nullHandling' in s), 'gap')
    palette = ['$' + key for key in theme.get('colors', {})] or list(PALETTE)
    result['palette'] = palette
    for item in series:
        item['color'] = item.get('lineColor' if item['type'] == 'line' else 'fill', palette[item['index'] % len(palette)])
    return result
