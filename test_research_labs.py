"""Independent IV recovery, calendar/accounting checks, and persistence boundaries."""
from copy import deepcopy
from datetime import date
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from pydantic import ValidationError
from crypto_portfolio import CryptoRequest, crypto_analysis, demo_crypto, fetch_crypto
from options_pricing import bsm
from portfolio_store import PortfolioStore, SavePortfolio, WorkspaceState
from tracker import PortfolioError
from volatility_surface import SurfaceRequest, build_surface, demo_chains
import terminal_api


class SurfaceTests(unittest.TestCase):
    def test_inverts_known_smile_and_retains_missing_cells(self):
        r=build_surface(SurfaceRequest(),demo_chains())
        self.assertEqual(r['included'],13)
        self.assertEqual(r['excluded'],17)
        for p in r['points']:
            self.assertAlmostEqual(p['iv_percent'],p['iv'],places=7)
        self.assertFalse(any(p['strike']==80 and p['expiration']=='2025-02-01' for p in r['points']))

    def test_call_put_parity_same_iv_under_continuous_yield(self):
        chain=demo_chains()[1]
        years=(date.fromisoformat(chain['expiration'])-date(2025,1,1)).days/365
        for p in chain['contracts']:
            premium=bsm(p['kind'],100,p['strike'],years,.4,-.01,.025)
            p.update(bid=premium*.99,ask=premium*1.01)
        for kind in ('call','put'):
            r=build_surface(SurfaceRequest(kind=kind,rate=-1,dividend_yield=2.5),[chain])
            self.assertEqual(len(r['points']),5)
            for p in r['points']:self.assertAlmostEqual(p['iv_percent'],40,places=7)

    def test_invalid_price_bounds_are_not_coerced(self):
        chains=demo_chains()[1:2]
        row=next(p for p in chains[0]['contracts'] if p['kind']=='call' and p['strike']==100)
        row.update(bid=101,ask=102)
        r=build_surface(SurfaceRequest(),chains)
        rejected=next(p for p in r['audit'] if p['strike']==100 and p['kind']=='call')
        self.assertIn('bounds',rejected['reason']);self.assertIsNone(rejected['iv_percent'])

    def test_filters_crossed_unknown_deliverable_and_interest(self):
        for change,needle in [({'ask':0},'crossed'),({'multiplier':None},'contract size'),({'open_interest':None},'interest')]:
            chains=demo_chains()[1:2]
            row=next(p for p in chains[0]['contracts'] if p['kind']=='call' and p['strike']==100)
            row.update(change)
            result=build_surface(SurfaceRequest(min_open_interest=1),chains)
            rejected=next(p for p in result['audit'] if p['strike']==100 and p['kind']=='call')
            self.assertIn(needle,rejected['reason'])

    def test_duplicate_or_mixed_underlying_rejected(self):
        for kind in ('duplicate','symbol','currency'):
            chains=demo_chains()
            if kind=='duplicate':chains[0]['contracts'].append(deepcopy(chains[0]['contracts'][0]))
            if kind=='symbol':chains[0]['symbol']='OTHER'
            if kind=='currency':chains[0]['currency']='EUR'
            with self.assertRaises(PortfolioError):build_surface(SurfaceRequest(),chains)

    def test_no_quote_timestamp_inferred_from_last_trade(self):
        chains=demo_chains()
        chains[1]['contracts'][2]['last_trade']='2020-01-01'
        r=build_surface(SurfaceRequest(),chains)
        self.assertTrue(any('not bid/ask timestamps' in n for n in r['notes']))

    def test_endpoint_offline_and_bounded_market_selection(self):
        client=TestClient(terminal_api.app)
        with patch('terminal_api.cached_chain',side_effect=AssertionError('network')):
            self.assertEqual(client.post('/api/volatility',json={}).status_code,200)
            self.assertEqual(client.post('/api/volatility',json={'source':'market','symbol':'AAPL'}).status_code,400)
        with self.assertRaises(ValidationError):SurfaceRequest(max_spread_percent=float('nan'))


