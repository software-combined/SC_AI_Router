# Publication boundary and release procedure

The router is independent SC software. Provider documentation describes
gateway integrations; it does not approve every router feature or every
user's subscription agreement. Release approval must name the actual
integration scope, supported clients and permitted data flows.

## Authentication and data destinations

Native Codex traffic carries the signed-in official client's headers to
OpenAI. Native Claude Messages traffic carries the official client's headers
to Anthropic. Native routes may add router-authored instructions and recovery
guidance while retaining the client's own credentials. The runtime does not
collect native subscription tokens from
credential files, create a shared login pool or rotate credentials after a
usage refusal. The installer inspects whether a Codex login exists to select
a mode, without extracting or copying its token. No client binary is patched.

Separately billed routes construct fresh headers using the user's local API
key. Subscription authentication is never sent to an external provider.
Model selection may send existing conversation history and tool results to
that provider. Get the information owner's permission before routing company
or customer material elsewhere. Local Claude profile task copies retain
conversation contents, including any secrets pasted into the conversation;
they are private working data, never support or publication artifacts.

The service listens on loopback and authenticates access with a per-install
path token. Provider key files have restricted permissions. Routing logs
contain metadata, not prompts, tool contents or credentials. Support requests
use the redacted support export. These controls are source behavior and
offline test evidence, not a penetration-test certification.

Paid title/summary helper fallback is off unless `openai_helper_fallback` is
explicitly `true`. Enabling it sends eligible helper prompts to the external
route and bills its key. Experimental external compaction is a separate
opt-in with its own history disclosure. Switch Codex selects a separately
billed profile; it does not extend a subscription entitlement.

## Provider and client support

Claude gateway discovery uses real vendor IDs. Only actual Claude rows have
Claude family metadata. The installer adds public gateway settings and never
sets the internal first-party override. An old installer-owned override is
removed using its receipt; hand-managed conflicts are preserved and refused.
Older disguised aliases are refused locally. A saved session using one must
choose a truthful ID in a new session.

Anthropic's [gateway guide](https://code.claude.com/docs/en/llm-gateway)
describes saved-client OAuth forwarding when only the base URL changes, and
states that Claude Code routing to non-Claude models is unsupported.
Non-Claude Messages compatibility therefore carries no Claude Code support
claim and may be hidden or rejected by the stock client. Changes to deferred
tool loading and desktop discovery need fresh client verification.
See its [legal and compliance guide](https://code.claude.com/docs/en/legal-and-compliance).

OpenAI documents [signed-in client gateway routing](https://learn.chatgpt.com/docs/enterprise/sign-in-with-chatgpt-through-a-gateway).
That official-client passthrough differs from an independent application
implementing [Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source).
The router does not claim to be a registered independent OAuth application.
Mixed-model history projection remains router behavior requiring compatibility
review, rather than automatic contractual clearance. Bedrock adapters remain
optional preview features and have no new stable support claim.

## Source, notices and public history

The application is Apache-2.0, with the attributed opencodex material under
MIT. Replacement router prompts are independently authored. Replay fixtures
use synthetic instruction prose; future captures hash native instruction
text. Read [provenance](PROVENANCE.md) and [third-party notices](../THIRD_PARTY_NOTICES.md).
The application declares no third-party Python dependencies. Bootstrap
CPython archives are separate distributions whose hashes and component
notices must be verified and retained for every platform.

Use `tools/export_public_source.py --out <new-directory>` from the reviewed
cleanup checkout after staging the intended paths. It exports current tracked
bytes, an inventory and an archive. It refuses private paths, symlinks and
overwriting an existing export. It includes no Git objects, branches, tags,
ignored working files or historical commits. Scan that snapshot, run its
offline tests and build the end-user package from those exact bytes.

Publication keeps `software-combined/SC_AI_Router` and its existing URL.
Before rewriting history, preserve a private mirror of every branch and tag
and verified copies of the release assets. Integrate the cleaned source
through reviewed pull requests and the normal release checks first.

Rewrite the affected historical prompt and fixture content in an isolated
copy. Keep the accepted current source bytes unchanged. Scan every rewritten
branch and tag, verify the retained unmerged work, then update the exact
reviewed refs with explicit leases. Never push a mirror over unknown refs.
Restore branch protection and publisher workflow state immediately. Publish
only after the rewritten main commit passes its required checks.

History rewriting does not remove old clones, GitHub pull-request refs or
cached views. Record those limits and the old-to-new commit map. Withdraw
affected downloadable archives after a clean successor is available.
Deployment retains this repository and its established publisher role;
public forks receive no publishing grants or copied repository variables.

Application release bundles include operator helpers but exclude developer
probes, capture tools, benchmarks and publishing scripts.

## Existing distribution and release decisions

The public 1.0.19.165 and 1.0.21.169 archives contain the old prompt and
developer tools. Their verified SHA-256 values are, respectively,
`9a3a3ffb6f57bb8919dd34de272a321f59f11b31bd08ad1dfd228273c965a937` and
`c78d4716d7c917f940652e122699871b509c08c8fe9718df7ce9aefe7099138b`.
Removing material from this candidate does not remove that download, other
old archives, cached copies or historical disclosures.

Before publishing, preserve the private archive record and prepare a
successor bundle, source companion and signed feed. Verify the successor
before withdrawing affected older downloads, retiring their feed references
and clearing caches. Keep verified private copies for rollback and reference.
Publishing a successor does not remove older affected downloads.
Historical infrastructure identifiers are not confirmed credentials; a
rotation decision needs evidence that an actual secret was exposed.

Approval also covers provider scope, runtime component licences, SC brand
use and public security/support ownership. External users have no support
service level. Local tests cannot establish provider approval, model quality
or live provider acceptance. `docs/compatibility.md` records fresh installed-client
checks against local synthetic upstreams, with external network access
blocked. Native OAuth and paid provider acceptance still require separately
authorized live checks before a production support claim. Windows runtime
redistribution follows the Visual C++ runtime basis recorded in `runtime-licenses.md`.
See repository verification and review gates before committing or integrating
the candidate.
