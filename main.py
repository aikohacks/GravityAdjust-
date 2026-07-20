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

from PySide6.QtWidgets import QApplication

from PySide6.QtGui import QFont

from gui import MainWindow


def main():
    """Bootstraps and runs the Gravity Adjustment Software application."""
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
