#!/bin/bash
# 手动更新房源数据：抓取两个论坛 → 更新 docs/data.json → 推送到 GitHub
#
#   ./update.sh
#
# 想起来就跑一次，不跑也没关系：已有房源不会因为没更新而消失。
# 全程大约 1–3 分钟（只抓没见过的新帖，老帖直接复用）。
#
# 为什么必须在本机跑：bay123 和 chineseinsfbay 都封 GitHub 机房 IP
# （bay123 返回 403，cis 返回 0 字节），只有住宅网络才抓得到。
# 云端定时任务已于 2026-08-30 停用，不跑这个脚本就不会有新房源。

set -uo pipefail
cd "$(dirname "$0")" || exit 1

PY=".venv/bin/python"

say(){ printf "\n\033[1m%s\033[0m\n" "$1"; }

# --- 依赖 ---
if [ ! -x "$PY" ]; then
  say "首次运行，正在创建 Python 环境…"
  python3 -m venv .venv || { echo "创建失败，请确认装了 python3"; exit 1; }
  .venv/bin/pip install -q -r requirements.txt || { echo "装依赖失败"; exit 1; }
fi

before=$($PY -c "import json;print(len(json.load(open('docs/data.json'))['points']))" 2>/dev/null || echo 0)

# --- 先同步远端（云端每日任务也会提交数据）---
say "同步远端…"
if ! git pull --rebase --autostash --quiet origin main; then
  git rebase --abort 2>/dev/null
  echo "同步失败，可能是网络问题或有冲突。先手动跑一次 git pull 看看。"
  exit 1
fi

# --- 抓取 ---
say "开始抓取（1–3 分钟，请稍候）…"
$PY scraper/scrape.py
rc=$?
if [ $rc -ne 0 ]; then
  echo "抓取脚本出错（退出码 $rc），数据未提交。"
  exit $rc
fi

# --- 提交推送：只碰数据文件，你自己改的东西一律不动 ---
if [ -z "$(git status --porcelain docs/data.json state/seen.json state/last_run.json)" ]; then
  say "数据没有变化，无需推送。"
  exit 0
fi

after=$($PY -c "import json;print(len(json.load(open('docs/data.json'))['points']))")
git add docs/data.json state/seen.json state/last_run.json
git -c user.name="rental-map-bot" -c user.email="actions@users.noreply.github.com" \
    commit -q -m "更新房源数据 $(date '+%Y-%m-%d %H:%M')"

say "推送到 GitHub…"
if ! git push --quiet origin main 2>/dev/null; then
  echo "推送被拒（云端可能刚好也提交了），重试一次…"
  git pull --rebase --quiet -X ours origin main && git push --quiet origin main \
    || { echo "推送失败，请手动跑：git push origin main"; exit 1; }
fi

down=$($PY -c "import json;print(','.join(json.load(open('state/last_run.json'))['down']))" 2>/dev/null)
[ -n "$down" ] && printf "\n\033[33m注意：%s 这次一条都没抓到，该来源的房源已保护不淘汰\033[0m\n" "$down"

say "完成：房源 $before → $after 条，约 1 分钟后 https://askaibay.com 生效。"
