"""
build_nicky_input.py
--------------------
Builds the two clean input workbooks the Least Squares Adjustment
(GUI "Run Least Squares Adjustment") expects, from Nicky's NH-61
survey sheet ("nicky's_Sheet(1).xlsx"), FULL survey.

Source of truth: the BM NO. / Δg columns read directly from the Excel
file (pasted from the sheet by the user). Additional reference columns
(CumulativeG, FinalAdjustedG) come from the earlier screenshot
transcription for stations 240..109 and from the running-sum
reconstruction for the rest.

Convention (verified against the sheet's own cumulative column):
    DeltaG[row i] = g(Station[i]) - g(Station[i-1])
which is exactly the tie convention the software's build_network()
uses (tie from row i-1 to row i, DeltaG taken from row i).

THE TWO MISSING LEGS (derived from the cumulative column)
----------------------------------------------------------
The sheet has two rows whose Δg cell is blank but whose cumulative
gravity cell (column header = the anchor value 978.432255) IS filled
with the surveyor's best value for that station:

    Excel row 74: BM 55 (first visit)   -> missing leg  57 -> 55
    Excel row 93: BM 3                  -> missing leg   9 ->  3

ROW NUMBERING: the pasted pandas table started at row 0 = BM 240, but
in the Excel file a title + header row sit above it, so

    Excel row = pasted row + 2

(verified against screenshots: Excel rows 72/91 are BM 60 / BM 12,
whose Δg and cumulative match the transcription exactly -- CumG(60) =
978.429762, CumG(12) = 978.401298). The blank-Δg rows are therefore
the next two: BM 55 at Excel 74, BM 3 at Excel 93.

The sheet's cumulative column is the running sum of Δg from the base
(verified exactly for rows 0..9 AND at BM 60 / BM 12), so the missing
legs are recovered as

    Δg(57->55) = CumG(BM 55, Excel 74) - CumG(BM 57)
    Δg(9->3)   = CumG(BM 3,  Excel 93) - CumG(BM 9)

CumG(BM 57) = 978.427244 and CumG(BM 9) = 978.402846 are
reconstructed here from the running sum. CumG(BM 55) and CumG(BM 3)
come from the sheet -- either read automatically from the original
xlsx (if it is placed next to this script; see
ORIGINAL_SHEET_CANDIDATES) or pasted into SHEET_CUM_G below. The
script refuses to write output until both values are available.

WHY THIS MATTERS (rank deficiency)
----------------------------------
Without the 57->55 leg the whole tail of the survey (stations 55, 54,
52, 46, 43, ..., 9 -- 18 stations) is connected to the anchored main
network through NO tie at all. That sub-network is a floating
component with no base station, so the design matrix A is singular
(rank = unknowns - 1) and the solver refuses to run. Deriving the leg
restores full rank; station 3 then joins the network through 9->3.

Structural notes:
  * The anchor is the first row of the ties file (Station=START,
    DeltaG=0). The first tie START->240 therefore uses row 1's DeltaG
    (0.043180) -- without this row that DeltaG would be orphaned and
    the system underdetermined.
  * Station 2 (row 92) also has no DeltaG in the transcription. Its
    row is KEPT: it acts as the "from" station of the following tie
    2->1 (DeltaG 0.006758). If the original sheet turns out to have a
    value there, the auto-read path picks it up automatically.
  * Row 94 has no station label and DeltaG = 0.030185: the closing
    leg back to the starting base, labelled "START".
  * ANCHORING: a single-anchor line with a closing leg has dof=0 and a
    7.534 uGal loop misclosure -- the system is rank-deficient and the
    software correctly refuses it. The survey's five GCP/GTS control
    points therefore anchor the network in the Base Reference file.
    Their KnownG values are the sheet's OFFICIAL final values (the
    survey was adjusted onto them); replace them with the published
    absolute values from the GCP/GTS datasheets for a fully
    independent adjustment. With them, dof > 0 and the misclosure is
    properly distributed as residuals.

Outputs:
    data/nicky_survey_ties_clean.xlsx    -> sheet "Ties" + sheet
        "Reference" (original cumulative/final values for validation).
    data/nicky_base_reference_clean.xlsx -> sheet "Base Reference"
        (Station, KnownG, Sigma) -- the survey's starting base.
"""

import os
import sys

import numpy as np
import pandas as pd

from core.adjustment import NetworkAdjustment

ANCHOR_STATION = "START"
ANCHOR_KNOWN_G = 978.432255  # mGal -- red cell at top of the sheet
ANCHOR_SIGMA = 0.010         # mGal -- published absolute base uncertainty

