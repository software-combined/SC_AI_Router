# SCG Prototypes

Publishes a built frontend prototype to the SCG prototype channel and returns a
shareable URL such as `https://prototypes.softwarecombined.com/checkout-v2-7f3a/`.

The `publish-prototype` skill owns the procedure; `scripts/prototypes.py` under
that skill does the work: validate the slug and asset paths, run the pinned
gitleaks scan, archive the artifact in `software-combined/SC_Prototypes`, sync it
to the private channel bucket, invalidate the CloudFront path, and verify the
live URL before printing it.

Requirements on the machine that publishes:

- AWS profile `scg-prototypes` from the `SC-AWS-PrototypePublisher` permission set.
- Git access to `software-combined/SC_Prototypes`.
- The gitleaks binary pinned by the SCG review hooks, verified by SHA-256 before
  every scan. Publishing refuses to run until that pin exists, so install the
  `scg-review` plugin and complete its review-setup skill first.

The channel foundation lives in `SC_Infrastructure` at
`domains/web-edge/static-site-cloudfront-s3` and stays fail-closed until its
owner approves the production deploy. Until then every publish stops with a
clear "not deployed yet" message.
