"""
gui.py
------
Graphical User Interface for the Gravity Adjustment Software.

This module contains ONLY GUI-related code (PySide6 widgets, layouts,
menus, toolbars, signal/slot wiring). It must never contain mathematical
or data-processing logic directly -- that logic lives in the `core`,
`reports`, and `visualization` packages and is called from here.

Phase 1 scope:
    - Build the main application window.
    - Add a menu bar, toolbar, and status bar.
    - Add a data table (for imported observations).
    - Add a results table (for adjusted values / statistics).
    - Add all required buttons (Open File, Drift Correction, Least
      Squares, Graphs, Export Excel, Export PDF).
    - Wire up placeholder slot methods that will be implemented in
      later phases (file import in Phase 2, drift correction in
      Phase 4, etc.). For now they simply report their status in the
      status bar / a message box so the interface is fully clickable
      and demonstrable.
"""

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QStatusBar,
    QPushButton,
    QLabel,
    QLineEdit,
    QGroupBox,
    QFileDialog,
    QMessageBox,
    QHeaderView,
    QFrame,
    QSizePolicy,
    QTabWidget,
    QRadioButton,
    QButtonGroup,
    QScrollArea,
)
from PySide6.QtGui import QAction, QFont, QKeySequence, QIcon, QDoubleValidator
from PySide6.QtCore import Qt, QSize

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from core.data_loader import GravityDataLoader, DataLoadError
from core.drift import DriftCorrector, DriftCorrectionError, format_minutes_to_clock
from core.line_drift import LineDriftCorrector, LineDriftError
from core.adjustment import NetworkAdjustment, AdjustmentError
from reports.excel_export import export_to_excel, export_drift_only, ExcelExportError
from reports.pdf_report import export_to_pdf, PdfReportError
from visualization import graphs

import os


