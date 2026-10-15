"""Validate native OPC/OOXML output without loading the legacy exporter."""
from pathlib import Path
import posixpath
import re
from urllib.parse import unquote
from zipfile import ZipFile, BadZipFile
import xml.etree.ElementTree as ET
from native_common import NS, NativeExportError
from native_project_fonts import read_eot, font_info, used_font_faces

ExportError=NativeExportError

def verify_output(pptx,transition='fade',expect_fonts=False):
    pptx=Path(pptx)
    try:
        with ZipFile(pptx) as archive:
            names=archive.namelist();known=set(names)
            if len(names)!=len(known) or archive.testzip():raise ExportError('duplicate ZIP members or CRC failure')
            types=ET.fromstring(archive.read('[Content_Types].xml'))
            overrides={n.get('PartName','').lstrip('/') for n in types if n.tag.endswith('Override')}
            content_types={n.get('PartName','').lstrip('/'):n.get('ContentType') for n in types if n.tag.endswith('Override')}
            defaults={n.get('Extension') for n in types if n.tag.endswith('Default')}
            rels={}
            font_relationships={}
            for name in names:
                if name=='[Content_Types].xml' or name.endswith('/'):continue
                if name not in overrides and name.rsplit('.',1)[-1] not in defaults:raise ExportError('missing content type: '+name)
                if name.endswith('.rels'):
                    owner='' if name=='_rels/.rels' else posixpath.join(posixpath.dirname(posixpath.dirname(name)),posixpath.basename(name)[:-5])
                    if owner and owner not in known:raise ExportError('relationship owner missing: '+name)
                    ids=set()
                    for rel in ET.fromstring(archive.read(name)):
                        rid=rel.get('Id')
                        if not rid or rid in ids:raise ExportError('duplicate or missing relationship ID: '+name)
                        ids.add(rid)
                        if rel.get('TargetMode')!='External':
                            target=unquote(rel.get('Target',''))
                            target=posixpath.normpath(posixpath.join(posixpath.dirname(owner),target)).lstrip('/')
                            if target not in known:raise ExportError('broken relationship: '+target)
                            if owner=='ppt/presentation.xml' and rel.get('Type')==NS['r']+'/font':
                                font_relationships[rid]=target
                    rels[owner]=ids
            slides=0;fades=0
            for name in names:
                if not name.endswith('.xml'):continue
                doc=ET.fromstring(archive.read(name))
                for element in doc.iter():
                    for key,value in element.attrib.items():
                        if key.startswith('{'+NS['r']+'}') and value not in rels.get(name,set()):raise ExportError('unresolved relationship reference: '+name)
                if not re.fullmatch(r'ppt/slides/slide\d+\.xml',name):continue
                slides+=1;order=[n.tag.rsplit('}',1)[-1] for n in doc];indexes=[i for i,k in enumerate(order) if k=='transition']
                if transition=='none':
                    if indexes:raise ExportError('transition=none contains a transition')
                else:
                    if len(indexes)!=1 or doc[indexes[0]].find('p:fade',NS) is None:raise ExportError('missing direct fade transition')
                    index=indexes[0]
                    if any(k in order and order.index(k)>index for k in ['cSld','clrMapOvr']) or any(k in order and order.index(k)<index for k in ['timing','extLst']):raise ExportError('transition has invalid slide child order')
                    fades+=1
            if not slides:raise ExportError('PPTX has no slides')
            fonts=[n for n in names if n.startswith('ppt/fonts/') and not n.endswith('/')]
            declared=set()
            families=[]
            embedded_faces=set()
            presentation=ET.fromstring(archive.read('ppt/presentation.xml'))
            for item in presentation.findall('p:embeddedFontLst/p:embeddedFont',NS):
                face=item.find('p:font',NS)
                family=face.get('typeface') if face is not None else None
                if not family or family in families:raise ExportError('invalid or duplicate embedded family')
                families.append(family)
                versions=set()
                for entry in item:
                    tag=entry.tag.rsplit('}',1)[-1]
                    if tag=='font':continue
                    if tag not in ('regular','bold','italic','boldItalic') or tag in versions:raise ExportError('invalid embedded font variant')
                    versions.add(tag)
                    target=font_relationships.get(entry.get('{'+NS['r']+'}id'))
                    if target not in fonts or content_types.get(target)!='application/x-fontdata':raise ExportError('invalid embedded font relationship/type')
                    info=font_info(read_eot(archive.read(target)))
                    if family not in info['aliases']:raise ExportError('embedded font family mismatch')
                    variant='boldItalic' if info['bold'] and info['italic'] else 'bold' if info['bold'] else 'italic' if info['italic'] else 'regular'
                    if tag!=variant:raise ExportError('embedded font variant mismatch')
                    embedded_faces.add((family, variant))
                    declared.add(target)
                if not versions:raise ExportError('embedded font has no data')
            if declared!=set(fonts) or set(font_relationships.values())!=declared:raise ExportError('orphan embedded font part or relationship')
            if fonts and (presentation.get('embedTrueTypeFonts')!='1' or presentation.get('saveSubsetFonts')!='0'):raise ExportError('invalid full-font embedding settings')
            used=used_font_faces({name:archive.read(name) for name in names if name.endswith('.xml') and name.startswith(('ppt/slides/', 'ppt/charts/'))})
            missing=[dict(family=family,variant=variant) for family,variant in sorted(used-embedded_faces)] if expect_fonts else []
            embedding={'requested':bool(expect_fonts),'status':'not-requested' if not expect_fonts else 'none' if not fonts else 'partial' if missing else 'complete',
                       'missingFaces':missing,'embeddedFamilies':families}
    except (BadZipFile,KeyError,ET.ParseError) as error:raise ExportError('invalid PPTX package: '+str(error)) from error
    return {'slides':slides,'fadeTransitions':fades,'fontParts':len(fonts),'embeddedFamilies':families,'fontValidation':'passed' if fonts else 'not-embedded','fontEmbedding':embedding,'relationshipValidation':'passed','bytes':pptx.stat().st_size}
