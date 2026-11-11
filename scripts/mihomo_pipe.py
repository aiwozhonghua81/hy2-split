#!/usr/bin/env python3
r"""Clash Verge (mihomo) 本地命名管道 API 客户端。

mihomo 以命名管道方式提供 external-controller，普通 HTTP/curl 连不上，
必须直接读写 \\\\.\pipe\\verge-mihomo-production-<hash>。

用法:
    python3 mihomo_pipe.py /rules
    python3 mihomo_pipe.py /rules/www.tiktok.com
    python3 mihomo_pipe.py --reload clash-verge.yaml
"""
import json
import os
import re
import sys

PIPE_RE = re.compile(r'verge-mihomo-[a-z]+-[0-9a-f]{16,}')


def find_pipe(base=None):
    """扫描 \\.\\pipe\\ 找到实际运行的 mihomo 管道。

    注意: clash-verge.yaml 里记录的 external-controller-pipe 名字
    (verge-mihomo-sidecar-release-xxx) 与实际运行的
    (verge-mihomo-production-xxx) 可能不一致, 必须以管道列表为准。
    """
    import subprocess
    try:
        out = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             "Get-ChildItem \\\\.\\pipe\\ | Where-Object {$_.Name -match 'verge-mihomo'} | "
             "Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=20).stdout
        names = [n.strip() for n in out.splitlines() if n.strip()]
        if names:
            # 优先 production（实际运行的核心）
            names.sort(key=lambda n: (0 if 'production' in n else 1, n))
            return r'\\.\pipe\%s' % names[0]
    except Exception:
        pass

    if base is None:
        base = os.path.join(
            os.path.expanduser('~'),
            r'AppData\Roaming\io.github.clash-verge-rev.clash-verge-rev\clash-verge.yaml')
    if os.path.exists(base):
        txt = open(base, encoding='utf-8', errors='replace').read()
        m = PIPE_RE.search(txt)
        if m:
            return r'\\.\pipe\%s' % m.group(0)
    raise RuntimeError('找不到 mihomo 命名管道')


def _dechunk(b):
    out = b''
    while True:
        i = b.find(b'\r\n')
        if i < 0:
            break
        try:
            n = int(b[:i].split(b';')[0], 16)
        except ValueError:
            break
        if n == 0:
            break
        out += b[i + 2:i + 2 + n]
        b = b[i + 2 + n + 2:]
    return out


def request(pipe, method, path, body=None, timeout=30):
    data = body if body is not None else b''
    head = (f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n").encode()
    with open(pipe, 'r+b', buffering=0) as f:
        f.write(head + data)
        chunks = []
        while True:
            part = f.read(65536)
            if not part:
                break
            chunks.append(part)
    raw = b''.join(chunks)
    h, _, b = raw.partition(b'\r\n\r\n')
    if b'chunked' in h.lower():
        b = _dechunk(b)
    status = int(h.split(b'\r\n')[0].split(b' ')[1])
    return status, b


def api(path, pipe=None):
    pipe = pipe or find_pipe()
    st, body = request(pipe, 'GET', path)
    if st >= 400:
        raise RuntimeError(f'HTTP {st}: {body[:300]}')
    return json.loads(body.decode('utf-8'))


def reload(path, pipe=None):
    """用本地 yaml 文件重载配置（payload 方式，绕过 SAFE_PATHS 限制）。"""
    pipe = pipe or find_pipe()
    payload = open(path, encoding='utf-8').read()
    body = json.dumps({'payload': payload}).encode('utf-8')
    st, resp = request(pipe, 'PUT', '/configs?force=true', body)
    return st, resp.decode('utf-8', 'replace')


if __name__ == '__main__':
    if sys.argv[1] == '--reload':
        st, msg = reload(sys.argv[2])
        print(f'重载 HTTP {st}: {msg[:200]}')
    else:
        print(json.dumps(api(sys.argv[1]), ensure_ascii=False, indent=2))
