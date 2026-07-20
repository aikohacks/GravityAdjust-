# Gravity Adjustment Software

A professional desktop application for surveyors and geodesy professionals
to process gravity observation data collected during gravity surveys.

## Technology Stack
- Python 3
- PySide6 (GUI)
- Pandas (reading Excel/CSV)
- NumPy (matrix operations)
- SciPy (Least Squares adjustment)
- Matplotlib (graphs)
- openpyxl (Excel export)
- reportlab (PDF report generation)

## Project Structure
```
GravityAdjustmentSoftware/
    main.py                 Application entry point
    gui.py                  All GUI code (PySide6)
    core/
        adjustment.py        Least Squares adjustment logic
        drift.py             Drift correction logic
        statistics.py        Residuals & adjustment statistics
    reports/
        excel_export.py      Excel export (openpyxl)
        pdf_report.py        PDF report generation (reportlab)
    visualization/
        graphs.py             Matplotlib graph generation
    data/                    Sample / working data files
    outputs/                 Generated exports (Excel, PDF)
    assets/                  Icons, logos, static resources
    requirements.txt
    README.md
```

## Installation
```bash
pip install -r requirements.txt
```

## Running the Application
```bash
python main.py
```

## Development Phases

| Phase | Description                         | Status         |
|-------|--------------------------------------|----------------|
| 1     | Create the GUI                       | ✅ Complete    |
| 2     | Implement file import                | ⬜ Not started |
| 3     | Display imported data                | ⬜ Not started |
| 4     | Implement drift correction           | ⬜ Not started |
| 5     | Implement Least Squares adjustment   | ⬜ Not started |
| 6     | Display adjusted values              | ⬜ Not started |
| 7     | Generate graphs                      | ⬜ Not started |
| 8     | Export Excel                         | ⬜ Not started |
| 9     | Export PDF                           | ⬜ Not started |

## Phase 1 — Current Status

The main window is fully built and functional:
- Menu bar (File, Process, Graphs, Export, Help)
- Toolbar with quick-access actions
- Left-hand action panel (Open File, Drift Correction, Least Squares,
  Graph buttons, Export buttons)
- Data table (for imported observations) and Results table
  (for adjusted values / statistics), arranged in a resizable splitter
- Status bar showing current state / record count

All processing buttons are wired to placeholder slot methods in
`gui.py` that report which future phase will implement them, so the
interface is fully clickable and demonstrable today. No computational
or file-handling logic has been added yet — that begins in Phase 2.

## Architecture Notes
- `gui.py` contains **only** GUI code. It never performs calculations
  directly; it will call into `core/`, `reports/`, and `visualization/`
  as those modules are implemented.
- Each phase will be delivered as complete, working code before moving
  to the next phase, per the agreed development strategy.