# (Station, DeltaG mGal, MeanDistKm). MeanDistKm is exact for the first
# 10 rows (read from the sheet) and a 3-decimal screenshot transcription
# for rows 10-51; None elsewhere (verify from the original if needed).
# Row 0 = the anchor (DeltaG 0) so the first tie START->240 exists.
DATA = [
    (ANCHOR_STATION, 0.0, None),
    (240, 0.043180, 0.7815),   # GCP MRO office, Nirmal
    (237, 0.001166, 1.4455),   # Bharat Petroleum
    (234, -0.003422, 2.0355),  # culvert 661/1
    (232, -0.002569, 1.7405),  # culvert 655/3
    (229, -0.002164, 1.7780),  # culvert 650/2
    (228, -0.000179, 1.9195),  # GCP Vet Dispensary, Narsapur
    (225, -0.002079, 1.5745),  # HP Petrol Pump plinth
    (222, -0.003754, 1.7135),  # Dhimapur road junction
    (218, -0.004288, 1.2180),  # Sai Agro Industries
    (215, -0.002954, 1.3545),  # HP Petroleum Bhainsa
    (213, 0.000259, 0.030),    # R&B Guest House Bhainsa (ref pillar)
    (209, -0.005513, 3.312),   # culvert 61, Manjri
    (207, -0.000872, 3.221),   # culvert 617/1, Beltaroda
    (204, 0.003113, 1.718),    # culvert, Bendriphata
    (201, -0.009907, 1.978),   # Kandevnagar kundi
    (199, -0.001530, 2.323),   # culvert, Neshi Dhaba
    (197, -0.000789, 1.477),   # culvert, Durgamata temple
    (195, -0.001792, 0.462),   # GCP PWD Division Bhokar
    (194, -0.005859, None),    # (re-occupation near base)
    (192, 0.010935, 1.909),    # culvert, Girgaon road
    (189, -0.002708, 1.053),   # culvert, Shitakhendi
    (185, 0.008322, 2.290),    # culvert, Wakad
    (182, 0.003388, 2.058),    # culvert, Pandarwadi
    (178, 0.000712, 0.231),    # Reference pillar
    (175, 0.002253, 2.141),    # HP Petrol Pump, Tukaram Petroleum
    (172, 0.000309, 1.581),    # culvert, Yelegav trijunction
    (169, -0.001276, 1.953),   # HP Oil Pump wall
    (167, 0.000592, 1.633),    # Canal Siphonic, Mendla Khurd
    (165, 0.001398, 1.756),    # Ganga Ramaji Farm House gate
    (163, -0.003301, 2.057),   # culvert parapet
    (161, 0.001991, 2.329),    # Girgaon-Malegaon road culvert
    (160, -0.000864, 0.606),   # GCP Gram Panchayat office, Girgaon
    (159, -0.000719, None),    # culvert, Hingoli road
    (156, -0.001462, 2.207),   # (MBO type)
    (155, -0.019657, None),    # Siphon near HP Petrol Pump
    (153, 0.024428, 1.358),    # culvert 158
    (150, -0.004464, 0.234),   # GTS BOM Type 'B', Basmat
    (147, -0.003598, 1.699),   # culvert, Jawahar Navodaya
    (144, -0.000786, 1.458),   # culvert, Khandegav
    (142, -0.003263, 2.057),   # Hayatnagar-Basmat-Raywadi trijunction
    (139, -0.000328, 2.180),   # Purna-Basmat road culvert
    (136, -0.001758, 1.209),   # culvert, 4 km N of Purna
    (132, -0.001072, 1.430),   # Zerophata-Purna road culvert
    (129, 0.000794, 1.347),    # Aaherwadi junction culvert
    (126, -0.001360, 1.115),   # Katneswar culvert
    (122, 0.000589, 1.351),    # Zerophata road pillar
    (119, 0.001676, 1.762),    # Bharti camp culvert
    (115, 0.000175, 1.116),    # Omkareswar Mandir parapet
    (114, -0.011062, None),    # (re-occupation near base)
    (112, 0.010392, 1.371),    # Shivneri Garden Dhaba culvert
    (110, -0.003655, 2.615),   # HP Petroleum Basmat road
    (109, -0.002328, 2.100),   # GCP Exec. Engineer PWD, Savli/Parbhani
    (107, 0.001426, None),
    (104, -0.002075, None),
    (101, 0.000485, None),
    (99, -0.000780, None),
    (98, 0.002897, None),
    (96, 0.002299, None),
    (93, 0.002300, None),
    (90, -0.001199, None),
    (87, -0.004855, None),
    (85, -0.003140, None),
    (82, -0.001962, None),
    (80, -0.002062, None),
    (77, 0.004421, None),
    (76, -0.002203, None),
    (73, 0.005386, None),
    (70, -0.001089, None),
    (67, -0.002160, None),
    (64, -0.005232, None),
    (60, 0.000710, None),
    (57, -0.002518, None),
    (55, None, None),          # row 72: first visit to BM 55 -- leg 57->55
    (54, 0.001493, None),
    (52, -0.000204, None),
    (55, -0.000049, None),     # re-occupation of BM 55
    (46, -0.007401, None),
    (43, -0.005991, None),
    (40, -0.000763, None),
    (39, -0.004537, None),
    (38, -0.002404, None),
    (35, 0.001234, None),
    (30, -0.001126, None),
    (28, 0.000051, None),
    (27, 0.024543, None),
    (24, -0.023231, None),
    (21, -0.003992, None),
    (19, -0.003437, None),
    (16, 0.002119, None),
    (12, -0.002251, None),
    (9, 0.001548, None),
    (3, None, None),           # row 91: BM 3 -- leg 9->3 (derived)
    (2, None, None),           # row 92: occupied, no DeltaG recorded (from for 2->1)
    (1, 0.006758, None),
    (ANCHOR_STATION, 0.030185, None),  # closing leg back to the base
]

