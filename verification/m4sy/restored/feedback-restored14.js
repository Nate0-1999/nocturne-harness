await page.locator('[data-testid="rack-plugin-frame-conversation"]').scrollIntoViewIfNeeded();
await page.getByRole('button', {name:'Deck',exact:true}).click(); await sleep(1200);
const stack=frame('conversation').locator('article.deck-stack').first();
const detail=stack.locator('details').filter({hasText:'Judge feedback'}).first();
if(await detail.getAttribute('open')===null)await detail.locator('summary').click();
await detail.scrollIntoViewIfNeeded();
await shot('small-14/FL-091-feedback-retained',{module:'conversation'});
return {state:await stack.getAttribute('data-state'),feedback:await detail.innerText()};
