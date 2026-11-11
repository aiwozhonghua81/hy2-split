#!/usr/bin/env python3
"""
把服务器端分流域名同步到本机 Clash Verge。

流程:
  1) 从服务器拉取 /opt/socks5-server/config.json
  2) 用 sync-domains.py 生成 mihomo 规则块
  3) 写入 profile 文件 (profiles/<uid>.yaml)，带起止标记，可重复执行
  4) 同步写入运行时配置 clash-verge.yaml
  5) 通过命名管道让 mihomo 热重载 (不重启客户端，连接不断)

用法:
    python3 sync-to-clash.py                      # 默认路径自动识别
    python3 sync-to-clash.py --profile <uid.yaml> --dry-run
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mihomo_pipe  # noqa: E402
import sync_domains as gen  # noqa: E402

BASE = os.path.join(
    os.path.expanduser('~'),
    r'AppData\Roaming\io.github.clash-verge-rev.clash-verge-rev')

# profile 用两格缩进, 运行时文件是顶层列表(无缩进), 两套标记
START = '  # ===== 服务端分流域名同步'
END = '  # ===== 服务端分流域名同步结束'
RT_START = '# ===== 服务端分流域名同步'
RT_END = '# ===== 服务端分流域名同步结束'


def fetch_server_config(host, port, user, pw, hostkey, path='/opt/socks5-server/config.json'):
    """通过 plink 取服务器配置。"""
    cmd = ['plink', '-ssh', '-P', str(port), '-pw', pw, '-hostkey', hostkey,
           '-batch', f'{user}@{host}', f'cat {path}']
    out = subprocess.run(cmd, capture_output=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode('utf-8', 'replace'))
    return json.loads(out.stdout.decode('utf-8'))


def strip_blocks(text):
    """按行删除所有「服务端分流域名同步」块(忽略缩进)。

    坑: profile 用两格缩进, 运行时文件是顶层列表(无缩进), 标记文字相同但缩进不同,
    匹配时必须忽略缩进, 否则会出现「重复插入两块」。
    另外块里可能残留没有结束标记的孤儿块(上次写坏的), 也要一起清掉。
    """
    MARK = '服务端分流域名同步'
    out = []
    in_block = False
    removed = 0
    for line in text.split('\n'):
        if MARK in line:
            if '结束' in line:
                in_block = False
                removed += 1
            else:
                if in_block:
                    removed += 1   # 上一个块没闭合, 一起清掉
                in_block = True
                continue
            continue
        if in_block:
            continue
        out.append(line)
    return '\n'.join(out), removed


def reindent(block, dedent=False):
    """block 由 sync_domains 生成, 统一带两格缩进, 且自带起止标记。
    dedent=True 时去掉两格, 用于运行时文件(顶层列表, 无缩进)。"""
    lines = block.rstrip('\n').split('\n')
    if dedent:
        lines = [l[2:] if l.startswith('  ') else l for l in lines]
    lines.append('  # ===== 服务端分流域名同步结束')
    if dedent:
        lines[-1] = lines[-1][2:]
    return '\n'.join(lines)


def upsert_block(text, block, dedent=False):
    """先清掉所有旧块, 再插入新块到锚点前。返回 (新文本, 清理数量)。"""
    text, removed = strip_blocks(text)
    flat = reindent(block, dedent)
    for anchor in ('  # Original LAN / mainland China / fallback policies',
                   '- GEOIP,LAN,DIRECT,no-resolve'):
        if anchor in text:
            text = text.replace(anchor, flat + '\n\n' + anchor, 1)
            break
    else:
        raise RuntimeError('找不到插入锚点')
    return text, removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='154.36.165.71')
    ap.add_argument('--port', type=int, default=22)
    ap.add_argument('--user', default='root')
    ap.add_argument('--pw', default=os.environ.get('HK_PASS', ''))
    ap.add_argument('--hostkey', default=os.environ.get(
        'HK_HOSTKEY',
        'ssh-ed25519 255 SHA256:FemOeBQ1OEKtmlSRZF5WrjjoeJHJjOrjnaYYKIaAGd8'))
    ap.add_argument('--profile', default=None, help='profile 文件名，如 Lp40mQdLETnX.yaml')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    # 1) 找当前 profile
    if args.profile:
        profile = os.path.join(BASE, 'profiles', args.profile)
    else:
        py = os.path.join(BASE, 'profiles.yaml')
        txt = open(py, encoding='utf-8').read()
        cur = txt.split('current:')[1].split('\n')[0].strip()
        profile = os.path.join(BASE, 'profiles', f'{cur}.yaml')
    print(f'profile: {profile}')

    # 2) 拉服务器配置 + 生成规则
    cfg = fetch_server_config(args.host, args.port, args.user, args.pw, args.hostkey)
    direct_all, sg_all = gen.collect(cfg)
    rules = gen.gen_rules(direct_all, sg_all)
    block = gen.HEADER + '\n'.join(rules) + '\n'
    print(f'服务器域名: direct={len(direct_all)} sg={len(sg_all)} -> 客户端规则 {len(rules)} 条')

    if args.dry_run:
        print(block[:2000])
        return

    # 3) 写 profile
    backup = profile + '.bak-sync-' + __import__('time').strftime('%Y%m%d-%H%M%S')
    shutil_copy(profile, backup)
    text = open(profile, encoding='utf-8').read()
    text, removed = upsert_block(text, block, dedent=False)
    open(profile, 'w', encoding='utf-8', newline='\n').write(text)
    print(f'已更新 profile (备份 {os.path.basename(backup)}, 清理旧块 {removed} 处)')

    # 4) 写运行时配置
    rt = os.path.join(BASE, 'clash-verge.yaml')
    if os.path.exists(rt):
        shutil_copy(rt, rt + '.bak-sync-' + __import__('time').strftime('%Y%m%d-%H%M%S'))
        rtxt = open(rt, encoding='utf-8').read()
        rtxt, rremoved = upsert_block(rtxt, block, dedent=True)
        open(rt, 'w', encoding='utf-8', newline='\n').write(rtxt)
        print(f'已更新运行时配置 clash-verge.yaml (清理旧块 {rremoved} 处)')

    # 5) 热重载
    st, msg = mihomo_pipe.reload(rt)
    print(f'热重载: HTTP {st} {msg[:80]}')
    total = len(mihomo_pipe.api('/rules')['rules'])
    print(f'运行时生效规则总数: {total}')


def shutil_copy(a, b):
    import shutil
    shutil.copy2(a, b)


if __name__ == '__main__':
    main()
