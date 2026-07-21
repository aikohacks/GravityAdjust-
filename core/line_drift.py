"""
core/line_drift.py
-------------------
Line drift correction logic for the Gravity Adjustment Software.

Line Drift extends Circuit Drift (core/drift.py) across a multi-day
survey line, where the area being surveyed is too large to close in a
single day. Confirmed with the user/mentor:

    Day 1 (or any brand-new line's first day):
        Ordinary Circuit Drift. A closed loop starting and ending at
        the master base station ("1"), anchored on a manually-entered
        known G value. Identical to core/drift.py's DriftCorrector.

    Every subsequent day:
        The field sequence always has this shape:

            [1]  ->  [anchor]  ->  [new station(s)...]  ->  [1]

        - Stop 1: revisit the master base station ("1"). Its G value
          is NOT trusted this day -- drift resets daily.
        - Stop 2: the "anchor" -- the last NEW station reached on the
          PREVIOUS day. Its G value IS trusted (carried forward from
          the day it was first computed).
        - Stop 3 onward: brand-new stations for today (one or many).
        - Final stop: close back on station "1" again.

        Because the anchor's G is known but station 1's is not, the
        G-value chain is seeded "backward": the effective known G fed
        into the normal forward Delta-g chain is

            effective_known_g = anchor_g_value - delta_g(anchor)

        where delta_g(anchor) is the ordinary drift-corrected delta
        between the first "1" visit and the anchor visit. Chaining
        forward from that seed with the same Delta-g formula used by
        Circuit Drift automatically reproduces both:
            - station 1's back-calculated G value (the seed itself,
              "g1_short" -- the value obtained the short/direct way)
            - the closing station 1's G value after the full loop
              ("g1_long" -- the value obtained the long way, through
              all of today's new stations)
        The difference between g1_long and g1_short is the day's
        closing discrepancy -- a diagnostic value, NOT auto-corrected
        here (per the user: reconciling it is a separate downstream
        process).

        What carries forward to the NEXT day is the newly-computed G
        value of TODAY's last new station (the visit immediately
        before the closing repeat of "1") -- not station 1's G value.

This module contains NO GUI code -- it is pure computation, called
from gui.py. It reuses core.drift.DriftCorrector's internal row
grouping, time parsing, mean/time calculation, and 12-hour clock
rollover handling, so every robustness fix already validated for
Circuit Drift (fuzzy header matching, variable sub-readings per visit,
variable stops per day, H:MM/H.MM time parsing, 12hr clock wrap)
automatically applies to Line Drift too, rather than being
reimplemented and risking drift (no pun intended) between the two.

These assumptions were derived from the mentor's handwritten notes and
a real field-book excerpt, and should be re-validated against a full
multi-day worked example once available.
"""

import pandas as pd

from core.drift import DriftCorrector, DriftCorrectionError


class LineDriftError(Exception):
    """Raised when line drift correction cannot be performed on the given data."""
    pass


