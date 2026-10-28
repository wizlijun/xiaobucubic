#!/usr/bin/env python3
"""Read-only hardware smoke check; does not claim to test Internet reachability."""
import argparse
import ipaddress
import json
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("url", help="Router URL, e.g. http://192.168.2.2")
parser.add_argument("--require-client", action="store_true")
args = parser.parse_args()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(args.url.rstrip("/") + "/api/status", timeout=5) as response:
    status = json.load(response)
checks = {
    "DHCP server running": status.get("dhcp_running") is True,
    "USB attached": status.get("usb_attached") is True,
    "IPv4 NAT enabled": status.get("nat_ready") is True,
    "No subnet overlap": status.get("subnet_conflict") is False,
}
if args.require_client:
    network = ipaddress.ip_network(status["ap_ip"] + "/24", strict=False)
    checks["Client has a DHCP address"] = any(
        ipaddress.ip_address(address) in network for address in status.get("client_ips", [])
    )
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}: {name}")
print(json.dumps(status, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
