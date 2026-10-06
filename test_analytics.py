"""Independently derived valuations, rejection paths, and persistence regressions."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import json
import unittest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from analytics_valuation import ValuationRequest, analyze_valuation
from portfolio_store import PortfolioStore, SavePortfolio
from terminal_api import app
from tracker import PortfolioError


def sample():
    return dict(company='Example',valuation_date='2026-09-30',currency='USD',units='millions',
                shares='10',current_price='50',cash='50',nonoperating='30',debt='200',preferred='10',minority='20',
                cases=[dict(name='Base',wacc='10',growth='0',exit_multiple='8',years=[
                    dict(ebit='100',tax_rate='20',depreciation='10',capex='10',change_nwc='0')])])


def analyze(body):
    return analyze_valuation(ValuationRequest(**body))


def comps():
    return dict(period='FY2027',revenue='500',ebitda='100',net_income='40',peers=[
        dict(name='A',enterprise_value='1000',equity_value='900',revenue='500',ebitda='100',net_income='50'),
        dict(name='B',enterprise_value='2000',equity_value='1800',revenue='500',ebitda='100',net_income='50')])


class ValuationTests(unittest.TestCase):
    def test_constant_cashflow_perpetuity_and_full_equity_bridge(self):
        body=sample(); r=analyze(body); d=r['dcf'][0]
        self.assertAlmostEqual(d['enterprise_value'],800)
        self.assertAlmostEqual(d['equity_value'],650)
        self.assertEqual(d['price'],65)
        self.assertEqual(d['upside_percent'],30)
        self.assertEqual(d['forecast'][0]['fcff'],80)
        self.assertEqual(r['bridge']['adjustment'],-150)
        body['cases'][0]['years']*=5
        self.assertAlmostEqual(analyze(body)['dcf'][0]['enterprise_value'],800)

    def test_terminal_growth_is_applied_to_next_year_and_discounted(self):
        body=sample();body['cases'][0]['growth']='2';d=analyze(body)['dcf'][0]
        self.assertEqual(d['terminal_value'],1020)
        self.assertEqual(d['enterprise_value'],1000)
        self.assertEqual(d['price'],85)

    def test_exit_multiple_uses_ebitda_at_horizon_and_year_end_discount(self):
        body=sample();body['terminal_method']='multiple';d=analyze(body)['dcf'][0]
        self.assertEqual(d['terminal_value'],880)
        self.assertAlmostEqual(d['enterprise_value'],960/1.1)
        self.assertAlmostEqual(d['price'],(960/1.1-150)/10)

    def test_working_capital_release_and_loss_tax_toggle(self):
        body=sample();first=deepcopy(body['cases'][0]['years'][0]);first.update(ebit='-100',change_nwc='-10')
        body['cases'][0]['years'].insert(0,first)
        self.assertEqual(analyze(body)['dcf'][0]['forecast'][0]['fcff'],-90)
        body['tax_benefit']=True
        self.assertEqual(analyze(body)['dcf'][0]['forecast'][0]['fcff'],-70)

    def test_units_cancel_only_when_financials_and_shares_scale_together(self):
        body=sample();body['units']='units'
        for key in ['shares','cash','nonoperating','debt','preferred','minority']:
            body[key]=str(Decimal(body[key])*1_000_000)
        for y in body['cases'][0]['years']:
            for key in ['ebit','depreciation','capex','change_nwc']:
                y[key]=str(Decimal(y[key])*1_000_000)
        self.assertEqual(analyze(body)['dcf'][0]['price'],65)

    def test_both_methods_cases_and_sensitivity_center(self):
        body=sample();body['terminal_method']='both'
        for name,ebit in [('Bear','80'),('Bull','120')]:
            case=deepcopy(body['cases'][0]);case['name']=name;case['years'][0]['ebit']=ebit;body['cases'].append(case)
        r=analyze(body);self.assertEqual(len(r['dcf']),6);self.assertEqual(len(r['ranges']),2)
        self.assertLess(r['ranges'][0]['low'],r['ranges'][0]['mid']);self.assertGreater(r['ranges'][0]['high'],r['ranges'][0]['mid'])
        for sensitivity in r['sensitivity']:
            base=next(d for d in r['dcf'] if d['case']=='Base' and d['method']==sensitivity['method'])
            self.assertEqual(sensitivity['rows'][2]['values'][2],base['price'])
        self.assertLess(r['sensitivity'][0]['rows'][3]['values'][2],r['sensitivity'][0]['rows'][2]['values'][2])
        self.assertGreater(r['sensitivity'][0]['rows'][2]['values'][3],r['sensitivity'][0]['rows'][2]['values'][2])

    def test_invalid_sensitivity_cells_are_missing_not_zero(self):
        body=sample();body['cases'][0].update(wacc='1',growth='.8')
        r=analyze(body);self.assertIsNone(r['sensitivity'][0]['rows'][0]['values'][0])
        self.assertIsNone(r['sensitivity'][0]['rows'][2]['values'][4])
        self.assertIsNotNone(r['sensitivity'][0]['rows'][2]['values'][2])

    def test_comps_quartiles_and_no_double_debt_subtraction_for_pe(self):
        body=sample();body.update(cases=[],comps=comps());r=analyze(body)
        ev,rev,pe=r['comps'];self.assertEqual(ev['multiples'],[12.5,15,17.5])
        self.assertEqual(ev['mid'],135);self.assertEqual(rev['mid'],135)
        self.assertEqual(pe['multiples'],[22.5,27,31.5]);self.assertEqual(pe['mid'],108)

    def test_comps_excludes_invalid_metrics_without_excluding_valid_other_metrics(self):
        body=sample();body['comps']=comps();body['comps']['peers'].append(dict(name='Loss',enterprise_value='3000',revenue='500',ebitda='-1'))
        r=analyze(body);self.assertEqual(r['comps'][0]['count'],2);self.assertEqual(r['comps'][1]['count'],3)
        bad=next(p for p in r['peer_audit'] if p['peer']=='Loss' and p['method']=='EV / EBITDA')
        self.assertIsNone(bad['multiple']);self.assertIn('Nonpositive',bad['exclusion'])

    def test_unavailable_comps_do_not_create_zero_ranges(self):
        body=sample();body.update(cases=[],comps=comps());body['comps']['peers']=body['comps']['peers'][:1]
        with self.assertRaises(PortfolioError):analyze(body)
        body['cases']=sample()['cases'];r=analyze(body)
        self.assertEqual(len(r['ranges']),1);self.assertEqual(r['comps'],[])

    def test_nonpositive_equity_is_reported_as_shortfall_not_clipped(self):
        body=sample();body['debt']='1000';r=analyze(body)
        self.assertLess(r['dcf'][0]['price'],0);self.assertTrue(any('shortfall' in w for w in r['warnings']))

    def test_rejects_invalid_terminal_assumptions_and_missing_inputs(self):
        body=sample()
        for wacc,growth in [('5','5'),('5','6')]:
            b=deepcopy(body);b['cases'][0].update(wacc=wacc,growth=growth)
            with self.assertRaises(PortfolioError):analyze(b)
        b=deepcopy(body);b['cases'][0]['years'][0]['capex']='1000'
        with self.assertRaises(PortfolioError):analyze(b)
        for change in [dict(shares='0'),dict(shares='NaN'),dict(cash=None),dict(cases=[]),dict(current_price='0')]:
            with self.assertRaises(ValidationError):ValuationRequest(**{**body,**change})
        b=deepcopy(body);b['cases'].append(deepcopy(b['cases'][0]))
        with self.assertRaises(ValidationError):ValuationRequest(**b)

    def test_api_uses_only_entered_data_and_returns_validation_errors(self):
        client=TestClient(app)
        with patch('terminal_api.fetch_price_history',side_effect=AssertionError('No market calls')):
            response=client.post('/api/analytics/valuation',json=sample())
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['dcf'][0]['price'],65)
        self.assertEqual(client.post('/api/analytics/valuation',json={**sample(),'shares':None}).status_code,422)
        body=sample();body['cases'][0]['growth']='10'
        self.assertEqual(client.post('/api/analytics/valuation',json=body).status_code,400)

    def test_incomplete_drafts_roundtrip_and_old_clients_preserve_analytics(self):
        with TemporaryDirectory() as directory:
            store=PortfolioStore(Path(directory)/'p.sqlite3');pid=uuid4()
            saved=store.save(SavePortfolio(id=pid,name='Valuation',revision=0,state={'view':'analytics','analytics':{'company':'Example','shares':'','hypothesis':'Test idea'}}))
            self.assertEqual(saved['state']['analytics']['shares'],'')
            self.assertEqual(saved['state']['view'],'analytics')
            old=store.save(SavePortfolio(id=pid,name='Renamed',revision=1,state={'cash':'10'}))
            self.assertEqual(old['state']['analytics'],saved['state']['analytics'])
            legacy=store.save(SavePortfolio(id=uuid4(),name='Old portfolio',revision=0,state={}))
            self.assertEqual(legacy['state']['analytics']['version'],1)


if __name__=='__main__':unittest.main()
