import React from 'react';
import {describe,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,within,act} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';
import {emptyCoveredCall,validCoveredCall,coveredCallPayload} from './covered-call-model.js';
import fixture from './fixtures/covered-call.json';
import * as helpers from './data.js';
vi.mock('recharts',async()=>{const actual=await vi.importActual('recharts');return {...actual,ResponsiveContainer:({children})=><div>{React.cloneElement(children,{width:600,height:290})}</div>};});
const ok=data=>({ok:true,json:async()=>data});
const edit=(label,value)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
function setup(handler){
  const records=new Map(),requests=[];
  vi.stubGlobal('fetch',vi.fn(async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;requests.push({url,body});
    if(url==='/api/portfolios')return ok({portfolios:[...records.values()]});
    if(url==='/api/portfolios/save'){const record={...body,revision:body.revision+1};records.set(body.id,structuredClone(record));return ok(record);}
    if(url.startsWith('/api/portfolios/'))return ok(records.get(url.split('/').at(-1)));
    if(url==='/api/simulation/covered-call')return handler?handler(body):ok(fixture);
    throw Error('Unexpected request '+url);
  }));
  return {...render(<React.StrictMode><App/></React.StrictMode>),user:userEvent.setup(),records,requests};
}
async function open(user){await user.click(screen.getByRole('tab',{name:'Backtesting'}));await user.click(screen.getByRole('button',{name:'Options strategy simulation',exact:true}));}
async function example(user){await user.click(screen.getByRole('button',{name:'Try covered-call example'}));await user.click(screen.getByRole('button',{name:'Load covered-call example'}));edit('Simulation end','2024-03-28');}
async function simulate(user){await user.click(screen.getByRole('button',{name:'Run covered-call simulation',exact:true}));await screen.findByRole('table',{name:'Covered-call performance comparison'});}

