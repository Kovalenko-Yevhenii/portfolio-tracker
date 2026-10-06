"""Known-answer dividend reinvestment, valuation separation, and UI regressions."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import tracker


def dividend_fixture():
    dates=pd.date_range('2025-01-01',periods=3)
    prices=pd.DataFrame({'AAA':[100.,98.,99.96],'SPY':[100.,99.,100.98]},index=dates)
    adjusted=pd.DataFrame({'AAA':[98.,98.,99.96],'SPY':[99.,99.,100.98]},index=dates)
    divs=pd.DataFrame({'AAA':[0.,2.,0.],'SPY':[0.,1.,0.]},index=dates)
    return prices,divs,adjusted


def positions():
    return pd.DataFrame({'ticker':['AAA'],'qty':[2.],'avg_cost':[80.]})


class TotalReturnTests(unittest.TestCase):
    def test_dividend_drop_offset_without_double_counting(self):
        px,dv,adj=dividend_fixture()
        _,price_history,p=tracker.compute_metrics(positions(),px,dv,2)
        _,total_history,t=tracker.compute_metrics(positions(),px,dv,2,adjusted_prices=adj,return_basis='total')
        np.testing.assert_allclose(total_history.performance_value,[200,200,204])
        self.assertAlmostEqual(price_history.returns.iloc[1],-.02)
        self.assertAlmostEqual(total_history.returns.iloc[1],0.)
        self.assertAlmostEqual(total_history.returns.iloc[2],.02)
        self.assertEqual(t['maximum_drawdown'],0.)
        self.assertAlmostEqual(p['maximum_drawdown'],-.02)
        for field in ['total_value','total_cost','total_unrealized_pnl']:
            self.assertEqual(t[field],p[field])
        self.assertAlmostEqual(t['total_value'],199.92)

    def test_starting_market_weights_and_adjustment_scale_invariance(self):
        p=pd.DataFrame({'ticker':['AAA','BBB'],'qty':[1.,3.],'avg_cost':[80.,80.]})
        px=pd.DataFrame({'AAA':[100.,105.],'BBB':[100.,100.]})
        adj=pd.DataFrame({'AAA':[50.,55.],'BBB':[10.,10.]})
        result=tracker.portfolio_performance(p,px,adj,'total')
        np.testing.assert_allclose(result,[400,410])
        scaled=adj.mul(pd.Series({'AAA':17,'BBB':.01}))
        np.testing.assert_allclose(tracker.portfolio_performance(p,px,scaled,'total'),result)

    def test_adjusted_equal_close_equals_price_performance(self):
        px,_,_=dividend_fixture()
        np.testing.assert_allclose(tracker.portfolio_performance(positions(),px,px,'total'),
                                   tracker.portfolio_performance(positions(),px,return_basis='price'))

    def test_missing_adjusted_never_falls_back_to_price(self):
        px,_,adj=dividend_fixture()
        for unavailable in [None,pd.DataFrame(),adj[['SPY']]]:
            with self.subTest(unavailable=type(unavailable)),self.assertRaisesRegex(tracker.PortfolioError,'adjusted'):
                tracker.portfolio_performance(positions(),px,unavailable,'total')

    def test_adjusted_interior_gap_preserves_blank_returns(self):
        px,dv,adj=dividend_fixture();adj.iloc[1,0]=np.nan
        _,ts,m=tracker.compute_metrics(positions(),px,dv,2,adjusted_prices=adj,return_basis='total')
        self.assertTrue(ts.returns.isna().all())
        self.assertTrue(pd.isna(ts.performance_value.iloc[1]))
        self.assertTrue(ts.portfolio_value.notna().all())
        self.assertIsNone(m['annualized_volatility'])
        self.assertEqual(m['missing_performance_observations'],1)

    def test_leading_adjusted_gap_uses_first_common_raw_weight(self):
        px,dv,adj=dividend_fixture();adj.iloc[0,0]=np.nan
        _,ts,m=tracker.compute_metrics(positions(),px,dv,2,adjusted_prices=adj,return_basis='total')
        self.assertTrue(pd.isna(ts.performance_value.iloc[0]))
        self.assertEqual(ts.performance_value.iloc[1],196)
        self.assertEqual(m['performance_start'],str(px.index[1]))

    def test_download_returns_both_price_fields_without_substitution(self):
        px,dv,adj=dividend_fixture()
        data=pd.concat({t:pd.DataFrame({'Close':px[t],'Adj Close':adj[t],'Dividends':dv[t]}) for t in px},axis=1)
        with patch('tracker.yf.download',return_value=data) as download:
            a,b,c=tracker.fetch_price_history(['AAA','SPY'],include_adjusted=True)
            self.assertFalse(download.call_args.kwargs['auto_adjust'])
            pd.testing.assert_frame_equal(a,px,check_names=False)
            pd.testing.assert_frame_equal(c,adj,check_names=False)
        with patch('tracker.yf.download',return_value=data.drop(columns=[('SPY','Adj Close')])):
            self.assertRaisesRegex(tracker.PortfolioError,'adjusted',tracker.fetch_price_history,['AAA','SPY'],include_adjusted=True)
            self.assertEqual(len(tracker.fetch_price_history(['AAA','SPY'])),2)

    def test_cli_total_return_export(self):
        px,dv,adj=dividend_fixture()
        with tempfile.TemporaryDirectory() as out:
            source=Path(out)/'holdings.csv';positions().to_csv(source,index=False)
            with patch.object(sys,'argv',['tracker.py','--positions',str(source),'--return_basis','total','--vol_window','2','--out',out]),patch('tracker.fetch_price_history',return_value=(px,dv,adj)),patch('sys.stdout',new_callable=io.StringIO):
                tracker.main()
            m=json.loads((Path(out)/'portfolio_metrics.json').read_text())
            history=pd.read_csv(Path(out)/'portfolio_timeseries.csv')
            self.assertEqual(m['return_basis'],'total')
            self.assertAlmostEqual(m['total_value'],199.92)
            self.assertAlmostEqual(history.performance_value.iloc[-1],204.)

    def test_invalid_basis_rejected(self):
        px,dv,adj=dividend_fixture()
        self.assertRaises(tracker.PortfolioError,tracker.compute_metrics,positions(),px,dv,2,adjusted_prices=adj,return_basis='mystery')


class TotalReturnUITests(unittest.TestCase):
    def test_basis_switch_changes_both_sides_and_preserves_balance(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_data.clear()
        px,dv,adj=dividend_fixture()
        def download(*args,**kwargs):
            return (px,dv,adj) if kwargs.get('include_adjusted') else (px,dv)
        def identity(ticker):
            return {'ticker':ticker,'name':'Example','exchange':'NYSE','currency':'USD'}
        with patch('tracker.fetch_price_history',side_effect=download),patch('tracker.get_instrument',side_effect=identity):
            app=AppTest.from_file(str(Path(__file__).with_name('streamlit_app.py')))
            app.session_state['selections']=[identity('AAA')]
            app.session_state['holding_values']={'AAA':{'qty':2.,'avg_cost':80.}}
            app.run()
            next(b for b in app.button if b.label=='Analyze').click().run()
            before=[m.value for m in app.metric][:3]
            c=app.session_state['analysis']['result']['comparison']
            self.assertAlmostEqual(c['summary'].loc['My portfolio','period_return'],-.0004)
            self.assertAlmostEqual(c['summary'].loc['Benchmark: SPY','period_return'],.0098)
            app.radio(key='return_basis').set_value('Total return (dividends reinvested)').run()
            self.assertNotIn('Benchmark comparison',[h.value for h in app.subheader])
            next(b for b in app.button if b.label=='Analyze').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual([m.value for m in app.metric][:3],before)
            c=app.session_state['analysis']['result']['comparison']
            self.assertEqual(c['return_basis'],'total')
            for ticker in ['My portfolio','Benchmark: SPY']:
                self.assertAlmostEqual(c['summary'].loc[ticker,'period_return'],.02)
            app.radio(key='mode').set_value('Research tickers').run()
            next(b for b in app.button if b.label=='Analyze').click().run()
            self.assertEqual(len(app.exception),0)
            c=app.session_state['analysis']['result']['comparison']
            self.assertAlmostEqual(c['summary'].loc['AAA','period_return'],.02)
            self.assertAlmostEqual(c['summary'].loc['Benchmark: SPY','period_return'],.02)


if __name__=='__main__':
    unittest.main()
