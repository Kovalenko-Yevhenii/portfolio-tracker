import React from 'react';
import {describe,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,within,act} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';
import {backtestPayload,emptyBacktest,validBacktest} from './backtest-model.js';
import fixture from './fixtures/backtest.json';
import * as helpers from './data.js';
vi.mock('recharts',async()=>{const actual=await vi.importActual('recharts');return {...actual,ResponsiveContainer:({children})=><div>{React.cloneElement(children,{width:600,height:280})}</div>};});
const ok=data=>({ok:true,json:async()=>data});
const edit=(label,value)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
function setup(handler){
  const records=new Map(),requests=[];
  vi.stubGlobal('fetch',vi.fn(async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;requests.push({url,body});
    if(url==='/api/portfolios')return ok({portfolios:[...records.values()]});
    if(url==='/api/portfolios/save'){const record={...body,revision:body.revision+1};records.set(body.id,structuredClone(record));return ok(record);}
    if(url.startsWith('/api/portfolios/'))return ok(records.get(url.split('/').at(-1)));
    if(url==='/api/backtest')return handler?handler(body):ok(fixture);
    throw Error('Unexpected request '+url);
  }));
  return {...render(<React.StrictMode><App/></React.StrictMode>),user:userEvent.setup(),records,requests};
}
async function open(user){await user.click(screen.getByRole('tab',{name:'Backtesting'}));}
async function example(user){await user.click(screen.getByRole('button',{name:'Try offline example'}));await user.click(screen.getByRole('button',{name:'Load example'}));edit('Backtest end','2024-03-28');}
async function run(user){await user.click(screen.getByRole('button',{name:'Run backtest',exact:true}));await screen.findByRole('table',{name:'Backtest performance comparison'});}

