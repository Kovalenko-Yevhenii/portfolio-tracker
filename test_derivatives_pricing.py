"""Closed-form benchmarks, independent tree rollback, limits and saved-draft safety."""
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import unittest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from derivatives_pricing import (OptionPricingRequest, FuturesPricingRequest, price_option,
                                 price_futures, crr, deterministic_american)
from portfolio_store import PortfolioStore, SavePortfolio, StoreError
from terminal_api import app
from tracker import PortfolioError


def option(**changes):
    return OptionPricingRequest(**dict(dict(as_of='2026-09-30',maturity='2027-09-30',spot=100,
        strike=100,volatility=20,rate=5,dividend_yield=0,contract_size=100,contracts=2),**changes))


def futures(**changes):
    return FuturesPricingRequest(**dict(dict(as_of='2026-09-30',maturity='2027-09-30',spot=100,
        rate=5,income_yield=2,contract_size=50,contracts=2),**changes))


class OptionPricingTests(unittest.TestCase):
    def test_published_atm_benchmark_and_contract_scaling(self):
        r=price_option(option());p=price_option(option(kind='put'))
        self.assertAlmostEqual(r['unit_price'],10.450583572185565,12)
        self.assertAlmostEqual(p['unit_price'],5.573526022256971,12)
        self.assertAlmostEqual(r['per_contract'],1045.0583572185565,9)
        self.assertAlmostEqual(r['total_premium'],2090.116714437113,9)
        self.assertAlmostEqual(r['greeks']['delta'],.6368306511756191,12)
        self.assertAlmostEqual(r['greeks']['gamma'],.0187620173458469,12)
        self.assertAlmostEqual(r['greeks']['vega'],.3752403469169379,12)
        self.assertAlmostEqual(r['greeks']['rho'],.5323248154537634,12)
        self.assertAlmostEqual(r['greeks']['theta'],-6.414027546438197/365,12)
        self.assertEqual(r['sensitivity']['rows'][2]['values'][2],r['unit_price'])

    def test_dividend_parity_negative_rates_and_calendar_days(self):
        c=price_option(option(rate=-2,dividend_yield=3,as_of='2027-03-01',maturity='2028-03-01'))
        p=price_option(option(kind='put',rate=-2,dividend_yield=3,as_of='2027-03-01',maturity='2028-03-01'))
        self.assertEqual(c['days'],366)
        self.assertAlmostEqual(c['unit_price']-p['unit_price'],100*math.exp(-.03*366/365)-100*math.exp(.02*366/365),11)

    def test_greek_units_match_independent_central_differences(self):
        from options_pricing import bsm
        r=price_option(option(dividend_yield=2));g=r['greeks'];h=.0001
        f=lambda s=100,t=1,v=.2,rate=.05:bsm('call',s,100,t,v,rate,.02)
        self.assertAlmostEqual(g['delta'],(f(s=100+h)-f(s=100-h))/(2*h),8)
        self.assertAlmostEqual(g['vega'],(f(v=.2+h)-f(v=.2-h))/(2*h)/100,6)
        self.assertAlmostEqual(g['rho'],(f(rate=.05+h)-f(rate=.05-h))/(2*h)/100,6)
        self.assertAlmostEqual(g['theta'],(f(t=1-h)-f(t=1+h))/(2*h)/365,8)

    def test_american_matches_independent_three_step_recursion(self):
        s,k,t,sigma,r,q,n=40,40,1,.2,.06,.02,3
        u=math.exp(sigma*math.sqrt(t/n));d=1/u;p=(math.exp((r-q)*t/n)-d)/(u-d)
        def recurse(stock,remaining):
            exercise=max(k-stock,0)
            if remaining==0:return exercise
            hold=math.exp(-r*t/n)*(p*recurse(stock*u,remaining-1)+(1-p)*recurse(stock*d,remaining-1))
            return max(exercise,hold)
        tree=crr('put',s,k,t,sigma,r,q,n)
        self.assertAlmostEqual(tree['price'],recurse(s,n),12)

    def test_american_put_early_exercise_and_european_benchmark(self):
        r=price_option(option(exercise='american',kind='put',spot=80))
        c=r['convergence'];self.assertGreaterEqual(r['unit_price'],20)
        self.assertGreater(c['early_exercise_premium'],0)
        self.assertAlmostEqual(c['early_exercise_premium'],c['fine_price']-c['european_tree'])
        self.assertEqual(c['fine_steps'],1000)
        self.assertAlmostEqual(c['difference'],abs(c['coarse_price']-c['fine_price']))
        self.assertIsNone(r['greeks'])
        self.assertEqual(r['sensitivity']['rows'][2]['values'][2],r['unit_price'])
        no_div=price_option(option(exercise='american'))
        self.assertAlmostEqual(no_div['convergence']['early_exercise_premium'],0,10)
        self.assertLess(abs(no_div['unit_price']-no_div['european_price']),.003)

    def test_expiry_and_zero_volatility_boundaries(self):
        for exercise in ['european','american']:
            for kind,spot,expected in [('call',120,20),('put',80,20),('call',80,0)]:
                r=price_option(option(exercise=exercise,kind=kind,spot=spot,maturity='2026-09-30',market_price=20))
                self.assertEqual(r['unit_price'],expected);self.assertIsNone(r['implied_volatility'])
                if r['greeks']:self.assertTrue(all(v is None for v in r['greeks'].values()))
        zero=price_option(option(volatility=0))
        self.assertAlmostEqual(zero['unit_price'],100-100*math.exp(-.05),12)
        self.assertTrue(all(v is None for v in zero['greeks'].values()))
        # Continuous optimal stopping may occur between endpoints, even at zero vol.
        self.assertAlmostEqual(deterministic_american('call',100,80,10,.1,.05),31.25,12)
        self.assertAlmostEqual(deterministic_american('put',80,100,10,.05,.1),31.25,12)

    def test_invalid_tree_and_unavailable_sensitivity_cells(self):
        with self.assertRaises(PortfolioError):price_option(option(exercise='american',volatility=.001))
        r=price_option(option(exercise='american',volatility=5.001))
        self.assertTrue(any(v is None for row in r['sensitivity']['rows'] for v in row['values']))
        self.assertTrue(any('unavailable' in w for w in r['warnings']))
        json.dumps(r,allow_nan=False)

    def test_european_implied_vol_roundtrip_and_invalid_quotes(self):
        value=price_option(option(dividend_yield=2))['unit_price']
        self.assertAlmostEqual(price_option(option(dividend_yield=2,market_price=value))['implied_volatility'],20,10)
        for quote in [0,101]:
            result=price_option(option(market_price=quote))
            self.assertIsNone(result['implied_volatility']);self.assertTrue(result['warnings'])
            self.assertAlmostEqual(result['market_gap'],quote-result['unit_price'])
        self.assertEqual(price_option(option(rate=0,market_price=0))['implied_volatility'],0)
        self.assertIsNone(price_option(option(exercise='american',market_price=10))['implied_volatility'])

    def test_validation_rejects_missing_nonfinite_and_unsupported_inputs(self):
        for patch_ in [dict(spot=0),dict(volatility=-1),dict(volatility=.00001),dict(rate=float('nan')),
                       dict(maturity='2026-09-29'),dict(maturity='2040-01-01'),dict(strike=None),
                       dict(contracts=1.5),dict(tree_steps=1000000),dict(exercise='bermudan')]:
            with self.subTest(patch_=patch_),self.assertRaises(ValidationError):option(**patch_)


