"""Uniform lat/lon grid indexing shared by every module."""
from __future__ import annotations

import numpy as np

from .config import GRID_DEG, GRID_NX, GRID_NY


def cell_of(lat, lon):
    """Vectorised (lat, lon) -> global cell id."""
    ix = np.floor((np.asarray(lon, dtype="float64") + 180.0) / GRID_DEG).astype("int64")
    iy = np.floor((np.asarray(lat, dtype="float64") + 90.0) / GRID_DEG).astype("int64")
    ix = np.clip(ix, 0, GRID_NX - 1)
    iy = np.clip(iy, 0, GRID_NY - 1)
    return (iy * GRID_NX + ix).astype("int32")


def cell_ixiy(cell_id):
    c = np.asarray(cell_id, dtype="int64")
    return c % GRID_NX, c // GRID_NX


def cell_bounds(cell_id):
    """-> (west, south, east, north) arrays."""
    ix, iy = cell_ixiy(cell_id)
    w = ix * GRID_DEG - 180.0
    s = iy * GRID_DEG - 90.0
    return w, s, w + GRID_DEG, s + GRID_DEG


def cell_center(cell_id):
    w, s, e, n = cell_bounds(cell_id)
    return (s + n) / 2.0, (w + e) / 2.0


def cells_in_bbox(w: float, s: float, e: float, n: float) -> np.ndarray:
    ix0 = int(np.floor((w + 180.0) / GRID_DEG))
    ix1 = int(np.ceil((e + 180.0) / GRID_DEG)) - 1
    iy0 = int(np.floor((s + 90.0) / GRID_DEG))
    iy1 = int(np.ceil((n + 90.0) / GRID_DEG)) - 1
    ix = np.arange(max(ix0, 0), min(ix1, GRID_NX - 1) + 1)
    iy = np.arange(max(iy0, 0), min(iy1, GRID_NY - 1) + 1)
    return (iy[:, None] * GRID_NX + ix[None, :]).ravel().astype("int32")


def cell_area_km2(cell_id):
    lat, _ = cell_center(cell_id)
    return (111.32 * GRID_DEG) * (111.32 * GRID_DEG * np.cos(np.radians(lat)))
