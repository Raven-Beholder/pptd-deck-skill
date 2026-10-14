"""Record source hashes and reject vendor runtime/assets in the current tree."""
from pathlib import Path
import hashlib
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
BLOCKED={'.wasm','.woff','.woff2','.ttf','.otf','.ttc','.dll','.dylib','.exe'}
SKIP={'.git','dist','node_modules','.venv','__pycache__'}
def audit(root=ROOT):
    files={};errors=[]
    for path in sorted(root.rglob('*')):
        rel=path.relative_to(root)
        if any(part in SKIP for part in rel.parts) or not path.is_file():continue
        if rel.parts[0] in ('editor','lib') or path.suffix.lower() in BLOCKED or path.name=='reference-icons.mjs':errors.append(str(rel))
        if path.suffix in ('.py','.mjs','.js','.html','.css') and rel.as_posix()!='tools/audit_native_tree.py':
            text=path.read_text(encoding='utf-8')
            if any(marker in text for marker in ['pptd_wasm_bg','neo-ppt/assets','extract_reference_icons','from "./reference-icons.mjs"']):errors.append(str(rel)+' forbidden runtime reference')
        if rel.as_posix().startswith('docs/audit/'):continue
        files[rel.as_posix()]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
    if errors:raise ValueError('non-native material: '+', '.join(errors))
    return {'schemaVersion':1,'currentTreeNativeOnly':True,'historicalGitObjectsPurged':False,'certifiedCleanRoom':False,'thirdPartyRuntimeAssets':[],'files':files}
if __name__=='__main__':
    try:
        result=audit();out=ROOT/'docs/audit/native-tree.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps({'currentTreeNativeOnly':True,'files':len(result['files']),'manifest':str(out)}))
    except (ValueError,OSError) as e:print(str(e),file=sys.stderr);raise SystemExit(1)
