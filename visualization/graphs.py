"""
visualization/graphs.py
------------------------
Pure plotting logic for the Gravity Adjustment Software (Phase 7).

This module contains NO PySide6/GUI code. Each function takes a
matplotlib Axes object (already created and owned by the GUI layer's
FigureCanvasQTAgg) plus the relevant DataFrame, and draws onto that
Axes. It is called from gui.py's graph-refresh methods, the same way
core/drift.py's DriftCorrector is called from gui.py's processing
slots.

Data source reminder (from core/drift.py DriftCorrector.compute()):
    Columns available in the drift-corrected results DataFrame:
    Station, MeanTime, MeanReading, Drift, CorrectedReading,
    DeltaG, GValue.

Residual data (Station, Residual, ... ) does not exist yet -- it will
be produced by core/least_squares.py in Phase 5. The residual-related
functions below accept an optional DataFrame and render a clear
"not yet available" message when it is None or missing the expected
column, rather than raising.
"""

import numpy as np


# ----------------------------------------------------------------------
# Shared styling constants (kept consistent with the app's navy/blue
# professional theme used in gui.py's _apply_professional_style()).
# ----------------------------------------------------------------------
COLOR_PRIMARY = "#2c6fbb"
COLOR_SECONDARY = "#2c3e50"
COLOR_ACCENT = "#c0392b"
COLOR_GRID = "#d5dae1"


