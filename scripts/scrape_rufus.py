#!/usr/bin/env python3
# ruff: noqa: UP007
from __future__ import annotations
"""
Amazon Rufus FAQ 抓取脚本

依赖：CDP 代理运行在 localhost:3456（由 web-access skill 启动）

用法:
  python3 scrape_rufus.py --asin B0DN9WR2TX

输出 JSON:
{
  "product_name": "...",
  "product_url":  "https://...",
  "price":        "$10.19",
  "rating":       "4.6 out of 5 (70 reviews)",
  "faqs": [
    {"q": "...", "a": "...", "imgs": ["https://..."]},
    ...
  ]
}
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

CDP_PROXY = "http://localhost:3456"


# ── CDP helpers ────────────────────────────────────────────────────────────────

def cdp(path: str, body: str = None, method: str = None) -> dict | str:
    """Call CDP proxy. Returns parsed JSON or raw string."""
    url = CDP_PROXY + path
    m = method or ("POST" if body else "GET")
    data = body.encode() if isinstance(body, str) else body
    req = urllib.request.Request(url, data=data, method=m)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"CDP {path} failed: {e.code} {e.read().decode()}")


def js(target_id: str, script: str):
    """Execute JS and return the unwrapped value."""
    result = cdp(f"/eval?target={target_id}", script, "POST")
    if isinstance(result, dict):
        return result.get("value")
    return result


def wait_for(target_id: str, condition_js: str, timeout: int = 15, interval: float = 0.8):
    """Poll until JS expression returns truthy or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            val = js(target_id, condition_js)
            if val:
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


# ── Scraping logic ─────────────────────────────────────────────────────────────

def open_tab(asin: str) -> str:
    url = f"https://www.amazon.com/dp/{asin}"
    result = cdp(f"/new?url={url}")
    if isinstance(result, dict):
        tid = result.get("targetId") or result.get("id")
    else:
        # Parse from plain text response
        import re
        m = re.search(r'[A-F0-9]{32}', str(result))
        tid = m.group(0) if m else None
    if not tid:
        raise RuntimeError(f"Could not get targetId from: {result}")
    print(f"  Opened tab: {tid}", file=sys.stderr)
    return tid


def wait_for_page(target_id: str):
    print("  Waiting for page load...", file=sys.stderr)
    ok = wait_for(target_id, "document.readyState === 'complete'", timeout=20)
    if not ok:
        print("  [warn] Page may not be fully loaded", file=sys.stderr)
    time.sleep(3)  # Extra wait for Rufus to initialize


def get_product_meta(target_id: str) -> dict:
    raw = js(target_id, """
(function() {
  var title = document.getElementById("productTitle");
  var price = document.querySelector(".a-price .a-offscreen, #priceblock_ourprice");
  var rating = document.querySelector("#acrPopover .a-icon-alt, [data-hook='rating-out-of-text'], #averageCustomerReviews .a-icon-alt");
  var reviews = document.getElementById("acrCustomerReviewText");
  return JSON.stringify({
    name:    title   ? title.textContent.trim() : "",
    price:   price   ? price.textContent.trim() : "",
    rating:  rating  ? rating.textContent.trim() : "",
    reviews: reviews ? reviews.textContent.trim() : ""
  });
})()
""")
    try:
        meta = json.loads(raw) if raw else {}
    except Exception:
        meta = {}
    rating_str = meta.get("rating", "")
    if meta.get("reviews"):
        rating_str = f"{rating_str} {meta.get('reviews', '')}".strip()
    return {
        "name":   meta.get("name", ""),
        "price":  meta.get("price", ""),
        "rating": rating_str,
    }


def get_default_pills(target_id: str) -> list[str]:
    """Read the default Rufus FAQ pill questions from the page."""
    print("  Reading Rufus default pill questions...", file=sys.stderr)

    # Wait for Rufus pills to appear
    wait_for(target_id, "document.querySelectorAll('button.rufus-pill').length > 0", timeout=12)

    raw = js(target_id, """
(function() {
  var pills = document.querySelectorAll("button.rufus-pill");
  var questions = [];
  for (var i = 0; i < pills.length; i++) {
    var t = pills[i].textContent.trim();
    // Only keep actual questions (contain ?)
    if (t.indexOf("?") !== -1) {
      questions.push(t);
    }
  }
  return JSON.stringify(questions);
})()
""")
    try:
        questions = json.loads(raw) if raw else []
    except Exception:
        questions = []

    # Normalize non-breaking spaces and extra whitespace
    questions = [q.replace('\xa0', ' ').strip() for q in questions]
    print(f"  Found {len(questions)} pill questions: {questions}", file=sys.stderr)
    return questions


