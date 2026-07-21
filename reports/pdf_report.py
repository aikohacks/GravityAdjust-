"""
reports/pdf_report.py
----------------------
PDF report export logic for the Gravity Adjustment Software (Phase 9).

This module contains NO GUI code -- it is pure export logic, called
from gui.py's export slot. It builds a paginated PDF report from the
same pandas DataFrames already displayed in the app's tables (and
optionally the same matplotlib Figures already drawn in the Graphs
tab, per visualization/graphs.py's original design note: "Phase 9
export can reuse the exact same matplotlib figures directly --
savefig() into the PDF").

Sections produced (each skipped if its source data is None/empty):
    1. Title page (report title + generation timestamp)
    2. Observations table (raw imported data)
    3. Drift Corrected Results (summary block + table)
    4. Graphs (each supplied matplotlib Figure embedded as an image)
"""

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
)

from core.drift import format_minutes_to_clock


class PdfReportError(Exception):
    """Raised when the PDF report cannot be generated."""
    pass


# ----------------------------------------------------------------------
# Shared styling constants (kept consistent with the app's navy/blue
# professional theme and with reports/excel_export.py's palette).
# ----------------------------------------------------------------------
COLOR_PRIMARY = colors.HexColor("#2C6FBB")
COLOR_SECONDARY = colors.HexColor("#2C3E50")
COLOR_ROW_ALT = colors.HexColor("#E3EBF5")
COLOR_GRID = colors.HexColor("#B8C0CC")

_styles = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle(
    "ReportTitle", parent=_styles["Title"], textColor=COLOR_SECONDARY, fontSize=20,
)
SECTION_STYLE = ParagraphStyle(
    "SectionHeading", parent=_styles["Heading2"], textColor=COLOR_SECONDARY, spaceBefore=16, spaceAfter=8,
)
SUBTITLE_STYLE = ParagraphStyle(
    "Subtitle", parent=_styles["Normal"], textColor=colors.HexColor("#5A6B7D"), fontSize=10,
)
BODY_STYLE = _styles["Normal"]


def export_to_pdf(
    filepath: str,
    observation_data=None,
    drift_corrected_data=None,
    known_g_value: float = None,
    graph_figures: dict = None,
    report_title: str = "Gravity Adjustment Report",
) -> None:
    """
    Write a formatted, paginated PDF report containing whichever of
    the supplied datasets/figures are not None.

    Args:
        filepath: destination path, e.g. "/path/to/report.pdf".
        observation_data: raw imported DataFrame (Station, Time,
            Reading), or None to skip this section.
        drift_corrected_data: DriftCorrector.compute() output
            DataFrame, or None to skip this section. If it has
            drift-rate attrs (total_time_minutes, total_drift,
            drift_rate_per_minute), those are written as a summary
            block above the table, same as excel_export.py.
        known_g_value: the manually-entered known G value used for
            this run, included in the summary block if provided.
        graph_figures: optional dict of {graph_title: matplotlib Figure}
            to embed as images, one per page, e.g. taken directly from
            gui.py's self.graph_widgets[graph_type]['figure']. A figure
            showing only the "not available yet" placeholder (e.g.
            Residual Plot before Phase 5 exists) is still embedded as-is
            -- this module doesn't inspect figure content, just renders
            whatever figures it's given.
        report_title: title shown on the report's first page.

    Raises:
        PdfReportError: if none of observation_data, drift_corrected_data,
            or graph_figures is provided (nothing to report), or if
            writing the file fails for any reason.
    """
    has_graphs = bool(graph_figures)
    if observation_data is None and drift_corrected_data is None and not has_graphs:
        raise PdfReportError(
            "Nothing to export -- import a file, run drift correction, "
            "and/or generate graphs before exporting to PDF."
        )

    try:
        doc = SimpleDocTemplate(
            filepath, pagesize=letter,
            topMargin=0.75 * inch, bottomMargin=0.75 * inch,
            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        )
        story = []

        story.extend(_build_title_section(report_title))

        if observation_data is not None and not observation_data.empty:
            story.append(PageBreak())
            story.extend(_build_observations_section(observation_data))

        if drift_corrected_data is not None and not drift_corrected_data.empty:
            story.append(PageBreak())
            story.extend(_build_drift_results_section(drift_corrected_data, known_g_value))

        if has_graphs:
            story.extend(_build_graphs_section(graph_figures))

        doc.build(story)
    except PdfReportError:
        raise
    except Exception as exc:
        raise PdfReportError(f"Failed to write PDF report: {exc}") from exc


