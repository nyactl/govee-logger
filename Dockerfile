# syntax=docker/dockerfile:1

# All dependencies ship manylinux wheels for amd64 and arm64, so no compiler is needed.
FROM python:3.14-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
RUN /opt/venv/bin/pip install --only-binary=:all: .

FROM python:3.14-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
RUN groupadd -g 1000 govee \
 && useradd -u 1000 -g govee -M -s /usr/sbin/nologin govee \
 && install -d -o govee -g govee /data
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    GOVEE_LOGGER_DB=/data/readings.db
USER govee
# Talks to the host's BlueZ over the system D-Bus socket; mount /run/dbus/system_bus_socket.
ENTRYPOINT ["govee-logger"]
CMD ["run", "--every", "24h"]
