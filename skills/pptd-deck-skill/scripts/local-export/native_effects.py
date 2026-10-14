"""DrawingML effects from PPTD values. See NATIVE_NOTICE.md."""
import math
from native_common import color, emu, fields, node, number, vector


def shadow(parent, spec, theme):
    if spec is None:
        return
    fields(spec, 'blur color offset', 'shadow')
    blur = number(spec.get('blur'), 'shadow.blur', 0, 10000)
    dx, dy = vector(spec.get('offset', [0, 0]), 2, 'shadow.offset')
    distance = number(math.hypot(dx, dy), 'shadow distance', 0, 10000)
    angle = math.degrees(math.atan2(dy, dx)) % 360
    effect = node('a:outerShdw', node('a:effectLst', parent),
                  blurRad=emu(blur), dist=emu(distance), dir=round(angle * 60000) % 21600000,
                  sx=100000, sy=100000, kx=0, ky=0, algn='bl', rotWithShape='0')
    # Observed shadow alpha is independent of the owning element's opacity.
    color(effect, spec.get('color'), theme)
