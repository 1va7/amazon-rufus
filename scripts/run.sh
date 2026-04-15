#!/usr/bin/env bash
# Amazon Rufus FAQ Scraper — universal single-command entrypoint
#
# Works across Claude Code, Hermes, OpenClaw, or direct shell invocation.
# Self-discovers its own location — no CLAUDE_SKILL_DIR pre-set required.
#
# Usage:
#   bash run.sh --asin B0DN9WR2TX
#   bash run.sh --asin B0DN9WR2TX --output excel --output-dir ~/Desktop/rufus-faq
#   bash run.sh --asin B0DN9WR2TX --output feishu --app-id cli_xxx --app-secret xxx
#
# Prerequisites:
#   - Google Chrome with remote debugging enabled (chrome://inspect/#remote-debugging)
#   - Chrome logged in to US Amazon account (Rufus only shows to logged-in users)
#   - Node.js 18+  (CDP proxy)
#   - Python 3.8+  (stdlib only, no pip needed)

set -euo pipefail

# ── Path discovery ──────────────────────────────────────────────────────────────
# CLAUDE_SKILL_DIR is injected by Claude Code automatically.
# For all other runtimes, derive it from this script's own location.
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
CLAUDE_SKILL_DIR="${CLAUDE_SKILL_DIR:-$(dirname "$SCRIPTS_DIR")}"
export CLAUDE_SKILL_DIR

# ── Argument parsing ────────────────────────────────────────────────────────────
ASIN=""
APP_ID=""
APP_SECRET=""
OUTPUT_MODE=""
OUTPUT_DIR=""
WAIT=8

usage() {
    echo "Usage: $(basename "$0") --asin <ASIN> [options]"
    echo ""
    echo "Options:"
    echo "  --asin <ASIN>           Amazon product ASIN (required)"
    echo "  --output feishu|excel   Output mode (uses saved config if omitted)"
    echo "  --app-id <id>           Feishu App ID (for non-interactive Feishu setup)"
    echo "  --app-secret <secret>   Feishu App Secret (for non-interactive Feishu setup)"
    echo "  --output-dir <path>     Excel output directory (default: ~/Desktop/rufus-faq)"
    echo "  --wait <seconds>        Wait per Rufus answer (default: 8)"
    echo "  -h, --help              Show this message"
    echo ""
    echo "Examples:"
    echo "  $(basename "$0") --asin B0DN9WR2TX"
    echo "  $(basename "$0") --asin B0DN9WR2TX --output excel"
    echo "  $(basename "$0") --asin B0DN9WR2TX --output feishu --app-id cli_xxx --app-secret xxx"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --asin)        ASIN="$2";        shift 2 ;;
        --app-id)      APP_ID="$2";      shift 2 ;;
        --app-secret)  APP_SECRET="$2";  shift 2 ;;
        --output)      OUTPUT_MODE="$2"; shift 2 ;;
        --output-dir)  OUTPUT_DIR="$2";  shift 2 ;;
        --wait)        WAIT="$2";        shift 2 ;;
        -h|--help)     usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

if [[ -z "$ASIN" ]]; then
    echo "❌ --asin is required" >&2
    usage >&2
    exit 1
fi

# ── Step 1: Chrome CDP ──────────────────────────────────────────────────────────
echo "[1/4] 检查 Chrome CDP..." >&2
if ! node "$CLAUDE_SKILL_DIR/scripts/check-deps.mjs"; then
    echo "" >&2
    echo "❌ Chrome CDP 检查失败，请按以上提示操作后重试" >&2
    exit 1
fi
echo "" >&2

# ── Step 2: Config ──────────────────────────────────────────────────────────────
echo "[2/4] 检查配置..." >&2
CONFIG_OK=0
if python3 "$CLAUDE_SKILL_DIR/scripts/feishu_setup.py" --check 2>/dev/null; then
    CONFIG_OK=1
fi

if [[ "$CONFIG_OK" -eq 0 ]]; then
    if [[ "$OUTPUT_MODE" == "excel" ]]; then
        SETUP_ARGS=(--output excel)
        [[ -n "$OUTPUT_DIR" ]] && SETUP_ARGS+=(--output-dir "$OUTPUT_DIR")
        python3 "$CLAUDE_SKILL_DIR/scripts/feishu_setup.py" "${SETUP_ARGS[@]}"
    elif [[ -n "$OUTPUT_MODE" && -n "$APP_ID" && -n "$APP_SECRET" ]]; then
        python3 "$CLAUDE_SKILL_DIR/scripts/feishu_setup.py" \
            --output "$OUTPUT_MODE" \
            --app-id "$APP_ID" \
            --app-secret "$APP_SECRET"
    else
        echo "" >&2
        echo "❌ 未找到有效配置。请用以下命令完成初始化（二选一）：" >&2
        echo "" >&2
        echo "  飞书模式：" >&2
        echo "    python3 \"$CLAUDE_SKILL_DIR/scripts/feishu_setup.py\" \\" >&2
        echo "        --output feishu --app-id <APP_ID> --app-secret <APP_SECRET>" >&2
        echo "" >&2
        echo "  Excel 模式：" >&2
        echo "    python3 \"$CLAUDE_SKILL_DIR/scripts/feishu_setup.py\" --output excel" >&2
        echo "" >&2
        echo "  或者在 run.sh 中直接传入 --output 和相关参数" >&2
        exit 1
    fi
fi
echo "" >&2

# ── Step 3: Scrape ──────────────────────────────────────────────────────────────
echo "[3/4] 采集 Rufus FAQ (ASIN: $ASIN)..." >&2
TMPFILE="/tmp/rufus_data_${ASIN}_$$.json"
trap 'rm -f "$TMPFILE"' EXIT

if ! python3 "$CLAUDE_SKILL_DIR/scripts/scrape_rufus.py" \
        --asin "$ASIN" --wait "$WAIT" > "$TMPFILE"; then
    echo "❌ 采集失败。如果 Rufus FAQ 为空，请确认 Chrome 已登录美区 Amazon 账户" >&2
    exit 1
fi
echo "" >&2

# ── Step 4: Upload / Export ─────────────────────────────────────────────────────
echo "[4/4] 保存结果..." >&2
python3 - "$TMPFILE" "$CLAUDE_SKILL_DIR/scripts/feishu_upload.py" <<'PYEOF'
import json, sys, subprocess

tmpfile, upload_script = sys.argv[1], sys.argv[2]

with open(tmpfile) as f:
    data = json.load(f)

cmd = [
    'python3', upload_script,
    '--asin',         data['asin'],
    '--product-name', data['product_name'],
    '--product-url',  data['product_url'],
    '--price',        data.get('price', ''),
    '--rating',       data.get('rating', ''),
    '--faqs-json',    json.dumps(data['faqs'], ensure_ascii=False),
]
result = subprocess.run(cmd, capture_output=True, text=True)
sys.stderr.write(result.stderr)
if result.returncode != 0:
    sys.exit(1)
print(result.stdout)
PYEOF
