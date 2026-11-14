import sys
import unittest
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.schedule_clock import (  # noqa: E402
    BOGOTA,
    interval_covers,
    intervals_overlap,
)


class ScheduleClockTest(unittest.TestCase):
    def test_origin_is_monday(self):
        self.assertEqual(datetime(2026, 11, 16, tzinfo=BOGOTA).weekday(), 0)

    def test_window_same_day(self):
        monday_19 = datetime(2026, 11, 16, 19, 0, tzinfo=BOGOTA)
        monday_22 = datetime(2026, 11, 16, 22, 0, tzinfo=BOGOTA)
        tuesday_19 = datetime(2026, 11, 17, 19, 0, tzinfo=BOGOTA)
        self.assertTrue(interval_covers(time(18, 0), time(22, 0), monday_19, {0}))
        self.assertFalse(interval_covers(time(18, 0), time(22, 0), monday_22, {0}))
        self.assertFalse(interval_covers(time(18, 0), time(22, 0), tuesday_19, {0}))

    def test_overnight_belongs_to_start_day(self):
        friday_23 = datetime(2026, 11, 20, 23, 0, tzinfo=BOGOTA)
        saturday_1 = datetime(2026, 11, 21, 1, 0, tzinfo=BOGOTA)
        saturday_3 = datetime(2026, 11, 21, 3, 0, tzinfo=BOGOTA)
        self.assertTrue(interval_covers(time(22, 0), time(2, 0), friday_23, {4}))
        self.assertTrue(interval_covers(time(22, 0), time(2, 0), saturday_1, {4}))
        self.assertFalse(interval_covers(time(22, 0), time(2, 0), saturday_3, {4}))

    def test_touching_ranges_do_not_overlap(self):
        self.assertFalse(
            intervals_overlap(time(18, 0), time(22, 0), {0}, time(22, 0), time(23, 0), {0})
        )

    def test_overnight_overlap(self):
        self.assertTrue(
            intervals_overlap(time(22, 0), time(2, 0), {4}, time(1, 0), time(3, 0), {5})
        )

    def test_as_time_from_timedelta(self):
        from app.services.schedule_clock import as_time

        self.assertEqual(as_time(timedelta(hours=18, minutes=30)), time(18, 30))


if __name__ == "__main__":
    unittest.main()
