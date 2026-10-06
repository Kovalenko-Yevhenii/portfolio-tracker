import json
import math
from datetime import date,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import unittest
from unittest.mock import patch
import pandas as pd
from fastapi.testclient import TestClient
from pydantic import ValidationError
from options_pricing import ScenarioRequest,OptionLeg,analyze_scenario,bsm,greeks,implied_vol
from options_market import FinderRequest,find_options,option_chain
from portfolio_store import PortfolioStore,SavePortfolio,StoreError
from tracker import PortfolioError
from terminal_api import app


def leg(kind='call',side='buy',strike=100,premium=5,**extra):
    return dict(kind=kind,side=side,strike=strike,premium=premium,**extra)


def analyze(legs,**kwargs):
    return analyze_scenario(ScenarioRequest(legs=legs,mode='expiry',**kwargs))


class PricingTests(unittest.TestCase):
    def test_black_scholes_known_values_put_call_parity_and_limits(self):
        self.assertAlmostEqual(bsm('call',100,100,1,.2,.05),10.450583572185565,places=10)
        self.assertAlmostEqual(bsm('put',100,100,1,.2,.05),5.573526022256971,places=10)
        for s in [0,50,100,200]:
            for t in [0,.5,2]:
                for sigma in [0,.2,1.5]:
                    c=bsm('call',s,100,t,sigma,.03,.02);p=bsm('put',s,100,t,sigma,.03,.02)
                    self.assertAlmostEqual(c-p,s*math.exp(-.02*t)-100*math.exp(-.03*t),places=9)

    def test_greeks_match_finite_differences_with_dividends(self):
        for kind in ['call','put']:
            s,k,t,v,r,q=105,100,.7,.27,.04,.015;h=.0001
            g=greeks(kind,s,k,t,v,r,q)
            f=lambda spot=s,time=t,vol=v,rate=r:bsm(kind,spot,k,time,vol,rate,q)
            self.assertAlmostEqual(g['delta'],(f(spot=s+h)-f(spot=s-h))/(2*h),places=7)
            self.assertAlmostEqual(g['gamma'],(f(spot=s+.01)-2*f()+f(spot=s-.01))/.0001,places=6)
            self.assertAlmostEqual(g['theta'],-(f(time=t+h)-f(time=t-h))/(2*h*365),places=7)
            self.assertAlmostEqual(g['vega'],(f(vol=v+h)-f(vol=v-h))/(2*h*100),places=7)
            self.assertAlmostEqual(g['rho'],(f(rate=r+h)-f(rate=r-h))/(2*h*100),places=7)
        self.assertIsNone(greeks('call',100,100,0,.2,0,0)['delta'])

    def test_iv_solver_round_trip_and_invalid_premium(self):
        for kind in ['call','put']:
            premium=bsm(kind,100,110,1,.35,.03,.01)
            self.assertAlmostEqual(implied_vol(kind,premium,100,110,1,.03,.01),.35,places=9)
        with self.assertRaises(PortfolioError):implied_vol('call',150,100,100,1,0,0)

    def test_short_call_unlimited_loss_and_put_price_floor(self):
        call=analyze([leg(side='sell')]);put=analyze([leg('put','sell')])
        self.assertTrue(call['summary']['loss_unlimited']);self.assertEqual(call['summary']['maximum_profit'],500)
        self.assertEqual(put['summary']['maximum_loss'],9500);self.assertEqual(put['summary']['break_evens'],[95])
        self.assertIsNone(call['capital_basis'])

    def test_straddle_condor_butterfly_and_ratio_known_outcomes(self):
        straddle=analyze([leg(),leg('put')])['summary']
        self.assertEqual(straddle['break_evens'],[90,110]);self.assertEqual(straddle['maximum_loss'],1000)
        condor=analyze([leg('put','buy',90,1),leg('put','sell',95,2),leg('call','sell',105,2),leg('call','buy',110,1)])['summary']
        self.assertEqual(condor['maximum_profit'],200);self.assertEqual(condor['maximum_loss'],300);self.assertEqual(condor['break_evens'],[93,107])
        butterfly=analyze([leg(strike=90,premium=12),leg(side='sell',strike=100,premium=5,quantity=2),leg(strike=110,premium=1)])['summary']
        self.assertEqual(butterfly['maximum_profit'],700);self.assertEqual(butterfly['maximum_loss'],300);self.assertEqual(butterfly['break_evens'],[93,107])
        ratio=analyze([leg(side='sell',strike=100,premium=5),leg(strike=110,premium=2,quantity=2)])['summary']
        self.assertTrue(ratio['profit_unlimited']);self.assertEqual(ratio['maximum_loss'],900);self.assertEqual(ratio['break_evens'],[101,119])

    def test_stock_leg_scaling_covered_and_reverse_conversion(self):
        covered=analyze([leg('stock',quantity=100,premium=95),leg(side='sell',premium=3)],scenario_price=120)
        self.assertEqual(covered['scenario_pnl'],800);self.assertEqual(covered['summary']['maximum_loss'],9200)
        reverse=analyze([leg('stock','sell',quantity=100,premium=100),leg(premium=5),leg('put','sell',premium=5)])
        self.assertEqual(reverse['summary']['break_even_ranges'],[{'from':0.,'to':None}])
        self.assertEqual(reverse['summary']['maximum_loss'],0)
        mismatch=analyze([leg('stock',quantity=50,premium=95),leg(side='sell',premium=3)])
        self.assertTrue(mismatch['summary']['loss_unlimited'])

    def test_fees_custom_sizes_exact_roots_and_leg_reconciliation(self):
        r=analyze([leg(premium=.3,multiplier=10,quantity=2)],scenario_price=100.3,fee_per_contract=1)
        self.assertEqual(r['summary']['break_evens'],[100.4]);self.assertAlmostEqual(r['scenario_pnl'],-2)
        self.assertEqual(r['fees'],2)
        self.assertAlmostEqual(sum(l['pnl'] for l in r['legs']),r['scenario_pnl'])
        self.assertAlmostEqual(sum(l['initial_cash_flow'] for l in r['legs']),-r['initial_debit'])

    def test_global_extrema_independent_of_zoom_and_zero_premium_ranges(self):
        full=analyze([leg('put')]);zoom=analyze([leg('put')],range_min=99,range_max=101,scenario_price=0)
        self.assertEqual(full['summary'],zoom['summary']);self.assertEqual(zoom['scenario_pnl'],9500)
        zero=analyze([leg(premium=0)])['summary']
        self.assertEqual(zero['break_even_ranges'],[{'from':0.,'to':100.}])

    def test_cash_collateral_and_optional_return_basis(self):
        csp=analyze([leg('put','sell')],strategy='cash_secured_put')
        self.assertEqual(csp['capital_basis'],10000)
        custom=analyze([leg(side='sell')],capital_basis=20000)
        self.assertEqual(custom['capital_basis'],20000)
        covered=analyze([leg('stock',quantity=100,premium=100),leg(side='sell')],include_stock_cost=False)
        self.assertEqual(covered['capital_basis'],9500)

    def test_calendar_retains_time_value_and_limits_horizon(self):
        a=date(2026,1,1);first=a+timedelta(days=30);second=a+timedelta(days=90)
        req=ScenarioRequest(mode='dated',as_of=a,spot=100,legs=[leg(expiration=second,iv=25,premium=5),leg(side='sell',expiration=first,iv=25,premium=2)])
        r=analyze_scenario(req)
        self.assertIsNone(r['summary']);self.assertIsNone(r['probability_of_profit']);self.assertEqual(r['horizon'],str(first))
        self.assertGreater(r['legs'][0]['position_value'],0);self.assertEqual(r['legs'][1]['position_value'],0)
        self.assertAlmostEqual(r['scenario_pnl'],bsm('call',100,100,60/365,.25)*100-300)
        with self.assertRaises(PortfolioError):analyze_scenario(req.model_copy(update={'target_date':first+timedelta(days=1)}))
        with self.assertRaises(PortfolioError):analyze_scenario(req.model_copy(update={'mode':'expiry'}))

    def test_dated_grid_terminal_payoff_greeks_and_probability(self):
        a=date(2026,1,1);exp=a+timedelta(days=365)
        r=analyze_scenario(ScenarioRequest(mode='dated',as_of=a,spot=100,legs=[leg(premium=5,expiration=exp,iv=20)],scenario_price=120))
        self.assertEqual(r['scenario_pnl'],1500);self.assertEqual(r['summary']['break_evens'],[105])
        expected=1-.5*math.erfc(-(math.log(1.05)+.3*.3/2)/.3/math.sqrt(2))
        self.assertAlmostEqual(r['probability_of_profit'],expected)
        self.assertAlmostEqual(r['greeks']['delta'],greeks('call',100,100,1,.2,0,0)['delta']*100)
        for row in r['grid']:
            self.assertAlmostEqual(row['values'][-1]['pnl'],max(row['price']-100,0)*100-500)
        self.assertEqual(len(r['dates']),11)

    def test_iv_shift_and_stock_comparison(self):
        a=date(2026,1,1);exp=a+timedelta(days=365)
        req=ScenarioRequest(mode='dated',as_of=a,spot=100,legs=[leg(expiration=exp,iv=20)],target_date=a,comparison_budget=1000,scenario_price=110)
        r=analyze_scenario(req);up=analyze_scenario(req.model_copy(update={'iv_shift':10}))
        self.assertGreater(up['scenario_pnl'],r['scenario_pnl']);self.assertAlmostEqual(up['legs'][0]['effective_iv'],30)
        point=next(p for p in r['chart'] if p['price']==110);self.assertEqual(point['stock_pnl'],100)
        with self.assertRaises(PortfolioError):analyze_scenario(req.model_copy(update={'iv_shift':-21}))

    def test_validation_and_endpoint(self):
        client=TestClient(app)
        self.assertEqual(client.post('/api/options/model',json={'mode':'expiry','legs':[leg()]}).status_code,200)
        for change in [{'quantity':1.2},{'premium':-1},{'strike':0},{'quantity':0},{'multiplier':0}]:
            self.assertEqual(client.post('/api/options/model',json={'mode':'expiry','legs':[{**leg(),**change}]}).status_code,422)
        self.assertEqual(client.post('/api/options/model',json={'mode':'dated','legs':[leg()]}).status_code,400)
        self.assertEqual(client.post('/api/options/model',json={'mode':'expiry','legs':[leg()]*9}).status_code,400)
        self.assertEqual(client.post('/api/options/model',headers={'Origin':'https://untrusted.example'},json={'mode':'expiry','legs':[leg()]}).status_code,403)


