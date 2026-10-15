# Staff download access

This service exchanges an approved work-account token for ten minutes of Router
download access. Microsoft Entra verifies the person. API Gateway verifies the
access token. The handler requires the resource tenant's `Download` app role.
Approved portfolio guests use the same explicit role assignment as other staff.

The template creates a separate API and a CloudFront key group. It does not
change `infra/feed.yaml` or restrict any existing download. Keep anonymous
updates available until installed beta and stable clients can sign in, refresh
access, update, and recover from rollback.

## Deployment prerequisites

These resources need an approved tenant and AWS target. There are no default
tenant, application, account or signing-key identifiers in the source.

`bootstrap.yaml` creates a private versioned artifact bucket and the asymmetric
KMS signer. Both are retained on stack deletion. Validate and review its change
set first. Use its outputs for the deployment parameters below; `GetPublicKey`
returns public verification material only.

1. Register an API application in the exact resource tenant. Set its identifier
   URI to `api://<API application UUID>` and request version 2 access tokens.
2. Expose the delegated `Download.Read` scope. Add the `Download` app role with
   `User` as its allowed member type. Require assignment on the API enterprise
   application. Assign that role only to approved staff and approved guests.
3. Register one shared public client in that tenant. Register
   `http://localhost/scg-router/signin` as a mobile and desktop redirect URI.
   Register `https://dist.softwarecombined.com/install/` as a single-page
   application (SPA) redirect URI on the same application ID.
   Grant approved delegated access to `Download.Read` with administrator consent.
   Do not create a client secret. If the native app requires assignment, assign
   the approved users there too.
4. Provision an AWS Key Management Service (KMS) `ECC_NIST_P256` key with usage
   `SIGN_VERIFY`. Keep the private key in KMS. Permit the exchange role to call
   `kms:Sign` for `ECDSA_SHA_256` on that key only.
5. Obtain the key's public `SubjectPublicKeyInfo` through `GetPublicKey`. Convert
   those public DER bytes to a `PUBLIC KEY` PEM file. Supply that file and the
   matching KMS key ARN as the template parameters. Never supply private key data.
6. Package `handler.py` at the root of a zip file. Upload the reviewed artifact
   to a private, versioned deployment bucket. Supply its object key and version.
7. Validate the exact template and artifact. Before approved deployment, inspect
   the account, region, effective identity, permissions and proposed changes.
   Use CloudFormation change-set pre-deployment validation and read its results.
8. Read the deployed `ClientConfiguration` output. Include that public JSON as
   `download-auth.json` in the installer and persistent controller home. Read back
   the deployed API route, authorizer, Lambda permission, and key relationship.

CloudFront accepts ECDSA-256 signatures. Its SHA-256 cookie format requires
`CloudFront-Hash-Algorithm=SHA256` alongside the policy, signature and public-key
ID. KMS returns the standard DER signature. The handler encodes it directly and
limits the signed policy to `https://dist.softwarecombined.com/*`.
See [CloudFront signing commands](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-linux-openssl.html),
[KMS Sign](https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html), and
[custom cookie policies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-setting-signed-cookie-custom-policy.html).

The native installer and web download page must use that same public-client
application ID. The `NativeClientId` parameter deliberately remains one exact
allowed caller. The web page uses browser PKCE and the registered SPA redirect;
the native client uses its registered loopback redirect. There is no second
allowed client or weakened role check.

The Lambda runtime supplies Boto3. No AWS SDK or JWT library enters the Router
package. Gateway owns signature verification and issuer, audience, expiry and
scope checks. The handler also requires the native client ID, resource-tenant
user ID and `Download` role. A matching email address, guest status, or raw
`Authorization` header alone grants nothing.
See [API Gateway JWT authorization](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html).

## Native-client contract

`packaging/download_auth.py` exposes these calls:

| Call | Result |
| --- | --- |
| `configure(home)` | Validated public deployment settings from `download-auth.json`. |
| `ensure_access(home, interactive=False)` | A `Cookie` header, or a fixed-message `SignInRequired` exception. |
| `signin(home)` | Explicit browser sign-in, followed by the same cookie exchange. |
| `status(home)` | Local `configured`, `signed_in`, and `access_ready` flags; expiry or a safe reason code. |

The public configuration requires `version: 1`, `distribution_origin`,
`tenant_id`, `client_id`, `scope`, and `exchange_url`. The distribution origin is
fixed. The scope must be `api://<API application UUID>/Download.Read`. The exchange
URL must be the deployed HTTPS API Gateway `/download-access` endpoint.

The client binds IPv4 loopback on an available random port before opening the
system browser. It uses authorization-code Proof Key for Code Exchange (PKCE)
with `S256` and validates the random state before accepting the callback.
The redirect hostname is `localhost`: Microsoft documents dynamic-port matching
for this hostname. The listener still binds only `127.0.0.1` and checks the Host
header. See [Microsoft redirect URI rules](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url)
and [authorization-code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow).

Refresh tokens and cookies are written atomically to `download-session.json`.
The existing permission helpers restrict this file to the installing user.
The Windows directory is protected before any temporary secret file is created.
Access tokens remain in memory. Tokens and cookies never enter command arguments,
exception text, callback logs, or status output.

Persist the auth modules and their existing atomic-write and platform permission
dependencies outside the rollback-selected release. Bind the saved session to
the complete public configuration so a tenant or application change requires
fresh sign-in. Background callers never open a browser. A failed refresh keeps
the running router and its last working catalogue intact.

Only attach the returned header to the exact HTTPS distribution origin. Do not
send it to a custom feed, local file, another host, or redirected destination.
Authentication requests reject redirects. Missing configuration and denied
access are typed failures; neither returns an anonymous success.

The handler also returns the HTTP API version 2 `cookies` array. API Gateway
turns each entry into a separate `Set-Cookie` header. Each cookie has `Secure`,
`HttpOnly`, `SameSite=Lax`, `Path=/`, and a bounded `Max-Age`. It has no `Domain`
attribute. The remaining lifetime cannot outlive the signed policy or the access
token, and never exceeds ten minutes. Errors set no cookies.

Serve the browser exchange through a same-origin CloudFront `/download-access`
proxy with caching disabled and `Authorization` forwarded to this API. Then the
browser stores the HttpOnly cookies against `dist.softwarecombined.com`; the page
does not write `document.cookie`. No cross-origin resource sharing (CORS) is
needed. Native clients continue to consume the JSON response. This template
does not create the proxy or alter existing distribution behavior.

## Verification and cutover

Run the offline contract tests and template checks:

```sh
python3.14 -m unittest tests.test_download_auth tests.test_download_oauth tests.test_download_exchange
cfn-lint --format json infra/downloads/template.yaml
cfn-guard validate --rules infra/downloads/access.guard --data infra/downloads/template.yaml --output-format json
```

These checks use simulated Microsoft and KMS responses. They prove client,
claim, policy and permission-handling contracts, not deployed sign-in or
CloudFront delivery. Real Windows and Linux permission checks remain separate
native acceptance gates.

Before attaching the output key group to protected distribution behaviors,
prove member and approved-guest sign-in, deny an unassigned user, and deny a
wrong-tenant token. Prove real KMS signing and CloudFront cookie validation,
short expiry, silent refresh, installer download, signed feed and bundle checks,
runtime download, model-catalogue refresh, and rollback recovery. Check every
affected path and preserve the existing stable or beta channel.

Removing a role prevents new cookie issuance after the new token reflects that
change. An issued cookie remains usable until its expiry, at most ten minutes.
The status call reports cached local readiness only. It does not verify current
entitlement or prove an end-to-end update.
