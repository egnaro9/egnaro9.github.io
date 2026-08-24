# suite/

Two generated pages and the provenance system behind them.

- `index.html` — six tools, one number each, every number recomputed from pinned bytes.
- `runner.html` — the same evidence stepped through, ending with a verifier refusing tampered
  bundles by name.

Both are **generated and committed**. Nothing on either page is typed by hand.

## Build it

```bash
python3 -m venv .venv
.venv/bin/pip install -r suite/requirements-dev.txt
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest tools/ suite/ -q
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python suite/build.py
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python suite/runner.py
git diff --exit-code -- suite/index.html suite/runner.html
```

`PATH` matters: `runner.py` invokes `vac-verify` as a subprocess, so the venv's `bin` has to be
on `PATH`, not just its interpreter.

## vac-verify is mandatory

`runner.py` preflights for `vac-verify` and **exits nonzero** if it is missing. This is
deliberate and is not a convenience check.

The five named refusals are step 5. Without the verifier the generator still renders, but every
case degrades to "could not run the verifier", which a visitor reads as five demonstrations when
it is five failures to demonstrate. A weaker page is worse than no new page, so the build refuses
and leaves the committed page untouched.

## Where the numbers come from

`sources.json` is the pin. Each entry names the artifact, the **issuer commit** its bytes came
from, the `sha256` those bytes must have, a **commit-pinned** public URL, and a versioned
`derivation` naming which reader may parse that artifact shape.

A sibling checkout under `$HOME` is only byte transport and carries no authority: bytes are
accepted only when they hash to the pin, otherwise the pinned URL is fetched instead. No local
`HEAD` is read and no `blob/main` link is rendered, because both go false silently when someone
else pushes.

Every panel resolves to exactly one of three states:

| state | meaning | rendering |
|---|---|---|
| `VALID` | bytes hash to the pin | the derived number |
| `STALE` | bytes exist but do not match the pin | the state, the reason, **and no number** |
| `ABSENT` | no bytes obtainable, or unparseable | the state and both paths tried |

`STALE` and `ABSENT` never keep the value the panel printed before. A source that moved off its
pin loses its number rather than flattering the page with a remembered one.

## Changing a pin

Bumping a pin republishes a public claim, so it is always a reviewed edit and never automatic.

1. `python3 suite/check_pins.py` reports every pin as `VALID`, `BEHIND` (pin intact, upstream
   moved past it) or `BROKEN` (does not resolve, or hash mismatch).
2. Review the upstream change and decide whether the claim still holds.
3. Update `issuer_commit`, `sha256`, `public_url` and `pinned_as_of` in `sources.json`.
4. Re-run `suite/build.py` and commit the regenerated page alongside it.

The pre-commit claim gate re-fetches the new pinned URL and hashes it itself, so a receipt alone
cannot pass a claim. A formatting-only edit to `sources.json` needs no receipt: the gate compares
semantic tuples, not text.

## What CI enforces

`.github/workflows/suite.yml` runs on any change under `suite/`. It fails if `vac-verify` is
missing, a pin does not resolve or hash, a panel is `STALE` or `ABSENT`, a test fails, or either
committed page differs from a fresh build. It never commits, bumps a pin, or deploys.

`.github/workflows/pin-drift.yml` runs weekly, reports drift, and fails on it. It changes
nothing: a failure there is a prompt for a human, not a deployment mechanism.
