"""
make_download.py
----------------
Packages the clean Least-Squares input workbooks (built by
build_nicky_input.py) into downloadable files:

    Nicky_Clean_Input.xlsx      - everything in one workbook
        Sheet "Ties"            - full station list (relative observations)
        Sheet "Base Reference"  - absolute known-G anchors
        Sheet "Notes"           - documentation
    Nicky_Relative_Input.xlsx   - RELATIVE values only (one row per station,
                                  DeltaG tie into that station) -- the day
                                  file for the adjustment.
    Nicky_Absolute_Input.xlsx   - ABSOLUTE values only (Station, KnownG,
                                  Sigma) -- the base station reference file
                                  for the adjustment.

Run:  python3 make_download.py
"""
import os

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
TIES = os.path.join(ROOT, "data", "nicky_survey_ties_clean.xlsx")
BASE = os.path.join(ROOT, "data", "nicky_base_reference_clean.xlsx")
OUT = os.path.join(ROOT, "Nicky_Clean_Input.xlsx")
REL = os.path.join(ROOT, "Nicky_Relative_Input.xlsx")
ABS = os.path.join(ROOT, "Nicky_Absolute_Input.xlsx")

NOTES = [
    ("Nicky NH-61 Gravity Survey - Clean Least-Squares Input", ""),
    ("", ""),
    ("DELIVERABLES", ""),
    ("Nicky_Relative_Input.xlsx", "RELATIVE observations: Station + DeltaG (tie into each station)."),
    ("Nicky_Absolute_Input.xlsx", "ABSOLUTE values: Station + KnownG + Sigma (base/control anchors)."),
    ("Nicky_Clean_Input.xlsx", "Both above + documentation, in one workbook."),
    ("", ""),
    ("RELATIVE FILE - COLUMN GUIDE", ""),
    ("Station", "BM number (START = the survey base at the top of the sheet)."),
    ("DeltaG (mGal)", "Observed tie INTO this station. Blank means 'no tie recorded'."),
    ("MeanDistKm", "Mean distance from the previous station (km), where available."),
    ("CumulativeG (mGal)", "Running sum of DeltaG from the base (validated against the sheet)."),
    ("FinalAdjustedG (mGal)", "Sheet's official final adjusted value (stations 240..109)."),
    ("", ""),
    ("MISSING LEGS - DERIVED FROM THE CUMULATIVE COLUMN", ""),
    ("leg 57 -> 55 (BM 55, first visit)", "DeltaG = CumG(55) - CumG(57) = 978.427265 - 978.427244 = +0.000021 mGal"),
    ("leg 9 -> 3 (BM 3)", "DeltaG = CumG(3) - CumG(9) = 978.402872 - 978.402846 = +0.000026 mGal"),
    ("Note", "Without the 57->55 leg the tail (BM 55..9) is an unanchored sub-network and the"),
    ("", "least-squares system is singular (rank-deficient). The derived legs restore full rank."),
    ("", ""),
    ("ABSOLUTE FILE - ANCHORS", ""),
    ("START", "KnownG = 978.432255 mGal, Sigma = 0.010 (survey base, red cell at top of sheet)."),
    ("Controls", "228, 195, 160, 150, 109 (GCP/GTS points). KnownG currently = the sheet's official"),
    ("", "final adjusted value as a placeholder; replace with each control's PUBLISHED absolute"),
    ("", "value for a fully independent adjustment."),
    ("", ""),
    ("NETWORK SUMMARY (validated)", ""),
    ("Rows", "96 (incl. START anchor + closing leg back to START)."),
    ("Loop misclosure", "7.581 uGal (distributed as residuals by the adjustment)."),
    ("Rank / dof", "Full rank; obs=100, unknowns=94, dof=6 (partial mode)."),
    ("vs sheet's official values", "52 stations compared, RMS 0.001 uGal, max 0.001 uGal (partial mode);"),
    ("", "47 stations, RMS 0.000 uGal (hard-fixed mode)."),
    ("", ""),
    ("HOW TO USE", ""),
    ("1", "In the app, run 'Least Squares Adjustment'."),
    ("2", "Load Nicky_Relative_Input.xlsx as the day/survey file and"),
    ("3", "Nicky_Absolute_Input.xlsx as the base station reference file."),
    ("4", "Pick a weighting scheme and run - results match the survey sheet's final values."),
]


def main():
    ties = pd.read_excel(TIES, sheet_name="Ties")
    base = pd.read_excel(BASE, sheet_name="Base Reference")

    # 1. Combined workbook (everything, self-documented).
    with pd.ExcelWriter(OUT, engine="openpyxl") as writer:
        ties.to_excel(writer, sheet_name="Ties", index=False)
        base.to_excel(writer, sheet_name="Base Reference", index=False)
        pd.DataFrame(NOTES, columns=["Item", "Detail"]).to_excel(
            writer, sheet_name="Notes", index=False, header=False
        )

    # 2. Separate RELATIVE values file (day/ties input).
    with pd.ExcelWriter(REL, engine="openpyxl") as writer:
        ties.to_excel(writer, sheet_name="Ties", index=False)

    # 3. Separate ABSOLUTE values file (base station reference input).
    with pd.ExcelWriter(ABS, engine="openpyxl") as writer:
        base.to_excel(writer, sheet_name="Base Reference", index=False)

    for path, label in ((OUT, "combined"), (REL, "relative"), (ABS, "absolute")):
        back = pd.ExcelFile(path)
        sheets = {s: len(pd.read_excel(path, sheet_name=s)) for s in back.sheet_names}
        print(f"Wrote {os.path.basename(path):<28} [{label}] sheets={sheets} "
              f"({os.path.getsize(path) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
