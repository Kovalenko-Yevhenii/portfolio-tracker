import React from 'react';
import {describe,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,act,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';
import fixtures from './fixtures/options-v2.json';
import funding from './fixtures/options-leverage.json';
import * as dataHelpers from './data.js';
import {upgradeOptions,validOptions,setupSnapshot,modelPayload,templateLegs} from './options-model.js';
vi.mock('recharts',async load=>{const actual=await load();return {...actual,ResponsiveContainer:({children})=>React.cloneElement(children,{width:700,height:280})};});
const ok=data=>({ok:true,json:async()=>data});
const edit=(label,value)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
function setup(handler,records=new Map()) {
  const requests=[];
  vi.stubGlobal('fetch',vi.fn(async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;requests.push({url,body});
    if(url==='/api/portfolios')return ok({portfolios:[...records.values()]});
    if(url==='/api/portfolios/save'){const record={...body,revision:body.revision+1};records.set(body.id,record);return ok(record);}
    if(url.startsWith('/api/portfolios/'))return ok(records.get(url.split('/').at(-1)));
    if(url==='/api/options/model')return handler?handler(body):ok(fixtures[body.mode]);
    if(url.startsWith('/api/options/expirations'))return ok({symbol:'AAPL',expirations:[fixtures.chain.expiration]});
    if(url.startsWith('/api/options/chain'))return ok(fixtures.chain);
    if(url==='/api/options/finder')return ok(fixtures.finder);
    throw new Error('Unexpected market-data request: '+url);
  }));
  const app=render(<React.StrictMode><App/></React.StrictMode>);
  return {...app,requests,records,user:userEvent.setup()};
}
async function openLab(user) {await user.click(screen.getByRole('tab',{name:'Options Lab'}));}
async function expiryInputs(user){await user.selectOptions(screen.getByLabelText('Options calculation mode'),'expiry');edit('Leg 1 Strike','100');edit('Leg 1 Premium per unit','5');edit('Scenario underlying price','120');}