describe('Backtesting workflows',()=>{
  it('runs the offline basket, displays costs, charts and auditable trades',async()=>{
    const {user,requests}=setup();await open(user);await example(user);await run(user);
    expect(screen.getByRole('img',{name:'Backtest portfolio value'})).toBeTruthy();
    expect(screen.getByRole('img',{name:'Backtest drawdowns'})).toBeTruthy();
    const sent=requests.find(r=>r.url==='/api/backtest').body;
    expect(sent).toMatchObject({source:'demo',assets:[{ticker:'DEMO-A',weight:60},{ticker:'DEMO-B',weight:40}],window:50,capital:10000,slippage_bps:5,refresh:false});
    expect(within(screen.getByLabelText('Backtest strategy summary')).getByText('$10,004.75')).toBeTruthy();
    expect(screen.getByRole('table',{name:'Backtest trade ledger'})).toBeTruthy();
    await user.selectOptions(screen.getByLabelText('Show trades for'),'benchmark');
    expect(within(screen.getByRole('table',{name:'Backtest trade ledger'})).getByText('DEMO-MKT')).toBeTruthy();
    edit('Slippage each way (basis points)','20');expect(screen.queryByRole('region',{name:'Backtest results'})).toBeNull();
    expect(screen.getByText(/Assumptions changed/)).toBeTruthy();
  });
  it('edits a stock basket without changing the holdings workspace and sends refresh',async()=>{
    const {user,requests}=setup();await open(user);edit('Backtest start','2024-01-02');edit('Backtest end','2025-12-31');
    edit('Backtest ticker 1','aapl');edit('Backtest weight 1','70');
    await user.click(screen.getByRole('button',{name:'Add security'}));edit('Backtest ticker 2','msft');edit('Backtest weight 2','30');
    await user.selectOptions(screen.getByLabelText('Trading rule'),'buy_hold');
    expect(screen.queryByLabelText('Moving-average sessions')).toBeNull();
    await user.click(screen.getByRole('button',{name:'Refresh data & run'}));
    await screen.findByRole('table',{name:'Backtest performance comparison'});
    expect(requests.find(r=>r.url==='/api/backtest').body).toMatchObject({source:'market',strategy:'buy_hold',refresh:true,assets:[{ticker:'AAPL',weight:70},{ticker:'MSFT',weight:30}]});
    await user.click(screen.getByRole('tab',{name:'Holdings'}));expect(screen.queryByRole('button',{name:'Remove AAPL'})).toBeNull();
  });
  it('protects example replacement and validates browser draft shapes',async()=>{
    const {user}=setup();await open(user);edit('Backtest hypothesis','My experiment');
    await user.click(screen.getByRole('button',{name:'Try offline example'}));expect(screen.getByLabelText('Backtest hypothesis').value).toBe('My experiment');
    await user.click(screen.getByRole('button',{name:'Cancel'}));expect(screen.getByLabelText('Backtest hypothesis').value).toBe('My experiment');
    expect(validBacktest(emptyBacktest())).toBe(true);expect(validBacktest({...emptyBacktest(),version:2})).toBe(false);
    expect(backtestPayload({...emptyBacktest(),capital:''}).capital).toBeNull();
  });
  it('recovers incomplete inputs and saves/restores alongside other labs',async()=>{
    const {user,records,unmount}=setup();await user.click(screen.getByRole('tab',{name:'Analytics Lab'}));edit('Company / ticker','Keep equity research');
    await open(user);edit('Backtest hypothesis','Keep backtest notes');edit('Backtest weight 1','');
    unmount();const next=render(<App/>);expect(screen.getByLabelText('Backtest weight 1').value).toBe('');
    edit('Portfolio name','Backtest research');await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');
    const [id,record]=[...records.entries()][0];expect(record.state.backtest.hypothesis).toBe('Keep backtest notes');expect(record.state.analytics.company).toBe('Keep equity research');
    next.unmount();localStorage.clear();sessionStorage.clear();render(<App/>);await screen.findByRole('option',{name:'Backtest research'});
    await user.selectOptions(screen.getByLabelText('Saved portfolios'),id);await user.click(screen.getByRole('button',{name:'Load',exact:true}));await screen.findByLabelText('Backtest hypothesis');
    expect(screen.getByLabelText('Backtest hypothesis').value).toBe('Keep backtest notes');
    expect(screen.getByLabelText('Backtest weight 1').value).toBe('');
  });
  it('ignores superseded results and preserves input after errors',async()=>{
    let finish;const {user}=setup(()=>new Promise(resolve=>{finish=resolve;}));await open(user);await example(user);
    await user.click(screen.getByRole('button',{name:'Run backtest'}));edit('Moving-average sessions','20');
    await act(async()=>finish(ok(fixture)));expect(screen.queryByRole('region',{name:'Backtest results'})).toBeNull();
    await user.click(screen.getByRole('button',{name:'Run backtest'}));await act(async()=>finish({ok:false,json:async()=>({error:'Initial allocations must add to 100%.'})}));
    expect(screen.getByRole('alert').textContent).toBe('Initial allocations must add to 100%.');expect(screen.getByLabelText('Moving-average sessions').value).toBe('20');
  });
  it('exports complete observed prices, settings, all ledgers and escaped research text',async()=>{
    const save=vi.spyOn(helpers,'download').mockImplementation(()=>{});const {user}=setup();await open(user);await example(user);edit('Backtest hypothesis',' =1+1');await run(user);
    await user.click(screen.getByRole('button',{name:'Download trades'}));expect(save.mock.calls[0][0].content).toContain("' =1+1");expect(save.mock.calls[0][0].content).toContain('signal_date');expect(save.mock.calls[0][0].content).toContain('benchmark');
    await user.click(screen.getByRole('button',{name:'Download daily values'}));expect(save.mock.calls[1][0].content).toContain('strategy_drawdown');
    await user.click(screen.getByRole('button',{name:'Download full run'}));const doc=JSON.parse(save.mock.calls[2][0].content);
    expect(doc.observations).toEqual(fixture.observations);expect(doc.data_sha256).toBe(fixture.data_sha256);expect(doc.hypothesis).toBe(' =1+1');
  });
});
