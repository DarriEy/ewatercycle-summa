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
    else:
        lats = np.array([0.0])
        lons = np.array([0.0])

    # Build a spatial mask from the reference cube to identify valid HRUs.
    # extract_shape sets cells outside the catchment to NaN/masked, so we
    # find cells that have at least one valid timestep.
    ref_data = ref_cube.data
    if ref_data.ndim > 2:
        flat_spatial = ref_data.reshape(n_times, -1)
    elif ref_data.ndim == 2:
        flat_spatial = ref_data
    else:
        flat_spatial = ref_data.reshape(-1, 1)

    if hasattr(flat_spatial, "mask") and flat_spatial.mask is not np.False_:
        if flat_spatial.mask.ndim == 0:
            valid_mask = np.ones(flat_spatial.shape[1], dtype=bool)
        else:
            valid_mask = ~np.all(flat_spatial.mask, axis=0)
    else:
        valid_mask = np.ones(flat_spatial.shape[1], dtype=bool)

    valid_indices = np.where(valid_mask)[0]
    n_hru = len(valid_indices) if len(valid_indices) > 0 else 1

    if lats.ndim > 1:
        flat_lats = lats.flatten()
        flat_lons = lons.flatten()
    else:
        lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")
        flat_lats = lat_grid.flatten()
        flat_lons = lon_grid.flatten()

    hru_lats = flat_lats[valid_indices] if len(valid_indices) > 0 else lats[:1]
    hru_lons = flat_lons[valid_indices] if len(valid_indices) > 0 else lons[:1]

    logger.info("Spatial grid: %d total cells, %d valid HRUs", len(valid_mask), n_hru)

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
        lat_var[:] = hru_lats

        lon_var = ds.createVariable("longitude", "f8", ("hru",))
        lon_var[:] = hru_lons

        ds_var = ds.createVariable("data_step", "f8")
        ds_var[:] = float(data_step)

        for cmor_name, summa_name in CMOR_TO_SUMMA.items():
            if cmor_name not in cubes:
                logger.warning("Missing variable %s, filling with zeros", cmor_name)
                data = np.zeros((n_times, n_hru), dtype=np.float64)
            else:
                cube = cubes[cmor_name]
                raw = cube.data
                if raw.ndim == 1:
                    raw = raw.reshape(-1, 1)
                elif raw.ndim > 2:
                    raw = raw.reshape(n_times, -1)
                if hasattr(raw, "filled"):
                    raw = raw.filled(np.nan)
                data = raw[:, valid_indices].astype(np.float64)

            var = ds.createVariable(
                summa_name, "f8", ("time", "hru"),
                zlib=True, complevel=4,
            )
            var.units = SUMMA_UNITS[summa_name]
            var[:] = data

        ds.Conventions = "CF-1.6"
        ds.model_format = "SUMMA"
        ds.history = "Created by ewatercycle-summa diagnostic script"

    logger.info(
        "Wrote SUMMA forcing: %s (%d times, %d HRUs)",
        output_path, n_times, n_hru,
    )

    provenance = {
        "caption": f"SUMMA forcing for {basin}",
        "domains": ["global"],
        "authors": ["unmaintained"],
        "references": ["acknowledge_project"],
    }
    with ProvenanceLogger(cfg) as provenance_logger:
        provenance_logger.log(str(output_path), provenance)


if __name__ == "__main__":
    with run_diagnostic() as config:
        main(config)
