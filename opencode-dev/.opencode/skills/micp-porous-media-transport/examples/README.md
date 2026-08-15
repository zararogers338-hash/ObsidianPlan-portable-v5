# Examples — micp-porous-media-transport

Three runnable invocations. Each is a complete stdin payload for
`tools/transport.py`.

## 01 — Sand column, moderate rates

```bash
python tools/transport.py < examples/01-sand-column-analyze.json
```

Expected: `SUCCESS`, open column, small CaCO3 mass, self-check passed.

## 02 — Inlet clogging (high concentration)

```bash
python tools/transport.py < examples/02-inlet-clogging.json
```

Expected: `SUCCESS`, `clogged=true`, porosity fell below 0.02 (inlet clogging).
Note the payload carries `human_approval_state.granted=true` for the
`risk_level=high` gate.

## 03 — Constant head vs constant flux

```bash
python tools/transport.py < examples/03-head-vs-flux.json
```

Expected: `SUCCESS`, clogged under the high-rate head case; precipitation mass
differs from the equivalent constant-flux run — demonstrating that the
boundary condition changes the clogging trajectory.

## Run all examples

```bash
for f in examples/*.json; do echo "== $f =="; python tools/transport.py < "$f" | python -c "import json,sys; o=json.load(sys.stdin); print(o['status'], '-', o['summary'])"; done
```
