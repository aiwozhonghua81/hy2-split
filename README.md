# hy2-split —— 自己搭的「一条隧道，两个出口」分流节点

> 一句话说明：这台香港服务器会把你的流量从一条隧道送进来，然后**自己决定**哪些流量从香港出去、哪些流量绕道新加坡出去。你在电脑上的任何软件（浏览器、AI 工具、脚本）都只看到「一个香港代理」，不用管后面发生了什么。

---

## 目录

- [一、这套东西到底解决什么问题](#一这套东西到底解决什么问题)
- [二、整体是怎么跑的](#二整体是怎么跑的)
- [三、为什么要分两个出口](#三为什么要分两个出口)
- [四、TikTok 到底怎么分的](#四tiktok-到底怎么分的)
- [五、目录里每个文件是干什么的](#五目录里每个文件是干什么的)
- [六、怎么装](#六怎么装)
- [七、怎么用](#七怎么用)
- [八、怎么知道流量到底走了哪边](#八怎么知道流量到底走了哪边)
- [九、规则表（12 条，有顺序讲究）](#九规则表12-条有顺序讲究)
- [十、国内字节 vs 国际字节](#十国内字节-vs-国际字节)
- [十一、速度优化都做了些什么](#十一速度优化都做了些什么)
- [十二、常见问题排查](#十二常见问题排查)
- [十三、备份与回滚](#十三备份与回滚)
- [十四、修改配置的正确姿势](#十四修改配置的正确姿势)

---

## 一、这套东西到底解决什么问题

先说场景。你有一台**香港服务器**，也有一台**新加坡服务器**（或者一个新加坡的 SOCKS5 节点）。

- 香港服务器：带宽大、流量多，但有些网站会**根据你所在的地区限制内容**。比如 TikTok 在香港 IP 上打开，直播列表可能是空的、视频可能提示「不可用」。
- 新加坡节点：地区限制少，什么都能看，但**带宽贵、流量省着用**，拿来跑大流量视频太浪费。

所以理想的方案是**两个都留着，但各干各的活**：

| 流量类型 | 走哪边 | 为什么 |
|---|---|---|
| 看视频、直播、大文件下载 | **香港** | 带宽大、流量便宜，跑得起 |
| 有地区限制的接口、需要固定地区的服务 | **新加坡** | 地区正确，能正常返回数据 |
| AI 服务（OpenAI / ChatGPT 等） | **新加坡** | 这类服务对 IP 地区敏感，走新加坡更稳 |

这套项目就是把这套判断逻辑**写死在服务器上**。你换电脑、换手机、换软件，都不用重新配一遍——只要连上香港服务器，分流自动生效。

**对比一下不做分流会怎样**：

```
❌ 全部走新加坡：  视频看着卡，流量账单飞涨
❌ 全部走香港：    TikTok 直播列表空白，某些接口直接报错
✅ 这套方案：      大流量走香港（省流量、速度快），接口走新加坡（该能用就能用）
```

---

## 二、整体是怎么跑的

```
    你的电脑
    浏览器 / AI 软件 / 命令行
         │
         │  ① 走 Hysteria2 协议（UDP 8443 端口，加密）
         ▼
   ╔═══════════════════════╗
   ║   香港服务器          ║
   ║   sing-box 核心       ║
   ║                       ║
   ║   ② 按规则表判断      ║
   ║   每个域名该走哪边    ║
   ╚═══╤═══════════════╤═══╝
       │               │
       │ ③ 直连        │ ④ 转发给上游
       │ （香港 IP）   │ socks5-client 容器
       ▼               ▼
   目标网站         新加坡出口
   （YouTube、        （TikTok 接口、
    TikTok 视频流、    OpenAI、
    Netflix…）         ChatGPT…）
```

**几个名词解释**（第一次看的话这里最重要）：

- **Hysteria2（hy2）**：一种代理协议。特点是**在 UDP 上跑**，所以在有丢包的网络里速度反而比 TCP 协议快很多。本项目用它做「入口」。
- **sing-box**：服务器上负责实际转发和分流判断的程序。整个分流逻辑都在它里面。
- **SOCKS5**：一种比较老但通用的代理协议。本项目拿它当「第二出口」——把需要走新加坡的流量扔给新加坡。
- **clash_api**：sing-box 内置的一个调试接口，能看到「现在有哪些连接、每个走了哪条路、传了多少字节」。这是本项目**唯一能准确回答「流量到底走了哪边」的工具**。
- **direct / socks-upstream**：sing-box 里两条出站的代号。`direct` = 服务器自己直接出去（香港 IP）；`socks-upstream` = 转发给新加坡节点。

---

## 三、为什么要分两个出口

一句话：**香港管「省流量」，新加坡管「能打开」。**

具体到 TikTok 这种站，情况很典型：

- 它的**视频流**（真正占流量的大头）来自 CDN，叫 `pull-flv-xxx.tiktokcdn.com`。这部分数据量大，但只要能拉回来，在哪个地区拉都一样。
- 它的**接口**（推荐列表、直播列表、消息）叫 `webcast.tiktok.com`。这部分数据量很小，但**返回什么内容取决于你的 IP 地区**——香港 IP 可能给你返回空列表。

所以最优解是：**大流量走香港，小接口走新加坡**。两边各取所长。

---

## 四、TikTok 到底怎么分的

这是本次调优花时间最多的地方，实测下来的结论：

| 环节 | 域名 | 走哪边 | 实测数据量 |
|---|---|---|---|
| 直播 / 视频流（大头） | `pull-flv-*.tiktokcdn.com` | **香港** | 124.9 MB |
| 视频流（大头） | `v16-webapp-prime.tiktok.com` | **香港** | 28.2 MB |
| 签名 / 加密密钥 | `p16/p19-common-sign.tiktokcdn.com` | **香港** | 约 5.4 MB |
| 直播控制接口 | `webcast.tiktok.com`、`webcast-ws.tiktok.com` | **新加坡** | 约 2.9 MB |
| 首页 | `www.tiktok.com` | **新加坡** | 约 1.0 MB |

**最终效果（实测）**：香港占 **96.56%**，新加坡只占 **3.44%**。直播和视频都能正常播放。

这里有个**很重要的坑**，值得单独讲：

> `v16-webapp-prime.tiktok.com` 在域名列表里只占 **1 条**，看起来微不足道。
> 但它一条连接就扛了 **28 MB**。
>
> 如果你只看「哪些域名走了新加坡」来统计，会觉得「没几个域名啊，问题不大」。
> **只有按字节数统计，才知道流量主体到底在哪。**

所以项目里专门配了 `scripts/traffic-stat.sh` 来做这件事。

---

## 五、目录里每个文件是干什么的

```
hy2-split/
├── server/                          ← 香港服务器上要放的东西
│   ├── config.template.json         sing-box 核心配置（分流规则都在这）
│   ├── compose.yaml                 怎么把 sing-box 跑起来的容器定义
│   ├── zz-quic-tune.conf             系统网络参数调优（文件名 zz- 前缀有讲究）
│   ├── 99-singbox-quic.conf         sing-box 配套的基础参数
│   ├── nic-tune.sh                  网卡参数自愈脚本（RPS/XPS/中断亲和性）
│   └── nic-tune.service             让上面的脚本开机自动跑一遍
│
├── upstream/                        ← 新加坡上游那层
│   ├── config.template.json         上游 SOCKS5 的配置
│   └── compose.yaml
│
├── client/                          ← 你电脑上的客户端
│   └── profile.yaml                 Clash Verge（mihomo 内核）配置
│
├── scripts/
│   ├── traffic-stat.sh              统计流量到底走了哪边
│   └── render-client.sh             把客户端配置里的占位符填成真值
│
├── install.sh                       一键部署脚本
├── .env.example                     参数填写模板
└── README.md                        就是你正在看的这个
```

### 关键文件详解

**`server/config.template.json` —— 分流的大脑**

整份配置 12 条规则，第一条是「开启域名嗅探」（这样才能按域名而不是按 IP 判断），中间是分流规则，最后一条兜底。

里面的 `__HY2_PASSWORD__`、`__UPSTREAM_SOCKS_HOST__` 这些是**占位符**，部署时由 `install.sh` 自动替换成真实值。仓库里不存真实密码，这是有意的。

**`server/zz-quic-tune.conf` —— 为什么文件名要加 `zz-`**

Linux 加载 sysctl 配置是**按文件名排序**执行的。加 `zz-` 前缀是为了保证这份配置**最后加载**，这样它设置的参数不会被其他文件覆盖掉。名字叫「zz」就是「最后一位」的意思。

**`server/nic-tune.sh` —— 为什么要做成 systemd 服务**

有些云厂商会在你重启机器后**悄悄把网卡参数重置回默认值**，网络优化的效果就没了。这个脚本的作用就是每次开机自动把这些参数重新设置一遍（业界叫「自愈」）。

**`scripts/traffic-stat.sh` —— 查流量真相的工具**

详见[第八节](#八怎么知道流量到底走了哪边)。

---

## 六、怎么装

### 前提条件

- 一台**海外**的 Linux 服务器（Debian / Ubuntu 都行），能装 Docker
- 一个**上游 SOCKS5 节点**（新加坡方向），格式是「地址 + 端口 + 用户名 + 密码」
- 服务器防火墙放行 **UDP 8443**

### 三条命令搞定

```bash
git clone https://github.com/aiwozhonghua81/hy2-split.git
cd hy2-split

HY2_PASSWORD='你的hy2密码' \
UPSTREAM_SOCKS_HOST='新加坡socks5地址' \
UPSTREAM_SOCKS_PORT='新加坡socks5端口' \
UPSTREAM_SOCKS_USER='用户名' \
UPSTREAM_SOCKS_PASS='密码' \
HY2_SERVER_IP='你的服务器公网IP' \
./install.sh
```

### 这个脚本做了什么

1. 建目录 `/opt/socks5-server`，**先把旧配置备份一份**（改坏了能退回去）
2. 把模板里的占位符替换成你填的真实值，生成 `config.json`
3. 如果没有证书，自动生成一张自签证书（有效期 10 年）
4. 部署上游 socks5 容器，两个容器放进同一个 Docker 网络
5. 写入系统网络调优参数
6. 启动容器，打印运行状态

**幂等**：可以反复执行，不会重复建东西，也不会覆盖你手动改过的配置（会先备份）。

### 关于上游节点在哪

`install.sh` 默认会在**本机**也起一个 socks5-client 容器（对应「上游就在同一台机器」的场景）。
如果你的新加坡节点在**另一台机器**上，改两处即可：

```bash
# 1) 编辑 server/config.template.json，把 outbound 里的 server 改成对方地址
# 2) 跳过上游容器部署
```

---

## 七、怎么用

### 1. 服务器那边

部署完容器跑起来就行了，验证一下：

```bash
docker ps --filter name=socks5-server
docker logs -f socks5-server
```

### 2. 客户端这边

需要用 **Clash Verge**（或任何基于 mihomo 的客户端）。

```bash
cd hy2-split
HY2_SERVER='你的服务器公网IP' \
HY2_PASSWORD='你的hy2密码' \
./scripts/render-client.sh client/profile.local.yaml
```

生成出来的 `client/profile.local.yaml` 导入 Clash Verge 的订阅/配置里就行。

客户端配置里已经做好的：

- **TUN 模式**（虚拟网卡接管全局流量，不用手动设系统代理）
- **fake-ip DNS**（本地假 IP 解析，域名分流才准）
- **国内域名直连**、国外走代理的常规策略
- Gemini / Antigravity 等 AI 产品的规则

### 关键设计：为什么分流放在服务端

客户端只负责「把流量送进隧道」，**所有「这个域名该走哪边」的判断都在服务器上**。

好处很实在：**你换设备的时候，策略不用重配**。手机、平板、公司电脑、家里电脑，只要填同一个服务器地址，行为完全一致。

---

## 八、怎么知道流量到底走了哪边

这是调优过程中最花时间也最有价值的部分。

### 为什么要看字节数，不能只看域名

举个真实例子：

- 看域名列表：「走了新加坡的有 5 个域名」→ 感觉问题不大
- 看字节数：「其中 119 MB 全是 `v16-webapp-prime.tiktok.com` 一个域名」→ 真相大白

**结论：任何分流调优，都必须按字节数归因。**

### 怎么查

```bash
./scripts/traffic-stat.sh
```

输出长这样：

```
== 链路占比 ==
direct             136.928 MB  96.56%
socks-upstream       4.873 MB   3.44%

== 字节系连接明细 ==
  124.952MB  pull-flv-l10-sg01.tiktokcdn.com          direct
   28.242MB  v16-webapp-prime.tiktok.com               direct
    4.877MB  p16-common-sign.tiktokcdn.com             direct
    2.252MB  webcast.tiktok.com                         socks-upstream
```

### ⚠️ 这里有个大坑

如果你直接执行：

```bash
curl http://127.0.0.1:19090/connections   # ❌ 永远返回 000，什么都拿不到
```

**原因**：`clash_api` 只监听在**容器自己的网络命名空间内部**，compose 文件里**没有**把这个端口映射到宿主机。所以宿主机上访问 `127.0.0.1` 是访问不到的。

**正确写法**（脚本里就是这么做的）：

```bash
docker exec socks5-server sh -c "wget -qO- --timeout=8 http://127.0.0.1:19090/connections"
```

另外注意：**容器里没有 `curl`，只有 `wget`**。这个坑不写下来，下次一定会再踩一遍。

---

## 九、规则表（12 条，有顺序讲究）

| # | 动作 | 走哪边 | 内容 |
|---|---|---|---|
| 00 | sniff | — | 开启域名嗅探。不开这条，后面全是 IP 匹配，规则等于白写 |
| 01 | reject | — | 拒绝私有 IP（防止有人用你的节点访问内网） |
| 02 | reject | — | 拒绝 `127.0.0.0/8`（同上，防环） |
| **03** | **direct** | **香港** | **`v16-webapp-prime.tiktok.com`（精确匹配，必须放最前面）** |
| 04 | route | 新加坡 | `peacocktv.com`、`tiktok.com`（按后缀匹配） |
| 05 | route | 新加坡 | `chatgpt.com`、`openai.com`、`oaistatic.com`、`oaistatsig.com`、`oaiusercontent.com`、`openaimerge.com` |
| 06 | route | 香港 | 498 条域名后缀，包含 YouTube、奈飞、Pornhub、TikTok CDN、`tiktokv.com` 等所有海外大流量站点 |

### 为什么第 03 条必须放最前面

第 04 条的 `tiktok.com` 是**后缀匹配**，意思是「凡是域名以 tiktok.com 结尾的都算」。那 `v16-webapp-prime.tiktok.com` 自然也会被它抓走。

sing-box 的规则是**从上往下匹配，命中即停**。所以精确的那条必须排在后缀那条**前面**，否则永远轮不到它执行。

**这一条是整份规则表最脆弱的地方**，以后加规则时务必注意顺序。

---

## 十、国内字节 vs 国际字节

字节跳动（ByteDance）旗下有两大体系，**必须分开处理**，混在一起会出问题：

| 归属 | 域名 | 说明 |
|---|---|---|
| **国内系** | `snssdk.com`、`pstatp.com`、`byteimg.com`、`douyin.com`、`bytecdn.cn`、`toutiao.com` | 抖音、西瓜、头条 |
| **国际系** | `isnssdk.com`、`ipstatp.com`、`ibyteimg.com`、`byteoversea.com`、`tiktokv.com`、`tiktokcdn.com` | TikTok、TikTok Shop |

本项目的处理：

- `tiktok.com` 系列 → 按国际处理（第 04 条，后缀匹配走新加坡，精确的 `v16-webapp-prime` 走香港）
- `douyin.com` 等国内系 → 落到第 06 条大 direct 组，走香港直连

---

## 十一、速度优化都做了些什么

| 优化项 | 做了什么 | 为什么 |
|---|---|---|
| **BBR 拥塞控制** | `bbr_profile: standard` | TCP 拥塞控制算法，在有丢包的线路上能显著提速 |
| **UDP 缓冲** | 加大 hy2 用的 UDP 收发缓冲 | 高速传输时 UDP 包容易丢，缓冲大一点能扛住突发 |
| **网卡中断分配（RPS/XPS）** | `nic-tune.sh` 设置 | 多核 CPU 上把网络中断分摊到各核，提升吞吐 |
| **环形缓冲 / 卸载** | `nic-tune.sh` 设置 | 减少内核拷贝开销 |
| **系统参数加载顺序** | 文件名加 `zz-` 前缀 | 保证参数不被其他文件覆盖 |
| **开机自愈** | `nic-tune.service` | 云厂商重置参数后自动恢复 |

### 两个踩过的坑

**坑 1：hy2 握手返回 404**

原因：配置里同时存在 `up_mbps` / `down_mbps` / `ignore_client_bandwidth` 这类**带宽限制参数**，和 BBR 的拥塞控制协商**互相冲突**。

解法：删掉这三个参数，只保留 `bbr_profile`。

**坑 2：Docker 里服务名解析 NXDOMAIN**

原因：compose 里额外配了 `dns` / `default_domain_resolver`，把 Docker 内置 DNS 搞乱了。

解法：**删掉**这两个自定义配置，用 Docker 默认的。

---

## 十二、常见问题排查

| 现象 | 原因 | 怎么办 |
|---|---|---|
| hy2 握手 404 | BBR 与带宽参数冲突 | 检查 `up_mbps` / `down_mbps` / `ignore_client_bandwidth` 是否还在 |
| 容器里服务名 NXDOMAIN | compose 里有自定义 `dns` 配置 | 删掉 `dns` 和 `default_domain_resolver` |
| 宿主机访问 19090 拿不到数据 | clash_api 只在容器网络内部 | 用 `docker exec ... wget`，见第八节 |
| TikTok 直播列表空白 | `webcast.tiktok.com` 被塞进香港直连组了 | 接口类域名要留新加坡 |
| 改了规则没效果 | 精确规则被后缀大组前置吞掉 | 检查规则顺序 |
| 视频播放卡顿 | `tiktokcdn.com` / `tiktokv.com` 不在 direct 组里 | 确认它们在第 06 条里 |
| 客户端连不上 | 防火墙没放行 UDP 8443 | 检查云厂商安全组 + 本机 iptables |
| 视频跳帧 / 断流 | UDP 缓冲太小 | 调 `zz-quic-tune.conf` 里的缓冲参数 |

---

## 十三、备份与回滚

`install.sh` 每次执行前会自动备份：

```bash
cp -a /opt/socks5-server/config.json \
      /opt/socks5-server/config.json.bak-$(date +%Y%m%d-%H%M%S)
```

手动改完配置也建议立刻备份一份。

**回滚方法**：

```bash
cd /opt/socks5-server
ls -t config.json.bak-* | head -1        # 找到最新的备份
cp -a config.json.bak-XXXXXXXX config.json
docker compose up -d --force-recreate    # 重新加载配置
```

---

## 十四、修改配置的正确姿势

### 在服务器上改

```bash
cd /opt/socks5-server
cp -a config.json config.json.bak-$(date +%Y%m%d-%H%M%S)   # ① 先备份
vi config.json                                               # ② 改
docker compose up -d --force-recreate                       # ③ 重新加载
docker logs --tail 50 socks5-server                          # ④ 看日志确认没报错
```

**每一步都不能省。** 尤其第 ① 步——配置 JSON 里规则有顺序依赖，改坏了很难一眼看出问题。

### 改完怎么验证

```bash
./scripts/traffic-stat.sh
```

然后**在浏览器上实际访问一下目标网站**（比如打开 TikTok 直播页），再看统计结果。

**注意一个陷阱**：连接日志是**累计**的，改完配置后老连接还在。判断效果要看**新产生**的连接，不是看总数。

### 在仓库里改（推荐）

改 `server/config.template.json`，然后：

```bash
git add -A
git commit -m "描述你改了什么"
git push
```

这样下次重新部署用的就是最新版，不用再回忆当时改了什么。

---

## 附：常用命令速查

```bash
# 看服务状态
docker ps --filter name=socks5-server
docker logs -f socks5-server

# 看流量走向
./scripts/traffic-stat.sh

# 手动拉一次连接数据
docker exec socks5-server sh -c "wget -qO- --timeout=8 http://127.0.0.1:19090/connections"

# 改完配置重新加载
cd /opt/socks5-server && docker compose up -d --force-recreate

# 备份 + 回滚
cp -a /opt/socks5-server/config.json /opt/socks5-server/config.json.bak-$(date +%Y%m%d-%H%M%S)

# 看当前生效的网络参数
sysctl net.ipv4.tcp_congestion_control
```

---

## 安全说明

- 仓库里**不含任何真实密码**，敏感值都是占位符
- `config.json`、`certs/`、`*.pem`、`*.bak`、`.env` 已在 `.gitignore` 中，不会被误提交
- hy2 密码建议用一串随机字符，不要用生日或简单数字
- 证书用了 `skip-cert-verify`（客户端不校验），所以**不要用这个节点做支付类操作**

---

## License

MIT
