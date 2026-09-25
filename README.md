# govee-logger

Pulls temperature and humidity history from Govee Bluetooth LE thermometers into SQLite.

The devices keep 20 days of per-minute readings. `govee-logger download` finds nearby devices,
connects to each one over Bluetooth and fetches only the minutes since its last download, so a
daily run is enough and nothing is lost while the logger is down for less than 20 days.
Newer firmware (e.g. H5075 1.04.x) encrypts this exchange; the handshake is handled automatically.

`govee-logger scan` records just the current reading from each device's broadcast, without connecting.

| | Models |
|---|---|
| Current reading | H5072, H5074, H5075, H5100, H5101, H5102, H5104, H5174, H5177, H5179 |
| History download | H5075 (tested), H5072, H5100, H5101, H5102, H5104, H5174, H5177 |

Only the H5075 has been tested on real hardware. The other models use the same formats and commands
according to the projects credited below; reports for them are welcome.

## Commands

    govee-logger run --every 24h        # download now, then every 24h until stopped (container default)
    govee-logger download               # one download pass
    govee-logger download --full        # re-fetch all 20 days
    govee-logger download --address MAC # one device only
    govee-logger scan --dry-run         # list devices in range with their current reading
    govee-logger latest                 # newest reading per device
    govee-logger export --since 2026-09-01 > readings.csv

| Setting | Flag | Environment | Default |
|---|---|---|---|
| Config file | `--config` | `GOVEE_LOGGER_CONFIG` | `/etc/govee-logger/config.toml` (optional) |
| Database | `--db` | `GOVEE_LOGGER_DB` | `/var/lib/govee-logger/readings.db`, `/data/readings.db` in the image |

The config file is optional:

```toml
scan_seconds = 60          # listen time before connecting; ends early once all [aliases] are seen
# adapter = "hci1"         # default adapter if unset

[aliases]
"A4:C1:38:12:34:56" = "Living room"
```

## Data

One SQLite file, written only by the logger. Readers (e.g. Grafana) can open it read-only.

| Table | Columns | |
|---|---|---|
| `readings` | `address`, `ts`, `temperature`, `humidity` | one row per device per minute; primary key `(address, ts)`; `ts` is UTC ISO 8601 at minute precision |
| `devices` | `address`, `name`, `label`, `battery`, `rssi`, `last_seen`, `last_download` | one row per device; `name` is what the device advertises, `label` its alias from the config (updated whenever the device is seen), `last_download` the watermark for the next incremental download |

## Container

`ghcr.io/nyactl/govee-logger` is built for amd64 and arm64 and signed with cosign by
`.github/workflows/container.yml`. It runs as uid 1000 and needs no network and no capabilities:
it reaches Bluetooth through the host's BlueZ over the system D-Bus socket.

Host requirements:

- a Bluetooth adapter and `bluez` installed, with `bluetooth.service` running
- on AppArmor hosts (Ubuntu, Debian): the profile in `contrib/apparmor/govee-logger`. Docker's
  default profile blocks all D-Bus traffic; this one is the same profile plus sending to `org.bluez` only.

      sudo install -m 0644 contrib/apparmor/govee-logger /etc/apparmor.d/govee-logger
      sudo apparmor_parser -r -W /etc/apparmor.d/govee-logger

  Files in `/etc/apparmor.d` are loaded again at boot.

```yaml
services:
  govee-logger:
    image: ghcr.io/nyactl/govee-logger:0.1.0@sha256:...
    volumes:
      - /run/dbus/system_bus_socket:/run/dbus/system_bus_socket
      - /srv/govee-logger:/data              # owned by 1000:1000
      # - ./config.toml:/etc/govee-logger/config.toml:ro
    network_mode: none
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges, apparmor=govee-logger]
    restart: unless-stopped
```

Verify a release before pinning it:

```bash
v=0.1.0
docker run --rm ghcr.io/sigstore/cosign/cosign:v3.1.3 verify ghcr.io/nyactl/govee-logger:$v \
  --certificate-identity "https://github.com/nyactl/govee-logger/.github/workflows/container.yml@refs/tags/v$v" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Develop

    python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
    make test
    .venv/bin/govee-logger --db ./readings.db download

Runs on macOS too, where devices show up as CoreBluetooth UUIDs instead of MAC addresses.

## Releasing

Bump `version` in `pyproject.toml`, commit, then tag `v<version>` and push the tag. CI refuses a
tag that does not match `pyproject.toml`.

## Credits

The Bluetooth formats and the history protocol, including the encrypted handshake on newer
firmware, were documented by these projects. This is an independent implementation.

- [GoveeBTTempLogger](https://github.com/wcbonner/GoveeBTTempLogger) (MIT)
- [govee-h5075-thermo-hygrometer](https://github.com/Heckie75/govee-h5075-thermo-hygrometer) (MIT)
- [govee-ble](https://github.com/Bluetooth-Devices/govee-ble) (Apache-2.0)

Not affiliated with or endorsed by Govee.

## License

MIT, see [LICENSE](LICENSE).
