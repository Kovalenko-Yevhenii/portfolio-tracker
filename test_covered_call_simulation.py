"""Independent accounting identities and timing tests for synthetic covered calls."""
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest.mock import patch
import unittest
import math
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from pydantic import ValidationError

from covered_call_simulation import CoveredCallRequest, run_covered_simulation, simulate_covered, prepare_covered_history, demo_covered_history, fetch_covered_history
from option_history import HistoricalContract, HistoricalQuote
from options_pricing import bsm
from portfolio_store import PortfolioStore, SavePortfolio
from terminal_api import app, market_cache
from tracker import PortfolioError


def request(**changes):
    return CoveredCallRequest(**{**dict(ticker='AAA',start='2024-01-04',end='2024-01-05',capital=25000,
        tenor_sessions=2,otm_percent=0,strike_increment=1,stock_fee_bps=0,stock_slippage_bps=0,option_fee=0,option_half_spread_percent=0),**changes})


def history():
    dates=pd.bdate_range('2024-01-02','2024-01-19')
    return pd.DataFrame({'open':100.,'close':100.,'distribution':0.,'split':0.},index=dates)


class CoveredCallTests(unittest.TestCase):
    def test_premium_is_offset_by_liability_and_final_cash_reconciles(self):
        r=run_covered_simulation(request(),history());run=r['covered_call']
        premium=bsm('call',100,100,1.5/252,.25)*100
        liability=bsm('call',100,100,1/252,.25)*100
        self.assertAlmostEqual(run['daily'][0]['value'],25000+premium-liability)
        self.assertAlmostEqual(run['summary']['ending_value'],25000+premium)
        self.assertEqual(run['cycles'][0]['status'],'EXPIRED')  # At strike: not assigned.
        self.assertEqual(run['summary']['ending_shares'],100)
        self.assertAlmostEqual(run['summary']['ending_cash'],15000+premium)
        self.assertEqual(r['stock_only']['summary']['ending_value'],25000)
        self.assertAlmostEqual(25000+sum(e['cash_change'] for e in run['events']),run['summary']['ending_cash'])

    def test_physical_assignment_no_double_intrinsic_debit(self):
        data=history();data.loc['2024-01-05','close']=120
        r=run_covered_simulation(request(),data);run=r['covered_call'];c=run['cycles'][0]
        self.assertEqual(c['status'],'ASSIGNED')
        self.assertEqual(c['exit_value'],2000)
        self.assertAlmostEqual(run['summary']['ending_value'],25000+c['premium_received'])
        self.assertEqual(run['summary']['ending_shares'],0)
        self.assertEqual(run['summary']['ending_liability'],0)
        assignment=next(e for e in run['events'] if e['event']=='ASSIGN')
        self.assertEqual(assignment['cash_change'],10000)
        self.assertAlmostEqual(c['option_pnl'],c['premium_received']-2000)
        self.assertEqual(r['stock_only']['summary']['ending_value'],27000)

    def test_assignment_rebuys_fixed_quantity_next_open_and_uses_prior_close_strike(self):
        data=history();data.loc['2024-01-05','close']=120;data.loc['2024-01-08','open']=130
        r=run_covered_simulation(request(end='2024-01-09'),data)['covered_call']
        purchases=[e for e in r['events'] if e['event']=='BUY_STOCK']
        self.assertEqual([e['date'] for e in purchases],['2024-01-04','2024-01-08'])
        self.assertEqual(purchases[1]['cash_change'],-13000)
        self.assertEqual(r['cycles'][1]['strike'],120)
        self.assertEqual(r['cycles'][1]['signal_date'],'2024-01-05')
        self.assertTrue(all(c['contracts']==1 for c in r['cycles']))

    def test_insufficient_repurchase_cash_waits_without_borrowing(self):
        data=history();data.loc['2024-01-05','close']=120;data.loc['2024-01-08':,'open']=1000
        run=run_covered_simulation(request(end='2024-01-09'),data)['covered_call']
        self.assertEqual(run['summary']['ending_shares'],0)
        self.assertEqual(run['summary']['skipped_actions'],2)
        self.assertTrue(all(d['cash']>=0 for d in run['daily']))

    def test_distributions_entitlement_and_pricing_yield_are_separate(self):
        data=history();data.loc['2024-01-04','distribution']=3;data.loc['2024-01-05','distribution']=1
        r=run_covered_simulation(request(dividend_yield_percent=2),data)
        self.assertEqual(r['covered_call']['summary']['distributions'],100)
        self.assertEqual(r['stock_only']['summary']['distributions'],100)
        self.assertEqual(r['stock_only']['summary']['ending_value'],25100)
        premium=bsm('call',100,100,1.5/252,.25,0,.02)*100
        self.assertAlmostEqual(r['covered_call']['summary']['ending_value'],25100+premium)

    def test_costs_stock_option_assignment_applied_once(self):
        data=history();data.loc['2024-01-05','close']=120
        req=request(stock_fee_bps=10,stock_slippage_bps=100,option_fee=2,option_half_spread_percent=10,assignment_fee=3)
        run=run_covered_simulation(req,data)['covered_call']
        p=bsm('call',100,100,1.5/252,.25)*100*.9
        expected=25000-10100-10.1+p-2+10000-3
        self.assertAlmostEqual(run['summary']['ending_value'],expected)
        self.assertAlmostEqual(run['summary']['fees'],15.1)
        self.assertAlmostEqual(run['summary']['slippage_cost'],100+bsm('call',100,100,1.5/252,.25)*100*.1)

    def test_early_roll_buyback_then_replacement_on_following_open(self):
        req=request(end='2024-01-10',tenor_sessions=4,roll_before=1,option_fee=.5,option_half_spread_percent=10)
        run=run_covered_simulation(req,history())['covered_call'];c=run['cycles'][0]
        self.assertEqual(c['status'],'ROLLED');self.assertEqual(c['exit_date'],'2024-01-08')
        self.assertEqual(run['cycles'][1]['entry_date'],'2024-01-09')
        ask=bsm('call',100,100,1/252,.25)*1.1
        self.assertAlmostEqual(c['exit_value'],ask*100)
        self.assertAlmostEqual(c['option_pnl'],c['premium_received']-.5-ask*100-.5)
        self.assertEqual(run['summary']['rolls'],1)

    def test_unfunded_roll_remains_covered_and_later_expires(self):
        data=history();data.loc['2024-01-08','close']=200
        run=run_covered_simulation(request(capital=10000,end='2024-01-09',tenor_sessions=4,roll_before=1),data)['covered_call']
        self.assertEqual(run['summary']['rolls'],0)
        self.assertIn('SKIP_ROLL',[e['event'] for e in run['events']])
        self.assertEqual(run['cycles'][0]['status'],'EXPIRED')
        self.assertTrue(all(d['cash']>=0 for d in run['daily']))

    def test_final_open_call_is_marked_not_force_closed(self):
        req=request(tenor_sessions=20)
        r=run_covered_simulation(req,history());run=r['covered_call'];c=run['cycles'][0]
        self.assertEqual(c['status'],'OPEN');self.assertIsNone(c['option_pnl']);self.assertIsNone(c['expiry_date'])
        self.assertGreater(run['summary']['ending_liability'],0)
        self.assertAlmostEqual(run['summary']['ending_liability'],100*bsm('call',100,100,18/252,.25))
        self.assertAlmostEqual(run['summary']['ending_value'],run['summary']['ending_cash']+10000-run['summary']['ending_liability'])

    def test_trailing_volatility_uses_prior_returns_and_is_fixed_per_call(self):
        data=history();data.loc['2024-01-02','close']=90;data.loc['2024-01-03','close']=100
        req=request(start='2024-01-05',end='2024-01-09',tenor_sessions=10,volatility_mode='trailing',volatility_window=2,volatility_premium=3)
        run=run_covered_simulation(req,data)['covered_call'];c=run['cycles'][0]
        expected=np.std([math.log(100/90),math.log(100/100)],ddof=1)*math.sqrt(252)*100+3
        self.assertAlmostEqual(c['assumed_iv'],expected)
        changed=data.copy();changed.loc['2024-01-05','close']=150
        later=run_covered_simulation(req,changed)['covered_call']
        self.assertEqual(c['assumed_iv'],later['cycles'][0]['assumed_iv'])
        self.assertEqual(c['fill_entry'],later['cycles'][0]['fill_entry'])
        mark=100*bsm('call',100,c['strike'],7/252,expected/100)
        self.assertAlmostEqual(run['daily'][-1]['call_liability'],mark)

    def test_future_prices_do_not_change_past_entries_or_account_values(self):
        req=request(end='2024-01-10',tenor_sessions=3);data=history()
        before=run_covered_simulation(req,data)['covered_call']
        data.loc['2024-01-10',['open','close']]=[180,170]
        after=run_covered_simulation(req,data)['covered_call']
        self.assertEqual(before['daily'][:-1],after['daily'][:-1])
        self.assertEqual([e for e in before['events'] if e['date']<'2024-01-10'],[e for e in after['events'] if e['date']<'2024-01-10'])

    def test_contract_size_scales_stock_premiums_liabilities_and_fees_together(self):
        kwargs=dict(tenor_sessions=20,option_fee=.65,stock_fee_bps=1,option_half_spread_percent=5)
        a=run_covered_simulation(request(**kwargs),history())['covered_call']
        b=run_covered_simulation(request(contracts=2,capital=50000,**kwargs),history())['covered_call']
        for key in ['ending_value','premium_received','fees','ending_liability','ending_shares','calls_written']:
            self.assertAlmostEqual(b['summary'][key],2*a['summary'][key])
        self.assertAlmostEqual(b['summary']['total_return'],a['summary']['total_return'])

    def test_zero_premium_not_written_and_initial_funding_required(self):
        run=run_covered_simulation(request(volatility_percent=0),history())['covered_call']
        self.assertEqual(run['cycles'],[]);self.assertEqual(run['summary']['ending_value'],25000)
        with self.assertRaisesRegex(PortfolioError,'Starting capital'):run_covered_simulation(request(capital=9999),history())

    def test_sensitivity_base_matches_and_unfunded_cells_are_explicit(self):
        req=request(capital=10015,stock_fee_bps=10)
        r=run_covered_simulation(req,history())
        self.assertEqual(r['sensitivity'][1]['values'][1]['ending_value'],r['covered_call']['summary']['ending_value'])
        self.assertIsNotNone(r['sensitivity'][1]['values'][2]['error'])
        self.assertIsNone(r['sensitivity'][1]['values'][2]['ending_value'])
        self.assertNotEqual(r['sensitivity'][0]['values'][1]['total_return'],r['sensitivity'][2]['values'][1]['total_return'])

    def test_bad_inputs_missing_prices_and_split_ranges_rejected(self):
        for changes in [dict(contracts=1.5),dict(capital=float('nan')),dict(tenor_sessions=1),dict(roll_before=1),dict(strike_increment=0),dict(volatility_percent=-1),dict(end='2099-01-01')]:
            with self.assertRaises(ValidationError):request(**changes)
        for key,value,message in [('open',np.nan,'Missing or invalid'),('distribution',np.nan,'corporate-action'),('split',2,'stock split')]:
            data=history();data.loc['2024-01-05',key]=value
            with self.assertRaisesRegex(PortfolioError,message):run_covered_simulation(request(),data)

    def test_snapshot_replay_is_exact_offline(self):
        req=request(source='demo',ticker='DEMO-CC',start='2024-01-02',end='2024-03-28',tenor_sessions=20)
        a=run_covered_simulation(req,demo_covered_history())
        b=run_covered_simulation(CoveredCallRequest(**a['settings']),pd.DataFrame(a['observations']).set_index('date'))
        self.assertEqual(a,b)
        self.assertEqual(a['result_type'],'MODELED_OPTIONS_SIMULATION')

    def test_provider_requests_price_history_and_actions_not_total_return(self):
        frame=history().rename(columns={'open':'Open','close':'Close','distribution':'Dividends','split':'Stock Splits'})
        with patch('yfinance.Ticker') as ticker:
            ticker.return_value.history.return_value=frame
            result=fetch_covered_history(request())
            kwargs=ticker.return_value.history.call_args.kwargs
            self.assertFalse(kwargs['auto_adjust']);self.assertTrue(kwargs['actions']);self.assertTrue(kwargs['keepna'])
            self.assertEqual(kwargs['end'],'2024-01-06')
            self.assertEqual(list(result.columns),['open','close','distribution','split'])

    def test_offline_api_and_market_api_verify_stock_only(self):
        client=TestClient(app);market_cache.clear()
        req=request(source='demo',ticker='DEMO-CC')
        with patch('terminal_api.instrument',side_effect=AssertionError('No market call')),patch('terminal_api.fetch_covered_history',side_effect=AssertionError('No market call')):
            response=client.post('/api/simulation/covered-call',json=req.model_dump(mode='json'))
            self.assertEqual(response.status_code,200,response.text)
            self.assertIsNone(response.json()['market_data_fetched_at'])
        with patch('terminal_api.instrument',return_value={'ticker':'AAA','currency':'USD'}) as identity,patch('terminal_api.fetch_covered_history',return_value=history()) as fetch:
            response=client.post('/api/simulation/covered-call',json=request().model_dump(mode='json'))
            self.assertEqual(response.status_code,200,response.text);self.assertEqual(identity.call_count,1);self.assertEqual(fetch.call_count,1)
        bad=request().model_dump(mode='json');bad['contracts']=0
        self.assertEqual(client.post('/api/simulation/covered-call',json=bad).status_code,422)
        market_cache.clear()

    def test_saved_partial_inputs_and_old_client_preserve_simulator(self):
        with TemporaryDirectory() as tmp:
            store=PortfolioStore(Path(tmp)/'test.sqlite3');identifier=uuid4()
            saved=store.save(SavePortfolio(id=identifier,name='Research',revision=0,state={'backtest_tool':'covered_call','covered_call':{'ticker':'AAA','volatility_percent':'','hypothesis':'Keep this'},'backtest':{'window':'77'}}))
            self.assertEqual(store.get(identifier)['state']['covered_call']['volatility_percent'],'')
            updated=store.save(SavePortfolio(id=identifier,name='Research 2',revision=1,state={'cash':'1'}))
            self.assertEqual(updated['state']['covered_call'],saved['state']['covered_call'])
            self.assertEqual(updated['state']['backtest_tool'],'covered_call')
            self.assertEqual(updated['state']['backtest']['window'],'77')


