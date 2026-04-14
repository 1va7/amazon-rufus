# amazon-rufus

A [Claude Code](https://claude.ai/code) skill that scrapes Amazon product FAQ answers from Rufus AI and saves them to a Feishu Bitable.

## What it does

Give Claude an Amazon ASIN → it opens the product page in your Chrome, reads the default Rufus FAQ suggestions, submits each question, captures the answers (including any images Rufus returns), and writes everything to a Feishu 多维表格 with a two-table structure:

```
Feishu Bitable
├── 产品表     ASIN / 产品名称 / 链接 / 价格 / 评分 / 采集时间
└── Rufus QA  问题 / 答案 / Rufus图片 / 序号 / 产品（↔ 产品表，双向关联）
```

Same ASIN scraped again → reuses the existing product record, appends new QA rows.

## Install

```bash
npx github:1va7/amazon-rufus
```

Requires Node.js 18+. Copies the skill into Claude Code's plugin directory and registers it automatically.

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| [Claude Code](https://claude.ai/code) | The CLI this skill runs inside |
| Google Chrome | Must have remote debugging enabled (guided on first run) |
| Node.js 18+ | For the CDP proxy bundled with this skill |
| Python 3.10+ | Standard library only, no pip installs needed |
| Feishu enterprise account | To create a self-hosted app (guided on first run) |

## Usage

After installing, restart Claude Code and say something like:

> 帮我采集这个产品的 Rufus FAQ，ASIN: B0DN9WR2TX

or in English:

> Scrape the Rufus FAQ for ASIN B0DN9WR2TX

Claude will handle the rest. **First run** walks you through two one-time setup steps:

### Step 1 — Enable Chrome remote debugging

1. Open Google Chrome
2. Go to `chrome://inspect/#remote-debugging`
3. Check **"Allow remote debugging for this browser instance"**

Done once, survives Chrome restarts.

### Step 2 — Create a Feishu app

1. Go to [open.feishu.cn/app](https://open.feishu.cn/app) → **创建企业自建应用**
2. Enable permissions: `bitable:app` and `drive:drive`
3. Publish the app
4. Copy the **App ID** and **App Secret** from 凭证与基础信息

Claude will prompt you for these, then automatically create the Bitable with both tables and the bidirectional link field.

Config is saved to `~/.config/amazon-rufus/config.json` — you only do this once.

## How it works

```
User gives ASIN
      ↓
check-deps.mjs       — verify Chrome CDP + start proxy (localhost:3456)
      ↓
feishu_setup.py      — verify Feishu config (or guide first-time setup)
      ↓
scrape_rufus.py      — open amazon.com/dp/<ASIN> in background Chrome tab
                       read Rufus default pill questions
                       submit each via text input, wait for answer
                       capture Q&A text + any product images
                       close tab, output JSON
      ↓
feishu_upload.py     — check ASIN in 产品表 (dedup)
                       create/reuse product record
                       upload images to Feishu drive
                       create QA records linked to product
      ↓
Return Bitable URL + summary to user
```

## File structure

```
amazon-rufus/
├── SKILL.md                       Claude Code skill definition
├── bin/
│   └── install.mjs                npx installer
├── scripts/
│   ├── cdp-proxy.mjs              Chrome DevTools Protocol HTTP proxy
│   ├── check-deps.mjs             Environment check + proxy startup
│   ├── feishu_setup.py            First-time Feishu app + Bitable setup
│   ├── scrape_rufus.py            CDP-based Rufus scraper
│   └── feishu_upload.py           Feishu upload (two-table, dedup)
└── references/
    └── feishu_app_setup.md        Feishu app creation guide (Chinese)
```

## Configuration

`~/.config/amazon-rufus/config.json` (auto-generated on first run):

```json
{
  "feishu": {
    "app_id": "cli_xxx",
    "app_secret": "xxx"
  },
  "bitable": {
    "base_token": "xxx",
    "products_table_id": "tblxxx",
    "qa_table_id": "tblxxx",
    "url": "https://..."
  }
}
```

To reset: `python3 ~/.claude/plugins/marketplaces/amazon-rufus/plugins/amazon-rufus/skills/amazon-rufus/scripts/feishu_setup.py --reset`

## Credits

- CDP proxy adapted from [eze-is/web-access](https://github.com/eze-is/web-access) (MIT)

## License

MIT
