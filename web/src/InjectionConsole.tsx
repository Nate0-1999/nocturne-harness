import { useEffect, useState } from 'react'
import { ContributionBars } from './ContributionBars'
import { useRackPlugin, useRackSnapshot } from './rack'

type Values = { tau: number; top_k: number; budget_tokens: number; half_life_time_days: number; half_life_hist_days: number; weights: Record<string, number> }
type Config = { version: string; status: string; values: Values }
type Point = { score: string; rank: number; shown_as: string; contributions: Record<string, string> }
type Snapshot = { active_version: string; configurations: Config[]; proposed_versions: Config[]; accuracy: { version: string; status: string; accuracy_percent: string | null }[]; candidates: { memory_id: string; label: string; points: Point[] }[] }
const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
const CONTROL_LABELS: Record<string, string> = {
  tau: 'Minimum match', top_k: 'Memories considered', budget_tokens: 'Context budget',
  half_life_time_days: 'Recent-use fade (days)', half_life_hist_days: 'Past-choice fade (days)',
}
const WEIGHT_LABELS: Record<string, string> = {
  sem: 'Meaning', kw: 'Keywords', time: 'Recency', proj: 'Project', freq: 'Use count', hist: 'Past choices',
}
function ulid(): string { let time = Date.now(); let out = ''; for (let i=0;i<10;i++){ out=ALPHABET[time%32]+out; time=Math.floor(time/32) } const bytes=crypto.getRandomValues(new Uint8Array(16)); for(let i=0;i<16;i++) out+=ALPHABET[bytes[i]%32]; return out }

export function InjectionConsole() {
  const { query, events } = useRackPlugin(); const rack = useRackSnapshot()
  const [scope, setScope] = useState<'GLOBAL'|'CURRENT'>('GLOBAL'); const [data, setData] = useState<Snapshot|null>(null); const [draft, setDraft] = useState<Values|null>(null); const [failure, setFailure] = useState<string|null>(null)
  const load = () => query.query({ resource:'scorer_console', as_of:'now', thread_id: scope === 'CURRENT' ? rack.selectedThreadId ?? undefined : undefined }).then((r) => { const next=r.data as unknown as Snapshot; setData(next); setDraft(next.configurations.find((c)=>c.version===next.active_version)?.values ?? null); setFailure(null) }).catch(()=>setFailure('Memory tuning is temporarily unavailable.'))
  useEffect(()=>{ void events.dispatch({type:'rack.scope.get',module_id:'injection_console'}).then(setScope) },[events])
  // The query surface is stable; scope/thread are the intended refresh keys.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(()=>{ void load() },[scope,rack.selectedThreadId])
  const weightSum = draft === null ? 0 : Object.values(draft.weights).reduce((a,b)=>a+b,0)
  const setNumber = (key: keyof Omit<Values,'weights'>, value:number) => setDraft((old)=>old===null?old:{...old,[key]:value})
  const setWeight = (key:string,value:number)=>setDraft((old)=>old===null?old:{...old,weights:{...old.weights,[key]:value}})
  async function enact(){ if(data===null||draft===null||Math.abs(weightSum-1)>0.000001)return; await events.dispatch({type:'scorer.write',event_uid:ulid(),base_version:data.active_version,values:draft as unknown as never}); await load() }
  return <section className="instrument instrument--console"><header><div><small>MEMORY TUNING</small><h1>Injection Console</h1></div><div className="scope-switch"><button aria-pressed={scope==='GLOBAL'} onClick={()=>setScope('GLOBAL')}>Global</button><button aria-pressed={scope==='CURRENT'} onClick={()=>setScope('CURRENT')}>Current</button></div></header>
    {failure!==null?<p role="alert">{failure}</p>:<div className="console-grid"><section><p className="console-active">Current recipe <strong>{data?.active_version}</strong></p>{draft&&<div className="control-bank">
      {(['tau','top_k','budget_tokens','half_life_time_days','half_life_hist_days'] as const).map((key)=><label key={key}><span>{CONTROL_LABELS[key]}</span><input type="number" value={draft[key]} min={key==='tau'?0:1} max={key==='tau'?1:undefined} step={key==='tau'?0.01:1} onChange={(e)=>setNumber(key,Number(e.target.value))}/></label>)}
      {Object.entries(draft.weights).map(([key,value])=><label key={key}><span>{WEIGHT_LABELS[key] ?? key}</span><input type="number" min="0" max="1" step="0.01" value={value} onChange={(e)=>setWeight(key,Number(e.target.value))}/></label>)}
      <p className={Math.abs(weightSum-1)<0.000001?'weight-ok':'weight-bad'}>Influence total {weightSum.toFixed(2)} / 1.00</p><button className="enact" disabled={Math.abs(weightSum-1)>0.000001} onClick={()=>void enact()}>Use this recipe</button>
    </div>}{(data?.proposed_versions ?? []).map((proposal)=><button key={proposal.version} onClick={()=>void events.dispatch({type:'scorer.activate',event_uid:ulid(),version:proposal.version}).then(load)}>Use suggested recipe {proposal.version}</button>)}</section>
    <section className="candidate-ledger"><h2>Why memories surfaced</h2>{(data?.candidates ?? []).map((candidate)=>{const point=candidate.points.at(-1);return <article key={candidate.memory_id}><header><strong>{candidate.label}</strong><span>{point?`${point.score} · #${point.rank} ${point.shown_as}`:'Not measured yet'}</span></header><ContributionBars values={point?.contributions}/></article>})}{data?.candidates.length===0&&<p>Nothing measured yet.</p>}</section></div>}
  </section>
}