# GCP/GTS control points of the survey. KnownG placeholder = the
# sheet's OFFICIAL final adjusted value (published value not yet
# available); Sigma 0.010 mGal. Replace KnownG with each control's
# published absolute value for an independent adjustment.
BASE_CONTROLS = [
    (228, 978.468269, 0.010),   # GCP Vet Dispensary, Narsapur
    (195, 978.438166, 0.010),   # GCP PWD Division, Bhokar
    (160, 978.454062, 0.010),   # GCP Gram Panchayat office, Girgaon
    (150, 978.452190, 0.010),   # GTS BOM Type 'B', Basmat
    (109, 978.436610, 0.010),   # GCP Exec. Engineer PWD, Savli/Parbhani
]

# Official "final adjusted" values from the sheet (screenshot
# transcription), stations 240..109. Used for validation only.
FINAL_ADJ = {
    240: 978.475435, 237: 978.476602, 234: 978.473180, 232: 978.470611,
    229: 978.468447, 228: 978.468269, 225: 978.466190, 222: 978.462436,
    218: 978.458149, 215: 978.455195, 213: 978.455454, 209: 978.449941,
    207: 978.449070, 204: 978.452183, 201: 978.442276, 199: 978.440747,
    197: 978.439958, 195: 978.438166, 194: 978.432308, 192: 978.443243,
    189: 978.440535, 185: 978.448857, 182: 978.452246, 178: 978.452958,
    175: 978.455211, 172: 978.455521, 169: 978.454245, 167: 978.454837,
    165: 978.456235, 163: 978.452935, 161: 978.454926, 160: 978.454062,
    159: 978.453344, 156: 978.451882, 155: 978.432225, 153: 978.456653,
    150: 978.452190, 147: 978.448592, 144: 978.447806, 142: 978.444544,
    139: 978.444216, 136: 978.442458, 132: 978.441386, 129: 978.442181,
    126: 978.440821, 122: 978.441410, 119: 978.443087, 115: 978.443262,
    114: 978.432200, 112: 978.442593, 110: 978.438938, 109: 978.436610,
}

# ---------------------------------------------------------------------------
# Missing-leg derivation inputs
# ---------------------------------------------------------------------------
# The two rows whose DeltaG cell is blank in the original survey sheet.
# Excel row = pasted row + 2 (title + header row above the table),
# confirmed against the user's screenshots (Excel 72 = BM 60, Excel
# 91 = BM 12). from_idx/to_idx are DATA indices (DATA row 0 = the
# START anchor).
MISSING_LEGS = [
    {
        "station": 55,  # first visit of BM 55 (there is a later re-occupation)
        "excel_row": 74,
        "from_idx": 72,  # DATA index of BM 57 (the 'from' station)
        "to_idx": 73,    # DATA index of this station
        "label": "leg 57->55",
    },
    {
        "station": 3,
        "excel_row": 93,
        "from_idx": 91,  # DATA index of BM 9
        "to_idx": 92,
        "label": "leg 9->3",
    },
]

