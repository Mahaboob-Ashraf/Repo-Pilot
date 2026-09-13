FROM python:3.11-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84

LABEL org.opencontainers.image.title="RepoPilot Python test runner"
LABEL org.opencontainers.image.description="Networkless pytest runtime for the bounded RepoPilot M5 sandbox"

# RepoPilot invokes pytest directly against a read-only source mount. Keep the
# image limited to pytest and its explicitly pinned runtime dependencies.
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
    iniconfig==2.3.0 \
    packaging==26.3 \
    pluggy==1.6.0 \
    Pygments==2.20.0 \
    pytest==9.1.1

WORKDIR /workspace
