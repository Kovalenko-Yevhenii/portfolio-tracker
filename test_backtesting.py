"""Execution timing, hand-computed ledgers, data integrity and saved drafts."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import math
import unittest

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backtesting import BacktestRequest, run_backtest, demo_history, fetch_backtest_history
from portfolio_store import PortfolioStore, SavePortfolio
from terminal_api import app, market_cache
from tracker import PortfolioError


def request(**changes):
    return BacktestRequest(**{**dict(start='2024-01-04', end='2024-01-09', capital=1000,
        assets=[{'ticker': 'AAA', 'weight': 100}], benchmark='AAA', window=2, slippage_bps=0), **changes})


def prices(opens=None, closes=None):
    index = pd.bdate_range('2024-01-02', '2024-01-09')
    return {'AAA': pd.DataFrame({'open': opens or [10, 10, 20, 8, 7, 15],
        'close': closes or [10, 12, 9, 8, 10, 16]}, index=index, dtype=float)}


class BacktestTests(unittest.TestCase):
    def test_previous_close_signal_next_open_and_terminal_mark(self):
        r = run_backtest(request(), prices())
        run = r['runs']['strategy']; t = run['trades']
        self.assertEqual([(x['date'], x['side']) for x in t], [('2024-01-04', 'BUY'), ('2024-01-05', 'SELL'), ('2024-01-09', 'BUY')])
        self.assertEqual(t[0]['signal_date'], '2024-01-03')
        self.assertEqual(t[0]['signal_close'], 12)
        self.assertEqual(t[0]['signal_average'], 11)
        self.assertEqual(t[0]['reference_open'], 20)  # Not the favorable signal close of 12.
        self.assertEqual(t[0]['adjusted_units'], 50)
        self.assertEqual(t[1]['closed_pnl'], -600)
        self.assertAlmostEqual(t[2]['adjusted_units'], 400/15)
        self.assertAlmostEqual(run['summary']['ending_value'], 400/15*16)
        self.assertEqual(run['summary']['closed_trades'], 1)
        self.assertEqual(run['summary']['win_rate'], 0)
        self.assertGreater(run['ending_positions'][0]['units'], 0)  # No forced terminal sale.
        self.assertEqual(r['warmup_sessions'], 2)

    def test_future_price_changes_cannot_alter_earlier_trades_or_values(self):
        first = run_backtest(request(), prices())['runs']['strategy']
        data = prices(); data['AAA'].loc['2024-01-09', ['open','close']] = [1000, 2000]
        second = run_backtest(request(), data)['runs']['strategy']
        self.assertEqual(first['trades'][:2], second['trades'][:2])
        self.assertEqual(first['daily'][:-1], second['daily'][:-1])
        # Today's close must not alter today's opening order.
        data = prices(); data['AAA'].loc['2024-01-04', 'close'] = 999
        third = run_backtest(request(), data)['runs']['strategy']
        self.assertEqual(first['trades'][0], third['trades'][0])

    def test_commissions_and_slippage_hand_calculated_once(self):
        r = run_backtest(request(commission_bps=10, fee_per_order=2, slippage_bps=100), prices())
        t = r['runs']['strategy']['trades']
        units = 998/(20.2*1.001)
        net_sale = units*7.92*.999-2
        self.assertAlmostEqual(t[0]['adjusted_units'], units)
        self.assertAlmostEqual(t[0]['commission'], 2+units*20.2*.001)
        self.assertAlmostEqual(t[0]['slippage_cost'], units*.2)
        self.assertAlmostEqual(t[1]['cash_after'], net_sale)
        self.assertAlmostEqual(t[1]['closed_pnl'], net_sale-1000)
        expected_end = (net_sale-2)/(15.15*1.001)*16
        self.assertAlmostEqual(r['runs']['strategy']['summary']['ending_value'], expected_end)
        self.assertTrue(all(d['cash'] >= 0 for d in r['runs']['strategy']['daily']))

    def test_initial_costs_count_towards_return_and_drawdown(self):
        r = run_backtest(request(strategy='buy_hold', slippage_bps=100), prices([10]*6, [10]*6))
        s = r['runs']['strategy']['summary']
        self.assertAlmostEqual(s['total_return'], 1/1.01-1)
        self.assertAlmostEqual(s['max_drawdown'], 1/1.01-1)
        self.assertIsNone(s['sharpe'])
        self.assertIsNone(s['win_rate'])
        self.assertIsNone(s['cagr'])
        self.assertEqual(s['orders'], 1)

    def test_identical_costs_and_dates_for_same_asset_comparators(self):
        r = run_backtest(request(strategy='buy_hold', slippage_bps=17, commission_bps=4, fee_per_order=1), prices())
        self.assertEqual(r['runs']['strategy'], r['runs']['buy_hold'])
        self.assertEqual(r['runs']['strategy'], r['runs']['benchmark'])

    def test_multiple_assets_are_independent_initial_allocations(self):
        data = prices(); data['BBB'] = pd.DataFrame({'open': [10]*6, 'close': [10]*6}, index=data['AAA'].index)
        req = request(assets=[{'ticker':'AAA','weight':60},{'ticker':'BBB','weight':40}])
        r = run_backtest(req, data)
        # BBB's close equals its average: it stays in its own $400 cash account.
        self.assertEqual(r['runs']['strategy']['ending_positions'][1]['cash'], 400)
        self.assertAlmostEqual(r['runs']['strategy']['summary']['ending_value'], (600*.4/15*16)+400)
        self.assertAlmostEqual(r['runs']['buy_hold']['summary']['ending_value'], 600/20*16+400)
        self.assertEqual(r['runs']['benchmark']['summary']['ending_value'], 1000/20*16)

    def test_equal_to_average_means_cash_and_no_phantom_trades(self):
        r = run_backtest(request(), prices([10]*6, [10]*6))
        run = r['runs']['strategy']
        self.assertEqual(run['trades'], [])
        self.assertEqual(run['summary']['ending_value'], 1000)
        self.assertEqual(run['summary']['average_exposure'], 0)
        self.assertEqual(run['summary']['max_drawdown'], 0)
        self.assertIsNone(run['summary']['sharpe'])

    def test_small_remaining_cash_reports_skipped_entries(self):
        data = prices([10,10,20,.1,7,15])
        r = run_backtest(request(fee_per_order=4), data)
        self.assertEqual(len(r['runs']['strategy']['skipped_orders']), 1)
        self.assertAlmostEqual(r['runs']['strategy']['summary']['ending_value'], .98)

    def test_unfunded_exit_is_rejected_without_negative_cash(self):
        with self.assertRaisesRegex(PortfolioError, 'exceeds sale proceeds'):
            run_backtest(request(fee_per_order=8), prices([10,10,20,.1,7,15]))

    def test_price_scale_changes_units_not_returns_or_dollar_costs(self):
        req = request(commission_bps=5, slippage_bps=5, fee_per_order=1)
        a = run_backtest(req, prices())
        data = prices();data['AAA'] *= .02
        b = run_backtest(req, data)
        for k in ['ending_value', 'pnl', 'total_return', 'max_drawdown', 'commissions', 'slippage_cost']:
            self.assertAlmostEqual(a['runs']['strategy']['summary'][k], b['runs']['strategy']['summary'][k])
        self.assertAlmostEqual(b['runs']['strategy']['trades'][0]['adjusted_units'], a['runs']['strategy']['trades'][0]['adjusted_units']*50)

    def test_risk_statistics_use_close_to_close_and_include_initial_peak(self):
        r = run_backtest(request(strategy='buy_hold', risk_free_percent=5), prices())['runs']['strategy']
        daily = [450, 400, 500, 800]
        returns = np.diff(daily)/np.array(daily[:-1]);sd = np.std(returns, ddof=1)
        self.assertAlmostEqual(r['summary']['volatility'], sd*math.sqrt(252))
        self.assertAlmostEqual(r['summary']['sharpe'], (np.mean(returns)-(1.05**(1/252)-1))/sd*math.sqrt(252))
        self.assertAlmostEqual(r['summary']['max_drawdown'], -.6)

    def test_rejects_missing_interior_start_and_warmup_quotes(self):
        for dt in ['2024-01-02','2024-01-04','2024-01-05']:
            data = prices();data['BBB'] = data['AAA'].copy();data['BBB'] = data['BBB'].drop(dt)
            with self.assertRaisesRegex(PortfolioError, 'Missing or invalid'):
                run_backtest(request(benchmark='BBB'), data)
        for value in [0, -1, np.nan, np.inf]:
            data = prices();data['AAA'].loc['2024-01-05', 'open'] = value
            with self.assertRaisesRegex(PortfolioError, 'Missing or invalid'):
                run_backtest(request(), data)

    def test_duplicate_dates_short_history_and_truncation_rejected(self):
        data=prices();data['AAA']=pd.concat([data['AAA'],data['AAA'].iloc[:1]])
        with self.assertRaisesRegex(PortfolioError,'Duplicate'):run_backtest(request(),data)
        with self.assertRaisesRegex(PortfolioError,'prior sessions'):run_backtest(request(window=3),prices())
        with self.assertRaisesRegex(PortfolioError,'cover the requested'):run_backtest(request(end='2024-02-20'),prices())

    def test_weekend_boundaries_show_actual_dates_and_keep_warmup_out_of_pnl(self):
        r=run_backtest(request(start='2024-01-06'),prices())
        self.assertEqual(r['start'],'2024-01-08');self.assertEqual(r['sessions'],2)
        self.assertEqual(r['runs']['strategy']['daily'][0]['value'],1000)
        self.assertEqual(r['runs']['strategy']['trades'][0]['date'],'2024-01-09')

    def test_input_bounds_duplicates_allocation_dates_and_nan(self):
        for changes in [dict(window=1),dict(window=2.5),dict(capital=float('nan')),dict(start='2025-01-01'),dict(end='2099-01-01'),dict(assets=[{'ticker':'AAA','weight':90}]),dict(assets=[{'ticker':'AAA','weight':50},{'ticker':'aaa','weight':50}]),dict(benchmark='=CMD()'),dict(fee_per_order=1000)]:
            with self.assertRaises(ValidationError):request(**changes)
        self.assertEqual(request(benchmark=' spy ').benchmark,'SPY')

    def test_demo_deterministic_exports_reproducible_and_cagr(self):
        req=BacktestRequest(source='demo',start='2024-01-02',end='2025-12-31',assets=[{'ticker':'DEMO-A','weight':60},{'ticker':'DEMO-B','weight':40}],benchmark='DEMO-MKT')
        a=run_backtest(req,demo_history());b=run_backtest(req,demo_history())
        self.assertEqual(a,b)
        restored={t:pd.DataFrame(rows).set_index('date') for t,rows in a['observations'].items()}
        self.assertEqual(a,run_backtest(BacktestRequest(**a['settings']),restored))
        s=a['runs']['strategy']['summary']
        self.assertAlmostEqual(s['cagr'], (s['ending_value']/10000)**(365.25/730)-1)
        self.assertIn('invented',a['warnings'][0])

    def test_provider_contract_inclusive_end_adjustments_and_no_fill(self):
        with patch('yfinance.Ticker') as ticker:
            ticker.return_value.history.return_value=prices()['AAA'].rename(columns={'open':'Open','close':'Close'})
            result=fetch_backtest_history(request())
            kwargs=ticker.return_value.history.call_args.kwargs
            self.assertEqual(kwargs['end'],'2024-01-10')
            self.assertTrue(kwargs['auto_adjust']);self.assertTrue(kwargs['keepna']);self.assertFalse(kwargs['repair'])
            self.assertIn('open',result['AAA'])

    def test_endpoint_demo_offline_and_market_identity_check(self):
        client=TestClient(app);market_cache.clear()
        req=dict(source='demo',start='2024-01-02',end='2024-02-01',assets=[{'ticker':'DEMO-A','weight':100}],benchmark='DEMO-MKT')
        with patch('terminal_api.instrument',side_effect=AssertionError('No network for demo')),patch('terminal_api.fetch_backtest_history',side_effect=AssertionError('No network')):
            response=client.post('/api/backtest',json=req)
            self.assertEqual(response.status_code,200,response.text)
            self.assertIsNone(response.json()['market_data_fetched_at'])
        with patch('terminal_api.instrument',return_value={'ticker':'AAA','currency':'USD'}) as identity,patch('terminal_api.fetch_backtest_history',return_value=prices()) as fetch:
            response=client.post('/api/backtest',json=request().model_dump(mode='json'))
            self.assertEqual(response.status_code,200,response.text)
            self.assertIsNotNone(response.json()['market_data_fetched_at'])
            self.assertEqual(identity.call_count,1);self.assertEqual(fetch.call_count,1)
        self.assertEqual(client.post('/api/backtest',json={**req,'window':0}).status_code,422)
        market_cache.clear()

    def test_save_load_partial_draft_and_older_client_preservation(self):
        with TemporaryDirectory() as tmp:
            store=PortfolioStore(Path(tmp)/'portfolios.sqlite3')
            state={'view':'backtesting','backtest':{'assets':[{'ticker':'AAA','weight':''}],'hypothesis':'Keep this research','start':''}}
            identifier=uuid4()
            saved=store.save(SavePortfolio(id=identifier,name='Backtest',revision=0,state=state))
            self.assertEqual(saved['state']['backtest']['assets'][0]['weight'],'')
            self.assertEqual(store.get(identifier)['state']['backtest']['hypothesis'],'Keep this research')
            old=store.save(SavePortfolio(id=identifier,name='Backtest renamed',revision=1,state={'cash':'100'}))
            self.assertEqual(old['state']['backtest'],saved['state']['backtest'])
            self.assertIn('options',old['state']);self.assertIn('analytics',old['state'])


if __name__=='__main__':
    unittest.main()
