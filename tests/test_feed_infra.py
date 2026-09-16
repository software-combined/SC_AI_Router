"""Feed infrastructure contracts (Plan 139): templates and publish workflow.

No network and no YAML dependency: the templates are read as text, because
what these tests pin is a small set of load-bearing lines whose removal
would only show up on a live release. The feed is public, so these tests
also pin the absence of an edge gate and of any token plumbing in the
publish workflow.
"""
import unittest
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
FEED_TEMPLATE = ROOT / 'infra' / 'feed.yaml'
RELEASE_WORKFLOW = ROOT / '.github' / 'workflows' / 'release.yml'


def _template():
    return FEED_TEMPLATE.read_text()


def _input_template():
    """The EventBridge InputTemplate body, unindented."""
    lines = _template().splitlines()
    start = next(i for i, line in enumerate(lines) if 'InputTemplate: |' in line)
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for line in lines[start + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line.strip())
    return '\n'.join(body).strip()


class PublicFeedTemplateTests(unittest.TestCase):
    def test_no_edge_gate_or_token_store(self):
        text = _template()
        for needle in ('FunctionAssociations', 'GateFunction', 'TokenStore',
                       'KeyValueStore', 'X-SCG-Feed-Token', 'current-token',
                       'ssm:GetParameter', 'kms:Decrypt'):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, text)

    def test_distribution_serves_the_private_bucket_publicly(self):
        text = _template()
        self.assertIn('DefaultCacheBehavior:', text)
        self.assertIn('TargetOriginId: feed-bucket', text)
        self.assertIn('ViewerProtocolPolicy: redirect-to-https', text)
        self.assertIn('OriginAccessControlId: !GetAtt FeedOriginAccessControl.Id', text)


class PublishWorkflowTests(unittest.TestCase):
    def test_release_assets_use_the_release_document(self):
        text = RELEASE_WORKFLOW.read_text()
        # Both channels publish the release document, never the feed copy:
        # the release copy keeps the GitHub URL; the feed copy points at the
        # feed origin and belongs only to the feed.
        self.assertIn('cp dist/release-latest.json dist/latest.json', text)
        self.assertIn('cp dist/release-latest.json dist/latest-beta.json', text)
        # The release ships the release document plus the detached feed
        # signature (Plan 145); the feed copy itself never becomes an asset.
        self.assertNotIn('dist/feed-latest.json ', text)
        self.assertNotIn('dist/feed-latest.json"', text)

    def test_no_token_switch_remains_in_the_workflow(self):
        text = RELEASE_WORKFLOW.read_text()
        self.assertNotIn('ROUTER_FEED_EMBED_TOKEN', text)
        self.assertNotIn('current-token', text)

    def test_feed_publish_precedes_the_github_release(self):
        text = RELEASE_WORKFLOW.read_text()
        publish = text.index('publish_feed.py')
        release = text.index('gh release create')
        self.assertLess(publish, release,
                        'the feed must serve before a host is told about it')

    def test_the_workflow_requires_the_feed_variables(self):
        # Plan 160: an empty variable must fail before a role is assumed, so a
        # fork or a misconfigured repository cannot publish to our bucket.
        text = RELEASE_WORKFLOW.read_text()
        self.assertIn('Require the feed variables', text)
        guard = text.index('Require the feed variables')
        credentials = text.index('configure-aws-credentials')
        self.assertLess(guard, credentials, 'the guard must run before assuming the role')
        for name in ('FEED_BUCKET', 'FEED_ROLE', 'FEED_SIGNING_SEED_ARN'):
            self.assertIn(name, text[guard:credentials], name)

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
        self.assertIn('software-combined@200868195/SC_Unlimited_ai@1360169840', _template())
        self.assertIn('${ImmutableSubjectPrefix}:ref:refs/tags/v*', _template())
        # Plan 145: the publisher may read exactly one secret, the signing
        # seed, and nothing else.
        self.assertIn('secretsmanager:GetSecretValue', _template())
        self.assertIn('SigningSeedArn', _template())
        self.assertNotIn('secretsmanager:*', _template())
        self.assertNotIn('Resource: \'*\'', _template())
        text = RELEASE_WORKFLOW.read_text()
        self.assertIn('--sign', text)
        self.assertIn('latest.json.sig', text)


