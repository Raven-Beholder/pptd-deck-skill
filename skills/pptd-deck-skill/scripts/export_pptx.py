"""Native-only compatibility entrypoint. No legacy fallback or font embedding."""
import sys
import yaml
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'local-export'))
from native_cli import export, main
from native_common import NativeExportError as ExportError
from native_validation import verify_output

def export_pptx(project,output,transition='fade',force=False,backend='native',embed_fonts=False,prefer_local=True,keep_download=False,**options):
    if backend!='native' or embed_fonts or not prefer_local or keep_download or options:raise ExportError('native backend cannot be combined with legacy, embedding or browser options')
    result=export(project,output,transition,force)
    result['validation']=verify_output(output,transition,False)
    result.update(result['validation'])
    return result
if __name__=='__main__':raise SystemExit(main())
