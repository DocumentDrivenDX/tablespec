"""Run the README quickstart: bash blocks between <!-- quickstart --> and <!-- /quickstart -->.

Blocks run in a temporary directory with `bash -euo pipefail`; `tablespec` must be on PATH
(CI puts a fresh venv's bin first). Usage: run_quickstart.py README.md
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

text = Path(sys.argv[1]).read_text()
section = re.search(r"<!-- quickstart -->(.*?)<!-- /quickstart -->", text, re.S)
if not section:
    sys.exit("quickstart markers not found")
blocks = re.findall(r"```(?:sh|bash)\n(.*?)```", section.group(1), re.S)
if not blocks:
    sys.exit("no sh blocks inside the quickstart markers")
with tempfile.TemporaryDirectory() as work:
    script = "\n".join(b for b in blocks if not b.lstrip().startswith("pip install"))
    print(script)
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script], cwd=work, timeout=300
    )
    sys.exit(result.returncode)
