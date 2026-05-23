"""eWaterCycle wrapper for the SUMMA hydrological model."""

import datetime
import shutil
from collections.abc import ItemsView
from pathlib import Path
from typing import Any

from ewatercycle.base.model import ContainerizedModel, eWaterCycleModel
from ewatercycle.base.parameter_set import ParameterSet
from ewatercycle.container import ContainerImage
from pydantic import PrivateAttr, model_validator

from ewatercycle_summa.forcing.forcing import SUMMAForcing
from ewatercycle_summa.utils import (
    parse_file_manager,
    parse_summa_time,
    write_file_manager,
)


class SUMMAMethods(eWaterCycleModel):
    """The eWaterCycle SUMMA model.

    SUMMA (Structure for Unifying Multiple Modeling Alternatives) is a
    hydrologic modeling framework that enables systematic analysis of
    alternative model conceptualizations.

    The model requires a ParameterSet containing SUMMA configuration files
    (fileManager.txt, modelDecisions.txt, attributes.nc, coldState.nc, etc.).

    Forcing is read from files by SUMMA itself (standard mode, not NGEN-BMI).
    The subprocess BMI wrapper runs the full simulation on the first update()
    call and then steps through the output timesteps.

    Setup args:
        start_time: Override simulation start time (ISO format string).
        end_time: Override simulation end time (ISO format string).
        output_prefix: Prefix for SUMMA output files.
    """

    forcing: SUMMAForcing | None = None
    parameter_set: ParameterSet

    _config: dict[str, str] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _initialize_config(self):
        """Load and parse fileManager.txt from the parameter set."""
        fm_path = self.parameter_set.directory / self.parameter_set.config
        if fm_path.exists():
            self._config = parse_file_manager(fm_path)
        return self

    def _make_cfg_file(self, **kwargs) -> Path:
        """Write SUMMA configuration for container execution.

        Remaps all paths from the parameter set to container mount points
        and writes a new fileManager.txt.
        """
        cfg = dict(self._config)

        settings_src = self.parameter_set.directory / cfg.get(
            "settingsPath", "settings/SUMMA"
        ).rstrip("/")

        if settings_src.is_dir():
            settings_dst = self._cfg_dir / "settings"
            if settings_dst.exists():
                shutil.rmtree(settings_dst)
            shutil.copytree(settings_src, settings_dst)
            cfg["settingsPath"] = str(settings_dst) + "/"

        if self.forcing is not None and self.forcing.directory is not None:
            cfg["forcingPath"] = str(self.forcing.directory) + "/"

        cfg["outputPath"] = str(self._cfg_dir) + "/"

        forcing_path = Path(cfg.get("forcingPath", "").rstrip("/"))
        if not forcing_path.is_absolute():
            forcing_path = (self.parameter_set.directory / forcing_path).resolve()
            cfg["forcingPath"] = str(forcing_path) + "/"
        if forcing_path.is_dir() and str(forcing_path) not in self._additional_input_dirs:
            self._additional_input_dirs.append(str(forcing_path))

        if "start_time" in kwargs:
            cfg["simStartTime"] = kwargs["start_time"]
        elif self.forcing is not None:
            cfg["simStartTime"] = self.forcing.start_time

        if "end_time" in kwargs:
            cfg["simEndTime"] = kwargs["end_time"]
        elif self.forcing is not None:
            cfg["simEndTime"] = self.forcing.end_time

        if "output_prefix" in kwargs:
            cfg["outFilePrefix"] = kwargs["output_prefix"]
        elif "outFilePrefix" not in cfg:
            cfg["outFilePrefix"] = "summa_output"

        self._config = cfg

        config_file = self._cfg_dir / "fileManager.txt"
        write_file_manager(cfg, config_file)

        return config_file

    @property
    def parameters(self) -> ItemsView[str, Any]:
        return self._config.items()


class SUMMA(ContainerizedModel, SUMMAMethods):
    """The SUMMA eWaterCycle model, with containerized execution.

    Uses a subprocess BMI wrapper that runs the standard SUMMA executable
    inside a Docker container and serves results via grpc4bmi.
    """

    bmi_image: ContainerImage = ContainerImage(
        "ghcr.io/darriey/summa-grpc4bmi:v0.1.0"
    )

    @property
    def start_time_as_datetime(self) -> datetime.datetime:
        """Start time parsed from fileManager.txt config."""
        return parse_summa_time(self._config.get("simStartTime", ""))

    @property
    def end_time_as_datetime(self) -> datetime.datetime:
        """End time parsed from fileManager.txt config."""
        return parse_summa_time(self._config.get("simEndTime", ""))

    @property
    def time_as_datetime(self) -> datetime.datetime:
        """Current model time computed from start + elapsed BMI seconds."""
        elapsed = datetime.timedelta(seconds=self._bmi.get_current_time())
        return self.start_time_as_datetime + elapsed
