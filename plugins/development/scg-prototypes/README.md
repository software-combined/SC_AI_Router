# SCG Prototypes

This plugin publishes a built frontend prototype and returns a shareable URL,
such as `https://prototypes.softwarecombined.com/checkout-v2-7f3a/`.

The `publish-prototype` skill validates the slug and asset paths, scans the
artifact for secrets, archives the exact published files, uploads them to the
configured channel, and verifies the live URL.

The bundled channel config is an empty template. A publisher needs:

- A completed private config outside the repository and installed plugin.
- Access to the AWS profile and archive repository named in that config.
- The gitleaks binary pinned by the SCG review hooks.

Select the private config with `--config` or
`PROTOTYPE_CHANNEL_CONFIG`. Publishing fails before external operations when
the selected config is missing or incomplete. See
`skills/publish-prototype/references/channel.md` for the fields and commands.

Publishing also verifies the scanner's SHA-256 hash before every scan. Install
the `scg-review` plugin and complete its review-setup skill when this machine
does not yet have the verified scanner record.
