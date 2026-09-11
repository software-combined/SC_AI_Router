"""Feed infrastructure contracts (Plan 139): templates and publish workflow.

No network and no YAML dependency: the templates are read as text, because
what these tests pin is a small set of load-bearing lines whose removal
would only show up on a live release. The two regressions they exist for
both shipped green before review:

  * the edge gate calling an undefined `kvs` global, which denied every
    request, and
  * the release step copying the feed document (which carries the read
    token) instead of the release document, which would publish the token
    to everyone with repo read access.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED_TEMPLATE = ROOT / 'infra' / 'feed.yaml'
RELEASE_WORKFLOW = ROOT / '.github' / 'workflows' / 'release.yml'
FEED_CLIENT = ROOT / 'packaging' / 'feed.py'


def _client_token_header():
    """The client's header name, loaded the installer's way, not imported."""
    spec = importlib.util.spec_from_file_location('router_feed_client', FEED_CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FEED_TOKEN_HEADER


def _template():
    return FEED_TEMPLATE.read_text()


def _gate_code():
    """The CloudFront function body, from its resource to the next resource."""
    text = _template()
    body = text.split('FunctionCode: |', 1)
    if len(body) != 2:
        raise AssertionError('feed.yaml declares no FunctionCode')
    return body[1].split('\n  Distribution:', 1)[0]


class GateFunctionTests(unittest.TestCase):
    def test_gate_uses_the_documented_kvs_api(self):
        code = _gate_code()
        self.assertIn("import cf from 'cloudfront';", code)
        self.assertIn('const kvsHandle = cf.kvs();', code)
        self.assertIn('async function handler(event)', code)
        self.assertIn('await kvsHandle.get(token)', code)
        # A bare `kvs.get(` is the ReferenceError that denied every request.
        self.assertNotRegex(code, r'(?<!\.)\bkvs\.get\(')

    def test_gate_serves_only_an_active_token(self):
        code = _gate_code()
        self.assertIn("=== 'active'", code)
        self.assertNotRegex(code, r"!==\s*'active'")
        # One way through, and it is the active-token comparison.
        self.assertEqual(code.count('return event.request'), 1)

    def test_gate_denies_after_the_try_block(self):
        """The fallthrough matters: a non-'active' value must not be served."""
        code = _gate_code()
        flat = ' '.join(code.split())
        # Whitespace-insensitive so the assertion pins the control flow and
        # not the indentation: three denies (missing header, throw, and the
        # fallthrough for a value that is present but not 'active').
        self.assertEqual(flat.count('return deny();'), 3)
        catch = 'catch (error) { return deny(); }'
        self.assertIn(catch, flat)
        after_catch = flat.split(catch, 1)[1]
        self.assertIn('return deny();', after_catch)

    def test_gate_denies_a_missing_header_before_lookup(self):
        code = _gate_code()
        guard = code.split('try {', 1)[0]
        self.assertIn('if (!token)', guard)
        self.assertIn('return deny();', guard)

    def test_denial_status_is_an_integer(self):
        """CloudFront rejects a string statusCode as a validation error.

        The difference is operational: the updater retries once with the
        previous token on 403 and names the bootstrap remedy on a second
        403, so a malformed denial would break token rotation instead.
        """
        code = _gate_code()
        self.assertIn('statusCode: 403', code)
        self.assertNotIn("statusCode: '403'", code)

    def test_gate_is_associated_with_the_default_behaviour(self):
        text = _template()
        self.assertIn('EventType: viewer-request', text)
        self.assertIn('!GetAtt GateFunction.FunctionMetadata.FunctionARN', text)
        # Viewer-request on the only cache behaviour: bundles and channel
        # documents share it, so neither path can bypass the gate.
        self.assertEqual(text.count('FunctionAssociations:'), 1)

    def test_gate_store_is_associated_with_the_function(self):
        text = _template()
        self.assertIn('KeyValueStoreAssociations:', text)
        self.assertIn('KeyValueStoreARN: !GetAtt TokenStore.Arn', text)

    def test_gate_reads_the_header_the_client_sends(self):
        """CloudFront lowercases header names; the client owns the name.

        A rename on either side denies every feed request while the rest of
        this suite stays green, so bind the two literals here.
        """
        self.assertIn(f"['{_client_token_header().lower()}']", _gate_code())


class PublishWorkflowTests(unittest.TestCase):
    def test_release_assets_use_the_release_document(self):
        text = RELEASE_WORKFLOW.read_text()
        # Both channels publish the release document, never the feed document:
        # the feed document carries the read token, and releases are public.
        self.assertIn('cp dist/release-latest.json dist/latest.json', text)
        self.assertIn('cp dist/release-latest.json dist/latest-beta.json', text)
        # The copy is not what uploads: the workflow must never name the
        # token-bearing feed document at all, in the release step or anywhere.
        self.assertNotIn('feed-latest.json', text)

    def test_feed_publish_precedes_the_github_release(self):
        text = RELEASE_WORKFLOW.read_text()
        publish = text.index('publish_feed.py')
        release = text.index('gh release create')
        self.assertLess(publish, release,
                        'the feed must serve before a host is told about it')

    def test_publisher_is_tag_scoped_and_oidc_gated(self):
        text = RELEASE_WORKFLOW.read_text()
        self.assertIn('id-token: write', text)
        self.assertIn('aws-actions/configure-aws-credentials@', text)
        self.assertIn('role-to-assume', text)
        # Tag scope is enforced in two independent places, and both matter:
        # the workflow trigger, and the role's trust condition.
        self.assertIn("tags: ['v*']", text)
        self.assertIn('ref:refs/tags/v*', _template())
        # This repository emits GitHub's immutable OIDC subject, so the
        # classic form alone could never assume the role.
        self.assertIn('software-combined@200868195/SC_OpenRouter_adapter@1360169840', _template())
        self.assertIn('${ImmutableSubjectPrefix}:ref:refs/tags/v*', _template())

    def test_embed_switch_is_a_repository_variable(self):
        text = RELEASE_WORKFLOW.read_text()
        self.assertIn('ROUTER_FEED_EMBED_TOKEN: ${{ vars.ROUTER_FEED_EMBED_TOKEN }}', text)


class TemplateGuardTests(unittest.TestCase):
    def test_bucket_is_private_and_retained(self):
        text = _template()
        self.assertIn('DeletionPolicy: Retain', text)
        self.assertIn('BlockPublicAcls: true', text)
        self.assertIn('RestrictPublicBuckets: true', text)

    def test_publisher_role_cannot_write_tokens_or_delete(self):
        text = _template()
        policy = text.split('Policies:', 1)[1] if 'Policies:' in text else ''
        self.assertTrue(policy, 'the publisher role carries no inline policy')
        self.assertNotIn('s3:DeleteObject', text)
        self.assertNotIn('cloudfront-keyvaluestore', text)
        self.assertNotIn('ssm:PutParameter', text)

    def test_publisher_role_can_see_whether_a_bundle_exists(self):
        """Absent-key HeadObject returns 404 only with s3:ListBucket.

        The publisher treats only an explicit 404 as absent, so without
        this grant every first publish would abort as unreadable.
        """
        policy = _template().split('Policies:', 1)[1]
        self.assertIn('s3:ListBucket', policy)
        self.assertIn('Resource: !GetAtt FeedBucket.Arn', policy)

    def test_certificate_stack_uses_dns_validation(self):
        text = (ROOT / 'infra' / 'feed-cert.yaml').read_text()
        self.assertIn('ValidationMethod: DNS', text)
        self.assertIn('DomainValidationOptions:', text)
        # CloudFront only reads viewer certificates from us-east-1; the
        # template cannot enforce the region, so it states it for the operator.
        self.assertIn('us-east-1', text)

    def test_no_literal_secret_in_the_templates(self):
        for name in ('infra/feed.yaml', 'infra/feed-cert.yaml'):
            text = (ROOT / name).read_text()
            with self.subTest(template=name):
                self.assertNotRegex(text, r'[0-9a-f]{64}')
                self.assertNotIn('X-SCG-Feed-Token:', text)


if __name__ == '__main__':
    unittest.main()
