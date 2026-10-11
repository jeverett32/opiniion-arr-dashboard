# Retired Proxmox LXC 108 (`arr-dashboard`)

This app previously ran on Proxmox **CT 108** (Ubuntu, Docker, `/opt/arr_dashboard`). The LXC was removed after the app moved to this repo. Use Docker on any host instead (see [DEPLOY.md](../DEPLOY.md)).

## Former container config (2026-10-11)

```
arch: amd64
cores: 2
hostname: arr-dashboard
memory: 2048
ostype: ubuntu
rootfs: local-lvm:vm-108-disk-0,size=12G
swap: 512
features: nesting=1
net0: dhcp on vmbr0
onboot: 0
```

## What was on the LXC

| Item | Location |
|------|----------|
| App + compose | `/opt/arr_dashboard` |
| SQLite data | `/opt/arr_dashboard/data/arr.db` (Docker volume `arr_data` in compose) |
| App port | `8000` |
| Tailscale | `tailscaled` enabled; hostname `arr-dashboard` |
| Optional tunnel | `scripts/setup_cloudflare_tunnel.sh` or compose `tunnel` profile |

Copy `data/arr.db` from backups if you need the old production DB; otherwise run `python db.py` to seed.
