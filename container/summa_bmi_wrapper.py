"""Restart-based subprocess BMI wrapper for SUMMA.

Each update() call runs SUMMA for one output timestep, using restart files
to chain state between steps. This gives true BMI time-stepping: get_value()
returns the state at the current time, and the model can be advanced
incrementally.

The wrapper manages fileManager.txt rewriting, restart file chaining,
and output collection across steps.
"""

import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple

import netCDF4 as nc
import numpy as np
from bmipy import Bmi

logger = logging.getLogger(__name__)

SUMMA_EXE = os.environ.get("SUMMA_EXE", "summa.exe")


def _parse_fm(path: str) -> dict:
    config = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("!"):
                continue
            m = re.match(r"(\S+)\s+'([^']*)'", line)
            if m:
                config[m.group(1)] = m.group(2)
    return config


def _write_fm(config: dict, path: str) -> None:
    with open(path, "w") as f:
        for k, v in config.items():
            f.write(f"{k:<20} '{v}'\n")


def _parse_time(s: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse time: {s!r}")


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


class SummaBmi(Bmi):
    """Restart-based subprocess BMI for SUMMA.

    Each update() runs SUMMA for one forcing timestep, writes a restart
    file, and reads the output. The restart file becomes the initial
    condition for the next step.
    """

    def __init__(self):
        self._config: dict = {}
        self._config_file: str = ""
        self._work_dir: Path = Path(".")

        self._current_time: datetime = datetime(2000, 1, 1)
        self._start_time: datetime = datetime(2000, 1, 1)
        self._end_time: datetime = datetime(2000, 1, 2)
        self._time_step: timedelta = timedelta(hours=1)
        self._time_step_seconds: float = 3600.0

        self._n_hru: int = 1
        self._step_count: int = 0
        self._initialized: bool = False

        self._current_output: nc.Dataset | None = None
        self._restart_file: str = "coldState.nc"

    def initialize(self, config_file: str) -> None:
        self._config_file = config_file
        self._config = _parse_fm(config_file)
        self._work_dir = Path(config_file).parent

        self._start_time = _parse_time(self._config["simStartTime"])
        self._end_time = _parse_time(self._config["simEndTime"])
        self._current_time = self._start_time

        self._restart_file = self._config.get("initConditionFile", "coldState.nc")

        settings_path = Path(self._config.get("settingsPath", "").rstrip("/"))
        attr_file = settings_path / self._config.get("attributeFile", "attributes.nc")
        if attr_file.exists():
            with nc.Dataset(str(attr_file)) as ds:
                self._n_hru = len(ds.dimensions.get("hru", [1]))

        forcing_path = Path(self._config.get("forcingPath", "").rstrip("/"))
        forcing_list = settings_path / self._config.get("forcingListFile", "forcingFileList.txt")
        self._time_step = self._detect_timestep(forcing_path, forcing_list)
        self._time_step_seconds = self._time_step.total_seconds()

        self._initialized = True
        logger.info(
            "SUMMA initialized: %s -> %s, dt=%s, %d HRU(s)",
            self._start_time, self._end_time, self._time_step, self._n_hru,
        )

    def _detect_timestep(self, forcing_path: Path, forcing_list: Path) -> timedelta:
        """Detect the forcing timestep from the first forcing file."""
        files = []
        if forcing_list.exists():
            with forcing_list.open() as f:
                for line in f:
                    fname = line.strip()
                    if fname and not fname.startswith("!"):
                        fpath = forcing_path / fname
                        if fpath.exists():
                            files.append(fpath)
                            break
        if not files:
            files = sorted(forcing_path.glob("*.nc"))[:1]
        if not files:
            return timedelta(hours=1)

        with nc.Dataset(str(files[0])) as ds:
            if "data_step" in ds.variables:
                return timedelta(seconds=int(ds.variables["data_step"][:]))
            if "time" in ds.variables and len(ds.variables["time"]) > 1:
                import cftime
                tv = ds.variables["time"]
                dates = cftime.num2date(
                    tv[:2], units=tv.units,
                    calendar=getattr(tv, "calendar", "standard"),
                )
                return timedelta(seconds=(dates[1] - dates[0]).total_seconds())
        return timedelta(hours=1)

    def _run_step(self) -> None:
        """Run SUMMA for one timestep using restart chaining."""
        step_start = self._current_time
        step_end = self._current_time + self._time_step

        step_dir = self._work_dir / f"step_{self._step_count:06d}"
        step_dir.mkdir(exist_ok=True)

        step_config = dict(self._config)
        step_config["simStartTime"] = _fmt_time(step_start)
        step_config["simEndTime"] = _fmt_time(step_end)
        step_config["outFilePrefix"] = f"step_{self._step_count:06d}"
        step_config["outputPath"] = str(step_dir) + "/"
        step_config["initConditionFile"] = self._restart_file

        step_fm = str(step_dir / "fileManager.txt")
        _write_fm(step_config, step_fm)

        env = dict(os.environ)
        exe_path = Path(SUMMA_EXE)
        libftz = exe_path.parent / "libftz.so"
        if libftz.exists() and libftz.stat().st_size > 0:
            existing = env.get("LD_PRELOAD", "")
            env["LD_PRELOAD"] = f"{libftz}:{existing}" if existing else str(libftz)

        result = subprocess.run(
            [SUMMA_EXE, "-m", step_fm],
            capture_output=True, text=True, env=env,
        )

        if result.returncode != 0:
            logger.error("SUMMA step %d failed:\n%s", self._step_count, result.stderr[-1000:])
            raise RuntimeError(
                f"SUMMA step {self._step_count} failed (code {result.returncode}): "
                f"{result.stderr[-300:]}"
            )

        if self._current_output is not None:
            self._current_output.close()

        out_files = sorted(step_dir.glob("*.nc"))
        restart_files = [f for f in out_files if "restart" in f.name]
        output_files = [f for f in out_files if "restart" not in f.name]

        if restart_files:
            self._restart_file = str(restart_files[-1])

        if output_files:
            self._current_output = nc.Dataset(str(output_files[0]), "r")
        else:
            self._current_output = None

        self._current_time = step_end
        self._step_count += 1

    def update(self) -> None:
        self._run_step()

    def update_until(self, time: float) -> None:
        target = self._start_time + timedelta(seconds=time)
        while self._current_time < target and self._current_time < self._end_time:
            self._run_step()

    def finalize(self) -> None:
        if self._current_output is not None:
            self._current_output.close()
            self._current_output = None

    # -- Info --

    def get_component_name(self) -> str:
        return "Structure for Unifying Multiple Modeling Alternatives: SUMMA"

    def get_input_item_count(self) -> int:
        return 0

    def get_output_item_count(self) -> int:
        if self._current_output is None:
            return 0
        skip = {"time", "hruId", "gruId", "latitude", "longitude"}
        return sum(1 for v in self._current_output.variables if v not in skip)

    def get_input_var_names(self) -> Tuple[str, ...]:
        return ()

    def get_output_var_names(self) -> Tuple[str, ...]:
        if self._current_output is None:
            return ()
        skip = {"time", "hruId", "gruId", "latitude", "longitude"}
        return tuple(v for v in self._current_output.variables if v not in skip)

    # -- Time --

    def get_current_time(self) -> float:
        return (self._current_time - self._start_time).total_seconds()

    def get_start_time(self) -> float:
        return 0.0

    def get_end_time(self) -> float:
        return (self._end_time - self._start_time).total_seconds()

    def get_time_step(self) -> float:
        return self._time_step_seconds

    def get_time_units(self) -> str:
        return "s"

    # -- Variable info --

    def get_var_type(self, name: str) -> str:
        if self._current_output and name in self._current_output.variables:
            dtype = self._current_output.variables[name].dtype
            if dtype == np.float64:
                return "float64"
            if dtype == np.float32:
                return "float32"
            if dtype in (np.int32, np.int64):
                return "int32"
        return "float64"

    def get_var_units(self, name: str) -> str:
        if self._current_output and name in self._current_output.variables:
            return getattr(self._current_output.variables[name], "units", "-")
        return "-"

    def get_var_itemsize(self, name: str) -> int:
        if self._current_output and name in self._current_output.variables:
            return self._current_output.variables[name].dtype.itemsize
        return 8

    def get_var_nbytes(self, name: str) -> int:
        return self.get_var_itemsize(name) * max(self._n_hru, 1)

    def get_var_location(self, name: str) -> str:
        return "node"

    # -- Grid --

    def get_var_grid(self, name: str) -> int:
        return 0

    def get_grid_rank(self, grid: int) -> int:
        return 1

    def get_grid_size(self, grid: int) -> int:
        return max(self._n_hru, 1)

    def get_grid_type(self, grid: int) -> str:
        return "points"

    def get_grid_shape(self, grid: int, shape: np.ndarray) -> np.ndarray:
        shape[0] = self.get_grid_size(grid)
        return shape

    def get_grid_spacing(self, grid: int, spacing: np.ndarray) -> np.ndarray:
        return spacing

    def get_grid_origin(self, grid: int, origin: np.ndarray) -> np.ndarray:
        return origin

    def get_grid_x(self, grid: int, x: np.ndarray) -> np.ndarray:
        if self._current_output and "longitude" in self._current_output.variables:
            x[:] = self._current_output.variables["longitude"][:]
        return x

    def get_grid_y(self, grid: int, y: np.ndarray) -> np.ndarray:
        if self._current_output and "latitude" in self._current_output.variables:
            y[:] = self._current_output.variables["latitude"][:]
        return y

    def get_grid_z(self, grid: int, z: np.ndarray) -> np.ndarray:
        return z

    def get_grid_node_count(self, grid: int) -> int:
        return self.get_grid_size(grid)

    def get_grid_edge_count(self, grid: int) -> int:
        return 0

    def get_grid_face_count(self, grid: int) -> int:
        return 0

    def get_grid_edge_nodes(self, grid: int, en: np.ndarray) -> np.ndarray:
        return en

    def get_grid_face_edges(self, grid: int, fe: np.ndarray) -> np.ndarray:
        return fe

    def get_grid_face_nodes(self, grid: int, fn: np.ndarray) -> np.ndarray:
        return fn

    def get_grid_nodes_per_face(self, grid: int, npf: np.ndarray) -> np.ndarray:
        return npf

    # -- Get/Set values --

    def get_value(self, name: str, dest: np.ndarray) -> np.ndarray:
        if self._current_output is None or name not in self._current_output.variables:
            return dest
        var = self._current_output.variables[name]
        if "time" in var.dimensions:
            data = var[-1]
        else:
            data = var[:]
        flat = np.atleast_1d(data).flatten()
        dest[: len(flat)] = flat
        return dest

    def get_value_ptr(self, name: str) -> np.ndarray:
        raise NotImplementedError

    def get_value_at_indices(self, name: str, dest: np.ndarray, inds: np.ndarray) -> np.ndarray:
        full = np.zeros(self.get_grid_size(0))
        self.get_value(name, full)
        dest[:] = full[inds]
        return dest

    def set_value(self, name: str, values: np.ndarray) -> None:
        pass

    def set_value_at_indices(self, name: str, inds: np.ndarray, src: np.ndarray) -> None:
        pass
