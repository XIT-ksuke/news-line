#!/usr/bin/env python3
"""毎日ニュース → LINE配信ボット（GitHub Actions で実行）"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import feedparser
import google.generativeai as genai
import requests

# ── 設定（環境変数） ──────────────────────────────────────────────
GEMINI_API_KEY            = os.environ["GEMINI_API_KEY"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID              = os.environ["LINE_USER_ID"]

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
TOP_N        = int(os.environ.get("TOP_N", "5"))
HOURS_WINDOW = int(os.environ.get("HOURS_WINDOW", "7"))

# RSS_FEEDS 環境変数が設定されていればそちらを優先（改行区切り）
_env_feeds = [u.strip() for u in os.environ.get("RSS_FEEDS", "").splitlines() if u.strip()]
RSS_FEEDS: list[str] = _env_feeds or [
    "https://www.nhk.or.jp/rss/news/cat0.xml",
    "https://rss.itmedia.co.jp/rss/2.0/itmedia_all.xml",
    "https://b.hatena.ne.jp/hotentry/it.rss",
    "https://gigazine.net/news/rss_2.0/",
    # Google News 検索フィード（URLエンコード済み）
    "https://news.google.com/rss/search?q=%E7%94%9F%E6%88%90AI&hl=ja&gl=JP&ceid=JP:ja",
    "https://news.google.com/rss/search?q=Oracle+%E3%82%AF%E3%83%A9%E3%82%A6%E3%83%89&hl=ja&gl=JP&ceid=JP:ja",
]

LINE_PUSH_URL  = "https://api.line.me/v2/bot/message/push"
LINE_MAX_CHARS = 5000
JST = timezone(timedelta(hours=9))

# ── ログ設定 ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


# ── RSS 取得 ──────────────────────────────────────────────────────
def fetch_articles(feeds: list[str], hours_window: int) -> list[dict]:
    """全フィードを取得し、直近 hours_window 時間・重複除外した記事リストを返す。
    1フィードが失敗しても残りを継続する。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_window)
    articles: list[dict] = []
    seen_titles: set[str] = set()

    for url in feeds:
        try:
            feed = feedparser.parse(url)
            added = 0
            for entry in feed.entries:
                title = (entry.get("title") or "").strip()
                link  = (entry.get("link")  or "").strip()

                if not title or not link:
                    continue
                if title in seen_titles:
                    continue

                # タイムスタンプがある場合のみ時刻フィルタを適用
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue

                seen_titles.add(title)
                articles.append({"title": title, "url": link})
                added += 1

            log.info("OK   %s → %d件追加", url, added)

        except Exception as exc:
            log.warning("SKIP %s: %s", url, exc)

    return articles


# ── Gemini による選定・要約 ───────────────────────────────────────
def select_with_gemini(articles: list[dict], top_n: int, model_name: str) -> list[dict]:
    """Gemini に記事を渡し、重要 top_n 件を JSON で受け取る。"""
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(model_name)

    numbered = "\n".join(f"{i+1}. {a['title']}" for i, a in enumerate(articles))

    prompt = f"""以下のニュース記事から重要度の高いものを{top_n}件選び、JSONのみ返してください。
選定基準: 社会的影響・技術革新・ビジネスインパクト・速報性。

記事一覧:
{numbered}

出力形式（```などのマークダウンは不要。JSONのみ）:
{{"selected":[{{"rank":1,"title":"元のタイトルそのまま","summary":"1〜2文の日本語要約"}}]}}"""

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # モデルが ``` ブロックで返してきた場合の除去
    if raw.startswith("```"):
        lines = raw.splitlines()
        inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
        raw = "\n".join(inner)

    data = json.loads(raw)
    gemini_items: list[dict] = data.get("selected", [])

    # Gemini が返したタイトルに対して元記事の URL を紐付け
    url_by_title = {a["title"]: a["url"] for a in articles}
    result: list[dict] = []
    for item in gemini_items:
        title = item.get("title", "")
        result.append({
            "title":   title,
            "summary": item.get("summary", ""),
            "url":     url_by_title.get(title, ""),
        })

    return result


# ── LINE メッセージ構築 ───────────────────────────────────────────
_NUM_SYMBOLS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]


def build_message(selected: list[dict]) -> str:
    now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M JST")
    blocks = [f"📰 ニュース速報 ({now_str})"]

    for i, item in enumerate(selected):
        num   = _NUM_SYMBOLS[i] if i < len(_NUM_SYMBOLS) else f"{i+1}."
        block = f"{num} {item['title']}\n{item['summary']}\n{item['url']}"
        blocks.append(block)

    message = "\n\n".join(blocks)

    if len(message) > LINE_MAX_CHARS:
        message = message[: LINE_MAX_CHARS - 3] + "..."

    return message


# ── LINE push 送信 ────────────────────────────────────────────────
def push_line(message: str) -> None:
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type":  "application/json",
    }
    payload = {
        "to":       LINE_USER_ID,
        "messages": [{"type": "text", "text": message}],
    }
    resp = requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    log.info("LINE push 完了: HTTP %d", resp.status_code)


# ── エントリーポイント ───────────────────────────────────────────
def main() -> None:
    log.info("=== news_bot 開始 (直近 %d 時間 / TOP %d 件) ===", HOURS_WINDOW, TOP_N)

    articles = fetch_articles(RSS_FEEDS, HOURS_WINDOW)
    log.info("候補記事数: %d 件", len(articles))

    if not articles:
        log.info("配信対象なし → 終了")
        return

    selected = select_with_gemini(articles, TOP_N, GEMINI_MODEL)
    log.info("Gemini 選定: %d 件", len(selected))

    if not selected:
        log.info("選定結果なし → 終了")
        return

    message = build_message(selected)
    log.info("メッセージ文字数: %d", len(message))

    push_line(message)
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
