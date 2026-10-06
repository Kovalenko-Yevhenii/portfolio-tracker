import React, {useCallback, useEffect, useRef, useState} from 'react';
import {Save, FolderOpen, Plus, Copy, RotateCcw} from 'lucide-react';
import {api} from './data.js';
import {emptyOptions,validOptions} from './options-model.js';
import {emptyAnalytics,validAnalytics} from './analytics-model.js';
import {emptyBacktest,validBacktest} from './backtest-model.js';
import {emptyCoveredCall,validCoveredCall} from './covered-call-model.js';

import {emptyCrypto,emptySurface,validCrypto,validSurface} from './research-model.js';

const PREFIX='portfolio-tracker.draft.v1.';
const ACTIVE='portfolio-tracker.active-draft.v1';
const uuid=()=>crypto.randomUUID();
const empty=()=>({id:uuid(),name:'',revision:0,state:null,savedKey:null,updated_at:new Date().toISOString()});
// Viewing another tab doesn't turn a saved portfolio into a changed portfolio.
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().filter(k=>value[k]!==undefined).map(k=>[k,canonical(value[k])])):value;
const contentKey=(name,state)=>JSON.stringify(canonical({name:name.normalize('NFC').trim(),state:state?{...state,options:state.options??emptyOptions(),analytics:state.analytics??emptyAnalytics(),backtest:state.backtest??emptyBacktest(),covered_call:state.covered_call??emptyCoveredCall(),crypto:state.crypto??emptyCrypto(),volatility:state.volatility??emptySurface(),backtest_tool:undefined,view:undefined}:null}));
function validDraft(d) {
  if(!d||typeof d.id!=='string'||typeof d.name!=='string'||!Number.isInteger(d.revision)||d.revision<0)return false;
  const s=d.state;
  if(!s||s.schema_version!==1||!Array.isArray(s.holdings)||!Array.isArray(s.research)||!s.settings)return false;
  if(!['holdings','research'].includes(s.mode)||!['quantity','allocation','csv'].includes(s.source)||!['overview','holdings','research','options','analytics','backtesting','risk','settings','volatility','crypto'].includes(s.view)||!['percent','dollars'].includes(s.unit))return false;
  if(s.crypto!==undefined&&!validCrypto(s.crypto))return false;
  if(s.volatility!==undefined&&!validSurface(s.volatility))return false;
  if(s.analytics!==undefined&&!validAnalytics(s.analytics))return false;
  if(s.backtest_tool!==undefined&&!['stocks','covered_call'].includes(s.backtest_tool))return false;
  if(s.covered_call!==undefined&&!validCoveredCall(s.covered_call))return false;
  if(s.backtest!==undefined&&!validBacktest(s.backtest))return false;
  if(s.options!==undefined&&!validOptions(s.options))return false;
  if(!['cash','budget'].every(k=>typeof s[k]==='string'))return false;
  if(!s.holdings.every(h=>['ticker','name','exchange','qty','avg_cost','percent','dollars','purchase_price'].every(k=>typeof h[k]==='string')))return false;
  if(!s.research.every(h=>['ticker','name','exchange'].every(k=>typeof h[k]==='string')))return false;
  if(!['benchmark','window','risk_free_percent'].every(k=>typeof s.settings[k]==='string'))return false;
  if(!['6mo','1y','2y','5y','max'].includes(s.settings.period)||!['1d','1wk','1mo'].includes(s.settings.interval)||!['price','total'].includes(s.settings.return_basis))return false;
  return s.csv===null||(s.csv&&typeof s.csv.name==='string'&&Array.isArray(s.csv.positions)&&s.csv.positions.every(p=>typeof p.ticker==='string'&&Number.isFinite(p.qty)&&Number.isFinite(p.avg_cost)));
}
function readDraft(slot) {
  if(!slot)return null;
  const text=localStorage.getItem(PREFIX+slot);
  if(!text)return null;
  const doc=JSON.parse(text);
  if(!validDraft(doc))throw new Error('The recovery draft could not be read. It has been kept; you can still load a saved portfolio.');
  return doc;
}
function boot() {
  try {
    const slot=sessionStorage.getItem(ACTIVE)||localStorage.getItem(ACTIVE);
    const doc=readDraft(slot);
    return {slot:doc?slot:uuid(),doc:doc||empty(),message:doc?'Draft restored. Analyze to refresh market results.':''};
  }catch(e){return {slot:uuid(),doc:empty(),message:e instanceof SyntaxError?'The recovery draft could not be read. It has been kept. Load a saved portfolio to continue.':e.message};}
}
function drafts() {
  const items=[];
  for(let i=0;i<localStorage.length;i++){
    const key=localStorage.key(i);
    if(!key.startsWith(PREFIX))continue;
    try{const doc=readDraft(key.slice(PREFIX.length));if(doc)items.push({slot:key.slice(PREFIX.length),...doc});}catch{/* A damaged draft is kept, never removed. */}
  }
  return items.sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
}

