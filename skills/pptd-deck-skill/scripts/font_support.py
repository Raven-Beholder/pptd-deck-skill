"""Small SFNT cmap reader for deterministic missing-glyph checks (TTF/OTF/TTC)."""
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path
import struct

class Face:
    def __init__(self, path, index=0):
        self.path=Path(path); self.index=index; self.data=self.path.read_bytes()
        if len(self.data)>100*1024*1024: raise ValueError('font exceeds 100 MiB')
        def u16(offset): return struct.unpack_from('>H',self.data,offset)[0]
        def u32(offset): return struct.unpack_from('>I',self.data,offset)[0]
        self.u16,self.u32=u16,u32
        if self.data[:4]==b'ttcf':
            count=u32(8)
            if not 0<=index<count<=128: raise ValueError('invalid font collection index')
            base=u32(12+index*4)
        else:
            if index: raise ValueError('non-collection font requires index 0')
            base=0
        count=u16(base+4)
        if count>128: raise ValueError('too many SFNT tables')
        tables={}
        for i in range(count):
            tag,_,start,length=struct.unpack_from('>4sIII',self.data,base+12+i*16)
            if start+length>len(self.data): raise ValueError('font table outside file')
            tables[tag]=(start,length)
        start,length=tables[b'cmap']; cmap_count=u16(start+2)
        self.maps=[]
        for i in range(cmap_count):
            platform,encoding,offset=struct.unpack_from('>HHI',self.data,start+4+i*8)
            pos=start+offset; fmt=u16(pos)
            if (platform==0 or platform==3 and encoding in (1,10)) and fmt in (4,12):
                if fmt==12:
                    n=u32(pos+12)
                    if n>100000 or pos+16+n*12>start+length: raise ValueError('invalid cmap groups')
                    groups=[struct.unpack_from('>III',self.data,pos+16+j*12) for j in range(n)]
                    self.maps.append((12,groups,[g[0] for g in groups]))
                else:
                    n=u16(pos+6)//2; ends=pos+14; starts=ends+2*n+2; deltas=starts+2*n; ranges=deltas+2*n
                    if ranges+2*n>start+length: raise ValueError('invalid cmap segments')
                    self.maps.append((4,pos,n,ends,starts,deltas,ranges))
        if not self.maps: raise ValueError('font lacks a supported Unicode cmap')
    def supports(self, char):
        cp=ord(char)
        if char.isspace(): return True
        for item in self.maps:
            if item[0]==12:
                _,groups,starts=item; i=bisect_right(starts,cp)-1
                if i>=0:
                    a,b,g=groups[i]
                    if a<=cp<=b and g+cp-a: return True
            elif cp<=65535:
                _,pos,n,ends,starts,deltas,ranges=item
                for i in range(n):
                    end=self.u16(ends+2*i)
                    if cp>end: continue
                    begin=self.u16(starts+2*i)
                    if cp<begin: break
                    delta=self.u16(deltas+2*i); offset=self.u16(ranges+2*i)
                    glyph=(cp+delta)&65535 if not offset else self.u16(ranges+2*i+offset+2*(cp-begin))
                    if offset and glyph: glyph=(glyph+delta)&65535
                    if glyph: return True
                    break
        return False

@lru_cache(maxsize=128)
def _face(path,index,mtime,size): return Face(path,index)
def face(path,index=0):
    stamp=Path(path).stat()
    return _face(str(path),index,stamp.st_mtime_ns,stamp.st_size)

# Shared QA mathematical alphabets. Canonical AST remains unchanged for OMML.
def alphabet(text, variant):
    offsets={'mathbb':(0x1d538,0x1d552,0x1d7d8),'mathcal':(0x1d49c,0x1d4b6,None),
             'mathscr':(0x1d49c,0x1d4b6,None),'mathfrak':(0x1d504,0x1d51e,None),
             'mathsf':(0x1d5a0,0x1d5ba,0x1d7e2),'mathtt':(0x1d670,0x1d68a,0x1d7f6)}.get(variant)
    exceptions={'mathbb':dict(zip('CHNPQRZ','ℂℍℕℙℚℝℤ')),'mathcal':dict(zip('BEFHILMRego','ℬℰℱℋℐℒℳℛℯℊℴ')),'mathfrak':dict(zip('CHIRZ','ℭℌℑℜℨ'))}
    if not offsets: return text
    special=exceptions.get('mathcal' if variant=='mathscr' else variant,{})
    result=[]
    for char in text:
        if char in special: result.append(special[char]); continue
        code=ord(char); value=None
        for low,high,base in [(65,90,offsets[0]),(97,122,offsets[1]),(48,57,offsets[2])]:
            if base and low<=code<=high: value=chr(base+code-low); break
        result.append(value or char)
    return ''.join(result)

class FontRegistry:
    def __init__(self, config, root):
        self.config=config; self.root=Path(root); self.limitations=set()
        from native_fonts import families
        for family,mapping in config.get('families',{}).items():
            path,index,_=self.descriptor(family)
            if family not in families(path,index):raise ValueError(f'font family {family} does not match mapped file {path} at index {index}')
            face(str(path),index)
    def descriptor(self, family, math_mode=False, bold=False, italic=False):
        if isinstance(family,dict): raise ValueError('QA requires a single fontFamily; use one mapped multilingual family')
        mapping=self.config.get('math') if math_mode else self.config['families'].get(family)
        if not mapping: raise ValueError(f'font family not mapped: {family}; add it to fonts.json or choose a mapped family')
        key='boldItalic' if bold and italic else 'bold' if bold else 'italic' if italic else 'regular'
        spec=mapping.get(key); synthetic=False
        if spec is None:
            if key!='regular' and mapping.get('syntheticStyles'):
                spec=mapping['regular']; synthetic=True
                self.limitations.add(f'synthetic {key}: {family}')
            else: raise ValueError(f'font style not mapped: {family}/{key}')
        if isinstance(spec,str): spec={'path':spec}
        path=(self.root/spec['path']).resolve() if not Path(spec['path']).is_absolute() else Path(spec['path'])
        if not path.is_file(): raise ValueError(f'font file missing: {path}')
        return path,int(spec.get('index',0)),synthetic
    def files(self):
        result=set()
        for mapping in [*self.config.get('families',{}).values(),self.config.get('math',{})]:
            for key in ['regular','bold','italic','boldItalic']:
                if key in mapping:
                    spec=mapping[key]; spec={'path':spec} if isinstance(spec,str) else spec
                    path=Path(spec['path']); result.add((self.root/path).resolve() if not path.is_absolute() else path)
        return sorted(result)
