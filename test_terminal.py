"""API parity, serialization, validation, and market-cache regressions."""
import json
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
import terminal_api as api
import tracker
from portfolio_analysis import diversification_analysis


def identity(t):
    return {'ticker':t, 'name':'Example '+t, 'exchange':'NYSE', 'currency':'USD'}


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.px = pd.DataFrame({'AAA':[100.,110.,95.,120.,115.,130.],
                               'BBB':[50.,48.,52.,53.,51.,56.],
                               'SPY':[100.,103.,98.,110.,108.,116.]},
                              index=pd.date_range('2025-01-01', periods=6))
        self.adj = self.px.copy()
        self.adj['AAA'] *= np.array([.9,.9,.9,1.,1.,1.])
        self.pos = [{'ticker':'AAA','qty':2.,'avg_cost':80.},{'ticker':'BBB','qty':3.,'avg_cost':45.}]
        self.client = TestClient(api.app)
        api.market_cache.clear()
        self.patch_identity = patch('terminal_api.get_instrument', side_effect=identity)
        self.patch_fetch = patch('terminal_api.fetch_price_history', side_effect=self.fetch)
        self.patch_identity.start(); self.fetch_mock = self.patch_fetch.start()
        self.addCleanup(self.patch_identity.stop); self.addCleanup(self.patch_fetch.stop)

    def fetch(self, tickers, period, interval, include_adjusted=False):
        tickers = list(tickers)
        result = (self.px[tickers].copy(), pd.DataFrame())
        return (*result,self.adj[tickers].copy()) if include_adjusted else result

    def analyze(self, **options):
        response = self.client.post('/api/analyze', json={'positions':self.pos,'cash_balance':100.,'window':2,**options})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_holdings_math_parity_all_bases_and_intervals(self):
        for basis in ['price','total']:
            for interval in ['1d','1wk','1mo']:
                with self.subTest(basis=basis,interval=interval):
                    result = self.analyze(return_basis=basis,interval=interval,annual_risk_free_rate=.04)
                    pos,hist,metrics = tracker.compute_metrics(pd.DataFrame(self.pos),self.px,window_vol=2,
                        interval=interval,adjusted_prices=self.adj if basis=='total' else None,return_basis=basis,cash_balance=100.)
                    for key in ['total_value','total_cost','total_unrealized_pnl','annualized_volatility','maximum_drawdown']:
                        self.assertAlmostEqual(result['metrics'][key],metrics[key])
                    pd.testing.assert_frame_equal(pd.DataFrame(result['history']['data'],columns=hist.columns,index=hist.index),hist,check_dtype=False)
                    comp = tracker.compare_history(hist[['performance_value']].rename(columns={'performance_value':'My portfolio'}),
                        (self.adj if basis=='total' else self.px).SPY,interval=interval,annual_risk_free_rate=.04)
                    self.assertEqual(result['comparison']['summary'],api.table(comp['summary']))
                    self.assertEqual(result['comparison']['risk']['summary'],api.table(comp['risk']['summary']))
                    expected = (hist[['performance_value']] / hist.performance_value.dropna().iloc[0] * 100).rename(columns={'performance_value':'My portfolio'})
                    self.assertEqual(result['performance_normalized'],api.table(expected))
                    d=diversification_analysis(pd.DataFrame(self.pos),self.px,self.adj if basis=='total' else self.px,interval,100.)
                    self.assertEqual(result['diversification']['allocation'],api.table(d['allocation']))

    def test_research_remains_independent_and_benchmark_may_be_selection(self):
        result=self.analyze(mode='research',tickers=['AAA','BBB','SPY'],return_basis='total')
        self.assertIsNone(result['metrics']); self.assertIsNone(result['diversification'])
        self.assertEqual(result['comparison']['summary']['index'],['AAA','BBB','SPY','Benchmark: SPY'])
        self.assertEqual(len(result['exports']),4)

    def test_allocation_cash_and_fractional_quantity(self):
        result=self.analyze(source='allocation',total_invested=1000,allocation_unit='dollars',
            allocations=[{'ticker':'AAA','allocation':100,'purchase_price':30}])
        self.assertEqual(result['metrics']['cash_balance'],900.)
        self.assertAlmostEqual(result['positions']['data'][0][1],10/3)
        over=self.client.post('/api/allocation',json={'total_invested':100,'allocations':[{'ticker':'AAA','allocation':101,'purchase_price':1}]})
        self.assertEqual(over.status_code,400);self.assertIn('exceed',over.json()['error'])

    def test_cash_only_no_cash_ticker_and_undefined_values(self):
        result=self.analyze(positions=[],cash_balance=1000)
        self.assertEqual(result['metrics']['total_value'],1000)
        self.assertEqual(result['metrics']['maximum_drawdown'],0)
        self.assertEqual(self.fetch_mock.call_args.args[0],['SPY'])
        self.assertIsNone(result['comparison']['risk']['summary']['data'][0][0])
        json.dumps(result,allow_nan=False)

    def test_gaps_are_json_null_and_not_zero(self):
        self.px.loc[self.px.index[2],'AAA']=np.nan
        result=self.analyze()
        idx=result['history']['columns'].index('portfolio_value')
        self.assertIsNone(result['history']['data'][2][idx])
        idx=result['history']['columns'].index('returns')
        self.assertIsNone(result['history']['data'][3][idx])
        self.assertTrue(result['warnings'])

    def test_export_values_and_cash_reference(self):
        result=self.analyze(return_basis='total')
        exports={e['name']:e['content'] for e in result['exports']}
        self.assertEqual(len(exports),9)
        positions=pd.read_csv(StringIO(exports['positions_with_prices.csv']))
        self.assertEqual(positions.market_value.sum()+100,result['metrics']['total_value'])
        self.assertEqual(json.loads(exports['holdings_settings.json'])['cash_balance'],100)
        exported=pd.read_csv(StringIO(exports['comparison_risk_total.csv']))
        self.assertTrue(exported.return_basis.eq('total').all())

    def test_csv_validation_consolidation_and_error(self):
        good=self.client.post('/api/import',json={'text':'ticker,qty,avg_cost\nAAA,1,100\naaa,3,200\n'})
        self.assertEqual(good.status_code,200)
        self.assertEqual(good.json()['positions'][0]['avg_cost'],175.)
        bad=self.client.post('/api/import',json={'text':'ticker,qty,avg_cost\nAAA,-1,100\n'})
        self.assertEqual(bad.status_code,400)

    def test_input_and_provider_errors_are_actionable(self):
        for body in [{'positions':self.pos,'cash_balance':-1},{'positions':self.pos,'return_basis':'bad'},
                     {'positions':self.pos,'annual_risk_free_rate':None},{'positions':self.pos,'window':2.5}]:
            response=self.client.post('/api/analyze',json=body)
            self.assertEqual(response.status_code,422);self.assertIn('error',response.json())
        with patch('terminal_api.get_instrument',side_effect=tracker.PortfolioError('Cannot verify AAA')):
            response=self.client.post('/api/analyze',json={'positions':self.pos})
            self.assertEqual(response.status_code,400);self.assertIn('Cannot verify',response.json()['error'])

    def test_search_identity_cache_and_refresh(self):
        with patch('terminal_api.search_instruments',return_value=[identity('AAA')]) as search:
            for _ in range(2): self.assertEqual(self.client.get('/api/search?q=Apple').status_code,200)
            self.assertEqual(search.call_count,1)
        self.analyze();self.analyze();self.assertEqual(self.fetch_mock.call_count,1)
        self.analyze(refresh=True);self.assertEqual(self.fetch_mock.call_count,2)

    def test_cross_origin_request_rejected(self):
        response=self.client.post('/api/analyze',json={'positions':self.pos},headers={'origin':'https://other.example'})
        self.assertEqual(response.status_code,403)

    def test_streamlit_results_match_terminal(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        for basis in ['price','total']:
            with self.subTest(basis=basis),patch('tracker.get_instrument',side_effect=identity),patch('tracker.fetch_price_history',side_effect=self.fetch):
                st.cache_data.clear()
                app=AppTest.from_file(str(Path(__file__).with_name('streamlit_app.py')))
                app.session_state['selections']=[identity('AAA'),identity('BBB')]
                app.session_state['holding_values']={p['ticker']:{'qty':p['qty'],'avg_cost':p['avg_cost']} for p in self.pos}
                app.run()
                app.number_input(key='manual_cash_balance').set_value(100.)
                if basis=='total':app.radio(key='return_basis').set_value('Total return (dividends reinvested)')
                app.run()
                next(b for b in app.button if b.label=='Analyze').click().run()
                self.assertEqual(len(app.exception),0)
                old=app.session_state['analysis']['result']
                new=self.analyze(return_basis=basis,window=30)
                self.assertEqual(api.table(old['comparison']['normalized']),new['comparison']['normalized'])
                self.assertEqual(api.table(old['comparison']['risk']['summary']),new['comparison']['risk']['summary'])
                self.assertEqual(api.table(old['diversification']['allocation']),new['diversification']['allocation'])


if __name__=='__main__':unittest.main()
