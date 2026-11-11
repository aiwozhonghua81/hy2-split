#!/usr/bin/env bash
# 一键部署 Hysteria2 分流节点（香港直连 + 新加坡上游）
#
#   用法：
#     HY2_PASSWORD=xxx UPSTREAM_SOCKS_HOST=1.2.3.4 UPSTREAM_SOCKS_PORT=1080 \
#       HY2_SERVER_IP=<your.server.ip> ./install.sh
#
# 幂等：可重复执行，脚本会在改动前自动备份。
set -euo pipefail

HY2_PASSWORD="${HY2_PASSWORD:?必须设置 HY2_PASSWORD}"
UPSTREAM_SOCKS_HOST="${UPSTREAM_SOCKS_HOST:?必须设置 UPSTREAM_SOCKS_HOST}"
UPSTREAM_SOCKS_PORT="${UPSTREAM_SOCKS_PORT:-1080}"
UPSTREAM_SOCKS_USER="${UPSTREAM_SOCKS_USER:-}"
UPSTREAM_SOCKS_PASS="${UPSTREAM_SOCKS_PASS:-}"
HY2_SERVER_IP="${HY2_SERVER_IP:-$(curl -s --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')}"
HY2_PORT="${HY2_PORT:-8443}"
SNI="${SNI:-bing.com}"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="/opt/socks5-server"

echo "==> 目标: ${DEST}  端口: ${HY2_PORT}/udp  出口IP: ${HY2_SERVER_IP}"

# ---------------------------------------------------------------- 1. 目录
mkdir -p "${DEST}/certs"
if [ -f "${DEST}/config.json" ]; then
  cp -a "${DEST}/config.json" "${DEST}/config.json.bak-$(date +%Y%m%d-%H%M%S)"
fi

# ---------------------------------------------------------------- 2. 配置
sed \
  -e "s|__HY2_PASSWORD__|${HY2_PASSWORD}|g" \
  -e "s|__UPSTREAM_SOCKS_HOST__|${UPSTREAM_SOCKS_HOST}|g" \
  -e "s|__UPSTREAM_SOCKS_PORT__|${UPSTREAM_SOCKS_PORT}|g" \
  "${SRC}/server/config.template.json" > "${DEST}/config.json"
chmod 600 "${DEST}/config.json"

cp -a "${SRC}/server/compose.yaml" "${DEST}/compose.yaml"

# ---------------------------------------------------------------- 3. 证书
if [ ! -f "${DEST}/certs/key.pem" ]; then
  echo "==> 生成自签证书"
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout "${DEST}/certs/key.pem" -out "${DEST}/certs/cert.pem" \
    -days 3650 -nodes -subj "/CN=${SNI}" \
    -addext "subjectAltName=DNS:${SNI},IP:${HY2_SERVER_IP}" 2>/dev/null
  chmod 600 "${DEST}/certs/key.pem"
else
  echo "==> 证书已存在，跳过"
fi

# ---------------------------------------------------------------- 4. 上游 socks5
# 场景 A：上游 socks5 在另一台机器 → 保持 config.json 里的 server/server_port 为该地址即可，
#          只需删掉/不部署下面的 socks5-client 容器。
# 场景 B：上游 socks5 就在本机（当前部署）→ 部署 socks5-client 容器，走外部网络共享给
#          socks5-server，容器名 socks5-client:1080 即上面的 server 值。
UPSTREAM_DIR="/opt/socks5-client"
mkdir -p "${UPSTREAM_DIR}"
if [ -f "${UPSTREAM_DIR}/config.json" ]; then
  cp -a "${UPSTREAM_DIR}/config.json" "${UPSTREAM_DIR}/config.json.bak-$(date +%Y%m%d-%H%M%S)"
fi
sed \
  -e "s|__UPSTREAM_SOCKS_HOST__|${UPSTREAM_SOCKS_HOST}|g" \
  -e "s|__UPSTREAM_SOCKS_PORT__|${UPSTREAM_SOCKS_PORT}|g" \
  -e "s|__UPSTREAM_SOCKS_USER__|${UPSTREAM_SOCKS_USER:-}|g" \
  -e "s|__UPSTREAM_SOCKS_PASS__|${UPSTREAM_SOCKS_PASS:-}|g" \
  "${SRC}/upstream/config.template.json" > "${UPSTREAM_DIR}/config.json"
chmod 600 "${UPSTREAM_DIR}/config.json"
cp -a "${SRC}/upstream/compose.yaml" "${UPSTREAM_DIR}/compose.yaml"

# 外部网络：两个容器共用，保证 socks5-server 能用容器名 socks5-client 访问上游
if ! docker network inspect socks5-client_default >/dev/null 2>&1; then
  docker network create socks5-client_default
fi
cd "${UPSTREAM_DIR}"
docker compose up -d

# ---------------------------------------------------------------- 5. 系统调优
echo "==> 写入 sysctl / NIC 调优"
cp -a "${SRC}/server/zz-quic-tune.conf"   /etc/sysctl.d/zz-quic-tune.conf
cp -a "${SRC}/server/99-singbox-quic.conf" /etc/sysctl.d/99-singbox-quic.conf
install -m 755 "${SRC}/server/nic-tune.sh"   /usr/local/sbin/nic-tune.sh
install -m 644 "${SRC}/server/nic-tune.service" /etc/systemd/system/nic-tune.service
sysctl --system >/dev/null 2>&1 || true
systemctl daemon-reload
systemctl enable --now nic-tune.service >/dev/null 2>&1 || true

# ---------------------------------------------------------------- 6. 启动
echo "==> 启动容器"
cd "${DEST}"
docker compose up -d

sleep 3
docker ps --filter name=socks5-server
echo
echo "完成。查看日志: docker logs -f socks5-server"
echo "流量统计: ./scripts/traffic-stat.sh"
