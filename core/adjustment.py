"""
core/adjustment.py
-------------------
Least Squares Network Adjustment engine for the Gravity Adjustment
Software (Phase 5).

Architecture (per the confirmed blueprint):

1. FILE-BASED MULTI-DAY ACCUMULATION
   Each survey day/circuit is drift-corrected and exported independently
   (core.drift.DriftCorrector -> reports.excel_export.export_drift_only).
   This module does NOT retain accumulated data in memory across a
   session -- it reads a batch of those exported files back in fresh
   each time an adjustment is run, plus one Base Station Reference file.

2. MATRIX ASSEMBLY & REDUNDANCY
   Every individual DeltaG measurement from every day's file becomes
   its own row in the design matrix (A) and observation vector (L).
   There is exactly one column in the unknowns vector (X) per unique
   Station ID. A station visited on multiple days contributes multiple
   independent observation rows pointing at the same column -- rows
   are appended to lists, never merged/averaged/overwritten, so the
   least squares solve itself is what reconciles any discrepancies.

3. BASE STATION REFERENCE
   A separate file with columns (fuzzy-matched): Station ID, Known G
   Value, Sigma. Each base station becomes its own observation row: a
   single +1 in that station's column, with the known G value as the
   observation. Sigma is captured now (per row) but not yet used for
   weighting -- that's Phase B.

4. PHASED EXECUTION
   Phase A (implemented here): unweighted least squares,
       X = (A^T A)^-1 A^T L
   Phase B (placeholder, not yet implemented): weighted least squares,
       X = (A^T P A)^-1 A^T P L
   using P built from the captured sigma values (w = 1/sigma^2).

This module contains NO GUI code.
"""

import numpy as np
import pandas as pd

from core.drift import DriftCorrector


class AdjustmentError(Exception):
    """Raised when the network adjustment cannot be built or solved."""
    pass


