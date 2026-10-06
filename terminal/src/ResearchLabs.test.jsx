import React,{useState} from 'react';
import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent,act} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';
import {CryptoLab,VolatilityLab} from './ResearchLabs.jsx';
import StrategyTransfer from './StrategyTransfer.jsx';
import {emptyCrypto,emptySurface,cryptoExample,validCrypto,validSurface} from './research-model.js';
import {equityTransfer,optionTransfer,keepAndTransfer} from './strategy-transfer.js';
import {emptyOptions,validOptions} from './options-model.js';
import {emptyOptionPricing} from './derivatives-model.js';
import cryptoResult from './fixtures/crypto.json';
import surfaceResult from './fixtures/volatility.json';
import * as data from './data.js';
vi.mock('recharts',async()=>({...await vi.importActual('recharts'),ResponsiveContainer:({children})=><div>{React.cloneElement(children,{width:600,height:300})}</div>}));
const ok=data=>({ok:true,json:async()=>data});
const edit=(label,value)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
function Host({kind='crypto'}){const [s,set]=useState(kind==='crypto'?emptyCrypto():emptySurface());const Lab=kind==='crypto'?CryptoLab:VolatilityLab;return <Lab inputs={s} onChange={set}/>;}

it('runs an explicit crypto example and exports observations, hiding stale results',async()=>{
  const fetch=vi.fn(async()=>ok(cryptoResult));vi.stubGlobal('fetch',fetch);const download=vi.spyOn(data,'download').mockImplementation(()=>{});
  render(<Host/>);const user=userEvent.setup();await user.click(screen.getByText('Try crypto example'));
  expect(screen.getByLabelText('Crypto ticker 1').value).toBe('');await user.click(screen.getByText('Load crypto example'));
  await user.click(screen.getByText('Analyze crypto'));await screen.findByRole('region',{name:'Crypto results'});
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({source:'demo',holdings:[{ticker:'DEMO-BTC',quantity:.1,avg_cost:35000},{ticker:'DEMO-ETH',quantity:2,avg_cost:null}],cash:1000});
  await user.click(screen.getByText('Download inputs, data & results'));expect(JSON.parse(download.mock.calls[0][0].content).observations).toEqual(cryptoResult.observations);
  edit('Crypto cash (USD)','3000');expect(screen.queryByRole('region',{name:'Crypto results'})).toBeNull();
});

it('renders the observed grid and excluded-quote audit without filling gaps',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>ok(surfaceResult)));render(<Host kind="surface"/>);const user=userEvent.setup();
  await user.click(screen.getByText('Build volatility grid'));await screen.findByRole('table',{name:'Volatility grid'});
  expect(screen.getByText('13 quotes included · 17 excluded (including the unselected side)')).toBeTruthy();
  expect(screen.getByRole('table',{name:'Volatility quote audit'})).toBeTruthy();
  edit('Surface interest rate (%)','4');expect(screen.queryByRole('region',{name:'Volatility results'})).toBeNull();
});

it('prevents stale crypto responses and preserves input after errors',async()=>{
  let resolve;vi.stubGlobal('fetch',vi.fn(()=>new Promise(r=>{resolve=r;})));render(<Host/>);const user=userEvent.setup();
  await user.click(screen.getByText('Analyze crypto'));edit('Crypto cash (USD)','12');
  await act(async()=>resolve(ok(cryptoResult)));expect(screen.queryByRole('region',{name:'Crypto results'})).toBeNull();
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,json:async()=>({error:'Missing UTC day'})})));
  await user.click(screen.getByText('Analyze crypto'));expect(await screen.findByRole('alert')).toBeTruthy();expect(screen.getByLabelText('Crypto cash (USD)').value).toBe('12');
});

it('saves both research tabs without changing the equity holdings',async()=>{
  let saved;
  vi.stubGlobal('fetch',vi.fn(async(url,opts)=>{if(url==='/api/portfolios')return ok({portfolios:[]});if(url==='/api/portfolios/save'){saved=JSON.parse(opts.body);return ok({...saved,revision:1});}throw Error(url);}));
  const user=userEvent.setup();render(<App/>);await user.click(screen.getByRole('tab',{name:'Crypto',exact:true}));edit('Crypto ticker 1','BTC-USD');edit('Crypto quantity 1','.02');
  await user.click(screen.getByRole('tab',{name:'Volatility',exact:true}));edit('Surface interest rate (%)','4.25');
  edit('Portfolio name','Independent labs');await user.click(screen.getByRole('button',{name:'Save portfolio',exact:true}));
  expect(saved.state.crypto.holdings[0]).toMatchObject({ticker:'BTC-USD',quantity:'.02'});expect(saved.state.volatility.rate).toBe('4.25');expect(saved.state.holdings).toEqual([]);
  expect(validCrypto(cryptoExample())).toBe(true);expect(validSurface(emptySurface())).toBe(true);expect(validCrypto({...emptyCrypto(),holdings:[]})).toBe(false);
});

it('transfers theoretical targets without inventing market premiums',()=>{
  const equity=equityTransfer({currency:'USD',current_price:'100',valuation_date:'2025-01-01'},{price:135,case:'Base',method:'growth'},'TEST','2026-01-01');
  expect(equity).toMatchObject({spot:'100',scenario_price:'135',target_date:'2026-01-01'});expect(equity.legs[0].premium).toBe('');
  const inputs={...emptyOptionPricing(),symbol:'TEST',spot:'100',strike:'105',as_of:'2025-01-01',maturity:'2026-01-01',volatility:'20'};
  const option=optionTransfer(inputs,{unit_price:8,model:'BSM'},'TEST');expect(option.legs[0].premium).toBe('');expect(option.legs[0].quote_note).toContain('8 USD/unit');
  expect(optionTransfer({...inputs,market_price:'9'},{unit_price:8,model:'BSM'},'TEST').legs[0].premium).toBe('9');
  expect(()=>optionTransfer({...inputs,exercise:'american'},{},'TEST')).toThrow(/European/);
  expect(()=>equityTransfer({currency:'EUR'}, {},'TEST','2026-01-01')).toThrow(/currency/);
  expect(validOptions(equity)).toBe(true);expect(validOptions(option)).toBe(true);
});

it('preserves the previous strategy and refuses to overwrite a full scenario library',()=>{
  const old={...emptyOptions(),symbol:'OLD',spot:'120'},next={...emptyOptions(),symbol:'NEW'};
  const result=keepAndTransfer(old,next);expect(result.symbol).toBe('NEW');expect(result.scenarios[0].state.spot).toBe('120');expect(old.scenarios).toEqual([]);
  expect(()=>keepAndTransfer({...old,scenarios:Array(12).fill(result.scenarios[0])},next)).toThrow(/12/);
});

it('offers an explicit reviewed DCF transfer and reports missing ticker',async()=>{
  const transfer=vi.fn();render(<StrategyTransfer type="equity" inputs={{currency:'USD',valuation_date:'2025-01-01',current_price:'100'}} result={{dcf:[{price:140,case:'Base',method:'growth'}]}} onTransfer={transfer}/>);
  const user=userEvent.setup();edit('Hypothesis target date','2026-01-01');await user.click(screen.getByText('Keep current strategy & open hypothesis'));
  expect(transfer).not.toHaveBeenCalled();expect(screen.getByRole('alert')).toBeTruthy();edit('Strategy ticker','TEST');await user.click(screen.getByText('Keep current strategy & open hypothesis'));
  expect(transfer).toHaveBeenCalledWith(expect.objectContaining({symbol:'TEST',scenario_price:'140'}));
});
