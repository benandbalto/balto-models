"""Commercial leases: bumps, options, rollover, downtime, recoveries and credit loss (synthetic leases)."""
from datetime import date
from decimal import Decimal
import importlib.util
import tempfile
import unittest

from balto_model_engine import DecimalPolicy, Dimension, Item, Model, attr, evaluate, if_, monthly_calendar, ref
from balto_model_engine.commercial import CommercialSpace, build_commercial_income, declare_inputs, space_dimension
from balto_model_engine.workbook import compile_workbook

HAS_COMPILER_DEPS = all(importlib.util.find_spec(m) is not None for m in ('openpyxl', 'pycel'))

D = Decimal
SPACES = (CommercialSpace('nnn', 'Corner cafe', 2600, 'nnn'),
          CommercialSpace('gross', 'Office suite', 1800, 'gross'))
INPUTS = {
    'tax': 3000,
    'commercial.rent': {'nnn': 72000, 'gross': 21600},
    'commercial.bump': {'nnn': '0.025', 'gross': 0},
    'commercial.bump_month': {'nnn': 7, 'gross': 2},
    'commercial.expiry_month': {'nnn': 6, 'gross': 15},
    'commercial.option_exercised': {'nnn': 1, 'gross': 0},
    'commercial.option_months': {'nnn': 60, 'gross': 0},
    'commercial.renewal_probability': {'nnn': '0.5', 'gross': '0.4'},
    'commercial.market_rent': {'nnn': 30, 'gross': 22},
    'commercial.downtime_months': {'nnn': 4, 'gross': 4},
    'commercial.ti': {'nnn': 15, 'gross': 35},
    'commercial.lc': {'nnn': 4, 'gross': 5},
    'commercial.recovery_share': {'nnn': '0.25'},
    'commercial.market_growth': '0.025', 'commercial.new_lease_bump': '0.03', 'commercial.credit_loss_rate': '0.04',
}


def model(spaces=SPACES):
    m = Model('commercial-test', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
    calendar = monthly_calendar(date(2026, 12, 31), 36)
    m.dimension(Dimension('month', calendar.items))
    m.dimension(space_dimension(spaces))
    m.input('tax', unit='usd')
    declare_inputs(m)
    live = ref('live')
    m.calc('live', unit='flag', dims=('month',), expr=if_(attr('month', 'index') >= 1, 1, 0))
    income = build_commercial_income(m, period_index=attr('month', 'index'),
                                     month_of_year=attr('month', 'month_of_year'), active=live,
                                     recoverable_costs=ref('tax') * live)
    return m, income


class CommercialLeaseTest(unittest.TestCase):
    def setUp(self):
        self.m, self.income = model()
        self.run = evaluate(self.m, INPUTS)

    def v(self, name, *idx):
        return self.run.values[name][idx]

    def test_in_place_rent_bumps_in_its_anniversary_month(self):
        monthly = D(72000) / 12
        self.assertEqual(self.v('commercial.base_rent', 'nnn', 6), monthly)
        self.assertEqual(self.v('commercial.base_rent', 'nnn', 7), monthly * D('1.025'))
        self.assertEqual(self.v('commercial.base_rent', 'nnn', 19), monthly * D('1.025') ** 2)

    def test_exercised_options_keep_the_tenant_and_its_bumps(self):
        self.assertEqual(self.v('commercial.lease_end', 'nnn'), 66)
        self.assertEqual(self.v('commercial.downtime', 'nnn', 12), 0)
        self.assertEqual(self.v('commercial.occupancy', 'nnn', 36), 1)

    def test_rollover_weights_renewal_and_downtime(self):
        market_16 = D(22) * 1800 / 12 * D('1.025') ** (D(16) / 12)
        self.assertEqual(self.v('commercial.base_rent', 'gross', 15), 1800)
        # Two in five renew at market at once; three in five go dark for four months.
        self.assertAlmostEqual(self.v('commercial.base_rent', 'gross', 16), D('0.4') * market_16, places=18)
        self.assertAlmostEqual(self.v('commercial.downtime', 'gross', 16), D('0.6') * market_16, places=18)
        self.assertEqual(self.v('commercial.occupancy', 'gross', 16), D('0.4'))
        self.assertEqual(self.v('commercial.occupancy', 'gross', 20), 1)
        self.assertEqual(self.v('commercial.leasing_costs', 'gross', 16), D('0.6') * 1800 * 40)
        self.assertEqual(self.v('commercial.leasing_costs', 'gross', 17), 0)
        # The renewal bumps on its first anniversary, not the calendar.
        renewal = self.v('commercial.renewal_rent', 'gross', 16)
        self.assertEqual(self.v('commercial.renewal_rent', 'gross', 27), renewal)
        self.assertAlmostEqual(self.v('commercial.renewal_rent', 'gross', 28), renewal * D('1.03'), places=18)

    def test_nnn_recovers_its_share_and_credit_loss_applies_to_commercial_income(self):
        self.assertEqual(self.v('commercial.recoveries', 'nnn', 5), 750)
        self.assertEqual(self.v('commercial.recoveries', 'gross', 5), 0)
        base = self.v('commercial.base_rent_total', 5)
        self.assertEqual(self.v('commercial.income', 5), (base + 750) * D('0.96'))
        self.assertEqual(self.v('commercial.net_rent', 5), base * D('0.96'))
        self.assertEqual(self.v('commercial.income', 0), 0)

    def test_no_spaces_needs_no_inputs(self):
        m, income = model(())
        self.assertFalse(income.has_spaces)
        evaluate(m, {'tax': 1})

    @unittest.skipUnless(HAS_COMPILER_DEPS, 'openpyxl and pycel are needed to compile and recalculate')
    def test_workbook_recalculates_live_including_a_flexed_lease(self):
        from balto_model_engine.parity import Tolerance, check_parity
        tolerance = Tolerance(absolute=D('0.000001'), relative=D('1e-9'))
        with tempfile.TemporaryDirectory() as directory:
            path = f'{directory}/commercial.xlsx'
            compiled = compile_workbook(self.m, self.run)
            compiled.save(path)
            report = check_parity(path, compiled, self.m, self.run, tolerance=tolerance)
            self.assertTrue(report.ok, report.mismatches[:5])
            flex = {'commercial.option_exercised': {('nnn',): 0}, 'commercial.expiry_month': {('gross',): 20}}
            report = check_parity(path, compiled, self.m, self.run, tolerance=tolerance, flex=flex, inputs=INPUTS)
            self.assertTrue(report.ok, report.mismatches[:5])

if __name__ == '__main__':
    unittest.main()
