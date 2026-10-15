#!/usr/bin/env python3
"""Repeatable PPTD production: prepare -> review -> export; failures enter repair.

Never opens a browser. A failed stage blocks publication, not further repair.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import struct
import uuid
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

SCRIPTS=Path(__file__).resolve().parent
sys.path.insert(0,str(SCRIPTS/'local-export'))
from native_project import parse, page_value
from native_common import configure_utf8_console, fields, project_path, NS
from native_writer import Writer
from native_cli import export as native_export
from native_fonts import families
from native_project_fonts import project_fonts
from native_font_catalog import catalog as font_catalog, install_family, project_font_config
from native_project import Project
from render_native import Renderer, check_capabilities
from font_support import FontRegistry, face
from PIL import Image, ImageDraw
from native_validation import verify_output, ExportError
from native_export_audit import verify_content
import template_workflow
import auto_fonts
import template_samples

VERSION=1
class NeedsRepair(ValueError): pass

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name('.'+path.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(temp,path)

def load(manifest):
    manifest=Path(manifest).resolve();root=manifest.parent;deck=parse(manifest.read_text(encoding='utf-8'))
    fields(deck,'version title size theme pages customFonts','presentation')
    if deck.get('version')!='v2' or not isinstance(deck.get('pages'),list) or not deck['pages']:raise NeedsRepair('manifest needs version v2 and a nonempty pages list')
    project_fonts(root,deck.get('customFonts'),allow_missing=True)
    pages=[page_value(parse(project_path(root,p).read_text(encoding='utf-8'))) for p in deck['pages']]
    return root,deck,pages

def snapshot(manifest, fonts):
    root,deck,pages=load(manifest);inputs={Path(manifest).resolve().relative_to(root).as_posix():digest(manifest)}
    for path in deck['pages']:inputs[path]=digest(project_path(root,path))
    for font in deck.get('customFonts',[]):
        path=root/font['src']
        inputs[font['src']]=digest(project_path(root,font['src'])) if path.is_file() else 'missing-project-font'
        if font.get('license'):
            inputs[font['license']]=digest(project_path(root,font['license'])) if (root/font['license']).is_file() else 'missing-font-notice'
    for page in pages:
        for element in page['elements']:
            if element['elementType']=='image':
                path=element['src'];inputs[path]=digest(project_path(root,path))
    for name in ['brief.json','evidence.json','theme.json']:
        if (root/name).is_file():inputs[name]=digest(root/name)
    if (root/'template-samples.json').is_file():
        inputs['template-samples.json']=digest(root/'template-samples.json')
        samples=read(root/'template-samples.json')
        for path,expected in samples['files'].items():
            actual=digest(project_path(root,path))
            if actual!=expected:raise NeedsRepair('template sample evidence changed; preserve original source and regenerate starter pages')
            inputs[path]=actual
    inputs.update(template_workflow.inputs(root,deck['pages']))
    config=read(fonts);registry=FontRegistry(config,Path(fonts).resolve().parent)
    font_files={str(path):digest(path) for path in registry.files()}
    # Changes to rendering or exporting code invalidate previous approvals.
    tools={p.relative_to(SCRIPTS).as_posix():digest(p) for p in [*SCRIPTS.glob('*.py'),*(SCRIPTS/'local-export').glob('*.py')]}
    if (root/'evidence.json').is_file():
        for source in read(root/'evidence.json').get('sources',[]):
            if source.get('localPath'):inputs[source['localPath']]=digest(project_path(root,source['localPath']))
    value={'inputs':inputs,'fontConfig':digest(fonts),'fontFiles':font_files,'tools':tools}
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest(),value

def editor_command(manifest):
    import shlex
    args=[str(p) for p in [sys.executable,SCRIPTS/'local-export/native_editor.py',Path(manifest).resolve()]]
    if sys.platform=='win32':return '& '+' '.join("'"+p.replace("'","''")+"'" for p in args)
    return ' '.join(shlex.quote(p) for p in args)

def evidence_check(root, pages):
    path=root/'evidence.json'
    brief=read(root/'brief.json') if (root/'brief.json').is_file() else {}
    if not path.is_file():
        if brief.get('requiresSources'):raise NeedsRepair('requiresSources is true: provide evidence.json with cited source records')
        return []
    evidence=read(path);sources={};claims={};results=[]
    for source in evidence.get('sources',[]):
        if not source.get('id') or source['id'] in sources or not re.match(r'^https?://\S+$',source.get('url','')):raise NeedsRepair('sources require unique id and a valid primary-source URL')
        if source.get('localPath'):
            actual=digest(project_path(root,source['localPath']))
            if source.get('sha256')!=actual:raise NeedsRepair(f"source hash mismatch: {source['id']}; verify the source version, then update sha256")
        sources[source['id']]=source
    if brief.get('requiresSources') and not sources:raise NeedsRepair('research brief requires at least one cited source')
    if brief.get('requiresSources') and not evidence.get('claims'):raise NeedsRepair('research brief requires sourced claims with page and source location')
    for claim in evidence.get('claims',[]):
        if not claim.get('id') or claim['id'] in claims or claim.get('source') not in sources:raise NeedsRepair('claims require unique id and a known source')
        if not 1<=claim.get('page',0)<=len(pages) or not claim.get('location'):raise NeedsRepair('claims require page and source section/table location')
        if 'value' in claim and (not isinstance(claim['value'],(int,float)) or isinstance(claim['value'],bool) or not math.isfinite(claim['value']) or not claim.get('unit')):raise NeedsRepair('numeric claims require a numeric value and unit')
        claims[claim['id']]=claim
    for comparison in evidence.get('comparisons',[]):
        left,right=claims.get(comparison.get('left')),claims.get(comparison.get('right'))
        if not left or not right:raise NeedsRepair('comparison refers to an unknown claim')
        if any(not left.get(k) or not right.get(k) for k in ['unit','dataset','split']):raise NeedsRepair('comparison requires explicit unit, dataset and evaluation split on both claims')
        if any(left.get(k)!=right.get(k) for k in ['unit','dataset','split']):raise NeedsRepair('comparison mixes units, datasets or evaluation splits')
        if comparison.get('operation')!='subtract':raise NeedsRepair('supported comparison operation is subtract')
        actual=left['value']-right['value']
        result=comparison.get('result')
        if not isinstance(result,(int,float)) or isinstance(result,bool) or not math.isfinite(result) or abs(actual-result)>1e-8:raise NeedsRepair(f'comparison result mismatch: expected {actual:g}')
        results.append(dict(comparison,computed=actual))
    return results

def prepare(args):
    root,deck,pages=load(args.manifest);state=root/'.pipeline';fonts=Path(args.fonts or root/'fonts.json').resolve()
    state.mkdir(parents=True,exist_ok=True)
    for name in ['render.json','review.json','issues.json']: (state/name).unlink(missing_ok=True)
    if not fonts.exists() and not args.fonts:
        save(fonts,auto_fonts.configure(root,deck,pages))
    fingerprint,input_map=snapshot(args.manifest,fonts)
    # Native writer validates export semantics in memory, without publishing a PPTX.
    writer=Writer(dict(deck,pages=pages),root,'fade');writer.slides();writer.scaffold()
    comparisons=evidence_check(root,pages)
    for i,page in enumerate(pages,1):
        for element in page['elements']:
            text=element.get('content',{}).get('text','')
            if re.search(r'\bTODO\b|待填写|待补充|替换此处',text):raise NeedsRepair(f'page {i}, {element["elementId"]}: unfinished placeholder; fill the authored content')
    save(state/'preflight.json',{'version':VERSION,'fingerprint':fingerprint,'inputs':input_map,'pages':len(pages),'comparisons':comparisons,'exportSupported':True})
    if args.structural_only:
        if not args.reason:raise NeedsRepair('structural-only mode requires an explicit reason; do not use it to bypass fixable errors')
        report={'mode':'structural-only','reason':args.reason,'pages':[{'page':i,'source':p} for i,p in enumerate(deck['pages'],1)],'warnings':[],'limitations':['No rendered or visual QA; structural validation only']}
    else:
        renderer=Renderer(root,deck,2,None,None,read(fonts),fonts.parent)
        for i,page in enumerate(pages,1):
            try:check_capabilities(page)
            except ValueError as error:raise NeedsRepair(f'page {i}: {error}; author with supported primitives, or explicitly report unavailable QA capability') from error
        images=state/'images';images.mkdir(parents=True,exist_ok=True);records=[];thumbs=[]
        for i,page in enumerate(pages,1):
            try:image=renderer.page(page,i)
            except ValueError as error:raise NeedsRepair(f'page {i}: {error}') from error
            target=images/f'{i:02}.png';image.save(target)
            records.append({'page':i,'source':deck['pages'][i-1],'image':target.relative_to(root).as_posix(),'sha256':digest(target)})
            image.thumbnail((480,270));thumbs.append(image)
        overview=Image.new('RGB',(1440,300*((len(thumbs)+2)//3)),'#E8E8E8');draw=ImageDraw.Draw(overview)
        for i,image in enumerate(thumbs):
            x=i%3*480;y=i//3*300;overview.paste(image,(x,y+25));draw.text((x+10,y+5),f'P{i+1}',fill='black')
        overview.save(images/'overview.jpg',quality=92)
        report={'mode':'layout-proof','pages':records,'overview':(images/'overview.jpg').relative_to(root).as_posix(),'overviewSha256':digest(images/'overview.jpg'),'warnings':renderer.warnings,'limitations':sorted(renderer.limitations)}
    report.update(version=VERSION,projectRoot=str(root),fingerprint=fingerprint,fontConfig=str(fonts),officeRenderVerified=False)
    if (root/'template.json').exists():
        report['templateComparison']=template_workflow.compare(root,deck,report)
    save(state/'render.json',report)
    if report['warnings']:
        save(state/'issues.json',{'status':'needs_repair','stage':'render','issues':report['warnings'],'taskComplete':False})
        raise NeedsRepair('render checks found errors; run repair --apply, then prepare; inspect .pipeline/issues.json for remaining model repairs')
    if snapshot(args.manifest,fonts)[0]!=fingerprint:raise NeedsRepair('inputs changed during prepare; rerun prepare')
    (state/'issues.json').unlink(missing_ok=True)
    print(json.dumps({'status':'ready_for_review','taskComplete':False,'report':str(state/'render.json'),'pages':len(pages),'next':'Inspect every listed page image, then review; only export after review.','editorCommand':editor_command(args.manifest),'notice':'导出前可用网页版 PPTD 编辑器预览或返工；编辑后必须重新 prepare/review。'},ensure_ascii=False))

def fresh(args, require_review=False):
    root,deck,pages=load(args.manifest);state=root/'.pipeline';report=read(state/'render.json');fonts=Path(args.fonts or report['fontConfig'])
    fingerprint=snapshot(args.manifest,fonts)[0]
    if report.get('projectRoot')!=str(root):raise NeedsRepair('project relocated; rerun prepare and review in the current project')
    if report.get('version')!=VERSION or report['fingerprint']!=fingerprint or report['warnings']:raise NeedsRepair('QA is stale or has errors; rerun prepare and repair before review/export')
    if report['mode']=='layout-proof':
        for page in report['pages']:
            if digest(project_path(root,page['image']))!=page['sha256']:raise NeedsRepair('review image changed; rerun prepare and review')
        if digest(project_path(root,report['overview']))!=report['overviewSha256']:raise NeedsRepair('overview changed; rerun prepare and review')
    if (root/'template.json').exists():template_workflow.verify_comparison(root,report)
    if require_review:
        review=read(state/'review.json')
        if review['fingerprint']!=fingerprint or review['renderSha256']!=digest(state/'render.json') or review['pages']!=list(range(1,len(pages)+1)):raise NeedsRepair('review does not cover the current complete deck; review all pages again')
        if not review.get('passed'):raise NeedsRepair('visual review marked issues; fix them and rerun prepare')
        if (root/'template.json').exists():
            if review['mode']!='visual' or not template_workflow.decisions(review.get('templateDecisions'),report['templateComparison']):raise NeedsRepair('template page acceptance is incomplete or failed')
    return root,deck,pages,report,fonts,fingerprint

def review(args):
    # A failed new review must not leave a previous passing approval usable.
    (Path(args.manifest).resolve().parent/'.pipeline/review.json').unlink(missing_ok=True)
    root,deck,pages,report,fonts,fingerprint=fresh(args)
    if not args.note.strip():raise NeedsRepair('review requires a note describing what was inspected')
    if args.mode=='visual' and report['mode']!='layout-proof':raise NeedsRepair('structural-only prepare cannot be marked visually reviewed')
    if args.mode=='structural' and not args.reason:raise NeedsRepair('structural review needs a reason such as model image-input unavailable')
    template_decisions=None;passed=not args.failed
    if (root/'template.json').exists():
        if args.mode!='visual' or not getattr(args,'template_decisions',None):raise NeedsRepair('template review requires visual mode and --template-decisions with per-page findings')
        template_decisions=read(args.template_decisions)
        passed=template_workflow.decisions(template_decisions,report['templateComparison']) and passed
    save(root/'.pipeline/review.json',{'version':VERSION,'fingerprint':fingerprint,'renderSha256':digest(root/'.pipeline/render.json'),'pages':list(range(1,len(pages)+1)),'mode':args.mode,'reason':args.reason,'passed':passed,'note':args.note,'templateDecisions':template_decisions})
    if not passed: raise NeedsRepair('Review found issues: '+args.note+'; fix source and rerun prepare/review')
    print(json.dumps({'status':'needs_repair' if args.failed else 'review_recorded','taskComplete':False,'next':'Fix source and rerun prepare' if args.failed else 'Tell the user about the PPTD web editor preview/rework entry, then run export.'},ensure_ascii=False))

def export(args):
    root,deck,pages,report,fonts,fingerprint=fresh(args,True)
    output=Path(args.output or root/'deck.pptx').resolve()
    if output.suffix.lower()!='.pptx':raise NeedsRepair('output must have a .pptx extension')
    if output.exists() and not args.force:raise NeedsRepair('output exists; choose a new output name or --force for an authorized replacement')
    with tempfile.TemporaryDirectory(prefix='pptd-pipeline-',dir=root/'.pipeline') as tmp:
        embedded=bool(getattr(args,'embed_fonts',False))
        staged=Path(tmp)/'deck.pptx';native_export(Path(args.manifest).resolve(),staged,args.transition,embed_fonts=embedded)
        package=verify_output(staged,args.transition,embedded)
        package['contentValidation']=verify_content(Path(args.manifest).resolve(),staged)
        with ZipFile(staged) as archive:
            if archive.testzip() is not None:raise NeedsRepair('PPTX ZIP validation failed')
            slides=[p for p in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',p)]
            if len(slides)!=len(pages):raise NeedsRepair('PPTX slide count mismatch')
            documents=[ET.fromstring(archive.read(p)) for p in slides]
            for document in documents:
                transition=document.find('p:transition/p:fade',NS)
                if (transition is not None)!=(args.transition=='fade'):raise NeedsRepair('PPTX transition validation failed')
            maths=sum(len(doc.findall('.//m:oMath',NS)) for doc in documents)
        if snapshot(args.manifest,fonts)[0]!=fingerprint:raise NeedsRepair('inputs changed during export; output was not published; prepare/review again')
        fresh(args,True)
        output.parent.mkdir(parents=True,exist_ok=True)
        pending=output.with_name('.'+output.name+'.'+uuid.uuid4().hex+'.pending')
        try:
            shutil.copyfile(staged,pending)
            if args.force:os.replace(pending,output)
            else:os.link(pending,output)
        finally:pending.unlink(missing_ok=True)
    review_record=read(root/'.pipeline/review.json')
    font_mode='system-not-embedded' if not package['fontParts'] else 'partial-embedded-project' if package['fontEmbedding']['status']=='partial' else 'embedded-project'
    result={'version':VERSION,'status':'complete','fingerprint':fingerprint,'output':str(output),'outputSha256':digest(output),'slides':len(pages),'editableMathObjects':maths,'transition':args.transition,'fontMode':font_mode,'fontEmbedding':package['fontEmbedding'],'qaMode':review_record['mode'],'limitations':report['limitations'],'officeRenderVerified':False,'computerUseUsed':False,'packageValidation':package,'editorCommand':editor_command(args.manifest)}
    save(root/'.pipeline/export.json',result);print(json.dumps(result,ensure_ascii=False))

def fresh_for_repair(args):
    root,deck,pages=load(args.manifest);report=read(root/'.pipeline/render.json');fonts=Path(args.fonts or report['fontConfig'])
    fingerprint=snapshot(args.manifest,fonts)[0]
    if report.get('projectRoot')!=str(root) or report['fingerprint']!=fingerprint:raise NeedsRepair('repair report is stale; rerun prepare before automatic repair')
    return root,deck,pages,report,fonts,fingerprint

def repair(args):
    root,deck,pages,report,fonts,fingerprint=fresh_for_repair(args);state=root/'.pipeline';actions=[]
    # Conservative automatic fix: extend a text box only into unoccupied space.
    for warning in report['warnings']:
        if warning.get('kind')!='text-height':continue
        i=warning['page']-1;page=pages[i];element=next(e for e in page['elements'] if e['elementId']==warning['element'])
        x,y,w,h=element['bounds'];needed=warning['required']+2
        edge=deck['size'][1]
        for other in page['elements']:
            if other is element:continue
            ox,oy,ow,oh=other['bounds']
            if ox<x+w and ox+ow>x and oy+oh>y:
                edge=min(edge,oy-2 if oy>=y+h else y+h)
        if needed>h and y+needed<=edge:
            actions.append({'page':i+1,'element':element['elementId'],'action':'extend-height','from':h,'to':needed})
            if args.apply:element['bounds'][3]=needed
    if args.apply and actions:
        backup=state/'repairs'/report['fingerprint'][:12];backup.mkdir(parents=True,exist_ok=True)
        import yaml
        for i in sorted({a['page']-1 for a in actions}):
            path=project_path(root,deck['pages'][i]);saved=backup/path.relative_to(root);saved.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,saved)
            path.write_text(yaml.safe_dump(pages[i],allow_unicode=True,sort_keys=False),encoding='utf-8')
        save(backup/'actions.json',actions)
    print(json.dumps({'status':'repair_applied' if args.apply and actions else 'model_repair_needed','taskComplete':False,'automaticActions':actions,'remaining': [w for w in report['warnings'] if w.get('kind')!='text-height' or not any(a['page']==w.get('page') and a['element']==w.get('element') for a in actions)],'next':'Rerun prepare. If errors remain, fix the listed source/font mapping; do not abandon the task or export stale QA.'},ensure_ascii=False))

def init(args):
    if not 1<=args.pages<=100:raise NeedsRepair('--pages must be 1..100')
    if not re.fullmatch(r'[a-z0-9-]+',args.theme):raise NeedsRepair('theme must be a preset id')
    project=Path(args.project).resolve();project.mkdir(parents=True,exist_ok=True)
    if any(project.iterdir()):raise NeedsRepair('init requires an empty project directory to preserve existing work')
    theme_path=SCRIPTS.parent/'reference/design_system/academic'/args.theme/'theme.json'
    if not theme_path.is_file():raise NeedsRepair('No machine preset for this theme. Read its design.md and author the manifest/theme manually, or use wine-red-data.')
    theme=read(theme_path)
    ofl=getattr(args,'font_family',None)
    if ofl:
        if args.body_font or args.math_font or args.family:
            raise NeedsRepair('--font-family uses project OFL resources; do not combine it with installed font options')
        choices={entry['id']:entry for entry in font_catalog()}
        math_id=getattr(args,'math_family',None) or 'stix-two-math'
        requested=list(dict.fromkeys([ofl,*getattr(args,'extra_font',[]),math_id]))
        if any(identifier not in choices for identifier in requested):raise NeedsRepair('unknown OFL catalog id; use native_font_catalog.py list')
        if choices[ofl].get('role','text')!='text' or choices[math_id].get('role')!='math':raise NeedsRepair('choose a text body font and a MATH font')
        family=choices[ofl]['family']
    else:
        if getattr(args,'math_family',None) or getattr(args,'extra_font',[]):raise NeedsRepair('catalog options require --font-family')
        if not args.body_font and not args.math_font:
            family,config=auto_fonts.defaults(args.topic,args.family)
        else:
            if not args.body_font or not args.math_font:raise NeedsRepair('provide both --body-font and --math-font, or omit both for offline automatic selection')
            body=Path(args.body_font).resolve();math_font=Path(args.math_font).resolve()
            face(str(body),args.body_font_index);face(str(math_font),args.math_font_index)
            names=sorted(families(body,args.body_font_index))
            if not names:raise NeedsRepair('body font has no readable family metadata at the selected index')
            family=args.family or next((n for n in names if n=='Arial Unicode MS'),names[0])
            if family not in names:raise NeedsRepair(f'font family does not match the font file/index; available names: {names}')
            math_map={'regular':{'path':str(math_font),'index':args.math_font_index},'syntheticStyles':True}
            alternative=math_font.with_name(math_font.stem+'Italic'+math_font.suffix)
            if alternative.is_file():math_map['italic']=str(alternative)
            config={'families':{family:{'regular':{'path':str(body),'index':args.body_font_index},'syntheticStyles':True}},'math':math_map}
        save(project/'fonts.json',config)
    save(project/'theme.json',theme)
    save(project/'brief.json',{'topic':args.topic,'audience':'具备相关基础的读者','pages':args.pages,'requiresSources':args.research,'minimumBodyFontSize':16})
    save(project/'evidence.json',{'sources':[],'claims':[],'comparisons':[]})
    import yaml
    (project/'pages').mkdir();(project/'media').mkdir()
    styles={k:dict(v,fontFamily=family) for k,v in theme['textStyles'].items()}
    deck={'version':'v2','title':args.topic,'size':theme['size'],'theme':{'colors':theme['colors'],'textStyles':styles},'pages':[]}
    for i in range(1,args.pages+1):
        file=f'pages/{i:02}.page';deck['pages'].append(file)
        page={'background':{'type':'solid','color':'$white'},'elements':[{'elementId':'title','elementType':'text','bounds':[46,34,860,58],'content':{'style':'$title','text':'TODO：填写本页结论'}},{'elementId':'body','elementType':'text','bounds':[46,160,860,310],'content':{'style':'$body','text':'TODO：填写正文、图表、公式与来源'}}]}
        (project/file).write_text(yaml.safe_dump(page,allow_unicode=True,sort_keys=False),encoding='utf-8')
    (project/'deck.pptd').write_text(yaml.safe_dump(deck,allow_unicode=True,sort_keys=False),encoding='utf-8')
    if ofl:
        value=Project(project)
        for identifier in requested:install_family(value,identifier,value.load()['manifestHash'])
        save(project/'fonts.json',project_font_config(value))
    print(json.dumps({'status':'initialized','project':str(project),'manifest':str(project/'deck.pptd'),'family':family,'next':'Read the selected design.md; fill all TODO pages and evidence.json, then prepare.'},ensure_ascii=False))

def fonts_config(args):
    root,deck,pages=load(args.manifest)
    target=root/'fonts.json'
    if target.exists():raise NeedsRepair('fonts.json exists; preserve existing mappings or rename it before configuring again')
    value=auto_fonts.configure(root,deck,pages)
    save(target,value)
    print(json.dumps({'status':'fonts_configured','fontConfig':str(target),'families':list(value['families']),'downloaded':False,'sourceChanged':False},ensure_ascii=False))

def main():
    configure_utf8_console()
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('init');p.add_argument('--project',required=True);p.add_argument('--theme',default='wine-red-data');p.add_argument('--topic',required=True);p.add_argument('--pages',type=int,default=18);p.add_argument('--body-font');p.add_argument('--math-font');p.add_argument('--font-family',help='body font id from the OFL catalog');p.add_argument('--extra-font',action='append',default=[]);p.add_argument('--math-family',help='OFL MATH font id; defaults to stix-two-math for catalog init');p.add_argument('--family');p.add_argument('--research',action='store_true');p.add_argument('--body-font-index',type=int,default=0);p.add_argument('--math-font-index',type=int,default=0)
    p=commands.add_parser('template-import',help='Import a PPTX/POTX reference and extract layout evidence; no editable conversion')
    p.add_argument('manifest');p.add_argument('--source',required=True);p.add_argument('--references',required=True);p.add_argument('--mapping')
    p=commands.add_parser('fonts-config',help='Map existing project/installed families offline without changing source fonts')
    p.add_argument('manifest')
    p=commands.add_parser('template-samples',help='Create editable starter pages and local assets from supported PPTX/POTX objects')
    p.add_argument('--source',required=True);p.add_argument('--project',required=True);p.add_argument('--topic',default='Template starter')
    for name in ['prepare','review','repair','export','editor-info']:
        p=commands.add_parser(name);p.add_argument('manifest');p.add_argument('--fonts')
        if name=='prepare':p.add_argument('--structural-only',action='store_true');p.add_argument('--reason')
        if name=='review':p.add_argument('--mode',choices=['visual','structural'],default='visual');p.add_argument('--note',required=True);p.add_argument('--reason');p.add_argument('--failed',action='store_true');p.add_argument('--template-decisions',help='JSON list of per-page template acceptance decisions')
        if name=='repair':p.add_argument('--apply',action='store_true')
        if name=='export':p.add_argument('--output');p.add_argument('--force',action='store_true');p.add_argument('--transition',choices=['fade','none'],default='fade');p.add_argument('--embed-fonts',action='store_true')
    args=parser.parse_args()
    try:
        if args.command=='template-samples':
            print(json.dumps(template_samples.create(args.source,args.project,args.topic),ensure_ascii=False))
        elif args.command=='template-import':
            root,deck,pages=load(args.manifest)
            contract=template_workflow.import_template(root,deck['pages'],args.source,args.references,read(args.mapping) if args.mapping else None)
            print(json.dumps({'status':'template_imported','contract':str(root/'template.json'),'layouts':contract['layouts'],'next':'Read layout evidence and reference images; author editable pages, then prepare and review with --template-decisions.'},ensure_ascii=False))
        elif args.command=='fonts-config':fonts_config(args)
        elif args.command=='editor-info':print(json.dumps({'command':editor_command(args.manifest),'notice':'用网页版 PPTD 编辑器查看效果或修改返工；文件改变后重新 prepare/review/export。'},ensure_ascii=False))
        else:globals()[args.command](args)
    except (ValueError,OSError,KeyError,TypeError,struct.error,ExportError) as error:
        result={'status':'needs_repair','stage':args.command,'taskComplete':False,'error':str(error),'next':'Diagnose and repair this stage, then rerun it. Do not treat the first error as task completion. Preserve source and previous published outputs.'}
        if getattr(args,'manifest',None):
            issue_path=Path(args.manifest).resolve().parent/'.pipeline/issues.json'
            if not (issue_path.exists() and 'render checks found errors' in str(error)):save(issue_path,result)
        print(json.dumps(result,ensure_ascii=False));return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
