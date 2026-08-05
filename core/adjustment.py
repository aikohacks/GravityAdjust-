"""
core/adjustment.py
-------------------
Least Squares Network Adjustment engine for the Gravity Adjustment
Software (Phase 5).

Supports TWO weighting architectures, selected via the `mode` argument
to build_network():

    "partial"    -- Approach A: Partial Constraints (Fully Weighted).
                    Both base stations AND relative ties get their own
                    sigma. Base stations remain in the matrices as
                    pseudo-observations (a +1 row for each), weighted
                    by w = 1/sigma^2 like everything else. The whole
                    network -- including base stations -- is solved as
                    part of X, so a base station's adjusted value CAN
                    move slightly if the network statistically pulls
                    it, constrained only by how small its sigma is.

    "hard_fixed" -- Approach B: Hard-Fixed (Zero Variance). Base
                    stations are NOT unknowns and never appear as rows
                    in the design matrix (avoids the 1/sigma^2
                    divide-by-zero that a literal sigma=0 pseudo-
                    observation would cause). Instead, every relative
                    observation touching a base station has that
                    station's known value substituted in and moved to
                    the observation side of the equation, before the
                    remaining (now base-station-free) row is added to
                    the design matrix. This is the classic "elimination
                    of fixed points" method (same approach used by
                    reference tools like Level_Net_Adjust.py). Relative
                    ties are still weighted in this mode -- only the
                    base stations themselves are excluded from
                    weighting, since they're constants, not observations.

Both modes share the same weighted-least-squares solver:
    X = (A^T P A)^-1 A^T P L,   P = diag(1/sigma_i^2)

RELATIVE TIE SIGMA: comes from one of two sources, chosen via
`relative_sigma_source`:
    "manual"            -- a single sigma value (manual_relative_sigma)
                            applied to every relative-tie observation.
    "mean_sigma_column" -- read per-observation from a "MeanSigma"
                            column in each day's drift-corrected file.
                            core/drift.py produces this column (the
                            standard error of each visit's mean
                            reading), and it round-trips through
                            reports.excel_export.export_drift_only, so
                            this source works with files exported from
                            the current drift-correction step. Each
                            relative-tie observation connects two visit
                            means, so its sigma is the rigorous error
                            propagation of the two endpoints:
                            sigma_dg = sqrt(sigma_from^2 + sigma_to^2).
                            If a day file is missing the column (or an
                            endpoint visit's MeanSigma is blank), a
                            clear AdjustmentError is raised rather than
                            silently falling back to something else.

BASE STATION SIGMA (mode="partial" only): read per-row from the Base
Station Reference file's Sigma column when present and not NaN;
otherwise falls back to manual_base_sigma. Ignored entirely in
mode="hard_fixed" (base stations aren't weighted rows in that mode).

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

        A, L, sigma, station_ids, obs_labels, closure_checks = adjustment.build_network(
            daily_dfs, base_df,
            mode="hard_fixed",
            relative_sigma_source="manual",
            manual_relative_sigma=5.0,
        )
        results_df, residuals_df = adjustment.solve(A, L, sigma, station_ids, obs_labels)
    """

    BASE_COLUMN_KEYWORDS = {
        "Station": ["station", "site"],
        "KnownG": ["known"],
        "Sigma": ["sigma", "uncertainty", "precision"],
    }

    DELTA_G_KEYWORDS = ["delta"]
    # Requires BOTH "mean" and "sigma" tokens to match (see
    # _find_column require_all=True): a lone "Sigma" column or a
    # "MeanTime"/"MeanReading" header must never be mistaken for the
    # per-visit MeanSigma precision column.
    MEAN_SIGMA_KEYWORDS = ["mean", "sigma"]

    VALID_MODES = ("partial", "hard_fixed")
    VALID_RELATIVE_SIGMA_SOURCES = ("manual", "mean_sigma_column")

    # ------------------------------------------------------------------
    # STATION ID NORMALIZATION
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_station_id(value) -> str:
        """
        Convert a station ID value to a canonical string, so the same
        logical station is always recognized as the same key -- even
        if one file's Excel/pandas round-trip gives it as an int (2)
        and another gives it as a float (2.0).
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
        A MeanSigma column is also looked for (fuzzy-matched) but is
        OPTIONAL at this stage -- absence is only an error if the
        caller later selects relative_sigma_source="mean_sigma_column".

        Returns the DataFrame with Station/DeltaG (and MeanSigma, if
        present) renamed to their canonical names, in original row
        order (order matters -- it defines the from/to sequence of
        visits).
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
        # MeanSigma requires BOTH "mean" and "sigma" tokens, so a
        # MeanTime/MeanReading header is never mis-identified as it.
        mean_sigma_col = self._find_column(df, self.MEAN_SIGMA_KEYWORDS, require_all=True)

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

        rename_map = {station_col: "Station", deltag_col: "DeltaG"}
        if mean_sigma_col is not None:
            rename_map[mean_sigma_col] = "MeanSigma"

        return df.rename(columns=rename_map)

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

        df = df.rename(columns=rename_map)[["Station", "KnownG", "Sigma"]]

        # Validate the Sigma column: it must hold strictly positive
        # numeric values. A zero or negative Sigma would produce an
        # infinite/negative weight in the weighted solve.
        sigma_values = pd.to_numeric(df["Sigma"], errors="coerce")
        if sigma_values.isna().all():
            raise AdjustmentError(
                "Base Station Reference file: all Sigma values are missing "
                "or non-numeric. Sigma must be a positive number (mGal) for "
                "each station."
            )
        if (sigma_values <= 0).any():
            bad_stations = df.loc[sigma_values <= 0, "Station"].tolist()
            raise AdjustmentError(
                "Base Station Reference file: Sigma must be positive for every "
                "station (got <= 0 for: " + ", ".join(str(s) for s in bad_stations) + "). "
                "A zero or negative Sigma would produce an invalid (infinite) weight."
            )

        return df

    @staticmethod
    def _find_column(df: pd.DataFrame, keywords, require_all: bool = False):
        """
        Find the first column whose header matches `keywords`.

        require_all=False: match if ANY keyword token appears (used for
            column aliases like Station/Site).
        require_all=True: match only if ALL keyword tokens appear
            (used for MeanSigma -- requires BOTH "mean" and "sigma"
            tokens so a generic "MeanTime"/"MeanReading" column is
            never mistaken for the per-visit precision column).
        """
        for col in df.columns:
            if require_all:
                if DriftCorrector._header_matches_all_keywords(col, keywords):
                    return col
            elif DriftCorrector._header_matches_keywords(col, keywords):
                return col
        return None

    # ------------------------------------------------------------------
    # MATRIX ASSEMBLY
    # ------------------------------------------------------------------
    def build_network(
        self,
        daily_dataframes: list,
        base_station_df: pd.DataFrame,
        mode: str = "partial",
        relative_sigma_source: str = "manual",
        manual_relative_sigma: float = 5.0,
        manual_base_sigma: float = 1.0,
    ):
        """
        Assemble the design matrix (A), observation vector (L), per-
        observation sigma vector, the ordered list of station IDs (one
        per column of A), and per-observation labels.

        Args:
            daily_dataframes: list of DataFrames, one per day/circuit,
                each with "Station" and "DeltaG" columns (and
                "MeanSigma" if relative_sigma_source="mean_sigma_column"),
                in original visit order.
            base_station_df: DataFrame with "Station", "KnownG", "Sigma"
                columns.
            mode: "partial" (Approach A) or "hard_fixed" (Approach B).
            relative_sigma_source: "manual" or "mean_sigma_column" --
                where each relative-tie observation's sigma comes from.
            manual_relative_sigma: sigma applied to every relative-tie
                observation when relative_sigma_source="manual".
            manual_base_sigma: fallback sigma for base stations (mode=
                "partial" only) when the reference file's own Sigma
                value for that station is missing/NaN.

        Returns:
            (A, L, sigma, station_ids, obs_labels, closure_checks)

            closure_checks: list of dicts, one per observation where
                BOTH endpoints are base (fixed) stations in
                mode="hard_fixed" -- these can't contribute an unknown
                to solve for, so they're reported separately as a
                diagnostic (observed Δg vs. what the two known values
                imply), same spirit as Line Drift's closure_discrepancy.
                Always empty in mode="partial".

        Raises:
            AdjustmentError: invalid mode/relative_sigma_source, no
                stations found, relative_sigma_source="mean_sigma_column"
                but no MeanSigma column exists in the data, or no valid
                observations could be built.
        """
        if mode not in self.VALID_MODES:
            raise AdjustmentError(
                f"Invalid mode '{mode}'. Must be one of: {', '.join(self.VALID_MODES)}."
            )
        if relative_sigma_source not in self.VALID_RELATIVE_SIGMA_SOURCES:
            raise AdjustmentError(
                f"Invalid relative_sigma_source '{relative_sigma_source}'. "
                f"Must be one of: {', '.join(self.VALID_RELATIVE_SIGMA_SOURCES)}."
            )

        # Validate base-station Sigma values up front, whether the
        # DataFrame came from load_base_station_reference() (which
        # validates too) or was constructed/edited in memory.
        if "Sigma" in base_station_df.columns:
            sigma_values = pd.to_numeric(base_station_df["Sigma"], errors="coerce")
            if (sigma_values <= 0).any():
                bad_stations = base_station_df.loc[sigma_values <= 0, "Station"].tolist()
                raise AdjustmentError(
                    "Base Station Reference: Sigma must be positive for every "
                    "station (got <= 0 for: " + ", ".join(str(s) for s in bad_stations) + "). "
                    "A zero or negative Sigma would produce an invalid (infinite) weight."
                )

        if relative_sigma_source == "mean_sigma_column":
            missing_files = [
                idx + 1 for idx, day_df in enumerate(daily_dataframes)
                if "MeanSigma" not in day_df.columns
            ]
            if missing_files:
                raise AdjustmentError(
                    "relative_sigma_source='mean_sigma_column' was selected, but "
                    f"day file(s) {missing_files} have no MeanSigma column. "
                    "Re-export the drift-corrected results from the current "
                    "drift-correction step (which now produces MeanSigma), or "
                    "switch to relative_sigma_source='manual'."
                )

        # Base station known values / normalized IDs, needed regardless
        # of mode (used directly in "partial", used for substitution in
        # "hard_fixed").
        base_values = {}
        base_sigma = {}
        for _, base_row in base_station_df.iterrows():
            sid = self._normalize_station_id(base_row["Station"])
            base_values[sid] = float(base_row["KnownG"])
            base_sigma[sid] = base_row["Sigma"]

        if mode == "hard_fixed":
            return self._build_network_hard_fixed(
                daily_dataframes, base_values,
                relative_sigma_source, manual_relative_sigma,
            )
        else:
            return self._build_network_partial(
                daily_dataframes, base_values, base_sigma,
                relative_sigma_source, manual_relative_sigma, manual_base_sigma,
            )

    def _relative_sigma_for_row(self, day_df, from_index, to_index, relative_sigma_source, manual_relative_sigma):
        """
        Sigma for the relative-tie observation connecting the two
        consecutive station visits at day_df rows `from_index` -> `to_index`.

        - "manual": one global sigma (manual_relative_sigma) for every tie.
        - "mean_sigma_column": the tie's sigma is the rigorous error
          propagation of the two endpoint visits' MeanSigma (each the
          standard error of that visit's mean reading, in mGal):

                sigma_dg = sqrt(sigma_from^2 + sigma_to^2)

          A DeltaG value is the difference of two visit means, so its
          variance is the sum of the two endpoint variances.
        """
        if relative_sigma_source == "manual":
            return manual_relative_sigma

        def _endpoint_sigma(row_index, endpoint_label):
            value = day_df.iloc[row_index]["MeanSigma"]
            if pd.isna(value):
                raise AdjustmentError(
                    f"MeanSigma is missing (blank/NaN) for {endpoint_label} "
                    f"(row {row_index}) of a day file. Every relative-tie "
                    "observation needs sigma values for BOTH endpoint visits "
                    "when relative_sigma_source='mean_sigma_column'."
                )
            return float(value)

        sigma_from = _endpoint_sigma(from_index, "the 'from' visit")
        sigma_to = _endpoint_sigma(to_index, "the 'to' visit")
        return float(np.sqrt(sigma_from ** 2 + sigma_to ** 2))

    def _build_network_partial(
        self, daily_dataframes, base_values, base_sigma,
        relative_sigma_source, manual_relative_sigma, manual_base_sigma,
    ):
        """
        Approach A: base stations remain as unknowns in X, appearing
        as their own weighted pseudo-observation rows, exactly like
        relative ties -- just with a single +1 coefficient instead of
        a -1/+1 pair.
        """
        station_order = {}
        for day_df in daily_dataframes:
            for station in day_df["Station"]:
                station_order.setdefault(self._normalize_station_id(station), None)
        for sid in base_values:
            station_order.setdefault(sid, None)

        station_ids = list(station_order.keys())
        station_index = {sid: idx for idx, sid in enumerate(station_ids)}
        num_stations = len(station_ids)

        if num_stations == 0:
            raise AdjustmentError("No stations found in the provided data.")

        rows_A, rows_L, rows_sigma, obs_labels = [], [], [], []

        for day_number, day_df in enumerate(daily_dataframes, start=1):
            for i in range(1, len(day_df)):
                from_station = self._normalize_station_id(day_df.iloc[i - 1]["Station"])
                to_station = self._normalize_station_id(day_df.iloc[i]["Station"])
                delta_g = day_df.iloc[i]["DeltaG"]
                if pd.isna(delta_g):
                    continue

                sigma_value = self._relative_sigma_for_row(
                    day_df, i - 1, i, relative_sigma_source, manual_relative_sigma
                )

                row = np.zeros(num_stations)
                row[station_index[to_station]] += 1.0
                row[station_index[from_station]] -= 1.0

                rows_A.append(row)
                rows_L.append(float(delta_g))
                rows_sigma.append(sigma_value)
                obs_labels.append(f"Day {day_number}: {from_station} -> {to_station} (DeltaG)")

        for sid, known_g in base_values.items():
            row = np.zeros(num_stations)
            row[station_index[sid]] = 1.0
            raw_sigma = base_sigma.get(sid)
            sigma_value = manual_base_sigma if (raw_sigma is None or pd.isna(raw_sigma)) else float(raw_sigma)

            rows_A.append(row)
            rows_L.append(known_g)
            rows_sigma.append(sigma_value)
            obs_labels.append(f"Base Station: {sid} (Known G)")

        if not rows_A:
            raise AdjustmentError("No valid observations could be built from the provided files.")

        A = np.array(rows_A)
        L = np.array(rows_L)
        sigma = np.array(rows_sigma, dtype=float)

        return A, L, sigma, station_ids, obs_labels, []

    def _build_network_hard_fixed(
        self, daily_dataframes, base_values,
        relative_sigma_source, manual_relative_sigma,
    ):
        """
        Approach B: base stations are eliminated from X entirely.
        Every relative-tie row touching a base station has that
        station's known value substituted in and moved to the L side;
        only rows between two free stations keep the usual -1/+1 form.
        Rows where BOTH endpoints are fixed contribute no unknowns and
        are reported as closure_checks instead of being added to A/L.
        """
        free_station_order = {}
        for day_df in daily_dataframes:
            for station in day_df["Station"]:
                sid = self._normalize_station_id(station)
                if sid not in base_values:
                    free_station_order.setdefault(sid, None)

        station_ids = list(free_station_order.keys())
        station_index = {sid: idx for idx, sid in enumerate(station_ids)}
        num_stations = len(station_ids)

        # NOTE: we deliberately do NOT raise here even if num_stations==0.
        # A day where every observation ties two fixed base stations
        # together (no free stations at all) is a legitimate scenario --
        # it produces closure_checks (diagnostic only) but no solvable
        # rows. Whether that's "an error" depends on whether there's
        # ANYTHING useful to report, which we only know after the loop
        # below runs -- see the check after the loop.

        rows_A, rows_L, rows_sigma, obs_labels = [], [], [], []
        closure_checks = []

        for day_number, day_df in enumerate(daily_dataframes, start=1):
            for i in range(1, len(day_df)):
                from_station = self._normalize_station_id(day_df.iloc[i - 1]["Station"])
                to_station = self._normalize_station_id(day_df.iloc[i]["Station"])
                delta_g = day_df.iloc[i]["DeltaG"]
                if pd.isna(delta_g):
                    continue

                from_fixed = from_station in base_values
                to_fixed = to_station in base_values

                if from_fixed and to_fixed:
                    # Both endpoints known -- no unknowns to solve for.
                    # Report as a diagnostic closure check instead.
                    implied_delta = base_values[to_station] - base_values[from_station]
                    closure_checks.append({
                        "label": f"Day {day_number}: {from_station} -> {to_station} (both fixed)",
                        "observed_delta_g": float(delta_g),
                        "implied_delta_g": implied_delta,
                        "discrepancy": float(delta_g) - implied_delta,
                    })
                    continue

                sigma_value = self._relative_sigma_for_row(
                    day_df, i - 1, i, relative_sigma_source, manual_relative_sigma
                )

                row = np.zeros(num_stations)
                if from_fixed:
                    # x_to = delta_g + KnownG(from)
                    row[station_index[to_station]] = 1.0
                    adjusted_L = float(delta_g) + base_values[from_station]
                elif to_fixed:
                    # -x_from = delta_g - KnownG(to)
                    row[station_index[from_station]] = -1.0
                    adjusted_L = float(delta_g) - base_values[to_station]
                else:
                    row[station_index[to_station]] += 1.0
                    row[station_index[from_station]] -= 1.0
                    adjusted_L = float(delta_g)

                rows_A.append(row)
                rows_L.append(adjusted_L)
                rows_sigma.append(sigma_value)
                obs_labels.append(f"Day {day_number}: {from_station} -> {to_station} (DeltaG)")

        if not rows_A and not closure_checks:
            raise AdjustmentError(
                "No valid observations could be built from the provided files."
            )

        # rows_A may legitimately be empty (e.g. every observation tied
        # two fixed stations together, contributing only closure_checks)
        # -- construct A with the correct column count either way, so
        # its shape stays meaningful even with zero rows.
        A = np.array(rows_A) if rows_A else np.zeros((0, num_stations))
        L = np.array(rows_L)
        sigma = np.array(rows_sigma, dtype=float)

        return A, L, sigma, station_ids, obs_labels, closure_checks

    # ------------------------------------------------------------------
    # WEIGHTED SOLVE (used by both modes)
    # ------------------------------------------------------------------
    def solve(self, A: np.ndarray, L: np.ndarray, sigma: np.ndarray,
              station_ids: list, obs_labels: list):
        """
        Solve the weighted normal equations:
            X = (A^T P A)^-1 A^T P L,   P = diag(1/sigma_i^2)

        Passing sigma as an array of all-ones is equivalent to the
        unweighted solve (every observation weighted equally).

        Returns:
            (results_df, residuals_df)

        Raises:
            AdjustmentError: if A^T P A is singular, or any sigma is
                zero (which would make the weight infinite -- mode=
                "hard_fixed" avoids this by construction; mode="partial"
                should never be passed a literal zero sigma for this
                reason).
        """
        if A.shape[0] == 0 or A.shape[1] == 0:
            raise AdjustmentError(
                "Nothing to solve -- there are no observations connecting "
                "any free stations (only closure checks, if any). Nothing "
                "further to do here; see closure_checks for diagnostics."
            )

        if np.any(sigma <= 0):
            raise AdjustmentError(
                "One or more observations has sigma <= 0, which would "
                "produce an infinite weight (1/sigma^2). If you intended "
                "a station to be treated as an immovable fixed point, use "
                "mode='hard_fixed' instead of assigning it sigma=0 in "
                "mode='partial'."
            )

        weights = 1.0 / (sigma ** 2)

        # Solve via the square-root-weighted design matrix instead of
        # forming the normal equations A^T P A directly: np.linalg.lstsq
        # uses an SVD, whose condition number scales like the SQUARE ROOT
        # of the normal-equation condition number -- far more robust when
        # observation weights span many orders of magnitude (e.g. tight
        # relative ties from MeanSigma vs. looser base-station pseudo-
        # observations). The solution X is identical either way.
        sqrt_w = np.sqrt(weights)
        weighted_A = sqrt_w[:, None] * A
        weighted_L = sqrt_w * L

        # An underdetermined/rank-deficient system (e.g. a sub-network
        # with no path to a base station) would silently return an
        # arbitrary particular solution from lstsq -- detect it and
        # surface the same helpful error as before.
        if np.linalg.matrix_rank(weighted_A) < weighted_A.shape[1]:
            raise AdjustmentError(
                "The network adjustment could not be solved -- the system "
                "is singular (rank-deficient). This usually means the "
                "network isn't fully tied to at least one base station, "
                "or some stations have no measurement path connecting "
                "them to the rest of the network. Check that your Base "
                "Station Reference file covers the network and that all "
                "stations are connected by at least one circuit."
            )

        X, _, _, _ = np.linalg.lstsq(weighted_A, weighted_L, rcond=None)

        results_df = pd.DataFrame({"Station": station_ids, "AdjustedGValue": X})
        residuals = A @ X - L
        residuals_df = pd.DataFrame({"Observation": obs_labels, "Residual": residuals})

        # --- A posteriori statistics (weighted) ---
        # n observations, m unknowns -> redundancy dof = n - m. When
        # dof <= 0 the system has no redundancy left for a variance
        # estimate, so the variance factor is undefined (NaN).
        n_obs = len(L)
        m_unknowns = A.shape[1]
        dof = n_obs - m_unknowns

        if dof > 0:
            variance_factor = float(np.sum(residuals ** 2 * weights) / dof)
        else:
            variance_factor = float("nan")

        # Parameter covariance matrix from the SVD of the weighted
        # design matrix: Cov = V diag(1/S^2) V^T * variance_factor.
        # (Recompute the SVD explicitly -- cheap for adjustment-sized
        # systems -- to obtain V and S directly.)
        try:
            _, S, Vt = np.linalg.svd(weighted_A, full_matrices=False)
            s_inv_sq = np.where(S > 1e-12, 1.0 / (S ** 2), 0.0)
            covariance = (Vt.T * s_inv_sq) @ Vt * variance_factor
            std_errors = np.sqrt(np.clip(np.diag(covariance), 0, None))
        except np.linalg.LinAlgError:
            covariance = None
            std_errors = np.full(m_unknowns, np.nan)

        results_df["StdError"] = std_errors
        results_df.attrs["statistics"] = {
            "n_observations": n_obs,
            "m_unknowns": m_unknowns,
            "degrees_of_freedom": dof,
            "variance_factor": variance_factor,
            "a_posteriori_sigma": (
                float(variance_factor ** 0.5)
                if np.isfinite(variance_factor) and variance_factor >= 0
                else float("nan")
            ),
            "covariance": covariance,
            "std_errors": std_errors,
        }

        return results_df, residuals_df

    def solve_unweighted(self, A: np.ndarray, L: np.ndarray, station_ids: list, obs_labels: list):
        """
        Backward-compatible convenience wrapper: solve with every
        observation weighted equally (sigma=1 for all rows). Equivalent
        to the original Phase A solver before weighting was added.
        """
        sigma = np.ones(len(L))
        return self.solve(A, L, sigma, station_ids, obs_labels)
