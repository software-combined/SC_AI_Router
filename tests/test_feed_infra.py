"""Feed infrastructure contracts (Plan 139): templates and publish workflow.

No network and no YAML dependency: the templates are read as text, because
what these tests pin is a small set of load-bearing lines whose removal
would only show up on a live release. The feed is public, so these tests
also pin the absence of an edge gate and of any token plumbing in the
publish workflow.
"""
import unittest
from copy import deepcopy
from pathlib import Path
import os
import sys
import types
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FEED_TEMPLATE = ROOT / 'infra' / 'feed.yaml'
RELEASE_WORKFLOW = ROOT / '.github' / 'workflows' / 'release.yml'


def _template():
    return FEED_TEMPLATE.read_text()


def _inline_code():
    """The formatter's ZipFile source, unindented."""
    lines = _template().splitlines()
    start = next(i for i, line in enumerate(lines) if 'ZipFile: |' in line)
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for line in lines[start + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line[indent + 2:] if line.strip() else '')
    return '\n'.join(body) + '\n'


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
        self.assertIn('software-combined@200868195/SC_AI_Router@1360169840', _template())
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
    BODY = {'detail': {'bucket': {'name': 'the-feed-bucket'},
                       'object': {'key': 'bundles/ai-router-0.6.80.78.tar.gz',
                                  'size': 514300, 'version-id': 'version-id'},
                       'reason': 'PutObject', 'requester': 'an-account'},
            'time': '2026-09-16T23:25:31Z'}

    def _handler(self, published):
        """Exec the formatter's inline source against a stubbed SNS client.

        The stub enforces the documented SNS subject contract, so a subject
        the service would reject fails here instead of silently silencing the
        alert in production.
        """
        code = _inline_code()
        compile(code, 'feed-alert-inline', 'exec')
        stub = types.ModuleType('boto3')

        def publish(**kwargs):
            subject = kwargs['Subject']
            assert len(subject) < 100, 'SNS caps subjects under 100 characters'
            assert subject.isascii() and all(32 <= ord(c) < 127 for c in subject), \
                'SNS rejects line breaks and control characters in a subject'
            published.append(kwargs)

        stub.client = lambda name, **kw: types.SimpleNamespace(publish=publish)
        namespace = {}
        with mock.patch.dict(sys.modules, {'boto3': stub}), \
                mock.patch.dict(os.environ, {'TOPIC_ARN': 'topic-arn'}):
            exec(code, namespace)
        return namespace['handler']

    def test_rule_invokes_the_formatter_not_the_topic(self):
        """The rule drives the function; the old SNS target is gone (Plan 167)."""
        text = _template()
        self.assertIn('!GetAtt FeedAlertFunction.Arn', text)
        self.assertNotIn('InputTransformer', text)
        self.assertNotIn('FeedPublishTopicPolicy', text)
        self.assertIn('Principal: events.amazonaws.com', text)
        self.assertIn('SourceArn: !GetAtt FeedPublishRule.Arn', text)

    def test_formatter_role_can_only_publish_to_the_topic(self):
        policy = _template().split('publish-feed-alert', 1)[1]
        self.assertIn('Action: sns:Publish', policy)
        self.assertIn('Resource: !Ref FeedPublishTopic', policy)
        self.assertNotIn('Resource: \'*\'', policy)

    def test_handler_mails_a_readable_message(self):
        published = []
        self._handler(published)(self.BODY, None)
        self.assertEqual(len(published), 1)
        sent = published[0]
        self.assertEqual(sent['TopicArn'], 'topic-arn')
        self.assertIn('bundles/ai-router-0.6.80.78.tar.gz', sent['Subject'])
        for expected in ('bundles/ai-router-0.6.80.78.tar.gz', '514300 bytes',
                         'version-id', '2026-09-16T23:25:31Z', 'PutObject',
                         'without going through the publisher'):
            with self.subTest(expected=expected):
                self.assertIn(expected, sent['Message'])

    def test_handler_mails_a_hostile_key_instead_of_dropping_it(self):
        """A crafted key must not silence the alarm this exists to raise.

        An EventBridge InputTemplate substitutes raw, so a quoting formatter
        upstream of it could be broken by the writer it watches; code quotes
        the key as one printable line and sends regardless: a key with a line
        break, a 1008-character key and a non-ASCII key all still mail.
        """
        hostile = ('bundles/evil".tar.gz\nsecond line',
                   'bundles/' + 'x' * 1000 + '.tar.gz',
                   'bundles/héllo\x00world.tar.gz')
        for key in hostile:
            with self.subTest(key=key[:40]):
                published = []
                event = deepcopy(self.BODY)
                event['detail']['object']['key'] = key
                self._handler(published)(event, None)
                self.assertEqual(len(published), 1)
                subject = published[0]['Subject']
                self.assertLess(len(subject), 100)
                message = published[0]['Message']
                # One line per field: a key that carries newlines must not be
                # able to forge a second Version: or Time: line.
                for label in ('Object:', 'Size:', 'Version:', 'Time:', 'By:'):
                    with self.subTest(label=label):
                        self.assertEqual(
                            sum(line.startswith(label) for line in message.splitlines()), 1)
                object_line = next(line for line in message.splitlines()
                                   if line.startswith('Object:'))
                self.assertTrue(object_line.isascii())
                self.assertIn('bundles/', object_line)
                self.assertIn('without going through the publisher', message)

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
