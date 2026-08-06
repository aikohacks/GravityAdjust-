"""
validate_nicky_adjustment.py
----------------------------
End-to-end validation of Nicky's clean input workbooks: runs the REAL
least-squares pipeline (core.adjustment.NetworkAdjustment) on
data/nicky_survey_ties_clean.xlsx + data/nicky_base_reference_clean.xlsx
and compares the adjusted gravity values against the survey sheet's
official final adjusted values (stations 240..109, transcribed in
build_nicky_input.py).

Run:  python3 validate_nicky_adjustment.py
"""
import os

import numpy as np

from core.adjustment import NetworkAdjustment

ROOT = os.path.dirname(os.path.abspath(__file__))
TIES = os.path.join(ROOT, "data", "nicky_survey_ties_clean.xlsx")
BASE = os.path.join(ROOT, "data", "nicky_base_reference_clean.xlsx")

# Official "final adjusted" values from Nicky's sheet (see build_nicky_input.py).
OFFICIAL = {
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


def run(mode, manual_relative_sigma=0.005, manual_base_sigma=0.010):
    adj = NetworkAdjustment()
    day_df = adj.load_drift_corrected_file(TIES)
    base_df = adj.load_base_station_reference(BASE)

    A, L, sigma, station_ids, obs_labels, closure = adj.build_network(
        [day_df], base_df,
        mode=mode,
        relative_sigma_source="manual",
        manual_relative_sigma=manual_relative_sigma,
        manual_base_sigma=manual_base_sigma,
    )
    results, residuals = adj.solve(A, L, sigma, station_ids, obs_labels)
    stats = results.attrs["statistics"]

    rmap = {r["Station"]: r["AdjustedGValue"] for _, r in results.iterrows()}
    diffs = np.array([
        (rmap[str(sid)] - off) * 1e3  # mGal -> uGal
        for sid, off in sorted(OFFICIAL.items(), key=lambda kv: int(kv[0]))
        if str(sid) in rmap
    ])

    print(f"\n===== mode={mode} =====")
    print(f"obs={stats['n_observations']} unknowns={stats['m_unknowns']} "
          f"dof={stats['degrees_of_freedom']} "
          f"variance_factor={stats['variance_factor']:.6f} "
          f"a_posteriori_sigma={stats['a_posteriori_sigma']:.6f} mGal")
    print(f"compared {len(diffs)} stations vs official final values")
    print(f"mean diff = {diffs.mean():+.3f} uGal | max |diff| = "
          f"{np.abs(diffs).max():.3f} uGal | rms = {np.sqrt((diffs**2).mean()):.3f} uGal")

    order = np.argsort(-np.abs(diffs))[:6]
    pairs = sorted(OFFICIAL.items(), key=lambda kv: int(kv[0]))
    for i in order:
        sid, off = pairs[i]
        print(f"   station {sid}: adj={rmap[str(sid)]:.6f} vs official={off:.6f} "
              f"({diffs[i]:+.3f} uGal)")

    if closure:
        print("closure checks (both endpoints fixed):")
        for c in closure:
            print(f"   {c['label']}: obs={c['observed_delta_g']:.6f} "
                  f"implied={c['implied_delta_g']:.6f} "
                  f"disc={c['discrepancy']*1e3:+.3f} uGal")

    r = residuals["Residual"]
    print(f"residuals: mean={r.mean()*1e3:+.3f} uGal "
          f"rms={np.sqrt((r**2).mean())*1e3:.3f} uGal "
          f"max|r|={r.abs().max()*1e3:.3f} uGal")
    worst = residuals.reindex(r.abs().sort_values(ascending=False).index).head(6)
    for _, row in worst.iterrows():
        print(f"   {row['Observation']}: {row['Residual']*1e3:+.3f} uGal")
    return results, residuals


if __name__ == "__main__":
    run("partial")
    run("hard_fixed")
