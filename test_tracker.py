"""Offline regression checks with known answers. Run: python -m unittest -v."""
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import tracker


def holdings():
    return pd.DataFrame({'ticker': ['AAA', 'BBB'], 'qty': [1., 2.], 'avg_cost': [80., 40.]})


def prices():
    return pd.DataFrame({'AAA': [100., 110., 120.], 'BBB': [50., 55., 60.]},
                        index=pd.date_range('2025-01-01', periods=3))


class PortfolioTests(unittest.TestCase):
    def test_known_value_cost_pnl_returns(self):
        pos, ts, m = tracker.compute_metrics(holdings(), prices(), window_vol=2)
        self.assertEqual(m['total_cost'], 160)
        self.assertEqual(m['total_value'], 240)
        self.assertEqual(m['total_unrealized_pnl'], 80)
        self.assertEqual(ts.portfolio_value.tolist(), [200, 220, 240])
        self.assertAlmostEqual(ts.returns.iloc[-1], 1/11)
        expected = abs(.1 - 1/11) / math.sqrt(2) * math.sqrt(252)
        self.assertAlmostEqual(m['annualized_volatility'], expected)

    def test_duplicate_lots_weighted_cost(self):
        p = pd.DataFrame({'ticker': ['AAA', 'aaa '], 'qty': [1., 2.], 'avg_cost': [80., 95.]})
        pos, ts, m = tracker.compute_metrics(p, prices()[['AAA']], window_vol=2)
        self.assertEqual(len(pos), 1)
        self.assertEqual(pos.avg_cost.iloc[0], 90)
        self.assertEqual(m['total_cost'], 270)
        self.assertEqual(m['total_value'], 360)
        self.assertEqual(ts.portfolio_value.iloc[-1], 360)

    def test_missing_quote_not_zero_or_false_return(self):
        px = prices(); px.iloc[1, 1] = np.nan
        _, ts, m = tracker.compute_metrics(holdings(), px, window_vol=2)
        self.assertTrue(pd.isna(ts.portfolio_value.iloc[1]))
        self.assertTrue(ts.returns.isna().all())
        self.assertIsNone(m['annualized_volatility'])
        self.assertEqual(m['missing_price_observations'], 1)

    def test_all_quotes_missing_on_one_date(self):
        px = prices(); px.iloc[1] = np.nan
        ts = tracker.compute_portfolio_timeseries(holdings(), px)
        self.assertTrue(pd.isna(ts.portfolio_value.iloc[1]))

    def test_leading_gap_never_backfilled(self):
        px = prices(); px.iloc[0, 1] = np.nan
        _, ts, _ = tracker.compute_metrics(holdings(), px, window_vol=2)
        self.assertTrue(pd.isna(ts.portfolio_value.iloc[0]))
        self.assertTrue(pd.isna(ts.returns.iloc[1]))

    def test_trailing_gap_snapshot_uses_common_date(self):
        px = prices(); px.iloc[-1, 1] = np.nan
        _, ts, m = tracker.compute_metrics(holdings(), px, window_vol=2)
        self.assertEqual(m['total_value'], 220)
        self.assertEqual(m['valuation_date'], str(px.index[1]))
        self.assertTrue(pd.isna(ts.portfolio_value.iloc[-1]))
        self.assertTrue(any('last complete' in w for w in m['warnings']))

    def test_unavailable_ticker_is_error(self):
        with self.assertRaisesRegex(tracker.PortfolioError, 'BBB'):
            tracker.compute_metrics(holdings(), prices()[['AAA']])

    def test_empty_download_data_is_error(self):
        with self.assertRaisesRegex(tracker.PortfolioError, 'No price history'):
            tracker.compute_metrics(holdings(), pd.DataFrame())

    def test_no_common_date_is_error(self):
        px = prices(); px['AAA'] = [100, np.nan, np.nan]; px['BBB'] = [np.nan, 50, 60]
        with self.assertRaisesRegex(tracker.PortfolioError, 'No date'):
            tracker.compute_metrics(holdings(), px)

    def test_infinite_and_nonpositive_quotes_are_missing(self):
        for bad in [np.inf, -1, 0]:
            px = prices(); px.iloc[1, 1] = bad
            self.assertTrue(pd.isna(tracker.compute_portfolio_timeseries(holdings(), px).portfolio_value.iloc[1]))

    def test_csv_invalid_rows_are_identified(self):
        for row in [',1,100', 'AAA,no,100', 'AAA,1,inf', 'AAA,0,100', 'AAA,-1,100', 'AAA,1,-1']:
            with self.subTest(row=row), self.assertRaisesRegex(tracker.PortfolioError, 'row.*2'):
                tracker.load_positions(io.StringIO('ticker,qty,avg_cost\n' + row))

    def test_csv_normalization(self):
        p = tracker.load_positions(io.StringIO(' TICKER ,QTY,AVG_COST\n aaa ,2,0\n'))
        self.assertEqual(p.ticker.tolist(), ['AAA'])
        self.assertEqual(p.currency.tolist(), ['USD'])

    def test_csv_schema_and_empty_errors(self):
        for content in ['', 'ticker,qty,avg_cost\n', 'ticker,qty\nAAA,1', 'ticker,qty,avg_cost, QTY \nAAA,1,100,2']:
            with self.subTest(content=content), self.assertRaises(tracker.PortfolioError):
                tracker.load_positions(io.StringIO(content))

    def test_non_usd_or_blank_currency_rejected(self):
        for currency in ['EUR', '', None]:
            p = holdings(); p['currency'] = currency
            with self.assertRaisesRegex(tracker.PortfolioError, 'USD'):
                tracker.compute_metrics(p, prices())

    def test_interval_annualization(self):
        r = pd.Series([.01, -.02, .03, -.01, .02])
        for interval, factor in [('1d',252), ('1wk',52), ('1mo',12)]:
            with self.subTest(interval=interval):
                self.assertAlmostEqual(tracker.annualized_volatility(r,5,interval), r.std()*math.sqrt(factor))
        self.assertRaises(tracker.PortfolioError, tracker.annualized_volatility, r,5,'1h')

    def test_invalid_or_incomplete_window(self):
        r = pd.Series([.1, .2, np.nan])
        self.assertTrue(math.isnan(tracker.annualized_volatility(r,2)))
        self.assertTrue(math.isnan(tracker.annualized_volatility(r,5)))
        for n in [0,1,2.5]:
            self.assertRaises(tracker.PortfolioError, tracker.annualized_volatility,r,n)

    def test_downloader_single_and_multiple_shapes(self):
        for tickers in [['AAA'], ['AAA','BBB']]:
            data = pd.concat({t: pd.DataFrame({'Close':[100,110], 'Dividends':[0,1]},
                        index=pd.date_range('2025-01-01',periods=2)) for t in tickers},axis=1)
            with patch('tracker.yf.download', return_value=data) as download:
                px, divs = tracker.fetch_price_history(tickers)
                self.assertEqual(px.columns.tolist(),tickers)
                self.assertEqual(divs.iloc[-1].tolist(),[1]*len(tickers))
                self.assertTrue(download.call_args.kwargs['actions'])
        with patch('tracker.yf.download', return_value=data['AAA']):
            px,_ = tracker.fetch_price_history(['AAA'])
            self.assertEqual(px.AAA.tolist(),[100,110])

    def test_download_failures(self):
        for result in [None,pd.DataFrame()]:
            with patch('tracker.yf.download', return_value=result), self.assertRaises(tracker.PortfolioError):
                tracker.fetch_price_history(['AAA'])
        with patch('tracker.yf.download', side_effect=RuntimeError('offline')), self.assertRaisesRegex(tracker.PortfolioError,'connection'):
            tracker.fetch_price_history(['AAA'])
        data = pd.concat({'AAA':prices().rename(columns={'AAA':'Close'})[['Close']]},axis=1)
        with patch('tracker.yf.download', return_value=data), self.assertRaisesRegex(tracker.PortfolioError,'BBB'):
            tracker.fetch_price_history(['AAA','BBB'])

    def test_dividends_use_calendar_window(self):
        div = pd.DataFrame({'AAA':[5.,1.,2.]},index=pd.to_datetime(['2023-11-01','2024-03-01','2025-01-02']))
        _,_,m = tracker.compute_metrics(holdings(),prices(),div,2)
        self.assertEqual(m['dividends_last_year_by_ticker'],{'AAA':3.})
        self.assertEqual(m['total_value'],240)

    def test_exports(self):
        with tempfile.TemporaryDirectory() as out:
            pos,ts,m = tracker.compute_metrics(holdings(),prices(),window_vol=2)
            files = tracker.export_outputs(pos,ts,m,out)
            self.assertTrue(all(Path(p).is_file() for p in files.values()))
            self.assertEqual(json.loads(Path(files['portfolio_metrics.json']).read_text())['total_value'],240)
            workbook = pd.ExcelFile(files['portfolio_report.xlsx'])
            self.assertEqual(workbook.sheet_names,['Positions','TimeSeries','Metrics'])

    def test_cli_uses_same_engine(self):
        import sys
        with tempfile.TemporaryDirectory() as out:
            source=Path(out)/'input.csv'; holdings().to_csv(source,index=False)
            with patch.object(sys,'argv',['tracker.py','--positions',str(source),'--interval','1mo','--vol_window','2','--out',out]), patch('tracker.fetch_price_history',return_value=(prices(),pd.DataFrame())), patch('sys.stdout',new_callable=io.StringIO):
                tracker.main()
            actual=json.loads((Path(out)/'portfolio_metrics.json').read_text())
            expected=tracker.compute_metrics(holdings(),prices(),window_vol=2,interval='1mo')[2]
            self.assertEqual(actual['total_value'],expected['total_value'])
            self.assertEqual(actual['annualized_volatility'],expected['annualized_volatility'])


class DashboardTests(unittest.TestCase):
    def test_dashboard_starts(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).with_name('streamlit_app.py'))).run()
        self.assertEqual(len(app.exception),0)
        self.assertIn('Add tickers',app.info[-1].value)

    def test_dashboard_renders_shared_metrics_offline(self):
        from streamlit.testing.v1 import AppTest
        script = '''
from streamlit_app import show_portfolio
from test_tracker import holdings, prices
show_portfolio(holdings(),prices(),None,2,'1mo')
'''
        app = AppTest.from_string(script).run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual([m.value for m in app.metric][:3],['$240.00','$80.00','$160.00'])
        self.assertIn('Monthly Returns',[h.value for h in app.subheader])


if __name__ == '__main__':
    unittest.main()
