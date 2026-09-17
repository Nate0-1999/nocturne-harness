/** PLAN M3OU / B.6: browser regressions use explicit speech doubles; native_walk proves native audio separately. */
import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {mkdir,writeFile} from 'node:fs/promises'
const require=createRequire(new URL('../../web/package.json',import.meta.url))
const {chromium}=require('playwright-core')
const arg=name=>process.argv[process.argv.indexOf(name)+1]
const base=arg('--base-url'), fixture=arg('--fixture'), output=arg('--evidence-dir')
if(process.argv.includes('--restore')) process.exit(0) // This speech regression has no daemon-restoration contract.
const browser=await chromium.launch({channel:'chrome',headless:true})
const context=await browser.newContext({viewport:{width:1440,height:1000}})
await context.addInitScript(()=>{
 window.speechTest={recognitions:[],utterances:[],cancelled:0}
 window.SpeechRecognition=class {
   constructor(){window.speechTest.recognitions.push(this);this.results=[];this.active=false}
   start(){this.active=true;this.onaudiostart?.()}
   stop(){this.active=false;this.onend?.()}
   abort(){this.active=false;this.onend?.()}
   dictate(text,final=true){this.results.push({isFinal:final,0:{transcript:text}});this.onresult?.({results:this.results})}
 }
 window.SpeechSynthesisUtterance=class{constructor(text){this.text=text}}
 Object.defineProperty(window,'speechSynthesis',{value:{
  speak(utterance){window.speechTest.utterances.push(utterance);queueMicrotask(()=>utterance.onstart?.())},
  cancel(){window.speechTest.cancelled++},
 }})
})
const page=await context.newPage()
const conversation=()=>page.frameLocator('[data-testid="rack-plugin-frame-conversation"]')
const contentFrame=()=>page.frames().find(f=>f.url().includes('rack_module=conversation'))
const wait=async predicate=>{for(let n=0;n<150;n++){if(await predicate())return;await page.waitForTimeout(100)}throw Error('Timed out waiting for browser state')}
const dictate=async text=>contentFrame().evaluate(text=>window.speechTest.recognitions.at(-1).dictate(text),text)
try{
 await mkdir(output,{recursive:true})
 await page.goto(`${base}/?fixture=${encodeURIComponent(fixture)}`)
 await page.getByRole('button',{name:'Sheet',exact:true}).click()
 await conversation().getByTestId('composer').waitFor()
 await conversation().getByRole('button',{name:'Out Loud',exact:true}).click()
 await wait(()=>contentFrame().evaluate(()=>window.speechTest.recognitions.at(-1)?.active))
 await dictate('Out Loud regression: answer the heartbeat check.')
 await wait(async()=>await conversation().getByTestId('composer').inputValue()==='Out Loud regression: answer the heartbeat check.')
 assert.equal(await conversation().locator('.message--user').count(),0,'Dictation does not send before the trigger word')
 await page.screenshot({path:`${output}/dictation-draft.png`})
 await dictate('Send.')
 const gate=page.frameLocator('[data-testid="rack-plugin-frame-gate"]')
 await gate.getByTestId('memory-gate').waitFor({timeout:60000})
 assert.equal(await conversation().getByTestId('send').isEnabled(),false)
 assert.equal(await contentFrame().evaluate(()=>window.speechTest.recognitions.at(-1).active),false)
 await gate.getByTestId('memory-gate-continue').click()
 await wait(()=>contentFrame().evaluate(()=>window.speechTest.utterances.length>0))
 const spoken=await contentFrame().evaluate(()=>window.speechTest.utterances.at(-1).text)
 assert.match(spoken,/M2H final post/)
 await page.screenshot({path:`${output}/response-read-aloud.png`})
 await contentFrame().evaluate(()=>window.speechTest.utterances.at(-1).onend())
 await wait(()=>contentFrame().evaluate(()=>window.speechTest.recognitions.at(-1)?.active))
 await dictate('An editable spoken draft')
 await conversation().getByTestId('composer').fill('Edited with the keyboard')
 assert.equal(await contentFrame().evaluate(()=>window.speechTest.recognitions.at(-1).active),false)
 await conversation().getByRole('button',{name:'Read aloud',exact:true}).click()
 await conversation().getByRole('button',{name:'Interrupt and listen',exact:true}).click()
 assert.equal(await contentFrame().evaluate(()=>window.speechTest.recognitions.at(-1).active),true)
 assert.ok(await contentFrame().evaluate(()=>window.speechTest.cancelled>0))
 await conversation().getByRole('button',{name:'Typing',exact:true}).click()
 assert.equal(await contentFrame().evaluate(()=>window.speechTest.recognitions.at(-1).active),false)
 await conversation().getByRole('button',{name:'Out Loud',exact:true}).click()
 await page.reload()
 await page.getByRole('button',{name:'Sheet',exact:true}).click()
 await wait(async()=>await conversation().getByRole('button',{name:'Out Loud',exact:true}).getAttribute('aria-pressed')==='true')
 await conversation().getByRole('button',{name:'Typing',exact:true}).click()
 await conversation().getByRole('button',{name:'Out Loud',exact:true}).click()
 await wait(()=>contentFrame().evaluate(()=>window.speechTest.recognitions.at(-1)?.active))
 await contentFrame().evaluate(()=>{
  const recognition=window.speechTest.recognitions.at(-1)
  recognition.onerror({error:'not-allowed'});recognition.onend()
 })
 await conversation().getByText('Microphone access is blocked.',{exact:false}).waitFor()
 await page.screenshot({path:`${output}/microphone-denied.png`})
 await conversation().getByRole('button',{name:'Typing',exact:true}).click()
 await page.setViewportSize({width:390,height:844})
 await page.getByRole('button',{name:'Stage',exact:true}).click()
 await page.getByRole('navigation',{name:'Off-screen modules'}).getByRole('button',{name:'Conversation',exact:true}).click()
 await conversation().getByTestId('composer').scrollIntoViewIfNeeded()
 await page.mouse.move(0,0)
 await page.waitForTimeout(500)
 console.log('Phone conversation',await page.locator('[data-rack-module="conversation"]').boundingBox())
 await page.screenshot({path:`${output}/phone.png`})
 const unsupported=await browser.newContext()
 await unsupported.addInitScript(()=>{delete window.SpeechRecognition;delete window.webkitSpeechRecognition})
 const fallback=await unsupported.newPage()
 await fallback.goto(`${base}/?fixture=${encodeURIComponent(fixture)}`)
 const fallbackConversation=fallback.frameLocator('[data-testid="rack-plugin-frame-conversation"]')
 await fallbackConversation.getByText('This browser does not support Out Loud. Typing is available.').waitFor()
 assert.equal(await fallbackConversation.getByRole('button',{name:'Out Loud',exact:true}).isDisabled(),true)
 assert.equal(await fallbackConversation.getByTestId('composer').isEnabled(),true)
 await fallback.screenshot({path:`${output}/unsupported-browser.png`})
 await unsupported.close()
 const result={speech_doubles:true,dictation_waits_for_send:true,send_uses_memory_gate:true,response_spoken:true,listening_after_response:true,typing_interrupts_dictation:true,tap_interrupts_speech:true,preference_survives_reload:true,microphone_denied_explained:true,unsupported_keeps_typing:true}
 await writeFile(`${output}/regression.json`,JSON.stringify(result,null,2))
 console.log('Out Loud browser regression PASS',result)
}catch(error){
 await page.screenshot({path:`${output}/failure.png`})
 console.error(await contentFrame()?.evaluate(()=>({text:document.body.innerText,speech:window.speechTest})))
 throw error
}finally{await browser.close()}
