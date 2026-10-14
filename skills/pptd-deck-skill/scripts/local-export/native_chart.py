"""Native ChartML serializer with embedded editable XLSX data.

Source/specification provenance and first-stage boundaries: NATIVE_NOTICE.md,
docs/native-charts.md. Unsupported content never invokes another chart engine.
"""
from native_chart_model import model
from native_common import NS, color, emu, node, string, xstring
from native_fill import fill
from native_effects import shadow
from native_workbook import formula, number_text, workbook


def paint(parent, value, theme):
    fill(parent, dict(type='solid', color=value) if isinstance(value, str) else value, theme)


def properties(parent, spec, chart, theme, default_size=None):
    props = node('a:defRPr', parent, sz=round(spec.get('fontSize', default_size or chart['fontSize']) * 100))
    color(node('a:solidFill', props), spec.get('color', '#333333'), theme)
    family = spec.get('fontFamily', chart['fontFamily'])
    for script in ('latin', 'ea'):
        face = family if isinstance(family, str) else family.get(script, family.get('latin', family.get('ea')))
        node('a:' + script, props, typeface=face)
    return props


def text(parent, tag, spec, chart, theme, default_size=None, literal=None):
    body = node(tag, parent)
    node('a:bodyPr', body)
    node('a:lstStyle', body)
    para = node('a:p', body)
    properties(node('a:pPr', para), spec, chart, theme, default_size)
    if literal is not None:
        node('a:t', node('a:r', para), text=literal)
    return body


def title(parent, spec, chart, theme, default_size):
    item = node('c:title', parent)
    text(node('c:tx', item), 'c:rich', spec, chart, theme, default_size, spec['text'])
    node('c:layout', item)
    node('c:overlay', item, val=0)


def labels(parent, spec, kind, chart, theme):
    item = node('c:dLbls', parent)
    if not spec.get('show', False):
        # Explicit flags also describe the hidden-label state to consumers
        # that do not implement the delete choice branch.
        for tag in ('showLegendKey', 'showVal', 'showCatName', 'showSerName', 'showPercent', 'showBubbleSize'):
            node('c:' + tag, item, val=0)
        return
    if 'numberFormat' in spec:
        node('c:numFmt', item, formatCode=spec['numberFormat'], sourceLinked=0)
    text(item, 'c:txPr', spec, chart, theme)
    content = spec.get('content', 'value')
    for tag, active in [('showLegendKey', False), ('showVal', content == 'value'),
                        ('showCatName', content == 'category'), ('showSerName', False),
                        ('showPercent', content == 'percentage'), ('showBubbleSize', False)]:
        node('c:' + tag, item, val=int(active))
    if kind == 'pie':
        node('c:showLeaderLines', item, val=1)


def cache(parent, tag, column, values, numeric=False):
    ref = node('c:numRef' if numeric else 'c:strRef', node(tag, parent))
    node('c:f', ref, text=formula(column, len(values)))
    items = node('c:numCache' if numeric else 'c:strCache', ref)
    if numeric:
        node('c:formatCode', items, text='General')
    node('c:ptCount', items, val=len(values))
    for index, value in enumerate(values):
        if value is None:
            continue
        node('c:v', node('c:pt', items, idx=index), text=number_text(value) if numeric else xstring(value))


