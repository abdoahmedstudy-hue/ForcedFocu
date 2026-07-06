import os

daemon_file = "/Users/aboda/Documents/ForcedFocu/daemon/forcefocus_daemon.py"
with open(daemon_file, "r") as f:
    lines = f.readlines()

# The constants block starts at line 46: COMMON_PREFIXES = (
# and ends at line 414: ]
start_idx = -1
end_idx = -1

for i, line in enumerate(lines):
    if line.startswith("COMMON_PREFIXES = ("):
        start_idx = i
    elif line.startswith("    \"about:policies\",") and lines[i+1].startswith("]"):
        end_idx = i + 1

if start_idx != -1 and end_idx != -1:
    print(f"Removing lines {start_idx} to {end_idx}")
    new_lines = lines[:start_idx-1] + ["from forcefocus.constants import *\n"] + lines[end_idx+1:]
    with open(daemon_file, "w") as f:
        f.writelines(new_lines)
    print("Done.")
else:
    print("Could not find start/end indices.")
    print("Start:", start_idx, "End:", end_idx)
