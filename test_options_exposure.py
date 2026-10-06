"""Known-answer position sizing and saved exposure compatibility checks."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import unittest

from options_pricing import ScenarioRequest, analyze_scenario
from portfolio_store import PortfolioStore, SavePortfolio, StoreError


class ExposureTests(unittest.TestCase):
    def test_scaled_call_cost_loss_fees_and_payoff(self):
        for multiple in [1, 2, 3, 5]:
            result = analyze_scenario(ScenarioRequest(
                mode='expiry', spot=100, scenario_price=120, fee_per_contract=2,
                legs=[dict(kind='call', quantity=multiple, strike=100, premium=5)]))
            self.assertEqual(result['initial_debit'], 502 * multiple)
            self.assertEqual(result['summary']['maximum_loss'], 502 * multiple)
            self.assertEqual(result['fees'], 2 * multiple)
            self.assertEqual(result['scenario_pnl'], 1498 * multiple)
            self.assertEqual(result['summary']['break_evens'], [105.02])
            self.assertTrue(result['summary']['profit_unlimited'])

    def test_covered_call_remains_covered(self):
        result = analyze_scenario(ScenarioRequest(
            mode='expiry', spot=100, scenario_price=120,
            legs=[dict(kind='stock', quantity=300, premium=100),
                  dict(kind='call', side='sell', quantity=3, strike=110, premium=5)]))
        self.assertFalse(result['summary']['loss_unlimited'])
        self.assertFalse(result['summary']['profit_unlimited'])
        self.assertEqual(result['summary']['maximum_loss'], 28500)
        self.assertEqual(result['summary']['maximum_profit'], 4500)
        self.assertEqual(result['scenario_pnl'], 4500)

    def test_short_call_still_has_unlimited_loss(self):
        result = analyze_scenario(ScenarioRequest(mode='expiry', legs=[
            dict(kind='call', side='sell', quantity=5, strike=100, premium=5)]))
        self.assertTrue(result['summary']['loss_unlimited'])
        self.assertEqual(result['summary']['maximum_profit'], 2500)

    def test_fixed_loan_is_not_multiplied(self):
        result = analyze_scenario(ScenarioRequest(
            mode='expiry', spot=100, scenario_price=120, financing_enabled=True,
            borrowed_amount=250, borrowing_rate=10, financing_days=365,
            legs=[dict(kind='call', quantity=3, strike=100, premium=5)]))
        self.assertEqual(result['financing']['own_capital'], 1250)
        self.assertEqual(result['financing']['scenario_interest'], 25)
        self.assertEqual(result['scenario_pnl'], 4475)
        self.assertEqual(result['summary']['maximum_loss'], 1525)

    def test_multiplier_persists_and_older_clients_cannot_overwrite_it(self):
        with TemporaryDirectory() as directory:
            store = PortfolioStore(Path(directory) / 'test.sqlite3')
            pid = uuid4()
            options = dict(engine_version=4, exposure_multiplier='3', scenarios=[
                dict(id='five', name='Five copies', state=dict(exposure_multiplier='5'))])
            store.save(SavePortfolio(id=pid, name='Exposure', revision=0,
                                     state=dict(options=options)))
            loaded = store.get(pid)['state']['options']
            self.assertEqual(loaded['exposure_multiplier'], '3')
            self.assertEqual(loaded['scenarios'][0]['state']['exposure_multiplier'], '5')
            with self.assertRaises(StoreError):
                store.save(SavePortfolio(id=pid, name='Old client', revision=1,
                                         state=dict(options=dict(engine_version=3))))
            legacy = store.save(SavePortfolio(id=uuid4(), name='Legacy', revision=0,
                                              state=dict(options=dict(engine_version=3))))
            self.assertEqual(legacy['state']['options']['exposure_multiplier'], '1')


if __name__ == '__main__':
    unittest.main()
