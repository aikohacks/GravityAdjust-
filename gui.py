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
)
from PySide6.QtGui import QAction, QFont, QKeySequence, QIcon, QDoubleValidator
from PySide6.QtCore import Qt, QSize

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from core.data_loader import GravityDataLoader, DataLoadError
from core.drift import DriftCorrector, DriftCorrectionError, format_minutes_to_clock
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

    # Maps each graph_type string (used by button/menu actions) to the
    # (tab_index in the inner graphs QTabWidget, plotting function in
    # visualization.graphs) it corresponds to. Built in _build_graphs_panel().
    GRAPH_TYPES = ["raw_vs_adjusted", "drift_curve", "residual_plot", "residual_histogram"]

    def __init__(self):
        super().__init__()

        # In-memory placeholders for data that later phases will
        # populate. Kept here so the GUI has somewhere to store state,
        # but the actual processing logic will live in core/.
        self.observation_data = None   # will hold imported observations (Phase 2/3)
        self.drift_corrected_data = None  # will hold drift-corrected visits (Phase 4)
        self.adjusted_results = None   # will hold least-squares results (Phase 5/6)
        # Data loader (computation logic lives in core/, not here)
        self.data_loader = GravityDataLoader()
        self.drift_corrector = DriftCorrector(readings_per_visit=5)
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
                padding-top: 8px;
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
        panel = QFrame()
        panel.setFixedWidth(230)
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        # --- Data group ---
        data_group = QGroupBox("Data")
        data_layout = QVBoxLayout(data_group)
        self.btn_open_file = QPushButton("Open File")
        self.btn_open_file.clicked.connect(self.on_open_file)
        data_layout.addWidget(self.btn_open_file)
        layout.addWidget(data_group)

       # --- Processing group ---
        processing_group = QGroupBox("Processing")
        processing_layout = QVBoxLayout(processing_group)

        # Known G Value input -- a permanent field, since drift
        # correction needs an absolute gravimeter reading entered
        # manually by the surveyor for each session/circuit.
        known_g_form = QFormLayout()
        self.input_known_g_value = QLineEdit()
        self.input_known_g_value.setPlaceholderText("e.g. 979.436285")
        self.input_known_g_value.setValidator(QDoubleValidator(-999999.0, 999999.0, 6))
        known_g_form.addRow(QLabel("Known G Value:"), self.input_known_g_value)
        processing_layout.addLayout(known_g_form)

        self.btn_drift_correction = QPushButton("Drift Correction")
        self.btn_drift_correction.clicked.connect(self.on_apply_drift_correction)
        self.btn_least_squares = QPushButton("Least Squares Adjustment")
        self.btn_least_squares.clicked.connect(self.on_run_least_squares)
        processing_layout.addWidget(self.btn_drift_correction)
        processing_layout.addWidget(self.btn_least_squares)
        layout.addWidget(processing_group)

        # --- Graphs group ---
        graphs_group = QGroupBox("Graphs")
        graphs_layout = QVBoxLayout(graphs_group)
        self.btn_graph_raw_vs_adjusted = QPushButton("Raw vs Adjusted")
        self.btn_graph_raw_vs_adjusted.clicked.connect(
            lambda: self.on_show_graph("raw_vs_adjusted")
        )
        self.btn_graph_drift_curve = QPushButton("Drift Curve")
        self.btn_graph_drift_curve.clicked.connect(
            lambda: self.on_show_graph("drift_curve")
        )
        self.btn_graph_residuals = QPushButton("Residual Plot")
        self.btn_graph_residuals.clicked.connect(
            lambda: self.on_show_graph("residual_plot")
        )
        self.btn_graph_histogram = QPushButton("Residual Histogram")
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
        self.btn_export_excel.clicked.connect(self.on_export_excel)
        self.btn_export_pdf = QPushButton("Export PDF")
        self.btn_export_pdf.clicked.connect(self.on_export_pdf)
        export_layout.addWidget(self.btn_export_excel)
        export_layout.addWidget(self.btn_export_pdf)
        layout.addWidget(export_group)

        layout.addStretch(1)
        return panel

    def _build_right_panel(self):
        """
        Builds the right-hand QTabWidget containing the "Data & Results"
        tab (existing tables splitter) and the "Graphs" tab (Phase 7).
        """
        self.main_tab_widget = QTabWidget()
        self.main_tab_widget.addTab(self._build_tables_panel(), "Data && Results")
        self.main_tab_widget.addTab(self._build_graphs_panel(), "Graphs")
        return self.main_tab_widget

    def _build_tables_panel(self):
        """Builds the splitter containing the data and results tables."""
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
        self.data_table.setFont(QFont("Segoe UI", 10))
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
        self.results_table.setFont(QFont("Segoe UI", 10))
        results_box_layout.addWidget(self.results_table)
        splitter.addWidget(results_box)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        return splitter

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

        graph_titles = {
            "raw_vs_adjusted": "Raw vs Adjusted",
            "drift_curve": "Drift Curve",
            "residual_plot": "Residual Plot",
            "residual_histogram": "Residual Histogram",
        }

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

            self.graphs_tab_widget.addTab(tab, graph_titles[graph_type])

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

    def on_apply_drift_correction(self):
        """
        Slot for the 'Drift Correction' button.
        Phase 4: validates inputs, then delegates the math to
        core.drift.DriftCorrector. Displays the result in the results table.
        """
        if self.observation_data is None:
            QMessageBox.warning(
                self,
                "No Data Imported",
                "Please open an observation file before applying drift correction.",
            )
            return

        g_text = self.input_known_g_value.text().strip()
        if not g_text:
            QMessageBox.warning(
                self,
                "Known G Value Required",
                "Please enter the known (absolute) G value before applying "
                "drift correction.",
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
        displayed here in the original 'H.MM' clock-style format
        (e.g. 98.0 minutes -> "1.38") for readability.
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
                if column_name == "MeanTime" and isinstance(value, (int, float)):
                    text = format_minutes_to_clock(value)
                elif isinstance(value, float):
                    text = f"{value:.6f}"
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.results_table.setItem(row_idx, col_idx, item)

        self.results_table.resizeColumnsToContents()

    def on_run_least_squares(self):
        """Placeholder slot for least squares adjustment (implemented in Phase 5)."""
        self._show_not_implemented("Least Squares Adjustment", phase=5)

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
        """Placeholder slot for Excel export (implemented in Phase 8)."""
        self._show_not_implemented("Export to Excel", phase=8)

    def on_export_pdf(self):
        """Placeholder slot for PDF export (implemented in Phase 9)."""
        self._show_not_implemented("Export to PDF", phase=9)

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