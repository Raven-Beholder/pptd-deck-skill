"""Native-only compatibility entrypoint with optional local project fonts."""
import sys
import yaml
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'local-export'))
from native_cli import export, main
from native_common import NativeExportError as ExportError
from native_validation import verify_output

def export_pptx(project,output,transition='fade',force=False,backend='native',embed_fonts=False,prefer_local=True,keep_download=False,**options):
    if backend!='native' or not prefer_local or keep_download or options:raise ExportError('native backend cannot be combined with legacy or browser options')
    result=export(project,output,transition,force,embed_fonts=embed_fonts)
    result['validation']=verify_output(output,transition,embed_fonts)
    result.update(result['validation'])
    return result
if __name__=='__main__':raise SystemExit(main())
