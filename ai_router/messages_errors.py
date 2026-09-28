"""Messages wire rendering of shared outcomes; no retry decisions or content."""
from . import errors, outcome


class MessagesError(errors.RouterError):
    def __init__(self, error, native_type):
        super().__init__(error.status, error.code, error.message, error.detail)
        self.native_type = native_type

    def body(self):
        return {'type': 'error', 'error': {
            'type': self.native_type, 'message': self.message, 'code': self.code}}


def render(error):
    """Keep the router's status and safe catalog prose in a native envelope."""
    if isinstance(error, MessagesError):
        return error
    native = {401: 'authentication_error', 403: 'permission_error',
              429: 'rate_limit_error', 529: 'overloaded_error'}.get(error.status)
    return MessagesError(error, native or ('api_error' if error.status >= 500
                                          else 'invalid_request_error'))


def from_outcome(settled, status, rate_message=None, credit_message=None, subscription=False):
    """An HTTP failure's shared category owns its status and user explanation."""
    if settled.category == outcome.TRANSIENT:
        error = errors.upstream_unavailable('The model is temporarily unavailable. Retry shortly.')
        error.status = status if status >= 500 else 500
        native = {'timeout_error': 'timeout_error',
                  'overloaded_error': 'overloaded_error'}.get(settled.code, 'api_error')
        return MessagesError(error, native)
    if settled.category == outcome.CONTEXT_OVERFLOW:
        return render(errors.context_window())
    if settled.category == outcome.REFUSED:
        return render(errors.upstream_invalid_prompt())
    if settled.category == outcome.QUOTA and not subscription:
        return render(errors.key_no_credit(credit_message or
                      'The model account has no remaining credit. Contact IT, then retry.'))
    if settled.category == outcome.AUTH:
        return render(errors.RouterError(status, 'UPSTREAM_AUTH',
                      'The model could not authorise this request. Check the account connection.'))
    if settled.category in (outcome.RATE_LIMIT, outcome.QUOTA):
        error = errors.upstream_rate_limited(rate_message or errors.upstream_rate_limited().message)
        error.status = 429
        return MessagesError(error, 'rate_limit_error')
    error = errors.upstream_failed()
    error.status = status
    return render(error)
