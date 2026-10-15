#!/usr/bin/env node
import {cpSync,existsSync,mkdirSync,mkdtempSync,renameSync,rmSync,readFileSync} from 'node:fs';
import {homedir} from 'node:os';
import {dirname,join,resolve,basename} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn,spawnSync} from 'node:child_process';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const args=process.argv.slice(2);const command=['install','serve','export','fonts'].includes(args[0])?args.shift():'install';
let targets=[],port=55174,project,output,open=false,all=false,force=false,embedFonts=false;
function python() {
  for(const [name,prefix] of process.env.PYTHON?[[process.env.PYTHON,[]]]:process.platform==='win32'?[['python',[]],['py',['-3']],['python3',[]]]:[['python3',[]],['python',[]]]) {
    const result=spawnSync(name,[...prefix,'-c','import sys; print(sys.executable)'],{encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});
    if(result.status===0)return result.stdout.trim();
  }
  throw new Error('Python 3.12+ is required. Install Python, then python -m pip install -r requirements.txt; or set PYTHON to its executable path.');
}
function install(target) {
  const directory=resolve(target);mkdirSync(directory,{recursive:true});
  const stage=mkdtempSync(join(directory,'.pptd-install-'));const destination=join(directory,'pptd-deck-skill');const staged=join(stage,'pptd-deck-skill');const backup=join(stage,'previous');
  try {
    cpSync(join(root,'skills/pptd-deck-skill'),staged,{recursive:true,filter:p=>!['tests','__pycache__','node_modules','.DS_Store'].includes(basename(p))});
    for(const name of ['LICENSE','THIRD_PARTY_NOTICES.md'])cpSync(join(root,name),join(staged,name));
    if(existsSync(destination))renameSync(destination,backup);
    try {renameSync(staged,destination);}catch(error){if(existsSync(backup))renameSync(backup,destination);throw error;}
    console.log(`Installed native skill: ${destination}`);
  } finally {rmSync(stage,{recursive:true,force:true});}
}
async function main() {
  if(Number(process.versions.node.split('.')[0])<18)throw new Error('Node 18+ required');
  if(command==='fonts') {
    const script=join(root,'skills/pptd-deck-skill/scripts/local-export/native_font_catalog.py');
    const result=spawnSync(python(),[script,...args],{env:{...process.env,PYTHONUTF8:'1'},stdio:'inherit'});
    if(result.error)throw result.error;
    process.exitCode=result.status??1;return;
  }
  while(args.length) {
    const arg=args.shift();
    if(arg==='--help'||arg==='-h'){console.log('PPTD Deck Skill\ninstall [-y] [--target DIRECTORY] [--all]\nserve [PROJECT] [--port PORT] [--open]\nexport PROJECT --output FILE.pptx [--embed-fonts]\nfonts list\nfonts add PROJECT --family ID [--family ID] [--write-config]\nPython 3.12+ + PyYAML; Pillow for layout QA. --open opens the native web editor.');return;}
    if(arg==='--version'||arg==='-V'){console.log(JSON.parse(readFileSync(join(root,'package.json'),'utf8')).version);return;}
    if(['--target','--port','--output'].includes(arg)) {
      const value=args.shift();if(!value||value.startsWith('--'))throw new Error(`${arg} requires a value`);
      if(arg==='--target')targets.push(resolve(value));if(arg==='--port')port=Number(value);if(arg==='--output')output=resolve(value);continue;
    }
    if(['--yes','-y'].includes(arg))continue;
    if(arg==='--force'){force=true;continue;}
    if(arg==='--embed-fonts'){embedFonts=true;continue;}
    if(arg==='--all'){all=true;continue;}if(arg==='--open'){open=true;continue;}
    if(!arg.startsWith('-')&&!project&&command!=='install'){project=resolve(arg);continue;}throw new Error('Unknown argument: '+arg);
  }
  if(command==='install') {
    if(all)targets.push(...['.agents','.codex','.claude','.cursor','.workbuddy'].filter(n=>existsSync(join(homedir(),n))).map(n=>join(homedir(),n,'skills')));
    if(!targets.length)targets.push(join(homedir(),'.agents/skills'));
    for(const target of new Set(targets))install(target);return;
  }
  if(!Number.isInteger(port)||port<0||port>65535)throw new Error('port must be 0..65535');
  if(command==='export'&&(!project||!output))throw new Error('export requires PROJECT and --output');
  const script=join(root,'skills/pptd-deck-skill/scripts/local-export',command==='serve'?'native_editor.py':'native_cli.py');
  const values=command==='serve'?[...(project?[project]:[]),'--port',String(port)]:[project,'--output',output,...(force?['--force']:[]),...(embedFonts?['--embed-fonts']:[])];
  const child=spawn(python(),[script,...values],{env:{...process.env,PYTHONUTF8:'1'},stdio:['inherit','pipe','inherit']});
  let opened=false;
  child.stdout.on('data',buffer=>{
    process.stdout.write(buffer);
    const match=buffer.toString().match(/http:\/\/127\.0\.0\.1:\d+\/#[\w-]+/);
    if(open&&!opened&&match){opened=true;const command=process.platform==='win32'?'cmd':process.platform==='darwin'?'open':'xdg-open';const values=process.platform==='win32'?['/c','start','',match[0]]:[match[0]];const browser=spawn(command,values,{stdio:'ignore',detached:true});browser.on('error',e=>console.error(e.message));browser.unref();}
  });
  child.on('error',error=>{console.error(error.message);process.exitCode=1;});
  child.on('exit',code=>{process.exitCode=code??1;});
  for(const signal of ['SIGINT','SIGTERM'])process.once(signal,()=>child.kill(signal));
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
