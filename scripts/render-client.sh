#!/usr/bin/env bash
# 渲染客户端配置：把占位符替换为实际值，输出到指定路径。
# 用法: HY2_SERVER=1.2.3.4 HY2_PASSWORD=xxx ./scripts/render-client.sh out.yaml
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/client/profile.yaml"
OUT="${1:-client/profile.rendered.yaml}"
HY2_SERVER="${HY2_SERVER:?设置 HY2_SERVER}"
HY2_PASSWORD="${HY2_PASSWORD:?设置 HY2_PASSWORD}"
sed -e "s|__HY2_SERVER__|${HY2_SERVER}|g" -e "s|__HY2_PASSWORD__|${HY2_PASSWORD}|g" "${SRC}" > "${OUT}"
echo "已生成 ${OUT}，导入 Clash Verge 即可。"