# ------------------------------------------------------------------
# INTERNAL SECTION BUILDERS
# ------------------------------------------------------------------
def _build_title_section(report_title: str):
    """Title page: report title + generation timestamp."""
    elements = []
    elements.append(Spacer(1, 2 * inch))
    elements.append(Paragraph(report_title, TITLE_STYLE))
    elements.append(Spacer(1, 0.2 * inch))
    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    elements.append(Paragraph(f"Generated on {timestamp}", SUBTITLE_STYLE))
    return elements


def _build_observations_section(observation_data):
    """Imported Observations section: heading + data table."""
    elements = [Paragraph("Imported Observations", SECTION_STYLE)]
    elements.append(_dataframe_to_table(observation_data, float_format="{:.4f}"))
    return elements


def _build_drift_results_section(drift_corrected_data, known_g_value):
    """Drift Corrected Results section: heading + summary block + table."""
    elements = [Paragraph("Drift Corrected Results", SECTION_STYLE)]

    summary_table = _build_summary_table(drift_corrected_data, known_g_value)
    if summary_table is not None:
        elements.append(summary_table)
        elements.append(Spacer(1, 0.2 * inch))

    elements.append(
        _dataframe_to_table(drift_corrected_data, float_format="{:.6f}", time_column="MeanTime")
    )
    return elements


def _build_graphs_section(graph_figures: dict):
    """Graphs section: one page per figure, each rendered as a PNG image."""
    elements = []
    for graph_title, figure in graph_figures.items():
        elements.append(PageBreak())
        elements.append(Paragraph(graph_title, SECTION_STYLE))

        image_buffer = io.BytesIO()
        figure.savefig(image_buffer, format="png", dpi=150, bbox_inches="tight")
        image_buffer.seek(0)

        # Scale the image to fit within the page's content width while
        # preserving its aspect ratio.
        max_width = 6.5 * inch
        fig_width_in, fig_height_in = figure.get_size_inches()
        aspect_ratio = fig_height_in / fig_width_in if fig_width_in else 1.0
        display_width = max_width
        display_height = max_width * aspect_ratio

        elements.append(Image(image_buffer, width=display_width, height=display_height))

    return elements


def _build_summary_table(drift_corrected_data, known_g_value):
    """
    Build a small two-column summary table (label/value), matching
    excel_export.py's summary block. Returns None if there's nothing
    to show (no known_g_value and no drift-rate attrs present).
    """
    attrs = drift_corrected_data.attrs
    rows = []

    if known_g_value is not None:
        rows.append(["Known G Value:", f"{known_g_value:.6f}"])
    if "total_time_minutes" in attrs:
        rows.append(["Total Time (min):", f"{attrs['total_time_minutes']:.2f}"])
    if "total_drift" in attrs:
        rows.append(["Total Drift:", f"{attrs['total_drift']:.6f}"])
    if "drift_rate_per_minute" in attrs:
        rows.append(["Drift Rate (per min):", f"{attrs['drift_rate_per_minute']:.6f}"])

    if not rows:
        return None

    table = Table(rows, colWidths=[1.8 * inch, 2.2 * inch])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), COLOR_SECONDARY),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _dataframe_to_table(dataframe, float_format="{:.4f}", time_column=None):
    """
    Convert a DataFrame into a styled reportlab Table: navy header row
    with white bold text, alternating row shading, thin grid lines,
    and the header row repeated automatically if the table spans
    multiple pages (repeatRows=1).

    Args:
        time_column: if given, that column's values are formatted via
            core.drift.format_minutes_to_clock() (H:MM) instead of the
            raw float, matching the app's own table display convention.
    """
    columns = [str(c) for c in dataframe.columns]
    data = [columns]

    for _, row in dataframe.iterrows():
        row_values = []
        for column_name in columns:
            value = row[column_name]
            if column_name == time_column and isinstance(value, (int, float)):
                row_values.append(format_minutes_to_clock(value))
            elif isinstance(value, float):
                row_values.append(float_format.format(value))
            else:
                row_values.append(str(value))
        data.append(row_values)

    table = Table(data, repeatRows=1, hAlign="LEFT")

    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_SECONDARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for row_idx in range(1, len(data), 2):
        style_commands.append(("BACKGROUND", (0, row_idx), (-1, row_idx), COLOR_ROW_ALT))
    table.setStyle(TableStyle(style_commands))

    return table