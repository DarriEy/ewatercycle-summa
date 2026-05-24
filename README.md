# ewatercycle-summa

SUMMA (Structure for Unifying Multiple Modeling Alternatives) plugin for [eWaterCycle](https://ewatercycle.readthedocs.io/).

Runs the standard SUMMA executable from [CH-Earth/summa](https://github.com/CH-Earth/summa/tree/develop_sundials)
inside a Docker container via a subprocess BMI wrapper served by
[grpc4bmi](https://github.com/eWaterCycle/grpc4bmi). Works with any existing
SUMMA domain setup (e.g. from [SYMFLUENCE](https://github.com/DarriEy/SYMFLUENCE)).

## Installation

`ewatercycle` depends on ESMValTool, which is only installable via conda. Set up a
conda env from eWaterCycle's lock file, then pip-install this plugin on top:

```bash
curl -o conda-lock.yml https://raw.githubusercontent.com/eWaterCycle/ewatercycle/main/conda-lock.yml
conda-lock install --no-dev -n ewatercycle
conda activate ewatercycle
pip install ewatercycle-summa
```

A plain `pip install ewatercycle-summa` into a non-conda venv will pull in
`ewatercycle` from PyPI but fail at first import: `ewatercycle.base.forcing`
loads ESMValTool diagnostic scripts at module load time.

Docker must be running — the SUMMA container is pulled automatically on first use.

## Quickstart

The repository ships a bundled example domain at `examples/data/bow_at_banff_lumped/`
(~870 KB: lumped Bow River at Banff catchment with ERA5 forcing for May–June 2004).
After installation, the notebook `examples/summa_ewatercycle_demo.ipynb` runs
end-to-end against this domain with no extra setup.

## Usage

```python
from ewatercycle.base.parameter_set import ParameterSet
from ewatercycle.models import sources

# Discover the SUMMA model class from eWaterCycle's registry
SUMMA = sources["SUMMA"]

# Point to a SUMMA parameter set (settings, attributes, cold state, etc.)
parameter_set = ParameterSet(
    name="summa_test",
    directory="/path/to/parameter_set",
    config="settings/SUMMA/fileManager.txt",
    target_model="SUMMA",
)

# Forcing paths inside fileManager.txt may be either absolute, or relative to
# the parameter-set directory. A separate SUMMAForcing object is optional.
model = SUMMA(parameter_set=parameter_set)
cfg_file, cfg_dir = model.setup(
    start_time="2004-06-01 01:00",
    end_time="2004-06-08 01:00",
)
model.initialize(cfg_file)

while model.time < model.end_time:
    model.update()

model.finalize()
```

## Parameter Set Structure

A SUMMA parameter set for eWaterCycle should contain:

```
parameter_set_dir/
  settings/SUMMA/
    fileManager.txt        # SUMMA file manager (paths are remapped at runtime)
    modelDecisions.txt     # Process-model decisions
    outputControl.txt      # Output variable selection
    basinParamInfo.txt     # GRU-level parameter metadata
    localParamInfo.txt     # HRU-level parameter metadata
    TBL_GENPARM.TBL        # General parameter lookup table
    TBL_MPTABLE.TBL        # Noah-MP parameter table
    TBL_SOILPARM.TBL       # Soil parameter table
    TBL_VEGPARM.TBL        # Vegetation parameter table
    coldState.nc           # Initial conditions
    attributes.nc          # Spatial attributes (HRU/GRU)
    trialParams.nc         # Calibration parameters
  forcing/SUMMA_input/     # (optional) default forcing if not provided separately
    *.nc
```

Default template files for the settings are included in this package and can be
used as a starting point.

## Container

The Docker image builds standard SUMMA (with iterative solver) and wraps it
via a Python subprocess BMI + grpc4bmi:

```bash
cd container
docker build -t ghcr.io/darriey/summa-grpc4bmi:v0.1.0 .
```

The first `update()` call runs the full SUMMA simulation as a subprocess.
Subsequent `update()` calls step through the output timesteps. All standard
SUMMA output variables are available via `get_value()`.

## License

Apache-2.0