class MainWindow(QMainWindow):
    """
    Main application window for the Gravity Adjustment Software.

    Responsibilities:
        - Lay out all GUI elements (menus, toolbar, tables, buttons,
          status bar).
        - Expose clearly named slot methods that later phases will
          fill in with real behaviour (import, drift correction,
          least squares adjustment, graphing, exporting).
        - Delegate ALL calculations to the `core` package and ALL
          report/graph generation to the `reports` / `visualization`
          packages. This class should never contain numerical logic.
    """

    WINDOW_TITLE = "Gravity Adjustment Software"
    MIN_WIDTH = 1200
    MIN_HEIGHT = 750

    # Table/canvas font. Explicitly NOT "Segoe UI" -- Windows 11's
    # variable-weight "Segoe UI Variable" font family has a known
    # Qt/DirectWrite glyph-rendering bug on some systems (observed:
    # certain letters like "j" rendering as "i", and some button text
    # rendering fully blank). "Arial" is a safe, universally-available,
    # non-variable font that sidesteps this entirely. Keep this constant
    # in sync with the FONT_FAMILY used in main.py's app-wide QFont.
    FONT_FAMILY = "Arial"

    # Maps each graph_type string (used by button/menu actions) to the
    # (tab_index in the inner graphs QTabWidget, plotting function in
    # visualization.graphs) it corresponds to. Built in _build_graphs_panel().
    GRAPH_TYPES = ["raw_vs_adjusted", "drift_curve", "residual_plot", "residual_histogram"]
    GRAPH_TITLES = {
        "raw_vs_adjusted": "Raw vs Adjusted",
        "drift_curve": "Drift Curve",
        "residual_plot": "Residual Plot",
        "residual_histogram": "Residual Histogram",
    }

    # Line Drift's GUI (action-panel group + results tab) is fully built
    # and wired below, but hidden for now: the project has pivoted to a
    # global least-squares network adjustment (Phase 5) instead of the
    # day-by-day anchor hand-off approach Line Drift implements. The
    # underlying core/line_drift.py logic and this GUI wiring are kept
    # intact (not deleted) in case a day-by-day view is still useful
    # later (e.g. as a QA/diagnostic tool alongside the network
    # adjustment) -- flip this to True to make it visible again.
    LINE_DRIFT_UI_ENABLED = False

    def __init__(self):
        super().__init__()

        # In-memory placeholders for data that later phases will
        # populate. Kept here so the GUI has somewhere to store state,
        # but the actual processing logic will live in core/.
        self.observation_data = None   # will hold imported observations (Phase 2/3)
        self.drift_corrected_data = None  # will hold drift-corrected visits (Phase 4)
        self.adjusted_results = None   # will hold least-squares results (Phase 5/6)
        # Data loader (computation logic lives in core/, not here)
        self.least_squares_results = None  # Station/AdjustedGValue table (Phase 5)
        self.data_loader = GravityDataLoader()
        self.drift_corrector = DriftCorrector(readings_per_visit=5)

        # --- Line Drift state ---
        # A line's data may arrive as one combined multi-day file (with
        # a Date column, auto-split) or as separate per-day files
        # imported and processed one at a time. Both modes accumulate
        # into the same self.line_drift_results list, in chronological
        # order, so the results table always shows the whole line so far.
        self.line_drift_corrector = LineDriftCorrector()
        self.network_adjustment = NetworkAdjustment()
        self.line_drift_pending_data = None  # most recently opened, not-yet-processed file
        self.line_drift_results = []  # list of per-day result DataFrames, chronological
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setMinimumSize(QSize(self.MIN_WIDTH, self.MIN_HEIGHT))

        # Populated by _build_graphs_panel(): graph_type -> dict with
        # keys 'figure', 'axes', 'canvas' for each of the 4 graphs.
        self.graph_widgets = {}

        self._apply_professional_style()

        self._create_menu_bar()
        self._create_toolbar()
        self._create_central_widget()
        self._create_status_bar()

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------
    def _apply_professional_style(self):
        """
        Applies a clean, professional, HIGH-CONTRAST look-and-feel
        (engineering-software style). Every widget type used in the
        window has an explicit rule -- nothing is left to Qt's default
        palette, which is what caused the washed-out/low-contrast menu
        bar and toolbar text previously.
        """
        self.setStyleSheet(
            """
            /* ---------------------------------------------------- */
            /* Base window                                          */
            /* ---------------------------------------------------- */
            QMainWindow {
                background-color: #f2f4f7;
            }
            QWidget {
                color: #1a2330;
                font-size: 10.5pt;
            }
            QFrame {
                background-color: transparent;
            }

            QScrollArea {
                border: none;
                background-color: #f2f4f7; /* Match QMainWindow background */
            }
            QScrollArea > QWidget {
                background-color: #f2f4f7; /* Ensure content widget also matches */
            }
            QScrollArea > QWidget > QWidget {
                background-color: #f2f4f7; /* Ensure nested widgets also match */
            }

            /* ---------------------------------------------------- */
            /* Menu bar (File / Process / Graphs / Export / Help)   */
            /* ---------------------------------------------------- */
            QMenuBar {
                background-color: #2c3e50;
                color: #ffffff;
                font-size: 10.5pt;
                font-weight: 600;
                padding: 4px 6px;
                border-bottom: 1px solid #1c2733;
            }
            QMenuBar::item {
                background-color: transparent;
                color: #ffffff;
                padding: 6px 12px;
                border-radius: 3px;
            }
            QMenuBar::item:selected {
                background-color: #2c6fbb;
                color: #ffffff;
            }
            QMenuBar::item:pressed {
                background-color: #1c4a7c;
                color: #ffffff;
            }

            /* ---------------------------------------------------- */
            /* Dropdown menus (File > Open, Process > ..., etc.)    */
            /* ---------------------------------------------------- */
            QMenu {
                background-color: #2c3e50;
                color: #ffffff;
                border: 1px solid #1c2733;
                padding: 4px;
            }
            QMenu::item {
                background-color: transparent;
                color: #ffffff;
                padding: 6px 24px 6px 16px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #2c6fbb;
                color: #ffffff;
            }
            QMenu::item:disabled {
                color: #8a94a3;
            }
            QMenu::separator {
                height: 1px;
                background-color: #465364;
                margin: 4px 8px;
            }

            /* ---------------------------------------------------- */
            /* Toolbar and its buttons                              */
            /* ---------------------------------------------------- */
            QToolBar {
                background-color: #2c3e50;
                border-bottom: 1px solid #1c2733;
                spacing: 4px;
                padding: 6px;
            }
            QToolBar::separator {
                background-color: #465364;
                width: 1px;
                margin: 4px 6px;
            }
            QToolButton {
                background-color: transparent;
                color: #ffffff;
                font-weight: 600;
                font-size: 10pt;
                padding: 6px 12px;
                border: none;
                border-radius: 4px;
            }
            QToolButton:hover {
                background-color: #2c6fbb;
                color: #ffffff;
            }
            QToolButton:pressed {
                background-color: #1c4a7c;
                color: #ffffff;
            }
            QToolButton:disabled {
                color: #8a94a3;
            }

            /* ---------------------------------------------------- */
            /* Group boxes                                          */
            /* ---------------------------------------------------- */
            QGroupBox {
                font-weight: 600;
                border: 1px solid #c3c9d1;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 12px;
                padding-bottom: 12px;
                background-color: #ffffff;
                color: #1a2330;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #2c3e50;
                font-size: 11pt;
                font-weight: 700;
            }

            /* ---------------------------------------------------- */
            /* Tables                                               */
            /* ---------------------------------------------------- */
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #e3ebf5;
                gridline-color: #b8c0cc;
                selection-background-color: #2c6fbb;
                selection-color: #ffffff;
                border: 1px solid #a9b2bd;
                font-size: 10.5pt;
                color: #1a2330;
            }
            QTableWidget::item {
                padding: 6px;
                color: #1a2330;
            }
            QHeaderView::section {
                background-color: #2c3e50;
                color: #ffffff;
                padding: 8px;
                font-size: 10.5pt;
                font-weight: 600;
                border: none;
                border-right: 1px solid #1c2733;
            }
            QTableCornerButton::section {
                background-color: #2c3e50;
                border: none;
            }

            /* ---------------------------------------------------- */
            /* Buttons (left action panel)                          */
            /* ---------------------------------------------------- */
            QPushButton {
                background-color: #2c6fbb;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 8px 12px;
                font-weight: 600;
                font-size: 10.5pt;
            }
            QPushButton:hover {
                background-color: #245a97;
            }
            QPushButton:pressed {
                background-color: #1c4a7c;
            }
            QPushButton:disabled {
                background-color: #a9b2bd;
                color: #e6e9ee;
            }

            /* ---------------------------------------------------- */
            /* Labels and inputs                                    */
            /* ---------------------------------------------------- */
            QLabel {
                color: #1a2330;
                font-weight: 500;
            }
            QLineEdit {
                background-color: #ffffff;
                color: #1a2330;
                border: 1px solid #a9b2bd;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 10.5pt;
                selection-background-color: #2c6fbb;
                selection-color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #2c6fbb;
            }
            QLineEdit:disabled {
                background-color: #e6e9ee;
                color: #8a94a3;
            }

            /* ---------------------------------------------------- */
            /* Radio buttons                                        */
            /* ---------------------------------------------------- */
            QRadioButton {
                color: #1a2330;
                font-weight: 500;
                spacing: 6px;
            }

            /* ---------------------------------------------------- */
            /* Splitter handle                                      */
            /* ---------------------------------------------------- */
            QSplitter::handle {
                background-color: #c3c9d1;
            }
            QSplitter::handle:hover {
                background-color: #2c6fbb;
            }

            /* ---------------------------------------------------- */
            /* Status bar                                           */
            /* ---------------------------------------------------- */
            QStatusBar {
                background-color: #2c3e50;
                color: #ffffff;
            }
            QStatusBar QLabel {
                color: #ffffff;
                font-weight: 500;
            }

            /* ---------------------------------------------------- */
            /* Message boxes / dialogs                              */
            /* ---------------------------------------------------- */
            QMessageBox {
                background-color: #ffffff;
            }
            QMessageBox QLabel {
                color: #1a2330;
                font-size: 10.5pt;
            }

            /* ---------------------------------------------------- */
            /* Tab widget (Data & Results / Graphs)                 */
            /* ---------------------------------------------------- */
            QTabWidget::pane {
                border: 1px solid #a9b2bd;
                background-color: #ffffff;
                top: -1px;
            }
            QTabBar::tab {
                background-color: #2c3e50;
                color: #ffffff;
                padding: 8px 16px;
                margin-right: 2px;
                font-weight: 600;
                font-size: 10pt;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #2c6fbb;
                color: #ffffff;
            }
            QTabBar::tab:hover:!selected {
                background-color: #3d5166;
            }
            /* ---------------------------------------------------- */
            /* File dialogs (Open/Save) -- explicit styling so they  */
            /* don't inherit dark-text-on-dark-background from the   */
            /* OS dark theme when using the non-native Qt dialog.    */
            /* ---------------------------------------------------- */
            QFileDialog {
                background-color: #ffffff;
                color: #1a2330;
            }
            QFileDialog QWidget {
                background-color: #ffffff;
                color: #1a2330;
            }
            QFileDialog QListView, QFileDialog QTreeView {
                background-color: #ffffff;
                color: #1a2330;
                selection-background-color: #2c6fbb;
                selection-color: #ffffff;
            }
            QFileDialog QComboBox {
                background-color: #ffffff;
                color: #1a2330;
                border: 1px solid #a9b2bd;
                padding: 4px;
            }
            QFileDialog QToolButton {
                background-color: transparent;
                color: #1a2330;
                padding: 4px;
            }
            QFileDialog QToolButton:hover {
                background-color: #e3ebf5;
            }
            QFileDialog QPushButton {
                background-color: #2c6fbb;
                color: #ffffff;
            }
            """
        )

    # ------------------------------------------------------------------
    # Menu Bar
    # ------------------------------------------------------------------
    def _create_menu_bar(self):
        """Builds the top menu bar (File, Process, Graphs, Export, Help)."""
        menu_bar = self.menuBar()

        # ---- File menu ----
        file_menu = menu_bar.addMenu("&File")

        self.action_open_file = QAction("&Open Observation File...", self)
        self.action_open_file.setShortcut(QKeySequence.Open)
        self.action_open_file.setStatusTip(
            "Import gravity observation data from a CSV or Excel file."
        )
        self.action_open_file.triggered.connect(self.on_open_file)
        file_menu.addAction(self.action_open_file)

        file_menu.addSeparator()

        action_exit = QAction("E&xit", self)
        action_exit.setShortcut(QKeySequence.Quit)
        action_exit.triggered.connect(self.close)
        file_menu.addAction(action_exit)

        # ---- Process menu ----
        process_menu = menu_bar.addMenu("&Process")

        self.action_drift_correction = QAction("Apply &Drift Correction", self)
        self.action_drift_correction.setStatusTip(
            "Apply drift correction to the imported observations."
        )
        self.action_drift_correction.triggered.connect(self.on_apply_drift_correction)
        process_menu.addAction(self.action_drift_correction)

        self.action_least_squares = QAction("Run &Least Squares Adjustment", self)
        self.action_least_squares.setStatusTip(
            "Perform the least squares adjustment on corrected observations."
        )
        self.action_least_squares.triggered.connect(self.on_run_least_squares)
        process_menu.addAction(self.action_least_squares)

        # ---- Graphs menu ----
        graphs_menu = menu_bar.addMenu("&Graphs")

        self.action_graph_raw_vs_adjusted = QAction("Raw vs Adjusted Gravity", self)
        self.action_graph_raw_vs_adjusted.triggered.connect(
            lambda: self.on_show_graph("raw_vs_adjusted")
        )
        graphs_menu.addAction(self.action_graph_raw_vs_adjusted)

        self.action_graph_drift_curve = QAction("Drift Curve", self)
        self.action_graph_drift_curve.triggered.connect(
            lambda: self.on_show_graph("drift_curve")
        )
        graphs_menu.addAction(self.action_graph_drift_curve)

        self.action_graph_residuals = QAction("Residual Plot", self)
        self.action_graph_residuals.triggered.connect(
            lambda: self.on_show_graph("residual_plot")
        )
        graphs_menu.addAction(self.action_graph_residuals)

        self.action_graph_histogram = QAction("Histogram of Residuals", self)
        self.action_graph_histogram.triggered.connect(
            lambda: self.on_show_graph("residual_histogram")
        )
        graphs_menu.addAction(self.action_graph_histogram)

        # ---- Export menu ----
        export_menu = menu_bar.addMenu("&Export")

        self.action_export_excel = QAction("Export to &Excel...", self)
        self.action_export_excel.triggered.connect(self.on_export_excel)
        export_menu.addAction(self.action_export_excel)

        self.action_export_pdf = QAction("Export to &PDF...", self)
        self.action_export_pdf.triggered.connect(self.on_export_pdf)
        export_menu.addAction(self.action_export_pdf)

        # ---- Help menu ----
        help_menu = menu_bar.addMenu("&Help")

        action_about = QAction("&About", self)
        action_about.triggered.connect(self.on_show_about)
        help_menu.addAction(action_about)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------
    def _create_toolbar(self):
        """Builds the main toolbar with quick-access actions."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setIconSize(QSize(22, 22))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction(self.action_open_file)
        toolbar.addSeparator()
        toolbar.addAction(self.action_drift_correction)
        toolbar.addAction(self.action_least_squares)
        toolbar.addSeparator()
        toolbar.addAction(self.action_export_excel)
        toolbar.addAction(self.action_export_pdf)

    # ------------------------------------------------------------------
    # Central Widget
    # ------------------------------------------------------------------
    def _create_central_widget(self):
        """
        Builds the central area of the window:
            - Left: action panel (buttons for each processing step + graphs).
            - Right: a QTabWidget with two tabs:
                * "Data & Results": the original QSplitter containing
                  self.data_table (top) and self.results_table (bottom).
                * "Graphs": inner QTabWidget with one sub-tab per graph
                  type (Raw vs Adjusted, Drift Curve, Residual Plot,
                  Residual Histogram), each holding an embedded
                  matplotlib canvas.
        """
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        main_layout.addWidget(self._build_action_panel(), stretch=0)
        main_layout.addWidget(self._build_right_panel(), stretch=1)

        self.setCentralWidget(central_widget)

    def _build_action_panel(self):
        """Builds the left-hand vertical panel containing all action buttons."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        panel_content = QWidget()
        panel_content.setFixedWidth(270) # Maintain fixed width for the content inside scroll area
        layout = QVBoxLayout(panel_content)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignTop)

        # --- Data group ---
        data_group = QGroupBox("Data")
        data_layout = QVBoxLayout(data_group)
        self.btn_open_file = QPushButton("Open File")
        self.btn_open_file.setMinimumHeight(34)
        self.btn_open_file.clicked.connect(self.on_open_file)
        data_layout.addWidget(self.btn_open_file)
        layout.addWidget(data_group)

        # --- Processing group ---
        processing_group = QGroupBox("Processing")
        processing_layout = QVBoxLayout(processing_group)
        processing_layout.setContentsMargins(15, 20, 15, 20) # Keep margins for group box content

        # Drift correction mode: with an absolute known G value (chains
        # a full GValue column), or without one (per your mentor:
        # produces the same Drift/CorrectedReading/DeltaG either way --
        # only the GValue column is skipped -- useful for producing
        # relative-only observations to feed the Phase 5 network
        # adjustment, where absolute anchoring comes from a separate
        # base-station reference sheet instead of from this file).
        mode_label = QLabel("Drift Correction Mode:")
        mode_label.setStyleSheet("font-weight: 600;")
        processing_layout.addWidget(mode_label)

        # Radio buttons for drift correction mode
        radio_button_layout = QVBoxLayout()
        radio_button_layout.setSpacing(5)
        self.radio_with_known_g = QRadioButton("With Known G Value")
        self.radio_without_known_g = QRadioButton("Without Known G Value")
        self.radio_with_known_g.setChecked(True)
        self.drift_mode_group = QButtonGroup(processing_group)
        self.drift_mode_group.addButton(self.radio_with_known_g)
        self.drift_mode_group.addButton(self.radio_without_known_g)
        self.radio_with_known_g.toggled.connect(self._on_drift_mode_toggled)
        radio_button_layout.addWidget(self.radio_with_known_g)
        radio_button_layout.addWidget(self.radio_without_known_g)
        processing_layout.addLayout(radio_button_layout)

        processing_layout.addSpacing(15) # Spacing between radio buttons and G value input

        # Known G Value input using QFormLayout for better alignment
        known_g_form_layout = QFormLayout()
        known_g_form_layout.setContentsMargins(0, 0, 0, 0)
        known_g_form_layout.setVerticalSpacing(5)
        known_g_label = QLabel("Known G Value:")
        self.input_known_g_value = QLineEdit()
        self.input_known_g_value.setPlaceholderText("e.g. 979.436285")
        self.input_known_g_value.setValidator(QDoubleValidator(-999999.0, 999999.0, 6))
        self.input_known_g_value.setMinimumHeight(32)
        known_g_form_layout.addRow(known_g_label, self.input_known_g_value)
        processing_layout.addLayout(known_g_form_layout)

        processing_layout.addSpacing(15) # Spacing between G value input and buttons

        self.btn_drift_correction = QPushButton("Drift Correction")
        self.btn_drift_correction.setMinimumHeight(36)
        self.btn_drift_correction.clicked.connect(self.on_apply_drift_correction)
        self.btn_least_squares = QPushButton("Least Squares Adjustment")
        self.btn_least_squares.setMinimumHeight(36)
        self.btn_least_squares.clicked.connect(self.on_run_least_squares)
        processing_layout.addWidget(self.btn_drift_correction)
        processing_layout.addWidget(self.btn_least_squares)
        layout.addWidget(processing_group)

        # --- Line Drift group ---
        line_drift_group = QGroupBox("Line Drift")
        line_drift_layout = QVBoxLayout(line_drift_group)

        # Known G Value for Day 1 of a new line only. Ignored for every
        # subsequent day -- the anchor station's G value (carried over
        # from the previous day) is used instead, computed automatically.
        line_drift_layout.addWidget(QLabel("Known G (Day 1):"))
        self.input_line_drift_known_g = QLineEdit()
        self.input_line_drift_known_g.setPlaceholderText("e.g. 979.436285")
        self.input_line_drift_known_g.setValidator(QDoubleValidator(-999999.0, 999999.0, 6))
        self.input_line_drift_known_g.setMinimumHeight(32)
        line_drift_layout.addWidget(self.input_line_drift_known_g)

        self.line_drift_status_label = QLabel("No line in progress.")
        self.line_drift_status_label.setWordWrap(True)
        line_drift_layout.addWidget(self.line_drift_status_label)

        self.btn_line_drift_open_file = QPushButton("Open Day File")
        self.btn_line_drift_open_file.setMinimumHeight(34)
        self.btn_line_drift_open_file.clicked.connect(self.on_open_line_drift_file)
        self.btn_line_drift_process = QPushButton("Process File")
        self.btn_line_drift_process.setMinimumHeight(34)
        self.btn_line_drift_process.clicked.connect(self.on_process_line_drift)
        self.btn_line_drift_reset = QPushButton("Reset Line")
        self.btn_line_drift_reset.setMinimumHeight(34)
        self.btn_line_drift_reset.clicked.connect(self.on_reset_line_drift)
        line_drift_layout.addWidget(self.btn_line_drift_open_file)
        line_drift_layout.addWidget(self.btn_line_drift_process)
        line_drift_layout.addWidget(self.btn_line_drift_reset)
        layout.addWidget(line_drift_group)
        line_drift_group.setVisible(self.LINE_DRIFT_UI_ENABLED)

        # --- Graphs group ---
        graphs_group = QGroupBox("Graphs")
        graphs_layout = QVBoxLayout(graphs_group)
        self.btn_graph_raw_vs_adjusted = QPushButton("Raw vs Adjusted")
        self.btn_graph_raw_vs_adjusted.setMinimumHeight(34)
        self.btn_graph_raw_vs_adjusted.clicked.connect(
            lambda: self.on_show_graph("raw_vs_adjusted")
        )
        self.btn_graph_drift_curve = QPushButton("Drift Curve")
        self.btn_graph_drift_curve.setMinimumHeight(34)
        self.btn_graph_drift_curve.clicked.connect(
            lambda: self.on_show_graph("drift_curve")
        )
        self.btn_graph_residuals = QPushButton("Residual Plot")
        self.btn_graph_residuals.setMinimumHeight(34)
        self.btn_graph_residuals.clicked.connect(
            lambda: self.on_show_graph("residual_plot")
        )
        self.btn_graph_histogram = QPushButton("Residual Histogram")
        self.btn_graph_histogram.setMinimumHeight(34)
        self.btn_graph_histogram.clicked.connect(
            lambda: self.on_show_graph("residual_histogram")
        )
        graphs_layout.addWidget(self.btn_graph_raw_vs_adjusted)
        graphs_layout.addWidget(self.btn_graph_drift_curve)
        graphs_layout.addWidget(self.btn_graph_residuals)
        graphs_layout.addWidget(self.btn_graph_histogram)
        layout.addWidget(graphs_group)

        # --- Export group ---
        export_group = QGroupBox("Export")
        export_layout = QVBoxLayout(export_group)
        self.btn_export_excel = QPushButton("Export Excel")
        self.btn_export_excel.setMinimumHeight(34)
        self.btn_export_excel.clicked.connect(self.on_export_excel)
        self.btn_export_pdf = QPushButton("Export PDF")
        self.btn_export_pdf.setMinimumHeight(34)
        self.btn_export_pdf.clicked.connect(self.on_export_pdf)
        self.btn_export_for_least_squares = QPushButton("Export for Least Squares")
        self.btn_export_for_least_squares.setMinimumHeight(34)
        self.btn_export_for_least_squares.setToolTip(
            "Minimal export of just the drift-corrected results table "
            "(no graphs, no summary) -- for use as a Phase 5 input file."
        )
        self.btn_export_for_least_squares.clicked.connect(self.on_export_for_least_squares)
        export_layout.addWidget(self.btn_export_excel)
        export_layout.addWidget(self.btn_export_pdf)
        export_layout.addWidget(self.btn_export_for_least_squares)
        layout.addWidget(export_group)
        layout.addStretch(1)

        scroll_area.setWidget(panel_content)
        return scroll_area

    def _build_right_panel(self):
        self.main_tab_widget = QTabWidget()
        self.main_tab_widget.addTab(self._build_tables_panel(), "Data && Results")
        line_drift_tab_index = self.main_tab_widget.addTab(self._build_line_drift_panel(), "Line Drift")
        self.main_tab_widget.setTabVisible(line_drift_tab_index, self.LINE_DRIFT_UI_ENABLED)
        self.main_tab_widget.addTab(self._build_least_squares_panel(), "Least Squares")
        self.main_tab_widget.addTab(self._build_graphs_panel(), "Graphs")
        return self.main_tab_widget

    def _build_least_squares_panel(self):
        """
        Builds the "Least Squares" tab: two sub-tabs, "Adjusted Values"
        (one row per unique station, its solved gravity value) and
        "Residuals" (one row per observation, its misfit) -- kept as
        separate tables since they have entirely different shapes.
        """
        self.least_squares_tab_widget = QTabWidget()

        adjusted_tab = QWidget()
        adjusted_layout = QVBoxLayout(adjusted_tab)
        adjusted_layout.setContentsMargins(4, 4, 4, 4)
        self.ls_adjusted_table = QTableWidget(0, 0)
        self.ls_adjusted_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.ls_adjusted_table.setAlternatingRowColors(True)
        self.ls_adjusted_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.ls_adjusted_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ls_adjusted_table.verticalHeader().setDefaultSectionSize(28)
        self.ls_adjusted_table.setFont(QFont("Segoe UI", 10))
        adjusted_layout.addWidget(self.ls_adjusted_table)
        self.least_squares_tab_widget.addTab(adjusted_tab, "Adjusted Values")

        residuals_tab = QWidget()
        residuals_layout = QVBoxLayout(residuals_tab)
        residuals_layout.setContentsMargins(4, 4, 4, 4)
        self.ls_residuals_table = QTableWidget(0, 0)
        self.ls_residuals_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.ls_residuals_table.setAlternatingRowColors(True)
        self.ls_residuals_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.ls_residuals_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ls_residuals_table.verticalHeader().setDefaultSectionSize(28)
        self.ls_residuals_table.setFont(QFont("Segoe UI", 10))
        residuals_layout.addWidget(self.ls_residuals_table)
        self.least_squares_tab_widget.addTab(residuals_tab, "Residuals")

        return self.least_squares_tab_widget

    def _populate_generic_table(self, table_widget, dataframe, float_format="{:.6f}"):
        """Shared fill logic for simple result tables (Least Squares tables)."""
        table_widget.clear()

        num_rows, num_cols = dataframe.shape
        table_widget.setRowCount(num_rows)
        table_widget.setColumnCount(num_cols)
        table_widget.setHorizontalHeaderLabels([str(c) for c in dataframe.columns])

        for row_idx in range(num_rows):
            for col_idx in range(num_cols):
                value = dataframe.iat[row_idx, col_idx]
                if isinstance(value, float):
                    text = float_format.format(value)
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                table_widget.setItem(row_idx, col_idx, item)

        table_widget.resizeColumnsToContents()

    def populate_least_squares_tables(self, results_df, residuals_df):
        """Fill both the Adjusted Values and Residuals tables."""
        self._populate_generic_table(self.ls_adjusted_table, results_df)
        self._populate_generic_table(self.ls_residuals_table, residuals_df)

    def _build_tables_panel(self):
        splitter = QSplitter(Qt.Vertical)

        # --- Observation data table ---
        data_box = QGroupBox("Imported Observations")
        data_box_layout = QVBoxLayout(data_box)
        self.data_table = QTableWidget(0, 0)
        self.data_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.data_table.setAlternatingRowColors(True)
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.data_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.data_table.verticalHeader().setDefaultSectionSize(28)
        self.data_table.setFont(QFont(self.FONT_FAMILY, 10))
        data_box_layout.addWidget(self.data_table)
        splitter.addWidget(data_box)

        # --- Adjusted results table ---
        results_box = QGroupBox("Adjusted Results / Statistics")
        results_box_layout = QVBoxLayout(results_box)
        self.results_table = QTableWidget(0, 0)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.results_table.verticalHeader().setDefaultSectionSize(28)
        self.results_table.setFont(QFont(self.FONT_FAMILY, 10))
        results_box_layout.addWidget(self.results_table)
        splitter.addWidget(results_box)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        return splitter

    def _build_line_drift_panel(self):
        """
        Builds the "Line Drift" tab: a single stacked results table
        (all days so far, with a "Day" column added) on top, and a
        small read-only diagnostics table underneath showing each
        day's closing discrepancy (g1_long - g1_short) -- useful to
        monitor even though it isn't auto-corrected here (that's a
        separate downstream process per the user).
        """
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(4, 4, 4, 4)

        results_box = QGroupBox("Line Drift Results (all days)")
        results_box_layout = QVBoxLayout(results_box)
        self.line_drift_table = QTableWidget(0, 0)
        self.line_drift_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.line_drift_table.setAlternatingRowColors(True)
        self.line_drift_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.line_drift_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.line_drift_table.verticalHeader().setDefaultSectionSize(28)
        self.line_drift_table.setFont(QFont(self.FONT_FAMILY, 10))
        results_box_layout.addWidget(self.line_drift_table)
        panel_layout.addWidget(results_box, stretch=3)

        log_box = QGroupBox("Day Closure Diagnostics")
        log_box_layout = QVBoxLayout(log_box)
        self.line_drift_log = QTableWidget(0, 3)
        self.line_drift_log.setEditTriggers(QTableWidget.NoEditTriggers)
        self.line_drift_log.setAlternatingRowColors(True)
        self.line_drift_log.setHorizontalHeaderLabels(["Day", "Anchor Station", "Closure Discrepancy"])
        self.line_drift_log.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.line_drift_log.verticalHeader().setDefaultSectionSize(26)
        self.line_drift_log.setFont(QFont(self.FONT_FAMILY, 10))
        log_box_layout.addWidget(self.line_drift_log)
        panel_layout.addWidget(log_box, stretch=1)

        return panel

    def _build_graphs_panel(self):
        """
        Builds the "Graphs" tab: an inner QTabWidget with one sub-tab
        per graph type. Each sub-tab holds a matplotlib Figure embedded
        via FigureCanvasQTAgg, plus its NavigationToolbar2QT (zoom/pan/
        save-to-file), stacked in a small QVBoxLayout.

        Graphs are NOT drawn here -- they start blank and are populated
        on demand by _refresh_graph() the first time the user opens
        that tab (via on_show_graph()), so we don't do unnecessary work
        before any data exists.
        """
        self.graphs_tab_widget = QTabWidget()

        for graph_type in self.GRAPH_TYPES:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(4, 4, 4, 4)

            figure = Figure(figsize=(6, 4), dpi=100, facecolor="#ffffff")
            axes = figure.add_subplot(111)
            canvas = FigureCanvasQTAgg(figure)
            toolbar = NavigationToolbar2QT(canvas, tab)

            tab_layout.addWidget(toolbar)
            tab_layout.addWidget(canvas)

            self.graph_widgets[graph_type] = {
                "figure": figure,
                "axes": axes,
                "canvas": canvas,
            }

            self.graphs_tab_widget.addTab(tab, self.GRAPH_TITLES[graph_type])

        return self.graphs_tab_widget

    # ------------------------------------------------------------------
    # Status Bar
    # ------------------------------------------------------------------
    def _create_status_bar(self):
        """Builds the status bar shown at the bottom of the window."""
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        self.status_label = QLabel("Ready.")
        status_bar.addWidget(self.status_label, stretch=1)

        self.record_count_label = QLabel("Records: 0")
        status_bar.addPermanentWidget(self.record_count_label)

    def set_status(self, message: str):
        """Convenience helper to update the status bar text."""
        self.status_label.setText(message)

    # ------------------------------------------------------------------
    # Slot methods (placeholders for now -- real logic added in later phases)
    # ------------------------------------------------------------------
    def on_open_file(self):
        """
        Slot for the 'Open File' action/button.

        Phase 1: only opens a file dialog so the UI is demonstrable.
        Phase 2 will wire this up to core/import logic that actually
        reads the CSV/Excel file into `self.observation_data` and
        populates `self.data_table`.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Gravity Observation File",
            "",
            "Data Files (*.csv *.xlsx *.xls);;All Files (*)",
        )

        if not file_path:
            self.set_status("File selection cancelled.")
            return

        try:
            dataframe = self.data_loader.load(file_path)
        except DataLoadError as exc:
            QMessageBox.critical(self, "Import Failed", str(exc))
            self.set_status("File import failed.")
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Unexpected Error",
                f"An unexpected error occurred while importing the file:\n\n{exc}",
            )
            self.set_status("File import failed (unexpected error).")
            return

        self.observation_data = dataframe

        # Display the imported data in the table (Phase 3).
        self.populate_data_table(dataframe)

        num_rows, num_cols = dataframe.shape
        file_name = os.path.basename(file_path)

        self.set_status(
            f"Imported '{file_name}': {num_rows} rows, {num_cols} columns."
        )

    def populate_data_table(self, dataframe):
        """
        Fill self.data_table with the contents of a pandas DataFrame.

        Phase 3: pure GUI/display logic -- takes data that has already
        been loaded and validated (Phase 2) and renders it. Does not
        do any parsing, calculation, or validation itself.
        """
        self.data_table.clear()

        num_rows, num_cols = dataframe.shape
        self.data_table.setRowCount(num_rows)
        self.data_table.setColumnCount(num_cols)
        self.data_table.setHorizontalHeaderLabels([str(c) for c in dataframe.columns])

        for row_idx in range(num_rows):
            for col_idx in range(num_cols):
                value = dataframe.iat[row_idx, col_idx]
                # Format floats to 4 decimal places for readability;
                # leave everything else (strings, ints, dates) as-is.
                if isinstance(value, float):
                    text = f"{value:.4f}"
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.data_table.setItem(row_idx, col_idx, item)

        self.data_table.resizeColumnsToContents()

    def _on_drift_mode_toggled(self, checked: bool):
        """
        Slot for the drift-mode radio buttons. Enables/disables the
        Known G Value field based on which mode is selected -- greyed
        out (and its contents ignored) in 'Without Known G Value' mode.
        """
        self.input_known_g_value.setEnabled(checked)
        if not checked:
            self.input_known_g_value.clear()

    def on_apply_drift_correction(self):
        """
        Slot for the 'Drift Correction' button.
        Phase 4: validates inputs, then delegates the math to
        core.drift.DriftCorrector. Displays the result in the results
        table. Respects the With/Without Known G Value mode toggle --
        in 'Without Known G Value' mode, Drift/CorrectedReading/DeltaG
        are computed exactly the same way, but GValue is left blank
        for every row (see core.drift.DriftCorrector.compute()).
        """
        if self.observation_data is None:
            QMessageBox.warning(
                self,
                "No Data Imported",
                "Please open an observation file before applying drift correction.",
            )
            return

        known_g_value = None
        if self.radio_with_known_g.isChecked():
            g_text = self.input_known_g_value.text().strip()
            if not g_text:
                QMessageBox.warning(
                    self,
                    "Known G Value Required",
                    "Please enter the known (absolute) G value, or switch to "
                    "'Without Known G Value' mode.",
                )
                return
            try:
                known_g_value = float(g_text)
            except ValueError:
                QMessageBox.warning(self, "Invalid G Value", f"'{g_text}' is not a valid number.")
                return

        try:
            results = self.drift_corrector.compute(self.observation_data, known_g_value)
        except DriftCorrectionError as exc:
            QMessageBox.critical(self, "Drift Correction Failed", str(exc))
            self.set_status("Drift correction failed.")
            return
        except Exception as exc:
            QMessageBox.critical(
                self, "Unexpected Error",
                f"An unexpected error occurred during drift correction:\n\n{exc}",
            )
            self.set_status("Drift correction failed (unexpected error).")
            return

        self.drift_corrected_data = results
        self.populate_results_table(results)
        self.set_status(f"Drift correction applied: {len(results)} station visits processed.")

        # Refresh any graphs that depend on drift-corrected data so they
        # stay in sync if the user has already opened the Graphs tab.
        self._refresh_graph("drift_curve")
        self._refresh_graph("raw_vs_adjusted")

    def populate_results_table(self, dataframe):
        """
        Fill self.results_table with the contents of a pandas DataFrame.

        The 'MeanTime' column is stored internally as total minutes
        (float) so drift/rate calculations work correctly, but it is
        displayed here in the 'H:MM' clock-style format (e.g. 98.0
        minutes -> "1:38") for readability.
        """
        self.results_table.clear()

        num_rows, num_cols = dataframe.shape
        self.results_table.setRowCount(num_rows)
        self.results_table.setColumnCount(num_cols)
        self.results_table.setHorizontalHeaderLabels([str(c) for c in dataframe.columns])

        column_names = [str(c) for c in dataframe.columns]

        for row_idx in range(num_rows):
            for col_idx in range(num_cols):
                value = dataframe.iat[row_idx, col_idx]
                column_name = column_names[col_idx]
                if value is None:
                    text = "\u2014"  # em dash, e.g. GValue column in 'Without Known G Value' mode
                elif column_name == "MeanTime" and isinstance(value, (int, float)):
                    text = format_minutes_to_clock(value)
                elif isinstance(value, float):
                    text = f"{value:.6f}"
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.results_table.setItem(row_idx, col_idx, item)

        self.results_table.resizeColumnsToContents()

    # ------------------------------------------------------------------
    # Line Drift slot methods
    # ------------------------------------------------------------------
    def on_open_line_drift_file(self):
        """
        Slot for the 'Open Day File' button (Line Drift group). Opens a
        file dialog and loads the selected CSV/Excel file into
        self.line_drift_pending_data, WITHOUT processing it yet -- the
        user reviews/confirms via the 'Process File' button next. This
        mirrors on_open_file() but keeps Line Drift's pending data
        completely separate from Circuit Drift's self.observation_data,
        so using one feature never clobbers the other.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Line Drift Day File",
            "",
            "Data Files (*.csv *.xlsx *.xls);;All Files (*)",
        )

        if not file_path:
            self.set_status("File selection cancelled.")
            return

        try:
            dataframe = self.data_loader.load(file_path)
        except DataLoadError as exc:
            QMessageBox.critical(self, "Import Failed", str(exc))
            self.set_status("Line Drift file import failed.")
            return
        except Exception as exc:
            QMessageBox.critical(
                self, "Unexpected Error",
                f"An unexpected error occurred while importing the file:\n\n{exc}",
            )
            self.set_status("Line Drift file import failed (unexpected error).")
            return

        self.line_drift_pending_data = dataframe
        file_name = os.path.basename(file_path)
        self.set_status(f"Loaded '{file_name}' for Line Drift -- click 'Process File' to continue.")

    def on_process_line_drift(self):
        """
        Slot for the 'Process File' button (Line Drift group).

        Auto-detects which of the two supported input modes the loaded
        file uses:
            - COMBINED FILE: has a Date/Day column (fuzzy-matched, same
              approach as Station/Time/Reading) -> split into per-day
              DataFrames and process the whole line in one go via
              LineDriftCorrector.compute_line(). Starts a fresh line
              (any previously accumulated sequential-day results are
              replaced, after confirmation).
            - SEQUENTIAL DAY FILE: no date column -> treated as the
              next single day in an ongoing line. If no line is in
              progress yet, this is Day 1 (requires the Known G Day 1
              field); otherwise it's a subsequent day, and the anchor
              station/G value are taken automatically from the
              previously processed day -- no user input needed.
        """
        if self.line_drift_pending_data is None:
            QMessageBox.warning(
                self, "No File Opened",
                "Please open a Line Drift day file before processing.",
            )
            return

        date_column = self.line_drift_corrector._find_date_column(self.line_drift_pending_data)

        if date_column is not None:
            self._process_line_drift_combined_file(date_column)
        else:
            self._process_line_drift_sequential_day()

    def _process_line_drift_combined_file(self, date_column: str):
        """Handle the 'combined multi-day file with a Date column' input mode."""
        if self.line_drift_results:
            confirm = QMessageBox.question(
                self, "Start a New Line?",
                "A line is already in progress. Processing this combined "
                "file will discard the current progress and start a new "
                "line. Continue?",
            )
            if confirm != QMessageBox.Yes:
                self.set_status("Line Drift: combined file processing cancelled.")
                return

        known_g_text = self.input_line_drift_known_g.text().strip()
        if not known_g_text:
            QMessageBox.warning(
                self, "Known G Value Required",
                "Please enter the Known G Value (Day 1) before processing "
                "a combined Line Drift file.",
            )
            return
        try:
            known_g_value = float(known_g_text)
        except ValueError:
            QMessageBox.warning(self, "Invalid G Value", f"'{known_g_text}' is not a valid number.")
            return

        try:
            day_dataframes = self.line_drift_corrector.split_by_date(
                self.line_drift_pending_data, date_column
            )
            results = self.line_drift_corrector.compute_line(day_dataframes, known_g_value)
        except (LineDriftError, DriftCorrectionError) as exc:
            QMessageBox.critical(self, "Line Drift Failed", str(exc))
            self.set_status("Line Drift (combined file) failed.")
            return
        except Exception as exc:
            QMessageBox.critical(
                self, "Unexpected Error",
                f"An unexpected error occurred during line drift correction:\n\n{exc}",
            )
            self.set_status("Line Drift (combined file) failed (unexpected error).")
            return

        self.line_drift_results = results
        self.line_drift_pending_data = None
        self.populate_line_drift_table(self.line_drift_results)
        self.line_drift_status_label.setText(
            f"Line in progress: {len(self.line_drift_results)} day(s) processed "
            f"(combined file, split by '{date_column}')."
        )
        self.set_status(f"Line Drift: processed {len(results)} day(s) from combined file.")

    def _process_line_drift_sequential_day(self):
        """Handle the 'one day file at a time' input mode."""
        if not self.line_drift_results:
            # This is Day 1 of a brand-new line.
            known_g_text = self.input_line_drift_known_g.text().strip()
            if not known_g_text:
                QMessageBox.warning(
                    self, "Known G Value Required",
                    "Please enter the Known G Value (Day 1) before "
                    "processing the first day of a new line.",
                )
                return
            try:
                known_g_value = float(known_g_text)
            except ValueError:
                QMessageBox.warning(self, "Invalid G Value", f"'{known_g_text}' is not a valid number.")
                return

            try:
                result = self.line_drift_corrector.compute_first_day(
                    self.line_drift_pending_data, known_g_value
                )
            except (LineDriftError, DriftCorrectionError) as exc:
                QMessageBox.critical(self, "Line Drift Failed", str(exc))
                self.set_status("Line Drift Day 1 failed.")
                return
            except Exception as exc:
                QMessageBox.critical(
                    self, "Unexpected Error",
                    f"An unexpected error occurred during line drift correction:\n\n{exc}",
                )
                self.set_status("Line Drift Day 1 failed (unexpected error).")
                return

            self.line_drift_results = [result]
        else:
            # A subsequent day -- anchor comes automatically from the
            # previous day's result, no user input required.
            previous_day = self.line_drift_results[-1]
            anchor_station = previous_day.attrs["next_anchor_station"]
            anchor_g_value = previous_day.attrs["next_anchor_g_value"]

            try:
                result = self.line_drift_corrector.compute_day(
                    self.line_drift_pending_data, anchor_station, anchor_g_value
                )
            except LineDriftError as exc:
                QMessageBox.critical(self, "Line Drift Failed", str(exc))
                self.set_status(f"Line Drift Day {len(self.line_drift_results) + 1} failed.")
                return
            except Exception as exc:
                QMessageBox.critical(
                    self, "Unexpected Error",
                    f"An unexpected error occurred during line drift correction:\n\n{exc}",
                )
                self.set_status(f"Line Drift Day {len(self.line_drift_results) + 1} failed (unexpected error).")
                return

            self.line_drift_results.append(result)

        self.line_drift_pending_data = None
        self.populate_line_drift_table(self.line_drift_results)
        self.line_drift_status_label.setText(
            f"Line in progress: {len(self.line_drift_results)} day(s) processed. "
            f"Open the next day's file and click 'Process File' to continue, "
            f"or 'Reset Line' to start over."
        )
        self.set_status(f"Line Drift: Day {len(self.line_drift_results)} processed successfully.")

    def on_reset_line_drift(self):
        """
        Slot for the 'Reset Line' button. Clears all accumulated Line
        Drift state (results, pending file, status) so a new line can
        be started from scratch -- either a new combined file or a
        fresh sequential Day 1.
        """
        self.line_drift_results = []
        self.line_drift_pending_data = None
        self.line_drift_table.clear()
        self.line_drift_table.setRowCount(0)
        self.line_drift_table.setColumnCount(0)
        self.line_drift_log.setRowCount(0)
        self.line_drift_status_label.setText("No line in progress.")
        self.set_status("Line Drift reset.")

    def populate_line_drift_table(self, day_results_list):
        """
        Fill self.line_drift_table with every day's results stacked
        into one table, with a "Day" column prepended so each row is
        traceable to the day it came from. Also refreshes
        self.line_drift_log with each day's closing discrepancy
        (g1_long - g1_short) as a diagnostic -- not auto-corrected,
        per the user, just surfaced for visibility.

        MeanTime is displayed in H:MM format via format_minutes_to_clock(),
        matching populate_results_table()'s convention for Circuit Drift.
        """
        if not day_results_list:
            return

        combined_rows = []
        for day_number, day_df in enumerate(day_results_list, start=1):
            for _, row in day_df.iterrows():
                combined_rows.append({"Day": day_number, **row.to_dict()})

        column_names = ["Day"] + [str(c) for c in day_results_list[0].columns]

        self.line_drift_table.clear()
        self.line_drift_table.setRowCount(len(combined_rows))
        self.line_drift_table.setColumnCount(len(column_names))
        self.line_drift_table.setHorizontalHeaderLabels(column_names)

        for row_idx, row_data in enumerate(combined_rows):
            for col_idx, column_name in enumerate(column_names):
                value = row_data[column_name]
                if column_name == "MeanTime" and isinstance(value, (int, float)):
                    text = format_minutes_to_clock(value)
                elif isinstance(value, float):
                    text = f"{value:.6f}"
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.line_drift_table.setItem(row_idx, col_idx, item)

        self.line_drift_table.resizeColumnsToContents()

        # Diagnostics log: Day 1 has no closure discrepancy (it's an
        # ordinary circuit, not a line-drift day), so only days 2+ get
        # a row here.
        self.line_drift_log.setRowCount(0)
        for day_number, day_df in enumerate(day_results_list, start=1):
            if "closure_discrepancy" not in day_df.attrs:
                continue
            row_idx = self.line_drift_log.rowCount()
            self.line_drift_log.insertRow(row_idx)
            anchor_station = day_df.iloc[1]["Station"] if len(day_df) > 1 else ""
            discrepancy = day_df.attrs["closure_discrepancy"]
            for col_idx, text in enumerate([str(day_number), str(anchor_station), f"{discrepancy:.6f}"]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.line_drift_log.setItem(row_idx, col_idx, item)

    def on_run_least_squares(self):
        """
        Slot for the 'Least Squares Adjustment' button.

        Prompts for a batch of daily drift-corrected files (multi-
        select, one dialog) plus a single Base Station Reference file,
        then delegates matrix assembly and solving entirely to
        core.adjustment.NetworkAdjustment. Per the file-based
        architecture, nothing is read from in-memory state here (not
        even self.drift_corrected_data) -- every file is read fresh
        from disk.
        """
        day_file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Daily Drift-Corrected Files (select all that apply)",
            "",
            "Excel Files (*.xlsx *.xls);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not day_file_paths:
            self.set_status("Least Squares Adjustment cancelled (no daily files selected).")
            return

        base_file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Base Station Reference File",
            "",
            "Excel/CSV Files (*.xlsx *.xls *.csv);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not base_file_path:
            self.set_status("Least Squares Adjustment cancelled (no Base Station Reference file selected).")
            return

        try:
            daily_dataframes = [
                self.network_adjustment.load_drift_corrected_file(p) for p in day_file_paths
            ]
            base_station_df = self.network_adjustment.load_base_station_reference(base_file_path)
        except AdjustmentError as exc:
            QMessageBox.critical(self, "Least Squares Adjustment Failed", str(exc))
            self.set_status("Least Squares Adjustment failed (file loading).")
            return
        except Exception as exc:
            QMessageBox.critical(
                self, "Unexpected Error",
                f"An unexpected error occurred while loading input files:\n\n{exc}",
            )
            self.set_status("Least Squares Adjustment failed (unexpected error).")
            return

        try:
            A, L, station_ids, sigma, obs_labels = self.network_adjustment.build_network(
                daily_dataframes, base_station_df
            )
            results_df, residuals_df = self.network_adjustment.solve_unweighted(
                A, L, station_ids, obs_labels
            )
        except AdjustmentError as exc:
            QMessageBox.critical(self, "Least Squares Adjustment Failed", str(exc))
            self.set_status("Least Squares Adjustment failed.")
            return
        except Exception as exc:
            QMessageBox.critical(
                self, "Unexpected Error",
                f"An unexpected error occurred during the adjustment:\n\n{exc}",
            )
            self.set_status("Least Squares Adjustment failed (unexpected error).")
            return

        self.least_squares_results = results_df
        # Reuse the existing self.adjusted_results slot (already wired
        # to the Residual Plot / Residual Histogram graphs) so those
        # graphs work immediately with real data, no extra plumbing.
        self.adjusted_results = residuals_df
        self.populate_least_squares_tables(results_df, residuals_df)

        self.main_tab_widget.setCurrentWidget(self.least_squares_tab_widget)

        self.set_status(
            f"Least Squares Adjustment complete: {len(station_ids)} station(s), "
            f"{len(obs_labels)} observation(s) from {len(day_file_paths)} day file(s)."
        )

        self._refresh_graph("residual_plot")
        self._refresh_graph("residual_histogram")

    def on_show_graph(self, graph_type: str):
        """
        Slot for all 4 graph buttons/menu actions (Phase 7).

        Switches to the "Graphs" tab, switches the inner tab to the
        requested graph_type, and (re)draws it from the latest
        available data via visualization.graphs.
        """
        if graph_type not in self.GRAPH_TYPES:
            QMessageBox.warning(self, "Unknown Graph", f"Unrecognized graph type: '{graph_type}'.")
            return

        self._refresh_graph(graph_type)

        # Switch the outer tab to "Graphs" and the inner tab to the
        # requested graph.
        self.main_tab_widget.setCurrentWidget(self.graphs_tab_widget)
        graph_index = self.GRAPH_TYPES.index(graph_type)
        self.graphs_tab_widget.setCurrentIndex(graph_index)

        self.set_status(f"Showing graph: {graph_type.replace('_', ' ').title()}.")

    def _refresh_graph(self, graph_type: str):
        """
        Clear and redraw a single graph's Axes using the current
        in-memory data, via the pure plotting functions in
        visualization.graphs. Safe to call at any time (including
        before any data has been loaded/processed) -- the plotting
        functions render a placeholder message when their required
        data isn't available yet.
        """
        widget_set = self.graph_widgets.get(graph_type)
        if widget_set is None:
            return

        axes = widget_set["axes"]
        axes.clear()

        if graph_type == "drift_curve":
            graphs.plot_drift_curve(axes, self.drift_corrected_data)
        elif graph_type == "raw_vs_adjusted":
            graphs.plot_raw_vs_adjusted(axes, self.drift_corrected_data)
        elif graph_type == "residual_plot":
            graphs.plot_residual_plot(axes, self.adjusted_results)
        elif graph_type == "residual_histogram":
            graphs.plot_residual_histogram(axes, self.adjusted_results)

        widget_set["figure"].tight_layout()
        widget_set["canvas"].draw()

    def on_export_excel(self):
        """
        Slot for the 'Export Excel' button/menu action (Phase 8).
        Validates there's data to export, prompts for a save location,
        and delegates the actual workbook creation to
        reports.excel_export.export_to_excel().
        """
        if self.observation_data is None and self.drift_corrected_data is None:
            QMessageBox.warning(
                self, "Nothing to Export",
                "Please import a file and/or run drift correction "
                "before exporting to Excel.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export to Excel", "gravity_report.xlsx",
            "Excel Files (*.xlsx);;All Files (*)",
        )
        if not file_path:
            self.set_status("Excel export cancelled.")
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"

        known_g_value = None
        g_text = self.input_known_g_value.text().strip()
        if g_text:
            try:
                known_g_value = float(g_text)
            except ValueError:
                known_g_value = None

        try:
            export_to_excel(
                file_path,
                observation_data=self.observation_data,
                drift_corrected_data=self.drift_corrected_data,
                known_g_value=known_g_value,
            )
        except ExcelExportError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            self.set_status("Excel export failed.")
            return
        except Exception as exc:
            QMessageBox.critical(
                self, "Unexpected Error",
                f"An unexpected error occurred while exporting to Excel:\n\n{exc}",
            )
            self.set_status("Excel export failed (unexpected error).")
            return

        file_name = os.path.basename(file_path)
        self.set_status(f"Exported to '{file_name}'.")
        QMessageBox.information(
            self, "Export Successful", f"Data exported successfully to:\n{file_path}",
        )

    def on_export_for_least_squares(self):
        """
        Slot for the 'Export for Least Squares' button. Exports ONLY
        the drift-corrected results table -- no graphs, no summary
        block, no Observations sheet -- via
        reports.excel_export.export_drift_only(). Intended as a clean,
        minimal input file for the Phase 5 network adjustment, which
        will re-import one file like this per survey day. Works in
        both 'With Known G Value' and 'Without Known G Value' modes --
        GValue is simply blank in the latter case.
        """
        if self.drift_corrected_data is None:
            QMessageBox.warning(
                self, "Nothing to Export",
                "Please run drift correction before exporting for Least Squares.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export for Least Squares", "drift_corrected.xlsx",
            "Excel Files (*.xlsx);;All Files (*)",
        )
        if not file_path:
            self.set_status("Export for Least Squares cancelled.")
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"

        try:
            export_drift_only(file_path, self.drift_corrected_data)
        except ExcelExportError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            self.set_status("Export for Least Squares failed.")
            return
        except Exception as exc:
            QMessageBox.critical(
                self, "Unexpected Error",
                f"An unexpected error occurred while exporting:\n\n{exc}",
            )
            self.set_status("Export for Least Squares failed (unexpected error).")
            return

        file_name = os.path.basename(file_path)
        self.set_status(f"Exported '{file_name}' for Least Squares input.")
        QMessageBox.information(
            self, "Export Successful",
            f"Drift-corrected data exported successfully to:\n{file_path}",
        )

    def on_export_pdf(self):
        """
        Slot for the 'Export PDF' button/menu action (Phase 9).
        Validates there's data to export, refreshes all 4 graphs so
        the PDF reflects the latest data (even if the user never
        opened the Graphs tab), prompts for a save location, and
        delegates the actual PDF building to
        reports.pdf_report.export_to_pdf().
        """
        if self.observation_data is None and self.drift_corrected_data is None:
            QMessageBox.warning(
                self, "Nothing to Export",
                "Please import a file and/or run drift correction "
                "before exporting to PDF.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export to PDF", "gravity_report.pdf",
            "PDF Files (*.pdf);;All Files (*)",
        )
        if not file_path:
            self.set_status("PDF export cancelled.")
            return
        if not file_path.lower().endswith(".pdf"):
            file_path += ".pdf"

        known_g_value = None
        g_text = self.input_known_g_value.text().strip()
        if g_text:
            try:
                known_g_value = float(g_text)
            except ValueError:
                known_g_value = None

        # Refresh every graph with the latest data before embedding,
        # so the PDF is correct even if the user never opened the
        # Graphs tab in this session.
        for graph_type in self.GRAPH_TYPES:
            self._refresh_graph(graph_type)
        graph_figures = {
            self.GRAPH_TITLES[graph_type]: self.graph_widgets[graph_type]["figure"]
            for graph_type in self.GRAPH_TYPES
        }

        try:
            export_to_pdf(
                file_path,
                observation_data=self.observation_data,
                drift_corrected_data=self.drift_corrected_data,
                known_g_value=known_g_value,
                graph_figures=graph_figures,
            )
        except PdfReportError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            self.set_status("PDF export failed.")
            return
        except Exception as exc:
            QMessageBox.critical(
                self, "Unexpected Error",
                f"An unexpected error occurred while exporting to PDF:\n\n{exc}",
            )
            self.set_status("PDF export failed (unexpected error).")
            return

        file_name = os.path.basename(file_path)
        self.set_status(f"Exported to '{file_name}'.")
        QMessageBox.information(
            self, "Export Successful", f"Report exported successfully to:\n{file_path}",
        )

    def on_show_about(self):
        """Shows a simple About dialog."""
        QMessageBox.information(
            self,
            "About Gravity Adjustment Software",
            "Gravity Adjustment Software\n"
            "A professional tool for processing gravity survey observations.\n\n"
            "Built with Python, PySide6, NumPy, SciPy, Pandas, and Matplotlib.",
        )

    def _show_not_implemented(self, feature_name: str, phase: int):
        """
        Shared helper for features not yet implemented in the current
        development phase. Keeps the GUI fully clickable while the
        rest of the application is being built incrementally.
        """
        self.set_status(f"'{feature_name}' will be implemented in Phase {phase}.")
        QMessageBox.information(
            self,
            "Not Yet Implemented",
            f"'{feature_name}' will be implemented in Phase {phase}.",
        )