class FuturesPricingTests(unittest.TestCase):
    def test_equity_fx_and_commodity_carry(self):
        for req,carry in [(futures(),.03),(futures(asset='fx',income_yield=0,foreign_rate=2),.03),
                          (futures(asset='commodity',income_yield=0,storage_rate=2,convenience_yield=1),.06)]:
            r=price_futures(req);self.assertAlmostEqual(r['unit_price'],100*math.exp(carry),12)
            self.assertAlmostEqual(r['basis'],100*math.expm1(carry),12)
            self.assertAlmostEqual(r['total_notional'],r['unit_price']*100,9)
            self.assertAlmostEqual(r['per_contract_notional'],r['unit_price']*50,9)
            self.assertEqual(r['sensitivity']['rows'][2]['values'][2],r['unit_price'])

    def test_expiry_negative_carry_quote_gap_and_sensitivities(self):
        r=price_futures(futures(maturity='2026-09-30',market_price=101))
        self.assertEqual(r['unit_price'],100);self.assertEqual(r['market_gap'],1)
        self.assertEqual(r['market_gap_percent'],1);self.assertEqual(r['rate_sensitivity'],0)
        self.assertEqual(r['spot_sensitivity'],1)
        backward=price_futures(futures(rate=-1))
        self.assertLess(backward['unit_price'],100)
        self.assertAlmostEqual(backward['spot_sensitivity'],math.exp(-.03))
        self.assertAlmostEqual(backward['rate_sensitivity'],backward['unit_price']/100)

    def test_irrelevant_carry_fields_cannot_silently_change_formula(self):
        for change in [dict(foreign_rate=2),dict(storage_rate=1),dict(asset='fx'),
                       dict(asset='commodity'),dict(contract_size=0),dict(spot=-10),dict(market_price=0)]:
            with self.subTest(change=change),self.assertRaises(ValidationError):futures(**change)

    def test_endpoints_only_use_manual_inputs_and_report_invalid_values(self):
        client=TestClient(app)
        with patch('terminal_api.fetch_price_history',side_effect=AssertionError('No market request')):
            for path,request in [('option',option()),('futures',futures())]:
                body=request.model_dump(mode='json');response=client.post('/api/analytics/'+path,json=body)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(client.post('/api/analytics/'+path,json={**body,'spot':None}).status_code,422)
            response=client.post('/api/analytics/option',json=option(exercise='american',volatility=.001).model_dump(mode='json'))
            self.assertEqual(response.status_code,400)

    def test_derivative_drafts_roundtrip_and_old_page_cannot_erase_them(self):
        with TemporaryDirectory() as directory:
            store=PortfolioStore(Path(directory)/'p.sqlite3');pid=uuid4()
            saved=store.save(SavePortfolio(id=pid,name='Pricing',revision=0,state={'analytics':{
                'version':2,'tool':'futures','company':'Existing DCF','shares':'10.123456789',
                'option_pricing':{'strike':'','volatility':'25.125','exercise':'american'},
                'futures_pricing':{'spot':'','asset':'commodity','storage_rate':'1.25'}}}))
            loaded=store.get(pid);self.assertEqual(loaded['state'],saved['state'])
            self.assertEqual(loaded['state']['analytics']['option_pricing']['strike'],'')
            self.assertEqual(loaded['state']['analytics']['shares'],'10.123456789')
            with self.assertRaises(StoreError):store.save(SavePortfolio(id=pid,name='Pricing',revision=1,state={'analytics':{'version':1}}))
            self.assertEqual(store.get(pid)['state'],loaded['state'])
            preserved=store.save(SavePortfolio(id=pid,name='Pricing renamed',revision=1,state={'cash':'50'}))
            self.assertEqual(preserved['state']['analytics'],loaded['state']['analytics'])


if __name__=='__main__':unittest.main()
