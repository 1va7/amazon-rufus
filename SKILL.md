---
name: amazon-rufus
description: This skill should be used when the user wants to scrape Amazon Rufus FAQ Q&A data for a product and save it to a Feishu Bitable. Triggers when the user provides an Amazon ASIN (format like "B0DN9WR2TX" or "asin: B0DN9WR2TX") and mentions scraping Rufus, collecting FAQ answers, Amazon product Q&A, Rufus采集, FAQ抓取, or similar. Handles the full end-to-end flow: Chrome setup, scraping, and Feishu upload. No prior setup assumed.
version: 2.0.0
---

# Amazon Rufus FAQ Scraper

从 Amazon 产品页的 Rufus AI 助手中自动采集默认 FAQ 问答（含回复图片），写入飞书多维表格（产品表 + QA 表，双向关联）。

## 数据结构

```
飞书多维表格
├── 产品表        ASIN / 产品名称 / 链接 / 价格 / 评分 / 采集时间 / [Rufus QA]
└── Rufus QA 表  问题 / 答案 / Rufus图片 / 序号 / [产品]（双向关联）
```

同一 ASIN 重复采集时，产品记录复用，QA 记录追加。

---

## 执行流程

### Step 0 — 确认 ASIN

从用户消息中提取 ASIN（10 位字母数字，如 `B0DN9WR2TX`）。若不确定，向用户确认后再继续。

### Step 1 — 检查 Chrome CDP 环境

```bash
node "${CLAUDE_SKILL_DIR}/scripts/check-deps.mjs"
```

**若输出 `chrome: NOT FOUND`：**
提示用户完成以下操作（完成后再次运行脚本确认）：
1. 打开 Google Chrome
2. 地址栏输入 `chrome://inspect/#remote-debugging`
3. 勾选 **"Allow remote debugging for this browser instance"**

**若输出 `proxy: ready`：** 继续下一步。

向用户展示以下提示后继续：
> 温馨提示：部分站点对浏览器自动化操作检测严格，存在账号封禁风险。已内置防护措施但无法完全避免，继续操作即视为接受。

### Step 2 — 检查飞书配置

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/feishu_setup.py" --check
```

**若配置不存在或无效：**
运行首次配置引导（交互模式，需用户输入）：
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/feishu_setup.py"
```

脚本会引导用户：
- 创建飞书自建应用（详细步骤见 `${CLAUDE_SKILL_DIR}/references/feishu_app_setup.md`）
- 输入 App ID 和 App Secret
- 自动创建包含两张表的多维表格
- 保存配置至 `~/.config/amazon-rufus/config.json`

**若配置有效：** 继续下一步。

### Step 3 — 抓取 Rufus FAQ

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/scrape_rufus.py" \
  --asin "<ASIN>" \
  > /tmp/rufus_data.json
```

脚本自动完成：
1. 在新后台 tab 中打开 `amazon.com/dp/<ASIN>`
2. 等待页面加载，读取 Rufus 默认 pill 问题（页面首次加载时显示的那几条）
3. 逐条通过文本输入框提交问题，等待 Rufus 回复
4. 采集每条 Q&A 及 Rufus 回复中的图片 URL
5. 关闭 tab，输出 JSON 到 stdout

若脚本报错 `Rufus pills not found`，可能原因：
- 页面加载太慢：重试时加 `--wait 12`
- Amazon 地区限制：确认 Chrome 已登录美区 Amazon 账户

### Step 4 — 上传至飞书

```bash
cat /tmp/rufus_data.json | python3 -c "
import json, sys, subprocess
data = json.load(sys.stdin)
result = subprocess.run([
    'python3', '${CLAUDE_SKILL_DIR}/scripts/feishu_upload.py',
    '--asin',         data['asin'],
    '--product-name', data['product_name'],
    '--product-url',  data['product_url'],
    '--price',        data['price'],
    '--rating',       data['rating'],
    '--faqs-json',    json.dumps(data['faqs'], ensure_ascii=False),
], capture_output=True, text=True)
print(result.stdout)
if result.returncode != 0:
    print('STDERR:', result.stderr, file=sys.stderr)
"
```

### Step 5 — 返回结果

解析上一步的 JSON 输出，向用户展示：

```
✅ 采集完成！

产品：<product_name>
ASIN：<asin>
FAQ 条数：<qa_count> 条（其中 <qa_with_images> 条含 Rufus 图片）
产品记录：<新建 / 已存在复用>

飞书多维表格：<bitable_url>
```

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `scripts/check-deps.mjs` | 检查 Chrome CDP + 启动 proxy（自包含，无需 web-access） |
| `scripts/cdp-proxy.mjs`  | CDP HTTP 代理（来自 eze-is/web-access，MIT 许可） |
| `scripts/feishu_setup.py`| 首次配置：引导创建飞书应用 + 建表 + 保存 config |
| `scripts/scrape_rufus.py`| CDP 抓取脚本：打开 Amazon → 读 pill → 提交 → 采集 |
| `scripts/feishu_upload.py`| 上传至飞书：ASIN 去重 + 建产品记录 + 建 QA 记录 |
| `references/feishu_app_setup.md` | 飞书应用创建图文教程 |

## 用户配置文件

`~/.config/amazon-rufus/config.json`（首次运行后自动生成）：
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

## 系统要求

- **Node.js 22+**（CDP proxy 依赖）
- **Python 3.10+**（标准库，无需额外安装）
- **Google Chrome**（需开启远程调试，见 Step 1）
- **飞书企业账户**（创建自建应用，见 Step 2）
