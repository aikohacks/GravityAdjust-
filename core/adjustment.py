"""
core/adjustment.py
-------------------
Least Squares Adjustment logic for gravity observations.

STATUS: Not yet implemented (reserved for Phase 5).

This module will contain a class (e.g. `LeastSquaresAdjustment`) that:
    - Accepts drift-corrected observations.
    - Builds the design matrix (A), observation vector (L), and
      weight matrix (P).
    - Solves the least squares system using SciPy / NumPy
      (e.g. via `scipy.linalg.lstsq` or normal equations).
    - Returns adjusted gravity values, residuals, and the
      variance-covariance matrix.

Kept intentionally empty in Phase 1 so the project structure is
complete from the start, per the incremental development plan.
"""
