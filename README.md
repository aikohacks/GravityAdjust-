# Gravity Adjustment Software

A desktop application (PySide6) for processing relative gravity survey field observations — importing raw readings, correcting for instrument drift, visualizing results, and exporting professional Excel/PDF reports.

## Status

| Phase | Feature | Status |
|---|---|---|
| 1 | GUI shell (window, menus, toolbar, tables) |  Done |
| 2 | File import (CSV/XLSX) |  Done |
| 3 | Display imported data |  Done |
| 4 | Drift correction (Circuit Drift) |  Done |
| 5 | Least Squares Adjustment (config dialog + two weighting modes) |  Done  |
| 6 | Statistics |  Not started — pending domain input |
| 7 | Graphs |  Done |
| 8 | Excel export |  Done |
| 9 | PDF export |  Done |
| — | Line Drift (multi-day) |  Built and tested, hidden — superseded by the Phase 5 network-adjustment approach |

## Features

- **Import** gravity survey observations from CSV or Excel (`.csv`, `.xlsx`, `.xls`).
- **Drift correction** using the circuit-drift method: a closed loop of station visits, starting and ending at the same base station, anchored on a manually-entered known G value. Handles real-world field data robustly:
  - Fuzzy column header matching (`Station ID`, `Site`, `Gravity Reading (mGal)`, etc. — no exact header format required)
  - Variable numbers of sub-readings per station stop, and variable numbers of stops per circuit
  - Time entered as `H:MM` (or legacy `H.MM`), including automatic correction for 12-hour clock rollover mid-circuit
- **Least Squares Adjustment** (Phase 5): builds a gravity network from the drift-corrected, consecutive-station Δg observations and solves the weighted normal equations `X = (AᵀPA)⁻¹AᵀPL`. A configuration dialog lets the user choose the weighting scheme before the math runs:
  - **Approach A — Partial Constraints (Weighted)**: base stations stay in the solve as weighted pseudo-observations (their sigma comes from the Base Station Reference file's Sigma column, with a manual fallback).
  - **Approach B — Hard-Fixed (Zero Variance)**: base station values are exact constants, substituted out of the normal equations; only non-fixed stations are solved.
  - **Relative-tie sigma**: either one global manual sigma for every Δg observation, or each tie's sigma read from the propagated `MeanSigma` column produced by Drift Correction (round-tripped through "Export for Least Squares").
  - Output: an Adjusted Values table (one row per station), a Residuals table (one row per observation), live residual graphs, and diagnostic closure checks for ties between two fixed stations in Approach B.
- **Graphs**: Drift Curve, Raw vs Adjusted, Residual Plot, and Residual Histogram, each in its own tab with pan/zoom/save controls.
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
│   ├── adjustment.py          # Least Squares Adjustment (Phase 5)
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
- **Least Squares weighting** follows the design decisions in `core/adjustment.py`: the network is anchored on base-station reference values (weighted in Approach A, hard-fixed in Approach B), and the observations are drift-corrected consecutive-station Δg values, one per tie, in visit order. Per-observation sigma comes from either a user-supplied global value or the `MeanSigma` column emitted by `core/drift.py` (standard error of each visit's mean reading). With the `MeanSigma` source, each tie's sigma is the rigorous error propagation of its two endpoint visits: σ<sub>Δg</sub> = √(σ<sub>from</sub>² + σ<sub>to</sub>²), since a Δg difference combines the variance of both visit means.

## Next steps

Phase 5 is complete: the config dialog (Approach A / Approach B, base sigma, and manual vs `MeanSigma` tie weighting) is wired through `gui.py` into `core/adjustment.py`'s `build_network(mode, relative_sigma_source, manual_relative_sigma, manual_base_sigma)` + `solve()`, with closure checks surfaced for hard-fixed ties between two base stations.

Phase 6 (Statistics) is next and needs confirmation of which statistics are required (RMS, variance factor, loop misclosure, chi-square, etc.).
