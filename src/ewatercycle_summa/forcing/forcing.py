"""Forcing data handling for SUMMA."""

from datetime import datetime
from pathlib import Path

from ewatercycle.base.forcing import DefaultForcing
from ewatercycle.esmvaltool.builder import RecipeBuilder
from ewatercycle.esmvaltool.schema import Dataset

# CMIP6 MIP table overrides for variables not in the standard "day" table.
# ps (surface pressure) has a broken CMOR entry in "day" and must use "CFday".
CMIP6_MIP_OVERRIDES: dict[str, str] = {"ps": "CFday"}

SUMMA_FORCING_VARIABLES = ["tas", "pr", "rsds", "rlds", "huss", "sfcWind", "ps"]


def cmip6_dataset(
    model: str,
    exp: str = "historical",
    ensemble: str = "r1i1p1f1",
    grid: str = "gn",
) -> Dataset:
    """Create an ESMValTool Dataset for a CMIP6 model.

    Args:
        model: CMIP6 model name (e.g. "MRI-ESM2-0", "EC-Earth3", "IPSL-CM6A-LR").
        exp: CMIP6 experiment ID. "historical" for 1850-2014, or an SSP
            scenario like "ssp126", "ssp245", "ssp370", "ssp585".
        ensemble: Ensemble member (default "r1i1p1f1").
        grid: Grid label (default "gn" for native grid).
    """
    return Dataset(
        dataset=model,
        project="CMIP6",
        exp=exp,
        ensemble=ensemble,
        grid=grid,
    )


class SUMMAForcing(DefaultForcing):
    """Container for SUMMA forcing data.

    Args:
        directory: Directory where forcing data files are stored.
        start_time: Start time of forcing in UTC and ISO format string e.g.
            'YYYY-MM-DDTHH:MM:SSZ'.
        end_time: End time of forcing in UTC and ISO format string e.g.
            'YYYY-MM-DDTHH:MM:SSZ'.
        shape: Path to a shape file. Used for spatial selection.
        forcing_file: Name of the forcing NetCDF file within directory.
    """

    forcing_file: str = "summa_forcing.nc"

    @classmethod
    def generate(
        cls,
        dataset: str | Dataset | dict,
        start_time: str,
        end_time: str,
        shape: str,
        directory: str | None = None,
    ) -> "SUMMAForcing":
        """Generate forcing data for SUMMA.

        Uses ESMValTool to download and process meteorological forcing, then
        converts to SUMMA's required format (variable names, units, dimensions).

        Args:
            dataset: Dataset to get forcing data from. Can be:
                - A string like "ERA5" for predefined datasets
                - A Dataset object (use cmip6_dataset() for CMIP6)
                - A dict passed to the Dataset constructor
            start_time: Start time of forcing in UTC and ISO format string.
            end_time: End time of forcing in UTC and ISO format string.
            shape: Path to a shape file. Used for spatial selection.
            directory: Directory in which forcing should be written.
        """
        return super().generate(
            dataset=dataset,
            start_time=start_time,
            end_time=end_time,
            shape=shape,
            directory=directory,
        )

    @classmethod
    def _build_recipe(
        cls,
        start_time: datetime,
        end_time: datetime,
        shape: Path,
        dataset: Dataset | str | dict,
        **model_specific_options,
    ):
        is_cmip6 = isinstance(dataset, Dataset) and dataset.project == "CMIP6"

        builder = (
            RecipeBuilder()
            .title("Generate forcing for the SUMMA hydrological model")
            .dataset(dataset)
            .start(start_time.year)
            .end(end_time.year)
            .shape(shape)
        )

        for var in SUMMA_FORCING_VARIABLES:
            mip = CMIP6_MIP_OVERRIDES.get(var) if is_cmip6 else None
            builder.add_variable(var, mip=mip)

        return (
            builder
            .script(
                str(Path(__file__).parent / "diagnostic_script.py"),
                {"basin": shape.stem},
            )
            .build()
        )

    @classmethod
    def _recipe_output_to_forcing_arguments(cls, recipe_output, model_specific_options):
        first_file = next(iter(recipe_output.values()))
        return {
            "forcing_file": first_file,
        }
