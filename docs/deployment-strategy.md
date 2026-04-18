# Deployment Strategy — simple-tcp-comm on DigitalOcean

> Saved: 2026-04-17
> Scope: solo-dev, minimal-hacker ergonomics. Not production-hardened.

---

## 1. DigitalOcean credentials

### Where they live on this machine

```
/home/b/.config/doctl/config.yaml   (line 10: access-token)
```

This is the `doctl` (official DigitalOcean CLI) config. The token has prefix
`dop_v1_…` — a bearer Personal Access Token. File mode is `600` (owner-only
read), which is correct.

**Redacted in this doc on purpose** — never commit the token to git or paste it
into shared notes. Retrieve it locally with:

```bash
grep '^access-token:' ~/.config/doctl/config.yaml
```

Useful checks:

```bash
doctl auth list         # show configured contexts
doctl account get       # confirm token works, show email
```

### Reusing the token on another machine

Technically portable — a `dop_v1_` PAT is a plain bearer credential with no
device binding. But the recommended pattern is **one token per machine/
purpose**, not sharing.

| Approach              | Tradeoff                                           |
|-----------------------|----------------------------------------------------|
| Share existing token  | Fast. But a single compromise revokes everywhere.  |
| One token per machine | A lost laptop → revoke that token only. Preferred. |

Create additional tokens at
`https://cloud.digitalocean.com/account/api/tokens`, then on the new machine:

```bash
doctl auth init --context laptop-work
```

**Avoid:** committing the token to git, syncing it via Dropbox/iCloud, pasting
it into chat tools. Leaked DO tokens get scraped within minutes.

### Scoping

DigitalOcean supports fine-grained PATs (e.g. `firewall:update` only). For any
token that lives on an ephemeral droplet, scope it to only what that droplet
needs — not full account access.

---

## 2. Overall deployment strategy

### Architecture

The **same bundle** is shipped via `scp` to every target — DO droplet and
worker devices alike. The target decides what to run (`server`, `worker`,
`drain`) based on its role config. Worker devices self-register with the
DO firewall using a narrowly-scoped PAT that can *only* append their own
IP to the existing firewall — no droplet, no account, no other resource.

```
┌──────────────────┐   scp bundle    ┌───────────────────────────┐
│ Control machine  │ ──────────────▶ │  DO droplet               │
│ (your laptop)    │                 │  role=server              │
│                  │                 │  runs: ./server on :9999  │
│ builds bundle:   │                 │  /var/lib/myapp/*.db      │
│  - worker bin    │                 └────────────▲──────────────┘
│  - drain  bin    │                              │ TCP 9999
│  - server bin    │                              │ (allowlisted
│  - *.env configs │                              │  per worker IP)
│  - do-token      │                              │
│    (SCOPED:      │   scp bundle    ┌────────────┴──────────────┐
│     firewall     │ ──────────────▶ │  Worker device            │
│     :update only)│                 │  (home lab, PC, friend)   │
└──────────────────┘                 │  role=worker (or drain)   │
                                     │                           │
                                     │  1. doctl firewall        │
                                     │     add-rules <self-ip>   │
                                     │     (scoped PAT)          │
                                     │  2. ./worker   (or drain) │
                                     └───────────────────────────┘
```

- **Server** (`server` binary) runs on a DO droplet, listens on
  `0.0.0.0:9999`.
- **Workers / drain** (`worker`, `drain` binaries) run on external devices,
  poll the server for jobs or drain archives.
- **Firewall** restricts inbound TCP/9999 and TCP/22 to allowlisted public
  IPs. The firewall *is* the worker registry — no orchestrator, no state
  store.
- **Scoped DO token on workers.** The token shipped in the bundle is a
  fine-grained PAT restricted to `firewall:update` on the one named
  firewall. It cannot create droplets, read other resources, or touch
  billing. Compromise blast radius = an attacker can add/remove IPs on
  that firewall, nothing else.

### Minimal self-registration loop

```
1. One long-lived firewall on DO (allow 22 + 9999, sources = allowlist).
2. Control machine creates droplet via doctl, scps bundle, starts server.
3. Adding a worker:
   a. Control machine scps bundle (binaries + configs + scoped PAT) to
      the worker device.
   b. Worker runs bootstrap: `doctl compute firewall add-rules <fw-id>
      --inbound-rules "protocol:tcp,ports:9999,address:$(curl -s
      ipinfo.io/ip)"` using the scoped token.
   c. Worker starts `./worker` (or `./drain`).
