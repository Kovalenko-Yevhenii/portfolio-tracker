"""Known-answer checks for exposure and funding; no market-data dependency."""
from datetime import date,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import unittest
from fastapi.testclient import TestClient
from options_pricing import ScenarioRequest,analyze_scenario
from portfolio_store import PortfolioStore,SavePortfolio,StoreError
from terminal_api import app
from tracker import PortfolioError


def request(**changes):
    data=dict(mode='dated',as_of=date(2026,1,1),spot=100,scenario_price=120,
              legs=[dict(kind='call',side='buy',quantity=1,strike=100,premium=5,iv=20,expiration=date(2027,1,1))])
    data.update(changes)
    return ScenarioRequest(**data)


class LeverageTests(unittest.TestCase):
    def test_quantity_doubles_exposure_but_not_unfunded_leverage(self):
        req=request();one=analyze_scenario(req)
        two=analyze_scenario(req.model_copy(update={'legs':[req.legs[0].model_copy(update={'quantity':2.})]}))
        self.assertAlmostEqual(one['leverage']['effective_leverage'],one['greeks']['delta']*100/500)
        self.assertEqual(one['leverage']['gross_notional'],10000)
        self.assertAlmostEqual(two['leverage']['net_delta_notional'],2*one['leverage']['net_delta_notional'])
        self.assertAlmostEqual(two['leverage']['effective_leverage'],one['leverage']['effective_leverage'])
        self.assertEqual(two['scenario_pnl'],2*one['scenario_pnl'])

    def test_put_has_negative_effective_leverage_and_offsets_keep_gross_exposure(self):
        req=request();put=req.legs[0].model_copy(update={'kind':'put'})
        r=analyze_scenario(req.model_copy(update={'legs':[put]}))
        self.assertLess(r['leverage']['effective_leverage'],0)
        combo=analyze_scenario(req.model_copy(update={'legs':[req.legs[0],put]}))
        self.assertGreater(combo['leverage']['gross_delta_notional'],abs(combo['leverage']['net_delta_notional']))
        self.assertAlmostEqual(combo['leverage']['gross_delta_notional'],10000)

    def test_credit_capital_not_inferred_from_maximum_loss(self):
        req=request();short=req.legs[0].model_copy(update={'kind':'put','side':'sell'})
        req=req.model_copy(update={'legs':[short]});r=analyze_scenario(req)
        self.assertEqual(r['capital_basis'],9500)
        self.assertIsNone(r['leverage']['capital']);self.assertIsNone(r['leverage']['effective_leverage'])
        entered=analyze_scenario(req.model_copy(update={'capital_basis':10000.}))
        self.assertEqual(entered['leverage']['capital'],10000)
        csp=analyze_scenario(req.model_copy(update={'strategy':'cash_secured_put'}))
        self.assertEqual(csp['leverage']['capital'],10000)

    def test_missing_delta_is_unavailable_and_zero_delta_is_not_unavailable(self):
        req=request(mode='expiry');r=analyze_scenario(req)
        self.assertIsNone(r['leverage']['effective_leverage']);self.assertEqual(r['leverage']['gross_notional'],10000)
        dated=request();long=dated.legs[0];short=long.model_copy(update={'side':'sell'})
        flat=analyze_scenario(dated.model_copy(update={'legs':[long,short],'capital_basis':1000.}))
        self.assertEqual(flat['leverage']['effective_leverage'],0)
        self.assertGreater(flat['leverage']['gross_delta_leverage'],0)

    def test_borrowing_changes_equity_interest_pnl_roots_and_probability(self):
        req=request();base=analyze_scenario(req)
        financed=analyze_scenario(req.model_copy(update={'financing_enabled':True,'borrowed_amount':250.,'borrowing_rate':10.}))
        self.assertEqual(financed['financing']['scenario_interest'],25)
        self.assertEqual(financed['capital_basis'],250)
        self.assertEqual(financed['scenario_pnl'],1475)
        self.assertEqual(financed['scenario_return_percent'],590)
        self.assertEqual(financed['financing']['scenario_equity'],1725)
        self.assertEqual(financed['summary']['break_evens'],[105.25])
        self.assertEqual(financed['summary']['maximum_loss'],525)
        self.assertLess(financed['probability_of_profit'],base['probability_of_profit'])
        self.assertAlmostEqual(financed['leverage']['effective_leverage'],2*base['leverage']['effective_leverage'])
        self.assertAlmostEqual(sum(l['pnl'] for l in financed['legs'])-financed['financing']['scenario_interest'],financed['scenario_pnl'])
        self.assertEqual(financed['financing']['own_capital']+financed['scenario_pnl'],financed['financing']['scenario_equity'])

    def test_zero_rate_and_zero_day_costs_do_not_charge_principal_as_loss(self):
        req=request(financing_enabled=True,borrowed_amount=250,borrowing_rate=0)
        r=analyze_scenario(req)
        self.assertEqual(r['scenario_pnl'],1500);self.assertEqual(r['summary']['maximum_loss'],500)
        self.assertEqual(r['financing']['scenario_equity'],1750)
        today=analyze_scenario(req.model_copy(update={'borrowing_rate':10.,'target_date':req.as_of}))
        self.assertEqual(today['financing']['scenario_interest'],0)

    def test_date_grid_position_values_unchanged_but_pnl_includes_elapsed_interest(self):
        req=request();base=analyze_scenario(req);funded=analyze_scenario(req.model_copy(update={'financing_enabled':True,'borrowed_amount':250.,'borrowing_rate':10.}))
        for brow,frow in zip(base['grid'],funded['grid']):
            for b,f in zip(brow['values'],frow['values']):
                days=(date.fromisoformat(f['date'])-req.as_of).days;cost=250*.1*days/365
                self.assertAlmostEqual(b['position_value'],f['position_value'])
                self.assertAlmostEqual(b['pnl']-f['pnl'],cost)
                self.assertAlmostEqual(f['equity_value'],f['position_value']-250-cost)
        for row in funded['chart']:
            self.assertAlmostEqual(row['horizon_position_value']-row['horizon_pnl'],525)
            self.assertAlmostEqual(row['start_position_value']-row['start_pnl'],500)

    def test_expiry_only_uses_explicit_term_even_without_expiration_dates(self):
        req=request(mode='expiry',financing_enabled=True,borrowed_amount=250,borrowing_rate=10,financing_days=73)
        req=req.model_copy(update={'legs':[req.legs[0].model_copy(update={'expiration':None})]})
        r=analyze_scenario(req);self.assertEqual(r['financing']['scenario_interest'],5);self.assertEqual(r['summary']['break_evens'],[105.05])
        self.assertEqual(r['scenario_pnl'],1495)
        zero=analyze_scenario(req.model_copy(update={'financing_days':0}))
        self.assertEqual(zero['financing']['scenario_interest'],0)
        with self.assertRaises(PortfolioError):analyze_scenario(req.model_copy(update={'financing_days':None}))

    def test_calendar_interest_stops_at_first_expiry_and_summary_remains_unavailable(self):
        req=request(financing_enabled=True,borrowed_amount=100,borrowing_rate=10)
        long=req.legs[0];short=long.model_copy(update={'side':'sell','expiration':date(2026,2,1),'premium':2.})
        r=analyze_scenario(req.model_copy(update={'legs':[long,short]}))
        self.assertEqual(r['horizon'],'2026-02-01');self.assertAlmostEqual(r['financing']['horizon_interest'],100*.1*31/365)
        self.assertIsNone(r['summary']);self.assertIsNone(r['probability_of_profit'])

    def test_automatic_leverage_capital_includes_stock_cost(self):
        req=request();stock=req.legs[0].model_copy(update={'kind':'stock','quantity':100.,'premium':100.})
        r=analyze_scenario(req.model_copy(update={'legs':[stock,req.legs[0]],'include_stock_cost':False}))
        self.assertEqual(r['capital_basis'],500);self.assertEqual(r['leverage']['capital'],10500)

    def test_disabled_funding_preserves_original_outputs(self):
        req=request();base=analyze_scenario(req)
        dormant=analyze_scenario(req.model_copy(update={'borrowed_amount':10000.,'borrowing_rate':90.,'financing_days':200}))
        for key in ['scenario_pnl','summary','grid','chart','capital_basis','leverage','financing']:self.assertEqual(base[key],dormant[key])

    def test_api_rejects_invalid_funding_and_reports_valid_case(self):
        client=TestClient(app);body=request(financing_enabled=True).model_dump(mode='json')
        for patch in [{'borrowed_amount':500},{'borrowed_amount':501},{'mode':'expiry','financing_days':None},{'capital_basis':300},{'include_stock_cost':False}]:
            self.assertEqual(client.post('/api/options/model',json={**body,**patch}).status_code,400)
        for patch in [{'borrowed_amount':-1},{'borrowing_rate':-1},{'financing_days':1.5}]:
            self.assertEqual(client.post('/api/options/model',json={**body,**patch}).status_code,422)
        result=client.post('/api/options/model',json={**body,'borrowed_amount':250,'borrowing_rate':10})
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()['financing']['scenario_interest'],25)
        short={**body,'legs':[{**body['legs'][0],'side':'sell'}]}
        self.assertEqual(client.post('/api/options/model',json=short).status_code,400)

    def test_funding_and_kept_scenarios_persist_and_old_client_is_blocked(self):
        with TemporaryDirectory() as directory:
            store=PortfolioStore(Path(directory)/'p.sqlite3');pid=uuid4()
            opts={'engine_version':3,'financing_enabled':True,'borrowed_amount':'250','borrowing_rate':'','financing_days':'73',
                  'scenarios':[{'id':'funded','name':'Funded call','state':{'financing_enabled':True,'borrowed_amount':'125','borrowing_rate':'8'}}]}
            saved=store.save(SavePortfolio(id=pid,name='Loan test',revision=0,state={'options':opts}))
            loaded=store.get(pid)['state']['options'];self.assertEqual(loaded['borrowing_rate'],'');self.assertEqual(loaded['scenarios'][0]['state']['borrowed_amount'],'125')
            with self.assertRaises(StoreError):store.save(SavePortfolio(id=pid,name='Old client',revision=1,state={'options':{'engine_version':2}}))
            preserved=store.save(SavePortfolio(id=pid,name='Renamed',revision=1,state={}))
            self.assertEqual(preserved['state']['options'],loaded)
            legacy=store.save(SavePortfolio(id=uuid4(),name='Version 2',revision=0,state={'options':{'engine_version':2}}))
            self.assertFalse(legacy['state']['options']['financing_enabled'])


if __name__=='__main__':unittest.main()
