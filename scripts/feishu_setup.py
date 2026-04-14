#!/usr/bin/env python3
"""
飞书首次配置脚本 — Amazon Rufus FAQ Skill

功能：
1. 引导用户填写飞书自建应用凭证
2. 验证凭证并检查权限
3. 创建 Bitable（多维表格）
4. 建立两张表：产品表 + Rufus QA 表
5. 在两表间建立双向关联字段
6. 保存配置到 ~/.config/amazon-rufus/config.json

用法：
  python3 feishu_setup.py               # 交互模式
  python3 feishu_setup.py --check       # 仅检查现有配置是否有效
  python3 feishu_setup.py --reset       # 清除现有配置并重新设置
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

CONFIG_PATH = os.path.expanduser("~/.config/amazon-rufus/config.json")
FEISHU_BASE = "https://open.feishu.cn"


# ── API helpers ────────────────────────────────────────────────────────────────

def feishu(method: str, path: str, body=None, token: str = None) -> dict:
    url = FEISHU_BASE + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"code": e.code, "error": e.read().decode()}


def get_token(app_id: str, app_secret: str) -> str | None:
    resp = feishu("POST", "/open-apis/auth/v3/tenant_access_token/internal",
                  {"app_id": app_id, "app_secret": app_secret})
    return resp.get("tenant_access_token")


# ── Config I/O ─────────────────────────────────────────────────────────────────

def load_config() -> dict | None:
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def save_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 配置已保存至 {CONFIG_PATH}")


# ── Setup steps ────────────────────────────────────────────────────────────────

def prompt_credentials() -> tuple[str, str]:
    print("\n" + "="*60)
    print("飞书自建应用配置")
    print("="*60)
    print("""
如果你还没有飞书自建应用，请按以下步骤创建：

  1. 打开 https://open.feishu.cn/app
  2. 点击「创建企业自建应用」
  3. 填写应用名称（如"Amazon Rufus FAQ"），保存
  4. 在「权限管理」中开通以下权限：
       - bitable:app（多维表格读写）
       - drive:drive（云文档管理，用于上传图片）
  5. 发布应用（在「版本管理与发布」中提交审核或直接发布）
  6. 在「凭证与基础信息」中找到 App ID 和 App Secret

详细图文教程见：
  {skill_dir}/references/feishu_app_setup.md
