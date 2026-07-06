import re

with open("daemon/forcefocus_daemon.py", "r") as f:
    code = f.read()

pattern = r'                self\.sni_proxy\.start_sync\(host="127\.0\.0\.1", port=8443\)\n        except Exception as exc:\n            logging\.error\("Failed to start SNI proxy: %s", exc\)\n'

code = re.sub(pattern, '', code, flags=re.DOTALL)

with open("daemon/forcefocus_daemon.py", "w") as f:
    f.write(code)

