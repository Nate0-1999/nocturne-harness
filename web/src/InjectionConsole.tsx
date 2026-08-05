import { useEffect, useMemo, useState } from 'react'
import { ContributionBars } from './ContributionBars'
import { useRackPlugin, useRackSnapshot } from './rack'

type Values = { tau: number; top_k: number; budget_tokens: number; half_life_time_days: number; half_life_hist_days: number; weights: Record<string, number> }
type Config = { version: string; status: string; values: Values }
type Point = { injection_id: string; ts: string; score: string; rank: number; shown_as: string; contributions: Record<string, string> }
type Candidate = { memory_id: string; label: string; points: Point[] }
type Comparison = { memory_id: string; preview_score: string; preview_rank: number; disposition: 'also_shown'|'would_add'|'would_drop'|'still_out' }
type Instant = { status: 'ready'|'not_requested'|'not_replayable'; candidates: Comparison[] }
type Slice = { parameter_id: string; points: { value: number; accuracy_percent: string|null }[] }
type Simulation = { simulation_digest: string; base_version: string; values: Values; holdout_dispositions: number; accuracy_percent: string|null; incumbent_accuracy_percent: string|null; delta_percent: string|null; instant: Instant; slice: Slice }
type Audition = { proposal_version: string; instant: Instant }
type Snapshot = { active_version: string; configurations: Config[]; proposed_versions: Config[]; accuracy: { version: string; status: string; accuracy_percent: string | null }[]; candidates: Candidate[] }
const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
const CONTROL_LABELS: Record<string, string> = {
  tau: 'Minimum match', top_k: 'Memories considered', budget_tokens: 'Context budget',
  half_life_time_days: 'Recent-use fade (days)', half_life_hist_days: 'Past-choice fade (days)',
}
const WEIGHT_LABELS: Record<string, string> = {
  sem: 'Meaning', kw: 'Keywords', time: 'Recency', proj: 'Project', freq: 'Use count', hist: 'Past choices',
}
function ulid(): string { let time = Date.now(); let out = ''; for (let i=0;i<10;i++){ out=ALPHABET[time%32]+out; time=Math.floor(time/32) } const bytes=crypto.getRandomValues(new Uint8Array(16)); for(let i=0;i<16;i++) out+=ALPHABET[bytes[i]%32]; return out }
function latestInjection(candidates: Candidate[]): string|undefined {
  return candidates.flatMap((candidate)=>candidate.points).sort((left,right)=>left.ts.localeCompare(right.ts)).at(-1)?.injection_id
}

