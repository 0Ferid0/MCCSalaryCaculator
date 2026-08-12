# Test Coverage Analysis — MCC Salary Calculator

## Summary

**Current automated test coverage is 0%.** The repository contains three files
(`app.py`, `salary_config.json`, `requirements.txt`). There are no test files, no test
runner configuration, no test dependencies, and no CI workflow.

This matters more than usual here because `app.py` computes payroll. Every defect in it
turns into a wrong number on someone's paycheck, and the output is an Excel file that a
human is likely to trust without re-deriving. While preparing this analysis I exercised
the calculation functions directly and found **one bug that silently pays teachers the
wrong amount**, plus several other confirmed defects described below. All of them would
be caught by a handful of ordinary unit tests.

---

## Blocker: the code is not currently testable

`app.py` is a single 746-line module that mixes two very different kinds of code:

| Lines | Content | Testable today |
|---|---|---|
| 13–415 | Pure logic: `load_config`, `save_config`, `get_workdays`, `get_custom_workdays`, `process_attendance`, `export_to_excel` | Only via source surgery |
| 417–746 | Streamlit UI, executed at module import time | No |

Because the UI runs at module scope, `import app` starts building a Streamlit page. A test
file cannot simply `from app import process_attendance` — the import has side effects and
requires a Streamlit runtime.

**Recommended first step, before writing any test:** move lines 13–415 into a
`payroll.py` (or a small `payroll/` package) that imports nothing from Streamlit, and have
`app.py` import from it. This is a pure move with no logic change, and it converts the most
valuable ~400 lines in the project from untestable to trivially testable.

A secondary point: `process_attendance` is one ~360-line function containing three nearly
identical department branches (admin at lines 82–170, teacher at 172–228, hybrid at
230–318). The three copies have already drifted apart — that drift is exactly the P0 bug
below. Extracting a per-day punch-pairing helper shared by all three branches would both
shrink the test matrix and prevent the copies from diverging again.

---

## Priority 1 — defects confirmed in the current code

These are not hypotheticals. Each was reproduced by calling the functions directly.

### 1.1 Teacher pay is computed from another employee's punch times (`app.py:196`)

The teacher branch reads `first_in` and `last_out` at line 196, but **never assigns them** —
the assignment exists only in the admin branch (line 113) and hybrid branch (line 261).

Two possible outcomes, both bad:

- If a teacher is the first employee processed, the function raises
  `UnboundLocalError: cannot access local variable 'last_out'` and the whole payroll run
  fails.
- If any admin or hybrid employee was processed first, Python's function-scoped locals mean
  the teacher silently inherits **that other person's** check-in/check-out times.

Reproduced: an admin working 10:00–16:00 followed by a teacher working 09:00–13:00 (4 hours)
produced a teacher record of **6.0 hours, paid 150.00 instead of 100.00**. No error, no
warning — the wrong number simply lands in the Excel export.

Since `groupby('Staff Name')` sorts alphabetically, which of the two failures you get
depends on employee names, which is why this can survive in production.

**Tests needed:** one test per department that processes that department *in isolation*,
asserting hours and pay. A single-teacher-only fixture would have caught this immediately.

### 1.2 A date range spanning two months prices every day at the first month's rate

`process_attendance` derives the month from `start_date` only (lines 63–64) and uses it for
every workday calculation, but the UI lets the user pick an arbitrary range (lines 427–431).

Reproduced: for a June 1 – July 31 range, June has 21 working days and July has 23, but both
the June and the July day were paid at the June daily rate (57.14 instead of 52.17 for July).

**Tests needed:** ranges that cross a month boundary, a partial month, a single day, and a
range with `end_date < start_date`. Also worth deciding explicitly whether cross-month ranges
should be supported at all, or rejected with a clear message.

### 1.3 Employees with an unrecognised department disappear silently

The three `if/elif` branches match exact strings, and there is no `else`. Any employee whose
department does not match is dropped with no daily row, no error row, and no message.

Reproduced: an employee with `"ადმინისტრცია"` (one character off) produced 0 daily rows,
0 error rows, and `error_msg = None` — they simply vanish from the payroll.

