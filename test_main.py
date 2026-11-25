import builtins
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class HostelManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_file = self.root / "hostel_data.txt"
        self.backup_file = self.root / "hostel_data.txt.bak"
        self.bills_dir = self.root / "bills"
        self.paths = (
            patch.object(main, "FILE_NAME", self.data_file),
            patch.object(main, "BACKUP_FILE", self.backup_file),
            patch.object(main, "BILLS_DIR", self.bills_dir),
        )
        for item in self.paths:
            item.start()
        self.hostel = main.HostelManagement()

    def tearDown(self):
        for item in reversed(self.paths):
            item.stop()
        self.temp_dir.cleanup()

    def add_room_and_student(self):
        rooms = {"R1": main.Room("R1", "Single", 1, 8000)}
        students = {"S1": main.Student("S1", "Test Student", "9876543210", "Test address")}
        self.assertTrue(self.hostel._commit(rooms, students))

    def test_allocation(self):
        self.add_room_and_student()
        rooms = __import__("copy").deepcopy(self.hostel.rooms)
        students = __import__("copy").deepcopy(self.hostel.students)
        rooms["R1"].students.append("S1")
        students["S1"].room_id = "R1"
        students["S1"].status = "Allocated"
        self.assertTrue(self.hostel._commit(rooms, students))
        self.assertEqual(self.hostel.students["S1"].room_id, "R1")
        self.assertIn("S1", self.hostel.rooms["R1"].students)

    def test_checkout_releases_bed_and_keeps_dates(self):
        self.add_room_and_student()
        rooms = __import__("copy").deepcopy(self.hostel.rooms)
        students = __import__("copy").deepcopy(self.hostel.students)
        rooms["R1"].students.append("S1")
        students["S1"].room_id = "R1"
        students["S1"].status = "Checked In"
        students["S1"].check_in_date = "2026-11-20"
        self.assertTrue(self.hostel._commit(rooms, students))

        rooms = __import__("copy").deepcopy(self.hostel.rooms)
        students = __import__("copy").deepcopy(self.hostel.students)
        rooms["R1"].students.remove("S1")
        students["S1"].room_id = None
        students["S1"].status = "Checked Out"
        students["S1"].check_out_date = "2026-11-22"
        self.assertTrue(self.hostel._commit(rooms, students))
        self.assertEqual(self.hostel.students["S1"].check_in_date, "2026-11-20")
        self.assertEqual(self.hostel.students["S1"].check_out_date, "2026-11-22")
        self.assertEqual(self.hostel.rooms["R1"].available_beds(), 1)


    def test_complete_return_workflow_uses_real_operations(self):
        """Allocate -> check in -> check out -> allocate again -> check in."""
        self.add_room_and_student()

        # Each operation consumes the same prompts a real user would enter.
        with patch("builtins.input", side_effect=["S1", "R1"]):
            self.hostel.allocate_room()
        self.assertEqual(self.hostel.students["S1"].status, "Allocated")
        self.assertEqual(self.hostel.rooms["R1"].students, ["S1"])
        self.assertIsNone(self.hostel.students["S1"].check_in_date)
        self.assertIsNone(self.hostel.students["S1"].check_out_date)

        with patch("builtins.input", return_value="S1"):
            self.hostel.check_in()
        first_check_in = self.hostel.students["S1"].check_in_date
        self.assertEqual(self.hostel.students["S1"].status, "Checked In")
        self.assertEqual(self.hostel.rooms["R1"].students, ["S1"])

        with patch("builtins.input", return_value="S1"):
            self.hostel.check_out()
        first_check_out = self.hostel.students["S1"].check_out_date
        self.assertEqual(self.hostel.students["S1"].status, "Checked Out")
        self.assertIsNone(self.hostel.students["S1"].room_id)
        self.assertEqual(self.hostel.rooms["R1"].students, [])
        self.assertEqual(self.hostel.rooms["R1"].available_beds(), 1)

        with patch("builtins.input", side_effect=["S1", "R1"]):
            self.hostel.allocate_room()
        returning = self.hostel.students["S1"]
        self.assertEqual(returning.status, "Allocated")
        self.assertEqual(returning.room_id, "R1")
        self.assertIsNone(returning.check_in_date)
        self.assertIsNone(returning.check_out_date)
        self.assertEqual(returning.stay_history, [{
            "check_in_date": first_check_in,
            "check_out_date": first_check_out,
        }])
        self.assertEqual(self.hostel.rooms["R1"].students, ["S1"])
        self.assertEqual(self.hostel.rooms["R1"].available_beds(), 0)

        with patch("builtins.input", return_value="S1"):
            self.hostel.check_in()
        second_check_in = self.hostel.students["S1"].check_in_date
        self.assertEqual(self.hostel.students["S1"].status, "Checked In")
        self.assertEqual(self.hostel.rooms["R1"].students, ["S1"])
        self.assertEqual(self.hostel.students["S1"].check_out_date, None)

        # Verify the saved JSON and a fresh application load agree with memory.
        saved = json.loads(self.data_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["rooms"]["R1"]["students"], ["S1"])
        self.assertEqual(saved["students"]["S1"]["status"], "Checked In")
        self.assertEqual(saved["students"]["S1"]["check_in_date"], second_check_in)
        self.assertIsNone(saved["students"]["S1"]["check_out_date"])
        self.assertEqual(saved["students"]["S1"]["stay_history"], [{
            "check_in_date": first_check_in,
            "check_out_date": first_check_out,
        }])
        reloaded = main.HostelManagement()
        self.assertTrue(reloaded.load_ok)
        self.assertEqual(reloaded.students["S1"].status, "Checked In")
        self.assertEqual(reloaded.rooms["R1"].students, ["S1"])
        self.assertEqual(reloaded.students["S1"].stay_history, returning.stay_history)
        self.assertTrue(self.backup_file.exists())

    def test_billing_calculation(self):
        self.add_room_and_student()
        room_fee = main.money(main.Decimal(str(8000)) * 2)
        extra = main.money(main.Decimal("500.00") + main.Decimal("250.00"))
        self.assertEqual(room_fee + extra, main.Decimal("16750.00"))

    def test_generate_bill_writes_bill_file(self):
        self.add_room_and_student()
        rooms = __import__("copy").deepcopy(self.hostel.rooms)
        students = __import__("copy").deepcopy(self.hostel.students)
        rooms["R1"].students.append("S1")
        students["S1"].room_id = "R1"
        students["S1"].status = "Allocated"
        self.assertTrue(self.hostel._commit(rooms, students))

        # Student ID, months, food, electricity, maintenance, paid amount
        answers = iter(["S1", "1", "100", "50", "25", "8175"])
        with patch("builtins.input", side_effect=lambda prompt="": next(answers)):
            self.hostel.generate_bill()

        bill = self.bills_dir / "bill_S1.txt"
        self.assertTrue(bill.exists())
        contents = bill.read_text(encoding="utf-8")
        self.assertIn("Total: Rs.8175.00", contents)
        self.assertIn("Payment status: PAID", contents)

    def test_invalid_phone_rejected(self):
        for phone in ("1234567890", "98765", "abcdefghij", "+919876543210", ""):
            with self.subTest(phone=phone):
                with self.assertRaises(ValueError):
                    self.hostel._valid_phone(phone)
        self.assertEqual(self.hostel._valid_phone("9876543210"), "9876543210")

    def test_registration_rejects_invalid_phone(self):
        answers = iter(["S2", "New Student", "12345", "Some address"])
        with patch("builtins.input", side_effect=lambda prompt="": next(answers)):
            self.hostel.register_student()
        self.assertNotIn("S2", self.hostel.students)

    def test_saved_data_rejects_invalid_phone(self):
        payload = {
            "rooms": {},
            "students": {
                "S1": {
                    "name": "Test", "phone": "12345", "address": "Address",
                    "room_id": None, "check_in_date": None,
                    "check_out_date": None, "status": "Not Allocated"
                }
            }
        }
        self.data_file.write_text(json.dumps(payload), encoding="utf-8")
        loaded = main.HostelManagement()
        self.assertFalse(loaded.load_ok)
        self.assertIn("phone", loaded.load_error.lower())

    def test_checked_in_requires_only_checkin_date(self):
        payload = self.valid_checked_in_payload()
        payload["students"]["S1"]["check_in_date"] = None
        self.assertRaises(ValueError, self.hostel._validate_snapshot, payload)
        payload = self.valid_checked_in_payload()
        payload["students"]["S1"]["check_out_date"] = "2026-11-22"
        self.assertRaises(ValueError, self.hostel._validate_snapshot, payload)

    def test_checked_out_requires_ordered_dates(self):
        payload = self.valid_checked_out_payload()
        payload["students"]["S1"]["check_out_date"] = None
        self.assertRaises(ValueError, self.hostel._validate_snapshot, payload)
        payload = self.valid_checked_out_payload()
        payload["students"]["S1"]["check_out_date"] = "2026-11-19"
        self.assertRaises(ValueError, self.hostel._validate_snapshot, payload)

    def valid_checked_in_payload(self):
        return {
            "rooms": {"R1": {"room_type": "Single", "capacity": 1,
                             "monthly_fee": 8000, "students": ["S1"]}},
            "students": {"S1": {"name": "Test", "phone": "9876543210",
                                "address": "Address", "room_id": "R1",
                                "check_in_date": "2026-11-20",
                                "check_out_date": None, "status": "Checked In"}}
        }

    def valid_checked_out_payload(self):
        return {
            "rooms": {"R1": {"room_type": "Single", "capacity": 1,
                             "monthly_fee": 8000, "students": []}},
            "students": {"S1": {"name": "Test", "phone": "9876543210",
                                "address": "Address", "room_id": None,
                                "check_in_date": "2026-11-20",
                                "check_out_date": "2026-11-22", "status": "Checked Out"}}
        }

    def test_corrupted_json_blocks_writes_and_preserves_file(self):
        original = '{"rooms": broken'
        self.data_file.write_text(original, encoding="utf-8")
        loaded = main.HostelManagement()
        self.assertFalse(loaded.load_ok)
        with self.assertRaises(RuntimeError):
            loaded.save_data()
        self.assertEqual(self.data_file.read_text(encoding="utf-8"), original)

    def test_failed_save_does_not_publish_memory_changes(self):
        self.add_room_and_student()
        previous_rooms = self.hostel.rooms
        previous_students = self.hostel.students
        with patch.object(self.hostel, "_write_snapshot", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.hostel._commit({}, {})
        self.assertIs(self.hostel.rooms, previous_rooms)
        self.assertIs(self.hostel.students, previous_students)


if __name__ == "__main__":
    unittest.main(verbosity=2)
