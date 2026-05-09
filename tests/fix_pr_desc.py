import re

with open("pr_description.md", "r") as f:
    content = f.read()

# Replace the conflict markers and keep both sections appended
fixed_content = re.sub(
    r"<<<<<<< HEAD\n(.*?)\n=======\n(.*?)>>>>>>> 47654f3[^\n]*\n",
    r"\1\n\n\2\n",
    content,
    flags=re.DOTALL,
)

with open("pr_description.md", "w") as f:
    f.write(fixed_content)