This is aggravated by an existing inconsistency in the department names themselves:
`"ადმინისტრაცია"` versus `"ადმნისტრაცია და მასწავლებელი"` (the second is missing an `ი`).
A typo in the uploaded file means someone does not get paid, and nothing on screen says so.

**Tests needed:** an unknown department must surface in the errors table. Also assert that
every unique `Staff Name` in the input appears in either the monthly report or the errors
report — a good invariant test that catches whole classes of silent-drop bugs.

### 1.4 Absent days are free for hybrid employees but not for admin employees

The two salary models handle absence in opposite ways, and only one of them is defensible:

- **Admin** accrues pay per recorded day, so an absent day simply earns nothing.
- **Hybrid** starts from the full monthly salary and subtracts only the deficits of days
  that *have punch records*. A day with no records at all generates no row, therefore no
  deficit, therefore no deduction.

Reproduced: a hybrid employee on a 1200 monthly salary who showed up for exactly one day out
of 21 working days in June was paid **the full 1200**. The same employee leaving after one
hour on that single day was paid 1152.38. An admin with identical attendance was paid 57.14.

**Tests needed:** for each department, a fixture with several absent working days, asserting
the expected monthly total. This requires first deciding what the intended policy is —
the test is the right place to pin that decision down.

### 1.5 `export_to_excel` crashes when there is nothing to export

Every `to_excel` call is guarded by a `not empty` check, so when all four frames are empty
the workbook has no sheets and `openpyxl` raises `IndexError: At least one sheet must be
visible`.

The UI mostly avoids this via the `if not df_monthly.empty or not df_errors.empty` guard at
line 729, but the function itself is unsafe and the guard does not cover all paths.

**Tests needed:** all-empty input, and one test per combination of populated/empty frames,
asserting the resulting sheet names.

---

## Priority 2 — untested logic likely to break next

### 2.1 Punch pairing and status parsing

The pairing rule is `len(day_df) % 2 != 0 or check_ins.empty or check_outs.empty`, then
first-in to last-out. Confirmed behaviours that no test currently pins down:

- **A mid-day break is paid.** Four punches (10:00 in, 12:00 out, 14:00 in, 16:00 out) are
  billed as a continuous 6.0 hours — the 2-hour gap is paid and no error is raised.
- **Two check-ins and no check-out** passes the even-count test but is caught by the
  `check_outs.empty` condition. Worth locking in with a test.
- **Status matching is exact after strip/lower.** `" CHECK IN "` works, but `"check-out"`
  with a hyphen is not recognised and the day is voided.
- Odd punch counts, duplicate identical timestamps, and check-out-before-check-in each take
  a different path through the code.

**Tests needed:** a table-driven test over punch sequences, asserting hours, deficit,
overtime, pay, and whether an error row is produced.

### 2.2 Overtime, deficit, and the hardcoded 10:00–16:00 window

The standard workday is hardcoded at lines 124–125 and the 6-hour day is hardcoded in
several places (`6.0` appears as a literal at lines 108, 135, 142, 156, 256, 283, 290, 304,
379). Untested boundary cases:

- Arriving before 10:00 earns nothing extra; leaving after 16:00 counts as overtime — but
  overtime is recorded and never actually paid for admins.
- **Overnight shifts are badly wrong.** A 22:00–23:30 shift (1.5 hours) was scored as
  **7.5 hours of overtime and 6.0 hours of deficit simultaneously**, because
  `standard_end` is derived from the check-in date at 16:00, which is already in the past.
- A non-working day yields zero pay regardless of hours worked.

**Tests needed:** parametrised cases across the 10:00/16:00 boundaries, plus an explicit
decision and test for overnight and midnight-crossing shifts.

### 2.3 Teacher monthly quota capping

Lines 351–367 recompute teacher pay monthly: capped at the quota, deficit below it, overtime
above it, and an unquota'd teacher (`monthly_req == 0`) is paid uncapped. Four distinct
branches, zero tests. Note this silently discards the daily salary figures computed earlier
in the run, which is easy to break during a refactor.

### 2.4 Workday counting

`get_custom_workdays` is the divisor for every admin and hybrid daily rate, so an error here
scales every paycheck.

