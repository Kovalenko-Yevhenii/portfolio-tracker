"""Known-answer allocation, cash, covariance, and direct-entry regressions."""
import math
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import tracker
from portfolio_analysis import allocations_to_positions, diversification_analysis, CASH_LABEL


def entries(amounts=(30.,20.),prices=(150.,200.)):
    return pd.DataFrame({'ticker':['AAA','BBB'],'allocation':amounts,'purchase_price':prices})


def raw_prices():
    # End values equal 100; allocation weights therefore have simple known answers.
    a=np.array([.1,-.1,.1,-.1]);b=np.array([.1,.1,-.1,-.1])
    def levels(r):
        series=np.r_[1.,np.cumprod(1+r)]
        return series/series[-1]*100
    return pd.DataFrame({'AAA':levels(a),'BBB':levels(b),'SPY':levels(a/2)},
                        index=pd.date_range('2025-01-01',periods=5))


def holdings(qty=(1.,1.)):
    return pd.DataFrame({'ticker':['AAA','BBB'],'qty':qty,'avg_cost':[80.,80.]})


class AllocationTests(unittest.TestCase):
    def test_percent_quantities_and_cash(self):
        pos,cash,preview=allocations_to_positions(10000,entries())
        self.assertEqual(pos.qty.tolist(),[20.,10.])
        self.assertEqual(cash,5000)
        self.assertEqual(preview.invested_amount.sum()+cash,10000)

    def test_dollars_and_fractional_shares(self):
        p,cash,_=allocations_to_positions(1000,entries((100.,250.),(30.,200.)),'dollars')
        self.assertAlmostEqual(p.qty.iloc[0],10/3)
        self.assertEqual(p.qty.iloc[1],1.25)
        self.assertEqual(cash,650)

    def test_budget_and_price_validation(self):
        for total,df,unit in [(10000,entries((70,40)),'percent'),(100,entries((70,40)),'dollars'),
                             (0,entries(),'percent'),(100,entries((-1,0)),'percent'),
                             (100,entries((np.nan,0)),'percent'),(100,entries((10,0),(0,0)),'percent'),
                             (100,entries((10,0),(np.inf,0)),'percent')]:
            with self.subTest(total=total,unit=unit),self.assertRaises(tracker.PortfolioError):
                allocations_to_positions(total,df,unit)

    def test_zero_allocations_and_cash_only(self):
        pos,cash,_=allocations_to_positions(1000,entries((0,0),(0,np.nan)))
        self.assertTrue(pos.empty);self.assertEqual(cash,1000)
        pos,cash,_=allocations_to_positions(1000,entries((100,0),(50,0)))
        self.assertEqual(pos.ticker.tolist(),['AAA']);self.assertEqual(cash,0.)

    def test_duplicate_lots_consolidate(self):
        df=entries((30,20),(100,200));df.ticker=['AAA','aaa']
        p,cash,_=allocations_to_positions(1000,df)
        self.assertEqual(p.qty.tolist(),[4.])
        self.assertEqual(p.avg_cost.tolist(),[125.])
        self.assertEqual(cash,500)

    def test_cash_in_snapshot_returns_and_total_return(self):
        px=raw_prices();p=holdings()
        for basis in ['price','total']:
            _,before,mb=tracker.compute_metrics(p,px,adjusted_prices=px,return_basis=basis,window_vol=2)
            _,after,ma=tracker.compute_metrics(p,px,adjusted_prices=px,return_basis=basis,window_vol=2,cash_balance=200.)
            self.assertEqual(ma['total_value'],400)
            self.assertEqual(ma['total_cost'],360)
            self.assertEqual(ma['total_unrealized_pnl'],40)
            np.testing.assert_allclose(after.portfolio_value,before.portfolio_value+200)
            np.testing.assert_allclose(after.performance_value,before.performance_value+200)
            expected=(before.portfolio_value.iloc[1]+200)/(before.portfolio_value.iloc[0]+200)-1
            self.assertAlmostEqual(after.returns.iloc[1],expected)

    def test_cash_does_not_fill_missing_security_prices(self):
        px=raw_prices();px.loc[px.index[2],'AAA']=np.nan
        _,ts,_=tracker.compute_metrics(holdings(),px,cash_balance=100,window_vol=2)
        self.assertTrue(pd.isna(ts.portfolio_value.iloc[2]))
        self.assertTrue(pd.isna(ts.returns.iloc[3]))

    def test_cash_only_metrics_and_risk(self):
        p=pd.DataFrame(columns=['ticker','qty','avg_cost','currency']);px=raw_prices()
        pos,ts,m=tracker.compute_metrics(p,px,cash_balance=1000,return_basis='total',window_vol=2)
        self.assertTrue(pos.empty)
        self.assertEqual(m['total_value'],1000);self.assertEqual(m['total_unrealized_pnl'],0)
        self.assertEqual(m['annualized_volatility'],0);self.assertEqual(m['maximum_drawdown'],0)
        self.assertTrue(ts.returns.dropna().eq(0).all())
        d=diversification_analysis(p,px,px,cash_balance=1000)
        self.assertEqual(d['allocation'].weight.sum(),1)
        self.assertEqual(d['annualized_volatility'],0)
        self.assertTrue(d['correlation'].empty)
        self.assertTrue(d['allocation'].risk_share.isna().all())

    def test_invalid_cash(self):
        for cash in [-1,np.nan,np.inf,'bad']:
            self.assertRaises(tracker.PortfolioError,tracker.compute_metrics,holdings(),raw_prices(),cash_balance=cash)


