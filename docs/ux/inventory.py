from pathlib import Path
import re,json,collections,sys,subprocess,argparse
p=argparse.ArgumentParser();p.add_argument("--ref");p.add_argument("--output");args=p.parse_args()
root=Path(__file__).resolve().parents[2]/'web/src'
if args.ref:
 repo=root.parents[1]
 names=subprocess.check_output(['git','ls-tree','-r','--name-only',args.ref,'web/src'],cwd=repo,text=True).splitlines()
 texts={name.removeprefix('web/src/'):subprocess.check_output(['git','show',args.ref+':'+name],cwd=repo,text=True) for name in names if Path(name).suffix in {'.tsx','.ts','.css'}}
else:
 texts={str(p.relative_to(root)):p.read_text() for p in root.rglob('*') if p.suffix in {'.tsx','.ts','.css'}}
files=list(texts);combined='\n'.join(texts.values())
routes=['/' + str(Path(name).parent).removeprefix('app').strip('/') for name in texts if name.endswith('/page.tsx')]
css={k:v for k,v in texts.items() if k.endswith('.css')};tokens={m for text in css.values() for m in re.findall(r'(--[A-Za-z][\w-]*)\s*:',text)};used={t:len(re.findall(r'var\(\s*'+re.escape(t)+r'\b',combined)) for t in tokens}
components=[]
for path,text in texts.items():
 for name in re.findall(r'(?:export\s+)?(?:function|const)\s+([A-Z]\w*)\s*(?:\(|=)',text):components.append({'file':path,'name':name,'name_mentions':len(re.findall(r'\b'+name+r'\b',combined))})
result={'routes':routes,'route_count':len(routes),'source_files':len(files),'component_declarations':len(components),'component_candidates_without_other_name_mentions':[c for c in components if c['name_mentions']==1],'css_tokens_defined':len(tokens),'css_var_reference_counts':used,'literal_color_occurrences':sum(len(re.findall(r'#[\da-fA-F]{3,8}\b|(?:rgb|hsl|oklch)\(',text)) for text in texts.values()),'tailwind_arbitrary_occurrences':sum(len(re.findall(r'\b[\w-]+-\[[^\]]+\]',text)) for text in texts.values()),'inline_style_attributes':sum(text.count('style={') for text in texts.values()),'state_markers_by_route':{p:{s:len(re.findall(s,texts.get('app/'+p.strip('/')+'/page.tsx' if p!='/' else 'app/page.tsx',''),re.I)) for s in ['empty','loading','error','success']} for p in routes},'motion_files':{p:len(re.findall(r'transition|animate-|@keyframes|duration-',s)) for p,s in texts.items() if re.search(r'transition|animate-|@keyframes|duration-',s)}}
if args.output: Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