describe('Covered-call research simulator',()=>{
  it('shows explicitly modeled results, comparators, sensitivity, cycles and cash accounting',async()=>{
    const {user,requests}=setup();await open(user);await example(user);await simulate(user);
    expect(screen.getByText('MODELED OPTION PRICES')).toBeTruthy();
    expect(screen.getByRole('img',{name:'Covered-call versus stock value'})).toBeTruthy();
    expect(screen.getByRole('img',{name:'Covered-call drawdowns'})).toBeTruthy();
    expect(within(screen.getByLabelText('Covered-call summary')).getByText('$26,578.59')).toBeTruthy();
    expect(screen.getByRole('table',{name:'Covered-call volatility and cost sensitivity'})).toBeTruthy();
    expect(screen.getByRole('table',{name:'Simulated call cycles'})).toBeTruthy();
    expect(screen.getByRole('table',{name:'Covered-call cash ledger'})).toBeTruthy();
    expect(requests.find(r=>r.url==='/api/simulation/covered-call').body).toMatchObject({source:'demo',ticker:'DEMO-CC',capital:25000,contracts:1,tenor_sessions:20,volatility_percent:25,option_fee:.65,refresh:false});
    edit('Assumed annual volatility (%)','35');expect(screen.queryByRole('region',{name:'Covered-call simulation results'})).toBeNull();expect(screen.getByText(/Assumptions changed/)).toBeTruthy();
  });
  it('sends trailing-volatility and roll assumptions with refresh and ignores dormant fixed IV',async()=>{
    const {user,requests}=setup();await open(user);edit('Simulation start','2024-01-02');edit('Simulation end','2024-12-31');
    edit('Simulation ticker','aapl');edit('Assumed annual volatility (%)','');
    await user.selectOptions(screen.getByLabelText('Volatility assumption'),'trailing');edit('Trailing volatility sessions','60');edit('Volatility premium (percentage points)','4');edit('Roll before expiry (sessions)','5');
    await user.click(screen.getByRole('button',{name:'Refresh stock data & simulate'}));await screen.findByRole('table',{name:'Simulated call cycles'});
    expect(requests.find(r=>r.url==='/api/simulation/covered-call').body).toMatchObject({ticker:'AAPL',volatility_mode:'trailing',volatility_percent:25,volatility_window:60,volatility_premium:4,roll_before:5,refresh:true});
    await user.selectOptions(screen.getByLabelText('Volatility assumption'),'fixed');expect(screen.getByLabelText('Assumed annual volatility (%)').value).toBe('');
  });
  it('keeps stock backtest inputs independent and recovers the selected tool',async()=>{
    const {user,unmount}=setup();await user.click(screen.getByRole('tab',{name:'Backtesting'}));edit('Moving-average sessions','77');
    await user.click(screen.getByRole('button',{name:'Options strategy simulation'}));edit('Covered-call hypothesis','Separate experiment');edit('Assumed annual volatility (%)','');
    unmount();render(<App/>);expect(screen.getByLabelText('Covered-call hypothesis').value).toBe('Separate experiment');expect(screen.getByLabelText('Assumed annual volatility (%)').value).toBe('');
    await user.click(screen.getByRole('button',{name:'Historical stocks & ETFs'}));expect(screen.getByLabelText('Moving-average sessions').value).toBe('77');
  });
  it('saves and restores incomplete inputs without losing other labs',async()=>{
    const {user,records,unmount}=setup();await user.click(screen.getByRole('tab',{name:'Analytics Lab'}));edit('Company / ticker','Keep valuation');await open(user);edit('Covered-call hypothesis','My assumptions');edit('Simulation end','');
    edit('Portfolio name','Covered-call research');await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');
    const [id,record]=[...records.entries()][0];expect(record.state.covered_call.end).toBe('');expect(record.state.analytics.company).toBe('Keep valuation');expect(record.state.backtest_tool).toBe('covered_call');
    unmount();localStorage.clear();sessionStorage.clear();render(<App/>);await screen.findByRole('option',{name:'Covered-call research'});await user.selectOptions(screen.getByLabelText('Saved portfolios'),id);await user.click(screen.getByRole('button',{name:'Load',exact:true}));
    await screen.findByLabelText('Covered-call hypothesis');expect(screen.getByLabelText('Covered-call hypothesis').value).toBe('My assumptions');
  });
  it('protects example replacement and hides late results after edits',async()=>{
    let finish;const {user}=setup(()=>new Promise(resolve=>{finish=resolve;}));await open(user);edit('Covered-call hypothesis','Keep me');
    await user.click(screen.getByRole('button',{name:'Try covered-call example'}));await user.click(screen.getByRole('button',{name:'Cancel'}));expect(screen.getByLabelText('Covered-call hypothesis').value).toBe('Keep me');
    await example(user);await user.click(screen.getByRole('button',{name:'Run covered-call simulation'}));edit('Strike above prior close (%)','10');await act(async()=>finish(ok(fixture)));expect(screen.queryByRole('region',{name:'Covered-call simulation results'})).toBeNull();
    await user.click(screen.getByRole('button',{name:'Run covered-call simulation'}));await act(async()=>finish({ok:false,json:async()=>({error:'Starting capital must cover the stock position.'})}));
    expect(screen.getByRole('alert').textContent).toBe('Starting capital must cover the stock position.');expect(screen.getByLabelText('Strike above prior close (%)').value).toBe('10');
  });
  it('exports marked simulation results with data, model assumptions, ledger and escaped text',async()=>{
    const save=vi.spyOn(helpers,'download').mockImplementation(()=>{});const {user}=setup();await open(user);await example(user);edit('Covered-call hypothesis',' =1+1');await simulate(user);
    await user.click(screen.getByRole('button',{name:'Download simulation CSV'}));const csv=save.mock.calls[0][0];expect(csv.name).toContain('MODELED');expect(csv.content).toContain("' =1+1");expect(csv.content).toContain('MODELED_OPTIONS_SIMULATION');expect(csv.content).toContain('Short-call liability');expect(csv.content).toContain('Cost multiplier');
    await user.click(screen.getByRole('button',{name:'Download complete simulation'}));const doc=JSON.parse(save.mock.calls[1][0].content);expect(doc.observations).toEqual(fixture.observations);expect(doc.covered_call.events).toEqual(fixture.covered_call.events);expect(doc.hypothesis).toBe(' =1+1');
    expect(validCoveredCall(emptyCoveredCall())).toBe(true);expect(validCoveredCall({...emptyCoveredCall(),version:2})).toBe(false);expect(coveredCallPayload({...emptyCoveredCall(),contracts:''}).contracts).toBeNull();
  });
});
