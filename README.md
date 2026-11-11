# hy2-split — Hysteria2 双出口分流节点

香港服务器自建 Hysteria2 节点，客户端（Clash Verge / mihomo）连入后由**服务端 sing-box**
做分流：**大流量走香港直连，受地区限制/业务接口走新加坡上游**。

```
本机浏览器/AI 软件
   │  hysteria2 (UDP 8443, 复用 TCP)
   ▼
香港服务器 sing-box  ──┬─ direct ─────────► 目标站点（走香港 IP）
                       └─ socks-upstream ──► socks5-client:1080 ──► 新加坡（上游 socks5 节点）
```

## 目录结构

```
server/
  config.template.json    sing-box 核心配置（12 条路由规则，敏感项已占位）
  compose.yaml            socks5-server 容器（8443/udp）
  zz-quic-tune.conf       sysctl 调优（文件名 zz- 前缀确保最后加载）
  99-singbox-quic.conf    sing-box 基础 UDP/TCP 参数
  nic-tune.sh             RPS/XPS/ring buffer/offload 自愈脚本
  nic-tune.service        systemd oneshot 开机自愈
upstream/
  config.template.json    新加坡上游 socks5 客户端配置
  compose.yaml
client/
  profile.yaml            Clash Verge / mihomo 客户端配置（TUN + DNS）
scripts/
  traffic-stat.sh         按真实字节统计分流走向
install.sh                一键部署（幂等，自动备份）
```

## 快速部署

```bash
git clone <this-repo> hy2-split && cd hy2-split

HY2_PASSWORD='你的hy2密码' \
UPSTREAM_SOCKS_HOST='上游socks5地址' \
UPSTREAM_SOCKS_PORT='上游端口' \
UPSTREAM_SOCKS_USER='用户名' \
UPSTREAM_SOCKS_PASS='密码' \
HY2_SERVER_IP='服务器公网IP' \
./install.sh
```

脚本会：创建 `/opt/socks5-server` → 渲染配置 → 生成自签证书 → 写入 sysctl/NIC 调优
→ `docker compose up -d` 启动 → 打印容器状态。

## 分流规则表（12 条，顺序敏感）

| # | 动作 | 出站 | 内容 |
|---|---|---|---|
| 00 | sniff | — | 开启域名嗅探，否则只有 IP 无法匹配 |
| 01 | reject | — | 私有 IP |
| 02 | reject | — | 127.0.0.0/8 |
| **03** | **direct** | **香港** | **`v16-webapp-prime.tiktok.com`（精确，必须前置）** |
| 04 | route | 新加坡 | `peacocktv.com`、`tiktok.com`（后缀） |
| 05 | route | 新加坡 | `chatgpt.com` / `openai.com` / `oaistatic.com` / `oaistatsig.com` / `oaiusercontent.com` / `openaimerge.com` |
| 06 | route | 香港 | 498 条域名后缀（含 `tiktokcdn.com`、`tiktokv.com`、`youtube.com`、奈飞、Pornhub 等海外高带宽站点） |

**为什么 03 必须前置**：04 的 `domain_suffix: tiktok.com` 会匹配 `v16-webapp-prime.tiktok.com`，
若 03 在其后，精确规则永远不生效。

## TikTok 分流策略（已实测）

| 环节 | 域名 | 出站 | 实测字节 |
|---|---|---|---|
| 直播/视频流主体 | `pull-flv-*.tiktokcdn.com` | 香港 | 124.9 MB |
| 直播/视频流主体 | `v16-webapp-prime.tiktok.com` | 香港 | 28.2 MB |
| 签名/密钥 | `p16/p19-common-sign.tiktokcdn.com` | 香港 | ~5.4 MB |
| 直播控制面 | `webcast.tiktok.com`、`webcast-ws.tiktok.com` | 新加坡 | ~2.9 MB |
| 首页 | `www.tiktok.com` | 新加坡 | ~1.0 MB |

实测总链路占比：**香港 96.56% / 新加坡 3.44%**，直播与视频均可正常播放。