def series(parent, spec, chart, writer):
    kind = spec['type']
    item = node('c:ser', parent)
    node('c:idx', item, val=spec['index'])
    node('c:order', item, val=spec['index'])
    node('c:v', node('c:tx', item), text=xstring(spec['name']))
    props = node('c:spPr', item)
    if kind == 'line':
        line = node('a:ln', props, w=emu(spec.get('width', 2)))
        paint(line, spec['color'], writer.theme)
        node('a:prstDash', line, val={'solid': 'solid', 'dash': 'dash', 'dot': 'sysDot'}[spec.get('lineStyle', 'solid')])
        marker = node('c:marker', item)
        config = spec.get('marker', False)
        node('c:symbol', marker, val={'rect': 'square'}.get(config.get('shape', 'circle'), config.get('shape', 'circle')) if config is not False else 'none')
        if config is not False:
            node('c:size', marker, val=config.get('size', 6))
            marker_props = node('c:spPr', marker)
            paint(marker_props, config.get('fill', spec['color']), writer.theme)
            writer.draw_border(marker_props, config.get('border'))
    elif kind == 'bar':
        paint(props, spec['color'], writer.theme)
        writer.draw_border(props, spec.get('border'))
        node('c:invertIfNegative', item, val=0)
    else:
        # Explicit per-point colors keep the theme cycle independent from
        # Office's automatic color policy and persist through data refresh.
        writer.draw_border(props, spec.get('border'))
        palette = spec['color'] if isinstance(spec['color'], list) else ([spec['color']] if 'fill' in spec else chart['palette'])
        for i in range(len(spec['values'])):
            point = node('c:dPt', item)
            node('c:idx', point, val=i)
            point_props = node('c:spPr', point)
            paint(point_props, palette[i % len(palette)], writer.theme)
            writer.draw_border(point_props, spec.get('border'))
    labels(item, spec['dataLabels'], kind, chart, writer.theme)
    cache(item, 'c:cat', spec['categoryColumn'], spec['categories'])
    cache(item, 'c:val', spec['valueColumn'], spec['values'], True)
    if kind == 'line':
        node('c:smooth', item, val=int(spec.get('smooth', False)))


def axis_stroke(parent, spec, writer, default_color, arrows=False):
    if spec is False:
        writer.draw_border(parent, None)
        return
    spec = {} if spec is True else spec
    style = {key: value for key, value in spec.items() if key != 'arrow'}
    style.setdefault('color', default_color)
    writer.draw_border(parent, style)
    if arrows:
        arrow = spec.get('arrow', False)
        for tag, active in [('a:headEnd', arrow in ('start', 'both')), ('a:tailEnd', arrow in (True, 'end', 'both'))]:
            node(tag, parent[-1], type='triangle' if active else 'none', w='med', len='med')


def axis(parent, spec, identifier, other, position, chart, writer):
    kind = spec['type']
    item = node('c:catAx' if kind == 'category' else 'c:valAx', parent)
    node('c:axId', item, val=identifier)
    scaling = node('c:scaling', item)
    node('c:orientation', scaling, val='maxMin' if spec.get('reverse', False) else 'minMax')
    for key in ('max', 'min'):
        if key in spec:
            node('c:' + key, scaling, val=number_text(spec[key]))
    node('c:delete', item, val=int(not spec.get('show', True)))
    node('c:axPos', item, val=position)
    grid = spec.get('gridLine', True)
    if grid is not False:
        axis_stroke(node('c:spPr', node('c:majorGridlines', item)), grid, writer, '#E2E8F0')
    if 'title' in spec:
        title(item, spec['title'], chart, writer.theme, chart['fontSize'])
    label = spec.get('label', True)
    config = {} if isinstance(label, bool) else label
    if kind == 'value':
        node('c:numFmt', item, formatCode=config.get('numberFormat', chart['valueFormat']), sourceLinked=0)
    node('c:majorTickMark', item, val='none')
    node('c:minorTickMark', item, val='none')
    node('c:tickLblPos', item, val='none' if label is False else 'nextTo')
    axis_stroke(node('c:spPr', item), spec.get('axisLine', True), writer, '#64748B', True)
    text(item, 'c:txPr', config, chart, writer.theme)
    node('c:crossAx', item, val=other)
    node('c:crosses', item, val='autoZero')
    if kind == 'category':
        node('c:auto', item, val=1)
        node('c:lblAlgn', item, val='ctr')
        node('c:lblOffset', item, val=100)
    else:
        node('c:crossBetween', item, val='between')


