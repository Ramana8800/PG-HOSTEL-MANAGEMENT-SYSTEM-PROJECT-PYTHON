# PG Hostel Management System (Python)

A command-line hostel management application built with Python. It manages rooms, student registrations, room allocation, check-in/check-out, billing, JSON-based data storage, backups, and recovery.

## Project structure

```text
Hostel-Management-Using-Python/
├── main.py                 # Application entry point and operations
├── test_main.py            # Automated unit and workflow tests
├── hostel_data.txt         # Created automatically; JSON data despite .txt extension
├── hostel_data.txt.bak     # Previous successfully saved data snapshot
├── hostel_data.txt.recovery.bak  # Preserved file during recovery, when applicable
└── bills/
    └── bill_<student_id>.txt     # Appended bill records for each student
```

`hostel_data.txt`, backup files, and `bills/` are created beside `main.py` as needed. Do not commit real student personal information to a public repository.

## Features

- Add and view Single, Double, and Triple rooms.
- Register students and validate Indian 10-digit mobile numbers.
- View room availability and occupied/available beds.
- Allocate rooms, cancel eligible allocations, check students in, and check them out.
- Support returning students. A completed stay is copied into `stay_history` before the current stay dates are cleared for a new allocation.
- Generate bills with room fees, additional charges, payment, balance, and payment status.
- Display hostel occupancy and student summaries; search student records.
- Validate loaded data and room/student relationships before accepting it.

## Room types and default monthly fees

| Room type | Capacity | Default fee per month |
|---|---:|---:|
| Single | 1 student | Rs. 8,000 |
| Double | 2 students | Rs. 6,000 |
| Triple | 3 students | Rs. 5,000 |

A custom monthly fee can be entered while adding a room. Enter `0` to use the default fee.

## Billing

The bill total is calculated as:

`(monthly room fee × number of months) + food charges + electricity charges + maintenance charges`

The application asks for the amount paid and records the remaining balance and `PAID` or `PENDING` status. Bills are appended to `bills/bill_<student_id>.txt`, so earlier bill entries remain in the file.

## Data storage, backups, and recovery

- Student and room data is stored in `hostel_data.txt` in JSON format.
- Before replacing an existing data file, the application copies it to `hostel_data.txt.bak`.
- Saves are written to a temporary file, flushed to disk, and atomically replaced. A failed save does not publish the proposed in-memory state.
- If existing data cannot be loaded or validated, normal write operations are blocked. The original file is preserved.
- In this damaged-data state, use menu option **14 – Backup and Reset/Recover Damaged Data**. Confirm by typing `RESET`. The damaged/original file is copied to `hostel_data.txt.recovery.bak` before an empty database is written.
- Keep independent copies of the data file, backups, and bills. A backup beside the application is not a substitute for an external backup.

## Run the application

Use Python 3.9 or later. No third-party packages are required.

From the project root (the folder containing `main.py`):

```bash
python main.py
```

## Run tests

From the same folder:

```bash
python -m unittest -v
```

The tests cover validation, billing, safe-save behaviour, and the full returning-student workflow using the actual allocation, check-in, and check-out methods.

## Migration from the previous Day_7 layout

If you are updating an existing installation that used the old `Day_7` folder:

1. Stop the old application before copying files.
2. Make a separate safety copy of the entire old `Day_7` folder.
3. Copy `Day_7/hostel_data.txt` into the new project root, beside the new `main.py`.
4. Copy the old backup file(s), including `hostel_data.txt.bak` if present, into that same new root. Preserve their filenames.
5. Copy the old `Day_7/bills/` directory into the new project root so existing bill files remain under `bills/`.
6. Do not overwrite or discard any existing data or backup without first comparing and preserving it.
7. Run `python main.py`. The application validates the migrated data when it loads. If validation fails, stop and preserve the files; use the documented recovery process only after making another copy.

The new loader treats a missing `stay_history` field as an empty history, so existing student records from the previous format remain compatible. New completed stays are recorded in `stay_history` on subsequent allocations.
"# PG-HOSTEL-MANAGEMENT-SYSTEM-PROJECT-PYTHON" 
"# PG-HOSTEL-MANAGEMENT-SYSTEM-PROJECT-PYTHON" 
