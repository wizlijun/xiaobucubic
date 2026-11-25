"""复用 Grok CLI 的 OIDC 会话并自动续期；与 CLI 共用 auth.json.lock。

协议及锁格式参考 xai-org/grok-build 的 xai-grok-login/oidc/protocol.rs
和 manager/lock.rs。仅访问官方 auth.x.ai，不进行交互登录或模型请求。
"""
import base64
import fcntl
import json
import math
import os
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

ISSUER = 'https://auth.x.ai'
CLIENT_ID = 'b1a00492-073a-47ea-816f-4c329264a828'
OIDC_SCOPE = ISSUER + '::' + CLIENT_ID
LEGACY_SCOPE = 'https://accounts.x.ai/sign-in'
TOKEN_ENDPOINT = ISSUER + '/oauth2/token'
REFRESH_MARGIN = 300


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def default_auth_path():
    return os.environ.get('GROK_AUTH_PATH') or str(Path(os.environ.get('GROK_HOME', '~/.grok')).expanduser() / 'auth.json')


def read_credentials(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise RuntimeError('未找到 Grok 登录凭据，请先运行 `grok login`。') from None
    except (ValueError, OSError):
        raise RuntimeError('无法读取 Grok 凭据文件，请检查 --auth-file。') from None
    if isinstance(data, dict):
        for scope in (OIDC_SCOPE, LEGACY_SCOPE):
            entry = data.get(scope)
            if isinstance(entry, dict) and isinstance(entry.get('key'), str) and entry['key'].strip():
                return data, scope, entry
    raise RuntimeError('未找到 Grok 订阅账号凭据，请运行 `grok login`。')


def expires_at(entry):
    """JWT 只用于到期提示，不用未验证的 claims 授权或选择请求目标。"""
    candidates = []
    try:
        stamp = datetime.fromisoformat(entry['expires_at'].replace('Z', '+00:00'))
        candidates.append(stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).timestamp())
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
        pass
    try:
        payload = entry['key'].split('.')[1]
        value = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4))).get('exp')
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            candidates.append(value)
    except (KeyError, IndexError, AttributeError, TypeError, ValueError):
        pass
    return min(candidates) if candidates else None


@contextmanager
def refresh_lock(path):
    # 与官方 CLI 使用同一 flock 文件，不删除锁文件，防止并发消耗轮换式 refresh token。
    lock_path = path.with_name('auth.json.lock')
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'r+') as stream:
        deadline = time.monotonic() + 10
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Grok CLI 正在续期，稍后重试。') from None
                time.sleep(0.1)
        try:
            stream.seek(0)
            stream.truncate()
            stream.write('%d:%d' % (os.getpid(), time.time()))
            stream.flush()
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def refresh_tokens(entry):
    if (entry.get('oidc_issuer') != ISSUER or entry.get('oidc_client_id') != CLIENT_ID
            or entry.get('auth_mode') != 'oidc'):
        raise RuntimeError('当前 Grok 凭据不支持官方 OIDC 自动续期，请运行 `grok login` 更新登录方式。')
    if not isinstance(entry.get('refresh_token'), str) or not entry['refresh_token']:
        raise RuntimeError('Grok 凭据缺少 refresh token，请运行 `grok login`。')
    form = {'grant_type': 'refresh_token', 'client_id': CLIENT_ID, 'refresh_token': entry['refresh_token']}
    for key in ('principal_type', 'principal_id'):
        if entry.get(key):
            form[key] = entry[key]
    request = urllib.request.Request(TOKEN_ENDPOINT, data=urlencode(form).encode(), headers={
        'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json',
        'User-Agent': 'grok-usage/1.1',
    }, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read(8192))
            code = body.get('error') if isinstance(body, dict) else None
        except (ValueError, OSError):
            code = None
        if exc.code in (400, 401, 403) and code in ('invalid_grant', 'invalid_client'):
            raise RuntimeError('Grok 刷新凭据已失效或被撤销，请运行 `grok login`。') from None
        raise RuntimeError('Grok 自动续期暂时失败 (HTTP %d)，保留凭据，稍后重试。' % exc.code) from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise RuntimeError('Grok 自动续期网络错误，保留凭据，稍后重试。') from None
    except ValueError:
        raise RuntimeError('Grok 自动续期返回无效 JSON，保留凭据。') from None
    if not isinstance(result, dict) or not isinstance(result.get('access_token'), str) or not result['access_token'].strip():
        raise RuntimeError('Grok 自动续期未返回有效 access token，保留凭据。')
    updated = dict(entry, key=result['access_token'])
    if result.get('refresh_token') is not None:
        if not isinstance(result['refresh_token'], str) or not result['refresh_token'].strip():
            raise RuntimeError('Grok 自动续期返回无效 refresh token，保留凭据。')
        updated['refresh_token'] = result['refresh_token']
    now = time.time()
    updated['create_time'] = datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z')
    lifetime = result.get('expires_in')
    updated['expires_at'] = None
    if isinstance(lifetime, (int, float)) and not isinstance(lifetime, bool) and 0 < lifetime <= 31536000:
        updated['expires_at'] = datetime.fromtimestamp(now + lifetime, timezone.utc).isoformat().replace('+00:00', 'Z')
    return updated


def save_credentials(path, data):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.grok-auth-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)  # mkstemp 创建的文件权限为 0600。
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_credentials(path, rejected_token=None):
    path = Path(path).expanduser()
    _, _, entry = read_credentials(path)

    def needs_refresh(value):
        expiry = expires_at(value)
        return ((rejected_token is not None and value['key'] == rejected_token)
                or (expiry is not None and expiry <= time.time() + REFRESH_MARGIN))

    if not needs_refresh(entry):
        return entry['key'].strip()
    with refresh_lock(path):
        _, scope, entry = read_credentials(path)
        if not needs_refresh(entry):
            return entry['key'].strip()  # CLI 或其他采集器已经续期，直接复用。
        try:
            updated = refresh_tokens(entry)
        except RuntimeError:
            _, _, latest = read_credentials(path)
            if latest['key'] != entry['key'] and not needs_refresh(latest):
                return latest['key'].strip()
            raise
        data, latest_scope, latest = read_credentials(path)
        if latest_scope != scope or latest['key'] != entry['key']:
            return latest['key'].strip()  # 不覆盖其他登录流程刚写入的新会话。
        data[scope] = dict(latest, **{key: updated[key] for key in ('key', 'refresh_token', 'create_time', 'expires_at')})
        save_credentials(path, data)
        return updated['key'].strip()
