import {spawnSync} from 'node:child_process';
import {readdirSync} from 'node:fs';
const python=process.env.PYTHON||(process.platform==='win32'?'python':'python3');
const env={...process.env,PYTHONUTF8:'1',PYTHONDONTWRITEBYTECODE:'1'};
for(const [executable,args] of [[process.execPath,['--test',...readdirSync('test').filter(n=>n.endsWith('.test.js')).sort().map(n=>'test/'+n)]],[python,['-m','unittest','discover','-s','skills/pptd-deck-skill/tests','-p','test_*.py']]]) {
 const result=spawnSync(executable,args,{stdio:'inherit',env});
 if(result.error)throw result.error;
 if(result.status!==0)process.exit(result.status??1);
}