def submit_question(target_id: str, question: str) -> bool:
    """Type a question into Rufus textarea and submit."""
    q_escaped = question.replace("\\", "\\\\").replace('"', '\\"')
    result = js(target_id, f"""
(function() {{
  var ta = document.getElementById("rufus-text-area");
  if (!ta) return "no-textarea";
  var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
  setter.call(ta, "{q_escaped}");
  ta.dispatchEvent(new Event("input", {{bubbles:true}}));
  ta.dispatchEvent(new Event("change", {{bubbles:true}}));
  return "set";
}})()
""")
    if result != "set":
        print(f"  [warn] Could not set textarea: {result}", file=sys.stderr)
        return False

    time.sleep(0.5)

    result = js(target_id, """
(function() {
  var btn = document.getElementById("rufus-submit-button");
  if (btn && !btn.disabled) { btn.click(); return "submitted"; }
  return "no-button";
})()
""")
    return result == "submitted"


def read_last_interaction(target_id: str) -> dict:
    """Read Q, A, and image URLs from the most recent Rufus interaction."""
    raw = js(target_id, """
(function() {
  var interactions = document.querySelectorAll("[id^='interaction']");
  var last = interactions[interactions.length - 1];
  if (!last) return JSON.stringify({q:"", a:"", imgs:[]});

  var text = last.innerText.replace(/\\s+/g, " ").trim();
  var prefix = "Customer question ";
  if (text.indexOf(prefix) === 0) text = text.substring(prefix.length);

  // Split on first ? to get Q and A
  var qi = text.indexOf("?");
  var q = qi !== -1 ? text.substring(0, qi + 1).trim() : "";
  var a = qi !== -1 ? text.substring(qi + 1).trim() : text;

  // Remove trailing pill suggestions (heuristic: lines shorter than 60 chars at the end)
  var lines = a.split("  ");
  var trimmed = [];
  var foundShort = false;
  for (var i = lines.length - 1; i >= 0; i--) {
    if (!foundShort && lines[i].trim().length < 60) {
      foundShort = true;
    } else if (foundShort && lines[i].trim().length >= 60) {
      trimmed = lines.slice(0, i + 1);
      break;
    }
  }
  if (trimmed.length > 0) a = trimmed.join("  ").trim();

  // Images (exclude feedback icons)
  var imgs = last.querySelectorAll("img");
  var imgUrls = [];
  for (var j = 0; j < imgs.length; j++) {
    var src = imgs[j].src || "";
    if (src && src.indexOf("Rufus_Desktop") === -1 && src.indexOf("thumbs_") === -1) {
      imgUrls.push(src);
    }
  }

  return JSON.stringify({q:q, a:a, imgs:imgUrls});
})()
""")
    try:
        return json.loads(raw) if raw else {"q": "", "a": "", "imgs": []}
    except Exception:
        return {"q": "", "a": "", "imgs": []}


def count_interactions(target_id: str) -> int:
    val = js(target_id, "document.querySelectorAll('[id^=\"interaction\"]').length")
    try:
        return int(val)
    except Exception:
        return 0


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--asin", required=True, help="Amazon product ASIN")
    parser.add_argument("--wait", type=int, default=8,
                        help="Seconds to wait after each question (default: 8)")
    args = parser.parse_args()

    target_id = None
    try:
        # Step 1: Open tab
        target_id = open_tab(args.asin)

        # Step 2: Wait for page
        wait_for_page(target_id)

        # Step 3: Get product meta
        print("  Getting product metadata...", file=sys.stderr)
        meta = get_product_meta(target_id)
        product_url = f"https://www.amazon.com/dp/{args.asin}"
        print(f"  Product: {meta['name'][:60]}", file=sys.stderr)

        # Step 4: Get default pill questions
        questions = get_default_pills(target_id)
        if not questions:
            print("  [warn] No pill questions found. Rufus may not have loaded.", file=sys.stderr)

        # Step 5: Submit each question and capture answer
        faqs = []
        for i, question in enumerate(questions, 1):
            print(f"  [{i}/{len(questions)}] Asking: {question[:60]}", file=sys.stderr)
            before = count_interactions(target_id)

            submitted = submit_question(target_id, question)
            if not submitted:
                print(f"  [warn] Submit failed for: {question}", file=sys.stderr)
                continue

            # Wait for new interaction to appear
            deadline = time.time() + args.wait + 5
            while time.time() < deadline:
                time.sleep(1)
                after = count_interactions(target_id)
                if after > before:
                    break

            # Extra wait for full response
            time.sleep(args.wait)

            faq = read_last_interaction(target_id)
            if not faq.get("q"):
                faq["q"] = question  # Fallback to the question we asked
            faqs.append(faq)
            print(f"     Answer: {faq['a'][:80]}... imgs={len(faq['imgs'])}", file=sys.stderr)

        result = {
            "asin":         args.asin,
            "product_name": meta["name"],
            "product_url":  product_url,
            "price":        meta["price"],
            "rating":       meta["rating"],
            "faqs":         faqs,
        }
        print(json.dumps(result, ensure_ascii=False))

    finally:
        if target_id:
            print(f"  Closing tab {target_id}", file=sys.stderr)
            try:
                cdp(f"/close?target={target_id}")
            except Exception:
                pass


if __name__ == "__main__":
    main()
