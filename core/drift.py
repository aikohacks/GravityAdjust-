"""
core/drift.py
-------------
Drift correction logic for the Gravity Adjustment Software.

Implements the "circuit drift" method as taught by the survey mentor:

    1. Each station is visited and read one or more times in quick
       succession (a "visit"). We take the mean time and mean reading
       of each visit.
    2. A "circuit" is a closed loop: it starts at a base station and
       later returns to that same station (the station ID repeats).
    3. Total drift over the circuit = first visit's mean reading minus
       the closing (repeat) visit's mean reading.
    4. Total time over the circuit = elapsed minutes between the first
       and closing visit's mean times.
    5. Drift rate = total drift / total time (drift per minute).
    6. Each visit's own drift = drift rate * (elapsed minutes since the
       first visit of the circuit).
    7. Corrected reading = mean reading + that visit's drift.
    8. Delta g between consecutive visits = (corrected[i] - corrected[i-1]) / 1000.
    9. G value chains from a user-supplied known/absolute G value:
       G[0] = known value; G[i] = G[i-1] + delta_g[i].

This module contains NO GUI code -- it is pure computation, called from
gui.py's drift-correction slot.

IMPORTANT ASSUMPTIONS (confirmed with the user/mentor so far):
    - A station "visit" is a contiguous run of one or more consecutive
      rows sharing the same Station ID -- the number of sub-readings
      per visit is NOT fixed (it can vary stop-to-stop), and the number
      of station stops in a day's circuit is NOT fixed either -- a
      circuit may be 5 stops, 7, 15, or any length. Visit boundaries
      are detected by where the Station ID changes between consecutive
      rows, not by a fixed block size.
    - A circuit is detected by station IDs repeating (first visit's
      station ID matches a later visit's station ID), not by an
      explicit "loop/circuit ID" column.
    - Time values are given as text like "1:36", meaning 1 hour and
      36 minutes (H:MM clock format, NOT a decimal fraction of an
      hour). The legacy "H.MM" dot-separated format (e.g. "1.36") is
      still accepted for backward compatibility with older field data.
    - The "known G value" is entered manually by the user (it comes
      from an absolute gravimeter reading), not looked up from a table.
    - The /1000 scale factor in delta-g is a fixed constant.
    - Imported CSV/Excel headers may vary slightly in wording (e.g.
      "Station ID" instead of "Station") -- these are normalized to
      the canonical column names before processing (see COLUMN_ALIASES).

These assumptions were derived from a single worked example and should
be re-validated against real field data once available.
"""

import pandas as pd


class DriftCorrectionError(Exception):
    """Raised when drift correction cannot be performed on the given data."""
    pass


