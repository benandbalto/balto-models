"""Caller-selected period and date boundaries determine eligible cash."""
from datetime import date
from decimal import Decimal
import unittest

from balto_model_engine import DecimalPolicy, Model, attr, const, evaluate, monthly_calendar, ref
from balto_model_engine.periods import period_total, period_window


class PeriodComponentTest(unittest.TestCase):
    def test_event_boundaries_select_year_one_trailing_and_forward_cash(self):
        m = Model('windows', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(monthly_calendar(date(2024, 1, 31), 24, name='interval'))
        m.input('cash', unit='usd', dims=('interval',))
        m.input('event', unit='period')
        idx = attr('interval', 'index')
        for name, start, end, include_start, include_end in (
            ('first', const(0), const(12), False, True),
            ('trailing', ref('event') - 12, ref('event'), False, True),
            ('forward', ref('event'), ref('event') + 12, False, True),
            ('closed', ref('event'), ref('event'), True, True),
            ('half_open', ref('event'), ref('event') + 2, True, False),
            ('open', ref('event'), ref('event'), False, False),
        ):
            mask = period_window(idx, start=start, end=end,
                include_start=include_start, include_end=include_end)
            m.calc(name, unit='usd', expr=period_total('interval', ref('cash'), activity=mask))
        # Dates are Excel serials; Jan 31 -> leap-day Feb 29 is an exact boundary.
        dates = [i.attrs['date'] for i in m.dimensions['interval'].items]
        m.calc('leap_day', unit='usd', expr=period_total('interval', ref('cash'), activity=period_window(
            attr('interval', 'date'), start=const(dates[0]), end=const(dates[1]),
            include_start=False, include_end=True)))
        m.calc('filtered', unit='usd', expr=period_total('interval', ref('cash'), hold_year=1))
        inputs = {'cash': {i: i for i in range(25)}, 'event': 12}
        r = evaluate(m, inputs)
        self.assertEqual(r.value('first'), sum(range(1, 13)))
        self.assertEqual(r.value('filtered'), r.value('first'))
        self.assertEqual(r.value('trailing'), sum(range(1, 13)))
        self.assertEqual(r.value('forward'), sum(range(13, 25)))
        self.assertEqual(r.value('closed'), 12)
        self.assertEqual(r.value('half_open'), 25)
        self.assertEqual(r.value('open'), 0)
        self.assertEqual(r.value('leap_day'), Decimal(1))
        shifted = evaluate(m, {**inputs, 'event': 13})
        self.assertEqual(shifted.value('trailing'), sum(range(2, 14)))
        # A truncated projection contributes only existing periods.
        self.assertEqual(shifted.value('forward'), sum(range(14, 25)))


if __name__ == '__main__':
    unittest.main()
