/** PLAN M3OU / B.6: real Web Speech audio-track input, native synthesis, real Palace/OpenRouter. */
import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
const require=createRequire(new URL('../../web/package.json',import.meta.url))
const {chromium}=require('playwright-core')
const base=process.env.M3OU_URL ?? 'http://127.0.0.1:8898'
const output=process.env.M3OU_EVIDENCE ?? '/private/tmp/m3ou-native-live'
const input=process.env.M3OU_AUDIO ?? '/private/tmp/m3ou-verification'
await mkdir(output,{recursive:true})
const recordings=await Promise.all(['prompt-send.wav','reply-send.wav'].map(async name=>(await readFile(`${input}/${name}`)).toString('base64')))
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--autoplay-policy=no-user-gesture-required']})
const context=await browser.newContext({viewport:{width:1440,height:1000},recordVideo:{dir:output,size:{width:1440,height:1000}}})
await context.addInitScript(recordings=>{
 window.speechEvidence=[]
 const Recognition=window.SpeechRecognition ?? window.webkitSpeechRecognition
 if(Recognition){
  class RecordedInput extends Recognition {
   constructor(){
    super(); this.generation=0
    for(const kind of ['start','audiostart','speechstart','speechend','audioend','end','error','result'])
     this.addEventListener(kind,event=>window.speechEvidence.push({kind,at:Date.now(),error:event.error,
      results:event.results&&Array.from(event.results).map(r=>({final:r.isFinal,text:r[0].transcript}))}))
    this.addEventListener('end',()=>this.releaseAudio())
   }
   start(){
    const generation=++this.generation
    const recording=new URL(location.href).searchParams.get('conversation_mode')==='stack'?recordings[1]:recordings[0]
    this.audio=new AudioContext()
    void this.audio.resume().then(()=>this.audio.decodeAudioData(Uint8Array.from(atob(recording),c=>c.charCodeAt(0)).buffer)).then(buffer=>{
     if(generation!==this.generation)return
     this.source=this.audio.createBufferSource();this.source.buffer=buffer
     const destination=this.audio.createMediaStreamDestination();this.source.connect(destination)
     super.start(destination.stream.getAudioTracks()[0]);this.source.start()
    })
   }
   releaseAudio(){this.source?.stop();this.source=null;void this.audio?.close().catch(()=>{});this.audio=null}
   abort(){++this.generation;super.abort();this.releaseAudio()}
   stop(){super.stop()}
  }
  window.SpeechRecognition=window.webkitSpeechRecognition=RecordedInput
 }
 const Utterance=window.SpeechSynthesisUtterance
 window.SpeechSynthesisUtterance=class extends Utterance{
  constructor(text){super(text);for(const kind of ['start','end','error'])this.addEventListener(kind,event=>window.speechEvidence.push({kind:`synthesis.${kind}`,at:Date.now(),text,error:event.error}))}
 }
},recordings)
const page=await context.newPage()
let identity;const traces={};const screenshots=[]
const conversation=()=>page.frameLocator('[data-testid="rack-plugin-frame-conversation"]')
const speechFrame=()=>page.frames().find(f=>f.url().includes('rack_module=conversation'))
const capture=async name=>{await page.mouse.move(0,0);await page.screenshot({path:`${output}/${name}.png`});screenshots.push(name)}
const wait=async predicate=>{for(let n=0;n<900;n++){if(await predicate())return;await page.waitForTimeout(100)}throw Error('Native voice state timed out')}
try{
 identity=await(await context.request.get(`${base}/v1/identity`)).json()
 assert.match(identity.principal_id,/^nocturne-verification-/)
 assert.equal(identity.home,process.env.M3OU_HOME ?? '/private/tmp/m3ou-verification/home')
 await page.goto(base)
 await page.getByRole('button',{name:'Sheet',exact:true}).click()
 await conversation().getByRole('button',{name:'Out Loud',exact:true}).click()
 await wait(async()=>/moon/i.test(await conversation().getByTestId('composer').inputValue()))
 await capture('out-loud-native-dictation')
 const gate=page.frameLocator('[data-testid="rack-plugin-frame-gate"]')
 await gate.getByTestId('memory-gate').waitFor({timeout:90000})
 traces.focused=await speechFrame().evaluate(()=>window.speechEvidence)
 assert.ok(traces.focused.some(e=>e.kind==='result'&&e.results.some(r=>r.final&&/^send[.!?]?$/i.test(r.text.trim()))))
 await capture('out-loud-voice-send-gate')
 await gate.getByTestId('memory-gate-continue').click()
 await wait(()=>speechFrame().evaluate(()=>window.speechEvidence.some(e=>e.kind==='synthesis.start')))
 await capture('out-loud-focused-read-aloud')
 traces.focused=await speechFrame().evaluate(()=>window.speechEvidence)
 await page.getByRole('button',{name:'Stack',exact:true}).click()
 await conversation().locator('.deck-proposal').first().waitFor({timeout:90000})
 await wait(()=>speechFrame().evaluate(()=>window.speechEvidence.some(e=>e.kind==='synthesis.start')))
 await capture('out-loud-stack-read-aloud')
 await wait(()=>speechFrame().evaluate(()=>window.speechEvidence.some(e=>e.kind==='synthesis.end')))
 await wait(async()=>/moonlight/i.test(await conversation().locator('textarea').first().inputValue()))
 await capture('out-loud-stack-dictation')
 await conversation().getByTestId('deck-undo').waitFor({timeout:90000})
 traces.stack=await speechFrame().evaluate(()=>window.speechEvidence)
 await capture('out-loud-card-fired')
 assert.ok(traces.stack.some(e=>e.kind==='result'&&e.results.some(r=>r.final&&/^send[.!?]?$/i.test(r.text.trim()))))
 await wait(async()=>!(await conversation().getByTestId('deck-undo').isVisible()))
 await conversation().getByRole('button',{name:'Typing',exact:true}).click({timeout:90000})
 await capture('out-loud-next-card')
 console.log('Native voice conversation PASS')
}finally{
 if(speechFrame())traces.last=await speechFrame().evaluate(()=>window.speechEvidence).catch(()=>[])
 await writeFile(`${output}/native.json`,JSON.stringify({identity,browser:await browser.version(),
  audio_source:'OS-synthesized fixture WAVs passed to native SpeechRecognition.start(audioTrack); no transcript injection; physical microphone not exercised',
  synthesis:'native SpeechSynthesisUtterance, unmodified playback',screenshots,traces},null,2))
 await context.close();await browser.close()
}