class ProviderAndStorageTests(unittest.TestCase):
    def chain(self):
        exp=str(date.today()+timedelta(days=30))
        rows=[]
        for kind in ['call','put']:
            for strike,premium in [(90,12),(100,5),(110,2)]:
                rows.append(dict(kind=kind,strike=strike,expiration=exp,bid=premium,ask=premium+1,mid=premium+.5,last=premium,iv=25,multiplier=100,currency='USD',open_interest=100,valid_market=True,contract_symbol=f'{kind}{strike}'))
        return dict(symbol='AAPL',currency='USD',spot=100,expiration=exp,contracts=rows,fetched_at='2026-01-01T00:00:00Z')

    def test_finder_uses_ask_bid_risk_limits_and_opens_scenarios(self):
        chain=self.chain();req=FinderRequest(symbol='AAPL',expirations=[chain['expiration']],target_date=chain['expiration'],target_price=120,types=['long','short','debit_spread','credit_spread'],max_risk=700)
        result=find_options(req,[chain]);self.assertTrue(result['results'])
        for row in result['results']:
            self.assertLessEqual(row['maximum_loss'],700)
            self.assertTrue(row['maximum_loss'] is not None)
            modeled=analyze_scenario(ScenarioRequest(mode='dated',spot=100,legs=row['legs'],scenario_price=120,target_date=req.target_date))
            self.assertAlmostEqual(row['pnl'],modeled['scenario_pnl'])
            for l in row['legs']:
                raw=next(r for r in chain['contracts'] if r['contract_symbol']==l['contract_symbol'])
                self.assertEqual(l['premium'],raw['ask'] if l['side']=='buy' else raw['bid'])
        self.assertEqual(result['results'],sorted(result['results'],key=lambda r:r['pnl'],reverse=True))

    def test_finder_excludes_unusable_quotes_and_unknown_contract_size(self):
        chain=self.chain()
        for i,r in enumerate(chain['contracts']):
            if i%2:r['valid_market']=False
            else:r['multiplier']=None
        req=FinderRequest(symbol='AAPL',expirations=[chain['expiration']],target_date=chain['expiration'],target_price=120)
        self.assertEqual(find_options(req,[chain])['results'],[])

    def test_chain_keeps_missing_values_and_identifies_currency(self):
        raw={'contractSymbol':'TEST','strike':100,'bid':float('nan'),'ask':3,'lastPrice':2,'impliedVolatility':.25,'contractSize':'UNKNOWN','currency':'CAD','lastTradeDate':pd.NaT}
        data=type('Chain',(),{'underlying':{'symbol':'X.TO','currency':'CAD','regularMarketPrice':100},'calls':pd.DataFrame([raw]),'puts':pd.DataFrame()})()
        with patch('options_market.yf.Ticker') as ticker:
            ticker.return_value.option_chain.return_value=data
            result=option_chain('X.TO','2026-10-16')
        row=result['contracts'][0]
        self.assertIsNone(row['bid']);self.assertIsNone(row['mid']);self.assertIsNone(row['multiplier']);self.assertIsNone(row['last_trade']);self.assertEqual(result['currency'],'CAD')
        json.dumps(result,allow_nan=False)

    def test_market_api_routes_use_cache_and_validate_dates(self):
        client=TestClient(app);chain=self.chain()
        with patch('terminal_api.expirations',return_value={'symbol':'AAPL','expirations':[chain['expiration']]}),patch('terminal_api.option_chain',return_value=chain) as provider:
            self.assertEqual(client.get('/api/options/expirations?symbol=AAPL&refresh=true').status_code,200)
            self.assertEqual(client.get('/api/options/chain',params={'symbol':'AAPL','expiration':chain['expiration']}).status_code,200)
            response=client.post('/api/options/finder',json={'symbol':'AAPL','expirations':[chain['expiration']],'target_date':chain['expiration'],'target_price':120})
            self.assertEqual(response.status_code,200);self.assertTrue(response.json()['results']);self.assertEqual(provider.call_count,1)
        self.assertEqual(client.get('/api/options/chain?symbol=AAPL&expiration=invalid').status_code,422)
        self.assertEqual(client.post('/api/options/finder',json={'symbol':'AAPL','expirations':[chain['expiration']],'target_date':'2000-01-01','target_price':100}).status_code,400)

    def test_new_drafts_and_scenarios_save_and_old_client_cannot_erase(self):
        with TemporaryDirectory() as directory:
            store=PortfolioStore(Path(directory)/'portfolios.sqlite3');pid=uuid4()
            opts={'engine_version':2,'strategy':'iron_condor','spot':'100','legs':[{'kind':'put','side':'buy','strike':'90','premium':''}],
                  'scenarios':[{'id':'one','name':'Practice','state':{'strategy':'calendar','legs':[{'kind':'call','expiration':'2026-12-18'}]}}]}
            saved=store.save(SavePortfolio(id=pid,name='Test',revision=0,state={'options':opts}))
            loaded=store.get(pid)['state']['options'];self.assertEqual(loaded['legs'][0]['premium'],'');self.assertEqual(loaded['scenarios'][0]['state']['strategy'],'calendar')
            with self.assertRaises(StoreError):store.save(SavePortfolio(id=pid,name='Test',revision=saved['revision'],state={'options':{'strike':'200'}}))
            preserved=store.save(SavePortfolio(id=pid,name='Renamed',revision=saved['revision'],state={}))
            self.assertEqual(preserved['state']['options'],loaded)


if __name__=='__main__':unittest.main()
