"""ESMValTool diagnostic script for SUMMA forcing generation.

Converts preprocessed ESMValTool meteorological data into SUMMA's
required NetCDF format:
  - Renames CMOR variables to SUMMA names
  - Converts units to SUMMA conventions
  - Reshapes to (time, hru) dimensions
  - Writes a single forcing NetCDF per output

Variable mapping (CMOR -> SUMMA):
  tas     -> airtemp    (K, no conversion needed)
  pr      -> pptrate    (kg m-2 s-1 -> kg m-2 s-1, same)
  rsds    -> SWRadAtm   (W m-2, no conversion needed)
  rlds    -> LWRadAtm   (W m-2, no conversion needed)
  huss    -> spechum    (kg kg-1, no conversion needed)
  sfcWind -> windspd    (m s-1, no conversion needed)
  ps      -> airpres    (Pa, no conversion needed)
"""

import logging
import os
from pathlib import Path

import iris
import numpy as np

from esmvaltool.diag_scripts.shared import (
    ProvenanceLogger,
    group_metadata,
    run_diagnostic,
)

logger = logging.getLogger(Path(__file__).stem)

CMOR_TO_SUMMA = {
    "tas": "airtemp",
    "pr": "pptrate",
    "rsds": "SWRadAtm",
    "rlds": "LWRadAtm",
    "huss": "spechum",
    "sfcWind": "windspd",
    "ps": "airpres",
}

SUMMA_UNITS = {
    "airtemp": "K",
    "pptrate": "kg m-2 s-1",
    "SWRadAtm": "W m-2",
    "LWRadAtm": "W m-2",
    "spechum": "kg kg-1",
    "windspd": "m s-1",
    "airpres": "Pa",
}


def _load_cube(metadata: dict) -> iris.cube.Cube:
    """Load a single variable from preprocessed ESMValTool output."""
    filename = metadata["filename"]
    cube = iris.load_cube(filename)
    return cube


def _compute_data_step(cube: iris.cube.Cube) -> int:
    """Compute the timestep in seconds from the time coordinate."""
    time_coord = cube.coord("time")
    if len(time_coord.points) < 2:
        return 3600
    dt = time_coord.points[1] - time_coord.points[0]
    unit = time_coord.units
    t0 = unit.num2date(time_coord.points[0])
    t1 = unit.num2date(time_coord.points[1])
    return int((t1 - t0).total_seconds())


def main(cfg: dict):
    """Convert ESMValTool preprocessed data to SUMMA forcing format."""
    input_data = cfg["input_data"].values()
    grouped = group_metadata(input_data, "short_name")
    basin = cfg.get("basin", "basin")

    cubes = {}
    for short_name, metadata_list in grouped.items():
        if short_name not in CMOR_TO_SUMMA:
            continue
        cube = _load_cube(metadata_list[0])
        cubes[short_name] = cube
        logger.info("Loaded %s: shape=%s", short_name, cube.shape)

    if not cubes:
        raise ValueError("No forcing variables found in preprocessed data")

    ref_cube = next(iter(cubes.values()))
    time_coord = ref_cube.coord("time")
    n_times = len(time_coord.points)
    data_step = _compute_data_step(ref_cube)

    has_lat = ref_cube.coords("latitude")
    has_lon = ref_cube.coords("longitude")

    if has_lat and has_lon:
        lats = ref_cube.coord("latitude").points
        lons = ref_cube.coord("longitude").points
        if lats.ndim > 1:
            lats = lats.flatten()
            lons = lons.flatten()
        n_hru = len(lats)
    else:
        n_hru = 1
        lats = np.array([0.0])
        lons = np.array([0.0])

    start_year = time_coord.units.num2date(time_coord.points[0]).year
    end_year = time_coord.units.num2date(time_coord.points[-1]).year
    output_name = f"summa_{basin}_{start_year}_{end_year}.nc"
    output_path = Path(cfg["work_dir"]) / output_name

    import netCDF4 as nc

    with nc.Dataset(str(output_path), "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("hru", n_hru)

        time_var = ds.createVariable("time", "f8", ("time",))
        time_var.units = str(time_coord.units)
        time_var.calendar = getattr(time_coord.units, "calendar", "standard")
        time_var[:] = time_coord.points

        hru_id = ds.createVariable("hruId", "i4", ("hru",))
        hru_id[:] = np.arange(1, n_hru + 1)

        lat_var = ds.createVariable("latitude", "f8", ("hru",))
        lat_var[:] = lats.flatten()[:n_hru]

        lon_var = ds.createVariable("longitude", "f8", ("hru",))
        lon_var[:] = lons.flatten()[:n_hru]

        ds_var = ds.createVariable("data_step", "f8")
        ds_var[:] = float(data_step)

        for cmor_name, summa_name in CMOR_TO_SUMMA.items():
            if cmor_name not in cubes:
                logger.warning("Missing variable %s, filling with zeros", cmor_name)
                data = np.zeros((n_times, n_hru), dtype=np.float64)
            else:
                cube = cubes[cmor_name]
                data = cube.data
                if data.ndim == 1:
                    data = data.reshape(-1, 1)
                elif data.ndim > 2:
                    spatial_size = int(np.prod(data.shape[1:]))
                    data = data.reshape(n_times, spatial_size)
                data = data[:, :n_hru].astype(np.float64)

            var = ds.createVariable(
                summa_name, "f8", ("time", "hru"),
                zlib=True, complevel=4,
            )
            var.units = SUMMA_UNITS[summa_name]
            var[:] = data

        ds.Conventions = "CF-1.6"
        ds.model_format = "SUMMA"
        ds.history = f"Created by ewatercycle-summa diagnostic script"

    logger.info("Wrote SUMMA forcing: %s (%d times, %d HRUs)", output_path, n_times, n_hru)

    provenance = {
        "caption": f"SUMMA forcing for {basin}",
        "domains": ["global"],
        "authors": ["ewatercycle-summa"],
        "references": ["summa"],
    }
    with ProvenanceLogger(cfg) as provenance_logger:
        provenance_logger.log(str(output_path), provenance)


if __name__ == "__main__":
    with run_diagnostic() as config:
        main(config)
