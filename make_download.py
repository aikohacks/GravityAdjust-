"""
make_download.py
----------------
Packages the two clean Least-Squares input workbooks
(data/nicky_survey_ties_clean.xlsx, data/nicky_base_reference_clean.xlsx)
into a single, self-documenting download file:

    Nicky_Clean_Input.xlsx
        Sheet "Ties"           - full station list, one row per station
        Sheet "Base Reference" - anchor + 5 GCP/GTS controls
        Sheet "Notes"          - column guide, missing-leg derivation,
                                 anchors, and usage instructions

Run:  python3 make_download.py
"""
import os

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
TIES = os.path.join(ROOT, "data", "nicky_survey_ties_clean.xlsx")
BASE = os.path.join(ROOT, "data", "nicky_base_reference_clean.xlsx")
OUT = os.path.join(ROOT, "Nicky_Clean_Input.xlsx")

NOTES = [
    ("Nicky NH-61 Gravity Survey - Clean Least-Squares Input", ""),
    ("", ""),
    ("SHEETS", ""),
    ("Ties", "One row per station in survey order. DeltaG(row i) = g(i) - g(i-1)."),
    ("Base Reference", "Absolute anchors for the network (START + 5 GCP/GTS controls)."),
    ("Notes", "This sheet."),
    ("", ""),
    ("TIES - COLUMN GUIDE", ""),
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
    ("ANCHORS", ""),
    ("START", "KnownG = 978.432255 mGal, Sigma = 0.010 (survey base, red cell at top of sheet)."),
    ("Controls", "228, 195, 160, 150, 109 (GCP/GTS points). KnownG currently = the sheet's official"),
    ("", "final adjusted value as a placeholder; replace with each control's PUBLISHED absolute"),
    ("", "value for a fully independent adjustment."),
    ("", ""),
    ("STATION 2", "Occupied but no DeltaG recorded in the sheet; kept as the 'from' station of tie 2->1."),
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
    ("2", "Load 'Ties' as the day/survey file and 'Base Reference' as the base station file."),
    ("3", "Pick a weighting scheme and run - results match the survey sheet's final values."),
]


def main():
    ties = pd.read_excel(TIES, sheet_name="Ties")
    base = pd.read_excel(BASE, sheet_name="Base Reference")

    with pd.ExcelWriter(OUT, engine="openpyxl") as writer:
        ties.to_excel(writer, sheet_name="Ties", index=False)
        base.to_excel(writer, sheet_name="Base Reference", index=False)
        pd.DataFrame(NOTES, columns=["Item", "Detail"]).to_excel(
            writer, sheet_name="Notes", index=False, header=False
        )

    # sanity check: read it back
    back = pd.ExcelFile(OUT)
    print(f"Wrote {OUT}")
    print("Sheets:", back.sheet_names)
    print("Ties rows:", len(pd.read_excel(OUT, sheet_name='Ties')))
    print("Base rows:", len(pd.read_excel(OUT, sheet_name='Base Reference')))
    print("Size: %.1f KB" % (os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