describe('expanded options laboratory',()=>{
  it('scales exposure from the base, recalculates risk, and returns to 1× without compounding',async()=>{
    const {user,requests}=setup(body=>ok({...fixtures.expiry,initial_debit:500*body.legs[0].quantity,scenario_pnl:1500*body.legs[0].quantity,summary:{...fixtures.expiry.summary,maximum_loss:500*body.legs[0].quantity}}));
    await openLab(user);await expiryInputs(user);
    const controls=screen.getByRole('group',{name:'Exposure multiplier'});
    await user.click(within(controls).getByRole('button',{name:'3×'}));
    expect(screen.getByText('Leg 1 · Buy 3 call contracts')).toBeTruthy();
    expect(screen.getByLabelText('Leg 1 Contracts').value).toBe('1');
    expect(screen.getByText('$1,500.00')).toBeTruthy();
    await user.click(screen.getByRole('button',{name:'Calculate strategy'}));
    await screen.findByRole('table',{name:'Options price and date scenarios'});
    expect(requests.filter(r=>r.url==='/api/options/model').at(-1).body.legs[0].quantity).toBe(3);
    await user.click(within(controls).getByRole('button',{name:'5×'}));
    await screen.findByRole('table',{name:'Options price and date scenarios'});
    expect(requests.filter(r=>r.url==='/api/options/model').at(-1).body.legs[0].quantity).toBe(5);
    expect(screen.getAllByText('$2,500.00').length).toBeGreaterThan(0);
    await user.click(within(controls).getByRole('button',{name:'1×'}));
    await screen.findByRole('table',{name:'Options price and date scenarios'});
    expect(requests.filter(r=>r.url==='/api/options/model').at(-1).body.legs[0].quantity).toBe(1);
  });
  it('preserves spread ratios and covered shares while keeping borrowing and capital inputs fixed',()=>{
    const base=upgradeOptions(null);
    for(const strategy of ['butterfly','covered_call']){
      const state={...base,strategy,legs:templateLegs(strategy),exposure_multiplier:'3',capital_basis:'10000',comparison_budget:'20000',borrowed_amount:'250'};
      const payload=modelPayload(state);
      expect(payload.legs.map(l=>l.quantity)).toEqual(strategy==='butterfly'?[3,6,3]:[300,3]);
      expect(payload.capital_basis).toBe(10000);expect(payload.comparison_budget).toBe(20000);
      expect(modelPayload({...state,financing_enabled:true}).borrowed_amount).toBe(250);
      expect(state.legs.map(l=>l.quantity)).toEqual(strategy==='butterfly'?['1','2','1']:['100','1']);
    }
    expect(modelPayload({...base,exposure_multiplier:'2',legs:[{...base.legs[0],quantity:'0.5'}]}).legs[0].quantity).toBeNull();
    expect(validOptions({...base,exposure_multiplier:'10'})).toBe(false);
    expect(validOptions({...base,engine_version:99})).toBe(false);
  });
  it('restores exposure in drafts, named portfolios, and kept scenarios',async()=>{
    const {user,unmount,records}=setup();await openLab(user);await expiryInputs(user);
    await user.click(screen.getByRole('button',{name:'3×'}));edit('Options scenario name','Triple call');
    await user.click(screen.getByRole('button',{name:'Keep scenario'}));
    edit('Portfolio name','Exposure workspace');await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');
    const record=[...records.values()][0];expect(record.state.options.exposure_multiplier).toBe('3');expect(record.state.options.scenarios[0].state.exposure_multiplier).toBe('3');
    await user.click(screen.getByRole('button',{name:'5×'}));await user.click(screen.getByRole('button',{name:'Load scenario'}));
    expect(screen.getByRole('button',{name:'3×'}).getAttribute('aria-pressed')).toBe('true');
    unmount();const restored=render(<App/>);expect(screen.getByRole('button',{name:'3×'}).getAttribute('aria-pressed')).toBe('true');
    restored.unmount();localStorage.clear();sessionStorage.clear();render(<App/>);
    await screen.findByRole('option',{name:'Exposure workspace'});await user.selectOptions(screen.getByLabelText('Saved portfolios'),record.id);await user.click(screen.getByRole('button',{name:'Load',exact:true}));
    await screen.findByLabelText('Leg 1 Contracts');expect(screen.getByRole('button',{name:'3×'}).getAttribute('aria-pressed')).toBe('true');
  });
  it('defaults older portfolios to 1× and preserves exposure in shared scenarios',async()=>{
    const old={...upgradeOptions(null),engine_version:3};delete old.exposure_multiplier;
    expect(validOptions(old)).toBe(true);expect(upgradeOptions(old).exposure_multiplier).toBe('1');
    const scenario={...upgradeOptions(old),exposure_multiplier:'5'};
    window.history.replaceState(null,'','#options='+encodeURIComponent(JSON.stringify(setupSnapshot(scenario))));
    const {user}=setup();await user.click(screen.getByRole('button',{name:'Load linked scenario'}));
    expect(screen.getByRole('button',{name:'5×'}).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('Leg 1 · Buy 5 call contracts')).toBeTruthy();
  });

  it('calculates without holdings and switches output views without extra requests',async()=>{
    const {user,requests}=setup();await openLab(user);await expiryInputs(user);
    await user.click(screen.getByRole('button',{name:'Calculate strategy'}));
    await screen.findByRole('table',{name:'Options price and date scenarios'});expect(screen.getByText('Unlimited')).toBeTruthy();
    await user.click(screen.getByRole('button',{name:'Line chart',exact:true}));expect(screen.getByRole('group',{name:'Options payoff line chart'})).toBeTruthy();
    await user.selectOptions(screen.getByLabelText('Output values'),'return_percent');
    expect(requests.filter(r=>r.url==='/api/options/model')).toHaveLength(1);
    expect(requests.find(r=>r.url==='/api/options/model').body).toMatchObject({mode:'expiry',legs:[{strike:100,premium:5,quantity:1,multiplier:100}],scenario_price:120});
    expect(requests.some(r=>r.url==='/api/analyze')).toBe(false);
  });
  it('builds templates with independent quantities and allows eight options plus stock',async()=>{
    const {user}=setup();await openLab(user);await user.selectOptions(screen.getByLabelText('Options strategy'),'butterfly');
    expect(screen.getByLabelText('Leg 2 Contracts').value).toBe('2');await user.selectOptions(screen.getByLabelText('Options strategy'),'iron_condor');
    expect(screen.getByLabelText('Leg 1 type').value).toBe('put');expect(screen.getByLabelText('Leg 4 type').value).toBe('call');
    for(let i=0;i<4;i++)await user.click(screen.getByRole('button',{name:'Add option leg'}));
    expect(screen.getByRole('button',{name:'Add option leg'}).disabled).toBe(true);await user.click(screen.getByRole('button',{name:'Add stock position'}));
    expect(screen.getByLabelText('Leg 9 Shares').value).toBe('100');expect(screen.getByRole('button',{name:'Add stock position'}).disabled).toBe(true);
  });
  it('passes dates, yield, IV shift and fees into the pricing request',async()=>{
    const {user,requests}=setup();await openLab(user);edit('Current underlying price','100');edit('Leg 1 Strike','100');edit('Leg 1 Premium per unit','5');edit('Leg 1 Expiration','2026-10-16');edit('Leg 1 IV % (blank = infer)','30');edit('Calculation date','2026-09-14');edit('Scenario date','2026-09-30');edit('IV shift (percentage points)','5');edit('Annual dividend yield (%)','1.2');edit('Round-trip fee per option contract','1');
    await user.click(screen.getByRole('button',{name:'Calculate strategy'}));await screen.findByRole('heading',{name:'Greeks at calculation date'});
    expect(requests.find(r=>r.url==='/api/options/model').body).toMatchObject({mode:'dated',spot:100,as_of:'2026-09-14',target_date:'2026-09-30',iv_shift:5,dividend_yield:1.2,fee_per_contract:1,legs:[{iv:30,expiration:'2026-10-16'}]});
  });
  it('discards results from earlier inputs',async()=>{
    let finish;const {user}=setup(()=>new Promise(resolve=>{finish=resolve;}));await openLab(user);await expiryInputs(user);
    await user.click(screen.getByRole('button',{name:'Calculate strategy'}));edit('Leg 1 Premium per unit','8');await act(async()=>finish(ok(fixtures.expiry)));
    expect(screen.queryByRole('heading',{name:'Explore price and time'})).toBeNull();expect(screen.getByLabelText('Leg 1 Premium per unit').value).toBe('8');
  });
  it('keeps fields on failure and hides results when inputs change',async()=>{
    let failure=false;const {user}=setup(()=>failure?{ok:false,json:async()=>({error:'Check the strike.'})}:ok(fixtures.expiry));await openLab(user);await expiryInputs(user);
    await user.click(screen.getByRole('button',{name:'Calculate strategy'}));await screen.findByRole('heading',{name:'Explore price and time'});edit('Chart maximum price','200');expect(screen.queryByRole('heading',{name:'Explore price and time'})).toBeNull();failure=true;
    await user.click(screen.getByRole('button',{name:'Calculate strategy'}));await screen.findByRole('alert');expect(screen.getByLabelText('Chart maximum price').value).toBe('200');
  });
  it('places a quoted contract in the chosen leg using the ask for a buy',async()=>{
    const {user,requests}=setup();await openLab(user);edit('Options underlying ticker','AAPL');await user.click(screen.getByRole('button',{name:'Option chain',exact:true}));await user.click(screen.getByRole('button',{name:'Load option chain'}));await screen.findByRole('table',{name:'Available option contracts'});
    expect(screen.getByLabelText('Chain destination leg').value).toBe('0');await user.click(screen.getByRole('button',{name:'Buy call 100',exact:true}));expect(screen.getByLabelText('Leg 1 Strike').value).toBe('100');expect(screen.getByLabelText('Leg 1 Premium per unit').value).toBe('6');expect(screen.getByLabelText('Current underlying price').value).toBe('100');expect(requests.some(r=>r.url.startsWith('/api/options/chain?symbol=AAPL'))).toBe(true);
  });
  it('runs the finder and opens a ranked result',async()=>{
    const {user,requests}=setup();await openLab(user);edit('Options underlying ticker','AAPL');await user.click(screen.getByRole('button',{name:'Option Finder',exact:true}));edit('Finder target price','120');edit('Finder target date',fixtures.chain.expiration);edit('Maximum expiration risk (optional)','1000');await user.click(screen.getByRole('button',{name:'Load available expirations'}));await screen.findByLabelText(fixtures.chain.expiration);await user.click(screen.getByLabelText(fixtures.chain.expiration));await user.click(screen.getByRole('button',{name:'Find options',exact:true}));await screen.findByRole('table',{name:'Option Finder results'});
    expect(requests.find(r=>r.url==='/api/options/finder').body).toMatchObject({max_risk:1000,target_price:120,pricing:'natural'});await user.click(screen.getAllByRole('button',{name:'Open strategy'})[0]);expect(screen.getByLabelText('Options strategy').value).toBe('custom');expect(screen.getByLabelText('Scenario underlying price').value).toBe('120');
  });
  it('restores unfinished legs and kept scenarios from drafts and named saves',async()=>{
    const {user,unmount,records}=setup();await openLab(user);await user.selectOptions(screen.getByLabelText('Options strategy'),'calendar');edit('Leg 1 Strike','110.25');edit('Leg 1 Expiration','2027-01-15');edit('Options scenario name','Calendar practice');await user.click(screen.getByRole('button',{name:'Keep scenario'}));edit('Portfolio name','Options practice');await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');
    const id=[...records.keys()][0];expect(records.get(id).state.options.scenarios).toHaveLength(1);unmount();const restored=render(<App/>);expect(screen.getByLabelText('Leg 1 Strike').value).toBe('110.25');expect(screen.getByLabelText('Leg 1 Premium per unit').value).toBe('');restored.unmount();localStorage.clear();sessionStorage.clear();render(<App/>);await screen.findByRole('option',{name:'Options practice'});await user.selectOptions(screen.getByLabelText('Saved portfolios'),id);await user.click(screen.getByRole('button',{name:'Load',exact:true}));await screen.findByLabelText('Leg 1 Strike');expect(screen.getByRole('option',{name:'Calendar practice'})).toBeTruthy();expect(screen.queryByRole('heading',{name:'Explore price and time'})).toBeNull();
  });
  it('compares scenarios and keeps errors specific to each incomplete scenario',async()=>{
    const {user}=setup(body=>body.legs[0].premium===null?{ok:false,json:async()=>({error:'Enter a premium.'})}:ok(fixtures.expiry));await openLab(user);await expiryInputs(user);edit('Options scenario name','Complete');await user.click(screen.getByRole('button',{name:'Keep scenario'}));edit('Options scenario name','Incomplete');edit('Leg 1 Premium per unit','');await user.click(screen.getByRole('button',{name:'Keep scenario'}));await user.click(screen.getByRole('button',{name:'Compare kept scenarios'}));const table=await screen.findByRole('table',{name:'Kept scenario comparison'});expect(within(table).getByText('Enter a premium.')).toBeTruthy();expect(within(table).getByText('Complete')).toBeTruthy();
  });
  it('loads a shared local scenario only after an explicit click',async()=>{
    const scenario={...upgradeOptions(null),symbol:'AAPL',valuation_mode:'expiry'};scenario.legs[0].strike='123';scenario.legs[0].premium='4';
    window.history.replaceState(null,'','#options='+encodeURIComponent(JSON.stringify(setupSnapshot(scenario))));
    const {user}=setup();expect(screen.getByLabelText('Leg 1 Strike').value).toBe('');
    await user.click(screen.getByRole('button',{name:'Load linked scenario'}));expect(screen.getByLabelText('Leg 1 Strike').value).toBe('123');expect(window.location.hash).toBe('');
  });
  it('includes borrowing costs and exports funded results without subtracting the loan twice',async()=>{
    const saveFile=vi.spyOn(dataHelpers,'download').mockImplementation(()=>{});
    const {user,requests}=setup(()=>ok(funding.expiry));await openLab(user);await expiryInputs(user);
    edit('Return capital basis (optional)','300');await user.click(screen.getByLabelText('Include stock cost in the automatic return basis'));
    if(!screen.getByText('Borrowing (optional)').parentElement.open)await user.click(screen.getByText('Borrowing (optional)'));await user.click(screen.getByLabelText('Include borrowing costs'));
    edit('Borrowed toward entry debit','250');edit('Annual borrowing rate (%)','10');edit('Holding days for borrowing','365');
    expect(screen.queryByLabelText('Return capital basis (optional)')).toBeNull();
    await user.click(screen.getByRole('button',{name:'Calculate strategy'}));await screen.findByText('Advanced sensitivity & borrowing details');await user.click(screen.getByText('Advanced sensitivity & borrowing details'));await screen.findByRole('heading',{name:'Borrowing breakdown'});
    expect(screen.getByText('$1,725.00')).toBeTruthy();expect(screen.getByText('590.00%')).toBeTruthy();
    expect(requests.find(r=>r.url==='/api/options/model').body).toMatchObject({financing_enabled:true,borrowed_amount:250,borrowing_rate:10,financing_days:365,capital_basis:null,include_stock_cost:true});
    await user.click(screen.getByRole('button',{name:'Download scenario CSV'}));
    const content=saveFile.mock.calls[0][0].content;expect(content).toContain('Interest cost');expect(content).toContain('Equity after loan repayment');expect(content).toContain('"25"');
    if(!screen.getByText('Borrowing (optional)').parentElement.open)await user.click(screen.getByText('Borrowing (optional)'));await user.click(screen.getByLabelText('Include borrowing costs'));
    expect(screen.queryByRole('heading',{name:'Borrowing breakdown'})).toBeNull();expect(screen.getByLabelText('Return capital basis (optional)').value).toBe('300');
  });
  it('saves borrowing assumptions and restores them with kept scenarios',async()=>{
    const {user,unmount,records}=setup();await openLab(user);await expiryInputs(user);if(!screen.getByText('Borrowing (optional)').parentElement.open)await user.click(screen.getByText('Borrowing (optional)'));await user.click(screen.getByLabelText('Include borrowing costs'));edit('Borrowed toward entry debit','250');edit('Annual borrowing rate (%)','10');edit('Holding days for borrowing','73');edit('Options scenario name','Funded call');await user.click(screen.getByRole('button',{name:'Keep scenario'}));edit('Portfolio name','Funding workspace');await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');
    const state=[...records.values()][0].state.options;expect(state.engine_version).toBe(4);expect(state.scenarios[0].state.financing_days).toBe('73');
    unmount();render(<App/>);expect(screen.getByLabelText('Include borrowing costs').checked).toBe(true);expect(screen.getByLabelText('Borrowed toward entry debit').value).toBe('250');expect(screen.getByLabelText('Holding days for borrowing').value).toBe('73');
  });
  it('resets funding when loading an older unfinanced kept scenario',async()=>{
    const {user}=setup();await openLab(user);await expiryInputs(user);edit('Options scenario name','Unfinanced');await user.click(screen.getByRole('button',{name:'Keep scenario'}));if(!screen.getByText('Borrowing (optional)').parentElement.open)await user.click(screen.getByText('Borrowing (optional)'));await user.click(screen.getByLabelText('Include borrowing costs'));edit('Borrowed toward entry debit','250');
    await user.click(screen.getByRole('button',{name:'Load scenario'}));expect(screen.getByLabelText('Include borrowing costs').checked).toBe(false);
    const old={...upgradeOptions(null),engine_version:2};for(const k of ['financing_enabled','borrowed_amount','borrowing_rate','financing_days'])delete old[k];
    expect(validOptions(old)).toBe(true);expect(upgradeOptions(old).financing_enabled).toBe(false);expect(upgradeOptions(old).engine_version).toBe(4);
  });
  it('shows signed effective leverage and does not reuse a stale leverage result',async()=>{
    const {user}=setup(()=>ok(funding.dated));await openLab(user);edit('Current underlying price','100');edit('Leg 1 Strike','100');edit('Leg 1 Premium per unit','5');edit('Leg 1 Expiration','2027-01-01');edit('Leg 1 IV % (blank = infer)','20');edit('Calculation date','2026-01-01');edit('Scenario underlying price','120');if(!screen.getByText('Borrowing (optional)').parentElement.open)await user.click(screen.getByText('Borrowing (optional)'));await user.click(screen.getByLabelText('Include borrowing costs'));edit('Borrowed toward entry debit','250');edit('Annual borrowing rate (%)','10');await user.click(screen.getByRole('button',{name:'Calculate strategy'}));
    await screen.findByText('Advanced sensitivity & borrowing details');await user.click(screen.getByText('Advanced sensitivity & borrowing details'));await screen.findByRole('heading',{name:'Leverage & exposure'});expect(screen.getByText('21.59×')).toBeTruthy();
    edit('Leg 1 Contracts','2');expect(screen.queryByRole('heading',{name:'Leverage & exposure'})).toBeNull();
  });
  it('migrates old vertical inputs without losing prices or size',()=>{
    const old={strategy:'vertical',symbol:'AAPL',expiration:'2027-01-15',contracts:'2',multiplier:'100',strike:'',premium:'',stock_entry:'',option_type:'put',long_strike:'110',long_premium:'7',short_strike:'100',short_premium:'3',range_min:'0',range_max:'',scenario_price:'90'};expect(validOptions(old)).toBe(true);const migrated=upgradeOptions(old);expect(migrated.valuation_mode).toBe('expiry');expect(migrated.legs[0]).toMatchObject({kind:'put',quantity:'2',strike:'110',premium:'7'});expect(validOptions(migrated)).toBe(true);expect(setupSnapshot(migrated).scenarios).toBeUndefined();expect(validOptions({...migrated,legs:[{}]})).toBe(false);
  });
});