class NetworkAdjustment:
    """
    Builds and solves a least-squares gravity network adjustment from
    a batch of drift-corrected daily files plus one base station
    reference file.

    Usage:
        adjustment = NetworkAdjustment()

        daily_dfs = [adjustment.load_drift_corrected_file(p) for p in day_paths]
        base_df = adjustment.load_base_station_reference(base_path)

        A, L, station_ids, sigma, obs_labels = adjustment.build_network(daily_dfs, base_df)
        results_df, residuals = adjustment.solve_unweighted(A, L, station_ids, obs_labels)
    """

    BASE_COLUMN_KEYWORDS = {
        "Station": ["station", "site"],
        "KnownG": ["known"],
        "Sigma": ["sigma", "uncertainty", "precision"],
    }

    DELTA_G_KEYWORDS = ["delta"]

    # ------------------------------------------------------------------
    # STATION ID NORMALIZATION
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_station_id(value) -> str:
        """
        Convert a station ID value to a canonical string, so the same
        logical station is always recognized as the same key -- even
        if one file's Excel/pandas round-trip gives it as an int (2)
        and another gives it as a float (2.0). Excel stores all numbers
        as floating point internally, so pandas' dtype inference can
        differ from file to file depending on incidental factors, even
        when the underlying station ID is logically identical.

        Whole-number floats are rendered without the trailing ".0"
        (2.0 -> "2"); everything else is just str()'d and stripped.
        """
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    # ------------------------------------------------------------------
    # FILE LOADING
    # ------------------------------------------------------------------
    def load_drift_corrected_file(self, file_path: str) -> pd.DataFrame:
        """
        Read one daily drift-corrected results file back in from disk.

        Looks for a sheet named "Drift Corrected Results" (case-
        insensitive) if the workbook has multiple sheets; otherwise
        reads whichever single sheet is present. Validates that a
        Station column and a DeltaG column can be found (fuzzy-matched).

        Returns the DataFrame with those two columns renamed to their
        canonical names ("Station", "DeltaG"), in original row order
        (order matters -- it defines the from/to sequence of visits).
        """
        try:
            excel_file = pd.ExcelFile(file_path)
        except Exception as exc:
            raise AdjustmentError(f"Could not open '{file_path}': {exc}") from exc

        sheet_name = excel_file.sheet_names[0]
        for name in excel_file.sheet_names:
            if name.strip().lower() == "drift corrected results":
                sheet_name = name
                break

        try:
            df = excel_file.parse(sheet_name)
        except Exception as exc:
            raise AdjustmentError(
                f"Could not read sheet '{sheet_name}' from '{file_path}': {exc}"
            ) from exc

        station_col = self._find_column(df, DriftCorrector.COLUMN_KEYWORDS["Station"])
        deltag_col = self._find_column(df, self.DELTA_G_KEYWORDS)

        if station_col is None or deltag_col is None:
            missing = []
            if station_col is None:
                missing.append("Station")
            if deltag_col is None:
                missing.append("DeltaG")
            raise AdjustmentError(
                f"File '{file_path}' is missing required column(s): "
                f"{', '.join(missing)}. Expected a drift-corrected "
                f"results export from Phase 4."
            )

        return df.rename(columns={station_col: "Station", deltag_col: "DeltaG"})

    def load_base_station_reference(self, file_path: str) -> pd.DataFrame:
        """
        Read the Base Station Reference file: Station ID, Known G
        Value, Sigma (fuzzy-matched column headers).

        Returns a DataFrame with canonical columns "Station", "KnownG",
        "Sigma".
        """
        try:
            df = pd.read_excel(file_path) if file_path.lower().endswith((".xlsx", ".xls")) \
                else pd.read_csv(file_path)
        except Exception as exc:
            raise AdjustmentError(f"Could not read '{file_path}': {exc}") from exc

        rename_map = {}
        for canonical, keywords in self.BASE_COLUMN_KEYWORDS.items():
            col = self._find_column(df, keywords)
            if col is None:
                raise AdjustmentError(
                    f"Base Station Reference file is missing a column for "
                    f"'{canonical}'. Expected columns matching: Station/Site, "
                    f"Known (G Value), Sigma/Uncertainty/Precision."
                )
            rename_map[col] = canonical

        return df.rename(columns=rename_map)[["Station", "KnownG", "Sigma"]]

    @staticmethod
    def _find_column(df: pd.DataFrame, keywords):
        for col in df.columns:
            if DriftCorrector._header_matches_keywords(col, keywords):
                return col
        return None

    # ------------------------------------------------------------------
    # MATRIX ASSEMBLY
    # ------------------------------------------------------------------
    def build_network(self, daily_dataframes: list, base_station_df: pd.DataFrame):
        """
        Assemble the design matrix (A), observation vector (L), sigma
        vector, and the ordered list of station IDs (one per column of A).

        Args:
            daily_dataframes: list of DataFrames, one per day/circuit,
                each with (at least) "Station" and "DeltaG" columns, in
                original visit order. Every row after the first in each
                DataFrame becomes one observation: the DeltaG between
                the previous row's station and this row's station.
            base_station_df: DataFrame with "Station", "KnownG", "Sigma"
                columns. Each row becomes one observation: a single +1
                at that station's column, with KnownG as the observed
                value.

        Returns:
            (A, L, station_ids, sigma, obs_labels)

        Raises:
            AdjustmentError: if there is not at least one observation,
                or fewer than 1 unique station.
        """
        station_order = {}
        for day_df in daily_dataframes:
            for station in day_df["Station"]:
                station_order.setdefault(self._normalize_station_id(station), None)
        for station in base_station_df["Station"]:
            station_order.setdefault(self._normalize_station_id(station), None)

        station_ids = list(station_order.keys())
        station_index = {sid: idx for idx, sid in enumerate(station_ids)}
        num_stations = len(station_ids)

        if num_stations == 0:
            raise AdjustmentError("No stations found in the provided data.")

        rows_A = []
        rows_L = []
        rows_sigma = []
        obs_labels = []

        for day_number, day_df in enumerate(daily_dataframes, start=1):
            for i in range(1, len(day_df)):
                from_station = self._normalize_station_id(day_df.iloc[i - 1]["Station"])
                to_station = self._normalize_station_id(day_df.iloc[i]["Station"])
                delta_g = day_df.iloc[i]["DeltaG"]

                if pd.isna(delta_g):
                    continue

                row = np.zeros(num_stations)
                row[station_index[to_station]] += 1.0
                row[station_index[from_station]] -= 1.0

                rows_A.append(row)
                rows_L.append(float(delta_g))
                rows_sigma.append(np.nan)
                obs_labels.append(
                    f"Day {day_number}: {from_station} -> {to_station} (DeltaG)"
                )

        for _, base_row in base_station_df.iterrows():
            row = np.zeros(num_stations)
            station_id = self._normalize_station_id(base_row["Station"])
            if station_id not in station_index:
                station_index[station_id] = num_stations
                station_ids.append(station_id)
                num_stations += 1
                row = np.append(row, 0.0)
                rows_A = [np.append(r, 0.0) for r in rows_A]

            row[station_index[station_id]] = 1.0
            rows_A.append(row)
            rows_L.append(float(base_row["KnownG"]))
            rows_sigma.append(base_row["Sigma"])
            obs_labels.append(f"Base Station: {station_id} (Known G)")

        if not rows_A:
            raise AdjustmentError(
                "No valid observations could be built from the provided files."
            )

        A = np.array(rows_A)
        L = np.array(rows_L)
        sigma = np.array(rows_sigma, dtype=float)

        return A, L, station_ids, sigma, obs_labels

    # ------------------------------------------------------------------
    # PHASE A: UNWEIGHTED SOLVE
    # ------------------------------------------------------------------
    def solve_unweighted(self, A: np.ndarray, L: np.ndarray, station_ids: list, obs_labels: list):
        """
        Solve X = (A^T A)^-1 A^T L (unweighted least squares).

        Returns:
            (results_df, residuals_df)

        Raises:
            AdjustmentError: if A^T A is singular.
        """
        AtA = A.T @ A
        AtL = A.T @ L

        try:
            X = np.linalg.solve(AtA, AtL)
        except np.linalg.LinAlgError as exc:
            raise AdjustmentError(
                "The network adjustment could not be solved -- the system "
                "is singular. This usually means the network isn't fully "
                "tied to at least one base station, or some stations have "
                "no measurement path connecting them to the rest of the "
                "network. Check that your Base Station Reference file "
                "covers the network and that all stations are connected "
                "by at least one circuit."
            ) from exc

        results_df = pd.DataFrame({"Station": station_ids, "AdjustedGValue": X})

        residuals = A @ X - L
        residuals_df = pd.DataFrame({"Observation": obs_labels, "Residual": residuals})

        return results_df, residuals_df

    # ------------------------------------------------------------------
    # PHASE B: WEIGHTED SOLVE (placeholder)
    # ------------------------------------------------------------------
    def solve_weighted(self, A: np.ndarray, L: np.ndarray, sigma: np.ndarray,
                        station_ids: list, obs_labels: list):
        """
        Placeholder for Phase B: weighted least squares,
            X = (A^T P A)^-1 A^T P L

        Not yet implemented -- every DeltaG observation currently has
        an unknown (NaN) sigma, since per-observation precision isn't
        captured anywhere upstream yet.
        """
        raise NotImplementedError(
            "Weighted least squares (Phase B) is not yet implemented. "
            "It requires a stated precision (sigma) for every DeltaG "
            "observation, not just base station observations -- this "
            "needs a design decision on where that precision comes from."
        )