export function InjectionConsole() {
  const { query, events } = useRackPlugin(); const rack = useRackSnapshot()
  const [scope, setScope] = useState<'GLOBAL'|'CURRENT'>('GLOBAL'); const [data, setData] = useState<Snapshot|null>(null); const [draft, setDraft] = useState<Values|null>(null); const [preview, setPreview] = useState<Instant|null>(null); const [receipt, setReceipt] = useState<Simulation|null>(null); const [audition, setAudition] = useState<Audition|null>(null); const [sliceParameter, setSliceParameter] = useState('scorer.tau'); const [busy, setBusy] = useState(false); const [failure, setFailure] = useState<string|null>(null)
  const load = () => query.query({ resource:'scorer_console', as_of:'now', thread_id: scope === 'CURRENT' ? rack.selectedThreadId ?? undefined : undefined }).then((r) => { const next=r.data as unknown as Snapshot; setData(next); setDraft(next.configurations.find((c)=>c.version===next.active_version)?.values ?? null); setPreview(null); setReceipt(null); setAudition(null); setFailure(null) }).catch(()=>setFailure('Memory tuning is temporarily unavailable.'))
  useEffect(()=>{ void events.dispatch({type:'rack.scope.get',module_id:'injection_console'}).then(setScope) },[events])
  // The query surface is stable; scope/thread are the intended refresh keys.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(()=>{ void load() },[scope,rack.selectedThreadId])
  const weightSum = draft === null ? 0 : Object.values(draft.weights).reduce((a,b)=>a+b,0)
  const valid = draft !== null && Math.abs(weightSum-1)<0.000001
  const injectionId = useMemo(()=>scope === 'CURRENT' && data !== null ? latestInjection(data.candidates) : undefined,[data,scope])
  useEffect(()=>{
    if(data===null||draft===null||!valid)return
    const timer=globalThis.setTimeout(()=>{void events.dispatch({type:'scorer.simulate',injection_id:injectionId,base_version:data.active_version,values:draft as unknown as never,slice_parameter_id:sliceParameter}).then((result)=>setPreview((result as unknown as Simulation).instant)).catch(()=>setPreview(null))},180)
    return()=>globalThis.clearTimeout(timer)
  },[data,draft,events,injectionId,sliceParameter,valid])
  const clearSimulation = () => { setReceipt(null); setPreview(null) }
  const setNumber = (key: keyof Omit<Values,'weights'>, value:number) => { clearSimulation(); setDraft((old)=>old===null?old:{...old,[key]:value}) }
  const setWeight = (key:string,value:number)=>{ clearSimulation(); setDraft((old)=>old===null?old:{...old,weights:{...old.weights,[key]:value}}) }
  async function simulate(){ if(data===null||draft===null||!valid)return; setBusy(true); try { const result=await events.dispatch({type:'scorer.simulate',injection_id:injectionId,base_version:data.active_version,values:draft as unknown as never,slice_parameter_id:sliceParameter}) as unknown as Simulation; setReceipt(result); setPreview(result.instant); setFailure(null) } catch { setFailure('The simulation could not be completed.') } finally { setBusy(false) } }
  async function enact(){ if(data===null||draft===null||receipt===null||!valid)return; setBusy(true); try { await events.dispatch({type:'scorer.force',event_uid:ulid(),base_version:data.active_version,values:draft as unknown as never,simulation_digest:receipt.simulation_digest}); await load() } catch { setReceipt(null); setFailure('Evidence changed. Run DEEP again before forcing this recipe.') } finally { setBusy(false) } }
  async function tryProposal(version:string){ if(injectionId===undefined){setFailure('Select a thread with a frozen gate to audition this proposal.');return} const result=await events.dispatch({type:'scorer.audition',injection_id:injectionId,proposal_version:version}) as unknown as Audition; setAudition(result) }
  const comparisonByMemory=new Map((audition?.instant.candidates ?? preview?.candidates ?? []).map((row)=>[row.memory_id,row]))
  return <section className="instrument instrument--console"><header><div><small>MEMORY TUNING</small><h1>Injection Console</h1></div><div className="scope-switch"><button aria-pressed={scope==='GLOBAL'} onClick={()=>setScope('GLOBAL')}>Global</button><button aria-pressed={scope==='CURRENT'} onClick={()=>setScope('CURRENT')}>Current</button></div></header>
    {failure!==null&&<p role="alert">{failure}</p>}<div className="console-grid"><section><p className="console-active">Current recipe <strong>{data?.active_version}</strong></p>{draft&&<div className="control-bank">
      {(['tau','top_k','budget_tokens','half_life_time_days','half_life_hist_days'] as const).map((key)=><label key={key}><span>{CONTROL_LABELS[key]}</span><input type="number" value={draft[key]} min={key==='tau'?0:1} max={key==='tau'?1:undefined} step={key==='tau'?0.01:1} onChange={(e)=>setNumber(key,Number(e.target.value))}/></label>)}
      {Object.entries(draft.weights).map(([key,value])=><label key={key}><span>{WEIGHT_LABELS[key] ?? key}</span><input type="number" min="0" max="1" step="0.01" value={value} onChange={(e)=>setWeight(key,Number(e.target.value))}/></label>)}
      <p className={valid?'weight-ok':'weight-bad'}>Influence total {weightSum.toFixed(2)} / 1.00</p><label><span>Accuracy slice</span><select value={sliceParameter} onChange={(event)=>{clearSimulation();setSliceParameter(event.target.value)}}>{['tau','top_k','budget_tokens','half_life_time_days','half_life_hist_days',...Object.keys(draft.weights).map((key)=>`weight.${key}`)].map((key)=><option key={key} value={`scorer.${key}`}>{CONTROL_LABELS[key] ?? WEIGHT_LABELS[key.replace('weight.','')] ?? key}</option>)}</select></label>
      <div className="simulation-actions"><button disabled={!valid||busy} onClick={()=>void simulate()}>Run DEEP simulation</button><button className="enact" disabled={receipt===null||busy} onClick={()=>void enact()}>FORCE exact recipe</button></div>
      {receipt&&<div className="simulation-receipt" aria-label="Deep simulation receipt"><strong>{receipt.accuracy_percent ?? 'Not scored'} accuracy</strong><span>{receipt.delta_percent===null?'No held-out comparison':`${Number(receipt.delta_percent)>=0?'+':''}${receipt.delta_percent} points vs current`}</span><small>{receipt.holdout_dispositions} held-out dispositions · {receipt.simulation_digest.slice(0,12)}</small><AccuracyCurve slice={receipt.slice}/></div>}
      {scope==='GLOBAL'&&<p className="console-note">Global simulation has no fabricated gate preview.</p>}
      {preview?.status==='not_replayable'&&<p className="console-note">This older gate lacks exact replay inputs.</p>}
    </div>}{(data?.proposed_versions ?? []).map((proposal)=><div className="proposal-actions" key={proposal.version}><button disabled={injectionId===undefined} onClick={()=>void tryProposal(proposal.version)}>Audition suggested recipe {proposal.version}</button><button onClick={()=>void events.dispatch({type:'scorer.activate',event_uid:ulid(),version:proposal.version}).then(load)}>Use suggested recipe</button></div>)}</section>
    <section className="candidate-ledger"><h2>{audition?`Auditioning ${audition.proposal_version}`:'Why memories surfaced'}</h2>{(data?.candidates ?? []).map((candidate)=>{const point=candidate.points.at(-1);const comparison=comparisonByMemory.get(candidate.memory_id);return <article key={candidate.memory_id}><header><strong>{candidate.label}</strong><span>{comparison?`${comparison.preview_score} · #${comparison.preview_rank} ${comparison.disposition.replace('_',' ')}`:point?`${point.score} · #${point.rank} ${point.shown_as}`:'Not measured yet'}</span></header><ContributionBars values={point?.contributions}/></article>})}{data?.candidates.length===0&&<p>Nothing measured yet.</p>}</section></div>
  </section>
}

function AccuracyCurve({slice}:{slice:Slice}) {
  const measured=slice.points.filter((point):point is {value:number;accuracy_percent:string}=>point.accuracy_percent!==null)
  if(measured.length===0)return <p className="console-note">No held-out accuracy is available yet.</p>
  const values=measured.map((point)=>point.value);const scores=measured.map((point)=>Number(point.accuracy_percent));const minX=Math.min(...values);const maxX=Math.max(...values);const minY=Math.min(...scores);const maxY=Math.max(...scores)
  const points=measured.map((point)=>`${10+80*(point.value-minX)/Math.max(maxX-minX,1)},${90-80*(Number(point.accuracy_percent)-minY)/Math.max(maxY-minY,1)}`).join(' ')
  return <figure className="accuracy-curve"><svg role="img" aria-label={`Accuracy by ${slice.parameter_id}`} viewBox="0 0 100 100"><polyline points={points} fill="none" stroke="currentColor" strokeWidth="2"/></svg><figcaption>{slice.parameter_id} · {minY.toFixed(1)}–{maxY.toFixed(1)}%</figcaption></figure>
}
