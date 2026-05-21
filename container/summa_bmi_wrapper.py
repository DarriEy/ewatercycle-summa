"""Subprocess-based BMI wrapper for SUMMA.

Runs the standard SUMMA executable as a subprocess and exposes results
through the BMI interface. The full simulation is run on the first
update() call; subsequent update() calls advance through the output
timesteps.

This avoids all Fortran ABI issues with the NGEN-BMI and works with
any standard SUMMA domain configuration.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Tuple

import netCDF4 as nc
import numpy as np
from bmipy import Bmi

logger = logging.getLogger(__name__)

SUMMA_EXE = os.environ.get("SUMMA_EXE", "summa_sundials.exe")


class SummaBmi(Bmi):
    """Subprocess BMI wrapper for SUMMA."""

    def __init__(self):
        self._config_file: str | None = None
        self._output_ds: nc.Dataset | None = None
        self._time_index: int = 0
        self._n_times: int = 0
        self._n_hru: int = 0
        self._start_time: float = 0.0
        self._end_time: float = 0.0
        self._time_step: float = 3600.0
        self._times: np.ndarray | None = None
        self._has_run: bool = False
        self._output_path: Path | None = None
        self._output_prefix: str = ""

    def initialize(self, config_file: str) -> None:
        self._config_file = config_file
        self._parse_file_manager(config_file)

    def _parse_file_manager(self, path: str) -> None:
        """Parse fileManager.txt to extract paths and simulation times."""
        import re
        config = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("!"):
                    continue
                m = re.match(r"(\S+)\s+'([^']*)'", line)
                if m:
                    config[m.group(1)] = m.group(2)

        self._output_path = Path(config.get("outputPath", ".").rstrip("/"))
        self._output_prefix = config.get("outFilePrefix", "summa_output")

        start_str = config.get("simStartTime", "")
        end_str = config.get("simEndTime", "")
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                from datetime import datetime
                self._start_dt = datetime.strptime(start_str, fmt)
                self._end_dt = datetime.strptime(end_str, fmt)
                break
            except ValueError:
                continue

        settings_path = Path(config.get("settingsPath", "").rstrip("/"))
        attr_file = settings_path / config.get("attributeFile", "attributes.nc")
        if attr_file.exists():
            with nc.Dataset(str(attr_file)) as ds:
                self._n_hru = len(ds.dimensions.get("hru", []))

        self._start_time = 0.0
        dt = self._end_dt - self._start_dt
        self._end_time = dt.total_seconds()

    def _run_summa(self) -> None:
        """Execute SUMMA as a subprocess."""
        if self._has_run:
            return

        logger.info("Running SUMMA: %s -m %s", SUMMA_EXE, self._config_file)

        env = dict(os.environ)
        libftz = Path(SUMMA_EXE).parent / "libftz.so"
        if libftz.exists():
            existing = env.get("LD_PRELOAD", "")
            env["LD_PRELOAD"] = f"{libftz}:{existing}" if existing else str(libftz)

        result = subprocess.run(
            [SUMMA_EXE, "-m", self._config_file],
            capture_output=True,
            text=True,
            env=env,
        )

        if result.returncode != 0:
            logger.error("SUMMA failed:\n%s\n%s", result.stdout, result.stderr)
            raise RuntimeError(
                f"SUMMA exited with code {result.returncode}: {result.stderr[-500:]}"
            )

        logger.info("SUMMA completed successfully")
        self._has_run = True
        self._open_output()

    def _open_output(self) -> None:
        """Open the SUMMA output NetCDF file."""
        pattern = f"{self._output_prefix}_output_*_timestep.nc"
        candidates = sorted(self._output_path.glob(pattern))
        if not candidates:
            pattern2 = f"{self._output_prefix}*.nc"
            candidates = sorted(self._output_path.glob(pattern2))
        if not candidates:
            all_nc = sorted(self._output_path.glob("*.nc"))
            raise FileNotFoundError(
                f"No SUMMA output found in {self._output_path}. "
                f"Files: {[f.name for f in all_nc]}"
            )

        self._output_ds = nc.Dataset(str(candidates[0]), "r")
        self._times = self._output_ds.variables["time"][:]
        self._n_times = len(self._times)
        self._n_hru = len(self._output_ds.dimensions.get("hru", [1]))

        if self._n_times > 1:
            time_var = self._output_ds.variables["time"]
            import cftime
            dates = cftime.num2date(
                self._times[:2],
                units=time_var.units,
                calendar=getattr(time_var, "calendar", "standard"),
            )
            dt = (dates[1] - dates[0]).total_seconds()
            self._time_step = dt

        self._end_time = self._n_times * self._time_step
        logger.info(
            "Output: %d timesteps, %d HRUs, dt=%.0fs",
            self._n_times, self._n_hru, self._time_step,
        )

    def update(self) -> None:
        self._run_summa()
        if self._time_index < self._n_times:
            self._time_index += 1

    def update_until(self, time: float) -> None:
        self._run_summa()
        while self.get_current_time() < time and self._time_index < self._n_times:
            self._time_index += 1

    def finalize(self) -> None:
        if self._output_ds is not None:
            self._output_ds.close()
            self._output_ds = None

    # -- Info --

    def get_component_name(self) -> str:
        return "Structure for Unifying Multiple Modeling Alternatives: SUMMA"

    def get_input_item_count(self) -> int:
        return 0

    def get_output_item_count(self) -> int:
        if self._output_ds is None:
            return 0
        skip = {"time", "hruId", "gruId", "latitude", "longitude"}
        return sum(1 for v in self._output_ds.variables if v not in skip)

    def get_input_var_names(self) -> Tuple[str, ...]:
        return ()

    def get_output_var_names(self) -> Tuple[str, ...]:
        if self._output_ds is None:
            return ()
        skip = {"time", "hruId", "gruId", "latitude", "longitude"}
        return tuple(v for v in self._output_ds.variables if v not in skip)

    # -- Time --

    def get_current_time(self) -> float:
        return self._time_index * self._time_step

    def get_start_time(self) -> float:
        return self._start_time

    def get_end_time(self) -> float:
        return self._end_time

    def get_time_step(self) -> float:
        return self._time_step

    def get_time_units(self) -> str:
        return "s"

    # -- Variable info --

    def get_var_type(self, name: str) -> str:
        if self._output_ds and name in self._output_ds.variables:
            dtype = self._output_ds.variables[name].dtype
            if dtype == np.float64:
                return "float64"
            if dtype == np.float32:
                return "float32"
            if dtype in (np.int32, np.int64):
                return "int32"
        return "float64"

    def get_var_units(self, name: str) -> str:
        if self._output_ds and name in self._output_ds.variables:
            return getattr(self._output_ds.variables[name], "units", "-")
        return "-"

    def get_var_itemsize(self, name: str) -> int:
        if self._output_ds and name in self._output_ds.variables:
            return self._output_ds.variables[name].dtype.itemsize
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
        if self._output_ds and "longitude" in self._output_ds.variables:
            x[:] = self._output_ds.variables["longitude"][:]
        return x

    def get_grid_y(self, grid: int, y: np.ndarray) -> np.ndarray:
        if self._output_ds and "latitude" in self._output_ds.variables:
            y[:] = self._output_ds.variables["latitude"][:]
        return y

    def get_grid_z(self, grid: int, z: np.ndarray) -> np.ndarray:
        return z

    def get_grid_node_count(self, grid: int) -> int:
        return self.get_grid_size(grid)

    def get_grid_edge_count(self, grid: int) -> int:
        return 0

    def get_grid_face_count(self, grid: int) -> int:
        return 0

    def get_grid_edge_nodes(self, grid: int, edge_nodes: np.ndarray) -> np.ndarray:
        return edge_nodes

    def get_grid_face_edges(self, grid: int, face_edges: np.ndarray) -> np.ndarray:
        return face_edges

    def get_grid_face_nodes(self, grid: int, face_nodes: np.ndarray) -> np.ndarray:
        return face_nodes

    def get_grid_nodes_per_face(self, grid: int, nodes_per_face: np.ndarray) -> np.ndarray:
        return nodes_per_face

    # -- Get/Set values --

    def get_value(self, name: str, dest: np.ndarray) -> np.ndarray:
        self._run_summa()
        if self._output_ds is None or name not in self._output_ds.variables:
            return dest
        var = self._output_ds.variables[name]
        idx = max(0, self._time_index - 1)
        if "time" in var.dimensions:
            data = var[idx]
        else:
            data = var[:]
        dest[: len(np.atleast_1d(data))] = np.atleast_1d(data).flatten()
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