""")
    app_id = input("请输入 App ID: ").strip()
    app_secret = input("请输入 App Secret: ").strip()
    return app_id, app_secret


def create_bitable(token: str) -> str:
    """Create a new Bitable and return its app_token."""
    print("\n📊 创建多维表格...")
    resp = feishu("POST", "/open-apis/bitable/v1/apps",
                  {"name": "Amazon Rufus FAQ"}, token)
    if resp.get("code") != 0:
        raise RuntimeError(f"创建多维表格失败: {resp}")
    base_token = resp["data"]["app"]["app_token"]
    url = resp["data"]["app"]["url"]
    print(f"   ✓ 已创建：{url}")
    return base_token


def rename_default_table(token: str, base_token: str, default_table_id: str):
    """Rename the auto-created default table to 产品."""
    resp = feishu("PATCH",
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{default_table_id}",
        {"name": "产品"}, token)
    if resp.get("code") == 0:
        print("   ✓ 默认表已重命名为「产品」")
    else:
        print(f"   ⚠ 重命名失败（不影响使用）: {resp}")


def setup_products_table(token: str, base_token: str, table_id: str) -> dict[str, str]:
    """Add fields to 产品表. Returns {field_name: field_id}."""
    print("   添加产品表字段...")

    # Rename default primary field to 产品名称
    fields_resp = feishu("GET",
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/fields",
        token=token)
    default_fields = fields_resp.get("data", {}).get("items", [])
    if default_fields:
        dfid = default_fields[0]["field_id"]
        feishu("PUT",
            f"/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/fields/{dfid}",
            {"field_name": "产品名称", "type": 1}, token)

    field_defs = [
        {"field_name": "ASIN",    "type": 1},
        {"field_name": "产品链接", "type": 15},
        {"field_name": "价格",    "type": 1},
        {"field_name": "评分",    "type": 1},
        {"field_name": "采集时间", "type": 5,  "property": {"date_formatter": "yyyy-MM-DD HH:mm"}},
    ]
    field_ids = {"产品名称": default_fields[0]["field_id"] if default_fields else ""}
    for fd in field_defs:
        resp = feishu("POST",
            f"/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/fields",
            fd, token)
        fid = resp.get("data", {}).get("field", {}).get("field_id", "")
        field_ids[fd["field_name"]] = fid
        print(f"      ✓ {fd['field_name']}")
    return field_ids


def create_qa_table(token: str, base_token: str) -> str:
    """Create the Rufus QA table and return its table_id."""
    print("   创建 Rufus QA 表...")
    resp = feishu("POST", f"/open-apis/bitable/v1/apps/{base_token}/tables",
                  {"table": {"name": "Rufus QA"}}, token)
    if resp.get("code") != 0:
        raise RuntimeError(f"创建 QA 表失败: {resp}")
    qa_table_id = resp["data"]["table_id"]
    print(f"      ✓ 已创建 (id: {qa_table_id})")
    return qa_table_id


def setup_qa_table(token: str, base_token: str, qa_table_id: str) -> dict[str, str]:
    """Add fields to QA表. Returns field_ids."""
    print("   添加 QA 表字段...")

    # Rename default primary field to 问题
    fields_resp = feishu("GET",
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{qa_table_id}/fields",
        token=token)
    default_fields = fields_resp.get("data", {}).get("items", [])
    if default_fields:
        dfid = default_fields[0]["field_id"]
        feishu("PUT",
            f"/open-apis/bitable/v1/apps/{base_token}/tables/{qa_table_id}/fields/{dfid}",
            {"field_name": "问题", "type": 1}, token)

    field_defs = [
        {"field_name": "答案",    "type": 1},
        {"field_name": "Rufus图片","type": 17},
        {"field_name": "序号",    "type": 2},
    ]
    field_ids = {"问题": default_fields[0]["field_id"] if default_fields else ""}
    for fd in field_defs:
        resp = feishu("POST",
            f"/open-apis/bitable/v1/apps/{base_token}/tables/{qa_table_id}/fields",
            fd, token)
        fid = resp.get("data", {}).get("field", {}).get("field_id", "")
        field_ids[fd["field_name"]] = fid
        print(f"      ✓ {fd['field_name']}")
    return field_ids


def create_bidirectional_link(token: str, base_token: str,
                              products_table_id: str, qa_table_id: str):
    """Create bidirectional link: 产品表.Rufus QA ↔ QA表.产品"""
    print("   建立双向关联字段...")
    resp = feishu("POST",
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{products_table_id}/fields",
        {
            "field_name": "Rufus QA",
            "type": 21,
            "property": {
                "table_id": qa_table_id,
                "back_field_name": "产品"
            }
        }, token)
    if resp.get("code") == 0:
        link_fid = resp["data"]["field"]["field_id"]
        print(f"      ✓ 产品表.Rufus QA → QA表.产品 (fid: {link_fid})")
        return link_fid
    else:
        print(f"      ⚠ 双向关联创建失败: {resp}")
        return None


# ── Main ───────────────────────────────────────────────────────────────────────

def run_setup(reset: bool = False):
    # Load existing config
    cfg = None if reset else load_config()

    if cfg and not reset:
        print(f"找到现有配置: {CONFIG_PATH}")
        print(f"Bitable: {cfg.get('bitable_url', '未知')}")
        answer = input("是否跳过设置并直接使用现有配置？(Y/n): ").strip().lower()
        if answer != "n":
            print("✅ 使用现有配置")
            return cfg

    # Get credentials
    app_id, app_secret = prompt_credentials()

    print("\n🔑 验证凭证...")
    token = get_token(app_id, app_secret)
    if not token:
        print("❌ 凭证无效，请检查 App ID 和 App Secret")
        sys.exit(1)
    print("   ✓ 凭证有效")

    # Create bitable
    base_token = create_bitable(token)

    # Get default table id
    tables_resp = feishu("GET",
        f"/open-apis/bitable/v1/apps/{base_token}/tables", token=token)
    tables = tables_resp.get("data", {}).get("items", [])
    if not tables:
        raise RuntimeError("无法获取表列表")
    default_table_id = tables[0]["table_id"]

    print("\n📋 设置产品表...")
    rename_default_table(token, base_token, default_table_id)
    products_table_id = default_table_id
    setup_products_table(token, base_token, products_table_id)

    print("\n📋 设置 Rufus QA 表...")
    qa_table_id = create_qa_table(token, base_token)
    setup_qa_table(token, base_token, qa_table_id)

    print("\n🔗 建立表间双向关联...")
    create_bidirectional_link(token, base_token, products_table_id, qa_table_id)

    bitable_url = f"https://open.feishu.cn/base/{base_token}"
    cfg = {
        "feishu": {
            "app_id": app_id,
            "app_secret": app_secret,
        },
        "bitable": {
            "base_token": base_token,
            "products_table_id": products_table_id,
            "qa_table_id": qa_table_id,
            "url": bitable_url,
        }
    }
    save_config(cfg)
    print(f"\n🎉 初始化完成！")
    print(f"   多维表格地址: {bitable_url}")
    return cfg


def run_check():
    cfg = load_config()
    if not cfg:
        print(f"❌ 未找到配置文件: {CONFIG_PATH}")
        print("请运行 python3 feishu_setup.py 完成初始化")
        sys.exit(1)

    print(f"配置文件: {CONFIG_PATH}")
    feishu_cfg = cfg.get("feishu", {})
    token = get_token(feishu_cfg.get("app_id", ""), feishu_cfg.get("app_secret", ""))
    if not token:
        print("❌ 飞书凭证无效或已过期，请运行 python3 feishu_setup.py --reset 重新配置")
        sys.exit(1)

    print("✅ 飞书凭证有效")
    bitable = cfg.get("bitable", {})
    print(f"✅ Bitable: {bitable.get('url', '未知')}")
    print(f"   产品表 ID: {bitable.get('products_table_id', '未知')}")
    print(f"   QA 表 ID:  {bitable.get('qa_table_id', '未知')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="检查现有配置有效性")
    parser.add_argument("--reset", action="store_true", help="重置配置")
    args = parser.parse_args()

    if args.check:
        run_check()
    else:
        run_setup(reset=args.reset)
