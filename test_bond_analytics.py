"""Independent bond benchmarks, calendar conventions, derivatives and persistence."""
from datetime import date
from decimal import Decimal, localcontext
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from pydantic import ValidationError
from bond_analytics import BondRequest, analyze_bond, schedule, coupon_date, us_30_360
from portfolio_store import PortfolioStore, SavePortfolio, StoreError
from terminal_api import app
from tracker import PortfolioError


def request(**changes):
    return BondRequest(**{**dict(name='Fictional bond',settlement='2026-10-01',maturity='2031-10-01',face_amount=10000,coupon_rate=4,frequency=2,yield_percent=4),**changes})


class BondTests(unittest.TestCase):
    def test_par_bond_coupon_date_and_principal_once(self):
        r=analyze_bond(request())
        self.assertAlmostEqual(r['clean_price'],100,11);self.assertEqual(r['accrued_per_100'],0)
        self.assertAlmostEqual(r['settlement_value'],10000,8)
        self.assertEqual(len(r['cashflows']),10);self.assertEqual(r['coupon_payment'],200)
        self.assertEqual(sum(c['principal_per_100'] for c in r['cashflows']),100)
        self.assertEqual(r['cashflows'][0]['date'],'2027-04-01')
        self.assertEqual(r['cashflows'][-1]['position_cashflow'],10200)
        self.assertAlmostEqual(sum(c['present_value'] for c in r['cashflows']),r['settlement_value'],8)

    def test_finance_canada_two_year_eight_percent_at_six_percent(self):
        # The published example has cash flows 4, 4, 4, 104, discounted at 3% per period.
        r=analyze_bond(request(maturity='2028-10-01',coupon_rate=8,yield_percent=6))
        with localcontext() as ctx:
            ctx.prec=50
            expected=sum(Decimal(cf)/Decimal('1.03')**t for t,cf in enumerate([4,4,4,104],1))
        self.assertAlmostEqual(r['clean_price'],float(expected),12)

    def test_actual_accrual_and_dirty_price_fractional_discounting(self):
        r=analyze_bond(request(settlement='2027-01-01'))
        elapsed=(date(2027,1,1)-date(2026,10,1)).days;period=182
        accrued=2*elapsed/period
        expected=sum((102 if i==9 else 2)/1.02**(1-elapsed/period+i) for i in range(10))
        self.assertAlmostEqual(r['accrued_per_100'],accrued,12)
        self.assertAlmostEqual(r['dirty_price'],expected,11)
        self.assertAlmostEqual(r['clean_price']+r['accrued_per_100'],r['dirty_price'],12)
        self.assertAlmostEqual(r['clean_value']+r['accrued_amount'],r['settlement_value'],8)

    def test_thirty360_us_including_february_end(self):
        for start,end,expected in [('2026-02-28','2026-03-31',30),('2024-02-29','2025-02-28',360),('2026-01-31','2026-02-28',28),('2026-01-15','2026-03-31',76)]:
            self.assertEqual(us_30_360(date.fromisoformat(start),date.fromisoformat(end)),expected)
        r=analyze_bond(request(settlement='2027-01-01',day_count='30u360'))
        self.assertEqual(r['accrued_per_100'],1);self.assertEqual(r['audit']['remaining_fraction'],.5)

    def test_month_end_and_anchor_day_do_not_drift_after_february(self):
        maturity=date(2030,8,31)
        self.assertEqual(coupon_date(maturity,6,'maturity_day'),date(2030,2,28))
        self.assertEqual(coupon_date(maturity,12,'maturity_day'),date(2029,8,31))
        end=analyze_bond(request(settlement='2027-09-01',maturity='2028-08-31',date_roll='month_end'))
        self.assertEqual(end['cashflows'][0]['date'],'2028-02-29')
        self.assertEqual(end['audit']['period_days'],182)
        same=schedule(request(settlement='2026-03-01',maturity='2027-02-28'))
        eom=schedule(request(settlement='2026-03-01',maturity='2027-02-28',date_roll='month_end'))
        self.assertEqual(same['dates'][0],date(2026,8,28));self.assertEqual(eom['dates'][0],date(2026,8,31))

    def test_settlement_coupon_is_excluded_and_accrual_resets(self):
        before=analyze_bond(request(settlement='2027-03-31'));on=analyze_bond(request(settlement='2027-04-01'))
        self.assertEqual(len(before['cashflows']),10);self.assertEqual(len(on['cashflows']),9)
        self.assertGreater(before['accrued_per_100'],1.98);self.assertEqual(on['accrued_per_100'],0)

    def test_yield_roundtrip_under_both_daycounts_and_frequencies(self):
        for frequency in [1,2,4]:
            for dc in ['actual_actual','30u360']:
                for y in [-1,0,7.25]:
                    req=request(settlement='2027-01-11',frequency=frequency,day_count=dc,yield_percent=y)
                    r=analyze_bond(req)
                    solved=analyze_bond(req.model_copy(update={'mode':'yield','yield_percent':None,'market_clean':r['clean_price']}))
                    self.assertAlmostEqual(solved['yield_percent'],y,9)
                    self.assertLess(abs(solved['yield_solver_residual']),1e-9)

    def test_zero_coupon_duration_convexity_and_current_yield(self):
        r=analyze_bond(request(coupon_rate=0,yield_percent=5,frequency=1))
        self.assertAlmostEqual(r['dirty_price'],100/1.05**5,12)
        self.assertAlmostEqual(r['macaulay_duration'],5,12)
        self.assertAlmostEqual(r['modified_duration'],5/1.05,12)
        self.assertAlmostEqual(r['convexity'],5*6/1.05**2,12)
        self.assertEqual(r['current_yield'],0);self.assertEqual(r['accrued_per_100'],0)

    def test_duration_and_convexity_match_finite_differences(self):
        req=request(settlement='2027-01-11',yield_percent=6.5);r=analyze_bond(req);h=.0001
        lo=analyze_bond(req.model_copy(update={'yield_percent':6.5-h*100}))['dirty_price']
        hi=analyze_bond(req.model_copy(update={'yield_percent':6.5+h*100}))['dirty_price']
        self.assertAlmostEqual(r['modified_duration'],(lo-hi)/(2*h)/r['dirty_price'],5)
        self.assertAlmostEqual(r['convexity'],(lo+hi-2*r['dirty_price'])/h**2/r['dirty_price'],4)
        self.assertAlmostEqual(r['dv01'],r['modified_duration']*r['settlement_value']*.0001,12)

    def test_last_period_simple_interest_and_derivatives(self):
        req=request(settlement='2031-07-01',discounting='simple_final',yield_percent=8)
        r=analyze_bond(req);t=r['audit']['remaining_fraction']/2
        self.assertAlmostEqual(r['dirty_price'],102/(1+.08*t),12)
        self.assertAlmostEqual(r['modified_duration'],t/(1+.08*t),12)
        self.assertAlmostEqual(r['convexity'],2*t*t/(1+.08*t)**2,12)
        self.assertAlmostEqual(r['macaulay_duration'],t,12)
        self.assertTrue(r['audit']['simple_final_used'])
        compound=analyze_bond(req.model_copy(update={'discounting':'compound'}))
        self.assertNotAlmostEqual(compound['dirty_price'],r['dirty_price'],5)
        self.assertFalse(analyze_bond(request(discounting='simple_final'))['audit']['simple_final_used'])
        solved=analyze_bond(req.model_copy(update={'mode':'yield','market_clean':r['clean_price']}))
        self.assertAlmostEqual(solved['yield_percent'],8,10)

    def test_credit_spread_units_grid_and_shocks(self):
        r=analyze_bond(request(issuer_type='corporate',mode='spread',coupon_rate=6,benchmark_yield=4,spread_bps=150))
        direct=analyze_bond(request(coupon_rate=6,yield_percent=5.5))
        self.assertEqual(r['yield_percent'],5.5);self.assertAlmostEqual(r['clean_price'],direct['clean_price'],12)
        self.assertEqual(r['spread_grid']['rows'][2]['values'][2],r['clean_price'])
        self.assertGreater(r['spread_grid']['rows'][2]['values'][1],r['spread_grid']['rows'][2]['values'][3])
        self.assertGreater(r['shocks'][0]['change'],0);self.assertLess(r['shocks'][-1]['change'],0)
        self.assertEqual(r['shocks'][3]['change'],0)
        self.assertTrue(any('default' in w for w in r['warnings']))

    def test_quote_comparison_and_face_scaling(self):
        a=analyze_bond(request(market_clean=99));b=analyze_bond(request(market_clean=99,face_amount=1000))
        self.assertGreater(a['market_yield_percent'],4);self.assertAlmostEqual(a['market_gap'],-1,11)
        for field in ['clean_price','modified_duration','convexity','yield_percent']:
            self.assertEqual(a[field],b[field])
        self.assertAlmostEqual(a['dv01'],b['dv01']*10,12)
        self.assertAlmostEqual(a['market_settlement_value'],9900,8)

    def test_yield_out_of_range_is_not_fabricated(self):
        with self.assertRaises(PortfolioError):analyze_bond(request(mode='yield',market_clean=.000001))
        r=analyze_bond(request(market_clean=.000001))
        self.assertIsNone(r['market_yield_percent']);self.assertTrue(r['warnings'])

    def test_zero_discount_time_cannot_produce_fake_implied_yield(self):
        req=request(settlement='2031-08-30',maturity='2031-08-31',day_count='30u360',date_roll='month_end',market_clean=100)
        r=analyze_bond(req);self.assertIsNone(r['market_yield_percent']);self.assertEqual(r['modified_duration'],0)
        with self.assertRaises(PortfolioError):analyze_bond(req.model_copy(update={'mode':'yield'}))

    def test_invalid_inputs_are_rejected(self):
        for change in [dict(settlement='2031-10-01'),dict(maturity='2026-10-01'),dict(maturity='2127-10-01'),
                       dict(face_amount=0),dict(coupon_rate=-1),dict(yield_percent=float('nan')),dict(frequency=3),
                       dict(mode='yield'),dict(mode='spread'),dict(yield_percent=None),dict(date_roll='month_end'),
                       dict(mode='spread',benchmark_yield=99,spread_bps=200),dict(market_clean=0)]:
            with self.subTest(change=change),self.assertRaises(ValidationError):request(**change)

    def test_api_is_offline_and_reports_input_and_solver_errors(self):
        client=TestClient(app)
        with patch('terminal_api.fetch_price_history',side_effect=AssertionError('No provider allowed')):
            response=client.post('/api/analytics/bond',json=request().model_dump(mode='json'))
        self.assertEqual(response.status_code,200,response.text)
        self.assertAlmostEqual(response.json()['clean_price'],100,11)
        self.assertEqual(client.post('/api/analytics/bond',json={**request().model_dump(mode='json'),'coupon_rate':None}).status_code,422)
        self.assertEqual(client.post('/api/analytics/bond',json=request(mode='yield',market_clean=.000001).model_dump(mode='json')).status_code,400)

    def test_incomplete_bond_saves_preserve_labs_and_reject_older_clients(self):
        with TemporaryDirectory() as folder:
            store=PortfolioStore(Path(folder)/'test.sqlite3');pid=uuid4()
            record=store.save(SavePortfolio(id=pid,name='Bond',revision=0,state={'analytics':{'version':3,'tool':'bond','company':'Equity','bond_pricing':{'name':'Notes','coupon_rate':'','spread_bps':'125.123456'},'option_pricing':{'spot':'150'}}}))
            self.assertEqual(store.get(pid)['state'],record['state'])
            for version in [1,2]:
                with self.assertRaises(StoreError):store.save(SavePortfolio(id=pid,name='Bond',revision=1,state={'analytics':{'version':version}}))
            saved=store.save(SavePortfolio(id=pid,name='Bond renamed',revision=1,state={'cash':'123'}))
            self.assertEqual(saved['state']['analytics'],record['state']['analytics'])


if __name__=='__main__':unittest.main()