4. On teardown: worker removes its own rule with the same scoped token;
   optionally the control machine destroys the droplet.
```

The scoped-PAT path is the default here — not cloud-init magic. It keeps
the control machine out of the loop when a worker's IP rotates, and the
token's narrow scope means leaking a bundle is bounded damage.

---

## 3. `deploy/automated/` — one-command deploy

### Files

| File              | Role                                                           |
|-------------------|----------------------------------------------------------------|
| `config.env`      | DO knobs — droplet size/region/image, firewall ports, IPs     |
| `deploy.sh`       | Local orchestrator (`doctl` → scp → ssh → bootstrap)           |
| `remote-setup.sh` | Runs on droplet: apt install, init DBs, start server           |
| `server.env`      | Becomes `/opt/simple-tcp-comm/.env` on the droplet             |
| `teardown.sh`     | Deletes the droplet + firewall                                 |
| `README.md`       | Usage doc                                                       |

### Resources created on DigitalOcean

```
1x Droplet         ~$6/mo (s-1vcpu-1gb)   destroyable anytime
1x Firewall        free
0x new SSH keys    uses one you already have on your account
0x managed DBs     SQLite on droplet disk
```

### Usage

```bash
cd ~/simple-tcp-comm
./deploy/automated/deploy.sh           # deploy (or re-deploy, idempotent)
./deploy/automated/teardown.sh         # destroy droplet + firewall
```

After deploy, the output prints the droplet IP. Workers:

```bash
QUEUE_HOST=<droplet-ip> QUEUE_PORT=9999 python3 worker.py
```

### Adding a worker

Run on the control machine to ship a bundle to a new worker device:

```bash
./deploy/automated/ship-worker.sh user@worker-host
```

This scps the binaries + `.env` configs + a freshly-minted scoped PAT
(`firewall:update` on the named firewall only) to the worker. The
worker then self-registers on start:

```bash
# on the worker device, bundled bootstrap script:
./bootstrap-worker.sh          # reads scoped token, adds $(self-ip) to FW
./worker                        # or ./drain
```

The control machine does *not* need to re-run `deploy.sh` when a worker
joins — the worker adds itself. `config.env`'s `FW_ALLOWED_IPS` is only
for the control machine's own IP (for ssh-in / ops).

### Idempotency model

Re-running `deploy.sh` with the same `DEPLOY_NAME`:

- Skips droplet creation if it already exists (name-lookup on DO *is* the
  state store — no local `.state` file).
- Updates firewall (useful when your home IP rotates).
- Re-ships code, restarts `server.py`.

### Key design decisions & why

- **`config.env` is the only file you edit day-to-day.** Scripts are generic;
  config is the strategy. Same scripts can back multiple deployments just by
  swapping env files.
- **Separate `server.env` (not reusing local `.env`).** Local `.env` points
  workers at `127.0.0.1`. Server needs `0.0.0.0`. Keeping them separate
  prevents "I scp'd the wrong env" bugs.
- **tmux default, systemd optional.** tmux is debuggable (`tmux attach -t
  tcpcomm`); systemd survives reboots. `RUN_MODE` in `config.env` toggles.
- **No cloud-init.** scp+ssh bootstrap is easier to iterate on than user-data
  scripts that fail invisibly at boot.
- **No TLS.** For allowlisted-IP TCP behind a DO firewall, plaintext is an
  acceptable solo-dev tradeoff. Layer in stunnel or WireGuard later if the
  traffic warrants it.

---

## 4. Packaging each component as a single self-contained binary

Three components ship as independent binaries. All are pure-stdlib
(`socket`, `struct`, `json`, `sqlite3`, `subprocess`) — no wheels, no
venv, no `pip install` on the target.

| Binary    | Runs on         | Source entry                                 |
|-----------|-----------------|----------------------------------------------|
| `server`  | DO droplet      | `server.py`                                  |
| `worker`  | Worker device   | `worker.py`                                  |
| `drain`   | Worker device   | `archive_receiver/struct_pack/drain.py`      |

### 4.1 Strategy matrix — pick *one* per deploy

| Strategy       | Target deps     | Artifact size | Cross-build? | Ergonomics              |
|----------------|-----------------|---------------|--------------|-------------------------|
| **PyInstaller**| none (glibc only)| ~8–12 MB     | per OS+arch  | truly standalone        |
| **Nuitka**     | none (glibc only)| ~10–20 MB    | per OS+arch  | faster; compile slower  |
| **shiv**       | `python3` only  | ~100 KB       | portable     | depends on Python on target |
| **zipapp**     | `python3` only  | ~50 KB        | portable     | stdlib-only build tool  |
| **ship `.py`** | `python3`       | raw           | portable     | current default         |

Default recommendation: **PyInstaller** for worker + drain (workers have
unpredictable OS/Python state), **ship `.py`** for server (the droplet is
a known Ubuntu image with `python3` preinstalled). Switch server to
PyInstaller only if you want bit-for-bit reproducible droplet bootstrap.

### 4.2 PyInstaller — per-component build

Shared build scaffolding:

```bash
pip install pyinstaller          # ideally inside a throwaway venv
mkdir -p dist build
COMMON_FLAGS="--onefile --strip --clean --workpath build --distpath dist"
```

**server** — bundles `env.py` as a data file so `.env` lookup still works:

```bash
pyinstaller $COMMON_FLAGS \
  --name server \
  --hidden-import env \
  server.py
