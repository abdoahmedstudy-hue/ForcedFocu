import re

with open("tests/test_forcefocus_cli.py", "r") as f:
    content = f.read()

# Replace the conflict markers and keep both test classes
fixed_content = re.sub(
    r"<<<<<<< HEAD\n(.*?)\n=======\n(.*?)>>>>>>> bd76397[^\n]*\n",
    r"\1\n\n\2\n",
    content,
    flags=re.DOTALL,
)

with open("tests/test_forcefocus_cli.py", "w") as f:
    f.write(fixed_content)
# I will replace the conflict markers with just both blocks.
# The structure is:
# <<<<<<< HEAD
# class TestCmdStart...
# =======
# import socket
# import json
# import os
#
# class TestSendCommand...
# >>>>>>> origin/main

# First let's extract the two blocks
head_match = re.search(
    r"<<<<<<< HEAD\n(.*?)\n=======\n(.*?)>>>>>>> origin/main", content, re.DOTALL
)

if head_match:
    head_content = head_match.group(1)
    main_content = head_match.group(2)

    # Let's move imports from main_content to the top, but for simplicity, we can just let python parse them where they are if they are just imports.
    # Actually, better to just put them in sequence.
    new_content = (
        content[: head_match.start()]
        + head_content
        + "\n\n"
        + main_content
        + content[head_match.end() :]
    )

    with open("tests/test_forcefocus_cli.py", "w") as f:
        f.write(new_content)

    print("Conflict resolved in script")
else:
    print("No conflict markers found")
