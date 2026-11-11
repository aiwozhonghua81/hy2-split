#!/usr/bin/env python3
r"""
从服务器端 sing-box 配置生成本地 mihomo(Clash Verge) 的分流规则块。

用法:
    python3 sync-domains.py /path/to/server_config.json [-o out.txt]

原理:
    服务器端把流量分成两类 —— direct(香港直连) 和 socks-upstream(新加坡)。
    在客户端(mihomo)层面，这两类的差别是「要不要进隧道」：
      * 服务器判定走新加坡的域名  -> 客户端必须 PROXY(进隧道)，让服务器转新加坡
      * 服务器判定走香港的域名    -> 客户端也应 PROXY(进隧道)，由服务器用香港 IP 出口
      * 纯国内域名(百度/B站/抖音…) -> 客户端 DIRECT 即可，省隧道带宽且更快
    所以最终映射规则:
      国内域名        -> DIRECT
      海外域名        -> PROXY
    其中「国内」由显式 CN 集合判定，避免依赖 geosite 数据导致漏判。
"""
import json
import sys
import argparse

# 国际字节系：虽然名字像字节，但属于 TikTok 海外体系，必须走隧道(香港出口)
INTL_BYTE = {
    'isnssdk.com', 'ipstatp.com', 'ibyteimg.com', 'ibytedtos.com',
    'byteoversea.com', 'byteoversea.net', 'sgpstatp.com', 'sgsnssdk.com',
    'bytedanceapi.com', 'byteintlapi.com', 'bytegecko-i18n.com',
    'bytedance.com.edgesuite.net',
}

# 明确的国内域名集合（从服务器 direct 列表中人工判定）
CN_DOMAINS = {
    # 字节国内系
    'snssdk.com', 'pstatp.com', 'pstatic.net', 'byteimg.com', 'bytecdn.cn',
    'byted.org', 'bytedance.com', 'bytedanceapi.com', 'bytedapm.com',
    'bytednsdoc.com', 'byteicdn.com',
    'douyin.com', 'douyin.com.edgesuite.net', 'douyincdn.com',
    'douyinpic.com', 'douyinstatic.com', 'douyinvod.com', 'iesdouyin.com',
    'toutiao.com', 'toutiaocloud.com', 'toutiaoimg.com',
    'zijieapi.com', 'zijiegou.com', 'zijievod.com',
    'gifshow.com', 'kuaishou.com', 'kwai.com',
    # 视频/内容
    'bilibili.co', 'bilibili.com', 'bilibili.tv', 'hdslb.com',
    'biliapi.com', 'biliapi.net', 'biliimg.com', 'bilivideo.cn', 'bilivideo.com',
    'iqiyi.com', 'iqiyipic.com', 'youku.com', 'mgtv.com', 'mgtvcdn.com',
    'pptv.com', 'pptvcdn.com', 'miao.com', 'livecdn.net', 'nmtv.com',
    # 资讯/工具
    'baidu.com', 'alicloud.com', 'alipan.com', 'aliyundrive.com',
    'cctv.cn', 'ntv.cn', 'quark.cn', 'yangkeduo.com', '115.com', '115cdn.com',
    'zhangku.com', 'zhangku.net',
}


def collect(config):
    """返回 (direct_domains, sg_domains)。direct 是精确域名集合，
    suffix 是后缀集合，mihomo 统一按 DOMAIN-SUFFIX 处理精确域名也无妨。"""
    exact, suffix, sg_exact, sg_suffix = set(), set(), set(), set()
    for r in config.get('route', {}).get('rules', []):
        ob = r.get('outbound')
        if ob not in ('direct', 'socks-upstream'):
            continue
        d, s = (r.get('domain') or []), (r.get('domain_suffix') or [])
        if ob == 'direct':
            exact |= set(d); suffix |= set(s)
        else:
            sg_exact |= set(d); sg_suffix |= set(s)
    return exact | suffix, sg_exact | sg_suffix


def gen_rules(direct_all, sg_all):
    """生成 mihomo 规则行列表。"""
    lines, seen = [], set()

    def add(text):
        if text not in seen:
            seen.add(text)
            lines.append(text)

    # 1) 服务器走新加坡的域名 -> 必须进隧道
    for dom in sorted(sg_all):
        add(f'  - DOMAIN-SUFFIX,{dom},PROXY')

    # 2) 服务器走香港的域名 -> 进隧道(香港出口)，国内域名除外
    for dom in sorted(direct_all):
        if dom in CN_DOMAINS:
            continue
        add(f'  - DOMAIN-SUFFIX,{dom},PROXY')

    # 3) 国内域名 -> 本地直连
    for dom in sorted(CN_DOMAINS & direct_all):
        add(f'  - DOMAIN-SUFFIX,{dom},DIRECT')

    return lines


HEADER = """  # ===== 服务端分流域名同步 (由 scripts/sync-domains.py 生成) =====
  # 数据来源: 服务器 sing-box /opt/socks5-server/config.json 的 route.rules
  # 映射原则:
  #   服务端判新加坡  -> 客户端 PROXY (进隧道, 由服务器转新加坡)
  #   服务端判香港    -> 客户端 PROXY (进隧道, 由服务器用香港 IP 出口)
  #   纯国内域名      -> 客户端 DIRECT (省隧道带宽, 更快)
  # 注意: 服务器端规则才是最终裁决, 客户端这份是同源镜像, 避免域名漏匹配
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('config', help='服务器端 sing-box config.json 路径')
    ap.add_argument('-o', '--out', help='输出文件 (默认打印到 stdout)')
    args = ap.parse_args()

    with open(args.config, encoding='utf-8') as f:
        cfg = json.load(f)

    direct_all, sg_all = collect(cfg)
    rules = gen_rules(direct_all, sg_all)

    body = HEADER + '\n'.join(rules) + '\n'
    if args.out:
        with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
        print(f'已生成 {args.out}，共 {len(rules)} 条规则')
    else:
        sys.stdout.write(body)




def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('config', help='服务器端 sing-box config.json 路径')
    ap.add_argument('-o', '--out', help='输出文件 (默认打印到 stdout)')
    args = ap.parse_args()
    with open(args.config, encoding='utf-8') as f:
        cfg = json.load(f)
    direct_all, sg_all = collect(cfg)
    rules = gen_rules(direct_all, sg_all)
    body = HEADER + '\n'.join(rules) + '\n'
    if args.out:
        with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
        print(f'已生成 {args.out}，共 {len(rules)} 条规则')
    else:
        sys.stdout.write(body)


if __name__ == '__main__':
    main()