export default function Workspace({Tracker}) {
  const [initial]=useState(boot);
  const [loaded,setLoaded]=useState(initial.doc),[epoch,setEpoch]=useState(0);
  const current=useRef(initial.doc),slot=useRef(initial.slot),writer=useRef(uuid());
  const [name,setName]=useState(initial.doc.name),[portfolios,setPortfolios]=useState([]),[selected,setSelected]=useState('');
  const [recovery,setRecovery]=useState([]),[recoverySelection,setRecoverySelection]=useState('');
  const [pending,setPending]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState('');
  const [message,setMessage]=useState(initial.message),[draftStatus,setDraftStatus]=useState(''),[dirty,setDirty]=useState(true);
  const mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);

  const persist=useCallback(doc=>{
    current.current={...doc,writer:writer.current,updated_at:new Date().toISOString()};
    setDirty(contentKey(doc.name,doc.state)!==doc.savedKey);
    if(!doc.state)return;
    try{
      localStorage.setItem(PREFIX+slot.current,JSON.stringify(current.current));
      localStorage.setItem(ACTIVE,slot.current);
      sessionStorage.setItem(ACTIVE,slot.current);
      setDraftStatus('Draft recovery ready in this browser');
    }catch{
      setDraftStatus('Browser draft recovery is unavailable. Use Save portfolio before closing.');
    }
  },[]);
  const changed=useCallback(state=>{
    if(JSON.stringify(current.current.state)===JSON.stringify(state))return;
    persist({...current.current,state});
  },[persist]);

  const refreshList=useCallback(async()=>{
    const data=await api('/portfolios');
    if(!Array.isArray(data.portfolios))throw new Error('Saved portfolios are unavailable. Restart the tracker and retry.');
    if(mounted.current)setPortfolios(data.portfolios);
  },[]);
  useEffect(()=>{refreshList().catch(e=>{if(mounted.current)setError(e.message);});},[refreshList]);
  useEffect(()=>{
    const onStorage=event=>{
      if(event.key!==PREFIX+slot.current||!event.newValue)return;
      try{
        const incoming=JSON.parse(event.newValue);
        if(incoming.writer===writer.current)return;
        // A duplicated tab may inherit the same session slot. Fork its recovery
        // buffer instead of letting either tab erase the other's unfinished work.
        slot.current=uuid();persist(current.current);
        setMessage('This tab has its own recovery draft. Saving checks for changes made in other tabs.');
      }catch{/* Keep the current input if another writer supplies unreadable data. */}
    };
    window.addEventListener('storage',onStorage);
    return()=>window.removeEventListener('storage',onStorage);
  },[persist]);

  function activate(doc,existingSlot=null) {
    slot.current=existingSlot||uuid();current.current=doc;
    setName(doc.name);setLoaded(doc);setEpoch(n=>n+1);setError('');setSelected(doc.revision?doc.id:'');
    persist(doc);
  }
  async function loadSelected() {
    if(!selected)return;
    setPending(true);setError('');
    try{
      const doc=await api('/portfolios/'+encodeURIComponent(selected));
      if(!validDraft(doc))throw new Error('The saved portfolio could not be read. Your current edits are kept.');
      activate({...doc,savedKey:contentKey(doc.name,doc.state)});
      setMessage('Saved portfolio loaded. Analyze to retrieve current market data.');
    }catch(e){setError(e.message);}
    finally{setPending(false);}
  }
  async function save() {
    const sent={...current.current,name:name.trim()};
    if(!sent.name){setError('Enter a portfolio name first.');return;}
    setSaving(true);setError('');setMessage('');
    try{
      const result=await api('/portfolios/save',{id:sent.id,name:sent.name,revision:sent.revision,state:sent.state});
      // Changes made while saving remain in the draft; the response only confirms
      // the submitted snapshot. Retain its revision for the next atomic save.
      const latest=current.current;
      const next={...latest,revision:result.revision,name:latest.name===sent.name?result.name:latest.name,savedKey:contentKey(result.name,result.state)};
      persist(next);setName(next.name);setSelected(result.id);
      setMessage(contentKey(next.name,next.state)===next.savedKey?'Portfolio saved to this device.':'Portfolio saved. Newer edits remain in your recovery draft; save again to include them.');
      try{await refreshList();}catch{setError('Portfolio saved, but the list could not refresh. Use Refresh list to retry.');}
    }catch(e){setError(e.message);}
    finally{setSaving(false);}
  }
  function create(copy=false) {
    const doc=copy?{...empty(),name:name?name.slice(0,74)+' copy':'',state:current.current.state}:empty();
    activate(doc);setMessage(copy?'Copy ready. Choose a name and save it.':'New portfolio. Your previous edits remain available under Draft recovery.');
  }
  function showRecovery() {
    try{setRecovery(drafts());}catch{setError('Browser draft recovery is unavailable. Saved portfolios on your device can still be loaded.');}
  }
  function restore() {
    try{
      const doc=readDraft(recoverySelection);
      if(!doc)throw new Error('That recovery draft is unavailable. Your current inputs are kept.');
      activate(doc);setMessage('Draft recovered. Analyze again to refresh market results.');
    }catch(e){setError(e.message);}
  }
  const locked=pending||saving;
  const bar=<section className="workspace-library" aria-label="Portfolio library">
    <div className="workspace-library-row"><label className="portfolio-picker">Saved portfolios<select aria-label="Saved portfolios" value={selected} onChange={e=>setSelected(e.target.value)} disabled={locked}><option value="">Choose a saved portfolio</option>{portfolios.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><button disabled={!selected||locked} onClick={loadSelected}><FolderOpen size={16}/>Load</button><button disabled={locked} onClick={()=>create()}><Plus size={16}/>New portfolio</button><button disabled={locked} onClick={()=>create(true)}><Copy size={16}/>Make a copy</button><button className="link" disabled={locked} onClick={()=>refreshList().then(()=>setError('')).catch(e=>setError(e.message))}>Refresh list</button></div>
    <div className="workspace-library-row"><label className="portfolio-name">Portfolio name<input aria-label="Portfolio name" value={name} maxLength={80} placeholder="e.g. Long-term investments" onChange={e=>{setName(e.target.value);persist({...current.current,name:e.target.value});}}/></label><button className="primary" disabled={locked||!name.trim()} onClick={save}><Save size={16}/>{saving?'Saving…':'Save portfolio'}</button><div className="save-status" aria-live="polite"><span>{dirty?'Changes not saved to portfolio':'Saved to this device'}</span><span className="muted small">{draftStatus}</span></div></div>
    {message&&<p className="workspace-message" role="status">{message}</p>}{error&&<p className="workspace-message error" role="alert">{error}</p>}
    <details className="draft-recovery" onToggle={e=>{if(e.currentTarget.open)showRecovery();}}><summary><RotateCcw size={14}/>Draft recovery</summary><div className="workspace-library-row"><label className="grow">Recover earlier edits<select aria-label="Recovery draft" value={recoverySelection} onChange={e=>setRecoverySelection(e.target.value)}><option value="">Choose a draft</option>{recovery.map(d=><option key={d.slot} value={d.slot}>{d.name||'Untitled portfolio'} · {new Date(d.updated_at).toLocaleString()}</option>)}</select></label><button disabled={!recoverySelection||locked} onClick={restore}>Restore draft</button></div><p className="small muted">Drafts stay in this browser, including incomplete inputs. Save a named portfolio to keep it in your project folder. Loading a portfolio refreshes your inputs; select Analyze for market results.</p></details>
  </section>;
  return <Tracker key={epoch} initialState={loaded.state} onDraftChange={changed} portfolioBar={bar} workspaceLoading={pending}/>;
}
