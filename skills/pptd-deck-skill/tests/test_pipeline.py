"""Publication gates and repair recovery must work without computer use."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import yaml

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
import pipeline
from render_native import Renderer, parse_math
from font_support import face
FONT=next((p for p in [Path('C:/Windows/Fonts/arial.ttf'),Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')] if p.is_file()),None)
MATH=Path('/System/Library/Fonts/Supplemental/STIXGeneral.otf')
if not MATH.exists():MATH=FONT

@unittest.skipUnless(FONT,'installed test font unavailable')
class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.manifest=self.root/'deck.pptd'
        from native_fonts import families
        self.family=sorted(families(FONT))[0]
        self.deck={'version':'v2','title':'test','size':[960,540],'theme':{'colors':{},'textStyles':{}},'pages':['pages/01.page']}
        self.page={'background':{'type':'solid','color':'#FFFFFF'},'elements':[{'elementId':'t','elementType':'text','bounds':[30,30,500,60],'content':{'text':'Test source','fontSize':24,'fontFamily':self.family}}]}
        (self.root/'pages').mkdir();self.write_page();self.manifest.write_text(yaml.safe_dump(self.deck))
        pipeline.save(self.root/'fonts.json',{'families':{self.family:{'regular':str(FONT),'syntheticStyles':True}},'math':{'regular':str(MATH),'syntheticStyles':True}})
    def tearDown(self):self.tmp.cleanup()
    def write_page(self):(self.root/'pages/01.page').write_text(yaml.safe_dump(self.page))
    def args(self,**kw):return SimpleNamespace(manifest=str(self.manifest),fonts=None,structural_only=False,reason=None,mode='visual',note='Inspected every rendered page',failed=False,output=str(self.root/'result.pptx'),force=False,transition='fade',apply=False,**kw)
    def run_stage(self,fn,args=None):
        with contextlib.redirect_stdout(io.StringIO()):return fn(args or self.args())
    def ready(self):self.run_stage(pipeline.prepare);self.run_stage(pipeline.review)
    def test_preexport_notice_and_editor_command_are_returned(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):pipeline.prepare(self.args())
        value=json.loads(out.getvalue());self.assertIn('网页版 PPTD 编辑器',value['notice']);self.assertIn('native_editor.py',value['editorCommand']);self.assertIn(str(self.manifest.resolve()),value['editorCommand'])
    def test_export_package_and_old_output_survive_failure(self):
        self.ready();self.run_stage(pipeline.export);before=(self.root/'result.pptx').read_bytes()
        report=pipeline.read(self.root/'.pipeline/export.json');self.assertEqual(report['packageValidation']['relationshipValidation'],'passed');self.assertEqual(report['packageValidation']['fadeTransitions'],1)
        with self.assertRaisesRegex(ValueError,'exists'):self.run_stage(pipeline.export)
        a=self.args();a.force=True
        with patch.object(pipeline,'verify_output',side_effect=ValueError('broken relationship')):
            with self.assertRaisesRegex(ValueError,'broken relationship'):self.run_stage(pipeline.export,a)
        self.assertEqual((self.root/'result.pptx').read_bytes(),before)
    def test_source_edit_and_review_image_edit_invalidate_export(self):
        self.ready();self.page['elements'][0]['content']['text']='Changed';self.write_page()
        with self.assertRaisesRegex(ValueError,'stale'):self.run_stage(pipeline.export)
        self.ready();(self.root/'.pipeline/images/01.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'image changed'):self.run_stage(pipeline.export)
    def test_relocated_project_requires_fresh_checks(self):
        self.ready()
        import shutil
        with tempfile.TemporaryDirectory() as moved:
            dest=Path(moved)/'copy';shutil.copytree(self.root,dest)
            a=self.args();a.manifest=str(dest/'deck.pptd')
            with self.assertRaisesRegex(ValueError,'relocated'):self.run_stage(pipeline.export,a)
            self.run_stage(pipeline.prepare,a);self.run_stage(pipeline.review,a)
    def test_failed_prepare_invalidates_previous_review(self):
        self.ready();self.page['elements'][0]['content']['text']='TODO';self.write_page()
        with self.assertRaisesRegex(ValueError,'placeholder'):self.run_stage(pipeline.prepare)
        self.assertFalse((self.root/'.pipeline/review.json').exists());self.assertFalse((self.root/'.pipeline/render.json').exists())
    def test_failed_review_blocks_export_and_can_recover(self):
        self.run_stage(pipeline.prepare);a=self.args();a.failed=True;a.note='Text requires realignment'
        with self.assertRaisesRegex(ValueError,'Review found issues'):self.run_stage(pipeline.review,a)
        with self.assertRaisesRegex(ValueError,'marked issues'):self.run_stage(pipeline.export)
        self.ready();self.run_stage(pipeline.export)
    def test_structural_mode_cannot_claim_visual_review(self):
        a=self.args();a.structural_only=True;a.reason='Image input unavailable';self.run_stage(pipeline.prepare,a)
        with self.assertRaisesRegex(ValueError,'visually reviewed'):self.run_stage(pipeline.review)
        a.mode='structural';self.run_stage(pipeline.review,a);self.run_stage(pipeline.export,a)
        self.assertEqual(pipeline.read(self.root/'.pipeline/export.json')['qaMode'],'structural')
    def test_repair_overflow_preserves_text_and_requires_new_checks(self):
        self.page['elements'][0]['bounds'][3]=2;self.write_page()
        with self.assertRaisesRegex(ValueError,'render checks'):self.run_stage(pipeline.prepare)
        a=self.args();a.apply=True;self.run_stage(pipeline.repair,a)
        fixed=yaml.safe_load((self.root/'pages/01.page').read_text());self.assertEqual(fixed['elements'][0]['content']['text'],'Test source');self.assertGreater(fixed['elements'][0]['bounds'][3],2)
        with self.assertRaisesRegex(ValueError,'stale'):self.run_stage(pipeline.export)
        self.ready();self.run_stage(pipeline.export)
    def test_repair_does_not_hide_other_errors_on_same_element(self):
        self.page['elements'][0]['bounds'][3]=2;self.write_page()
        with self.assertRaises(ValueError):self.run_stage(pipeline.prepare)
        path=self.root/'.pipeline/render.json';report=pipeline.read(path);report['warnings'].append({'kind':'missing-glyph','page':1,'element':'t'});pipeline.save(path,report)
        out=io.StringIO();a=self.args();a.apply=True
        with contextlib.redirect_stdout(out):pipeline.repair(a)
        self.assertTrue(any(x['kind']=='missing-glyph' for x in json.loads(out.getvalue())['remaining']))
    def test_comparison_rejects_different_evaluation_split(self):
        pipeline.save(self.root/'brief.json',{'requiresSources':True})
        evidence={'sources':[{'id':'paper','url':'https://arxiv.org/abs/1706.03762'}],'claims':[{'id':id,'source':'paper','page':1,'location':'Table 2','unit':'BLEU','value':v,'dataset':'WMT','split':split} for id,v,split in [('a',28.4,'test'),('b',26.36,'dev')]],'comparisons':[{'left':'a','right':'b','operation':'subtract','result':2.04}]}
        pipeline.save(self.root/'evidence.json',evidence)
        with self.assertRaisesRegex(ValueError,'splits'):self.run_stage(pipeline.prepare)
    def test_comparison_missing_context_and_nonfinite_values_fail(self):
        evidence={'sources':[{'id':'paper','url':'https://arxiv.org/abs/1706.03762'}],'claims':[{'id':id,'source':'paper','page':1,'location':'Table 2','unit':'BLEU','value':v} for id,v in [('a',28.4),('b',26.36)]],'comparisons':[{'left':'a','right':'b','operation':'subtract','result':2.04}]}
        pipeline.save(self.root/'evidence.json',evidence)
        with self.assertRaisesRegex(ValueError,'explicit unit, dataset'):self.run_stage(pipeline.prepare)
        evidence['claims'][0]['value']=float('nan');pipeline.save(self.root/'evidence.json',evidence)
        with self.assertRaisesRegex(ValueError,'numeric claims'):self.run_stage(pipeline.prepare)
    def test_none_transition(self):
        self.ready();a=self.args();a.transition='none';self.run_stage(pipeline.export,a);self.assertEqual(pipeline.read(self.root/'.pipeline/export.json')['packageValidation']['fadeTransitions'],0)
    def renderer(self):return Renderer(self.root,self.deck,1,None,None,pipeline.read(self.root/'fonts.json'),self.root)
    def test_opacity_zero_and_image_border_capability(self):
        r=self.renderer();p={'elements':[{'elementId':'s','elementType':'shape','shapeName':'rect','bounds':[20,20,80,80],'fill':{'type':'solid','color':'#000000'},'opacity':0}]}
        self.assertEqual(r.page(p,1).getpixel((30,30)),(255,255,255))
        p['elements'][0]={'elementId':'i','elementType':'image','bounds':[20,20,80,80],'src':'missing.png','border':{'color':'#000000'}}
        with self.assertRaisesRegex(ValueError,'image borders'):r.page(p,1)
    def test_math_bar_and_alphabet_are_not_ignored(self):
        r=self.renderer();plain=r.formula(parse_math(r'\mathrm{R}').expression,28,'black');double=r.formula(parse_math(r'\mathbb{R}').expression,28,'black')
        self.assertNotEqual(plain.image.tobytes(),double.image.tobytes())
        base=r.formula(parse_math('AB').expression,28,'black');bar=r.formula(parse_math(r'\overline{AB}').expression,28,'black')
        self.assertGreater(bar.height,base.height);self.assertLessEqual(bar.width,base.width+10)
    def test_missing_glyph_is_reported(self):
        r=self.renderer();r.glyph('\U0010ffff',24,'black');self.assertTrue(any(w['kind']=='missing-glyph' for w in r.warnings));self.assertFalse(face(str(FONT)).supports('\U0010ffff'))