class DiversificationTests(unittest.TestCase):
    def test_independent_assets_equal_weights_known_covariance(self):
        px=raw_prices();d=diversification_analysis(holdings(),px,px)
        asset_variance=4*.1**2/3
        expected=math.sqrt(.5*asset_variance*252)
        self.assertAlmostEqual(d['annualized_volatility'],expected)
        np.testing.assert_allclose(d['allocation'].risk_share,[.5,.5])
        self.assertAlmostEqual(d['allocation'].volatility_contribution.sum(),expected)
        self.assertAlmostEqual(d['correlation'].loc['AAA','BBB'],0.)
        self.assertEqual(d['observations'],4)

    def test_cash_scales_volatility_but_has_zero_risk(self):
        px=raw_prices();p=holdings()
        full=diversification_analysis(p,px,px)
        half=diversification_analysis(p,px,px,cash_balance=200)
        self.assertAlmostEqual(half['annualized_volatility'],full['annualized_volatility']/2)
        self.assertEqual(half['allocation'].loc[CASH_LABEL,'weight'],.5)
        self.assertEqual(half['allocation'].loc[CASH_LABEL,'risk_share'],0)
        self.assertAlmostEqual(half['allocation'].weight.sum(),1.)
        self.assertAlmostEqual(half['allocation'].risk_share.sum(),1.)

    def test_market_weights_use_latest_common_close(self):
        px=raw_prices();px.loc[px.index[-1],'BBB']=np.nan
        d=diversification_analysis(holdings((1,3)),px,px)
        last=px.iloc[-2][['AAA','BBB']]*[1,3]
        np.testing.assert_allclose(d['allocation'].weight,last/last.sum())
        self.assertEqual(d['valuation_date'],str(px.index[-2]))

    def test_gap_no_bridging(self):
        px=raw_prices();px.loc[px.index[2],'BBB']=np.nan
        d=diversification_analysis(holdings(),px,px)
        self.assertEqual(d['observations'],2)

    def test_total_basis_uses_adjusted_covariance_raw_weights(self):
        px=raw_prices();adj=px.copy();adj['AAA']=px.BBB*.5
        d=diversification_analysis(holdings(),px,adj)
        self.assertAlmostEqual(d['correlation'].loc['AAA','BBB'],1.)
        np.testing.assert_allclose(d['allocation'].weight,[.5,.5])

    def test_negative_contribution_preserved(self):
        px=raw_prices();r=np.array([.1,-.1,.1,-.1])
        values=np.r_[1.,np.cumprod(1-.5*r)]
        px.BBB=values/values[-1]*100
        d=diversification_analysis(holdings((3,1)),px,px)
        self.assertLess(d['allocation'].loc['BBB','risk_share'],0)
        self.assertGreater(d['allocation'].loc['AAA','risk_share'],1)
        self.assertAlmostEqual(d['allocation'].risk_share.sum(),1)

    def test_constant_and_insufficient_history(self):
        px=raw_prices();px[['AAA','BBB']]=100.
        d=diversification_analysis(holdings(),px,px)
        self.assertEqual(d['annualized_volatility'],0)
        self.assertTrue(d['correlation'].isna().all().all())
        self.assertTrue(d['allocation'].risk_share.isna().all())
        px=raw_prices().iloc[:2];d=diversification_analysis(holdings(),px,px)
        self.assertIsNone(d['annualized_volatility'])

    def test_single_asset_and_interval_scaling(self):
        px=raw_prices();p=holdings().iloc[:1]
        daily=diversification_analysis(p,px,px)
        monthly=diversification_analysis(p,px,px,'1mo')
        self.assertAlmostEqual(daily['allocation'].risk_share.iloc[0],1.)
        self.assertAlmostEqual(monthly['annualized_volatility']/daily['annualized_volatility'],math.sqrt(12/252))


