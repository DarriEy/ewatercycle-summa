"""Create a SUMMA parameter set from minimal inputs using SYMFLUENCE.

Wraps SYMFLUENCE's SUMMA preprocessor to generate all required files
(attributes.nc, coldState.nc, trialParams.nc, fileManager.txt, etc.)
from a catchment shapefile and DEM.

Requires the `symfluence` package to be installed.

Usage:
    from ewatercycle_summa.parameter_set import create_parameter_set

    ps = create_parameter_set(
        domain_name="my_basin",
        shapefile="/path/to/catchment.shp",
        dem="/path/to/dem.tif",
        forcing_dir="/path/to/forcing/SUMMA_input/",
        start_time="2000-01-01 00:00",
        end_time="2001-01-01 00:00",
        output_dir="/path/to/output/",
    )
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def _import_symfluence_class(module_path: str, class_name: str):
    """Import a class from SYMFLUENCE by loading the .py file directly.

    Avoids triggering SYMFLUENCE's full __init__.py import chain which
    pulls in 20+ model packages and heavy dependencies.
    """
    import importlib.util
    import sys

    if module_path in sys.modules:
        return getattr(sys.modules[module_path], class_name)

    spec = importlib.util.find_spec(module_path)
    if spec is None or spec.origin is None:
        raise ImportError(f"Cannot find {module_path}")

    # Ensure parent packages exist as namespace stubs
    parts = module_path.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        if parent not in sys.modules:
            sys.modules[parent] = type(sys)(parent)
            sys.modules[parent].__path__ = []
            parent_spec = importlib.util.find_spec(parent)
            if parent_spec and parent_spec.submodule_search_locations:
                sys.modules[parent].__path__ = list(
                    parent_spec.submodule_search_locations
                )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_path] = module
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def _check_symfluence():
    """Verify SYMFLUENCE source is available without triggering full import chain."""
    import importlib.util
    for mod in ["symfluence.models.summa.attributes_manager",
                "symfluence.models.summa.config_manager"]:
        spec = importlib.util.find_spec(mod)
        if spec is None:
            raise ImportError(
                "symfluence is required for parameter set generation. "
                "Install it with: pip install symfluence"
            )


def create_parameter_set(
    domain_name: str,
    shapefile: str | Path,
    dem: str | Path,
    forcing_dir: str | Path,
    start_time: str,
    end_time: str,
    output_dir: str | Path,
    soil_raster: str | Path | None = None,
    landclass_raster: str | Path | None = None,
    hru_id_col: str = "HRU_ID",
    gru_id_col: str = "GRU_ID",
    data_step: int = 3600,
    measurement_height: float = 3.0,
    soil_profile: str = "FA",
    decisions: dict[str, str] | None = None,
) -> Path:
    """Create a complete SUMMA parameter set using SYMFLUENCE.

    Args:
        domain_name: Name for this domain/experiment.
        shapefile: Path to catchment shapefile (GeoPackage or .shp) with
            HRU/GRU ID columns, area, and lat/lon.
        dem: Path to DEM raster (GeoTIFF).
        forcing_dir: Directory containing SUMMA-format forcing NetCDFs.
        start_time: Simulation start time (YYYY-MM-DD HH:MM).
        end_time: Simulation end time (YYYY-MM-DD HH:MM).
        output_dir: Where to write the parameter set.
        soil_raster: Path to soil class raster (USDA classes, 1-12).
            If not provided, defaults to loam everywhere.
        landclass_raster: Path to land cover raster (IGBP classes, 1-17).
            If not provided, defaults to evergreen needleleaf.
        hru_id_col: Column name for HRU IDs in shapefile.
        gru_id_col: Column name for GRU IDs in shapefile.
        data_step: Forcing timestep in seconds (default 3600).
        measurement_height: Forcing measurement height in meters.
        soil_profile: Soil profile type ('FA' or 'CWARHM').
        decisions: Optional dict of SUMMA decision overrides.

    Returns:
        Path to the output directory containing the parameter set.

    The output directory will contain:
        settings/SUMMA/
            fileManager.txt, modelDecisions.txt, outputControl.txt,
            coldState.nc, attributes.nc, trialParams.nc,
            TBL_*.TBL, *ParamInfo.txt, forcingFileList.txt
        forcing/SUMMA_input/
            (symlinked or copied from forcing_dir)
    """
    _check_symfluence()

    output = Path(output_dir)
    shapefile = Path(shapefile)
    dem = Path(dem)
    forcing_dir = Path(forcing_dir)

    settings_dir = output / "settings" / "SUMMA"
    forcing_out = output / "forcing" / "SUMMA_input"
    settings_dir.mkdir(parents=True, exist_ok=True)
    forcing_out.mkdir(parents=True, exist_ok=True)

    _copy_base_settings(settings_dir)
    _create_forcing_file_list(forcing_dir, settings_dir)

    if decisions:
        _apply_decisions(settings_dir / "modelDecisions.txt", decisions)

    _create_attributes(
        shapefile, dem, forcing_dir, settings_dir,
        hru_id_col, gru_id_col, measurement_height,
        soil_raster=Path(soil_raster) if soil_raster else None,
        landclass_raster=Path(landclass_raster) if landclass_raster else None,
    )

    _create_cold_state(
        forcing_dir, settings_dir, hru_id_col, soil_profile,
    )

    _create_trial_params(forcing_dir, settings_dir, hru_id_col)

    _create_file_manager(
        settings_dir, forcing_dir, output,
        domain_name, start_time, end_time,
    )

    logger.info("Parameter set created at %s", output)
    return output


def _copy_base_settings(settings_dir: Path):
    """Copy SUMMA template files (decisions, tables, param info)."""
    resources = Path(__file__).parent / "resources"
    for f in resources.iterdir():
        if f.is_file():
            shutil.copy2(f, settings_dir / f.name)
    logger.info("Copied %d base settings files", len(list(resources.iterdir())))


def _create_forcing_link(forcing_src: Path, forcing_dst: Path):
    """Symlink forcing files into the parameter set."""
    for f in forcing_src.glob("*.nc"):
        link = forcing_dst / f.name
        if not link.exists():
            link.symlink_to(f.resolve())


def _create_forcing_file_list(forcing_dir: Path, settings_dir: Path):
    """Write forcingFileList.txt from the forcing directory."""
    files = sorted(f.name for f in forcing_dir.glob("*.nc"))
    (settings_dir / "forcingFileList.txt").write_text("\n".join(files) + "\n")
    logger.info("Forcing file list: %d files", len(files))


def _apply_decisions(decisions_file: Path, overrides: dict[str, str]):
    """Apply decision overrides to modelDecisions.txt."""
    import re
    content = decisions_file.read_text()
    for key, value in overrides.items():
        content = re.sub(
            rf"({key}\s+)\S+",
            rf"\g<1>{value}",
            content,
        )
    decisions_file.write_text(content)


def _create_attributes(
    shapefile: Path,
    dem: Path,
    forcing_dir: Path,
    settings_dir: Path,
    hru_id_col: str,
    gru_id_col: str,
    measurement_height: float,
    soil_raster: Path | None = None,
    landclass_raster: Path | None = None,
):
    """Create attributes.nc from shapefile and DEM."""
    project_dir = settings_dir.parent.parent

    _ensure_intersections(
        shapefile, dem, project_dir, hru_id_col,
        soil_raster=soil_raster,
        landclass_raster=landclass_raster,
    )

    SummaAttributesManager = _import_symfluence_class(
        "symfluence.models.summa.attributes_manager", "SummaAttributesManager"
    )
    manager = SummaAttributesManager(
        config={},
        logger=logger,
        catchment_path=shapefile.parent,
        catchment_name=shapefile.name,
        dem_path=dem,
        forcing_summa_path=forcing_dir,
        setup_dir=settings_dir,
        project_dir=project_dir,
        hruId=hru_id_col,
        gruId=gru_id_col,
        attribute_name="attributes.nc",
        forcing_measurement_height=measurement_height,
        get_default_path_callback=lambda k, d: project_dir / d,
    )
    manager.create_attributes_file()
    logger.info("Created attributes.nc")


def _ensure_intersections(
    shapefile: Path,
    dem: Path,
    project_dir: Path,
    hru_id_col: str,
    soil_raster: Path | None = None,
    landclass_raster: Path | None = None,
):
    """Create intersection shapefiles from raster data.

    The SYMFLUENCE attributes manager expects pre-computed intersection
    shapefiles with specific column formats:
      - with_dem/: elev_mean column
      - with_soilgrids/: USGS_0..USGS_12 columns (area fractions)
      - with_landclass/: IGBP_1..IGBP_17 columns (area fractions)
    """
    import geopandas as gpd
    from rasterstats import zonal_stats

    gdf = gpd.read_file(shapefile)
    intersect_base = project_dir / "shapefiles" / "catchment_intersection"

    # -- Elevation --
    dem_dir = intersect_base / "with_dem"
    dem_file = dem_dir / "catchment_with_dem.shp"
    if not dem_file.exists():
        dem_dir.mkdir(parents=True, exist_ok=True)
        dem_gdf = gdf.copy()
        if "elev_mean" not in dem_gdf.columns:
            if dem.exists() and dem.stat().st_size > 0:
                stats = zonal_stats(dem_gdf, str(dem), stats=["mean"])
                dem_gdf["elev_mean"] = [s["mean"] or 0 for s in stats]
            else:
                dem_gdf["elev_mean"] = 1000.0
        dem_gdf.to_file(dem_file)
        logger.info("Created DEM intersection from shapefile")

    # -- Soil class --
    soil_dir = intersect_base / "with_soilgrids"
    soil_file = soil_dir / "catchment_with_soilclass.shp"
    if not soil_file.exists() and soil_raster is not None and soil_raster.exists():
        soil_dir.mkdir(parents=True, exist_ok=True)
        soil_gdf = gdf.copy()
        stats = zonal_stats(soil_gdf, str(soil_raster), categorical=True)
        for i in range(13):
            col = f"USGS_{i}"
            soil_gdf[col] = 0.0
        for idx, row_stats in enumerate(stats):
            total = sum(v for k, v in row_stats.items() if k is not None)
            if total > 0:
                for class_id, count in row_stats.items():
                    if class_id is not None and 0 <= int(class_id) <= 12:
                        soil_gdf.loc[idx, f"USGS_{int(class_id)}"] = count / total
        soil_gdf.to_file(soil_file)
        logger.info("Created soil class intersection from raster")

    # -- Land cover --
    land_dir = intersect_base / "with_landclass"
    land_file = land_dir / "catchment_with_landclass.shp"
    if not land_file.exists() and landclass_raster is not None and landclass_raster.exists():  # noqa: E501
        land_dir.mkdir(parents=True, exist_ok=True)
        land_gdf = gdf.copy()
        stats = zonal_stats(land_gdf, str(landclass_raster), categorical=True)
        for i in range(1, 18):
            col = f"IGBP_{i}"
            land_gdf[col] = 0.0
        for idx, row_stats in enumerate(stats):
            total = sum(v for k, v in row_stats.items() if k is not None)
            if total > 0:
                for class_id, count in row_stats.items():
                    if class_id is not None and 1 <= int(class_id) <= 17:
                        land_gdf.loc[idx, f"IGBP_{int(class_id)}"] = count / total
        land_gdf.to_file(land_file)
        logger.info("Created land cover intersection from raster")


def _create_cold_state(
    forcing_dir: Path,
    settings_dir: Path,
    hru_id_col: str,
    soil_profile: str,
):
    """Create coldState.nc (initial conditions)."""
    SummaConfigManager = _import_symfluence_class(
        "symfluence.models.summa.config_manager", "SummaConfigManager"
    )
    manager = SummaConfigManager(
        config={"SETTINGS_SUMMA_SOILPROFILE": soil_profile},
        logger=logger,
        project_dir=settings_dir.parent.parent,
        setup_dir=settings_dir,
        forcing_summa_path=forcing_dir,
        catchment_path=Path("."),
        catchment_name="",
        dem_path=Path("."),
        hruId=hru_id_col,
        gruId="gruId",
        data_step=3600,
        coldstate_name="coldState.nc",
        parameter_name="trialParams.nc",
        attribute_name="attributes.nc",
        forcing_measurement_height=3.0,
    )
    manager.create_initial_conditions()
    logger.info("Created coldState.nc")


def _create_trial_params(
    forcing_dir: Path,
    settings_dir: Path,
    hru_id_col: str,
):
    """Create trialParams.nc."""
    SummaConfigManager = _import_symfluence_class(
        "symfluence.models.summa.config_manager", "SummaConfigManager"
    )
    manager = SummaConfigManager(
        config={},
        logger=logger,
        project_dir=settings_dir.parent.parent,
        setup_dir=settings_dir,
        forcing_summa_path=forcing_dir,
        catchment_path=Path("."),
        catchment_name="",
        dem_path=Path("."),
        hruId=hru_id_col,
        gruId="gruId",
        data_step=3600,
        coldstate_name="coldState.nc",
        parameter_name="trialParams.nc",
        attribute_name="attributes.nc",
        forcing_measurement_height=3.0,
    )
    manager.create_trial_parameters()
    logger.info("Created trialParams.nc")


def _create_file_manager(
    settings_dir: Path,
    forcing_dir: Path,
    output_dir: Path,
    experiment_id: str,
    start_time: str,
    end_time: str,
):
    """Write fileManager.txt with relative paths."""
    from ewatercycle_summa.utils import write_file_manager

    config = {
        "controlVersion": "SUMMA_FILE_MANAGER_V3.0.0",
        "simStartTime": start_time,
        "simEndTime": end_time,
        "tmZoneInfo": "utcTime",
        "outFilePrefix": experiment_id,
        "settingsPath": str(settings_dir) + "/",
        "forcingPath": str(forcing_dir.resolve()) + "/",
        "outputPath": str(output_dir / "output") + "/",
        "decisionsFile": "modelDecisions.txt",
        "outputControlFile": "outputControl.txt",
        "globalHruParamFile": "localParamInfo.txt",
        "globalGruParamFile": "basinParamInfo.txt",
        "initConditionFile": "coldState.nc",
        "attributeFile": "attributes.nc",
        "trialParamFile": "trialParams.nc",
        "forcingListFile": "forcingFileList.txt",
        "vegTableFile": "TBL_VEGPARM.TBL",
        "soilTableFile": "TBL_SOILPARM.TBL",
        "generalTableFile": "TBL_GENPARM.TBL",
        "noahmpTableFile": "TBL_MPTABLE.TBL",
    }

    write_file_manager(config, settings_dir / "fileManager.txt")
    logger.info("Created fileManager.txt")


def acquire_attributes(
    shapefile: str | Path,
    dem: str | Path,
    output_dir: str | Path,
    datasets: list[str] | None = None,
) -> Path:
    """Download and process catchment attributes using SYMFLUENCE.

    Acquires soil type, land cover, and elevation attributes for the
    catchment defined by the shapefile, using global datasets.

    Args:
        shapefile: Path to catchment shapefile.
        dem: Path to DEM raster.
        output_dir: Where to write intersection shapefiles.
        datasets: Which attribute datasets to process. Defaults to
            ['elevation', 'soilclass', 'landclass'].

    Returns:
        Path to directory containing intersection shapefiles.
    """
    _check_symfluence()


    shapefile = Path(shapefile)
    dem = Path(dem)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if datasets is None:
        datasets = ["elevation", "soilclass", "landclass"]

    import geopandas as gpd
    gdf = gpd.read_file(shapefile)

    if "elevation" in datasets:
        logger.info("Processing elevation from DEM...")
        elev_dir = output_dir / "with_dem"
        elev_dir.mkdir(exist_ok=True)
        from rasterstats import zonal_stats
        stats = zonal_stats(gdf, str(dem), stats=["mean"])
        gdf["elev_mean"] = [s["mean"] for s in stats]
        gdf.to_file(elev_dir / f"{shapefile.stem}_with_dem.shp")

    if "soilclass" in datasets:
        logger.info("Processing soil classification...")
        try:
            from symfluence.data.preprocessing.attribute_processors import SoilProcessor
            processor = SoilProcessor(
                config={"SYMFLUENCE_DATA_DIR": str(output_dir.parent)},
                logger=logger,
            )
            processor.process(gdf, output_dir / "with_soilclass")
        except ImportError:
            logger.warning("SoilProcessor not available, skipping soil attributes")

    if "landclass" in datasets:
        logger.info("Processing land cover classification...")
        try:
            from symfluence.data.preprocessing.attribute_processors import (
                LandCoverProcessor,
            )
            processor = LandCoverProcessor(
                config={"SYMFLUENCE_DATA_DIR": str(output_dir.parent)},
                logger=logger,
            )
            processor.process(gdf, output_dir / "with_landclass")
        except ImportError:
            logger.warning("LandCoverProcessor not available, skipping land attributes")

    logger.info("Attribute acquisition complete: %s", output_dir)
    return output_dir
