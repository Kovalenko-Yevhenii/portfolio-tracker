"""Known-answer expiration payoffs, extrema, roots, and saved-state compatibility."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import json
import sqlite3
import unittest

from fastapi.testclient import TestClient
from options_analysis import analyze_options
from portfolio_store import PortfolioStore,SavePortfolio,WorkspaceState,OptionsDraft
import terminal_api
from tracker import PortfolioError


class OptionsMathTests(unittest.TestCase):
    def calc(self, strategy='long_call', **fields):
        return analyze_options({'strategy':strategy,'strike':100,'premium':5,'contracts':1,'multiplier':100,**fields})

    def test_long_call_includes_premium_quantity_and_multiplier(self):
        r=self.calc(contracts=2,scenario_price=120)
        self.assertTrue(r['profit_unlimited']);self.assertIsNone(r['maximum_profit'])
        self.assertEqual(r['maximum_loss'],1000)
        self.assertEqual(r['break_evens'],[105])
        self.assertEqual(r['scenario_pnl'],3000)
        self.assertEqual(self.calc(contracts=2,multiplier=10,scenario_price=120)['scenario_pnl'],300)

    def test_long_put_price_floor_and_premium(self):
        r=self.calc('long_put',scenario_price=0)
        self.assertEqual(r['maximum_profit'],9500);self.assertEqual(r['maximum_loss'],500)
        self.assertFalse(r['profit_unlimited']);self.assertEqual(r['scenario_pnl'],9500)
        self.assertEqual(r['break_evens'],[95])

    def test_covered_call_matches_stock_and_never_has_naked_call_tail(self):
        r=self.calc('covered_call',premium=3,stock_entry=95,scenario_price=120)
        self.assertEqual(r['stock_quantity'],100);self.assertEqual(r['maximum_profit'],800)
        self.assertEqual(r['maximum_loss'],9200);self.assertEqual(r['break_evens'],[92])
        self.assertEqual(r['scenario_pnl'],800);self.assertFalse(r['loss_unlimited'])
        self.assertEqual(r['net_initial_debit'],9200)

    def test_protective_put_floor_and_unlimited_upside(self):
        r=self.calc('protective_put',strike=95,premium=2,stock_entry=100,scenario_price=80)
        self.assertEqual(r['maximum_loss'],700);self.assertEqual(r['scenario_pnl'],-700)
        self.assertEqual(r['break_evens'],[102]);self.assertTrue(r['profit_unlimited'])
        self.assertEqual(r['stock_quantity'],100)

    def test_four_vertical_spread_variants(self):
        cases=[('call',100,7,110,3,'Bull call spread',600,400,104),
               ('call',110,3,100,7,'Bear call spread',400,600,104),
               ('put',110,7,100,3,'Bear put spread',600,400,106),
               ('put',100,3,110,7,'Bull put spread',400,600,106)]
        for kind,lk,lp,sk,sp,name,gain,loss,be in cases:
            with self.subTest(name=name):
                r=self.calc('vertical',option_type=kind,long_strike=lk,long_premium=lp,short_strike=sk,short_premium=sp)
                self.assertEqual((r['strategy_name'],r['maximum_profit'],r['maximum_loss']),(name,gain,loss))
                self.assertEqual(r['break_evens'],[be]);self.assertFalse(r['warnings'])
                self.assertFalse(r['profit_unlimited']);self.assertFalse(r['loss_unlimited'])

    def test_extrema_and_roots_do_not_depend_on_chart_window(self):
        full=self.calc('covered_call',stock_entry=95,premium=3)
        zoom=self.calc('covered_call',stock_entry=95,premium=3,range_min=150,range_max=160,scenario_price=0)
        for key in ['maximum_profit','maximum_loss','break_evens']:self.assertEqual(full[key],zoom[key])
        self.assertEqual(zoom['scenario_pnl'],-9200)
        self.assertTrue(all(row['pnl']==800 for row in zoom['chart']))

    def test_zero_premiums_and_break_even_plateaus(self):
        call=self.calc(premium=0)
        self.assertEqual(call['break_evens'],[])
        self.assertEqual(call['break_even_ranges'],[{'from':0.,'to':100.}])
        put=self.calc('long_put',premium=0)
        self.assertEqual(put['break_even_ranges'],[{'from':100.,'to':None}])
        spread=self.calc('vertical',long_strike=100,long_premium=10,short_strike=110,short_premium=0)
        self.assertEqual(spread['break_even_ranges'],[{'from':110.,'to':None}])

    def test_no_reachable_break_even_and_always_profitable_inputs(self):
        r=self.calc('long_put',strike=10,premium=15)
        self.assertEqual(r['break_evens'],[]);self.assertEqual(r['break_even_ranges'],[])
        self.assertEqual(r['maximum_profit'],0);self.assertEqual(r['best_case_pnl'],-500)
        self.assertTrue(r['warnings'])
        covered=self.calc('covered_call',stock_entry=10,premium=15)
        self.assertEqual(covered['maximum_loss'],0);self.assertTrue(covered['warnings'])

    def test_decimal_roots_and_each_leg_reconciles_to_total(self):
        r=self.calc(strike=100.1,premium=.2,scenario_price=100.3)
        self.assertEqual(r['break_evens'],[100.3]);self.assertEqual(r['scenario_pnl'],0)
        for strategy,extra in [('covered_call',{'stock_entry':95}),('protective_put',{'stock_entry':100}),
                               ('vertical',{'long_strike':100,'long_premium':7,'short_strike':110,'short_premium':3})]:
            for spot in [0,50,100,105,110,1000]:
                r=self.calc(strategy,scenario_price=spot,**extra)
                self.assertAlmostEqual(sum(leg['pnl'] for leg in r['legs']),r['scenario_pnl'])
                for leg in r['legs']:
                    self.assertAlmostEqual(leg['initial_cash_flow']+leg['expiration_value'],leg['pnl'])
                self.assertAlmostEqual(-sum(leg['initial_cash_flow'] for leg in r['legs']),r['net_initial_debit'])

    def test_invalid_inputs_are_rejected(self):
        for changes in [{'strike':0},{'premium':-1},{'premium':float('nan')},{'contracts':1.5},
                        {'multiplier':0},{'scenario_price':-1},{'range_min':100,'range_max':50},{'expiration':'2026-02-30'}]:
            with self.subTest(changes=changes),self.assertRaises(PortfolioError):self.calc(**changes)
        with self.assertRaises(PortfolioError):self.calc('covered_call')
        with self.assertRaises(PortfolioError):self.calc('vertical',long_strike=100,short_strike=100,long_premium=5,short_premium=3)


class OptionsAPITests(unittest.TestCase):
    def setUp(self):self.client=TestClient(terminal_api.app)

    def test_calculator_works_without_provider_calls_or_holdings(self):
        with patch('terminal_api.get_instrument',side_effect=AssertionError('No provider call')),patch('terminal_api.fetch_price_history',side_effect=AssertionError('No price call')):
            response=self.client.post('/api/options/analyze',json={'strategy':'long_call','strike':100,'premium':5,'scenario_price':120})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['scenario_pnl'],1500)
        json.dumps(response.json(),allow_nan=False)

    def test_invalid_requests_and_same_origin_policy(self):
        for body in [{'strategy':'long_call','strike':None,'premium':5},
                     {'strategy':'long_call','strike':100,'premium':5,'contracts':1.5},
                     {'strategy':'other'}]:
            self.assertIn(self.client.post('/api/options/analyze',json=body).status_code,[400,422])
        self.assertEqual(self.client.post('/api/options/analyze',json={'strategy':'long_call','strike':100,'premium':5},headers={'origin':'https://other.example'}).status_code,403)

    def test_options_save_round_trip_and_old_snapshots_remain_readable(self):
        with TemporaryDirectory() as directory:
            store=PortfolioStore(Path(directory)/'portfolios.sqlite3')
            old=WorkspaceState().model_dump();old.pop('options')
            portfolio_id=str(uuid4())
            # Seed the previous on-disk shape without any options field.
            with closing(store.connect()) as db,db:
                db.execute('INSERT INTO portfolios VALUES (?,?,?,?,?,?,?)',(portfolio_id,'Legacy','legacy',json.dumps(old,sort_keys=True),1,'2026-01-01','2026-01-01'))
            self.assertEqual(store.get(portfolio_id)['state']['options'],OptionsDraft().model_dump())
            same=SavePortfolio.model_validate({'id':portfolio_id,'name':'Legacy','revision':0,'state':old})
            self.assertEqual(store.save(same)['revision'],1)
            state=store.get(portfolio_id)['state'];state['view']='options';state['options'].update(strategy='vertical',long_strike='100.25',short_strike='110',long_premium='',contracts='2')
            with patch('terminal_api.portfolio_store',store):
                saved=self.client.post('/api/portfolios/save',json={'id':portfolio_id,'name':'Legacy','revision':1,'state':state})
                self.assertEqual(saved.status_code,200,saved.text)
                self.assertEqual(self.client.get('/api/portfolios/'+portfolio_id).json()['state'],state)
            # A still-open old client cannot silently discard the new fields.
            old['cash']='200'
            updated=store.save(SavePortfolio.model_validate({'id':portfolio_id,'name':'Legacy','revision':2,'state':old}))
            self.assertEqual(updated['state']['options'],state['options'])
            self.assertEqual(updated['state']['cash'],'200')


if __name__=='__main__':unittest.main()
