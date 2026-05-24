"""Full end-to-end example: generate parameter set + run SUMMA via eWaterCycle.

This script demonstrates the complete workflow from raw geospatial data
to hydrological simulation output, using the ewatercycle-summa plugin.

Requires:
  - ewatercycle + ewatercycle-summa installed
  - symfluence installed (for parameter set generation)
  - Docker running (for SUMMA container)
  - Bow at Banff domain data (set SUMMA_DOMAIN_DIR to the path)
"""

import logging
import os
import tempfile
import time
from pathlib import Path

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("e2e_example")

BOW = Path(
    os.environ.get(
        "SUMMA_DOMAIN_DIR",
        "domain_Bow_at_Banff_lumped",
    )
)
SHP = BOW / "shapefiles/catchment/lumped/snow17_run_1/Bow_at_Banff_lumped_HRUs_GRUS.shp"
DEM = BOW / "data/attributes/dem/dem.tif"
SOIL = BOW / "data/attributes/soilclass/domain_Bow_at_Banff_lumped_soil_classes.tif"
LAND = BOW / "data/attributes/landclass/domain_Bow_at_Banff_lumped_land_classes.tif"
FORCING = BOW / "data/forcing/SUMMA_input"


def main():
    t_total = time.time()

    # =========================================================================
    # Step 1: Generate SUMMA parameter set from geospatial data
    # =========================================================================
    logger.info("=" * 60)
    logger.info("STEP 1: Generate SUMMA parameter set")
    logger.info("=" * 60)

    from ewatercycle_summa.parameter_set import create_parameter_set

    with tempfile.TemporaryDirectory() as workdir:
        param_dir = Path(workdir) / "parameter_set"

        t1 = time.time()
        create_parameter_set(
            domain_name="bow_banff",
            shapefile=SHP,
            dem=DEM,
            soil_raster=SOIL,
            landclass_raster=LAND,
            forcing_dir=FORCING,
            start_time="2002-01-01 01:00",
            end_time="2002-01-04 01:00",  # 3 days for quick test
            output_dir=param_dir,
        )
        logger.info("Parameter set generated in %.1fs", time.time() - t1)

        # Verify attributes
        import netCDF4 as nc

        with nc.Dataset(str(param_dir / "settings/SUMMA/attributes.nc")) as ds:
            logger.info(
                "Attributes: soil=%d, veg=%d, elev=%.0fm, lat=%.2f, lon=%.2f",
                ds.variables["soilTypeIndex"][:][0],
                ds.variables["vegTypeIndex"][:][0],
                ds.variables["elevation"][:][0],
                ds.variables["latitude"][:][0],
                ds.variables["longitude"][:][0],
            )

        # =====================================================================
        # Step 2: Create eWaterCycle model from the parameter set
        # =====================================================================
        logger.info("=" * 60)
        logger.info("STEP 2: Create eWaterCycle SUMMA model")
        logger.info("=" * 60)

        from ewatercycle.base.parameter_set import ParameterSet
        from ewatercycle.models import sources

        SUMMA = sources["SUMMA"].load()

        ps = ParameterSet(
            name="bow_banff",
            directory=param_dir,
            config="settings/SUMMA/fileManager.txt",
            target_model="SUMMA",
        )

        model = SUMMA(parameter_set=ps)
        logger.info(
            "Model created: %s -> %s",
            model.start_time_as_datetime,
            model.end_time_as_datetime,
        )

        # =====================================================================
        # Step 3: Setup + Initialize (starts Docker container)
        # =====================================================================
        logger.info("=" * 60)
        logger.info("STEP 3: Setup and initialize")
        logger.info("=" * 60)

        run_dir = Path(workdir) / "run"
        t2 = time.time()
        cfg_file, cfg_dir = model.setup(cfg_dir=str(run_dir))
        logger.info("Setup done in %.1fs", time.time() - t2)

        t3 = time.time()
        model.initialize(cfg_file)
        logger.info("Initialize done in %.1fs", time.time() - t3)
        logger.info("Current time: %s", model.time_as_datetime)

        # =====================================================================
        # Step 4: Run time-stepping loop
        # =====================================================================
        logger.info("=" * 60)
        logger.info("STEP 4: Time-stepping (restart-based)")
        logger.info("=" * 60)

        results = {"time": [], "SWE": [], "runoff": []}
        output_vars = model._bmi.get_output_var_names()
        logger.info("Available outputs: %s", output_vars[:5])

        n_steps = 24  # 24 hours
        for i in range(n_steps):
            t4 = time.time()
            model.update()
            dt = time.time() - t4

            swe = np.zeros(1)
            if "scalarSWE" in output_vars:
                model._bmi.get_value("scalarSWE", swe)

            results["time"].append(str(model.time_as_datetime))
            results["SWE"].append(swe[0])

            if i < 5 or i == n_steps - 1:
                logger.info(
                    "  Step %2d: %s  SWE=%.4f  (%.2fs)",
                    i + 1, model.time_as_datetime, swe[0], dt,
                )
            elif i == 5:
                logger.info("  ...")

        # =====================================================================
        # Step 5: Finalize
        # =====================================================================
        logger.info("=" * 60)
        logger.info("STEP 5: Finalize")
        logger.info("=" * 60)
        model.finalize()

        logger.info("Total time: %.1fs", time.time() - t_total)
        logger.info("")
        logger.info("=" * 60)
        logger.info("FULL E2E PIPELINE: SUCCESS")
        logger.info("=" * 60)
        logger.info("  Parameter set: generated from shapefile + DEM + rasters")
        logger.info("  Model: SUMMA via eWaterCycle plugin")
        logger.info("  Container: Docker (native ARM)")
        logger.info("  Steps: %d hourly timesteps (restart-based)", n_steps)
        logger.info("  SWE range: %.4f - %.4f", min(results["SWE"]), max(results["SWE"]))


if __name__ == "__main__":
    main()
