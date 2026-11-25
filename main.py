import copy
import json
import math
import os
import re
import shutil
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
FILE_NAME = BASE_DIR / "hostel_data.txt"
BILLS_DIR = BASE_DIR / "bills"
BACKUP_FILE = FILE_NAME.with_suffix(FILE_NAME.suffix + ".bak")

ROOM_RULES = {
    "Single": (1, 8000.00),
    "Double": (2, 6000.00),
    "Triple": (3, 5000.00),
}
STATUSES = {"Not Allocated", "Allocated", "Checked In", "Checked Out"}
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def money(value):
    """Return a finite amount rounded consistently to two decimal places."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if not amount.is_finite() or amount < 0:
        raise ValueError("Money must be finite and non-negative.")
    return amount


class Person:
    def __init__(self, name, phone):
        self.name = name
        self.phone = phone


class Student(Person):
    def __init__(self, student_id, name, phone, address):
        super().__init__(name, phone)
        self.student_id = student_id
        self.address = address
        self.room_id = None
        self.check_in_date = None
        self.check_out_date = None
        self.stay_history = []
        self.status = "Not Allocated"


class Room:
    def __init__(self, room_id, room_type, capacity, monthly_fee):
        self.room_id = room_id
        self.room_type = room_type
        self.capacity = capacity
        self.monthly_fee = float(money(monthly_fee))
        self.students = []

    def available_beds(self):
        return self.capacity - len(self.students)

    def is_available(self):
        return self.available_beds() > 0


class HostelManagement:
    def __init__(self):
        self.rooms = {}
        self.students = {}
        self.load_ok = True
        self.load_error = None
        self.load_data()

    # ---------- Serialization, validation and persistence ----------

    def _snapshot(self, rooms=None, students=None):
        rooms = self.rooms if rooms is None else rooms
        students = self.students if students is None else students
        return {
            "rooms": {
                rid: {
                    "room_type": room.room_type,
                    "capacity": room.capacity,
                    "monthly_fee": float(money(room.monthly_fee)),
                    "students": list(room.students),
                }
                for rid, room in rooms.items()
            },
            "students": {
                sid: {
                    "name": student.name,
                    "phone": student.phone,
                    "address": student.address,
                    "room_id": student.room_id,
                    "check_in_date": student.check_in_date,
                    "check_out_date": student.check_out_date,
                    "stay_history": copy.deepcopy(student.stay_history),
                    "status": student.status,
                }
                for sid, student in students.items()
            },
        }

    @staticmethod
    def _valid_id(value, label):
        if not isinstance(value, str) or not SAFE_ID.fullmatch(value.strip()):
            raise ValueError(f"{label} must contain 1-40 letters, numbers, '_' or '-'.")
        return value.strip()

    @staticmethod
    def _valid_text(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a nonblank string.")
        return value.strip()

    @staticmethod
    def _valid_phone(value):
        """Accept a 10-digit Indian mobile number beginning with 6, 7, 8 or 9."""
        if not isinstance(value, str) or not re.fullmatch(r"[6-9][0-9]{9}", value.strip()):
            raise ValueError("Phone number must be a valid 10-digit Indian mobile number.")
        return value.strip()

    def _validate_snapshot(self, data):
        if not isinstance(data, dict):
            raise ValueError("Storage root must be a JSON object.")
        if set(data) != {"rooms", "students"}:
            raise ValueError("Storage must contain exactly 'rooms' and 'students'.")
        raw_rooms, raw_students = data["rooms"], data["students"]
        if not isinstance(raw_rooms, dict) or not isinstance(raw_students, dict):
            raise ValueError("'rooms' and 'students' must be JSON objects.")

        rooms, students = {}, {}
        for rid, details in raw_rooms.items():
            rid = self._valid_id(rid, "Room ID")
            if rid in rooms or not isinstance(details, dict):
                raise ValueError(f"Duplicate or invalid room record: {rid}")
            room_type = details.get("room_type")
            if room_type not in ROOM_RULES:
                raise ValueError(f"Room {rid}: unsupported room type.")
            expected_capacity = ROOM_RULES[room_type][0]
            capacity = details.get("capacity")
            if type(capacity) is not int or capacity <= 0 or capacity != expected_capacity:
                raise ValueError(f"Room {rid}: invalid capacity for {room_type}.")
            fee = money(details.get("monthly_fee"))
            occupants = details.get("students")
            if not isinstance(occupants, list):
                raise ValueError(f"Room {rid}: occupants must be a list.")
            if len(occupants) > capacity:
                raise ValueError(f"Room {rid}: occupied beds exceed capacity.")
            clean_occupants = [self._valid_id(x, "Occupant student ID") for x in occupants]
            if len(clean_occupants) != len(set(clean_occupants)):
                raise ValueError(f"Room {rid}: duplicate occupant ID.")
            room = Room(rid, room_type, capacity, fee)
            room.students = clean_occupants
            rooms[rid] = room

        for sid, details in raw_students.items():
            sid = self._valid_id(sid, "Student ID")
            if sid in students or not isinstance(details, dict):
                raise ValueError(f"Duplicate or invalid student record: {sid}")
            student = Student(
                sid,
                self._valid_text(details.get("name"), f"Student {sid} name"),
                self._valid_phone(details.get("phone")),
                self._valid_text(details.get("address"), f"Student {sid} address"),
            )
            room_id = details.get("room_id")
            if room_id is not None:
                room_id = self._valid_id(room_id, f"Student {sid} room ID")
            status = details.get("status")
            if status not in STATUSES:
                raise ValueError(f"Student {sid}: unsupported status.")
            check_in = details.get("check_in_date")
            check_out = details.get("check_out_date")

            parsed_check_in = None
            parsed_check_out = None
            for label, value in (("check-in date", check_in), ("check-out date", check_out)):
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError(f"Student {sid}: invalid {label}.")
                    try:
                        parsed = date.fromisoformat(value)
                    except ValueError:
                        raise ValueError(f"Student {sid}: invalid {label}; use YYYY-MM-DD.")
                    if parsed.isoformat() != value:
                        raise ValueError(f"Student {sid}: {label} must use YYYY-MM-DD format.")
                    if label == "check-in date":
                        parsed_check_in = parsed
                    else:
                        parsed_check_out = parsed

            if status == "Checked In":
                if parsed_check_in is None or parsed_check_out is not None:
                    raise ValueError(
                        f"Student {sid}: Checked In requires a check-in date and no check-out date."
                    )
            elif status == "Checked Out":
                if parsed_check_in is None or parsed_check_out is None:
                    raise ValueError(
                        f"Student {sid}: Checked Out requires both check-in and check-out dates."
                    )
                if parsed_check_out < parsed_check_in:
                    raise ValueError(
                        f"Student {sid}: check-out date cannot be earlier than check-in date."
                    )
            elif parsed_check_in is not None or parsed_check_out is not None:
                raise ValueError(
                    f"Student {sid}: dates are only allowed for Checked In or Checked Out students."
                )

            # Stay history is optional for compatibility with older data files.
            history = details.get("stay_history", [])
            if not isinstance(history, list):
                raise ValueError(f"Student {sid}: stay_history must be a list.")
            clean_history = []
            for index, stay in enumerate(history, start=1):
                if not isinstance(stay, dict):
                    raise ValueError(f"Student {sid}: invalid stay history entry {index}.")
                old_in, old_out = stay.get("check_in_date"), stay.get("check_out_date")
                if not isinstance(old_in, str) or not isinstance(old_out, str):
                    raise ValueError(f"Student {sid}: stay history requires both dates.")
                try:
                    parsed_in = date.fromisoformat(old_in)
                    parsed_out = date.fromisoformat(old_out)
                except ValueError:
                    raise ValueError(f"Student {sid}: invalid stay history date.")
                if parsed_in.isoformat() != old_in or parsed_out.isoformat() != old_out:
                    raise ValueError(f"Student {sid}: stay history dates must use YYYY-MM-DD.")
                if parsed_out < parsed_in:
                    raise ValueError(f"Student {sid}: stay history check-out precedes check-in.")
                clean_history.append({
                    "check_in_date": old_in,
                    "check_out_date": old_out,
                })

            student.room_id = room_id
            student.status = status
            student.check_in_date = check_in
            student.check_out_date = check_out
            student.stay_history = clean_history
            students[sid] = student

        # Validate both directions of every room/student relationship.
        seen_occupants = set()
        for rid, room in rooms.items():
            for sid in room.students:
                if sid not in students:
                    raise ValueError(f"Room {rid} references unknown student {sid}.")
                if sid in seen_occupants:
                    raise ValueError(f"Student {sid} appears in more than one room.")
                seen_occupants.add(sid)
                student = students[sid]
                if student.room_id != rid or student.status not in {"Allocated", "Checked In"}:
                    raise ValueError(f"Room/student relationship mismatch for {sid}.")
        for sid, student in students.items():
            if student.status in {"Allocated", "Checked In"}:
                if student.room_id not in rooms:
                    raise ValueError(f"Student {sid} references a nonexistent room.")
                if sid not in rooms[student.room_id].students:
                    raise ValueError(f"Student {sid} is missing from room occupant list.")
            elif student.room_id is not None:
                raise ValueError(f"Student {sid} has a room but status is {student.status}.")
        return rooms, students

    def load_data(self):
        if not FILE_NAME.exists():
            self.rooms, self.students = {}, {}
            self.load_ok = True
            return
        try:
            with FILE_NAME.open("r", encoding="utf-8") as file:
                raw = json.load(file)
            rooms, students = self._validate_snapshot(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, InvalidOperation) as error:
            self.load_ok = False
            self.load_error = str(error)
            print(f"ERROR: Hostel data was not loaded: {error}")
            print(f"Original file preserved: {FILE_NAME}")
            print("Use menu option 14 to back up and reset/recover the data.")
            return
        self.rooms, self.students = rooms, students
        self.load_ok = True
        self.load_error = None

    def _write_snapshot(self, rooms, students):
        data = self._snapshot(rooms, students)
        self._validate_snapshot(data)
        FILE_NAME.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=FILE_NAME.parent,
                prefix=FILE_NAME.name + ".", suffix=".tmp", delete=False
            ) as temp:
                temp_path = Path(temp.name)
                json.dump(data, temp, indent=4, allow_nan=False)
                temp.flush()
                os.fsync(temp.fileno())
            # Keep the last on-disk version before replacing it.
            if FILE_NAME.exists():
                shutil.copy2(FILE_NAME, BACKUP_FILE)
            os.replace(temp_path, FILE_NAME)
        except Exception:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

    def save_data(self):
        if not self.load_ok:
            raise RuntimeError("Saving is blocked because the existing data failed to load.")
        self._write_snapshot(self.rooms, self.students)

    def _commit(self, rooms, students):
        """Persist proposed state first; publish it in memory only after success."""
        if not self.load_ok:
            print("Change blocked: storage did not load safely.")
            return False
        self._write_snapshot(rooms, students)
        self.rooms, self.students = rooms, students
        return True

    def recover_reset(self):
        print("\nRecovery will replace the current data with an empty hostel database.")
        confirm = input("Type RESET to continue: ").strip()
        if confirm != "RESET":
            print("Recovery cancelled.")
            return
        try:
            if FILE_NAME.exists():
                recovery_backup = FILE_NAME.with_name(FILE_NAME.name + ".recovery.bak")
                shutil.copy2(FILE_NAME, recovery_backup)
                print("Damaged/original file backed up to:", recovery_backup)
            empty_rooms, empty_students = {}, {}
            self._write_snapshot(empty_rooms, empty_students)
            self.rooms, self.students = empty_rooms, empty_students
            self.load_ok = True
            self.load_error = None
            print("Recovery completed. Empty database saved.")
        except OSError as error:
            print("Recovery failed; original file was not intentionally removed:", error)

    # ---------- Input helpers ----------

    @staticmethod
    def get_number(prompt, number_type=int, minimum=0):
        while True:
            raw = input(prompt).strip()
            try:
                if number_type is int:
                    value = int(raw)
                    if value < minimum:
                        raise ValueError
                    return value
                value = float(raw)
                if not math.isfinite(value) or value < minimum:
                    raise ValueError
                return float(money(value))
            except (ValueError, InvalidOperation):
                print(f"Enter a finite valid number greater than or equal to {minimum}.")

    # ---------- Hostel operations ----------

    def add_room(self):
        rid = input("Enter room ID: ").strip()
        try:
            self._valid_id(rid, "Room ID")
        except ValueError as error:
            print(error); return
        if rid in self.rooms:
            print("Room ID already exists."); return
        print("1. Single  2. Double  3. Triple")
        choices = {"1": "Single", "2": "Double", "3": "Triple"}
        choice = input("Select room type: ").strip()
        if choice not in choices:
            print("Invalid room type."); return
        kind = choices[choice]
        capacity, default_fee = ROOM_RULES[kind]
        fee = self.get_number(f"Monthly fee (0 for default Rs.{default_fee:.2f}): ", float)
        if fee == 0:
            fee = default_fee
        rooms, students = copy.deepcopy(self.rooms), copy.deepcopy(self.students)
        rooms[rid] = Room(rid, kind, capacity, fee)
        if self._commit(rooms, students):
            print("Room added and saved successfully.")

    def view_rooms(self):
        if not self.rooms:
            print("No rooms available."); return
        print(f"{'Room ID':<12}{'Type':<12}{'Capacity':<12}{'Occupied':<12}{'Available':<12}{'Fee':<10}")
        for room in self.rooms.values():
            print(f"{room.room_id:<12}{room.room_type:<12}{room.capacity:<12}"
                  f"{len(room.students):<12}{room.available_beds():<12}{room.monthly_fee:<10.2f}")

    def register_student(self):
        sid = input("Enter student ID: ").strip()
        try:
            self._valid_id(sid, "Student ID")
        except ValueError as error:
            print(error); return
        if sid in self.students:
            print("Student ID already exists."); return
        name = input("Enter name: ").strip()
        name = name.strip()
        phone = input("Enter phone: ").strip()
        address = input("Enter address: ").strip()
        if not name or not address:
            print("Name and address are required."); return
        try:
            phone = self._valid_phone(phone)
        except ValueError as error:
            print(error)
            return
        rooms, students = copy.deepcopy(self.rooms), copy.deepcopy(self.students)
        students[sid] = Student(sid, name, phone, address)
        if self._commit(rooms, students):
            print("Student registered and saved successfully.")

    def view_students(self):
        if not self.students:
            print("No students registered."); return
        for s in self.students.values():
            print("-" * 35)
            print("ID:", s.student_id, "| Name:", s.name, "| Phone:", s.phone)
            print("Address:", s.address, "| Room:", s.room_id or "Not Allocated")
            print("Status:", s.status)

    def check_availability(self):
        found = False
        for room in self.rooms.values():
            if room.is_available():
                found = True
                print(f"Room {room.room_id} ({room.room_type}) - "
                      f"{room.available_beds()} bed(s), Rs.{room.monthly_fee:.2f}/month")
        if not found:
            print("No available beds.")

    def allocate_room(self):
        sid = input("Enter student ID: ").strip()
        if sid not in self.students:
            print("Student not found."); return
        if self.students[sid].room_id is not None:
            print("Student already has a room."); return
        self.check_availability()
        rid = input("Enter room ID: ").strip()
        if rid not in self.rooms:
            print("Room not found."); return
        rooms, students = copy.deepcopy(self.rooms), copy.deepcopy(self.students)
        room, student = rooms[rid], students[sid]
        if not room.is_available():
            print("Room is full."); return
        room.students.append(sid)
        # Archive a completed previous stay before resetting dates for this allocation.
        if student.status == "Checked Out":
            if student.check_in_date and student.check_out_date:
                student.stay_history.append({
                    "check_in_date": student.check_in_date,
                    "check_out_date": student.check_out_date,
                })
        student.check_in_date = None
        student.check_out_date = None
        student.room_id, student.status = rid, "Allocated"
        if self._commit(rooms, students):
            print("Room allocated and saved successfully.")

    def cancel_allocation(self):
        sid = input("Enter student ID: ").strip()
        if sid not in self.students:
            print("Student not found."); return
        original = self.students[sid]
        if original.room_id is None:
            print("No room allocation found."); return
        if original.status == "Checked In":
            print("Check out the student before cancelling allocation."); return
        rooms, students = copy.deepcopy(self.rooms), copy.deepcopy(self.students)
        room_id = students[sid].room_id
        rooms[room_id].students.remove(sid)
        students[sid].room_id, students[sid].status = None, "Not Allocated"
        if self._commit(rooms, students):
            print("Allocation cancelled and saved.")

    def check_in(self):
        sid = input("Enter student ID: ").strip()
        if sid not in self.students:
            print("Student not found."); return
        original = self.students[sid]
        if original.room_id is None or original.status != "Allocated":
            print("Student must have an active allocation before check-in."); return
        rooms, students = copy.deepcopy(self.rooms), copy.deepcopy(self.students)
        student = students[sid]
        student.check_in_date, student.check_out_date = date.today().isoformat(), None
        student.status = "Checked In"
        if self._commit(rooms, students):
            print("Student checked in and saved:", student.check_in_date)

    def check_out(self):
        sid = input("Enter student ID: ").strip()
        if sid not in self.students:
            print("Student not found."); return
        if self.students[sid].status != "Checked In":
            print("Student is not currently checked in."); return
        rooms, students = copy.deepcopy(self.rooms), copy.deepcopy(self.students)
        student = students[sid]
        rooms[student.room_id].students.remove(sid)
        student.check_out_date = date.today().isoformat()
        student.room_id, student.status = None, "Checked Out"
        if self._commit(rooms, students):
            print("Student checked out and bed released:", student.check_out_date)

    def calculate_charges(self):
        food = self.get_number("Food charges: Rs.", float)
        electricity = self.get_number("Electricity charges: Rs.", float)
        maintenance = self.get_number("Maintenance charges: Rs.", float)
        return money(Decimal(str(food)) + Decimal(str(electricity)) + Decimal(str(maintenance)))

    def generate_bill(self):
        sid = input("Enter student ID: ").strip()
        if sid not in self.students:
            print("Student not found."); return
        student = self.students[sid]
        if student.room_id is None:
            print("Student has no allocated room."); return
        months = self.get_number("Number of months: ", int, minimum=1)
        extra = self.calculate_charges()
        room_fee = money(Decimal(str(self.rooms[student.room_id].monthly_fee)) * months)
        total = money(room_fee + extra)
        print(f"Room fee: Rs.{room_fee:.2f}")
        print(f"Additional charges: Rs.{extra:.2f}")
        print(f"Total: Rs.{total:.2f}")
        paid = money(self.get_number("Paid amount: Rs.", float))
        if paid > total:
            print("Paid amount cannot exceed total."); return
        balance = money(total - paid)
        status = "PAID" if balance == Decimal("0.00") else "PENDING"
        lines = [
            "", "PG HOSTEL BILL", f"Student: {student.name} ({sid})",
            f"Room: {student.room_id}", f"Months: {months}",
            f"Room fee: Rs.{room_fee:.2f}", f"Additional charges: Rs.{extra:.2f}",
            f"Total: Rs.{total:.2f}", f"Paid: Rs.{paid:.2f}",
            f"Balance: Rs.{balance:.2f}", f"Payment status: {status}",
            f"Date: {date.today().isoformat()}", "-" * 35,
        ]
        BILLS_DIR.mkdir(parents=True, exist_ok=True)
        bill_path = BILLS_DIR / f"bill_{sid}.txt"
        with bill_path.open("a", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")
        print(f"Paid: Rs.{paid:.2f} | Balance: Rs.{balance:.2f} | {status}")
        print("Bill saved to", bill_path)

    def hostel_summary(self):
        total_rooms = len(self.rooms)
        capacity = sum(room.capacity for room in self.rooms.values())
        occupied = sum(len(room.students) for room in self.rooms.values())
        allocated = sum(1 for s in self.students.values() if s.room_id is not None)
        checked_in = sum(1 for s in self.students.values() if s.status == "Checked In")
        print("Total rooms:", total_rooms)
        print("Total bed capacity:", capacity)
        print("Occupied beds:", occupied)
        print("Available beds:", capacity - occupied)
        print("Registered students:", len(self.students))
        print("Allocated students:", allocated)
        print("Checked-in students:", checked_in)

    def search_student(self):
        sid = input("Enter student ID: ").strip()
        if sid not in self.students:
            print("Student not found."); return
        s = self.students[sid]
        print("ID:", s.student_id, "| Name:", s.name, "| Phone:", s.phone)
        print("Address:", s.address, "| Room:", s.room_id or "Not Allocated")
        print("Status:", s.status)

    def menu(self):
        actions = {
            "1": self.add_room,
            "2": self.view_rooms,
            "3": self.register_student,
            "4": self.view_students,
            "5": self.check_availability,
            "6": self.allocate_room,
            "7": self.cancel_allocation,
            "8": self.check_in,
            "9": self.check_out,
            "10": self.generate_bill,
            "11": self.hostel_summary,
            "12": self.search_student,
        }
        while True:
            print("\n===== PG HOSTEL MANAGEMENT SYSTEM =====")
            print("1 Add Room")
            print("2 View Rooms")
            print("3 Register")
            print("4 View Students")
            print("5 Availability ")
            print(" 6 Allocate Room")
            print("7 Cancel ")
            print("8 Check-in")
            print("9 Check-out")
            print("10 Generate Bill")
            print("11 Hostel Summary")
            print("12 Search Student")
            print("13 Exit")
            if not self.load_ok:
                print("14 Backup and Reset/Recover Damaged Data")
            choice = input("Enter choice: ").strip()
            try:
                if choice == "13":
                    print("Thank you for using the system. No exit-time rewrite performed.")
                    break
                if choice == "14" and not self.load_ok:
                    self.recover_reset()
                elif choice in actions:
                    if not self.load_ok and choice not in {"2", "4", "5", "11", "12"}:
                        print("Operation blocked until data is recovered safely.")
                    else:
                        actions[choice]()
                else:
                    print("Choose a valid menu option.")
            except (ValueError, KeyError, OSError, RuntimeError, InvalidOperation) as error:
                print("Operation could not be completed:", error)


if __name__ == "__main__":
    HostelManagement().menu()