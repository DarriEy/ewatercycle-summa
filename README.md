# ewatercycle-summa

SUMMA (Structure for Unifying Multiple Modeling Alternatives) plugin for [eWaterCycle](https://ewatercycle.readthedocs.io/).

Runs the standard SUMMA executable from [CH-Earth/summa](https://github.com/CH-Earth/summa/tree/develop_sundials)
inside a Docker container via a subprocess BMI wrapper served by
[grpc4bmi](https://github.com/eWaterCycle/grpc4bmi). Works with any existing
SUMMA domain setup (e.g. from [SYMFLUENCE](https://github.com/DarriEy/SYMFLUENCE)).

## Installation

```bash
pip install ewatercycle-summa
```

## Usage

```python
from ewatercycle.models import SUMMA
from ewatercycle.parameter_sets import ParameterSet

from ewatercycle_summa.forcing import SUMMAForcing

# Point to pre-prepared SUMMA forcing
forcing = SUMMAForcing(
    directory="/path/to/forcing",
    forcing_file="forcing.nc",
    start_time="2000-01-01T00:00:00Z",
    end_time="2001-01-01T00:00:00Z",
)

# Point to SUMMA parameter set (settings, attributes, cold state, etc.)
parameter_set = ParameterSet(
    name="summa_test",
    directory="/path/to/parameter_set",
    config="settings/SUMMA/fileManager.txt",
    target_model="SUMMA",
)

# Create and run the model
model = SUMMA(forcing=forcing, parameter_set=parameter_set)
cfg_file, cfg_dir = model.setup()
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
docker build -t ghcr.io/ewatercycle/summa-grpc4bmi:v0.1.0 .
```

The first `update()` call runs the full SUMMA simulation as a subprocess.
Subsequent `update()` calls step through the output timesteps. All standard
SUMMA output variables are available via `get_value()`.

## License

Apache-2.0