```

**worker** — same pattern:

```bash
pyinstaller $COMMON_FLAGS \
  --name worker \
  --hidden-import env \
  worker.py
```

**drain** — lives in `archive_receiver/struct_pack/` and uses `sys.path`
manipulation to import sibling modules (`protocol`, `drain_base`,
`schema_registry`). PyInstaller's static analysis will miss these unless
we tell it explicitly:

```bash
pyinstaller $COMMON_FLAGS \
  --name drain \
  --paths archive_receiver \
  --paths archive_receiver/struct_pack \
  --hidden-import protocol \
  --hidden-import drain_base \
  --hidden-import receiver_base \
  --hidden-import schema_registry \
  archive_receiver/struct_pack/drain.py
```

Output: `dist/server`, `dist/worker`, `dist/drain` — each a single
executable, ~10 MB, runnable with `./worker` etc.

### 4.3 Cross-building for worker devices

PyInstaller binaries are **OS + arch + glibc specific**. If your laptop
is Arch (glibc 2.41) and the worker is Ubuntu 22.04 (glibc 2.35), the
binary built on the laptop *may* fail on the worker with "symbol not
found". Build on the oldest glibc you need to support.

Reproducible build via Docker, one per target:

```bash
# Ubuntu 22.04 / amd64 / glibc 2.35 target
docker run --rm -v "$PWD":/src -w /src --platform=linux/amd64 \
  ubuntu:22.04 bash -c '
    apt-get update -qq && apt-get install -y -qq python3-pip binutils
    pip install --break-system-packages pyinstaller
    for entry in "server.py server" "worker.py worker" \
                 "archive_receiver/struct_pack/drain.py drain"; do
      set -- $entry
      pyinstaller --onefile --strip --clean \
        --workpath /tmp/build --distpath dist/ubuntu-22.04-amd64 \
        --name $2 \
        --paths archive_receiver --paths archive_receiver/struct_pack \
        --hidden-import env --hidden-import protocol \
        --hidden-import drain_base --hidden-import schema_registry \
        --hidden-import receiver_base \
        $1
    done
  '
```

For arm64 targets (Raspberry Pi, Apple Silicon workers) swap
`--platform=linux/arm64` and `ubuntu:22.04` for the matching image.
Binfmt/QEMU emulation makes this work on an x86 laptop at ~5× slower
compile speed — acceptable for a handful of infrequent builds.

### 4.4 Nuitka (optional) — faster runtime, same standalone property

Nuitka compiles Python → C → native binary. Same target-dep profile as
PyInstaller (glibc only), but startup is ~3× faster and runtime CPU-bound
code is ~1.5× faster. Compile time is much slower (~1 min/component).

```bash
pip install nuitka
python3 -m nuitka --onefile --standalone --follow-imports \
  --output-filename=worker --output-dir=dist worker.py