class AllocationUITests(unittest.TestCase):
    def test_optional_percent_dollar_entry_and_cash_analysis(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_data.clear();px=raw_prices()
        def identity(t):return {'ticker':t,'name':'Example','exchange':'NYSE','currency':'USD'}
        def download(*args,**kwargs):
            return (px,pd.DataFrame(),px) if kwargs.get('include_adjusted') else (px,pd.DataFrame())
        with patch('tracker.get_instrument',side_effect=identity),patch('tracker.fetch_price_history',side_effect=download):
            app=AppTest.from_file(str(Path(__file__).with_name('streamlit_app.py')))
            app.session_state['selections']=[identity('AAA'),identity('BBB')]
            app.run()
            next(r for r in app.radio if r.label=='Input method').set_value('Enter by allocation (optional)').run()
            app.number_input(key='allocation_percent_AAA').set_value(30.)
            app.number_input(key='purchase_price_AAA').set_value(150.)
            app.number_input(key='allocation_percent_BBB').set_value(20.)
            app.number_input(key='purchase_price_BBB').set_value(200.).run()
            next(b for b in app.button if b.label=='Analyze').click().run()
            self.assertEqual(len(app.exception),0)
            result=app.session_state['analysis']['result']
            self.assertEqual(result['diversification']['allocation'].loc[CASH_LABEL,'market_value'],5000)
            self.assertEqual(next(m.value for m in app.metric if m.label=='Total Value'),'$8,000.00')
            for label in ['Current portfolio allocation','Correlation between holdings','Contribution to portfolio volatility']:
                self.assertIn(label,[h.value for h in app.subheader])
            app.radio(key='allocation_unit').set_value('Dollar amount').run()
            app.number_input(key='allocation_dollars_AAA').set_value(3000.)
            app.number_input(key='allocation_dollars_BBB').set_value(2000.).run()
            next(b for b in app.button if b.label=='Analyze').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(next(m.value for m in app.metric if m.label=='Total Value'),'$8,000.00')
            app.radio(key='allocation_unit').set_value('Percentage').run()
            self.assertEqual(app.number_input(key='allocation_percent_AAA').value,30.)
            self.assertEqual(app.number_input(key='allocation_percent_BBB').value,20.)
            app.radio(key='allocation_unit').set_value('Dollar amount').run()
            self.assertEqual(app.number_input(key='allocation_dollars_AAA').value,3000.)
            app.number_input(key='allocation_dollars_BBB').set_value(9000.).run()
            self.assertTrue(app.error)
            self.assertTrue(next(b.disabled for b in app.button if b.label=='Analyze'))

    def test_cash_only_optional_mode(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_data.clear();px=raw_prices()
        with patch('tracker.get_instrument',return_value={'ticker':'SPY','name':'Example','exchange':'NYSE','currency':'USD'}),patch('tracker.fetch_price_history',return_value=(px,pd.DataFrame())):
            app=AppTest.from_file(str(Path(__file__).with_name('streamlit_app.py'))).run()
            next(r for r in app.radio if r.label=='Input method').set_value('Enter by allocation (optional)').run()
            next(b for b in app.button if b.label=='Analyze').click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(next(m.value for m in app.metric if m.label=='Total Value'),'$10,000.00')


if __name__=='__main__':
    unittest.main()
