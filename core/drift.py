"""
core/drift.py
--------------
Circuit drift correction logic for the Gravity Adjustment Software.

See core/line_drift.py for the multi-day extension of this same method.
This module contains NO GUI code -- it is pure computation.
"""

import re
import pandas as pd


class DriftCorrectionError(Exception):
    """Raised when drift correction cannot be performed on the given data."""
    pass


def format_minutes_to_clock(total_minutes: float) -> str:
    """
    Convert total minutes (e.g. 98.0) back into an H:MM display string
    (e.g. "1:38"), for readability in the GUI. Handles values that have
    been "unwrapped" past 12 hours (720 min) by taking mod 720 first.
    """
    wrapped = total_minutes % 720
    hours = int(wrapped // 60)
    minutes = int(round(wrapped % 60))
    if minutes == 60:
        minutes = 0
        hours += 1
    return f"{hours}:{minutes:02d}"


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
    # in the weighted adjustment. Flooring at 0.1 microGal (1e-4 mGal)
    # keeps such degenerate visits finite AND keeps the weight ratio
    # between the tightest relative tie and the base-station pseudo-
    # observations within safe double-precision bounds (a much smaller
    # floor, e.g. 1e-9 counter units ~ 1e-12 mGal, produces weight
    # ratios ~1e21 that silently corrupt the normal-equations solve).
    # 1e-4 mGal is also below the repeatability of any real gravimeter,
    # so it never distorts genuine data.
    MIN_SIGMA_MGAL = 1e-4

    def __init__(self, reading_precision: int = 3, drift_precision: int = 3, readings_per_visit: int = None):
        self.reading_precision = reading_precision
        self.drift_precision = drift_precision
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

        visits = self._group_into_visits(df)
        self._validate_circuit_closure(visits)

        visits = self._compute_mean_time_and_reading(visits)
        visits = self._unwrap_12hr_rollover(visits)
        total_time, total_drift, drift_rate = self._compute_circuit_drift_rate(visits)

        is_absolute = known_g_value is not None
        seed_g_value = known_g_value if is_absolute else 0.0

        results = self._apply_drift_and_gvalue(visits, drift_rate, seed_g_value)

        results.attrs["total_time_minutes"] = total_time
        results.attrs["total_drift"] = total_drift
        results.attrs["drift_rate_per_minute"] = drift_rate
        results.attrs["is_absolute"] = is_absolute

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

    def _compute_mean_time_and_reading(self, visits):
        """Add mean time (in minutes), mean reading, and reading_sigma to each visit dict."""
        for visit in visits:
            minutes_list = [self.parse_time_to_minutes(t) for t in visit["times"]]
            visit["mean_time_minutes"] = sum(minutes_list) / len(minutes_list)
            raw_mean = sum(visit["readings"]) / len(visit["readings"])
            visit["mean_reading"] = round(raw_mean, self.reading_precision)

            # Standard error of the mean, from the repeatability of this
            # visit's raw sub-readings -- an internal precision estimate
            # used downstream (Phase 5) to weight DeltaG observations.
            # Note: this captures short-term instrument/reading noise
            # only, not other error sources (drift-model uncertainty,
            # transport disturbance, temperature) -- documented as a
            # deliberate first-version limitation.
            # Standard error of the mean, in RAW reading (counter)
            # units. Kept in counter units here (may be 0 for identical
            # sub-readings, or None for single-reading visits); the
            # conversion to milligals and the positive floor both happen
            # in _apply_drift_and_gvalue where DeltaG is converted too.
            n = len(visit["readings"])
            if n > 1:
                std_dev = pd.Series(visit["readings"]).std(ddof=1)
                visit["reading_sigma"] = std_dev / (n ** 0.5)
            else:
                visit["reading_sigma"] = None
        return visits

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
                offset += 720
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
