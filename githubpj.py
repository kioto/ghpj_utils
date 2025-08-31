"""GitHub Project
"""
import sys
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_HTTP_PROXY = ''         # HTTPプロキシ
DEFAULT_HTTPS_PROXY = ''        # HTTPSプロキシ
DEFAULT_VERIFY = ''             # SSL検証
DEFAULT_TIMEOUT = 30            # リクエストタイムアウト
DEFAULT_MAX_RETRIES = 5         # 再試行回数
DEFAULT_BACKOFF_FACTOR = 0.5    # 指数バックオフ係数
DEFAULT_PER_PAGE = 100

# API_SUFFIX = '/api/v3'
API_SUFFIX = ''


class GitHubPj:

    def __init__(self, config):
        self._config = config
        self._session = self._build_session()

    def _build_session(self):
        # パラメータ設定
        _net = self._config['network']
        token = _net.get('token')
        http_proxy = _net.get('http_proxy')
        if not http_proxy:
            http_proxy = DEFAULT_HTTP_PROXY
        https_proxy = _net.get('https_proxy')
        if not https_proxy:
            https_proxy = DEFAULT_HTTPS_PROXY

        verify = DEFAULT_VERIFY
        backoff_factor = DEFAULT_BACKOFF_FACTOR
        max_retries = DEFAULT_MAX_RETRIES
        timeout = DEFAULT_TIMEOUT

        # セッション作成
        s = requests.Session()
        s.headers.update({
            'Accept': 'application/vnd.github+json',
            'Authorization': f'token {token}',
            'User-Agent': 'ghes-issue-exporter/1.0'
        })

        # プロキシ設定（引数優先。未指定なら環境変数 HTTP(S)_PROXY が使われます）
        proxies = {}
        if http_proxy:
            proxies['http'] = http_proxy
        if https_proxy:
            proxies['https'] = https_proxy
        if proxies:
            s.proxies.update(proxies)

        # SSL検証（True/False/CAパス）
        s.verify = True
        if verify is not None:
            if verify.lower() in ('false', '0', 'no'):
                s.verify = False
            else:
                s.verify = verify  # CA バンドルパス

        # 再試行（5xx, 一部の 429/403 レート制限も考慮）
        retry = Retry(
            total=max_retries,
            read=max_retries,
            connect=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(['GET', 'HEAD', 'OPTIONS']),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount('https://', adapter)
        s.mount('http://', adapter)

        # デフォルトタイムアウトを保持
        s.request = self._with_timeout(s.request, timeout)
        return s

    def _with_timeout(self, request_func, timeout_default):
        def wrapper(method, url, **kwargs):
            if "timeout" not in kwargs:
                kwargs["timeout"] = timeout_default
            return request_func(method, url, **kwargs)
        return wrapper

    def get_issues(self):
        """issueの取り出し
        """
        issues = []
        try:
            issues = list(self._fetch_issues())
        except Exception as e:
            print(f"Failed to fetch issues: {e}", file=sys.stderr)
            sys.exit(1)

        return issues

    def _fetch_issues(self):
        """
        GitHub REST API: GET /repos/{owner}/{repo}/issues
        PR も混在するため、必要なら 'pull_request' キー有無でフィルタ可能
        """
        # パラメータ設定
        _net = self._config['network']
        owner = _net.get('owner')
        base_url = _net.get('url')
        _proj = self._config['origin-project']
        repo = _proj.get('repogitory')

        #
        url = self._gh_api_url(base_url, f'/repos/{owner}/{repo}/issues')
        #url = 'https://api.github.com/repos/kioto/space-sample/issues'
        print(url)
        params = {
            'state': 'all',            # open, closed, all
            'per_page': max(1, min(DEFAULT_PER_PAGE, 100)),
            'direction': 'desc',
            'sort': 'updated'
        }

        total = 0
        while url:
            resp = self._session.get(url, params=params)
            if resp.status_code >= 400:
                self._rate_limit_sleep(resp)
                # もう一度だけ即時リトライ（上位のRetryもあるが、明示）
                if resp.status_code in (429, 500, 502, 503, 504):
                    resp = self._session.get(url, params=params)

            if resp.status_code >= 400:
                raise RuntimeError(
                    f'GitHub API error {resp.status_code}: {resp.text[:200]}'
                )

            items = resp.json()
            if not isinstance(items, list):
                raise RuntimeError('Unexpected API response (expected list)')

            for it in items:
                yield it
                total += 1

            links = self._parse_link_header(resp.headers.get('Link'))
            url = links.get('next')
            params = None  # 2ページ目以降はURLにクエリが含まれる

    def _gh_api_url(self, base_url, path):
        base = base_url.rstrip('/')
        if not base.endswith(API_SUFFIX):
            base = base + API_SUFFIX
        return f'{base}/{path.lstrip('/')}'

    def _rate_limit_sleep(self, resp):
        """レート制限が近い/超えた場合に待機（GHESでもGitHub互換ヘッダが返ることが多い）
        """
        try:
            remaining = int(resp.headers.get('X-RateLimit-Remaining', '1'))
            reset = int(resp.headers.get('X-RateLimit-Reset', '0'))
        except ValueError:
            return
        if remaining <= 0 and reset > 0:
            wait = max(0, reset - int(time.time())) + 1
            print(f'[info] rate limit reached. sleeping {wait}s...',
                  file=sys.stderr)
            time.sleep(wait)

    def _parse_link_header(self, link):
        """Linkヘッダから rel->url の辞書を作成
        """
        if not link:
            return {}
        parts = link.split(",")
        links = {}
        for p in parts:
            seg = p.split(";")
            if len(seg) < 2:
                continue
            url = seg[0].strip().strip("<>")
            rel = None
            for s in seg[1:]:
                s = s.strip()
                if s.startswith("rel="):
                    rel = s.split("=")[1].strip('"')
            if url and rel:
                links[rel] = url

        return links
