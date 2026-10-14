#!/usr/bin/env python3
"""Browser-free PPTD layout QA for native text, shapes, lines and local images.

Uses the native exporter's RichText/LaTeX parsers, Pillow and installed fonts.
This is a layout proof, not a PowerPoint/WPS/Keynote rendering certificate.
Unsupported elements/rotations fail explicitly; no browser or UI is opened.
"""
import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont, ImageOps
from font_support import face, alphabet, FontRegistry

sys.path.insert(0, str(Path(__file__).parent / 'local-export'))
from native_math import Formula, parse as parse_math
from native_text import RichText
from native_common import configure_utf8_console, NativeExportError, project_path
from native_project import parse as parse_yaml, page_value


def resolve(value, theme, default='#000000'):
    seen = set()
    while isinstance(value, str) and value.startswith('$'):
        if value in seen:
            raise ValueError('cyclic theme color')
        seen.add(value)
        value = theme.get('colors', {}).get(value[1:])
    return value or default


@dataclass
class Box:
    image: Image.Image
    baseline: int
    @property
    def width(self): return self.image.width
    @property
    def height(self): return self.image.height


class Renderer:
    def __init__(self, root, deck, scale, font_path, math_font, font_config=None, config_root=None):
        self.root, self.deck, self.scale = root, deck, scale
        self.theme = deck.get('theme', {})
        self.font_path, self.math_font = font_path, math_font
        self.warnings = []
        self.limitations = {'Pillow layout proof; Office rendering not verified', 'Math spacing/metrics approximate'}
        self.default_family = next(iter(font_config.get('families',{})), 'Arial Unicode MS') if font_config else 'Arial Unicode MS'
        self.active_family = self.default_family
        self.active_context = {}
        self.font_cache = {}
        if font_config:
            self.registry = FontRegistry(font_config, config_root or root)
        else:
            from native_fonts import families
            names=sorted(families(font_path))
            if not names:raise ValueError('font has no readable family name')
            self.default_family='Arial Unicode MS' if 'Arial Unicode MS' in names else names[0]
            self.active_family=self.default_family
            regular={'path':str(Path(font_path).resolve())}
            math_regular={'path':str(Path(math_font).resolve())}
            self.registry=FontRegistry({'families':{self.default_family:{'regular':regular,'syntheticStyles':True}}, 'math':{'regular':math_regular,'syntheticStyles':True}},root)
            alternative=Path(math_font).with_name(Path(math_font).stem+'Italic'+Path(math_font).suffix)
            if alternative.is_file():self.registry.config['math']['italic']={'path':str(alternative.resolve())}
            self.limitations.add('legacy --font override; declared family must match the configured default')

    def glyph(self, text, size, color, math_mode=False, bold=False, italic=False, underline=False, strike=False):
        path,index,synthetic=self.registry.descriptor(self.active_family,math_mode,bold,italic)
        key=(str(path),index,max(1,round(size)))
        if key not in self.font_cache: self.font_cache[key]=ImageFont.truetype(str(path),key[2],index=index)
        font=self.font_cache[key]; coverage=face(str(path),index)
        for char in set(text):
            if not coverage.supports(char):
                warning=dict(self.active_context,kind='missing-glyph',character=char,codepoint=f'U+{ord(char):04X}',font=str(path),fix='Choose a font covering this character or replace the character with equivalent notation.')
                if warning not in self.warnings:self.warnings.append(warning)
        ascent,descent=font.getmetrics(); stroke=int(bold and synthetic)
        width=max(1,math.ceil(font.getlength(text))+stroke)
        image=Image.new('RGBA',(width,ascent+descent+3))
        draw=ImageDraw.Draw(image)
        draw.text((0,ascent),text,font=font,fill=color,anchor='ls',stroke_width=stroke)
        if underline: draw.line((0,ascent+2,width,ascent+2),fill=color,width=max(1,round(size*.04)))
        if strike: draw.line((0,round(ascent*.65),width,round(ascent*.65)),fill=color,width=max(1,round(size*.04)))
        return Box(image,ascent)

    def combine(self, boxes, gap=0):
        if not boxes:
            return Box(Image.new('RGBA', (1, 1)), 0)
        base = max(box.baseline for box in boxes)
        height = base + max(box.height - box.baseline for box in boxes)
        width = sum(box.width for box in boxes) + gap * (len(boxes)-1)
        image = Image.new('RGBA', (max(1, width), max(1, height)))
        x = 0
        for box in boxes:
            image.alpha_composite(box.image, (x, base-box.baseline))
            x += box.width + gap
        return Box(image, base)

    def formula(self, value, size, color, italic=None, bold=False, variant=None):
        children = value.children
        visit = lambda child, size=size: self.formula(child, size, color, italic, bold, variant)
        gap = max(2, round(size*.12))
        if value.kind == 'sequence': return self.combine([visit(child) for child in children])
        if value.kind in ('symbol','upright','text'):
            return self.glyph(alphabet(value.value,variant), size, color, value.kind != 'text', bold, (value.kind == 'symbol' and value.value.isalpha()) if italic is None else italic)
        if value.kind == 'space': return Box(Image.new('RGBA', (max(1, round(size*.17)), round(size))), round(size*.8))
        if value.kind == 'style': return self.formula(children[0],size,color,value.value=='mathit',value.value=='mathbf',value.value)
        if value.kind == 'fraction':
            top, bot = visit(children[0],size*.8), visit(children[1],size*.8)
            width = max(top.width,bot.width)+gap*2
            image = Image.new('RGBA',(width,top.height+bot.height+gap*3))
            image.alpha_composite(top.image,((width-top.width)//2,0))
            image.alpha_composite(bot.image,((width-bot.width)//2,top.height+gap*3))
            if value.value != 'noBar':
                ImageDraw.Draw(image).line((0,top.height+gap,width,top.height+gap),fill=color,width=max(1,round(size*.04)))
            return Box(image, top.height+gap+round(size*.25))
        if value.kind == 'root':
            body = visit(children[1]); sign = self.glyph('√',size*1.25,color,True)
            image = Image.new('RGBA',(sign.width+body.width+gap,max(sign.height,body.height)+gap))
            image.alpha_composite(sign.image,(0,gap)); image.alpha_composite(body.image,(sign.width,gap))
            ImageDraw.Draw(image).line((sign.width,gap,sign.width+body.width,gap),fill=color,width=max(1,round(size*.04)))
            if children[0].children:
                degree=visit(children[0],size*.5); image.alpha_composite(degree.image,(0,0))
            return Box(image,body.baseline+gap)
        if value.kind == 'script':
            base=visit(children[0]); sub=visit(children[1],size*.65); sup=visit(children[2],size*.65)
            baseline=max(base.baseline,sup.baseline+round(size*.45)) if '^' in value.value else base.baseline
            top=baseline-base.baseline
            sup_y=max(0,baseline-round(size*.45)-sup.baseline)
            sub_y=max(0,baseline+round(size*.25)-sub.baseline)
            height=max(base.height+top,sup_y+sup.height if '^' in value.value else 0,sub_y+sub.height if '_' in value.value else 0)
            image=Image.new('RGBA',(base.width+max(sub.width,sup.width),height))
            image.alpha_composite(base.image,(0,top))
            if '^' in value.value: image.alpha_composite(sup.image,(base.width,sup_y))
            if '_' in value.value: image.alpha_composite(sub.image,(base.width,sub_y))
            return Box(image,baseline)
        if value.kind == 'delimiter':
            body=visit(children[0]); left,right=value.value.split('\0')
            fences=[]
            for mark in [left,right]:
                glyph=self.glyph(mark or ' ',size,color,True)
                glyph.image=glyph.image.resize((max(1,round(size*.35)) if mark else 1,body.height))
                glyph.baseline=body.baseline; fences.append(glyph)
            return self.combine([fences[0],body,fences[1]],gap)
        if value.kind == 'matrix':
            cells=[[visit(child) for child in row.children] for row in children]
            widths=[max(row[c].width for row in cells) for c in range(len(cells[0]))]
            heights=[max(cell.height for cell in row) for row in cells]
            width=sum(widths)+gap*3*(len(widths)-1); height=sum(heights)+gap*(len(heights)-1)
            image=Image.new('RGBA',(width,height)); y=0
            for row,h in zip(cells,heights):
                x=0
                for index,(cell,w) in enumerate(zip(row,widths)):
                    align=('right' if index%2==0 else 'left') if value.value=='aligned' else 'left' if value.value=='cases' else 'center'
                    offset=w-cell.width if align=='right' else 0 if align=='left' else (w-cell.width)//2
                    image.alpha_composite(cell.image,(x+offset,y)); x+=w+gap*3
                y+=h+gap
            return Box(image,height//2+round(size*.3))
        if value.kind == 'nary':
            low,up,body=[visit(child,size*.65 if i<2 else size) for i,child in enumerate(children)]
            operator=self.glyph(value.value,size*1.35,color,True)
            width=max(low.width,up.width,operator.width); image=Image.new('RGBA',(width,up.height+operator.height+low.height))
            for box,y in [(up,0),(operator,up.height),(low,up.height+operator.height)]:
                image.alpha_composite(box.image,((width-box.width)//2,y))
            return self.combine([Box(image,up.height+operator.baseline),body],gap)
        if value.kind in ('accent','bar','over','under'):
            body=visit(children[0]); under=value.kind=='under' or value.value=='bot'
            if value.kind=='bar' or value.kind=='accent' and value.value=='̅':
                padding=max(2,round(size*.12)); image=Image.new('RGBA',(body.width,body.height+padding))
                image.alpha_composite(body.image,(0,0 if under else padding))
                y=body.height+padding-1 if under else 0
                ImageDraw.Draw(image).line((0,y,body.width,y),fill=color,width=max(1,round(size*.04)))
                return Box(image,body.baseline+(0 if under else padding))
            marks={'̂':'^','̃':'~','⃗':'→','̇':'˙','̈':'¨','̆':'˘','̌':'ˇ','́':'´','̀':'`'}
            annotation=visit(children[1],size*.6) if len(children)>1 else self.glyph(marks.get(value.value,value.value),size*.65,color,True)
            width=max(body.width,annotation.width); image=Image.new('RGBA',(width,body.height+annotation.height))
            image.alpha_composite(body.image,((width-body.width)//2,0 if under else annotation.height))
            image.alpha_composite(annotation.image,((width-annotation.width)//2,body.height if under else 0))
            return Box(image,body.baseline+(0 if under else annotation.height))
        raise ValueError(f'unsupported QA math node: {value.kind}')

    def text(self, canvas, element, page_index):
        content=element['content']; style=dict(fontSize=16,fontFamily=self.default_family,color='#000000',lineHeight=1.2)
        ref=content.get('style','').removeprefix('$')
        style.update(self.theme.get('textStyles',{}).get(ref,{})); style.update(content)
        self.active_family=style['fontFamily']
        x,y,w,h=[round(v*self.scale) for v in element['bounds']]
        rows=[]
        for pstyle,runs in RichText(content['text'],style).paragraphs:
            if any(pstyle.get(k) for k in ('marginTop','lineHeightPx','letterSpacing','backgroundColor')):raise ValueError('unsupported QA paragraph spacing/decoration')
            line=[]; width=0
            for value,run in runs:
                size=run.get('fontSize',style['fontSize'])*self.scale
                color=resolve(run.get('color',style['color']),self.theme)
                self.active_family=run.get('fontFamily',style['fontFamily'])
                if run.get('baseline') or run.get('letterSpacing') or run.get('gradient') or run.get('shadow') or run.get('backgroundColor'): raise ValueError('QA does not support rich-text baseline, tracking, gradients or shadows')
                if value is None:
                    rows.append((self.combine(line),pstyle)); line=[]; width=0; continue
                parts=[self.formula(value.expression,size,color)] if isinstance(value,Formula) else [self.glyph(char,size,color,bold=run.get('bold',False),italic=run.get('italic',False),underline=run.get('underline',False),strike=run.get('strike',False)) for char in value]
                for box in parts:
                    if content.get('wrap',True) and line and width+box.width>w:
                        rows.append((self.combine(line),pstyle)); line=[]; width=0
                    line.append(box); width+=box.width
            rows.append((self.combine(line),pstyle))
        total=sum(max(row.height,round(style['fontSize']*self.scale*pstyle.get('lineHeight',style.get('lineHeight',1.2)))) for row,pstyle in rows)
        if total>h+2:
            self.warnings.append(dict(page=page_index,element=element['elementId'],kind='text-height',required=total/self.scale,available=h/self.scale))
        align=content.get('align',['left','top'])
        dy=y+(max(0,h-total)//2 if align[1]=='middle' else max(0,h-total) if align[1]=='bottom' else 0)
        for row,pstyle in rows:
            if row.width>w+2: self.warnings.append(dict(page=page_index,element=element['elementId'],kind='text-width',required=row.width/self.scale,available=w/self.scale))
            halign=pstyle.get('horizontal',align[0]); dx=x+(max(0,w-row.width)//2 if halign=='center' else max(0,w-row.width) if halign=='right' else 0)
            canvas.alpha_composite(row.image,(dx,dy)); dy+=max(row.height,round(style['fontSize']*self.scale*pstyle.get('lineHeight',style.get('lineHeight',1.2))))

    def page(self, page, index):
        check_capabilities(page)
        width,height=[round(v*self.scale) for v in self.deck['size']]
        canvas=Image.new('RGBA',(width,height),resolve(page.get('background',{}).get('color'),self.theme,'#FFFFFF'))
        for element in page['elements']:
            x,y,w,h=[round(v*self.scale) for v in element['bounds']]
            if x<0 or y<0 or x+w>width+2 or y+h>height+2: self.warnings.append(dict(page=index,element=element['elementId'],kind='bounds'))
            if element.get('rotation') or any(element.get('flip',[])): raise ValueError('QA renderer does not support rotations/flips')
            self.active_context={'page':index,'element':element['elementId']}
            layer=Image.new('RGBA',canvas.size); draw=ImageDraw.Draw(layer)
            kind=element['elementType']
            if kind=='text': self.text(layer,element,index)
            elif kind=='shape':
                fill=element.get('fill',{}); border=element.get('border',{}) or {}; shape=element.get('shapeName','rect')
                kwargs=dict(fill=resolve(fill.get('color'),self.theme) if fill else None,outline=resolve(border.get('color'),self.theme) if border else None,width=max(1,round(border.get('width',1)*self.scale)))
                if shape=='rect': draw.rectangle((x,y,x+w,y+h),**kwargs)
                elif shape=='ellipse': draw.ellipse((x,y,x+w,y+h),**kwargs)
                else: raise ValueError(f'unsupported QA shape: {shape}')
            elif kind=='line':
                vx,vy=element['viewBox']; points=[tuple(map(float,p.split(','))) for p in element['points'].split()]
                points=[(x+px/vx*w,y+py/vy*h) for px,py in points]
                border=element.get('border',{}); color=resolve(border.get('color'),self.theme)
                draw.line(points,fill=color,width=max(1,round(border.get('width',1)*self.scale)))
                if element.get('arrow',[None,None])[1]:
                    (ax,ay),(bx,by)=points[-2:]; angle=math.atan2(by-ay,bx-ax); size=8*self.scale
                    draw.polygon([(bx,by),(bx-size*math.cos(angle-.4),by-size*math.sin(angle-.4)),(bx-size*math.cos(angle+.4),by-size*math.sin(angle+.4))],fill=color)
            elif kind=='image':
                image=Image.open(project_path(self.root,element['src'])).convert('RGBA')
                mode=element.get('fit',{}).get('mode','cover')
                if mode=='cover': image=ImageOps.fit(image,(w,h),method=Image.Resampling.LANCZOS)
                elif mode=='contain': image=ImageOps.contain(image,(w,h),method=Image.Resampling.LANCZOS)
                elif mode=='fill': image=image.resize((w,h),Image.Resampling.LANCZOS)
                else: raise ValueError(f'unsupported image fit: {mode}')
                layer.alpha_composite(image,(x+(w-image.width)//2,y+(h-image.height)//2))
            else: raise ValueError(f'unsupported QA element: {kind}; use another renderer or author with supported primitives')
            opacity=element.get('opacity',1)
            if opacity!=1: layer.putalpha(layer.getchannel('A').point(lambda a:round(a*opacity)))
            canvas.alpha_composite(layer)
        self.limitations.update(self.registry.limitations)
        return canvas.convert('RGB')


def check_capabilities(page):
    background=page.get('background',{})
    if background.get('type','solid')!='solid':raise ValueError('QA supports solid page backgrounds only')
    if page.get('animations'):raise ValueError('QA cannot verify element animations; choose structural-only mode or remove them')
    for element in page['elements']:
        kind=element['elementType']
        if kind not in ('text','shape','image','line'):raise ValueError(f'unsupported QA element: {kind}')
        if element.get('rotation') or any(element.get('flip',[])):raise ValueError('QA does not support rotations/flips')
        if element.get('shadow') or element.get('crop'):raise ValueError('QA does not support shadows or explicit image crops')
        if kind=='shape' and element.get('shapeName','rect') not in ('rect','ellipse'):raise ValueError('QA supports rect/ellipse shapes only')
        fill=element.get('fill',{})
        if fill and fill.get('type','solid')!='solid':raise ValueError('QA supports solid shape fills only')
        border=element.get('border',{}) or {}
        if kind=='image' and border:raise ValueError('QA does not support image borders')
        if border.get('style','solid')!='solid':raise ValueError('QA supports solid borders only')
        if kind=='line':
            if len(element['points'].split())!=2 or element.get('curve','sharp')!='sharp':raise ValueError('QA supports straight two-point sharp lines only')
            if element.get('arrow',[None,None])[0] or element.get('arrow',[None,None])[1] not in (None,'arrow'):raise ValueError('QA supports a triangular end arrow only')
        if kind=='text':
            content=element['content']
            if content.get('textDirection','horizontal')!='horizontal' or any(content.get(k) for k in ('gradient','shadow','backgroundColor','letterSpacing','marginTop','lineHeightPx')):raise ValueError('unsupported QA text layout/decoration; use basic text or structural-only mode')
            if content.get('align',['left','top'])[0] not in ('left','center','right'):raise ValueError('QA does not support justified/distributed text')


def main():
    configure_utf8_console()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path); parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--font',type=Path); parser.add_argument('--math-font',type=Path)
    parser.add_argument('--fonts',type=Path)
    parser.add_argument('--scale',type=float,default=2)
    args=parser.parse_args(); manifest=args.manifest.resolve(); deck=parse_yaml(manifest.read_text(encoding='utf-8')); args.output.mkdir(parents=True,exist_ok=True)
    config=json.loads(args.fonts.read_text(encoding='utf-8')) if args.fonts else None
    if not config and (not args.font or not args.math_font):parser.error('use --fonts, or both --font and --math-font')
    if not 0.5<=args.scale<=4:parser.error('--scale must be between 0.5 and 4')
    renderer=Renderer(manifest.parent,deck,args.scale,args.font,args.math_font,config,args.fonts.parent if args.fonts else None); thumbnails=[]; records=[]
    for i,path in enumerate(deck['pages'],1):
        page=page_value(parse_yaml(project_path(manifest.parent,path).read_text(encoding='utf-8')))
        image=renderer.page(page,i); target=args.output/f'{i:02}.png'; image.save(target)
        thumb=image.copy(); thumb.thumbnail((480,270)); thumbnails.append(thumb); records.append(dict(page=i,source=path,image=str(target)))
    overview=Image.new('RGB',(480*3,300*math.ceil(len(thumbnails)/3)),'#E8E8E8'); draw=ImageDraw.Draw(overview)
    for i,image in enumerate(thumbnails):
        x=(i%3)*480; y=(i//3)*300; overview.paste(image,(x,y+25)); draw.text((x+12,y+5),f'P{i+1}',fill='black')
    overview.save(args.output/'overview.jpg',quality=92)
    report=dict(renderer='native-pillow-layout-proof',officeRenderVerified=False,pages=records,warnings=renderer.warnings,limitations=sorted(renderer.limitations))
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(pages=len(records),overview=str(args.output/'overview.jpg'),warnings=renderer.warnings),ensure_ascii=False))
    return 1 if renderer.warnings else 0

if __name__=='__main__': raise SystemExit(main())
