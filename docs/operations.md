# Router operations

## How to ship

Merge to `main`. The release workflow builds the bundle, runs the suite,
and publishes a `vMAJOR.MINOR.BUILD` release with `latest.json`. Every
router on the stable channel installs it within about fifteen minutes.

## How to test first

Push to `beta`. The workflow publishes a `vMAJOR.MINOR.BUILD-beta`
pre-release with `latest-beta.json`. Cyril's machine follows the `beta`
channel (`beta` in the `channel` file beside the state directory), so it
updates first; watch its `/health` version and `logs/update.log` before
merging to `main`.

## How to roll back

Push a revert to `main` (the next release supersedes the bad one), or pin
one machine with `python3 packaging/install.py --version X`. The installer
itself rolls back automatically when the new release fails its health
check.

## Restart behavior

On update the router stops accepting new requests (they get `503` with
`Retry-After: 2`), finishes in-flight requests up to the two-minute drain
deadline, then exits; launchd holds the listening socket so connections
wait instead of failing. `/health` reports `draining: true` during the
drain. Without socket activation (manual runs) there is a brief
refused-connection window at process start; the Codex request and stream
retry settings cover it.
