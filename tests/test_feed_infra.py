"""Feed infrastructure contracts (Plan 139): templates and publish workflow.

No network and no YAML dependency: the templates are read as text, because
what these tests pin is a small set of load-bearing lines whose removal
would only show up on a live release. The feed is public, so these tests
also pin the absence of an edge gate and of any token plumbing in the
publish workflow.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED_TEMPLATE = ROOT / 'infra' / 'feed.yaml'
RELEASE_WORKFLOW = ROOT / '.github' / 'workflows' / 'release.yml'


def _template():
    return FEED_TEMPLATE.read_text()


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
        self.assertNotIn('feed-latest.json', text)

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
        self.assertNotIn('ssm:GetParameter', text)

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
