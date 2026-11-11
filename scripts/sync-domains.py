#!/usr/bin/env python3
r"""从服务器端 sing-box 配置生成本地 mihomo(Clash Verge) 的分流规则块。

用法:
    python3 sync-domains.py /path/to/server_config.json [-o out.txt]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_domains import main  # noqa: E402

if __name__ == '__main__':
    main()
