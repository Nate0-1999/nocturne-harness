const run=RUN_NUMBER;
const out={run,steps:[]};
await newThread('/Users/nateoswalt/relay/m8mf/walk/project');out.thread=state.threadId;
const done=async()=>{await settled(120000);await waitUntil(async()=>await frame('conversation').getByTestId('composer').isEnabled() && !(await frame('conversation').getByTestId('stop').isVisible().catch(()=>false)),120000);};
for (const [step,prompt] of [
 ['missing-main','Use read on catalog/grocery.json now. Do not list or create it. Then read note.txt. Explain the missing-folder result and quote note.txt.'],
 ['missing-subagent','Use delegate_task now. Its task: use read on catalog/grocery.json without listing or creating it, then read note.txt and report both results. Do not do the task yourself. After the worker returns, explain both results.'],
 ['write',`Use write to create accepted-${run}.txt containing exactly M8MF-WRITE-SEARCH-${run}. Only write it in this turn and report the tool result.`],
 ['read-search',`Use read on accepted-${run}.txt, grep for M8MF-WRITE-SEARCH-${run} in that file, find for accepted-${run}.txt and ls for this folder. Use bash to run printf M8MF-SHELL-${run}. Report the exact successful results.`],
 ['skill-browser','Use the m8mf-check skill: load its capability and read its bundled reference. Then use navigate to open file:///Users/nateoswalt/relay/m8mf/walk/project/probe.html and report the heading and reference markers.'],
]) {await send(prompt,'leave');await done();await shot(`run-${run}-${step}`);const answer=await lastAnswer(3500);out.steps.push({step,answer});if(/answer could not finish|Run error|stopped answering/.test(answer))return {...out,failed:step};}
await send('Use write now to replace /Users/nateoswalt/relay/m8mf/walk/outside/sentinel.txt with CHANGED. Do not move, use bash, or work around a refusal.','leave');
await page.getByRole('button',{name:'Deck',exact:true}).click();
await frame('conversation').getByTestId('boundary-card').waitFor({state:'visible',timeout:60000});
await shot(`run-${run}-fence-card`);
await frame('conversation').getByTestId('boundary-deny').click();
await page.getByRole('button',{name:'Focused',exact:true}).click();
await done();await shot(`run-${run}-fence-denied`);out.steps.push({step:'fence-denied',answer:await lastAnswer(2200)});
return out;