```

Worth it only if worker/drain become CPU-bound (they currently aren't —
they're I/O-bound on TCP + sqlite). Keep PyInstaller as the default.

### 4.5 shiv / zipapp — when the target has Python

Useful for the DO droplet (we control it, it has `python3`) or
Python-friendly worker devices.

**shiv**:

```bash
pip install shiv
shiv -e worker:main       -o dist/worker.pyz worker.py env.py
shiv -e server:main       -o dist/server.pyz server.py env.py
# drain is a __main__ module, not a function — needs a wrapper, so prefer
# PyInstaller for it.
```

**zipapp** (stdlib-only, no external build tool):

```bash
build_zipapp() {              # usage: build_zipapp <src.py> <out.pyz>
  local src=$1 out=$2
  local tmp=$(mktemp -d)
  cp "$src" env.py "$tmp/" && mv "$tmp/$(basename $src)" "$tmp/__main__.py"
  python3 -m zipapp "$tmp" -o "$out" -p '/usr/bin/env python3'
  chmod +x "$out" && rm -rf "$tmp"
}
build_zipapp server.py dist/server.pyz
build_zipapp worker.py dist/worker.pyz
```

Targets then run: `./worker.pyz` (needs `python3` on PATH).

### 4.6 Build script — one entry point, all three binaries

Recommended to wire this into `deploy/automated/build-bundle.sh` so the
bundle always contains fresh artifacts. Sketch:

```bash
#!/usr/bin/env bash
# deploy/automated/build-bundle.sh — builds server/worker/drain binaries
set -euo pipefail
MODE=${MODE:-pyinstaller}      # pyinstaller | nuitka | zipapp | raw
OUT=${OUT:-dist}
case "$MODE" in
  pyinstaller) ./scripts/build-pyinstaller.sh "$OUT" ;;
  nuitka)      ./scripts/build-nuitka.sh "$OUT" ;;
  zipapp)      ./scripts/build-zipapp.sh "$OUT" ;;
  raw)         cp server.py worker.py archive_receiver/struct_pack/drain.py "$OUT/" ;;
  *) echo "unknown MODE=$MODE" >&2; exit 1 ;;
esac
```

The bundle scp'd to each target then contains the right artifact for the
role: `server` binary to the droplet, `worker` + `drain` + configs +
scoped DO token to worker devices (see §2 architecture diagram).

### 4.7 Gotchas

- **`env.py` path lookup.** `env.load()` reads `.env` from CWD. PyInstaller's
  `--onefile` extracts the frozen payload to `$TMPDIR/_MEIxxxx` but CWD
  stays as the launch dir, so this keeps working. If you ever switch to
  `__file__`-based resolution inside `env.py`, wrap it:
  ```python
  import sys, os
  base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
  ```
- **sqlite3 on musl.** PyInstaller builds on Alpine (musl libc) can fail
  to find `_sqlite3` because CPython's musl wheels don't always ship it.
  Stick to glibc base images (Ubuntu/Debian) for builds.
- **`drain`'s `sys.path` hack.** The `sys.path.insert` calls at the top of
  `archive_receiver/struct_pack/drain.py` do nothing once frozen — the
  `--hidden-import` + `--paths` flags in §4.2 are what actually wire up
  imports. Don't remove the `sys.path` lines (they're needed for running
  from source during dev).
- **Binary size.** `--strip` shaves ~2 MB; UPX shaves another ~4 MB but
  many AV scanners flag UPX'd binaries — not worth the noise.
- **Reproducibility.** PyInstaller bakes the build timestamp into the
  binary. Use `SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)` before
  building if you want byte-identical artifacts from the same commit.

---

## 5. What's intentionally NOT built yet

- **Auto-spawning worker droplets.** Once the server-side is stable, a
  `spawn-worker.sh` that creates a second droplet and auto-appends its IP
  to the firewall is the natural next layer.
- **TLS / WireGuard.** Firewall allowlist is the only access control. Fine
  for this scope.
- **Secrets manager.** `.env` is ad-hoc. If the threat model grows, move
  sensitive values into DO's Spaces-backed config or sops+age.
- **Observability.** `tmux attach` / `journalctl -u tcpcomm -f` are the
  current debugging tools. Add structured logging → a log collector only
  if volume justifies it.

---

## 6. Quick reference

| Want to…                          | Command                                         |
|-----------------------------------|-------------------------------------------------|
| Deploy / re-deploy                | `./deploy/automated/deploy.sh`                  |
| Tear down                         | `./deploy/automated/teardown.sh`                |
| Add a new worker                  | `./deploy/automated/ship-worker.sh user@host`   |
| Add control machine IP to firewall | Edit `FW_ALLOWED_IPS` in `config.env`, redeploy |
| Inspect server                    | `ssh root@<ip> 'tmux attach -t tcpcomm'`        |
| See all DO resources              | `doctl compute droplet list && doctl compute firewall list` |
| List SSH keys on DO               | `doctl compute ssh-key list`                    |
| Switch to another DO account      | `doctl auth init --context <name>`              |
| Show public IP (for allowlist)    | `curl -s https://ipinfo.io/ip`                  |
