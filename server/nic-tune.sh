#!/bin/bash
# 由 systemd 执行的网络调优（网卡设置重启后失效，需重新应用）
DEV=ens17
NCPU=$(nproc)
MASK=$(printf '%x' $(( (1 << NCPU) - 1 )))

# RPS: 将软中断分摊到所有 CPU 核心 (hy2 多 UDP 流场景收益明显)
for i in $(ls /sys/class/net/$DEV/queues/ 2>/dev/null | grep '^rx-'); do
  printf '%s' "$MASK" > /sys/class/net/$DEV/queues/$i/rps_cpus 2>/dev/null
  printf '%s' "4096" > /sys/class/net/$DEV/queues/$i/rps_flow_cnt 2>/dev/null
done

# XPS: 发送侧按队列分摊
for i in $(ls /sys/class/net/$DEV/queues/ 2>/dev/null | grep '^tx-'); do
  printf '%s' "f" > /sys/class/net/$DEV/queues/$i/xps_cpus 2>/dev/null
done

# ring buffer 拉满
ethtool -G $DEV rx 256 tx 256 2>/dev/null

# LRO 在虚拟网卡上有已知问题, 关闭
ethtool -K $DEV lro off 2>/dev/null

# UDP GRO 转发: QUIC/UDP 收包合并, 降低 CPU 占用
ethtool -K $DEV rx-udp-gro-forwarding on 2>/dev/null

echo "nic-tune applied: dev=$DEV rps=$MASK"
