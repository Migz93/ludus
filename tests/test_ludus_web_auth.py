"""Exercise the real HTTP handler without PAM, root, or host configuration."""
import concurrent.futures
import hashlib
import http.client
import importlib.util
import json
import pathlib
import threading
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('web_auth', pathlib.Path(__file__).parents[1] / 'src/ludus-web.py')
W = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(W)


class WebAuthTest(unittest.TestCase):
    def setUp(self):
        self.config = {'auth_mode': 'local', 'username': 'admin',
                       'password_sha256': hashlib.sha256(b'secret').hexdigest()}
        W.SESSIONS.clear()
        W.PAM_FAILURES.clear()
        self.cfg = mock.patch.object(W, 'cfg', side_effect=lambda: dict(self.config))
        self.backend = mock.patch.object(W, 'call', return_value={'ok': True, 'output': ''})
        self.cfg.start()
        self.call = self.backend.start()
        self.server = W.ThreadingHTTPServer(('127.0.0.1', 0), W.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = '127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.backend.stop()
        self.cfg.stop()

    def request(self, path, body=None, cookie=None, csrf=None, headers=None):
        request_headers = dict(headers or {})
        if cookie: request_headers['Cookie'] = cookie
        if csrf: request_headers['X-Ludus-CSRF'] = csrf
        if body is not None: request_headers.setdefault('Content-Type', 'application/json')
        connection = http.client.HTTPConnection(self.host, timeout=3)
        connection.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, request_headers)
        response = connection.getresponse()
        payload = response.read().decode()
        result = response.status, dict(response.getheaders()), payload
        connection.close()
        return result

    def login(self, **kwargs):
        status, headers, body = self.request('/api/auth/login', {'username': 'admin', 'password': 'secret'}, **kwargs)
        self.assertEqual(status, 200, body)
        self.assertNotIn('secret', headers['Set-Cookie'])
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        return headers['Set-Cookie'].split(';', 1)[0], json.loads(body)['csrf']

    def test_public_page_does_not_challenge_and_apis_remain_private(self):
        status, headers, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn('id="login-form"', body)
        self.assertIn('Content-Security-Policy', headers)
        for path in ('/api/auth/session', '/api/settings', '/api/games/1/poster'):
            status, headers, _ = self.request(path)
            self.assertEqual(status, 401)
            self.assertNotIn('WWW-Authenticate', headers)
        self.assertEqual(self.request('/api/repair', {})[0], 401)
        self.call.assert_not_called()

    def test_session_reads_parallel_requests_and_logout(self):
        cookie, csrf = self.login()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(lambda _: self.request('/api/status', cookie=cookie)[0], range(6)))
        self.assertEqual(statuses, [200] * 6)
        self.assertEqual(json.loads(self.request('/api/auth/session', cookie=cookie)[2])['csrf'], csrf)
        status, headers, _ = self.request('/api/auth/logout', {}, cookie, csrf)
        self.assertEqual(status, 200)
        self.assertIn('Max-Age=0', headers['Set-Cookie'])
        self.assertEqual(self.request('/api/status', cookie=cookie)[0], 401)

    def test_mutations_require_csrf_and_same_origin(self):
        cookie, csrf = self.login()
        self.assertEqual(self.request('/api/repair', {}, cookie)[0], 403)
        self.assertEqual(self.request('/api/repair', {}, cookie, 'wrong')[0], 403)
        self.assertEqual(self.request('/api/repair', {}, cookie, csrf, {'Origin': 'http://other.example'})[0], 403)
        self.call.assert_not_called()
        self.assertEqual(self.request('/api/repair', {}, cookie, csrf, {'Origin': 'http://' + self.host})[0], 200)
        self.call.assert_called_once_with('repair', {})

    def test_login_rejects_cross_origin_and_non_json(self):
        credentials = {'username': 'admin', 'password': 'secret'}
        for origin in ('null', 'http://evil.example', 'http://['):
            self.assertEqual(self.request('/api/auth/login', credentials, headers={'Origin': origin})[0], 403)
        self.assertEqual(self.request('/api/auth/login', credentials, headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.request('/api/auth/login', credentials, headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertFalse(W.SESSIONS)

    def test_bad_credentials_and_retry_limit(self):
        credentials = {'username': 'admin', 'password': 'wrong'}
        self.assertEqual(self.request('/api/auth/login', credentials)[0], 401)
        self.assertEqual(self.request('/api/auth/login', credentials)[0], 429)
        self.assertFalse(W.SESSIONS)

    def test_invalid_credentials_types(self):
        for body in ({}, {'username': [], 'password': 'x'}, {'username': 'admin', 'password': ''}):
            self.assertEqual(self.request('/api/auth/login', body)[0], 400)

    def test_idle_expiry_and_policy_changes_revoke_sessions(self):
        cookie, _ = self.login()
        token = cookie.split('=', 1)[1]
        with mock.patch.object(W.time, 'monotonic', return_value=W.SESSIONS[token]['expires'] - 1):
            self.assertEqual(self.request('/api/status', cookie=cookie)[0], 200)
        with mock.patch.object(W.time, 'monotonic', return_value=W.SESSIONS[token]['expires'] + 1):
            self.assertEqual(self.request('/api/status', cookie=cookie)[0], 401)
        for key, value in (('password_sha256', 'changed'), ('auth_mode', 'pam')):
            cookie, _ = self.login()
            original = self.config[key]
            self.config[key] = value
            self.assertEqual(self.request('/api/status', cookie=cookie)[0], 401)
            self.config[key] = original

    def test_pam_and_combined_modes_keep_backend_validation(self):
        for mode in ('pam', 'pam+local'):
            self.config['auth_mode'] = mode
            self.config['username'] = 'other-local-user'
            self.call.reset_mock()
            self.login()
            self.call.assert_called_once_with('webui.pam_auth', {'username': 'admin', 'password': 'secret'})

    def test_combined_local_login_does_not_call_pam(self):
        self.config['auth_mode'] = 'pam+local'
        self.login()
        self.call.assert_not_called()

    def test_pam_failure_does_not_create_session(self):
        self.config['auth_mode'] = 'pam'
        self.call.return_value = {'ok': False}
        self.assertEqual(self.request('/api/auth/login', {'username': 'admin', 'password': 'secret'})[0], 401)
        self.assertFalse(W.SESSIONS)

    def test_disabled_authentication_opens_without_cookie(self):
        self.config['auth_mode'] = 'none'
        self.assertEqual(self.request('/api/status')[0], 200)
        self.assertFalse(json.loads(self.request('/api/auth/session')[2])['required'])
        self.assertEqual(self.request('/api/repair', {})[0], 200)
        self.assertEqual(self.request('/api/repair', {}, headers={'Origin': 'http://evil.example'})[0], 403)

    def test_https_origin_sets_secure_cookie_and_relogin_rotates_token(self):
        cookie, _ = self.login(headers={'Origin': 'https://' + self.host})
        status, headers, _ = self.request('/api/auth/login', {'username': 'admin', 'password': 'secret'}, cookie=cookie,
                                          headers={'Origin': 'https://' + self.host})
        self.assertEqual(status, 200)
        self.assertIn('; Secure', headers['Set-Cookie'])
        self.assertNotEqual(cookie, headers['Set-Cookie'].split(';', 1)[0])
        self.assertEqual(self.request('/api/status', cookie=cookie)[0], 401)


if __name__ == '__main__':
    unittest.main()
