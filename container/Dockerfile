# SUMMA subprocess BMI container for eWaterCycle.
#
# Builds standard SUMMA (with SUNDIALS) from CH-Earth/summa and serves it
# via a Python subprocess BMI wrapper + grpc4bmi.
#
# Build:  docker build -t ghcr.io/ewatercycle/summa-grpc4bmi:v0.1.0 .
# Run:    docker run -p 55555:55555 -v /data:/data ghcr.io/ewatercycle/summa-grpc4bmi:v0.1.0

# ---------------------------------------------------------------------------
# Stage 1: Build SUMMA with SUNDIALS
# ---------------------------------------------------------------------------
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gfortran cmake make git \
    libnetcdf-dev libnetcdff-dev libopenblas-dev liblapack-dev \
    pkg-config ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN git clone --depth 1 -b develop_sundials \
    https://github.com/CH-Earth/summa.git

# Patch sources for Linux (from SYMFLUENCE build_instructions.py)
RUN cd summa && \
    # int(max_steps) -> int(max_steps, kind=8) for LP64
    sed -i 's/int(max_steps)/int(max_steps, kind=8)/g' \
        build/source/engine/summaSolve4ida.f90 2>/dev/null || true && \
    # Initialize total_soil_depth to prevent NaN
    if grep -q 'total_soil_depth' build/source/engine/soilLiqFlx.f90 && \
       ! grep -q 'total_soil_depth = ' build/source/engine/soilLiqFlx.f90; then \
        awk '/depthWettingFront = \(rootZoneLiq\/availCapacity\)/{print "   total_soil_depth = sum(in_surfaceFlx % mLayerDepth)"}1' \
            build/source/engine/soilLiqFlx.f90 > /tmp/fix.f90 && \
        mv /tmp/fix.f90 build/source/engine/soilLiqFlx.f90; \
    fi && \
    # Git tag for version detection
    git config user.email "build@docker" && git config user.name "build" && \
    git tag v0.0.0 && \
    # Build libftz.so for x86-64 denormal handling
    mkdir -p bin && \
    if [ "$(uname -m)" = "x86_64" ]; then \
        printf '#include <xmmintrin.h>\n#include <pmmintrin.h>\n__attribute__((constructor))\nstatic void enable_ftz_daz(void) {\n    _MM_SET_FLUSH_ZERO_MODE(_MM_FLUSH_ZERO_ON);\n    _MM_SET_DENORMALS_ZERO_MODE(_MM_DENORMALS_ZERO_ON);\n}\n' \
            | gcc -shared -fPIC -o bin/libftz.so -x c - -msse2; \
    else \
        touch bin/libftz.so; \
    fi

# Build standard SUMMA (no NGEN, with SUNDIALS)
RUN cd summa && \
    cmake -S build -B cmake_build \
        -DUSE_SUNDIALS=OFF \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_Fortran_FLAGS_RELEASE="-O2 -DNDEBUG -finit-real=zero -finit-integer=0 -finit-logical=false" && \
    cmake --build cmake_build --target all -j"$(nproc)" && \
    # Stage outputs
    mkdir -p /install/bin /install/lib && \
    cp bin/summa.exe /install/bin/ && \
    cp cmake_build/libsumma.so /install/lib/ && \
    cp bin/libftz.so /install/lib/ 2>/dev/null || true

# ---------------------------------------------------------------------------
# Stage 2: Runtime
# ---------------------------------------------------------------------------
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnetcdff7 libopenblas0 liblapack3 libgfortran5 libgomp1 \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir grpc4bmi numpy bmipy netCDF4 cftime

COPY --from=builder /install/bin/ /usr/local/bin/
COPY --from=builder /install/lib/ /usr/local/lib/
RUN ldconfig

COPY summa_bmi_wrapper.py /usr/local/lib/python3/summa_bmi_wrapper.py
ENV PYTHONPATH=/usr/local/lib/python3
ENV SUMMA_EXE=/usr/local/bin/summa.exe

RUN mkdir -p /data
EXPOSE 55555

ENTRYPOINT ["run-bmi-server", "--name", "summa_bmi_wrapper.SummaBmi", "--port"]
CMD ["55555"]
