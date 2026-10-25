#!/bin/bash
# 扫描工作区中的凭证模式，命中即失败。注意：本脚本自身被排除，避免自匹配。
PATTERN='gho_|ghp_|github_pat_|BINANCE_API_SECRET|oauth_token|BEGIN (RSA|OPENSSH|EC) PRIVATE|sk-[A-Za-z0-9]{20}'
if grep -rnE --exclude-dir=.git --exclude=check-creds.sh "$PATTERN" .; then
  echo "BLOCKED: possible credential found" >&2
  exit 1
fi
echo "OK: no credential patterns found"
exit 0
