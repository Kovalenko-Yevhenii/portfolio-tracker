"""Known-answer benchmark, drawdown, search, and direct-entry workflow tests."""
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import numpy as np
import pandas as pd
import tracker


def fixture_prices():
    return pd.DataFrame({'AAA':[100.,120.,96.,132.], 'SPY':[100.,110.,99.,121.]},
                        index=pd.date_range('2025-01-01',periods=4))


def identity(ticker):
    return {'ticker':ticker,'name':'Example '+ticker,'exchange':'NYSE','currency':'USD'}


class ComparisonTests(unittest.TestCase):
    def test_known_peak_trough_recovery(self):
        values=pd.Series([100.,120.,96.,108.,132.])
        np.testing.assert_allclose(tracker.drawdown_series(values),[0,0,-.2,-.1,0],atol=1e-14)

    def test_monotonic_and_missing_drawdown(self):
        self.assertEqual(tracker.drawdown_series(pd.Series([100,101,102])).min(),0)
        result=tracker.drawdown_series(pd.Series([np.nan,100.,np.nan,80.]))
        self.assertTrue(pd.isna(result.iloc[0]))
        self.assertTrue(pd.isna(result.iloc[2]))
        self.assertAlmostEqual(result.iloc[-1],-.2)

    def test_comparison_known_returns_and_drawdowns(self):
        px=fixture_prices()
        c=tracker.compare_history(px[['AAA']],px.SPY)
        self.assertAlmostEqual(c['summary'].loc['AAA','period_return'],.32)
        self.assertAlmostEqual(c['summary'].loc['Benchmark: SPY','period_return'],.21)
        self.assertAlmostEqual(c['summary'].loc['AAA','excess_return_vs_benchmark'],.11)
        self.assertAlmostEqual(c['summary'].loc['AAA','maximum_drawdown'],-.2)
        self.assertAlmostEqual(c['summary'].loc['Benchmark: SPY','maximum_drawdown'],-.1)

    def test_identical_asset_and_benchmark(self):
        px=fixture_prices()
        c=tracker.compare_history(px[['SPY']],px.SPY)
        np.testing.assert_allclose(c['normalized'].SPY,c['normalized']['Benchmark: SPY'])
        self.assertEqual(c['summary'].loc['SPY','excess_return_vs_benchmark'],0)

    def test_common_dates_rebase_after_late_listing(self):
        px=fixture_prices(); px.loc[px.index[0],'AAA']=np.nan
        c=tracker.compare_history(px[['AAA']],px.SPY)
        self.assertEqual(c['start'],str(px.index[1]))
        self.assertTrue((c['normalized'].iloc[0]==100).all())
        self.assertAlmostEqual(c['summary'].loc['AAA','period_return'],.1)
        self.assertAlmostEqual(c['summary'].loc['Benchmark: SPY','period_return'],.1)

    def test_gaps_remain_blank_for_both_series(self):
        px=fixture_prices();px.loc[px.index[1],'SPY']=np.nan
        c=tracker.compare_history(px[['AAA']],px.SPY)
        self.assertTrue(c['normalized'].iloc[1].isna().all())
        self.assertEqual(len(c['normalized']),4)
        self.assertTrue(c['warnings'])

    def test_no_overlap_or_only_one_common_observation(self):
        px=fixture_prices()
        for benchmark in [pd.Series([1.,2.],index=pd.date_range('2024-01-01',periods=2)),px.SPY.iloc[:1]]:
            with self.assertRaisesRegex(tracker.PortfolioError,'at least two'):
                tracker.compare_history(px[['AAA']],benchmark)

    def test_search_filters_and_deduplicates_without_autoselecting(self):
        quotes=[{'symbol':'AAA','longname':'Example','exchDisp':'NYSE','quoteType':'EQUITY'},
                {'symbol':'AAA','quoteType':'EQUITY'},
                {'symbol':'BTC-USD','quoteType':'CRYPTOCURRENCY'},
                {'symbol':'SPY','shortname':'SPDR','exchange':'PCX','quoteType':'ETF'}]
        with patch('tracker.yf.Search',return_value=Mock(quotes=quotes)):
            matches=tracker.search_instruments('Example')
        self.assertEqual([r['ticker'] for r in matches],['AAA','SPY'])
        self.assertEqual(matches[0]['exchange'],'NYSE')

    def test_search_errors_and_no_matches(self):
        with patch('tracker.yf.Search',side_effect=RuntimeError('offline')):
            self.assertRaisesRegex(tracker.PortfolioError,'unavailable',tracker.search_instruments,'Apple')
        with patch('tracker.yf.Search',return_value=Mock(quotes=[])):
            self.assertRaisesRegex(tracker.PortfolioError,'No equity',tracker.search_instruments,'xyz')
        self.assertRaises(tracker.PortfolioError,tracker.search_instruments,' ')

    def test_instrument_currency_type_and_exact_symbol(self):
        valid={'symbol':'AAA','quoteType':'EQUITY','currency':'USD','longName':'Example','exchange':'NYQ'}
        with patch('tracker.yf.Ticker',return_value=Mock(get_info=Mock(return_value=valid))):
            self.assertEqual(tracker.get_instrument(' aaa ')['ticker'],'AAA')
        for replacement in [{'currency':'EUR'},{'quoteType':'FUTURE'},{'symbol':'OTHER'},{'currency':None}]:
            info={**valid,**replacement}
            with patch('tracker.yf.Ticker',return_value=Mock(get_info=Mock(return_value=info))):
                self.assertRaises(tracker.PortfolioError,tracker.get_instrument,'AAA')


