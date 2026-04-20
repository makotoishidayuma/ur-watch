#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import smtplib
import ssl
from dataclasses import dataclass, asdict
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)
TIMEOUT = 30

TARGETS = [
    {
        "name": "物件詳細ページ",
        "url": "https://www.ur-net.go.jp/chintai/kanto/tokyo/20_6330.html",
    },
    {
        "name": "部屋情報ページ",
        "url": "https://www.ur-net.go.jp/chintai/sp/kanto/tokyo/20_6330_room.html",
    },
    {
        "name": "板橋駅一覧ページ",
        "url": "https://www.ur-net.go.jp/chintai/kanto/tokyo/eki/1573.html",
    },
    {
        "name": "新板橋駅一覧ページ",
        "url": "https://www.ur-net.go.jp/chintai/kanto/tokyo/eki/2305.html",
    },
]


@dataclass
class PageState:
    name: str
    url: str
    checked_at: str
    status_code: int
    text_hash: str
    available_rooms_guess: int | None
    changed: bool
    availability_changed: bool
    summary: str
    raw_excerpt: str


def fetch(url: str) -> tuple[int, str]:
    res = requests.get(
        url,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"},
    )
    res.raise_for_status()
    return res.status_code, res.text


def normalize_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text)
    return text


ROOM_COUNT_PATTERNS = [
    re.compile(r"空室状況\s*[:：]?\s*(\d+)"),
    re.compile(r"該当空室数\s*(\d+)\s*部屋"),
    re.compile(r"(\d+)\s*部屋\s*空室"),
]

POSITIVE_HINTS = [
    "ネットで仮申込み",
    "このお部屋はネットで直接仮申込みできます",
    "お申込みにはユーザー登録が必要です",
    "先着順のため",
]

NEGATIVE_HINTS = [
    "空室状況: 0",
    "空室状況：0",
    "該当空室数 0 部屋",
    "現在ご案内できる物件がございません",
    "現在ご案内できる部屋がありません",
]


def detect_availability(text: str) -> tuple[int | None, str]:
    for pat in ROOM_COUNT_PATTERNS:
        m = pat.search(text)
        if m:
            count = int(m.group(1))
            return count, f"空室数らしき表記を検出: {count}"

    if any(h in text for h in NEGATIVE_HINTS):
        return 0, "空室なしを示す文言を検出"

    if any(h in text for h in POSITIVE_HINTS):
        return 1, "申込み可能らしき文言を検出"

    return None, "空室数を断定できる表記は未検出"


def build_excerpt(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    keywords = ["板橋ビュータワー", "空室", "仮申込み", "申込み", "該当空室数", "空室状況"]
    picks: list[str] = []
    for line in lines:
        if any(k in line for k in keywords):
            picks.append(line)
        if len(picks) >= 8:
            break
    if not picks:
        picks = lines[:8]
    return "\n".join(picks[:8])


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def page_to_state(name: str, url: str, previous: dict[str, Any] | None) -> PageState:
    status_code, html = fetch(url)
    text = normalize_text(html)
    excerpt = build_excerpt(text)
    room_guess, summary = detect_availability(text)
    text_digest = hash_text(text)

    prev_hash = previous.get("text_hash") if previous else None
    prev_rooms = previous.get("available_rooms_guess") if previous else None

    return PageState(
        name=name,
        url=url,
        checked_at=datetime.now(JST).isoformat(timespec="seconds"),
        status_code=status_code,
        text_hash=text_digest,
        available_rooms_guess=room_guess,
        changed=(prev_hash is not None and prev_hash != text_digest),
        availability_changed=(prev_rooms is not None and prev_rooms != room_guess),
        summary=summary,
        raw_excerpt=excerpt,
    )


def compose_report(results: list[PageState], had_any_change: bool, first_run: bool) -> str:
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    lines = [
        f"UR監視結果: 板橋ビュータワー",
        f"確認時刻: {now}",
        "",
    ]
    if first_run:
        lines.append("これは初回記録です。今回の内容を基準値として保存しました。")
        lines.append("")
    elif had_any_change:
        lines.append("前回チェックからページ内容の変化を検知しました。")
        lines.append("")
    else:
        lines.append("前回チェックから大きな変化は検知しませんでした。")
        lines.append("")

    any_positive = False
    for r in results:
        if r.available_rooms_guess and r.available_rooms_guess > 0:
            any_positive = True
        lines.extend(
            [
                f"[{r.name}]",
                f"URL: {r.url}",
                f"HTTP: {r.status_code}",
                f"空室推定: {r.available_rooms_guess}",
                f"判定メモ: {r.summary}",
                f"本文変化: {'あり' if r.changed else 'なし'}",
                f"空室判定変化: {'あり' if r.availability_changed else 'なし'}",
                "抜粋:",
                r.raw_excerpt,
                "",
            ]
        )

    lines.append("総合判定:")
    if any_positive:
        lines.append("空室ありの可能性があります。すぐにURへ確認してください。")
    else:
        lines.append("少なくとも自動判定上は空室ありの強いシグナルは見つかっていません。")
    return "\n".join(lines)


def send_email(subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("MAIL_FROM") or username
    recipient = os.getenv("MAIL_TO")

    if not all([host, username, password, sender, recipient]):
        raise RuntimeError("SMTP環境変数が不足しています。")

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port) as server:
        server.starttls(context=context)
        server.login(username, password)
        server.send_message(msg)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", default=".state/ur_state.json")
    parser.add_argument(
        "--notify-mode",
        choices=["always", "changes_only", "availability_only"],
        default=os.getenv("NOTIFY_MODE", "always"),
    )
    args = parser.parse_args()

    state_path = Path(args.state_file)
    prev = load_state(state_path)
    prev_pages = prev.get("pages", {})

    results: list[PageState] = []
    for target in TARGETS:
        results.append(page_to_state(target["name"], target["url"], prev_pages.get(target["url"], {})))

    first_run = not bool(prev)
    had_any_change = any(r.changed or r.availability_changed for r in results)
    had_any_positive = any((r.available_rooms_guess or 0) > 0 for r in results)

    body = compose_report(results, had_any_change, first_run)
    subject = "[UR監視] 板橋ビュータワー"
    if had_any_positive:
        subject += " - 空室ありの可能性"
    elif had_any_change:
        subject += " - ページ変化あり"
    else:
        subject += " - 変化なし"

    new_state = {
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "pages": {r.url: asdict(r) for r in results},
    }
    save_state(state_path, new_state)

    should_notify = False
    if args.notify_mode == "always":
        should_notify = True
    elif args.notify_mode == "changes_only":
        should_notify = first_run or had_any_change
    elif args.notify_mode == "availability_only":
        should_notify = had_any_positive or first_run

    output_path = os.getenv("REPORT_PATH")
    if output_path:
        Path(output_path).write_text(body, encoding="utf-8")

    print(body)

    if should_notify:
        send_email(subject, body)
        print("\nメール送信完了")
    else:
        print("\n通知条件に該当しないため、メール送信はスキップしました")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
