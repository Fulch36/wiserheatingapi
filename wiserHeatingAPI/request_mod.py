from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry # pylint: disable=import-error
from requests.compat import urljoin

DEFAULT_TIMEOUT = (1.5, 0.001)
DEFAULT_RETRIES = 3

class CustomSession(Session):
    def __init__(self, base_url, hub_secret, *args, **kwargs):
        self._base_url = base_url

        session_timeout = kwargs.pop('timeout', DEFAULT_TIMEOUT)
        num_retries = kwargs.pop('num_retries', DEFAULT_RETRIES)
        retry_config = Retry(
            total = num_retries,
            status_forcelist=[500, 502, 503, 504]
        )

        adapter = _CustomHTTPAdapter(timeout = session_timeout, max_retries=retry_config)
        super().__init__(*args, **kwargs)
        super().mount('http://', adapter)
        self.headers.update({'SECRET': hub_secret})
        self.hooks = {
            'response': lambda r, *args, **kwargs: r.raise_for_status()
        }

    def request(self, method, url, **kwargs):
        new_url = urljoin(self._base_url, url)
        return super().request(method, new_url, **kwargs)

class _CustomHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.pop('timeout')
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        if not 'timeout' in kwargs:
            kwargs['timeout'] = self.timeout
        return super().send(request, **kwargs)