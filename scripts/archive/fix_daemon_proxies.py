import re

with open("daemon/forcefocus_daemon.py", "r") as f:
    code = f.read()

pattern = r'    def _start_dns_proxy\(self\):.*?return True'

code = re.sub(pattern, '    # Proxy methods moved to enforcement/dns.py', code, flags=re.DOTALL)

with open("daemon/forcefocus_daemon.py", "w") as f:
    f.write(code)

