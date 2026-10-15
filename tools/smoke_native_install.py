"""Real-platform post-install smoke, including spaces and non-ASCII paths."""
from pathlib import Path
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from urllib.parse import urlsplit
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/pptd-deck-skill/scripts'))
sys.path.insert(0,str(ROOT/'skills/pptd-deck-skill/scripts/local-export'))
from native_fonts import families
from font_support import face
from native_project import Project
from native_editor import create_server
from native_validation import verify_output

def run(args,expected=0):
    result=subprocess.run(args,cwd=ROOT,env={**os.environ,'PYTHONUTF8':'0' if os.name=='nt' else '1','PYTHONDONTWRITEBYTECODE':'1','PYTHON':sys.executable},capture_output=True,text=True,encoding='utf-8',timeout=45)
    if result.returncode!=expected:raise AssertionError(str(args[:2])+': '+result.stderr+' '+result.stdout)
    return result

def main():
    candidates=[Path('C:/Windows/Fonts/msyh.ttc'),Path('C:/Windows/Fonts/arial.ttf'),Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    body=next((p for p in candidates if p.is_file()),None)
    if body is None:raise RuntimeError('Installed QA font unavailable; platform smoke must not skip font checks')
    names=families(body);family=next((n for n in ['Microsoft YaHei','Arial Unicode MS','Arial','DejaVu Sans'] if n in names),sorted(names)[0])
    math_font=body;math_index=0
    if Path('C:/Windows/Fonts/cambria.ttc').is_file():math_font=Path('C:/Windows/Fonts/cambria.ttc');math_index=1
    if Path('/System/Library/Fonts/Supplemental/STIXGeneral.otf').is_file():math_font=Path('/System/Library/Fonts/Supplemental/STIXGeneral.otf')
    cjk=face(str(body)).supports('中')
    with tempfile.TemporaryDirectory(prefix='native-smoke-') as temporary:
        work=Path(temporary)/'space 中文 project';work.mkdir()
        target=work/'installed skills'
        run(['node',str(ROOT/'bin/pptd-deck-skill.js'),'install','--target',str(target),'-y'])
        skill=target/'pptd-deck-skill'
        assert not (skill/'runtime').exists() and not list(skill.rglob('*.wasm'))
        catalog=run(['node',str(ROOT/'bin/pptd-deck-skill.js'),'fonts','list'])
        assert len(json.loads(catalog.stdout)['families'])==16
        project=work/'deck 内容';pipeline=skill/'scripts/pipeline.py'
        run([sys.executable,str(pipeline),'init','--project',str(project),'--topic','Unicode 路径 test','--pages','1','--body-font',str(body),'--math-font',str(math_font),'--math-font-index',str(math_index),'--family',family])
        manifest=project/'deck.pptd';page=project/'pages/01.page';value=yaml.safe_load(page.read_text(encoding='utf-8'))
        value['elements'][0]['content']['text']='原生 Windows 验证' if cjk else 'Native platform validation'
        value['elements'][1]['content']['text']=r'Editable math: \(x^2+\frac{1}{2}\)'
        page.write_text(yaml.safe_dump(value,allow_unicode=True),encoding='utf-8')
        expected=page.read_bytes()
        service=subprocess.Popen([sys.executable,'-u',str(skill/'scripts/local-export/native_editor.py'),str(manifest),'--port','0'],cwd=work,env={**os.environ,'PYTHONUTF8':'1','PYTHONPATH':''},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        url=None
        for _ in range(5):
            line=service.stdout.readline().strip()
            if line.startswith('http://127.0.0.1:'):url=line;break
            if service.poll() is not None:break
        if not url:raise AssertionError('installed editor failed to start: '+service.stderr.read())
        try:
            parsed=urlsplit(url);base=f'http://{parsed.netloc}';headers={'Authorization':'Bearer '+parsed.fragment}
            def request(path,data=None):
                h=dict(headers)
                if data is not None:h.update({'Content-Type':'application/json','Origin':base})
                req=urllib.request.Request(base+path,data=json.dumps(data,ensure_ascii=False).encode('utf-8') if data is not None else None,headers=h)
                with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)
            loaded=request('/api/project');first=loaded['pages'][0]
            assert len(request('/api/font-catalog')['families'])==16
            request('/api/save',{'path':first['path'],'text':expected.decode('utf-8'),'hash':first['hash'],'manifestHash':loaded['manifestHash']})
            assert page.read_bytes()==expected
        finally:
            service.terminate()
            try:service.wait(timeout=5)
            except subprocess.TimeoutExpired:service.kill();service.wait(timeout=5)
            service.stdout.close();service.stderr.close()
        run([sys.executable,str(skill/'scripts/local-export/native_cli.py'),str(manifest),'--output',str(project/'standalone.pptx')])
        verify_output(project/'standalone.pptx')
        for command in ['prepare','review']:
            run([sys.executable,str(pipeline),command,str(manifest),*(['--mode','structural','--reason','Automated source/layout checks; human visual review not performed','--note','Smoke tested installed pipeline only, no image inspection claim'] if command=='review' else [])])
        # Structural review is truthful even though prepare produced the layout proof.
        run([sys.executable,str(pipeline),'export',str(manifest),'--output',str(project/'verified.pptx')])
        report=verify_output(project/'verified.pptx')
        page.write_text(page.read_text(encoding='utf-8').replace('Editable math','Changed math'),encoding='utf-8')
        failure=run([sys.executable,str(pipeline),'export',str(manifest),'--output',str(project/'stale.pptx')],expected=2)
        assert json.loads(failure.stdout)['status']=='needs_repair' and not (project/'stale.pptx').exists()
        # Installed entrypoint must work without the source checkout or legacy tools.
        result={'platform':platform.system(),'python':platform.python_version(),'cjkFontPresent':cjk,'family':family,'unicodePaths':True,'utf8SaveRoundTrip':True,'installedNativeExport':True,'installedEditorSave':True,'installedFontCatalog':True,'pipelineExport':True,'staleQARejected':True,'packageValidation':report,'officeRenderVerified':False,'browserGUIVerified':False}
    out=ROOT/'docs/audit/platform-smoke.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main()
