import React,{useRef,useState} from 'react'
import{createRoot}from'react-dom/client'
import{Canvas,useFrame}from'@react-three/fiber'
import{Roots}from'./src/Roots'
import data from'../verification/m3vl/fresh/final-live-feed.json'
import type{VisualizationSnapshot}from'./src/visualization'
const feed=data as unknown as VisualizationSnapshot
function Meter({report}:{report:(s:string)=>void}){const state=useRef({warm:0,seconds:0,frames:0,samples:[] as number[]});useFrame(({camera},delta)=>{const s=state.current;s.warm+=delta;camera.position.set(Math.sin(s.warm*.08)*6,2,18);camera.lookAt(0,0,0);if(s.warm<2)return;s.frames++;s.seconds+=delta;if(s.seconds>=1&&s.samples.length<12){s.samples.push(Math.round(s.frames/s.seconds));s.frames=0;s.seconds=0;report(JSON.stringify({tier:'efficient',agents:feed.agents.length,capillaries:feed.agents.reduce((n,a)=>n+(a.touched_files?.length??0),0),fps:s.samples,minimum:Math.min(...s.samples),complete:s.samples.length===12}));}});return null}
function App(){const[value,setValue]=useState('warming');return <><h1>PERFORMANCE FIXTURE · recorded real data · synthetic camera orbit only</h1><pre id="measurement">{value}</pre><div style={{width:1230,height:318}}><Canvas dpr={1} camera={{fov:42,position:[0,2,18]}} gl={{antialias:false}}><ambientLight intensity={.65}/><directionalLight position={[0,8,12]} color="#eff8fa" intensity={4}/><directionalLight position={[-8,-4,6]} color="#436ac5" intensity={3}/><pointLight position={[8,4,8]} color="#e8b29f" intensity={45}/><Roots data={feed} agents={feed.agents} selectedId={null} tier="efficient" pick={()=>{}} newest={false}/><Meter report={setValue}/></Canvas></div></>}
createRoot(document.getElementById('root')!).render(<App/>);
