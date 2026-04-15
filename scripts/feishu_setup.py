#!/usr/bin/env python3
"""
Amazon Rufus Skill — 首次配置脚本

选择输出方式：
  [1] 飞书多维表格（已有企业应用，提供 App ID + App Secret 即可）
  [2] 本地 Excel 文件（无需飞书，双 sheet 格式）

配置保存至 ~/.config/amazon-rufus/config.json

用法：
  python3 feishu_setup.py           # 交互配置
  python3 feishu_setup.py --check   # 检查现有配置
  python3 feishu_setup.py --reset   # 重置配置
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

CONFIG_PATH = os.path.expanduser("~/.config/amazon-rufus/config.json")
FEISHU_BASE = "https://open.feishu.cn"


# ── Feishu API ─────────────────────────────────────────────────────────────────

def feishu(method, path, body=None, token=None):
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


def get_token(app_id, app_secret):
    resp = feishu("POST", "/open-apis/auth/v3/tenant_access_token/internal",
                  {"app_id": app_id, "app_secret": app_secret})
    return resp.get("tenant_access_token")


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 配置已保存至 {CONFIG_PATH}")


# ── Bitable setup ──────────────────────────────────────────────────────────────

def create_bitable(token):
    resp = feishu("POST", "/open-apis/bitable/v1/apps",
                  {"name": "Amazon Rufus FAQ"}, token)
    if resp.get("code") != 0:
        raise RuntimeError(f"创建多维表格失败: {resp}")
    app = resp["data"]["app"]
    print(f"   ✓ 多维表格已创建: {app['url']}")
    return app["app_token"], app["default_table_id"]


def rename_field(token, base_token, table_id, field_id, new_name):
    feishu("PUT",
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/fields/{field_id}",
        {"field_name": new_name, "type": 1}, token)


def add_field(token, base_token, table_id, name, ftype, prop=None):
    body = {"field_name": name, "type": ftype}
    if prop:
        body["property"] = prop
    resp = feishu("POST",
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/fields",
        body, token)
    return resp.get("data", {}).get("field", {}).get("field_id", "")


def get_default_field(token, base_token, table_id):
    resp = feishu("GET",
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/fields",
        token=token)
    items = resp.get("data", {}).get("items", [])
    return items[0]["field_id"] if items else None


def setup_bitable(token):
    """Create bitable with 产品表 + Rufus QA 表 and bidirectional link."""
    print("\n📊 初始化飞书多维表格...")

    base_token, products_table_id = create_bitable(token)

    # ── 产品表 ──
    dfid = get_default_field(token, base_token, products_table_id)
    if dfid:
        rename_field(token, base_token, products_table_id, dfid, "产品名称")
    feishu("PATCH",
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{products_table_id}",
        {"name": "产品"}, token)

    for name, ftype, prop in [
        ("ASIN",    1, None),
        ("产品链接", 15, None),
        ("价格",    1,  None),
        ("评分",    1,  None),
        ("采集时间", 5,  {"date_formatter": "yyyy-MM-DD HH:mm"}),
    ]:
        add_field(token, base_token, products_table_id, name, ftype, prop)
    print("   ✓ 产品表字段已添加")

    # ── Rufus QA 表 ──
    resp = feishu("POST", f"/open-apis/bitable/v1/apps/{base_token}/tables",
                  {"table": {"name": "Rufus QA"}}, token)
    if resp.get("code") != 0:
        raise RuntimeError(f"创建 QA 表失败: {resp}")
    qa_table_id = resp["data"]["table_id"]

    dfid2 = get_default_field(token, base_token, qa_table_id)
    if dfid2:
        rename_field(token, base_token, qa_table_id, dfid2, "问题")

    for name, ftype in [("答案", 1), ("Rufus图片", 17), ("序号", 2)]:
        add_field(token, base_token, qa_table_id, name, ftype)
    print("   ✓ Rufus QA 表字段已添加")

    # ── 双向关联 ──
    resp = feishu("POST",
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{products_table_id}/fields",
        {"field_name": "Rufus QA", "type": 21,
         "property": {"table_id": qa_table_id, "back_field_name": "产品"}},
        token)
    if resp.get("code") == 0:
        print("   ✓ 双向关联字段已建立（产品表.Rufus QA ↔ QA表.产品）")
    else:
        print(f"   ⚠ 双向关联创建失败（不影响基本功能）: {resp}")

    bitable_url = f"https://open.feishu.cn/base/{base_token}"
    print(f"   ✓ 多维表格地址: {bitable_url}")

    return {
        "base_token":        base_token,
        "products_table_id": products_table_id,
        "qa_table_id":       qa_table_id,
        "url":               bitable_url,
    }


# ── Setup flows ────────────────────────────────────────────────────────────────

def setup_feishu():
    print("\n── 飞书多维表格配置 ──────────────────────────────────────")
    print("需要飞书企业自建应用的 App ID 和 App Secret。")
    print("（OpenClaw / Hermes 用户通常已有企业应用，直接填写凭证即可）\n")

    app_id     = input("App ID：    ").strip()
    app_secret = input("App Secret：").strip()

    print("\n🔑 验证凭证...")
    token = get_token(app_id, app_secret)
    if not token:
        print("❌ 凭证无效，请检查 App ID 和 App Secret")
        sys.exit(1)
    print("   ✓ 凭证有效")

    bitable_cfg = setup_bitable(token)

    return {
        "output": "feishu",
        "feishu": {"app_id": app_id, "app_secret": app_secret},
        "bitable": bitable_cfg,
    }


def setup_excel():
    print("\n── 本地 Excel 配置 ───────────────────────────────────────")
    default_dir = os.path.expanduser("~/Desktop/rufus-faq")
    raw = input(f"Excel 保存目录 [{default_dir}]：").strip()
    output_dir = raw if raw else default_dir
    output_dir = os.path.expanduser(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    print(f"   ✓ 将保存至: {output_dir}")
    return {
        "output": "excel",
        "excel": {"output_dir": output_dir},
    }


def run_setup(reset=False):
    cfg = None if reset else load_config()

    if cfg and not reset:
        mode = cfg.get("output", "?")
        print(f"找到现有配置（输出方式：{mode}）: {CONFIG_PATH}")
        ans = input("直接使用现有配置？(Y/n)：").strip().lower()
        if ans != "n":
            print("✅ 使用现有配置")
            return cfg

    print("\n选择采集结果的输出方式：")
    print("  [1] 上传到飞书多维表格（需要飞书企业应用凭证）")
    print("  [2] 保存为本地 Excel 文件（无需飞书）")

    while True:
        choice = input("\n请选择 (1/2)：").strip()
        if choice == "1":
            cfg = setup_feishu()
            break
        elif choice == "2":
            cfg = setup_excel()
            break
        else:
            print("请输入 1 或 2")

    save_config(cfg)
    print("\n🎉 配置完成！")
    return cfg


def run_check():
    cfg = load_config()
    if not cfg:
        print(f"❌ 未找到配置: {CONFIG_PATH}")
        print("请运行 python3 feishu_setup.py 完成初始化")
        sys.exit(1)

    mode = cfg.get("output", "unknown")
    print(f"输出方式：{mode}")

    if mode == "feishu":
        fc = cfg.get("feishu", {})
        token = get_token(fc.get("app_id", ""), fc.get("app_secret", ""))
        if not token:
            print("❌ 飞书凭证无效，请运行 python3 feishu_setup.py --reset 重新配置")
            sys.exit(1)
        print("✅ 飞书凭证有效")
        bc = cfg.get("bitable", {})
        print(f"✅ Bitable: {bc.get('url', '未知')}")
    elif mode == "excel":
        d = cfg.get("excel", {}).get("output_dir", "")
        print(f"✅ 输出目录: {d}")
    else:
        print("❌ 未知输出方式")
        sys.exit(1)


def _run_setup_noninteractive(args):
    """Configure without any input() prompts — for agent/script use."""
    if args.output == "feishu":
        if not args.app_id or not args.app_secret:
            print("❌ --output feishu 需要同时提供 --app-id 和 --app-secret")
            sys.exit(1)
        print("\n🔑 验证凭证...")
        token = get_token(args.app_id, args.app_secret)
        if not token:
            print("❌ 凭证无效，请检查 App ID 和 App Secret")
            sys.exit(1)
        print("   ✓ 凭证有效")
        bitable_cfg = setup_bitable(token)
        cfg = {
            "output": "feishu",
            "feishu":  {"app_id": args.app_id, "app_secret": args.app_secret},
            "bitable": bitable_cfg,
        }
    else:  # excel
        output_dir = os.path.expanduser(args.output_dir or "~/Desktop/rufus-faq")
        os.makedirs(output_dir, exist_ok=True)
        print(f"   ✓ 将保存至: {output_dir}")
        cfg = {
            "output": "excel",
            "excel":  {"output_dir": output_dir},
        }
    save_config(cfg)
    print("\n🎉 配置完成！")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Amazon Rufus — 首次配置",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
非交互模式（适合 agent 脚本）：
  飞书：python3 feishu_setup.py --output feishu --app-id cli_xxx --app-secret xxx
  Excel：python3 feishu_setup.py --output excel --output-dir ~/Desktop/rufus-faq
        """,
    )
    parser.add_argument("--check", action="store_true",
                        help="检查现有配置是否有效")
    parser.add_argument("--reset", action="store_true",
                        help="删除现有配置，重新配置")
    # Non-interactive flags
    parser.add_argument("--output", choices=["feishu", "excel"],
                        help="输出方式（非交互）")
    parser.add_argument("--app-id",     default="",
                        help="飞书 App ID（非交互，--output feishu 时使用）")
    parser.add_argument("--app-secret", default="",
                        help="飞书 App Secret（非交互，--output feishu 时使用）")
    parser.add_argument("--output-dir", default="",
                        help="Excel 输出目录（非交互，--output excel 时使用）")
    args = parser.parse_args()

    if args.check:
        run_check()
    elif args.output:
        # Non-interactive path
        _run_setup_noninteractive(args)
    else:
        run_setup(reset=args.reset)
