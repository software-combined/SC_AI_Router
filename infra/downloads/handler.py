"""Exchange API Gateway-verified Entra staff claims for scoped CloudFront cookies.

JWT verification belongs to API Gateway. This handler accepts claims only from
its authorizer context and requires the resource tenant's Download app role.
"""
import base64
import json
import os
import time
import uuid

DISTRIBUTION_ORIGIN = 'https://dist.softwarecombined.com'
REQUIRED_SCOPE = 'Download.Read'
REQUIRED_ROLE = 'Download'
_kms = None


def _client():
    global _kms
    if _kms is None:
        # Lambda supplies boto3; the installed router never imports this module.
        import boto3
        from botocore.config import Config
        _kms = boto3.client('kms', config=Config(
            connect_timeout=3, read_timeout=5,
            retries={'total_max_attempts': 2, 'mode': 'standard'}))
    return _kms


def _roles(value):
    if isinstance(value, str):
        if value == REQUIRED_ROLE:
            return [value]
        try:
            value = json.loads(value)
        except ValueError:
            # HTTP API JWT authorizers render array claims as [Role, Other].
            if not (value.startswith('[') and value.endswith(']')):
                return []
            value = [role.strip() for role in value[1:-1].split(',')]
    return value if isinstance(value, list) else []


def entitled(event, settings, now):
    """Staff and assigned guests share one explicit resource-tenant entitlement."""
    try:
        context = event['requestContext']
        claims = context['authorizer']['jwt']['claims']
        if (event.get('routeKey') != 'POST /download-access'
                or context['http']['method'] != 'POST'
                or claims['tid'] != settings['TENANT_ID']
                or claims['iss'] != 'https://login.microsoftonline.com/' + settings['TENANT_ID'] + '/v2.0'
                or claims['aud'] != settings['API_CLIENT_ID']
                or claims.get('azp') != settings['NATIVE_CLIENT_ID']
                or claims.get('ver') != '2.0'
                or REQUIRED_SCOPE not in claims.get('scp', '').split()
                or REQUIRED_ROLE not in _roles(claims.get('roles'))
                or int(claims['exp']) <= now + 30
                or int(claims['nbf']) > now
                or int(claims['iat']) > now):
            return False
        # oid identifies the user object in this resource tenant, also for guests.
        return str(uuid.UUID(claims['oid'])) == claims['oid']
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def _encode(data):
    return base64.b64encode(data).decode('ascii').translate(str.maketrans('+=/', '-_~'))


def cookies(settings, expires_at):
    policy = json.dumps({'Statement': [{'Resource': DISTRIBUTION_ORIGIN + '/*',
            'Condition': {'DateLessThan': {'AWS:EpochTime': expires_at}}}]},
            separators=(',', ':')).encode('utf-8')
    signed = _client().sign(KeyId=settings['SIGNING_KEY_ARN'], Message=policy,
                            MessageType='RAW', SigningAlgorithm='ECDSA_SHA_256')
    # KMS supplies the DER ECDSA signature; CloudFront uses the standard encoding.
    return {'CloudFront-Policy': _encode(policy),
            'CloudFront-Signature': _encode(signed['Signature']),
            'CloudFront-Key-Pair-Id': settings['PUBLIC_KEY_ID'],
            'CloudFront-Hash-Algorithm': 'SHA256'}


def _response(status, body, browser_cookies=None):
    response = {'statusCode': status, 'headers': {
        'Content-Type': 'application/json', 'Cache-Control': 'no-store',
        'Pragma': 'no-cache'}, 'body': json.dumps(body, separators=(',', ':'))}
    if browser_cookies is not None:
        response['cookies'] = browser_cookies
    return response


def handler(event, _context):
    """No event, token, cookie or personal claim is written to logs."""
    now = int(time.time())
    settings = os.environ
    if not entitled(event, settings, now):
        return _response(403, {'error': 'download_access_denied'})
    try:
        expiry = min(now + 600, int(event['requestContext']['authorizer']['jwt']['claims']['exp']))
        result = cookies(settings, expiry)
    except Exception:
        # This external boundary deliberately returns a fixed error, with no SDK
        # exception or request payload escaping into Lambda's automatic logs.
        return _response(503, {'error': 'download_access_unavailable'})
    remaining = max(0, min(600, expiry - int(time.time())))
    if not remaining:
        return _response(403, {'error': 'download_access_denied'})
    browser_cookies = [name + '=' + value
                       + '; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=' + str(remaining)
                       for name, value in result.items()]
    return _response(200, {'expires_at': expiry, 'cookies': result}, browser_cookies)