class DirectEntryTests(unittest.TestCase):
    @staticmethod
    def button(app,label):
        return next(b for b in app.button if b.label==label)

    def app(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_data.clear()
        return AppTest.from_file(str(Path(__file__).with_name('streamlit_app.py')))

    def test_search_select_research_analyze_change_settings(self):
        with patch('tracker.search_instruments',return_value=[identity('AAA')]), patch('tracker.get_instrument',side_effect=identity), patch('tracker.fetch_price_history',return_value=(fixture_prices(),pd.DataFrame())):
            app=self.app().run()
            self.assertEqual(len(app.exception),0)
            self.assertFalse(any(n.type=='file_uploader' for n in app))
            app.radio(key='mode').set_value('Research tickers').run()
            app.text_input(key='search_query').set_value('Example')
            self.button(app,'Search tickers').click().run()
            self.button(app,'Add selected ticker').click().run()
            self.assertEqual(app.session_state['selections'][0]['ticker'],'AAA')
            self.button(app,'Analyze').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertIn('Benchmark comparison',[h.value for h in app.subheader])
            c=app.session_state['analysis']['result']['comparison']
            self.assertAlmostEqual(c['summary'].loc['AAA','period_return'],.32)
            next(s for s in app.selectbox if s.label=='Interval').set_value('1wk').run()
            self.assertNotIn('Benchmark comparison',[h.value for h in app.subheader])

    def test_manual_holdings_analyze_without_upload(self):
        with patch('tracker.get_instrument',side_effect=identity),patch('tracker.fetch_price_history',return_value=(fixture_prices(),pd.DataFrame())):
            app=self.app()
            app.session_state['selections']=[identity('AAA')]
            app.session_state['holding_values']={'AAA':{'qty':2.,'avg_cost':80.}}
            app.run()
            self.button(app,'Analyze').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual([m.value for m in app.metric][:3],['$264.00','$104.00','$160.00'])
            self.assertIn('Benchmark comparison',[h.value for h in app.subheader])
            self.assertAlmostEqual(app.session_state['analysis']['result']['comparison']['summary'].loc['My portfolio','maximum_drawdown'],-.2)

    def test_missing_holding_inputs_show_error(self):
        app=self.app();app.session_state['selections']=[identity('AAA')];app.run()
        self.button(app,'Analyze').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertTrue(app.error)

    def test_search_connection_error_shown(self):
        with patch('tracker.search_instruments',side_effect=tracker.PortfolioError('Search unavailable')):
            app=self.app().run();app.text_input(key='search_query').set_value('Apple')
            self.button(app,'Search tickers').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(app.error[0].value,'Search unavailable')

    def test_csv_remains_optional(self):
        app=self.app().run()
        next(r for r in app.radio if r.label=='Input method').set_value('Upload CSV (optional)').run()
        self.assertEqual(len(app.exception),0)
        self.assertTrue(any(n.type=='file_uploader' for n in app))


if __name__=='__main__':
    unittest.main()
