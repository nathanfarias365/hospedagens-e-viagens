import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app import AvailabilityError, BookingService, ValidationError


class BookingServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.service = BookingService(Path(self.temporary_directory.name) / "test.db")
        self.checkin = (date.today() + timedelta(days=10)).isoformat()
        self.checkout = (date.today() + timedelta(days=12)).isoformat()
        self.customer = {
            "name": "Pessoa de Teste",
            "document": "DOC-12345",
            "email": "teste@example.com",
            "phone": "11999999999",
        }

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_booking(self, room_type="Casal", document=None, **overrides):
        payload = {
            **self.customer,
            "document": document or self.customer["document"],
            "hotel_id": "rio",
            "room_type": room_type,
            "checkin": self.checkin,
            "checkout": self.checkout,
            "guests": 2 if room_type == "Casal" else 1,
            **overrides,
        }
        return self.service.create_reservation(payload)

    def test_booking_uses_room_type_price_and_registers_customer(self):
        booking = self.make_booking("Suíte", guests=3)
        self.assertEqual(booking["total_price"], 1008.0)
        customers = self.service.connect()
        with customers:
            row = customers.execute("SELECT document FROM customers").fetchone()
        customers.close()
        self.assertEqual(row["document"], self.customer["document"])

    def test_booking_rejects_overlapping_stays_when_inventory_is_full(self):
        self.make_booking(document="DOC-11111")
        self.make_booking(document="DOC-22222")
        with self.assertRaises(AvailabilityError):
            self.make_booking(document="DOC-33333")

    def test_adjacent_stays_do_not_overlap(self):
        self.make_booking(document="DOC-11111")
        adjacent_checkin = self.checkout
        adjacent_checkout = (date.fromisoformat(adjacent_checkin) + timedelta(days=2)).isoformat()
        booking = self.make_booking(
            document="DOC-22222",
            checkin=adjacent_checkin,
            checkout=adjacent_checkout,
        )
        self.assertEqual(booking["checkin"], adjacent_checkin)

    def test_room_capacity_is_checked(self):
        with self.assertRaises(AvailabilityError):
            self.make_booking("Solteiro", guests=2)

    def test_invalid_dates_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.make_booking(checkout=self.checkin)

    def test_search_reports_available_room_types(self):
        hotels = self.service.list_hotels({
            "city": "Rio de Janeiro",
            "checkin": self.checkin,
            "checkout": self.checkout,
            "guests": "2",
        })
        self.assertEqual(len(hotels), 1)
        self.assertEqual(
            {room["room_type"] for room in hotels[0]["available_rooms"]},
            {"Casal", "Suíte"},
        )


if __name__ == "__main__":
    unittest.main()