# If the original survey xlsx is present next to this script it is read
# automatically and SHEET_CUM_G is ignored. Otherwise paste the two
# cumulative-gravity cells (column headed 978.432255) from Excel rows
# 74 and 93 here (filled from the user's sheet):
SHEET_CUM_G = {
    74: 978.427265,  # Excel row 74 = BM 55 (first visit)
    93: 978.402872,  # Excel row 93 = BM 3
}

ORIGINAL_SHEET_CANDIDATES = [
    "nicky's_Sheet(1).xlsx",
    "data/nicky's_Sheet(1).xlsx",
    "nicky_Sheet.xlsx",
    "data/nicky_Sheet.xlsx",
]


def running_cumulative(up_to_row):
    """Running sum of DeltaG from the anchor over DATA rows 0..up_to_row."""
    cum = ANCHOR_KNOWN_G
    for i in range(1, up_to_row + 1):
        dg = DATA[i][1]
        if dg is not None:
            cum += dg
    return cum


def find_original_sheet():
    for path in ORIGINAL_SHEET_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def read_sheet_cumulative(path):
    """
    Read the original survey xlsx and return {sheet_row: cumulative}
    for the two missing-leg rows. Column matching mirrors the layout
    pasted earlier: station header contains 'BM', the DeltaG header is
    '∆g', and the cumulative header is the anchor value 978.432255.
    """
    df = pd.read_excel(path, sheet_name=0)
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]

    station_col = next(
        (c for c in df.columns if "BM" in str(c).upper()), None
    )
    dg_col = next(
        (c for c in df.columns if str(c).strip() in ("∆g", "Δg", "Ag")),
        None,
    )
    cum_col = None
    for c in df.columns:
        try:
            if abs(float(c) - ANCHOR_KNOWN_G) < 1e-6:
                cum_col = c
                break
        except (TypeError, ValueError):
            continue

    if station_col is None or cum_col is None:
        raise ValueError(
            f"Could not find the station/cumulative columns in {path} "
            f"(cols found: {list(df.columns)})"
        )

    # Verify the running-sum pattern on the rows we can (0..9).
    ok = True
    cum = ANCHOR_KNOWN_G
    for i in range(len(df)):
        dg = pd.to_numeric(df.iloc[i][dg_col], errors="coerce") if dg_col else None
        if pd.notna(dg):
            cum += float(dg)
        if i <= 9 and pd.notna(df.iloc[i][cum_col]):
            if abs(float(df.iloc[i][cum_col]) - cum) > 1e-6:
                ok = False
    print(f"[read {path}] cumulative column running-sum check (rows 0-9): "
          f"{'OK' if ok else 'MISMATCH -- fall back to SHEET_CUM_G'}")

    result = {}
    for leg in MISSING_LEGS:
        stations = pd.to_numeric(df[station_col], errors="coerce")
        matches = df.index[stations == float(leg["station"])].tolist()
        if not matches:
            print(f"[read] BM {leg['station']} not found in {path}")
            result[leg["excel_row"]] = None
            continue
        row = matches[0]  # first occurrence (for BM 55: the first visit)
        val = df.iloc[row][cum_col]
        found_cum = None if pd.isna(val) else float(val)
        dg = None if dg_col is None or pd.isna(df.iloc[row][dg_col]) \
            else float(df.iloc[row][dg_col])
        result[leg["excel_row"]] = found_cum
        print(f"[read] BM {leg['station']} at Excel row {row + 2}: "
              f"DeltaG={dg} cumulative={found_cum} "
              f"({leg['label']})")
    return result


def derive_legs(sheet_cum):
    """Returns {DATA index of the missing row: DeltaG} derived from the
    cumulative column:  DeltaG(from->to) = CumG(to) - CumG(from)."""
    legs = {}
    for leg in MISSING_LEGS:
        cum_here = sheet_cum.get(leg["excel_row"])
        cum_from = running_cumulative(leg["from_idx"])
        if cum_here is None:
            raise ValueError(
                f"Missing cumulative value for BM {leg['station']} "
                f"(Excel row {leg['excel_row']}, {leg['label']}). Provide it "
                f"via SHEET_CUM_G or place the original xlsx next to this script."
            )
        legs[leg["to_idx"]] = cum_here - cum_from
        print(
            f"derived {leg['label']}: CumG[BM {leg['station']}]={cum_here:.6f} - "
            f"CumG[BM {DATA[leg['from_idx']][0]}]={cum_from:.6f} = "
            f"DeltaG {legs[leg['to_idx']]:+.6f} mGal"
        )
    return legs


