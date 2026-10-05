const RUNS=[{"n": 12, "project": "/private/tmp/m4sy-01a10a5b/walk/small-12", "thread": "fd725560-5577-4680-9fbb-dadfbc5eb5ec", "id": "01M46R4ZRYDDTTQ0BAJXJQSZXP"}, {"n": 13, "project": "/private/tmp/m4sy-01a10a5b/walk/small-13", "thread": "3453e70f-dd71-411c-bd92-7aba83e43fea", "id": "01M46RCHMA23GHTFWCK65FSHAC"}, {"n": 14, "project": "/private/tmp/m4sy-01a10a5b/walk/small-14", "thread": "89a42db1-8005-4467-8ee8-476d7665477c", "id": "01M46RNQB7XJMQDBM14WHYM6SM"}];
const results=[];
for (const run of RUNS) {
  const other=await newThread(run.project);
  const c=frame('conversation');
  const before=await c.locator('article').count();
  await c.getByLabel('Orchestration mode').selectOption('Symphony');
  await sleep(1500);
  const after=await c.locator('article').count();
  if(after!==before)throw new Error(`Run ${run.n}: selecting mode sent a message`);
  await shot(`small-${run.n}/mode-selection`,{module:'conversation'});
  const unrelated=await api(`/v1/rack/query?resource=recipe_graph&as_of=now&thread_id=${other}`);
  if(unrelated.data.nodes.length)throw new Error(`Run ${run.n}: unrelated plan returned`);
  await page.locator('[data-testid="rack-plugin-frame-recipe"]').scrollIntoViewIfNeeded();
  await sleep(2500);
  await shot(`small-${run.n}/recipe-unrelated`,{module:'recipe'});
  await page.locator('[data-testid="rack-plugin-frame-threads"]').scrollIntoViewIfNeeded();
  await page.getByRole('button',{name:'Focused',exact:true}).click();
  await frame('threads').locator('.thread-item').filter({hasText:run.thread.slice(0,8).toUpperCase()}).first().locator('.thread-item__select').click();
  await sleep(2500);
  const mode=await c.getByLabel('Orchestration mode').inputValue();
  const own=await api(`/v1/rack/query?resource=recipe_graph&as_of=now&thread_id=${run.thread}`);
  if(mode!=='Symphony'||own.data.packet_id!==run.id)throw new Error(`Run ${run.n}: selection did not restore its state`);
  await page.locator('[data-testid="rack-plugin-frame-conversation"]').scrollIntoViewIfNeeded();
  await c.getByTestId('symphony-result').last().locator('.symphony-card__header').evaluate(el=>el.scrollIntoView({block:'center'}));
  await shot(`small-${run.n}/FL-085-confirmed`,{module:'conversation'});
  results.push({n:run.n,before,after,otherNodes:unrelated.data.nodes.length,restoredMode:mode,ownPacket:own.data.packet_id});
}
return results;
