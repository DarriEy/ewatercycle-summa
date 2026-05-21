"""Pure utility functions for SUMMA configuration handling.

No ewatercycle dependency — can be tested and used standalone.
"""

import datetime
import re
from pathlib import Path

# SUMMA variable names mapped from CSDMS standard names used in the BMI.
# Extracted from SYMFLUENCE's SUMMAForcingAdapter (forcing_adapter.py).
SUMMA_INPUT_VARIABLES = {
    "atmosphere_water__precipitation_mass_flux": "pptrate",
    "land_surface_air__temperature": "airtemp",
    "atmosphere_air_water~vapor__relative_saturation": "spechum",
    "land_surface_wind__x_component_of_velocity": "windspd",
    "land_surface_wind__y_component_of_velocity": "windspd",
    "land_surface_radiation~incoming~shortwave__energy_flux": "SWRadAtm",
    "land_surface_radiation~incoming~longwave__energy_flux": "LWRadAtm",
    "land_surface_air__pressure": "airpres",
}

# Reverse mapping: SUMMA NetCDF variable name → CSDMS BMI input name(s).
# NGEN mode uses x/y wind components; standard SUMMA uses scalar windspd.
SUMMA_NETCDF_TO_BMI = {
    "pptrate": "atmosphere_water__precipitation_mass_flux",
    "airtemp": "land_surface_air__temperature",
    "spechum": "atmosphere_air_water~vapor__relative_saturation",
    "windspd": "land_surface_wind__x_component_of_velocity",
    "SWRadAtm": "land_surface_radiation~incoming~shortwave__energy_flux",
    "LWRadAtm": "land_surface_radiation~incoming~longwave__energy_flux",
    "airpres": "land_surface_air__pressure",
}

SUMMA_OUTPUT_VARIABLES = {
    "land_surface_water__runoff_volume_flux": "averageRoutedRunoff",
    "land_surface_water__evaporation_mass_flux": "scalarLatHeatTotal",
    "snowpack_mass": "scalarSWE",
    "soil_water__mass": "scalarTotalSoilWat",
    "land_surface_water__baseflow_volume_flux": "scalarAquiferBaseflow",
}


def parse_file_manager(path: Path) -> dict[str, str]:
    """Parse a SUMMA fileManager.txt into a dict.

    Each line has the format: ``key  'value'`` (value is single-quoted).
    Comment lines starting with ``!`` and blank lines are skipped.
    """
    config: dict[str, str] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("!"):
                continue
            match = re.match(r"(\S+)\s+'([^']*)'", line)
            if match:
                config[match.group(1)] = match.group(2)
    return config


def write_file_manager(config: dict[str, str], path: Path) -> None:
    """Write a SUMMA fileManager.txt from a dict."""
    with path.open("w") as f:
        for key, value in config.items():
            f.write(f"{key:<20} '{value}'\n")


def parse_summa_time(time_str: str) -> datetime.datetime:
    """Parse SUMMA time string like '2000-01-01 00:00'."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse SUMMA time string: {time_str!r}")
