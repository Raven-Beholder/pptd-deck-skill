"""Validate native OPC/OOXML output without loading the legacy exporter."""
from pathlib import Path
import posixpath
import re
from urllib.parse import unquote
from zipfile import ZipFile, BadZipFile
import xml.etree.ElementTree as ET
from native_common import NS, NativeExportError

ExportError=NativeExportError

def verify_output(pptx,transition='fade',expect_fonts=False):
    pptx=Path(pptx)
    try:
        with ZipFile(pptx) as archive:
            names=archive.namelist();known=set(names)
            if len(names)!=len(known) or archive.testzip():raise ExportError('duplicate ZIP members or CRC failure')
            types=ET.fromstring(archive.read('[Content_Types].xml'))
            overrides={n.get('PartName','').lstrip('/') for n in types if n.tag.endswith('Override')}
            defaults={n.get('Extension') for n in types if n.tag.endswith('Default')}
            rels={}
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
            if fonts or expect_fonts:raise ExportError('native validation does not support embedded font parts')
    except (BadZipFile,KeyError,ET.ParseError) as error:raise ExportError('invalid PPTX package: '+str(error)) from error
    return {'slides':slides,'fadeTransitions':fades,'fontParts':0,'fontValidation':'not-embedded','relationshipValidation':'passed','bytes':pptx.stat().st_size}
