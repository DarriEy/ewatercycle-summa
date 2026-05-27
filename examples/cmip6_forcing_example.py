"""Generate SUMMA forcing from CMIP6 daily data via ESMValTool.

This script demonstrates generating SUMMA-format forcing from a CMIP6 model
using the eWaterCycle/ESMValTool pipeline. It downloads and preprocesses daily
meteorological variables, then converts them to SUMMA's required NetCDF format.

Requirements:
  - ewatercycle + ewatercycle-summa installed
  - ESMValTool configured with access to CMIP6 data (ESGF or local)
  - A catchment shapefile for spatial extraction

The seven required forcing variables (CMOR -> SUMMA):
  tas     -> airtemp    (K)
  pr      -> pptrate    (kg m-2 s-1)
  rsds    -> SWRadAtm   (W m-2)
  rlds    -> LWRadAtm   (W m-2)
  huss    -> spechum    (kg kg-1)
  sfcWind -> windspd    (m s-1)
  ps      -> airpres    (Pa)

Usage:
  python cmip6_forcing_example.py --shape /path/to/catchment.shp

ESMValTool configuration:
  ESMValTool needs to know where to find CMIP6 data. Configure this in
  ~/.esmvaltool/config-user.yml. For ESGF downloads, ensure:

    search_esgf: when_missing

  For local CMIP6 archives, set the rootpath:

    rootpath:
      CMIP6: /path/to/cmip6/archive

  See https://docs.esmvaltool.org/en/latest/quickstart/configuration.html
"""

import argparse
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cmip6_forcing")


def main():
    parser = argparse.ArgumentParser(
        description="Generate SUMMA forcing from CMIP6 daily data"
    )
    parser.add_argument(
        "--shape",
        type=Path,
        required=True,
        help="Path to catchment shapefile",
    )
    parser.add_argument(
        "--model",
        default="MRI-ESM2-0",
        help="CMIP6 model name (default: MRI-ESM2-0)",
    )
    parser.add_argument(
        "--exp",
        default="historical",
        help="CMIP6 experiment (default: historical)",
    )
    parser.add_argument(
        "--ensemble",
        default="r1i1p1f1",
        help="Ensemble member (default: r1i1p1f1)",
    )
    parser.add_argument(
        "--start",
        default="2000-01-01T00:00:00Z",
        help="Start time (ISO format, default: 2000-01-01T00:00:00Z)",
    )
    parser.add_argument(
        "--end",
        default="2000-12-31T23:59:59Z",
        help="End time (ISO format, default: 2000-12-31T23:59:59Z)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: temp directory)",
    )
    args = parser.parse_args()

    from ewatercycle_summa.forcing import SUMMAForcing, cmip6_dataset

    # =========================================================================
    # Step 1: Create CMIP6 dataset specification
    # =========================================================================
    logger.info("CMIP6 model: %s (%s, %s)", args.model, args.exp, args.ensemble)

    dataset = cmip6_dataset(
        model=args.model,
        exp=args.exp,
        ensemble=args.ensemble,
    )

    # =========================================================================
    # Step 2: Generate forcing via ESMValTool
    # =========================================================================
    logger.info("Generating forcing: %s to %s", args.start, args.end)
    logger.info("Shapefile: %s", args.shape)

    forcing = SUMMAForcing.generate(
        dataset=dataset,
        start_time=args.start,
        end_time=args.end,
        shape=str(args.shape),
        directory=str(args.output) if args.output else None,
    )

    logger.info("Forcing generated successfully:")
    logger.info("  Directory: %s", forcing.directory)
    logger.info("  File: %s", forcing.forcing_file)
    logger.info("  Period: %s to %s", forcing.start_time, forcing.end_time)

    # =========================================================================
    # Step 3: Inspect the output
    # =========================================================================
    forcing_path = Path(forcing.directory) / forcing.forcing_file
    if forcing_path.exists():
        import netCDF4 as nc

        with nc.Dataset(str(forcing_path)) as ds:
            logger.info("Output NetCDF contents:")
            logger.info("  Dimensions: %s", dict(ds.dimensions))
            for var_name, var in ds.variables.items():
                if var.ndim > 0:
                    logger.info(
                        "  %s: shape=%s, units=%s",
                        var_name,
                        var.shape,
                        getattr(var, "units", "?"),
                    )

    # =========================================================================
    # Step 4 (optional): Use forcing with SUMMA model
    # =========================================================================
    # To run SUMMA with this forcing, combine it with a parameter set:
    #
    #   from ewatercycle.base.parameter_set import ParameterSet
    #   from ewatercycle.models import sources
    #
    #   SUMMA = sources["SUMMA"].load()
    #   ps = ParameterSet(
    #       name="my_domain",
    #       directory=param_dir,
    #       config="settings/SUMMA/fileManager.txt",
    #       target_model="SUMMA",
    #   )
    #   model = SUMMA(parameter_set=ps, forcing=forcing)
    #   cfg_file, cfg_dir = model.setup()
    #   model.initialize(cfg_file)

    return forcing


if __name__ == "__main__":
    main()
