#!/usr/bin/env python3
"""
Amazon Rufus FAQ → 飞书多维表格 上传脚本（两表结构版）

数据结构：
  产品表  ←→  Rufus QA 表（双向关联）

用法:
  python3 feishu_upload.py \
    --product-name "..." \
    --product-url  "https://..." \
    --asin         "B0DN9WR2TX" \
    --price        "$10.19" \
    --rating       "4.6 out of 5" \
    --faqs-json    '[{"q":"...","a":"...","imgs":["url"]}]'

config 读取自: ~/.config/amazon-rufus/config.json
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

CONFIG_PATH = os.path.expanduser("~/.config/amazon-rufus/config.json")
FEISHU_BASE = "https://open.feishu.cn"


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ 未找到配置文件 {CONFIG_PATH}", file=sys.stderr)
        print("请先运行: python3 feishu_setup.py", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


# ── Feishu API ─────────────────────────────────────────────────────────────────

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
        raise RuntimeError(f"Feishu API {path} error {e.code}: {e.read().decode()}")


def get_token(app_id: str, app_secret: str) -> str:
    resp = feishu("POST", "/open-apis/auth/v3/tenant_access_token/internal",
                  {"app_id": app_id, "app_secret": app_secret})
    tok = resp.get("tenant_access_token")
    if not tok:
        raise RuntimeError(f"Token failed: {resp}")
    return tok


def upload_image(token: str, base_token: str, img_url: str, filename: str) -> str | None:
    try:
        req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            img_data = r.read()
    except Exception as e:
        print(f"  [warn] 下载图片失败 {img_url}: {e}", file=sys.stderr)
        return None

    boundary = "----RufusUploadBoundary"
    parts = []
    for name, val in [("file_name", filename), ("parent_type", "bitable_file"),
                      ("parent_node", base_token), ("size", str(len(img_data)))]:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f'Content-Type: image/jpeg\r\n\r\n'.encode() + img_data + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())

    upload_req = urllib.request.Request(
        f"{FEISHU_BASE}/open-apis/drive/v1/medias/upload_all",
        data=b''.join(parts), method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(upload_req, timeout=30) as r:
            return json.loads(r.read()).get("data", {}).get("file_token")
    except Exception as e:
        print(f"  [warn] 图片上传失败: {e}", file=sys.stderr)
        return None


# ── Business logic ─────────────────────────────────────────────────────────────

def find_existing_product(token: str, base_token: str, products_table_id: str,
                           asin: str) -> str | None:
    """Search for an existing product record by ASIN. Returns record_id or None."""
    path = (f"/open-apis/bitable/v1/apps/{base_token}/tables/{products_table_id}/records"
            f"?filter=AND(CurrentValue.[ASIN]=\"{asin}\")&page_size=1")
    resp = feishu("GET", path, token=token)
    items = resp.get("data", {}).get("items", [])
    if items:
        return items[0]["record_id"]
    return None


def create_product_record(token: str, base_token: str, products_table_id: str,
                           product_name: str, asin: str, product_url: str,
                           price: str, rating: str) -> str:
    """Create a new product record. Returns record_id."""
    fields = {
        "产品名称": product_name,
        "ASIN":    asin,
        "产品链接": {"text": "Amazon 商品页", "link": product_url},
        "价格":    price,
        "评分":    rating,
        "采集时间": int(time.time() * 1000),  # Feishu timestamp in ms
    }
    resp = feishu("POST",
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{products_table_id}/records",
        {"fields": fields}, token)
    if resp.get("code") != 0:
        raise RuntimeError(f"创建产品记录失败: {resp}")
    return resp["data"]["record"]["record_id"]


def create_qa_record(token: str, base_token: str, qa_table_id: str,
                     seq: int, question: str, answer: str,
                     img_tokens: list[dict], product_record_id: str) -> str:
    """Create a QA record linked to the product. Returns record_id."""
    fields = {
        "问题":  question,
        "答案":  answer,
        "序号":  seq,
        "产品":  [{"record_id": product_record_id}],
    }
    if img_tokens:
        fields["Rufus图片"] = img_tokens

    resp = feishu("POST",
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{qa_table_id}/records",
        {"fields": fields}, token)
    if resp.get("code") != 0:
        raise RuntimeError(f"创建 QA 记录失败: {resp}")
    return resp["data"]["record"]["record_id"]


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Upload Rufus FAQ to Feishu Bitable")
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--product-url",  required=True)
    parser.add_argument("--asin",         required=True)
    parser.add_argument("--price",        default="")
    parser.add_argument("--rating",       default="")
    parser.add_argument("--faqs-json",    required=True,
                        help='JSON: [{"q":"...","a":"...","imgs":["url",...]}]')
    args = parser.parse_args()

    try:
        faqs = json.loads(args.faqs_json)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"faqs-json 解析失败: {e}"}))
        sys.exit(1)

    cfg = load_config()
    feishu_cfg = cfg["feishu"]
    bitable_cfg = cfg["bitable"]

    base_token         = bitable_cfg["base_token"]
    products_table_id  = bitable_cfg["products_table_id"]
    qa_table_id        = bitable_cfg["qa_table_id"]
    bitable_url        = bitable_cfg["url"]

    print(f"获取飞书 Token...", file=sys.stderr)
    token = get_token(feishu_cfg["app_id"], feishu_cfg["app_secret"])

    # Check for existing product
    print(f"检查 ASIN {args.asin} 是否已存在...", file=sys.stderr)
    existing_id = find_existing_product(token, base_token, products_table_id, args.asin)

    if existing_id:
        print(f"发现已有产品记录 {existing_id}，将追加 QA（不重复创建产品）", file=sys.stderr)
        product_record_id = existing_id
        is_new_product = False
    else:
        print(f"创建新产品记录...", file=sys.stderr)
        product_record_id = create_product_record(
            token, base_token, products_table_id,
            args.product_name, args.asin, args.product_url,
            args.price, args.rating)
        print(f"  产品记录 ID: {product_record_id}", file=sys.stderr)
        is_new_product = True

    # Create QA records
    img_count = 0
    qa_record_ids = []
    for i, faq in enumerate(faqs, 1):
        print(f"  QA {i}/{len(faqs)}: {faq.get('q','')[:50]}...", file=sys.stderr)

        # Upload images
        img_tokens = []
        for j, img_url in enumerate(faq.get("imgs", [])):
            ft = upload_image(token, base_token, img_url, f"rufus_{args.asin}_{i}_{j+1}.jpg")
            if ft:
                img_tokens.append({"file_token": ft})

        if img_tokens:
            img_count += 1

        rid = create_qa_record(
            token, base_token, qa_table_id,
            i, faq.get("q", ""), faq.get("a", ""),
            img_tokens, product_record_id)
        qa_record_ids.append(rid)

    result = {
        "ok": True,
        "bitable_url": bitable_url,
        "asin": args.asin,
        "product_record_id": product_record_id,
        "is_new_product": is_new_product,
        "qa_count": len(faqs),
        "qa_with_images": img_count,
        "qa_record_ids": qa_record_ids,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
