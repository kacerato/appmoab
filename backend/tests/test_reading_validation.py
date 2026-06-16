import unittest
import uuid

from fastapi import HTTPException

from app.models.hydrometer import Hydrometer
from app.routers.readings import _evaluate_reading


def hydrometer(**kwargs):
    base = {
        "latitude": -8.0539,
        "longitude": -34.8811,
        "allowed_radius_meters": 80.0,
        "location_required": True,
        "black_digits": 4,
        "red_digits": 3,
    }
    base.update(kwargs)
    meter = Hydrometer(customer_id=uuid.UUID("00000000-0000-0000-0000-000000000001"), code="123")
    for key, value in base.items():
        setattr(meter, key, value)
    return meter


class ReadingValidationTest(unittest.TestCase):
    def test_location_inside_radius_has_no_alert(self):
        consumption, status, distance, flags = _evaluate_reading(
            hydrometer=hydrometer(),
            current_value=12.0,
            previous_value=10.0,
            latitude=-8.05391,
            longitude=-34.88111,
            location_accuracy_meters=8.0,
        )

        self.assertEqual(consumption, 2.0)
        self.assertEqual(status, "ok")
        self.assertLess(distance or 999, 80)
        self.assertEqual(flags, [])

    def test_location_far_marks_blocked_review(self):
        _, status, distance, flags = _evaluate_reading(
            hydrometer=hydrometer(),
            current_value=12.0,
            previous_value=10.0,
            latitude=-8.0639,
            longitude=-34.8911,
            location_accuracy_meters=12.0,
        )

        self.assertEqual(status, "blocked_review")
        self.assertGreater(distance or 0, 320)
        self.assertTrue(any(flag["code"] == "location_far" for flag in flags))

    def test_regressive_reading_without_rollover_is_blocked(self):
        with self.assertRaises(HTTPException):
            _evaluate_reading(
                hydrometer=hydrometer(),
                current_value=30.0,
                previous_value=50.0,
                latitude=-8.05391,
                longitude=-34.88111,
                location_accuracy_meters=8.0,
            )

    def test_rollover_reading_is_allowed(self):
        consumption, _, _, flags = _evaluate_reading(
            hydrometer=hydrometer(),
            current_value=3.0,
            previous_value=9998.0,
            latitude=-8.05391,
            longitude=-34.88111,
            location_accuracy_meters=8.0,
        )

        self.assertEqual(consumption, 5.0)
        self.assertTrue(any(flag["code"] == "meter_rollover" for flag in flags))


if __name__ == "__main__":
    unittest.main()
