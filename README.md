# Gravity Adjustment Software

A desktop application (PySide6) for processing relative gravity survey field observations — importing raw readings, correcting for instrument drift, visualizing results, and exporting professional Excel/PDF reports.

## Status

| Phase | Feature | Status |
|---|---|---|
| 1 | GUI shell (window, menus, toolbar, tables) | ✅ Done |
| 2 | File import (CSV/XLSX) | ✅ Done |
| 3 | Display imported data | ✅ Done |
| 4 | Drift correction (Circuit Drift) | ✅ Done |
| 5 | Least Squares Adjustment | 🔒 Not started — pending domain input |
| 6 | Statistics | 🔒 Not started — pending domain input |
| 7 | Graphs | ✅ Done |
| 8 | Excel export | ✅ Done |
| 9 | PDF export | ✅ Done |
| — | Line Drift (multi-day) | ⏸️ Built and tested, hidden — superseded by the Phase 5 network-adjustment approach |

## Features

- **Import** gravity survey observations from CSV or Excel (`.csv`, `.xlsx`, `.xls`).
- **Drift correction** using the circuit-drift method: a closed loop of station visits, starting and ending at the same base station, anchored on a manually-entered known G value. Handles real-world field data robustly:
  - Fuzzy column header matching (`Station ID`, `Site`, `Gravity Reading (mGal)`, etc. — no exact header format required)
  - Variable numbers of sub-readings per station stop, and variable numbers of stops per circuit
  - Time entered as `H:MM` (or legacy `H.MM`), including automatic correction for 12-hour clock rollover mid-circuit
- **Graphs**: Drift Curve, Raw vs Adjusted, Residual Plot, and Residual Histogram, each in its own tab with pan/zoom/save controls. (Residual graphs will populate once Phase 5 is implemented.)
- **Excel export**: a formatted `.xlsx` workbook with your imported observations and drift-corrected results, including a summary of total drift/time/rate.
- **PDF export**: a formatted, paginated report combining the same data tables plus all 4 graphs as embedded images.

## Installation

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

## Running the app

```bash
python main.py
```

## Project structure

```
gravity_adjustment_software/
├── main.py                  # Entry point
├── gui.py                   # PySide6 main window (all UI code lives here)
├── requirements.txt
├── core/
│   ├── data_loader.py        # CSV/Excel import
│   ├── drift.py               # Circuit Drift correction (Phase 4)
│   ├── line_drift.py          # Multi-day Line Drift (built, currently hidden in the GUI)
│   ├── adjustment.py          # Least Squares Adjustment (Phase 5 — stub)
│   └── statistics.py          # Statistics (Phase 6 — stub)
├── reports/
│   ├── excel_export.py        # Excel export (Phase 8)
│   └── pdf_report.py          # PDF export (Phase 9)
├── visualization/
│   └── graphs.py               # Matplotlib plotting functions (Phase 7)
├── data/                       # Sample/demo CSVs
└── outputs/                    # Default export destination
```

`gui.py` contains only PySide6 UI code (widgets, layout, signal/slot wiring) — all calculations live in `core/`, all report generation in `reports/`, and all plotting in `visualization/`. This separation keeps the math independently testable from the interface.

## Known design decisions & assumptions

- **Circuit Drift** assumes a closed loop: the survey starts and ends at the same base station. A "station visit" is any contiguous run of rows sharing the same Station ID — no fixed count of sub-readings is assumed.
- **12-hour clock handling**: field data is recorded without an AM/PM marker. If a circuit's readings cross the 12:00 mark, the app automatically detects and corrects for the rollover so elapsed time stays continuous.
- **Line Drift** (`core/line_drift.py`) implements a day-by-day anchor hand-off method for multi-day survey lines, validated against a mentor-provided worked example. It's currently hidden in the GUI (`LINE_DRIFT_UI_ENABLED = False` in `gui.py`) because the project has since moved toward a global least-squares network adjustment (Phase 5) instead, which is expected to supersede this approach. The code is kept intact in case a day-by-day diagnostic view is still useful later.
- **Excel/PDF exports** are values-only report snapshots of already-computed results, not live editable models — cells/tables don't recalculate if source data changes after export.

## Next steps

Phase 5 (Least Squares Adjustment) needs three things confirmed before implementation:
1. Adjustment model — is the network anchored on a fixed/known station, or free-net?
2. Weighting scheme — equal weighting, or weighted by precision/reading count? Are repeat observations across days combined or kept separate?
3. Observation equations — confirming that drift-corrected consecutive-station Δg values are the observations feeding the adjustment.

Phase 6 (Statistics) needs confirmation of which statistics are required (RMS, variance factor, loop misclosure, chi-square, etc.).