class HistoricalProviderContractTests(unittest.TestCase):
    def quote(self,**changes):
        contract=HistoricalContract('EXAMPLE','AAA',date(2024,2,16),100,'call','american',100,True)
        t=datetime(2024,1,4,15,tzinfo=timezone.utc)
        return HistoricalQuote(**{**dict(contract=contract,observed_at=t,available_at=t,bid=1,ask=1.2,provider='test fixture'),**changes})

    def test_observed_quotes_reject_future_unavailable_and_stale_data(self):
        q=self.quote();t=q.observed_at
        self.assertIs(q.validate_for(t+timedelta(seconds=5),10),q)
        for candidate,now in [(self.quote(available_at=t+timedelta(seconds=1)),t),(q,t-timedelta(seconds=1)),(q,t+timedelta(seconds=11))]:
            with self.assertRaises(ValueError):candidate.validate_for(now,10)

    def test_missing_or_crossed_prices_cannot_silently_become_model_quotes(self):
        for changes in [dict(bid=2),dict(ask=float('nan')),dict(provider=''),dict(observed_at=datetime(2024,1,4,15))]:
            q=self.quote(**changes)
            with self.assertRaises(ValueError):q.validate_for(datetime(2024,1,4,15,tzinfo=timezone.utc),10)

    def test_contract_metadata_is_explicit_and_valid(self):
        with self.assertRaises(ValueError):HistoricalContract('EXAMPLE','AAA',date(2024,2,16),-100,'call','american',100,True)
        with self.assertRaises(ValueError):HistoricalContract('EXAMPLE','AAA',date(2024,2,16),100,'call','american',1.5,True)


if __name__=='__main__':unittest.main()
