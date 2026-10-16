"""账号完整引用；点分前缀表示分组，末段为组内引用名。"""

import re

ACCOUNT_REFERENCE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
