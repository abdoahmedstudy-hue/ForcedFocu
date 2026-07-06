active_iface = "en0"
upstream_dns = "8.8.8.8"
DOH_IPS = ["1.1.1.1", "8.8.8.8"]

tables = [
    "table <ff_blocked_ips> persist",
    "table <ff_whitelisted_ips> persist",
]
translations = []
filters = [
    "pass out quick on lo0 all",
    "pass in quick on lo0 all",
]

if upstream_dns:
    filters.append(f"pass out quick proto {{tcp udp}} from any to {upstream_dns} port 53")
else:
    filters.append("pass out quick proto {tcp udp} from any to any port 53")

filters.extend(
    [
        "block return out proto udp from any to any port 443",
        "block return out proto {tcp udp} from any to any port 853",
        "block return out proto {tcp udp} from any to any port {1080, 8080, 3128, 9050, 9051}",
        "block return out proto {tcp udp} from any to any port 51820",
        "block return out proto {tcp udp} from any to any port 1194",
        "block return out proto {tcp udp} from any to any port {500, 4500}",
        "block return out proto {tcp udp} from any to any port {1723, 1701}",
        "block return out proto {tcp udp} from any to any port {8388, 8389}",
        "block return out proto {tcp udp} from any to any port {10808, 10809}",
        "block return out proto {tcp udp} from any to any port {7890, 7891, 7892, 7893}",
        "block return out proto tcp from any to any port 22",
        "block return out quick from any to <ff_blocked_ips>",
    ]
)

translations.append("rdr pass on lo0 proto tcp from any to any port 443 -> 127.0.0.1 port 8443")
filters.extend(
    [
        "pass out quick from any to <ff_whitelisted_ips>",
        f"pass out on {active_iface} route-to lo0 proto tcp from any to any port 443",
        "block return out proto tcp from any to any port 80",
    ]
)

for ip in DOH_IPS:
    filters.append(f"block return out proto tcp from any to {ip} port 443")

rules_str = "\n".join(tables + translations + filters) + "\n"

import subprocess
p = subprocess.run(["pfctl", "-n", "-f", "-"], input=rules_str.encode(), capture_output=True)
print("Returncode:", p.returncode)
print("STDOUT:", p.stdout.decode())
print("STDERR:", p.stderr.decode())