class DriftCorrector:
    """
    Performs circuit-based drift correction on gravity observations.

    Usage:
        corrector = DriftCorrector()
        results_df = corrector.compute(raw_df, known_g_value=979.436285)
    """

    # Column names expected in the raw observation DataFrame.
    COL_STATION = "Station"
    COL_TIME = "Time"
    COL_READING = "Reading"

    # Keyword-based header matching: a raw CSV/Excel header is mapped to
    # a canonical column name if it contains one of these keywords as a
    # whole word (case-insensitive, punctuation/underscores treated as
    # word separators). This is deliberately fuzzy rather than an exact
    # alias whitelist, so headers we didn't anticipate in advance (e.g.
    # "Station No.", "STATION_ID", "Gravity Reading (mGal)") still match
    # without needing a code change every time a new field-CSV format
    # shows up. Order matters: canonical names earlier in this dict are
    # checked first, so a header like "Reading Time" (which contains
    # both "reading" and "time") resolves to Time, not Reading, because
    # Time is checked before Reading.
    COLUMN_KEYWORDS = {
        "Station": ["station", "site"],
        "Time": ["time"],
        "Reading": ["reading", "gravity", "grav"],
    }

    def __init__(self, readings_per_visit: int = None, reading_precision: int = 3, drift_precision: int = 3):
        # readings_per_visit is kept only for backward-compatibility with
        # existing call sites (e.g. gui.py's DriftCorrector(readings_per_visit=5))
        # and is no longer used to determine visit boundaries -- visits
        # are now detected dynamically by Station ID changing between
        # consecutive rows (see _group_into_visits), since the number
        # of sub-readings per stop and the number of stops per circuit
        # both vary in real field data. It has no effect on computation.
        self.readings_per_visit = readings_per_visit
        # The mentor's worked example rounds the mean reading (and the
        # drift applied to it) to the same decimal precision as the raw
        # readings themselves before using them in further calculations
        # -- it is NOT carried through in full floating-point precision.
        # This matters: rounding here changes the final corrected reading
        # by a small but real amount compared to using raw float means.
        self.reading_precision = reading_precision
        self.drift_precision = drift_precision

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------
    def compute(self, raw_df: pd.DataFrame, known_g_value: float) -> pd.DataFrame:
        """
        Run the full drift-correction pipeline on raw observation data.

        Args:
            raw_df: DataFrame with columns Station, Time, Reading (or
                recognized aliases such as "Station ID") -- one row per
                sub-reading. Consecutive rows sharing the same Station
                ID form one "visit"; a visit can be any length (1 or
                more rows), and a circuit (day's run) can contain any
                number of visits.
            known_g_value: absolute gravity value (mGal or gal, per your
                convention) for the very first visit of the circuit,
                entered manually by the surveyor.

        Returns:
            DataFrame with one row per station visit, columns:
            Station, MeanTime (minutes), MeanReading, Drift,
            CorrectedReading, DeltaG, GValue.

        Raises:
            DriftCorrectionError: if required columns are missing, or
                if the data doesn't close into a circuit (first and
                last station IDs don't match).
        """
        raw_df = self._normalize_columns(raw_df)
        self._validate_columns(raw_df)

        visits = self._group_into_visits(raw_df)
        self._validate_circuit_closure(visits)

        visits = self._compute_mean_time_and_reading(visits)
        visits = self._unwrap_12hr_rollover(visits)
        total_time, total_drift, drift_rate = self._compute_circuit_drift_rate(visits)

        results = self._apply_drift_and_gvalue(visits, drift_rate, known_g_value)

        results.attrs["total_time_minutes"] = total_time
        results.attrs["total_drift"] = total_drift
        results.attrs["drift_rate_per_minute"] = drift_rate

        return results

    # ------------------------------------------------------------------
    # TIME PARSING
    # ------------------------------------------------------------------
    @staticmethod
    def parse_time_to_minutes(time_value) -> float:
        """
        Convert a time value like "1:36" (1 hour, 36 minutes) into total
        minutes (96.0 in this example).

        The convention here is H:MM -- clock hours and literal clock
        minutes, NOT a decimal fraction of an hour. Minutes are assumed
        to be given as two digits (e.g. "1:05" for 1:05, not "1:5"),
        though a single digit is still accepted and zero-padded.

        For backward compatibility with older field data recorded as
        "H.MM" (dot separator, e.g. "1.36"), a "." is also accepted as
        a separator if no ":" is present -- both mean the same thing.
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
    # INTERNAL STEPS
    # ------------------------------------------------------------------
    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Rename raw CSV/Excel headers to the canonical names ('Station',
        'Time', 'Reading') this module expects, using fuzzy keyword
        matching (see COLUMN_KEYWORDS) rather than an exact-match
        whitelist. This means headers we didn't explicitly anticipate
        -- different capitalization, punctuation, extra words like
        "No." or units -- are still recognized as long as they contain
        a relevant keyword as a whole word.

        Exactly one raw column is mapped per canonical name (the first
        match found, scanning left to right through the DataFrame's
        columns). If a header could match multiple canonical names
        (e.g. "Reading Time" contains both "reading" and "time"), the
        canonical name checked earlier in COLUMN_KEYWORDS wins -- Time
        is checked before Reading, so "Reading Time" resolves to Time.
        """
        already_mapped_raw_columns = set()
        rename_map = {}

        for canonical_name, keywords in self.COLUMN_KEYWORDS.items():
            for col in df.columns:
                if col in already_mapped_raw_columns:
                    continue
                if self._header_matches_keywords(col, keywords):
                    rename_map[col] = canonical_name
                    already_mapped_raw_columns.add(col)
                    break  # only take the first matching raw column for this canonical name

        return df.rename(columns=rename_map)

    @staticmethod
    def _header_matches_keywords(header, keywords) -> bool:
        """
        True if `header` contains any of `keywords` as a whole word,
        case-insensitively. Punctuation, underscores, and hyphens are
        treated as word separators ("Station_ID", "Station-No.",
        "STATION NO" all tokenize to include the word "station"), and
        camelCase/concatenated headers are also split at lowercase-to-
        uppercase transitions ("StationID" -> "Station ID") before
        tokenizing, so no-separator headers are recognized too.
        """
        import re
        text = str(header).strip()
        text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)  # StationID -> Station ID
        tokens = re.split(r"[^a-zA-Z0-9]+", text.lower())
        tokens = [t for t in tokens if t]  # drop empty strings from split
        return any(keyword in tokens for keyword in keywords)

    def _validate_columns(self, df: pd.DataFrame):
        required = {self.COL_STATION, self.COL_TIME, self.COL_READING}
        missing = required - set(df.columns)
        if missing:
            raise DriftCorrectionError(
                f"Missing required column(s) for drift correction: "
                f"{', '.join(sorted(missing))}. "
                f"Expected columns: {', '.join(sorted(required))}."
            )

    def _group_into_visits(self, df: pd.DataFrame):
        """
        Split the raw rows into visits, where a visit is a contiguous
        run of one or more consecutive rows that share the same
        Station ID. This does NOT assume a fixed number of sub-readings
        per visit, and does NOT assume a fixed number of visits per
        circuit -- both vary in real field data (e.g. a day's circuit
        might be 5 stops, 7 stops, or 15 stops before closing back on
        the starting station).

        Boundaries are detected purely by where the Station column
        value changes between consecutive rows, preserving original
        row order.

        Example: Station column values
            A A A B B B B C C A
        produces 4 visits: [A,A,A], [B,B,B,B], [C,C], [A]
        (the last single-row [A] visit is the closing repeat of the
        base station).
        """
        if len(df) == 0:
            raise DriftCorrectionError("No observation data to process.")

        station_series = df[self.COL_STATION].reset_index(drop=True)
        time_series = df[self.COL_TIME].reset_index(drop=True)
        reading_series = df[self.COL_READING].reset_index(drop=True)

        # A new visit starts whenever the station value differs from
        # the previous row's station value. cumsum() of that boolean
        # gives each contiguous run a unique increasing group id.
        visit_group_id = (station_series != station_series.shift()).cumsum()

        visits = []
        for _, row_indices in station_series.groupby(visit_group_id).groups.items():
            rows = list(row_indices)
            visits.append({
                "station": station_series.iloc[rows[0]],
                "times": [time_series.iloc[i] for i in rows],
                "readings": [reading_series.iloc[i] for i in rows],
            })

        return visits

    def _validate_circuit_closure(self, visits):
        """Check that the circuit closes: first and last visit share a station ID."""
        if len(visits) < 2:
            raise DriftCorrectionError(
                "At least two station visits (start and closing repeat) "
                "are required to compute circuit drift."
            )

        first_station = visits[0]["station"]
        last_station = visits[-1]["station"]

        if first_station != last_station:
            raise DriftCorrectionError(
                f"The circuit does not close: the first visit is station "
                f"'{first_station}' but the last visit is station "
                f"'{last_station}'. Drift correction requires the survey "
                f"to start and end at the same base station."
            )

    def _compute_mean_time_and_reading(self, visits):
        """Add mean time (in minutes) and mean reading to each visit dict."""
        for visit in visits:
            minutes_list = [self.parse_time_to_minutes(t) for t in visit["times"]]
            visit["mean_time_minutes"] = sum(minutes_list) / len(minutes_list)
            # Round to instrument precision, matching the mentor's manual
            # method -- downstream drift math uses this rounded value,
            # not the full-precision float mean.
            raw_mean = sum(visit["readings"]) / len(visit["readings"])
            visit["mean_reading"] = round(raw_mean, self.reading_precision)
        return visits

    def _unwrap_12hr_rollover(self, visits):
        """
        Correct for 12-hour clock rollover across the circuit.

        Field data is often recorded on a 12-hour clock (hours cycle
        1-12, then wrap back to 1) with no AM/PM marker and no date
        field. A circuit that runs long enough to cross that 12:00
        boundary -- e.g. a visit at "12:38" followed later by a visit
        at "01:03" -- means the clock wrapped forward, NOT that time
        went backward. Without correction, that next visit's raw
        mean_time_minutes would be smaller than the previous visit's,
        which breaks every downstream elapsed-time calculation.

        This walks the visits in order and adds 720 minutes (12 hours)
        every time a visit's mean time is earlier than the previous
        (already-corrected) visit's mean time, so mean_time_minutes
        becomes monotonically non-decreasing across the whole circuit.
        Handles multiple rollovers in a single circuit if the survey
        runs long enough to wrap more than once.
        """
        offset = 0.0
        previous_corrected_time = None

        for visit in visits:
            corrected_time = visit["mean_time_minutes"] + offset
            while previous_corrected_time is not None and corrected_time < previous_corrected_time:
                offset += 12 * 60
                corrected_time = visit["mean_time_minutes"] + offset
            visit["mean_time_minutes"] = corrected_time
            previous_corrected_time = corrected_time

        return visits

    def _compute_circuit_drift_rate(self, visits):
        """
        Compute the circuit-level total time, total drift, and drift rate,
        using the first and last (closing) visits.
        """
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
        """Apply per-visit drift, corrected reading, delta-g, and G value."""
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

            rows.append({
                "Station": visit["station"],
                "MeanTime": visit["mean_time_minutes"],
                "MeanReading": visit["mean_reading"],
                "Drift": drift,
                "CorrectedReading": corrected_reading,
                "DeltaG": delta_g,
                "GValue": g_value,
            })

            previous_corrected = corrected_reading

        return pd.DataFrame(rows)


def format_minutes_to_clock(total_minutes: float) -> str:
    """
    Inverse of DriftCorrector.parse_time_to_minutes(). Converts total
    elapsed minutes back into 'H:MM' clock-style display string (colon
    separates hours from literal clock minutes -- NOT a decimal point).

    Used by the GUI (gui.py) for display purposes only -- all internal
    drift/rate calculations continue to use the raw float-minutes value,
    not this formatted string.

    Example: 98.0 minutes -> "1:38"  (1 hour, 38 minutes)
    """
    hours = int(total_minutes // 60)
    minutes = round(total_minutes % 60)
    if minutes == 60:  # handles rounding edge case, e.g. 59.6 -> 60
        hours += 1
        minutes = 0
    return f"{hours}:{minutes:02d}"