# Prototype channel

Published prototypes use `https://prototypes.softwarecombined.com/<slug>/`.
The channel stores each site privately and serves it through a public, unlisted
URL. Responses use `noindex`, and each publication expires after 30 days.

## Configure this machine

The bundled `channel.json` is an empty template. It cannot publish anything.
Copy it to a private location outside the repository and installed plugin, such
as `~/.config/scg-prototypes/channel.json`. Fill the copy with the approved
values for this environment:

- `account`: the expected Amazon Web Services (AWS) account identifier.
- `archiveRepository`: the Git repository that preserves published artifacts.
- `bucket`: the private storage bucket.
- `distributionId`: the content distribution identifier.
- `domain`: the public prototype domain.
- `profile`: the local AWS profile used for publishing.
- `expiryDays`: the publication lifetime. Keep this at `30` for the SCG channel.

Do not edit the installed template or commit a filled configuration file. Select
the private file for each command:

```sh
python3 <skill-dir>/scripts/prototypes.py --config ~/.config/scg-prototypes/channel.json publish <output-dir> --slug <slug>
```

You can instead set `PROTOTYPE_CHANNEL_CONFIG` to the private file path. Use
`--repo-dir` or `PROTOTYPE_CHANNEL_REPO_DIR` when the archive clone is not in
the default location.

## Safety checks

Publishing verifies that the selected AWS profile belongs to the configured
account before any storage write. It also refuses to run with
`GITLEAKS_CONFIG` or `GITLEAKS_CONFIG_TOML` set. The command verifies the
SHA-256 hash of the gitleaks binary recorded by the SCG review setup.

A machine without that scanner record cannot publish. Install the `scg-review`
plugin and run its review-setup skill first.

## Failures

- **Channel not configured**: select a complete private config with `--config`
  or `PROTOTYPE_CHANNEL_CONFIG`.
- **AWS sign-in expired**: sign in to the profile named in the private config,
  then retry once.
- **Wrong account**: select the approved profile for the configured channel.
- **Gitleaks finding**: remove the secret, rotate it, and rebuild. Never bypass
  the finding.
- **Root-absolute references**: rebuild with the slug as the base path, such as
  `npm run build -- --base=/<slug>/`, or convert references to relative paths.
- **Symbolic links**: replace links with real files before publishing.
- **Slug already published**: choose another slug, or use `--update` when the
  replacement is deliberate.
- **Verification failed**: wait one minute and check the configured channel.
  Retry with `--update` after the channel is healthy.
- **Link expired**: rebuild from the archive and publish the same slug with
  `--update`.

## Unpublishing

`unpublish <slug>` removes the public copy and its registry entry. The archived
source remains available for a later republish.
