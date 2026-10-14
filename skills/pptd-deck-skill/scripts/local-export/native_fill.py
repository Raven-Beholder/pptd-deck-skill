"""Shared shape, background, text and cell paints. See NATIVE_NOTICE.md."""
from native_common import NativeExportError, choice, color, fields, node, number
from native_media import placement


def fill(parent, spec, theme, opacity=1, *, media=None, owner=None, bounds=None):
    if spec is None:
        node('a:noFill', parent)
        return
    if not isinstance(spec, dict):
        raise NativeExportError('fill: expected mapping')
    kind = choice(spec.get('type'), ('solid', 'gradient', 'image'), 'fill.type')
    if kind == 'solid':
        fields(spec, 'type color', 'fill')
        color(node('a:solidFill', parent), spec.get('color'), theme, opacity)
    elif kind == 'gradient':
        fields(spec, 'type gradientType stops angle', 'gradient fill')
        gradient_type = choice(spec.get('gradientType'), ('linear', 'radial'), 'gradientType')
        stops = spec.get('stops')
        if not isinstance(stops, list) or len(stops) < 2:
            raise NativeExportError('gradient requires at least two stops')
        gradient = node('a:gradFill', parent, rotWithShape='1')
        items = node('a:gsLst', gradient)
        previous = -1
        for stop in stops:
            fields(stop, 'position color', 'gradient stop')
            position = number(stop.get('position'), 'stop.position', 0, 1)
            if position < previous:
                raise NativeExportError('gradient stops must be ordered')
            previous = position
            color(node('a:gs', items, pos=round(position * 100000)), stop.get('color'), theme, opacity)
        angle = number(spec.get('angle', 0), 'gradient angle', 0, 360)
        if gradient_type == 'linear':
            node('a:lin', gradient, ang=round(angle % 360 * 60000), scaled='1')
        else:
            # Match the observed legacy circular path without a custom focus.
            node('a:path', gradient, path='circle')
    else:
        fields(spec, 'type src fit crop opacity', 'image fill')
        if media is None or owner is None or bounds is None:
            raise NativeExportError('image fill requires a local media/slide/container context')
        # The legacy exporter treats ImageFill.opacity independently from the
        # element opacity, unlike solid/gradient alpha. Keep that contract.
        alpha = number(spec.get('opacity', 1), 'image fill opacity', 0, 1)
        image_fill(parent, 'a:blipFill', spec, media, owner, bounds, alpha)



def image_fill(parent, tag, spec, media, owner, bounds, opacity=1):
    """Reference deduplicated bytes and preserve the declared container bounds."""
    part, width, height = media.load(spec.get('src'))
    _, crop = placement(bounds, (width, height), spec.get('fit', {}), spec.get('crop', {}))
    rid = media.package.relate(owner, '../media/' + part.split('/')[-1], 'image')
    paint = node(tag, parent)
    blip = node('a:blip', paint, **{'r:embed': rid})
    if opacity != 1:
        node('a:alphaModFix', blip, amt=round(opacity * 100000))
    node('a:srcRect', paint, **crop)
    node('a:fillRect', node('a:stretch', paint))
    return paint