- A duplicated entry in the working-days list double counts: `[0, 0]` returns 10 for June
  2025 instead of 5. The UI derives this list from checkboxes so duplicates are unlikely
  today, but it is loaded from a user-editable JSON file.
- An empty working-days list returns 0, which the `total_workdays > 0` guard turns into a
  0.0 daily rate — an employee configured with no working days is paid nothing, silently.
- Months starting on a Sunday, leap Februaries, and December/January need coverage.
- `get_workdays` (line 26) is **dead code** — nothing calls it. Either delete it or use it.

### 2.5 Config load/save

- `load_config` (lines 13–20) swallows every exception with a bare `except: pass`, so a
  corrupted config silently resets everyone's salary to the defaults. This deserves a test
  asserting that malformed JSON is at minimum surfaced to the user.
- `save_config` has no error handling — a read-only filesystem or a permissions problem
  raises straight through the Streamlit callback.
- The config path is relative to the working directory, so behaviour depends on where the
  app was launched from.
- **The committed config has already drifted from the code**: `salary_config.json` contains
  `teacher_rates` (30 per-teacher rates) and `teacher_normal_hours`, and `app.py` reads
  neither — it uses a single global `teacher_rate`. Either those per-teacher rates are meant
  to be applied and are being ignored, or they are stale. A round-trip test plus a schema
  test would have flagged this.

---

## Priority 3 — smaller gaps

- **Week numbering is not year-qualified.** `df['Date Time'].dt.isocalendar().week` keeps the
  week number and drops the year, so 2025-W02 and 2026-W02 merge into a single weekly row
  (reproduced). Only reachable on ranges longer than a year, but the weekly table is also
  ambiguous to read without the year.
- **File ingestion** (lines 460–475) — CSV vs XLSX, the `N/A`/`NaN`/`None` name cleaning, the
  `ID` column drop, and missing-required-column handling are all untested. Note the cleaning
  at line 470 does not catch names that are only whitespace variants, and the missing-column
  check inside `process_attendance` (lines 50–53) duplicates the UI's check at line 467 with
  different columns.
- **Department filter** (lines 686–701) — "ადმინისტრაცია" and "მასწავლებელი" both include
  hybrid employees, so a hybrid person appears under both filters. Intentional, but should be
  pinned by a test.
- **Rounding** — values are rounded to 2 decimals only at the end (lines 396–400), so weekly
  and monthly sums are computed on unrounded values and may not equal the sum of the rounded
  daily rows shown to the user. Decide whether that reconciliation matters and test it.

---

## Suggested approach

**Step 1 — make it testable.** Move the logic functions out of `app.py` into `payroll.py`.
No behaviour change.

**Step 2 — add the harness.** Add `pytest` to a `requirements-dev.txt` and pin the runtime
dependencies in `requirements.txt` (currently `streamlit`, `pandas`, `openpyxl` are all
unpinned — this analysis ran against pandas 3.0.5, and the code's behaviour on older or newer
pandas is unverified).

```
tests/
  conftest.py            # DataFrame builders for punch records
  test_workdays.py       # get_custom_workdays edge cases
  test_config.py         # load/save round-trip, malformed JSON, schema drift
  test_admin.py          # accrual model, deficit, overtime, non-working days
  test_teacher.py        # hourly model, quota capping  (starts by catching 1.1)
  test_hybrid.py         # deduction model, manual teaching hours
  test_process_shape.py  # cross-cutting invariants: no employee silently dropped,
                         # errors table populated, daily/weekly/monthly reconcile
  test_export.py         # sheet names, empty frames
```

**Step 3 — write the P1 tests first.** Each of §1.1–§1.5 is a few lines of DataFrame setup
and one assertion, and each pins down a bug that exists right now.

**Step 4 — add CI.** A GitHub Actions workflow running `pytest` on push would keep this from
regressing.

A reasonable initial target is high statement coverage on `payroll.py` specifically; the
Streamlit UI layer is lower value to test and much more expensive to cover.

### Note on test fixtures

`salary_config.json` is committed with what appear to be real employee names and real
salary figures. Test fixtures should use synthetic names and round numbers rather than
copying from it — and it is worth a separate conversation about whether that file belongs in
version control at all.