class LineDriftCorrector:
    """
    Performs multi-day line drift correction on gravity observations.

    Usage (per-day, e.g. separate CSVs imported one at a time):
        corrector = LineDriftCorrector()

        day1_results = corrector.compute_first_day(day1_df, known_g_value=979.436285)
        anchor_station = day1_results.attrs["next_anchor_station"]
        anchor_g_value = day1_results.attrs["next_anchor_g_value"]

        day2_results = corrector.compute_day(day2_df, anchor_station, anchor_g_value)
        anchor_station = day2_results.attrs["next_anchor_station"]
        anchor_g_value = day2_results.attrs["next_anchor_g_value"]
        ...

    Usage (combined multi-day file, split by a Date column):
        corrector = LineDriftCorrector()
        day_dataframes = corrector.split_by_date(combined_df, date_column="Date")
        all_results = corrector.compute_line(day_dataframes, known_g_value=979.436285)
    """

    # Column name expected for day-splitting a combined multi-day file.
    # Accepted aliases are matched the same fuzzy way as Station/Time/Reading.
    DATE_COLUMN_KEYWORDS = ["date", "day"]

    def __init__(self, reading_precision: int = 3, drift_precision: int = 3):
        self.reading_precision = reading_precision
        self.drift_precision = drift_precision
        # Composition, not inheritance: reuse DriftCorrector's row
        # grouping / time parsing / mean calc / 12hr unwrap machinery
        # via its internal (underscore) methods, rather than duplicating
        # that logic here.
        self._helper = DriftCorrector(
            reading_precision=reading_precision, drift_precision=drift_precision
        )

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------
    def compute_first_day(self, day_df: pd.DataFrame, known_g_value: float) -> pd.DataFrame:
        """
        Compute the first day of a brand-new line: ordinary Circuit
        Drift (see core.drift.DriftCorrector), plus identification of
        the next day's anchor station.

        Returns a DataFrame identical in shape to DriftCorrector.compute()
        (columns: Station, MeanTime, MeanReading, Drift, CorrectedReading,
        DeltaG, GValue), with two extra attrs:
            next_anchor_station: station ID to use as tomorrow's anchor
            next_anchor_g_value: that station's computed G value today
        """
        results = self._helper.compute(day_df, known_g_value)

        if len(results) < 2:
            raise LineDriftError(
                "Day 1 circuit must contain at least 2 station visits "
                "to identify a next-day anchor station."
            )

        # The next anchor is the last NEW station reached before the
        # closing repeat of the master base -- i.e. the second-to-last
        # visit in the closed circuit.
        last_new_station_row = results.iloc[-2]
        results.attrs["next_anchor_station"] = last_new_station_row["Station"]
        results.attrs["next_anchor_g_value"] = last_new_station_row["GValue"]

        return results

    def compute_day(self, day_df: pd.DataFrame, anchor_station_id, anchor_g_value: float) -> pd.DataFrame:
        """
        Compute a subsequent day of a line: sequence must be
        [master base] -> [anchor] -> [new station(s)...] -> [master base].

        Args:
            day_df: raw observation rows for this single day only
                (Station, Time, Reading columns, or recognized aliases).
            anchor_station_id: the station ID that should appear as the
                SECOND visit of the day (the trusted carry-over from
                yesterday).
            anchor_g_value: that anchor station's known/trusted G value.

        Returns:
            DataFrame (same columns as Circuit Drift's output), plus attrs:
                next_anchor_station: next day's anchor station ID
                next_anchor_g_value: that station's G value today
                g1_short: master base's G value computed the direct way
                    (via the first leg, master base -> anchor)
                g1_long: master base's G value computed the long way
                    (chained forward through all of today's stations)
                closure_discrepancy: g1_long - g1_short (diagnostic only;
                    NOT auto-corrected here -- reconciling it is a
                    separate downstream process)

        Raises:
            LineDriftError: if required columns are missing, if there
                are fewer than 3 visits (master base, anchor, closing
                master base at minimum), if the day doesn't close back
                on the same master base station it started on, or if
                the second visit's station doesn't match anchor_station_id.
        """
        raw_df = self._helper._normalize_columns(day_df)
        self._helper._validate_columns(raw_df)

        visits = self._helper._group_into_visits(raw_df)

        if len(visits) < 3:
            raise LineDriftError(
                "A line-drift day requires at least 3 station visits: "
                "the master base, the anchor station, and the closing "
                f"repeat of the master base. Got {len(visits)}."
            )

        master_base = visits[0]["station"]
        if visits[-1]["station"] != master_base:
            raise LineDriftError(
                f"The day does not close: it starts at station "
                f"'{master_base}' but ends at station '{visits[-1]['station']}'. "
                f"Every line-drift day must start and end at the same "
                f"master base station."
            )

        actual_second_station = visits[1]["station"]
        if str(actual_second_station) != str(anchor_station_id):
            raise LineDriftError(
                f"Expected the second visit of the day to be the anchor "
                f"station '{anchor_station_id}' (carried over from the "
                f"previous day), but found '{actual_second_station}' instead."
            )

        visits = self._helper._compute_mean_time_and_reading(visits)
        visits = self._helper._unwrap_12hr_rollover(visits)
        total_time, total_drift, drift_rate = self._helper._compute_circuit_drift_rate(visits)

        # Compute corrected readings for just the first two visits
        # (master base, anchor) to work out delta_g(anchor) -- corrected
        # reading depends only on drift_rate and elapsed time, not on
        # any G value, so this can be done before deciding the seed G.
        first_visit, anchor_visit = visits[0], visits[1]
        corrected_first = first_visit["mean_reading"] + round(
            drift_rate * 0.0, self.drift_precision
        )
        elapsed_anchor = anchor_visit["mean_time_minutes"] - first_visit["mean_time_minutes"]
        corrected_anchor = anchor_visit["mean_reading"] + round(
            drift_rate * elapsed_anchor, self.drift_precision
        )
        delta_g_anchor = (corrected_anchor - corrected_first) / 1000.0

        # Seed the forward Delta-g chain so that, after chaining forward
        # through the anchor, the anchor's G value comes out exactly
        # equal to the known anchor_g_value -- this reproduces both the
        # back-calculated station-1 value AND the correct forward chain
        # in a single pass, reusing the exact same chaining logic as
        # Circuit Drift.
        effective_known_g = anchor_g_value - delta_g_anchor

        results = self._helper._apply_drift_and_gvalue(visits, drift_rate, effective_known_g)

        results.attrs["total_time_minutes"] = total_time
        results.attrs["total_drift"] = total_drift
        results.attrs["drift_rate_per_minute"] = drift_rate

        g1_short = results.iloc[0]["GValue"]
        g1_long = results.iloc[-1]["GValue"]
        results.attrs["g1_short"] = g1_short
        results.attrs["g1_long"] = g1_long
        results.attrs["closure_discrepancy"] = g1_long - g1_short

        last_new_station_row = results.iloc[-2]
        results.attrs["next_anchor_station"] = last_new_station_row["Station"]
        results.attrs["next_anchor_g_value"] = last_new_station_row["GValue"]

        return results

    def compute_line(self, day_dataframes: list, known_g_value: float) -> list:
        """
        Chain compute_first_day() + compute_day() across an ordered
        list of per-day DataFrames (already split, whether that's from
        separate CSVs imported one at a time or split out of one
        combined file via split_by_date()).

        Args:
            day_dataframes: list of DataFrames, one per day, in
                chronological order.
            known_g_value: the manually-entered known G value for the
                very first day of the line.

        Returns:
            List of per-day result DataFrames, in the same order as
            day_dataframes, each with the same columns/attrs documented
            in compute_first_day() / compute_day().

        Raises:
            LineDriftError: if day_dataframes is empty, or propagated
                from compute_first_day()/compute_day() for any day.
        """
        if not day_dataframes:
            raise LineDriftError("No day data provided to compute_line().")

        all_results = []

        first_result = self.compute_first_day(day_dataframes[0], known_g_value)
        all_results.append(first_result)

        anchor_station = first_result.attrs["next_anchor_station"]
        anchor_g_value = first_result.attrs["next_anchor_g_value"]

        for day_number, day_df in enumerate(day_dataframes[1:], start=2):
            try:
                day_result = self.compute_day(day_df, anchor_station, anchor_g_value)
            except LineDriftError as exc:
                raise LineDriftError(f"Day {day_number}: {exc}") from exc

            all_results.append(day_result)
            anchor_station = day_result.attrs["next_anchor_station"]
            anchor_g_value = day_result.attrs["next_anchor_g_value"]

        return all_results

    def split_by_date(self, combined_df: pd.DataFrame, date_column: str = None) -> list:
        """
        Split one combined multi-day DataFrame into an ordered list of
        per-day DataFrames, using a Date (or Day) column to mark
        boundaries. Chronological order is preserved (sorted by the
        date column's natural sort order, then by original row order
        within a day).

        Args:
            combined_df: the full multi-day DataFrame, containing
                Station, Time, Reading (or aliases) PLUS a date/day
                column recognized by DATE_COLUMN_KEYWORDS.
            date_column: exact column name to split on, if you already
                know it. If None, it's auto-detected via fuzzy keyword
                matching (same approach as Station/Time/Reading).

        Returns:
            List of DataFrames, one per unique date value, in
            chronological order. The date column itself is dropped from
            each day's DataFrame before returning (downstream drift
            computation doesn't need it).

        Raises:
            LineDriftError: if no date column can be found/matched.
        """
        if date_column is None:
            date_column = self._find_date_column(combined_df)
        if date_column is None or date_column not in combined_df.columns:
            raise LineDriftError(
                "Could not find a Date/Day column to split the combined "
                "file into individual days. Expected a column whose "
                "header contains the word 'date' or 'day'."
            )

        day_groups = []
        # sort_values keeps rows within each date in original relative
        # order (stable sort), and orders the distinct dates themselves
        # chronologically.
        sorted_df = combined_df.sort_values(by=date_column, kind="stable")
        for _, day_df in sorted_df.groupby(date_column, sort=True):
            day_groups.append(day_df.drop(columns=[date_column]).reset_index(drop=True))

        return day_groups

    @staticmethod
    def _find_date_column(df: pd.DataFrame):
        """Fuzzy-match a Date/Day column the same way Station/Time/Reading are matched."""
        for col in df.columns:
            if DriftCorrector._header_matches_keywords(
                col, LineDriftCorrector.DATE_COLUMN_KEYWORDS
            ):
                return col
        return None