---
name: amazon-rufus
description: >
  Use this skill when the user wants to scrape Amazon Rufus AI FAQ Q&A for a product.
  Triggers when an Amazon ASIN (e.g. "B0DN9WR2TX") is provided alongside keywords like:
  Rufus, Rufus FAQ, Rufus采集, FAQ抓取, Amazon product Q&A, scrape Rufus, collect FAQ.
  Handles the full pipeline: Chrome setup → config → scrape → save to Feishu or Excel.
version: 2.1.0
---

# Amazon Rufus FAQ Scraper

自动从 Amazon 产品页 Rufus AI 助手采集默认 FAQ 问答（含图片），保存至飞书多维表格或本地 Excel。

---

## 路径说明（Path Resolution）

`CLAUDE_SKILL_DIR` 在所有命令中指向本 `SKILL.md` 所在目录：

| 运行环境 | 如何获取 `CLAUDE_SKILL_DIR` |
|---------|---------------------------|
| **Claude Code** | 自动注入，无需操作 |
| **Hermes / OpenClaw** | 本 `SKILL.md` 所在目录即为技能根目录。<br>例：若 `SKILL.md` 位于 `/home/user/.hermes/skills/amazon-rufus/SKILL.md`，则 `CLAUDE_SKILL_DIR=/home/user/.hermes/skills/amazon-rufus` |
| **直接调用** | `export CLAUDE_SKILL_DIR=/path/to/amazon-rufus` |

---

## 执行命令

**推荐**：使用单一入口脚本，内置全流程、自动路径发现：

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/run.sh" --asin <ASIN>
```

首次运行（含飞书凭证，非交互）：
```bash
# 飞书模式
bash "${CLAUDE_SKILL_DIR}/scripts/run.sh" \
  --asin <ASIN> \
  --output feishu \
  --app-id <APP_ID> \
  --app-secret <APP_SECRET>

# Excel 模式（无需飞书）
bash "${CLAUDE_SKILL_DIR}/scripts/run.sh" \
  --asin <ASIN> \
  --output excel \
  --output-dir ~/Desktop/rufus-faq
```

**`run.sh` 全部参数：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--asin` | Amazon ASIN（必填） | — |
| `--output` | `feishu` 或 `excel`（首次必填） | 读取已有配置 |
| `--app-id` | 飞书 App ID | — |
| `--app-secret` | 飞书 App Secret | — |
| `--output-dir` | Excel 保存目录 | `~/Desktop/rufus-faq` |
| `--wait` | 每道题等待 Rufus 回复的秒数 | `8` |

---

## 成功输出（JSON）

```json
{
  "ok": true,
  "mode": "feishu",
  "bitable_url": "https://...",
  "asin": "B0DN9WR2TX",
  "qa_count": 5,
  "qa_with_images": 2,
  "is_new_product": true
}
```

或 Excel 模式：
```json
{
  "ok": true,
  "mode": "excel",
  "file": "/Users/xxx/Desktop/rufus-faq/rufus_faq_B0DN9WR2TX_20240101_120000.xlsx",
  "asin": "B0DN9WR2TX",
  "qa_count": 5,
  "qa_with_images": 2
}
```

向用户展示结果时：

```
✅ 采集完成！

产品：<product_name>
ASIN：<asin>
FAQ 条数：<qa_count> 条（其中 <qa_with_images> 条含 Rufus 图片）

[飞书模式] 多维表格：<bitable_url>
[Excel 模式] 文件：<file>
```

---

## 常见错误处理

| 错误 / 现象 | 原因 | 解决 |
|------------|------|------|
| `chrome: NOT FOUND` | Chrome 未开启远程调试 | 打开 `chrome://inspect/#remote-debugging` → 勾选 Allow remote debugging |
| FAQ 为空 / Rufus pills not found | **Chrome 未登录 Amazon**（最常见） | 在 Chrome 中登录美区 Amazon 后重试 |
| FAQ 为空 | 页面加载太慢 | 加 `--wait 12` 重试 |
| `❌ 未找到有效配置` | 首次运行未初始化 | 加 `--output` 和对应参数（见上方示例） |
| 飞书凭证无效 | App ID/Secret 错误或应用未发布 | 在飞书开放平台重新获取或重新发布应用 |

---

## 系统要求

- **Node.js 18+**（CDP proxy 依赖）
- **Python 3.8+**（标准库，无需额外安装）
- **Google Chrome**（需开启远程调试 + 登录美区 Amazon）
- **飞书企业账户**（仅飞书模式需要；Excel 模式无需飞书）

---

## 数据结构

**飞书多维表格：**
```
├── 产品表     ASIN / 产品名称 / 链接 / 价格 / 评分 / 采集时间
└── Rufus QA  问题 / 答案 / Rufus图片 / 序号 / 产品（↔ 双向关联）
```

**Excel（两 sheet）：**
```
├── 产品信息  ASIN / 产品名称 / 价格 / 评分 / 采集时间 / 产品链接
└── Rufus QA  ASIN / 序号 / 问题 / 答案 / 图片数量 / 图片URLs
```

同一 ASIN 重复采集（飞书模式）→ 产品记录复用，QA 追加。

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `scripts/run.sh` | **主入口**：全流程自动化，自发现路径 |
| `scripts/check-deps.mjs` | Chrome CDP 检查 + proxy 启动 |
| `scripts/cdp-proxy.mjs` | CDP HTTP 代理 |
| `scripts/feishu_setup.py` | 配置：支持交互 / `--app-id`/`--app-secret` 非交互两种模式 |
| `scripts/scrape_rufus.py` | Rufus 抓取：开 tab → 读 pill → 提交 → 采集 |
| `scripts/feishu_upload.py` | 路由：飞书上传 or Excel 导出 |
| `scripts/excel_export.py` | stdlib xlsx 生成器（zipfile，无 pip） |
| `references/feishu_app_setup.md` | 飞书应用创建图文教程 |