class TemplateGuardTests(unittest.TestCase):
    def test_publish_email_is_a_short_readable_message(self):
        """The alarm is for a person: the raw S3 envelope is not (Plan 167)."""
        text = _template()
        self.assertIn('InputTransformer:', text)
        self.assertIn('one email per bundle', text.lower())
        for path in ('$.detail.object.size', '$.detail.object.version-id', '$.time',
                     '$.detail.reason'):
            with self.subTest(path=path):
                self.assertIn(path, text)

    def test_message_substitutes_no_value_a_writer_controls(self):
        """A crafted key would break the JSON template and silence the alarm.

        EventBridge substitutes raw, so quoting the object key into the
        template lets the actor this alert watches suppress its own email by
        writing a key that carries a double quote.
        """
        lines = _template().splitlines()
        start = next(i for i, line in enumerate(lines) if 'InputPathsMap:' in line)
        paths = []
        for line in lines[start + 1:]:
            if line.strip() and len(line) - len(line.lstrip()) <= 12:
                break
            if ':' in line:
                paths.append(line.split(':', 1)[1].strip())
        self.assertNotIn('$.detail.object.key', paths)
        self.assertTrue(paths, 'the transformer maps no input paths')

    def test_message_template_survives_substitution_as_json(self):
        """EventBridge needs valid JSON, so a broken template fails silently.

        A person would simply stop receiving the alarm, which is the failure
        this test exists to prevent.
        """
        # Account-shaped values would trip the Plan 160 identifier scan; the
        # substitution check needs a shape, not a real account.
        sample = {'<size>': '514300', '<bucket>': 'scg-router-feed-apse2',
                  '<time>': '2026-09-16T23:25:31Z', '<reason>': 'PutObject',
                  '<requester>': 'publishing-account', '<version>': 'version-id'}
        body = _input_template()
        self.assertEqual(sorted(re.findall(r'<[a-z]+>', body)), sorted(sample))
        for token, value in sample.items():
            body = body.replace(token, value)
        message = json.loads(body)
        for expected in ('514300 bytes', 'version-id', 'PutObject',
                         'without going through the publisher'):
            with self.subTest(expected=expected):
                self.assertIn(expected, message)

    def test_bucket_is_private_and_retained(self):
        text = _template()
        self.assertIn('DeletionPolicy: Retain', text)
        self.assertIn('BlockPublicAcls: true', text)
        self.assertIn('RestrictPublicBuckets: true', text)

    def test_publisher_role_cannot_write_tokens_or_delete(self):
        text = _template()
        policy = text.split('Policies:', 1)[1] if 'Policies:' in text else ''
        self.assertTrue(policy, 'the publisher role carries no inline policy')
        # No Allow grants a delete; a Deny may list one (Plan 167).
        allow = policy.split('Effect: Deny', 1)[0]
        self.assertNotIn('s3:DeleteObject', allow)
        self.assertIn('Effect: Deny', policy, 'the delete deny is missing')
        self.assertNotIn('cloudfront-keyvaluestore', text)
        self.assertNotIn('ssm:PutParameter', text)
        self.assertNotIn('ssm:GetParameter', text)

    def test_publisher_role_can_see_whether_a_bundle_exists(self):
        """Absent-key HeadObject returns 404 only with s3:ListBucket.

        The publisher treats only an explicit 404 as absent, so without
        this grant every first publish would abort as unreadable.
        """
        policy = _template().split('Policies:', 1)[1]
        self.assertIn('s3:ListBucket', policy)
        self.assertIn('Resource: !GetAtt FeedBucket.Arn', policy)

    def test_the_role_can_write_every_key_the_publisher_writes(self):
        """The Allow list must cover `publish_feed.main`'s writes (Plan 167).

        A missing key fails AccessDenied halfway through a release, after the
        bundle and channel document are already published, so the key set is
        enumerated here rather than trusted. Update this list with the
        publisher.
        """
        policy = _template().split('PolicyName: publish-router-feed', 1)[1]
        allow = policy.split('Effect: Deny', 1)[0]
        for key in ('bundles/', 'stable/latest.json', 'stable/latest.json.sig',
                    'stable/models.json', 'beta/latest.json',
                    'beta/latest.json.sig', 'beta/models.json'):
            with self.subTest(key=key):
                self.assertIn(f'${{FeedBucket.Arn}}/{key}', allow)

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
