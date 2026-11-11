#!/usr/bin/env bash
# 读取 sing-box 内置 clash_api 的连接统计，按链路（direct=香港 / socks-upstream=新加坡）
# 与字节系域名归因真实流量走向。
#
# 注意：clash_api 只监听在容器 netns 内（127.0.0.1:19090），compose 未做端口映射，
# 宿主机 curl 127.0.0.1:19090 永远拿不到数据。必须进容器取，且容器内只有 wget。
set -euo pipefail

CONTAINER="${CONTAINER:-socks5-server}"
API="http://127.0.0.1:19090/connections"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

docker exec "$CONTAINER" sh -c "wget -qO- --timeout=8 ${API}" > "$TMP"

python3 - "$TMP" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
conns = d.get('connections', [])
BYTE_KEYS = ('tiktok','byteoversea','ibyteimg','tiktokv','snssdk','pstatp','byteimg','isnssdk','ipstatp','douyin','toutiao')

tot, rows = {}, []
for c in conns:
    key = '->'.join(c.get('chains') or ['?'])
    m = c.get('metadata') or {}
    host = m.get('host') or ''
    n = (c.get('download') or 0) + (c.get('upload') or 0)
    tot[key] = tot.get(key, 0) + n
    if any(k in host for k in BYTE_KEYS):
        rows.append((n, host, key, m.get('network')))

grand = sum(tot.values()) or 1
print('== 链路占比 ==')
for k, v in sorted(tot.items(), key=lambda x: -x[1]):
    print(f'{k:16s} {v/1048576:9.3f} MB  {v*100/grand:5.2f}%')
print()
print('== 字节系连接明细 ==')
for n, host, key, net in sorted(rows, key=lambda x: -x[0])[:30]:
    print(f'{n/1048576:8.3f}MB  {host[:52]:54s} {key:16s} {net}')
PY
