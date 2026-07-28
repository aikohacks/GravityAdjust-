"""
main.py
-------
Entry point for the Gravity Adjustment Software.

This file is intentionally minimal. Its only job is to:
    1. Create the Qt Application instance.
    2. Create and show the MainWindow (defined in gui.py).
    3. Start the Qt event loop.

No GUI logic and no computational logic should ever live here.
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication

from gui import MainWindow


def main():
    """Bootstraps and runs the Gravity Adjustment Software application."""
    # Fix for garbled/"melted" text rendering on Windows displays using
    # a fractional scale factor (125%, 150%, 175%, etc.). Qt6's default
    # DPI-rounding policy can misrender text at those scale factors;
    # PassThrough uses the exact scale factor instead of rounding it.
    # MUST be set before the QApplication instance is created.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Gravity Adjustment Software")
    app.setOrganizationName("Geodesy Tools")

    # Set a larger, cleaner default font across the whole app.
    default_font = QFont("Segoe UI", 10)
    app.setFont(default_font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()