class CryptoTests(unittest.TestCase):
    def request(self,**changes):
        return CryptoRequest(**dict(source='demo',holdings=[{'ticker':'DEMO-BTC','quantity':2,'avg_cost':9}],
                                   benchmark='DEMO-ETH',cash=10,start='2024-01-05',end='2024-01-08',**changes))

    def history(self):
        idx=pd.date_range('2024-01-05','2024-01-08')
        return {'DEMO-BTC':pd.Series([10,12,9,11],index=idx),'DEMO-ETH':pd.Series([4,5,6,5],index=idx)}

    def test_cash_cost_pnl_benchmark_and_weekend_accounting(self):
        r=crypto_analysis(self.request(),self.history())
        self.assertEqual([d['value'] for d in r['daily']],[30,34,28,32])
        self.assertEqual(r['summary']['period_pnl'],2)
        self.assertEqual(r['holdings'][0]['unrealized_pnl'],4)
        self.assertAlmostEqual(r['summary']['max_drawdown'],28/34-1)
        self.assertEqual(r['daily'][-1]['benchmark'],37.5)
        self.assertEqual(len(r['daily']),4)
        self.assertIsNone(r['summary']['cagr'])

    def test_volatility_and_sharpe_use_365_sample_days(self):
        r=crypto_analysis(self.request(),self.history())
        daily=np.array([34/30-1,28/34-1,32/28-1])
        self.assertAlmostEqual(r['summary']['annual_volatility'],daily.std(ddof=1)*math.sqrt(365))
        self.assertAlmostEqual(r['summary']['sharpe'],daily.mean()/daily.std(ddof=1)*math.sqrt(365))

    def test_missing_weekend_or_duplicate_is_an_error(self):
        for kind in ('missing','duplicate','nan','zero'):
            h=self.history()
            if kind=='missing':h['DEMO-BTC']=h['DEMO-BTC'].drop(pd.Timestamp('2024-01-06'))
            elif kind=='duplicate':h['DEMO-BTC']=pd.concat([h['DEMO-BTC'],h['DEMO-BTC'].iloc[:1]])
            else:h['DEMO-BTC'].iloc[1]=np.nan if kind=='nan' else 0
            with self.assertRaises(PortfolioError):crypto_analysis(self.request(),h)

    def test_absent_cost_does_not_become_zero_cost(self):
        request=self.request().model_copy(update={'holdings':[self.request().holdings[0].model_copy(update={'avg_cost':None})]})
        r=crypto_analysis(request,self.history())
        self.assertIsNone(r['holdings'][0]['unrealized_pnl'])
        self.assertEqual(r['summary']['period_pnl'],2)

    def test_flat_series_has_no_sharpe_and_two_closes_no_sample_vol(self):
        h={k:s*0+10 for k,s in self.history().items()}
        self.assertIsNone(crypto_analysis(self.request(),h)['summary']['sharpe'])
        r=self.request().model_copy(update={'end':date(2024,1,6)})
        self.assertIsNone(crypto_analysis(r,h)['summary']['annual_volatility'])

    def test_exact_replay(self):
        r=crypto_analysis(self.request(),self.history())
        h={k:pd.DataFrame(rows).set_index('date')['close'] for k,rows in r['observations'].items()}
        self.assertEqual(r,crypto_analysis(CryptoRequest(**r['settings']),h))

    def test_provider_verifies_type_and_utc_download(self):
        fake=MagicMock();fake.get_info.return_value={'symbol':'BTC-USD','quoteType':'CRYPTOCURRENCY','currency':'USD'}
        fake.history.return_value=pd.DataFrame({'Close':[10,11,12,13]},index=pd.date_range('2024-01-05',periods=4,tz='UTC'))
        r=self.request().model_copy(update={'source':'market','benchmark':'BTC-USD','holdings':[self.request().holdings[0].model_copy(update={'ticker':'BTC-USD'})]})
        with patch('crypto_portfolio.yf.Ticker',return_value=fake):
            history,identities=fetch_crypto(r)
            self.assertEqual(len(history),1);self.assertEqual(identities[0]['currency'],'USD')
            self.assertEqual(fake.history.call_args.kwargs['end'],'2024-01-09')
            self.assertFalse(fake.history.call_args.kwargs['auto_adjust'])
            fake.get_info.return_value['quoteType']='EQUITY'
            with self.assertRaises(PortfolioError):fetch_crypto(r)

    def test_dates_duplicates_and_nonfinite_rejected(self):
        body=self.request().model_dump()
        for patch_value in ({'end':date.today()},{'cash':float('inf')},{'holdings':body['holdings']*2}):
            with self.assertRaises(ValidationError):CryptoRequest(**{**body,**patch_value})

    def test_offline_endpoint(self):
        with patch('terminal_api.fetch_crypto',side_effect=AssertionError('network')):
            response=TestClient(terminal_api.app).post('/api/crypto',json=self.request().model_dump(mode='json'))
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['summary']['annualization'],365)


class ResearchStorageTests(unittest.TestCase):
    def test_new_tools_roundtrip_and_old_clients_cannot_erase_them(self):
        with TemporaryDirectory() as tmp:
            store=PortfolioStore(Path(tmp)/'portfolio.sqlite3')
            state=WorkspaceState().model_dump()
            state['crypto']['holdings'][0].update(ticker='BTC-USD',quantity='')
            state['volatility'].update(source='market',symbol='AAPL',rate='4.75')
            body=dict(id=uuid4(),name='Research',revision=0,state=state)
            saved=store.save(SavePortfolio(**body))
            self.assertEqual(saved['state']['crypto'],state['crypto'])
            older={k:v for k,v in state.items() if k not in ('crypto','volatility')}
            again=store.save(SavePortfolio(**{**body,'revision':saved['revision'],'state':older}))
            for key in ('crypto','volatility'):self.assertEqual(again['state'][key],state[key])


if __name__=='__main__':unittest.main()
