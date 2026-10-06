"""Known-answer Sharpe/beta and dashboard setting propagation tests."""
import math
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import tracker


def levels(returns):
    return np.r_[100.,100.*np.cumprod(1+np.asarray(returns))]


def fixture():
    market=np.array([-.02,.01,.03,0.])
    asset=2*market+.001
    return pd.DataFrame({'AAA':levels(asset),'SPY':levels(market)},
                        index=pd.date_range('2025-01-01',periods=5))


class RiskTests(unittest.TestCase):
    def test_known_sharpe_and_beta(self):
        px=fixture();r=tracker.risk_statistics(px,'SPY')
        self.assertAlmostEqual(r['summary'].loc['AAA','beta'],2.)
        self.assertAlmostEqual(r['summary'].loc['SPY','beta'],1.)
        # AAA returns: -0.039, 0.021, 0.061, 0.001. Mean = .011.
        sample_std=math.sqrt((.05**2+.01**2+.05**2+.01**2)/3)
        self.assertAlmostEqual(r['summary'].loc['AAA','sharpe_ratio'],.011/sample_std*math.sqrt(252))
        self.assertEqual(r['matched_return_observations'],4)
        self.assertEqual(r['sample_start'],str(px.index[0]))
        self.assertEqual(r['sample_end'],str(px.index[-1]))

    def test_effective_annual_rate_conversion_all_intervals(self):
        px=fixture()
        for interval,n in [('1d',252),('1wk',52),('1mo',12)]:
            with self.subTest(interval=interval):
                r=tracker.risk_statistics(px,'SPY',interval, .05)
                expected_rf=(1.05)**(1/n)-1
                self.assertAlmostEqual(r['period_risk_free_rate'],expected_rf)
                asset_returns=np.array([-.039,.021,.061,.001])
                expected=(asset_returns.mean()-expected_rf)/asset_returns.std(ddof=1)*math.sqrt(n)
                self.assertAlmostEqual(r['summary'].loc['AAA','sharpe_ratio'],expected)
                self.assertAlmostEqual(r['summary'].loc['AAA','beta'],2.)

    def test_risk_free_rate_changes_sharpe_not_beta(self):
        px=fixture()
        zero=tracker.risk_statistics(px,'SPY',annual_risk_free_rate=0)['summary']
        higher=tracker.risk_statistics(px,'SPY',annual_risk_free_rate=.1)['summary']
        self.assertLess(higher.loc['AAA','sharpe_ratio'],zero.loc['AAA','sharpe_ratio'])
        self.assertEqual(higher.loc['AAA','beta'],zero.loc['AAA','beta'])

    def test_gap_is_not_bridged(self):
        px=fixture();px.loc[px.index[2],'SPY']=np.nan
        r=tracker.risk_statistics(px,'SPY')
        # Only periods ending at rows 1 and 4 are valid, not the jump at row 3.
        self.assertEqual(r['matched_return_observations'],2)
        self.assertAlmostEqual(r['summary'].loc['AAA','beta'],2.)

    def test_all_assets_use_same_sample(self):
        px=fixture();px['BBB']=px.AAA;px.loc[px.index[2],'BBB']=np.nan
        r=tracker.risk_statistics(px,'SPY')
        self.assertEqual(r['summary']['matched_return_observations'].tolist(),[2,2,2])

    def test_constant_asset_sharpe_blank_and_beta_zero(self):
        px=fixture();px['AAA']=levels([.02]*4)
        r=tracker.risk_statistics(px,'SPY')
        self.assertTrue(pd.isna(r['summary'].loc['AAA','sharpe_ratio']))
        self.assertAlmostEqual(r['summary'].loc['AAA','beta'],0.)
        self.assertTrue(any('Sharpe is unavailable' in w for w in r['warnings']))

    def test_constant_benchmark_beta_blank(self):
        px=fixture();px['SPY']=100.
        r=tracker.risk_statistics(px,'SPY')
        self.assertTrue(r['summary']['beta'].isna().all())
        self.assertTrue(any('Beta is unavailable' in w for w in r['warnings']))

    def test_insufficient_returns_do_not_crash_comparison(self):
        px=fixture().iloc[:2]
        c=tracker.compare_history(px[['AAA']],px.SPY)
        self.assertEqual(c['risk']['matched_return_observations'],1)
        self.assertTrue(c['risk']['summary'][['sharpe_ratio','beta']].isna().all().all())
        px=fixture();px.iloc[1:4]=np.nan
        c=tracker.compare_history(px[['AAA']],px.SPY)
        self.assertEqual(c['risk']['matched_return_observations'],0)
        self.assertIsNone(c['risk']['sample_start'])

    def test_negative_beta(self):
        px=fixture();px.AAA=levels(-.5*np.array([-.02,.01,.03,0.]))
        self.assertAlmostEqual(tracker.risk_statistics(px,'SPY')['summary'].loc['AAA','beta'],-.5)

    def test_negative_rate_supported_and_invalid_inputs_rejected(self):
        px=fixture()
        self.assertLess(tracker.risk_statistics(px,'SPY',annual_risk_free_rate=-.01)['period_risk_free_rate'],0)
        for value in [-1,-2,np.inf,np.nan,'bad',None]:
            with self.subTest(value=value),self.assertRaises(tracker.PortfolioError):
                tracker.risk_statistics(px,'SPY',annual_risk_free_rate=value)
        self.assertRaises(tracker.PortfolioError,tracker.risk_statistics,px,'SPY','1h')
        self.assertRaises(tracker.PortfolioError,tracker.risk_statistics,px,'MISSING')