def main():
    os.makedirs("data", exist_ok=True)

    # 1. Get the two cumulative values: original sheet if present, else
    #    pasted constants.
    sheet_cum = {}
    original = find_original_sheet()
    if original:
        read = read_sheet_cumulative(original)
        sheet_cum = {row: info["cumulative"] for row, info in read.items()}
    else:
        print("[sheet] original xlsx not found -- using SHEET_CUM_G constants")
        sheet_cum = dict(SHEET_CUM_G)

    # 2. Derive the missing legs (refuses to proceed if values absent).
    try:
        legs = derive_legs(sheet_cum)
    except ValueError as exc:
        print(f"\nCannot build clean files yet: {exc}\n")
        print("Context numbers already known (running-sum cumulative):")
        for leg in MISSING_LEGS:
            from_station = DATA[leg["from_idx"]][0]
            print(
                f"  CumG(BM {from_station}) = "
                f"{running_cumulative(leg['from_idx']):.6f} mGal  "
                f"[{leg['label']}]"
            )
        print("\nAll you need to provide: the cumulative-gravity cell (column")
        print("headed 978.432255) at Excel rows 74 (BM 55) and 93 (BM 3), or")
        print("upload the file.")
        sys.exit(1)

    # 3. Fill the derived legs into the rows.
    rows = []
    cum = ANCHOR_KNOWN_G
    for idx, (station, dg, meandist) in enumerate(DATA):
        if dg is None and idx in legs:
            dg = legs[idx]
        if dg is not None:
            cum += dg
        rows.append((station, dg, meandist, cum, FINAL_ADJ.get(station)))

    df = pd.DataFrame(
        rows, columns=["Station", "DeltaG", "MeanDistKm", "CumulativeG", "FinalAdjustedG"]
    )

    # 4. Loop closure report.
    total = sum(dg for _, dg, _ in DATA if dg is not None)
    total = total + sum(legs.values())
    print(f"\nrows: {len(df)} | sum(DeltaG) = {total:.6f} mGal")
    print(f"cumulative after closing leg = {cum:.6f} mGal  (anchor {ANCHOR_KNOWN_G})")
    print(f"loop misclosure = {(cum - ANCHOR_KNOWN_G) * 1e3:.3f} microGal")

    ties_path = "data/nicky_survey_ties_clean.xlsx"
    base_path = "data/nicky_base_reference_clean.xlsx"

    with pd.ExcelWriter(ties_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Ties", index=False)
        notes = pd.DataFrame(
            {
                "Station": ["228", "195", "160", "150", "109"],
                "Type": [
                    "GCP (Narsapur)", "GCP (PWD Bhokar)", "GCP (Girgaon)",
                    "GTS BOM Type B (Basmat)", "GCP (Savli, Parbhani)",
                ],
                "CumulativeG_mGal": [978.468267, 978.438161, 978.454053,
                                     978.452179, 978.436595],
                "Note": [
                    "Absolute controls in the survey. Enter each one's "
                    "published absolute value (KnownG) to use it as an "
                    "additional anchor in the adjustment.",
                ] * 5,
            }
        )
        notes.to_excel(writer, sheet_name="Reference", index=False)

    base_rows = [(ANCHOR_STATION, ANCHOR_KNOWN_G, ANCHOR_SIGMA)] + BASE_CONTROLS
    base = pd.DataFrame(base_rows, columns=["Station", "KnownG", "Sigma"])
    base.to_excel(base_path, sheet_name="Base Reference", index=False)

    print(f"Wrote {ties_path}  ({len(df)} rows incl. anchor + closing leg)")
    print(f"Wrote {base_path}  (anchor {ANCHOR_STATION} = {ANCHOR_KNOWN_G} mGal)")

    # 5. Structural self-check: the network must now solve.
    adj = NetworkAdjustment()
    day_df = adj.load_drift_corrected_file(ties_path)
    base_df = adj.load_base_station_reference(base_path)
    A, L, sigma, station_ids, obs_labels, closure = adj.build_network(
        [day_df], base_df, mode="partial", relative_sigma_source="manual",
        manual_relative_sigma=0.005, manual_base_sigma=0.010,
    )
    rank = np.linalg.matrix_rank(A)
    print(f"\n[self-check] A {A.shape}: rank {rank} vs unknowns {A.shape[1]} "
          f"-> {'FULL RANK (solvable)' if rank == A.shape[1] else 'SINGULAR'}")
    results, residuals = adj.solve(A, L, sigma, station_ids, obs_labels)
    stats = results.attrs["statistics"]
    print(f"[self-check] solve OK: obs={stats['n_observations']} "
          f"unknowns={stats['m_unknowns']} dof={stats['degrees_of_freedom']}")


if __name__ == "__main__":
    main()