def write_chart(writer, tree, element, index, owner, bounds):
    chart = model(element, writer.theme)
    serial = getattr(writer, 'chart_count', 0) + 1
    writer.chart_count = serial
    chart_owner = f'ppt/charts/chart{serial}.xml'
    data_part = f'ppt/embeddings/chart{serial}.xlsx'
    package = writer.package
    package.add(data_part, workbook(chart['data']), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    root = node('c:chartSpace')
    node('c:date1904', root, val=0)
    node('c:lang', root, val='en-US')
    node('c:roundedCorners', root, val=0)
    content = node('c:chart', root)
    if 'title' in chart:
        title(content, chart['title'], chart, writer.theme, chart['titleFontSize'])
    node('c:autoTitleDeleted', content, val=int('title' not in chart))
    plot = node('c:plotArea', content)
    node('c:layout', plot)
    for kind in ('bar', 'line', 'pie'):
        entries = [s for s in chart['series'] if s['type'] == kind]
        if not entries:
            continue
        donut = kind == 'pie' and entries[0]['innerRadius'] > 0
        group = node('c:' + ('doughnutChart' if donut else kind + 'Chart'), plot)
        if kind == 'bar':
            node('c:barDir', group, val='bar' if chart['horizontal'] else 'col')
        if kind != 'pie':
            mode = entries[0].get('stack') if kind == 'bar' else None
            node('c:grouping', group, val={None: 'clustered' if kind == 'bar' else 'standard', 'value': 'stacked', 'percent': 'percentStacked'}[mode])
        node('c:varyColors', group, val=int(kind == 'pie'))
        for spec in entries:
            series(group, spec, chart, writer)
        if kind == 'bar':
            node('c:gapWidth', group, val=chart['gapWidth'])
            node('c:overlap', group, val=chart['overlap'])
        if kind == 'pie':
            node('c:firstSliceAng', group, val=entries[0]['startAngle'])
            if donut:
                node('c:holeSize', group, val=round(entries[0]['innerRadius'] * 100))
        else:
            # ChartML references the category axis before the value axis,
            # including horizontal bars where the category axis is on y.
            for identifier in ((2, 1) if chart['horizontal'] else (1, 2)):
                node('c:axId', group, val=identifier)
    if chart['series'][0]['type'] != 'pie':
        axis(plot, chart['xAxis'], 1, 2, 'b', chart, writer)
        axis(plot, chart['yAxis'], 2, 1, 'l', chart, writer)
    legend = chart['legend']
    if legend.get('show', True):
        item = node('c:legend', content)
        node('c:legendPos', item, val={'top': 't', 'bottom': 'b', 'left': 'l', 'right': 'r'}[legend.get('position', 'bottom')])
        node('c:layout', item)
        node('c:overlay', item, val=0)
        text(item, 'c:txPr', legend, chart, writer.theme)
    node('c:plotVisOnly', content, val=1)
    node('c:dispBlanksAs', content, val={'zero': 'zero', 'gap': 'gap', 'connect': 'span'}[chart['nullHandling']])
    node('c:showDLblsOverMax', content, val=0)
    props = node('c:spPr', root)
    writer.draw_fill(props, chart.get('fill'), chart_owner, bounds)
    writer.draw_border(props, chart.get('border'))
    shadow(props, chart.get('shadow'), writer.theme)
    text(root, 'c:txPr', {}, chart, writer.theme)
    rid = package.relate(chart_owner, '../embeddings/' + data_part.split('/')[-1], 'package')
    node('c:autoUpdate', node('c:externalData', root, **{'r:id': rid}), val=0)
    package.add(chart_owner, root, 'application/vnd.openxmlformats-officedocument.drawingml.chart+xml')
    rid = package.relate(owner, '../charts/' + chart_owner.split('/')[-1], 'chart')
    frame = node('p:graphicFrame', tree)
    nv = node('p:nvGraphicFramePr', frame)
    node('p:cNvPr', nv, id=index, name=string(element['elementId'], 'chart.elementId'))
    node('p:cNvGraphicFramePr', nv)
    node('p:nvPr', nv)
    transform = node('p:xfrm', frame)
    node('a:off', transform, x=emu(bounds[0]), y=emu(bounds[1]))
    node('a:ext', transform, cx=emu(bounds[2]), cy=emu(bounds[3]))
    graphic = node('a:graphicData', node('a:graphic', frame), uri=NS['c'])
    node('c:chart', graphic, **{'r:id': rid})
    return frame
