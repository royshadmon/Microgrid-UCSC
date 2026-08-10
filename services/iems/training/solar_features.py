"""Deterministic solar-geometry features for the Mantey site (Los Gatos, CA).

Measured Solar Assistant PV covers only days (Aug 3-4 as of this writing), so
it cannot feature a March-July retrain. Solar GEOMETRY, however, is exact for
every timestamp: sun elevation and a clear-sky irradiance proxy are computable
with no data at all (NOAA SPA approximation, adequate to <0.5 deg here).

These drive:
  - the solar gates (solar_pump cannot run with the sun down; the additive
    water-heater fallback keys off low solar)
  - BiLSTM input features that exist across the ENTIRE archive, with measured
    pv_power merged on top where it overlaps (pv_valid flags the real thing).

LAT/LON: Los Gatos, CA. TZ handling is UTC-in, so no DST logic is needed.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

LAT, LON = 37.2358, -121.9624  # degrees; LON negative = west


def sun_elevation_deg(idx: pd.DatetimeIndex) -> np.ndarray:
    """Solar elevation (deg) for UTC timestamps. Vectorized NOAA approximation."""
    ts = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    doy = ts.dayofyear.to_numpy(float)
    hh = ts.hour.to_numpy(float) + ts.minute.to_numpy(float) / 60.0 \
         + ts.second.to_numpy(float) / 3600.0
    g = 2.0 * np.pi / 365.0 * (doy - 1.0 + (hh - 12.0) / 24.0)
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g)
            - 0.006758 * np.cos(2 * g) + 0.000907 * np.sin(2 * g)
            - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g)
                    - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    tst = hh * 60.0 + eqt + 4.0 * LON          # true solar time, minutes
    ha = np.radians(tst / 4.0 - 180.0)         # hour angle
    lat = np.radians(LAT)
    sin_el = (np.sin(lat) * np.sin(decl)
              + np.cos(lat) * np.cos(decl) * np.cos(ha))
    return np.degrees(np.arcsin(np.clip(sin_el, -1.0, 1.0)))


def clear_sky_ghi(elev_deg: np.ndarray) -> np.ndarray:
    """Haurwitz clear-sky GHI (W/m^2). Zero when the sun is down."""
    el = np.radians(np.clip(elev_deg, 0.0, None))
    cz = np.sin(el)  # cos(zenith) = sin(elevation)
    ghi = 1098.0 * cz * np.exp(-0.059 / np.clip(cz, 1e-3, None))
    ghi[elev_deg <= 0] = 0.0
    return ghi


def solar_frame(idx: pd.DatetimeIndex,
                measured_parquet: str | None = None) -> pd.DataFrame:
    """sun_elev, csky_ghi for every row; pv_power/pv_valid merged if available."""
    el = sun_elevation_deg(idx)
    F = pd.DataFrame(index=idx)
    F["sun_elev"] = el
    F["csky_ghi"] = clear_sky_ghi(el)
    F["pv_power"], F["pv_valid"] = 0.0, 0.0
    if measured_parquet:
        try:
            sol = pd.read_parquet(measured_parquet)
            sol = sol[~sol.index.duplicated(keep="last")]
            sol.index = pd.to_datetime(sol.index)
            sr = sol["pv_power"].reindex(idx, method="ffill",
                                         tolerance=pd.Timedelta("120s"))
            ok = sr.notna()
            F.loc[ok, "pv_power"] = pd.to_numeric(sr[ok], errors="coerce").fillna(0.0)
            F.loc[ok, "pv_valid"] = 1.0
        except Exception as e:  # measured solar is optional by design
            print(f"      [solar_features] measured merge skipped: {e}")
    return F