def _style_axes(ax, title: str, xlabel: str, ylabel: str):
    """Apply consistent title/label/grid styling to an Axes."""
    ax.set_title(title, fontsize=11, fontweight="bold", color=COLOR_SECONDARY)
    ax.set_xlabel(xlabel, fontsize=9.5, color=COLOR_SECONDARY)
    ax.set_ylabel(ylabel, fontsize=9.5, color=COLOR_SECONDARY)
    ax.grid(True, color=COLOR_GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _show_placeholder_message(ax, message: str):
    """
    Render a centered placeholder message on an otherwise empty Axes.
    Used when the data a graph needs doesn't exist yet (e.g. residuals
    before Phase 5 / Least Squares Adjustment has been run).
    """
    ax.axis("off")
    ax.text(
        0.5, 0.5, message,
        ha="center", va="center",
        fontsize=10.5, color=COLOR_SECONDARY, wrap=True,
        transform=ax.transAxes,
    )


# ----------------------------------------------------------------------
# Graph 1: Drift Curve
# ----------------------------------------------------------------------
def plot_drift_curve(ax, drift_df):
    """
    Plot applied drift (mGal-equivalent, per drift.py's units) against
    elapsed time (minutes) for each station visit in the circuit.

    Args:
        ax: matplotlib Axes to draw on.
        drift_df: DataFrame from DriftCorrector.compute(), must contain
            'MeanTime', 'Drift', and 'Station' columns. May be None if
            drift correction hasn't been run yet.
    """
    if drift_df is None or drift_df.empty:
        _show_placeholder_message(
            ax, "No drift-corrected data available.\nRun Drift Correction first."
        )
        return

    times = drift_df["MeanTime"].to_numpy()
    drift = drift_df["Drift"].to_numpy()
    stations = drift_df["Station"].astype(str).to_numpy()

    ax.plot(times, drift, color=COLOR_PRIMARY, linewidth=1.8, marker="o",
             markersize=5, markerfacecolor=COLOR_SECONDARY,
             markeredgecolor=COLOR_SECONDARY, zorder=3)

    for x, y, label in zip(times, drift, stations):
        ax.annotate(label, (x, y), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color=COLOR_SECONDARY)

    _style_axes(ax, "Drift Curve", "Elapsed Time (minutes)", "Applied Drift")


# ----------------------------------------------------------------------
# Graph 2: Raw vs Adjusted
# ----------------------------------------------------------------------
def plot_raw_vs_adjusted(ax, drift_df):
    """
    Plot mean raw reading vs drift-corrected reading per station visit.

    NOTE: Until Phase 5 (Least Squares Adjustment) exists, 'adjusted'
    here means 'drift-corrected' (CorrectedReading), not the final
    least-squares-adjusted value. This should be revisited once
    core/least_squares.py produces true adjusted values -- at that
    point this function should plot MeanReading vs the least-squares
    adjusted reading instead of CorrectedReading.

    Args:
        ax: matplotlib Axes to draw on.
        drift_df: DataFrame from DriftCorrector.compute(), must contain
            'Station', 'MeanReading', 'CorrectedReading'. May be None.
    """
    if drift_df is None or drift_df.empty:
        _show_placeholder_message(
            ax, "No drift-corrected data available.\nRun Drift Correction first."
        )
        return

    stations = drift_df["Station"].astype(str).to_numpy()
    x = np.arange(len(stations))
    raw = drift_df["MeanReading"].to_numpy()
    adjusted = drift_df["CorrectedReading"].to_numpy()

    ax.plot(x, raw, color=COLOR_ACCENT, linewidth=1.6, marker="s",
             markersize=5, label="Raw (Mean Reading)", zorder=3)
    ax.plot(x, adjusted, color=COLOR_PRIMARY, linewidth=1.6, marker="o",
             markersize=5, label="Drift-Corrected Reading", zorder=3)

    ax.set_xticks(x)
    ax.set_xticklabels(stations, fontsize=8.5)
    ax.legend(loc="best", fontsize=8.5, frameon=True)

    _style_axes(ax, "Raw vs Adjusted Gravity", "Station Visit", "Reading")


# ----------------------------------------------------------------------
# Graph 3: Residual Plot
# ----------------------------------------------------------------------
def plot_residual_plot(ax, adjustment_df):
    """
    Plot residuals per station/observation from the least squares
    adjustment.

    Args:
        ax: matplotlib Axes to draw on.
        adjustment_df: DataFrame expected to contain 'Station' (or an
            observation identifier) and 'Residual' columns, produced by
            core/least_squares.py (Phase 5). Not implemented yet, so
            this currently renders a placeholder for any input that
            doesn't have a 'Residual' column.
    """
    if adjustment_df is None or "Residual" not in getattr(adjustment_df, "columns", []):
        _show_placeholder_message(
            ax,
            "Residuals are not available yet.\n"
            "Requires Least Squares Adjustment (Phase 5)."
        )
        return

    labels = adjustment_df.iloc[:, 0].astype(str).to_numpy()
    residuals = adjustment_df["Residual"].to_numpy()
    x = np.arange(len(labels))

    colors = [COLOR_ACCENT if r < 0 else COLOR_PRIMARY for r in residuals]
    ax.bar(x, residuals, color=colors, zorder=3)
    ax.axhline(0, color=COLOR_SECONDARY, linewidth=1.0)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)

    _style_axes(ax, "Residual Plot", "Observation", "Residual")


# ----------------------------------------------------------------------
# Graph 4: Residual Histogram
# ----------------------------------------------------------------------
def plot_residual_histogram(ax, adjustment_df):
    """
    Plot a histogram of residuals from the least squares adjustment.

    Args:
        ax: matplotlib Axes to draw on.
        adjustment_df: DataFrame expected to contain a 'Residual'
            column, produced by core/least_squares.py (Phase 5). Not
            implemented yet, so this currently renders a placeholder
            for any input that doesn't have a 'Residual' column.
    """
    if adjustment_df is None or "Residual" not in getattr(adjustment_df, "columns", []):
        _show_placeholder_message(
            ax,
            "Residuals are not available yet.\n"
            "Requires Least Squares Adjustment (Phase 5)."
        )
        return

    residuals = adjustment_df["Residual"].to_numpy()

    ax.hist(residuals, bins=min(10, max(3, len(residuals) // 2)),
            color=COLOR_PRIMARY, edgecolor=COLOR_SECONDARY, zorder=3)
    ax.axvline(0, color=COLOR_ACCENT, linewidth=1.2, linestyle="--")

    _style_axes(ax, "Histogram of Residuals", "Residual", "Frequency")