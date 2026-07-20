"""
core/data_loader.py
--------------------
File import logic for the Gravity Adjustment Software.

Responsibilities:
    - Read gravity observation data from CSV or Excel files into a
      pandas DataFrame.
    - Perform basic validation (file exists, supported extension,
      not empty, readable).
    - Raise clear, GUI-friendly exceptions on failure so gui.py can
      show a helpful message box instead of crashing.

This module contains NO GUI code. It is called from gui.py's
open_file() handler.
"""

import os
import pandas as pd


class DataLoadError(Exception):
    """Raised when a gravity observation file cannot be loaded or is invalid."""
    pass


class GravityDataLoader:
    """
    Loads gravity observation data from CSV or Excel files.

    Usage:
        loader = GravityDataLoader()
        df = loader.load(file_path)
    """

    SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".xls")

    def load(self, file_path: str) -> pd.DataFrame:
        """
        Load a gravity observation file into a pandas DataFrame.

        Args:
            file_path: Absolute or relative path to a .csv, .xlsx, or .xls file.

        Returns:
            pandas.DataFrame containing the imported observations.

        Raises:
            DataLoadError: if the file is missing, has an unsupported
                extension, is empty, or cannot be parsed.
        """
        self._validate_path(file_path)

        extension = os.path.splitext(file_path)[1].lower()

        try:
            if extension == ".csv":
                df = pd.read_csv(file_path)
            else:  # .xlsx or .xls
                df = pd.read_excel(file_path)
        except Exception as exc:
            raise DataLoadError(
                f"Failed to parse the file. It may be corrupted or in an "
                f"unexpected format.\n\nDetails: {exc}"
            ) from exc

        self._validate_dataframe(df)

        # Drop fully empty rows/columns that sometimes appear from
        # trailing blank lines in exported CSV/Excel files.
        df = df.dropna(how="all")
        df = df.dropna(axis=1, how="all")
        df = df.reset_index(drop=True)

        return df

    def _validate_path(self, file_path: str):
        """Check the file exists and has a supported extension."""
        if not file_path:
            raise DataLoadError("No file path was provided.")

        if not os.path.isfile(file_path):
            raise DataLoadError(f"File not found:\n{file_path}")

        extension = os.path.splitext(file_path)[1].lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            raise DataLoadError(
                f"Unsupported file type '{extension}'.\n"
                f"Supported types: {', '.join(self.SUPPORTED_EXTENSIONS)}"
            )

    def _validate_dataframe(self, df: pd.DataFrame):
        """Check the parsed data is non-empty and has at least one column."""
        if df is None or df.empty:
            raise DataLoadError(
                "The file was read successfully but contains no data rows."
            )

        if len(df.columns) == 0:
            raise DataLoadError("The file contains no recognizable columns.")