"""Browser-free layout QA must preserve math and report unsafe bounds."""
import sys
import unittest
from pathlib import Path
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'scripts'))
from render_native import Renderer, parse_math

FONT=next((p for p in [Path('C:/Windows/Fonts/arial.ttf'),Path('/System/Library/Fonts/Supplemental/Arial.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')] if p.is_file()),None)

@unittest.skipUnless(FONT,'installed test font unavailable')
class NativeRenderTests(unittest.TestCase):
    def renderer(self):
        return Renderer(Path('/tmp'),{'size':[960,540]},1,FONT,FONT)
    def test_math_box_is_not_plain_latex_and_layout_reports_overflow(self):
        renderer=self.renderer()
        box=renderer.formula(parse_math(r'\frac{x_1^2}{\sqrt{d}}').expression,28,'#000000')
        self.assertGreater(box.height,28)
        self.assertGreater(box.width,10)
        page={'elements':[{'elementId':'text','elementType':'text','bounds':[20,20,5,5],'content':{'text':'Too much text','fontSize':24}}]}
        image=renderer.page(page,1)
        self.assertEqual(image.size,(960,540))
        self.assertTrue(any(w['kind']=='text-height' for w in renderer.warnings))
    def test_unknown_elements_fail_instead_of_disappearing(self):
        with self.assertRaisesRegex(ValueError,'unsupported QA element'):
            self.renderer().page({'elements':[{'elementId':'table','elementType':'table','bounds':[20,20,100,50]}]},1)