class RiskUITests(unittest.TestCase):
    def test_rate_and_interval_settings_propagate_and_invalidate_results(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_data.clear()
        px=fixture()
        def identity(t): return {'ticker':t,'name':'Example','exchange':'NYSE','currency':'USD'}
        def download(*args,**kwargs):
            return (px,pd.DataFrame(),px) if kwargs.get('include_adjusted') else (px,pd.DataFrame())
        with patch('tracker.get_instrument',side_effect=identity),patch('tracker.fetch_price_history',side_effect=download):
            app=AppTest.from_file(str(Path(__file__).with_name('streamlit_app.py')))
            app.session_state['selections']=[identity('AAA')]
            app.session_state['holding_values']={'AAA':{'qty':1.,'avg_cost':80.}}
            app.run()
            next(b for b in app.button if b.label=='Analyze').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertIn('Sharpe ratio and beta',[h.value for h in app.subheader])
            old=app.session_state['analysis']['result']['comparison']['risk']['summary'].loc['My portfolio','sharpe_ratio']
            app.number_input(key='risk_free_percent').set_value(5.).run()
            self.assertNotIn('Sharpe ratio and beta',[h.value for h in app.subheader])
            next(b for b in app.button if b.label=='Analyze').click().run()
            risk=app.session_state['analysis']['result']['comparison']['risk']
            self.assertEqual(risk['annual_risk_free_rate'],.05)
            self.assertLess(risk['summary'].loc['My portfolio','sharpe_ratio'],old)
            self.assertAlmostEqual(risk['summary'].loc['My portfolio','beta'],2.)
            app.radio(key='mode').set_value('Research tickers').run()
            app.radio(key='return_basis').set_value('Total return (dividends reinvested)').run()
            next(s for s in app.selectbox if s.label=='Interval').set_value('1mo').run()
            next(b for b in app.button if b.label=='Analyze').click().run()
            self.assertEqual(len(app.exception),0)
            c=app.session_state['analysis']['result']['comparison']
            self.assertEqual(c['return_basis'],'total')
            self.assertEqual(c['risk']['interval'],'1mo')
            self.assertEqual(c['risk']['periods_per_year'],12)
            self.assertAlmostEqual(c['risk']['summary'].loc['AAA','beta'],2.)
            self.assertTrue(any('Annual risk-free rate: 5.00%' in caption.value for caption in app.caption))


if __name__=='__main__':
    unittest.main()
