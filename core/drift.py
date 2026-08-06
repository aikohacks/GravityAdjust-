"""
core/drift.py
--------------
Circuit drift correction logic for the Gravity Adjustment Software.

See core/line_drift.py for the multi-day extension of this same method.
This module contains NO GUI code -- it is pure computation.
"""

import re
import warnings

import pandas as pd


class DriftCorrectionError(Exception):
    """Raised when drift correction cannot be performed on the given data."""
    pass


def format_minutes_to_clock(total_minutes: float) -> str:
    """
    Convert total minutes past midnight (e.g. 511.0) back into an
    HH:MM clock-time display string (e.g. "08:31"), matching how the
    time is recorded in the original field data sheets. Used for
    display in the GUI and when exporting to Excel/PDF.

    Values are minutes from midnight, wrapped modulo 24 hours (1440
    min). The drift-unwrap step can push a visit past the 12:00 mark
    (e.g. 13:00 -> 780 min); the 24-hour wrap keeps such times
    displaying as "13:00" rather than "01:00".
    """
    wrapped = total_minutes % 1440
    hours = int(wrapped // 60)
    minutes = int(round(wrapped % 60))
    if minutes == 60:
        minutes = 0
        hours += 1
    hours %= 24  # rounding edge (e.g. 23:59:30 -> 24:00 -> 00:00)
    return f"{hours:02d}:{minutes:02d}"


class DriftCorrector:
    """
    Performs circuit-based drift correction on gravity observations.

    Usage:
        corrector = DriftCorrector()
        results_df = corrector.compute(raw_df, known_g_value=979.436285)
    """

    COLUMN_KEYWORDS = {
        "Station": ["station", "site"],
        "Time": ["time"],
        "Reading": ["reading", "gravity", "grav"],
    }

    # Floor for the per-visit MeanSigma (standard error of the mean),
    # expressed in milligals. MeanSigma is converted from raw reading
    # (counter) units into mGal in _apply_drift_and_gvalue -- the same
    # /1000.0 conversion applied to DeltaG -- so the Phase 5 weighting
    # scheme uses consistent units (base-station Sigma values in the
    # reference file are also mGal). A visit whose sub-readings are all
    # identical has a sample std of 0, and a single-reading visit has no
    # std at all -- either would become an infinite weight (1/sigma^2)
    # in the weighted adjustment. Flooring at 0.01 microGal (1e-5 mGal)
    # keeps such degenerate visits finite. The floor sits well below the
    # repeatability of any real gravimeter (CG-5/CG-6: ~1-5 microGal =
    # 1e-3..5e-3 mGal), so it never distorts genuine data -- it only
    # caps the weight of degenerate zero-variance visits. The SVD-based
    # solve in core.adjustment keeps even extreme weight ratios
    # numerically safe. Overridable per instance via `min_sigma_mgal`.
    MIN_SIGMA_MGAL = 1e-5

    def __init__(self, reading_precision: int = 3, drift_precision: int = 3,
                 readings_per_visit: int = None, min_sigma_mgal: float = None):
        self.reading_precision = reading_precision
        self.drift_precision = drift_precision
        if min_sigma_mgal is not None:
            self.MIN_SIGMA_MGAL = min_sigma_mgal
        # readings_per_visit is accepted but unused -- kept only for
        # backward compatibility with older call sites; visit grouping
        # is dynamic (see _group_into_visits), not a fixed block size.

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------
    def compute(self, raw_df: pd.DataFrame, known_g_value: float = None) -> pd.DataFrame:
        """
        Run the full drift-correction pipeline on raw observation data.

        Args:
            raw_df: raw observation rows (Station, Time, Reading, or
                fuzzy-matched aliases like Site, StationID, Gravity Reading).
            known_g_value: absolute gravity value for the first visit.
                If None, the GValue column is RELATIVE ONLY -- it starts
                at 0.0 and accumulates DeltaG from there, intended as raw
                input to a downstream least-squares network adjustment
                (Phase 5), which treats absolute base station values as
                separate observations rather than requiring them here.

        Returns:
            DataFrame with columns: Station, MeanTime, MeanReading,
            Drift, CorrectedReading, DeltaG, GValue, MeanSigma.
            MeanSigma is the standard error of the mean of that visit's
            raw sub-readings -- an internal precision estimate used by
            core.adjustment for weighted least squares (Phase B).
            attrs["is_absolute"] indicates whether GValue is a true
            absolute value or a relative-to-zero datum.
        """
        df = self._normalize_columns(raw_df)
        self._validate_columns(df)
        self._validate_data_quality(df)

        visits = self._group_into_visits(df)
        self._validate_circuit_closure(visits)

        visits = self._compute_mean_time_and_reading(visits)
        for visit in visits:
            if visit.get("outlier_count", 0):
                warnings.warn(
                    f"Station '{visit['station']}': {visit['outlier_count']} of "
                    f"{len(visit['readings'])} sub-reading(s) flagged as outliers "
                    f"(MAD > 3 sigma) and excluded from the visit mean."
                )
        visits = self._unwrap_12hr_rollover(visits)
        total_time, total_drift, drift_rate = self._compute_circuit_drift_rate(visits)

        is_absolute = known_g_value is not None
        seed_g_value = known_g_value if is_absolute else 0.0

        results = self._apply_drift_and_gvalue(visits, drift_rate, seed_g_value)

        results.attrs["total_time_minutes"] = total_time
        results.attrs["total_drift"] = total_drift
        results.attrs["drift_rate_per_minute"] = drift_rate
        results.attrs["is_absolute"] = is_absolute
        results.attrs["drift_quality"] = self._compute_drift_quality(visits, drift_rate)

        return results

    # ------------------------------------------------------------------
    # TIME PARSING
    # ------------------------------------------------------------------
    @staticmethod
    def parse_time_to_minutes(time_value) -> float:
        """
        Convert a time value into total minutes. Primary format is
        H:MM (colon). H.MM (dot) is kept for backward compatibility --
        the part after the separator is literal clock minutes, not a
        decimal fraction of an hour.
        """
        text = str(time_value).strip()

        if ":" in text:
            hour_part, minute_part = text.split(":", 1)
        elif "." in text:
            hour_part, minute_part = text.split(".", 1)
        else:
            hour_part, minute_part = text, "0"

        if len(minute_part) == 1:
            minute_part = minute_part + "0"

        try:
            hours = int(hour_part)
            minutes = int(minute_part)
        except ValueError as exc:
            raise DriftCorrectionError(
                f"Could not parse time value '{time_value}' as H:MM (e.g. '1:36')."
            ) from exc

        if minutes >= 60:
            raise DriftCorrectionError(
                f"Time value '{time_value}' has an invalid minute component "
                f"({minutes}); minutes must be 0-59."
            )

        return hours * 60 + minutes

    # ------------------------------------------------------------------
    # FUZZY HEADER MATCHING
    # ------------------------------------------------------------------
    @staticmethod
    def _tokenize_header(header: str):
        """Split a header into lowercase word tokens (punctuation/underscore/camelCase aware)."""
        spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(header))
        spaced = re.sub(r"[^A-Za-z0-9]+", " ", spaced)
        return [tok.lower() for tok in spaced.split() if tok]

    @classmethod
    def _header_matches_keywords(cls, header: str, keywords) -> bool:
        tokens = cls._tokenize_header(header)
        return any(keyword in tokens for keyword in keywords)

    @classmethod
    def _header_matches_all_keywords(cls, header: str, keywords) -> bool:
        """
        True only if EVERY keyword token appears in the header (AND
        semantics). Used for columns whose identity requires multiple
        tokens, e.g. MeanSigma = "mean" AND "sigma" -- so a plain
        "Sigma" column or a "MeanTime"/"MeanReading" header never
        matches it.
        """
        tokens = cls._tokenize_header(header)
        return all(keyword in tokens for keyword in keywords)

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        rename_map = {}
        for canonical, keywords in self.COLUMN_KEYWORDS.items():
            if canonical in df.columns:
                continue
            for col in df.columns:
                if self._header_matches_keywords(col, keywords):
                    rename_map[col] = canonical
                    break
        return df.rename(columns=rename_map)

    def _validate_columns(self, df: pd.DataFrame):
        required = set(self.COLUMN_KEYWORDS.keys())
        missing = required - set(df.columns)
        if missing:
            raise DriftCorrectionError(
                f"Missing required column(s) for drift correction: "
                f"{', '.join(sorted(missing))}. "
                f"Expected columns matching: Station/Site, Time, "
                f"Reading/Gravity."
            )

    # ------------------------------------------------------------------
    # VISIT GROUPING (dynamic block size)
    # ------------------------------------------------------------------
    def _group_into_visits(self, df: pd.DataFrame):
        """
        Split rows into visits: contiguous runs of rows sharing the
        same Station value, in original order. The number of
        sub-readings per visit may vary freely.
        """
        if len(df) == 0:
            raise DriftCorrectionError("No observation data to process.")

        station_series = df["Station"].reset_index(drop=True)
        block_id = (station_series != station_series.shift()).cumsum()

        visits = []
        for _, block in df.reset_index(drop=True).groupby(block_id):
            visits.append({
                "station": block["Station"].iloc[0],
                "times": block["Time"].tolist(),
                "readings": block["Reading"].tolist(),
            })
        return visits

    def _validate_circuit_closure(self, visits):
        """Check that the circuit closes: first and last visit share a station ID."""
        if len(visits) < 2:
            raise DriftCorrectionError(
                "At least two station visits (start and closing repeat) "
                "are required to compute circuit drift."
            )
        if visits[0]["station"] != visits[-1]["station"]:
            raise DriftCorrectionError(
                f"The circuit does not close: the first visit is station "
                f"'{visits[0]['station']}' but the last visit is station "
                f"'{visits[-1]['station']}'. Drift correction requires the "
                f"survey to start and end at the same base station."
            )

    def _detect_outliers(self, readings, threshold: float = 3.0):
        """
        Flag outlier sub-readings using the Median Absolute Deviation
        (MAD) method -- robust to the outliers themselves, unlike
        mean/std. A reading whose |z| = |x - median| / (1.4826 * MAD)
        exceeds `threshold` is flagged as an outlier.

        Returns a boolean mask aligned with `readings`. Degenerate
        inputs (fewer than 3 readings, or MAD == 0 -- i.e. all readings
        identical) never flag anything.
        """
        readings = pd.Series(readings, dtype=float)
        n = len(readings)
        if n < 3:
            return pd.Series([False] * n, index=readings.index)
        median = readings.median()
        mad = (readings - median).abs().median()
        if mad == 0:
            return pd.Series([False] * n, index=readings.index)
        z_scores = (readings - median) / (mad * 1.4826)
        return z_scores.abs() > threshold

    def _compute_mean_time_and_reading(self, visits):
        """
        Add mean time (in minutes), mean reading, and reading_sigma to
        each visit dict.

        - Outlier sub-readings (MAD, 3-sigma) are excluded from the
          visit mean and sigma so one bad reading cannot corrupt the
          visit estimate. The number excluded is kept on the visit as
          `outlier_count` for reporting.
        - reading_sigma is the standard error of the mean of the CLEAN
          sub-readings, in raw counter units (converted to mGal later
          in _apply_drift_and_gvalue).
        - Single-reading visits have no internal sigma estimate; they
          inherit the circuit-wide AVERAGE reading_sigma from the
          multi-reading visits (falling back to None -- and thus the
          MIN_SIGMA_MGAL floor -- only if no visit in the circuit has
          an estimate).
        """
        # First pass: per-visit mean, outlier rejection, and sigma.
        for visit in visits:
            minutes_list = [self.parse_time_to_minutes(t) for t in visit["times"]]
            visit["mean_time_minutes"] = sum(minutes_list) / len(minutes_list)

            readings = pd.Series(visit["readings"], dtype=float)
            is_outlier = self._detect_outliers(readings)
            visit["outlier_count"] = int(is_outlier.sum())

            clean = readings[~is_outlier]
            if len(clean) == 0:
                # Every reading flagged (pathological data) -- fall back
                # to the full set so we still produce an estimate, but
                # record that nothing was excluded.
                clean = readings
                visit["outlier_count"] = 0

            raw_mean = clean.mean()
            visit["mean_reading"] = round(raw_mean, self.reading_precision)

            n = len(clean)
            if n > 1:
                std_dev = clean.std(ddof=1)
                visit["reading_sigma"] = std_dev / (n ** 0.5)
            else:
                visit["reading_sigma"] = None

        # Second pass: single-reading visits inherit the circuit-wide
        # average sigma instead of masquerading as perfectly known.
        computed = [v["reading_sigma"] for v in visits if v["reading_sigma"] is not None]
        if computed:
            circuit_avg_sigma = sum(computed) / len(computed)
            for visit in visits:
                if visit["reading_sigma"] is None:
                    visit["reading_sigma"] = circuit_avg_sigma
        return visits

    def _compute_drift_quality(self, visits, drift_rate):
        """
        Assess how well the linear drift model fits the observed
        readings: R^2, RMS of residuals, max absolute residual, and the
        number of visits used. The linear model is the first visit's
        reading plus drift_rate * elapsed time.
        """
        first = visits[0]
        predicted, actual = [], []
        for visit in visits:
            elapsed = visit["mean_time_minutes"] - first["mean_time_minutes"]
            predicted.append(first["mean_reading"] + drift_rate * elapsed)
            actual.append(visit["mean_reading"])

        predicted = pd.Series(predicted, dtype=float)
        actual = pd.Series(actual, dtype=float)
        residuals = predicted - actual

        rms_residual = float((residuals ** 2).mean() ** 0.5)
        max_residual = float(residuals.abs().max())
        ss_tot = float(((actual - actual.mean()) ** 2).sum())
        ss_res = float((residuals ** 2).sum())
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        return {
            "rms_residual": rms_residual,
            "max_residual": max_residual,
            "r_squared": r_squared,
            "num_visits": len(visits),
        }

    def _validate_data_quality(self, df: pd.DataFrame):
        """
        Lightweight data-quality checks on the raw input. Currently
        warns on negative raw readings, which are invalid for gravity
        instruments and usually indicate a transcription error or a
        swapped column.
        """
        reading_series = df["Reading"]
        if (reading_series < 0).any():
            count = int((reading_series < 0).sum())
            warnings.warn(
                f"Data quality: {count} negative Reading value(s) found. "
                f"Gravity readings must be positive -- please check the data."
            )

    def _unwrap_12hr_rollover(self, visits):
        """
        Field data is on a 12-hour clock with no AM/PM marker. If a
        circuit runs long enough to cross the 12:00 mark, later visits
        will appear to have an earlier mean_time than previous visits.
        This walks visits in order and adds 720 minutes whenever that
        happens, making the whole circuit's timeline monotonic.
        """
        if not visits:
            return visits

        adjusted = [visits[0]["mean_time_minutes"]]
        offset = 0
        for i in range(1, len(visits)):
            candidate = visits[i]["mean_time_minutes"] + offset
            if candidate < adjusted[-1]:
                # Candidate is still earlier than the previous visit
                # even after the accumulated rollover offset -- it
                # crossed the 12:00 mark again. Add enough 720-minute
                # blocks to land after the previous visit, handling
                # circuits that span multiple 12-hour crossings.
                blocks = int((adjusted[-1] - candidate) // 720) + 1
                offset += 720 * blocks
                candidate = visits[i]["mean_time_minutes"] + offset
            adjusted.append(candidate)

        for visit, new_time in zip(visits, adjusted):
            visit["mean_time_minutes"] = new_time
        return visits

    def _compute_circuit_drift_rate(self, visits):
        first_visit = visits[0]
        last_visit = visits[-1]

        total_time = last_visit["mean_time_minutes"] - first_visit["mean_time_minutes"]
        if total_time <= 0:
            raise DriftCorrectionError(
                "Computed circuit total time is zero or negative -- check "
                "that observation times are in increasing order."
            )

        total_drift = first_visit["mean_reading"] - last_visit["mean_reading"]
        drift_rate = total_drift / total_time

        return total_time, total_drift, drift_rate

    def _apply_drift_and_gvalue(self, visits, drift_rate, known_g_value):
        first_visit = visits[0]
        rows = []

        previous_corrected = None
        g_value = known_g_value

        for visit in visits:
            elapsed = visit["mean_time_minutes"] - first_visit["mean_time_minutes"]
            drift = round(drift_rate * elapsed, self.drift_precision)
            corrected_reading = visit["mean_reading"] + drift

            if previous_corrected is None:
                delta_g = 0.0
            else:
                delta_g = (corrected_reading - previous_corrected) / 1000.0
                g_value = g_value + delta_g

            # MeanSigma: this visit's standard error of the mean,
            # converted from reading (counter) units to milligals -- the
            # same /1000.0 conversion applied to DeltaG above -- so the
            # weighting scheme in core.adjustment sees consistent units.
            # Degenerate visits (identical sub-readings, or a single
            # reading) get the MIN_SIGMA_MGAL floor instead of 0, which
            # would otherwise produce an infinite weight (1/sigma^2).
            raw_sigma = visit["reading_sigma"]
            if raw_sigma is None or raw_sigma <= 0:
                mean_sigma = self.MIN_SIGMA_MGAL
            else:
                mean_sigma = max(raw_sigma / 1000.0, self.MIN_SIGMA_MGAL)

            rows.append({
                "Station": visit["station"],
                "MeanTime": visit["mean_time_minutes"],
                "MeanReading": visit["mean_reading"],
                "Drift": drift,
                "CorrectedReading": corrected_reading,
                "DeltaG": delta_g,
                "GValue": g_value,
                "MeanSigma": mean_sigma,
            })

            previous_corrected = corrected_reading

        return pd.DataFrame(rows)
