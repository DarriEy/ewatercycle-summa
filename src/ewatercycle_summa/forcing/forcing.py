"""Forcing data handling for SUMMA."""

from datetime import datetime
from pathlib import Path

from ewatercycle.base.forcing import DefaultForcing
from ewatercycle.esmvaltool.builder import RecipeBuilder
from ewatercycle.esmvaltool.schema import Dataset


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
            dataset: Dataset to get forcing data from.
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
        return (
            RecipeBuilder()
            .title("Generate forcing for the SUMMA hydrological model")
            .dataset(dataset)
            .start(start_time.year)
            .end(end_time.year)
            .shape(shape)
            .add_variables(["tas", "pr", "rsds", "rlds", "huss", "sfcWind", "ps"])
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