设计意图：视频字节走香港（带宽大、免新加坡流量费），而**控制面**（推荐流、直播列表、
IM/WebSocket）留在新加坡，避免香港 IP 触发的地区限制/空列表问题。
`v16-webapp-prime` 承载单连接 28 MB 级别的字节，是 HK 直连能成立的关键一条。

## 国内 / 国际字节系拆分

| 归属 | 域名 |
|---|---|
| 国内（douyin/头条系） | `snssdk.com`、`pstatp.com`、`byteimg.com`、`douyin.com`、`bytecdn.cn` |
| 国际（TikTok 系） | `isnssdk.com`、`ipstatp.com`、`ibyteimg.com`、`byteoversea.com`、`tiktokv.com` |

`tiktok.com` 统一按国际处理；`douyin.com` 等国内系走第 06 条大 direct 组。

## 流量归因方法

**看域名或连接数会骗人**——`v16-webapp-prime` 在域名清单里只有 1 条，实际承载 28 MB。
必须按字节数看：

```bash
./scripts/traffic-stat.sh
```

关键坑：`clash_api` 只监听在**容器 netns 内**的 `127.0.0.1:19090`，compose 未做端口映射，
所以宿主机 `curl 127.0.0.1:19090` 永远返回 000。正确取法：

```bash
docker exec socks5-server sh -c "wget -qO- --timeout=8 http://127.0.0.1:19090/connections"
```

容器内**没有 curl，只有 wget**。

## 性能调优要点

- **BBR + fq**：`bbr_profile: standard`（sing-box 内建 congestion control）；
  切勿同时设置 `up_mbps`/`down_mbps`/`ignore_client_bandwidth`，否则与 BBR 协商冲突导致 404。
- **UDP 缓冲**：`zz-quic-tune.conf` 用 `zz-` 前缀，确保在所有其他 sysctl 之后加载。
- **RPS/XPS**：`nic-tune.sh` 由 systemd 开机自愈，防止网卡参数被云厂商重置。
- **容器网络**：容器 netns 内只有 `net.ipv6.conf.all.disable_ipv6` 可写，其余在宿主机层全局生效。
- **DNS**：不要在 compose 里额外配 `dns`/`default_domain_resolver`，否则 Docker 内嵌 DNS
  会让服务名解析 NXDOMAIN。

## 客户端使用

`client/profile.yaml` 导入 Clash Verge（mihomo 内核）：

- TUN 模式 + fake-ip DNS（`198.18.0.1/16`）
- 节点 `HK-Hy2` 指向你的服务器 `8443/udp`
- 渲染时把 `__HY2_SERVER__` / `__HY2_PASSWORD__` 替换为实际值

客户端只负责把流量送进隧道，**所有分流判定都在服务端**——这样换设备时策略不用重配。

## 排障速查

| 现象 | 原因 / 处理 |
|---|---|
| hy2 握手 404 | BBR 与带宽参数冲突，检查 `up_mbps`/`down_mbps`/`ignore_client_bandwidth` 是否同时存在 |
| Docker 服务名 NXDOMAIN | 删掉 compose 里自定义 `dns` / `default_domain_resolver` |
| 宿主机访问不到 19090 | 正常，clash_api 只在容器 netns 内，用 `docker exec ... wget` |
| TikTok 直播列表空白 | `webcast.tiktok.com` 必须留新加坡，别塞进 HK 直连大组 |
| 规则不生效 | 检查精确规则是否被 `domain_suffix` 大组前置吞掉 |
| 视频卡顿 | 确认 `tiktokcdn.com` / `tiktokv.com` 在 direct 大组内 |

## 备份策略

`install.sh` 每次执行前自动 `cp -a` 备份 `config.json` 为
`config.json.bak-YYYYmmdd-HHMMSS`。手动改配置后建议立即备份：

```bash
cp -a /opt/socks5-server/config.json /opt/socks5-server/config.json.bak-$(date +%Y%m%d-%H%M%S)
```
