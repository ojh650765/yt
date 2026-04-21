"""
Telegram Bot for YouTube Premium Payment Tracker
-------------------------------------------------
GitHub Actions에서 schedule(폴링)로 실행됩니다.
한 줄 명령어로 동작 — 폴링 1회에 처리 완료.

명령어:
  /add 이름 개월수          결제 추가 (오늘 날짜)
  /add 이름 개월수 날짜     결제 추가 (날짜 지정)
  /del 이름                 마지막 결제 삭제
  /status                   전체 현황
  /members                  등록된 멤버 목록
  /help                     도움말

예시:
  /add 구회원 3
  /add 류동헌 5 2026-03-01
  /del 구회원
  /status

환경변수:
  TELEGRAM_BOT_TOKEN  - Telegram Bot API 토큰
  TELEGRAM_CHAT_ID    - 허용할 채팅 ID (쉼표 구분)
  GH_TOKEN            - GitHub Token (github.token)
  GH_REPO             - owner/repo
  DATA_PATH           - JSON 파일 경로 (기본: data.json)
"""

import os
import json
import sys
import base64
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, date, timezone, timedelta

# ─── 설정 ───
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHATS = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_REPO = os.environ.get("GH_REPO", "")
DATA_PATH = os.environ.get("DATA_PATH", "data.json")

KST = timezone(timedelta(hours=9))


# ─── API helpers ───

def tg_api(method, data=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    if data:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"TG API error: {e.code} {e.read().decode()}")
        return {"ok": False}


def gh_api(endpoint, method="GET", data=None):
    url = f"https://api.github.com/repos/{GH_REPO}/{endpoint}"
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"token {GH_TOKEN}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"GH API error: {e.code} {e.read().decode()}")
        return None


def send_msg(chat_id, text):
    return tg_api("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


# ─── data.json ───

def load_data():
    result = gh_api(f"contents/{DATA_PATH}")
    if not result or "content" not in result:
        return [], None
    content = base64.b64decode(result["content"]).decode("utf-8")
    return json.loads(content), result["sha"]


def save_data(payments, sha, commit_msg):
    content = base64.b64encode(
        (json.dumps(payments, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    ).decode("ascii")
    result = gh_api(f"contents/{DATA_PATH}", method="PUT", data={
        "message": commit_msg, "content": content, "sha": sha,
    })
    return result is not None


# ─── offset (GitHub 저장) ───

def load_offset():
    result = gh_api("contents/.tg_offset")
    if result and "content" in result:
        try:
            return int(base64.b64decode(result["content"]).decode().strip()), result["sha"]
        except ValueError:
            pass
    return 0, None


def save_offset(offset, sha=None):
    content = base64.b64encode(str(offset).encode()).decode("ascii")
    data = {"message": "Update telegram bot offset", "content": content}
    if sha:
        data["sha"] = sha
    gh_api("contents/.tg_offset", method="PUT", data=data)


# ─── 계산 ───

def add_months(d, months):
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    max_days = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(d.day, max_days[month - 1]))


def compute_status(payments):
    groups = {}
    for p in payments:
        groups.setdefault(p["name"], []).append(p)
    today = datetime.now(KST).date()
    result = []
    for name, lst in groups.items():
        lst.sort(key=lambda x: x["date"])
        cover_end = None
        total_months = 0
        for p in lst:
            pay_d = date.fromisoformat(p["date"])
            start = pay_d if (cover_end is None or pay_d > cover_end) else cover_end
            cover_end = add_months(start, int(p["months"]))
            total_months += int(p["months"])
        last = lst[-1]
        days_left = (cover_end - today).days
        state = "expired" if days_left < 0 else ("soon" if days_left <= 30 else "safe")
        result.append({
            "name": name, "cover_end": cover_end.isoformat(),
            "days_left": days_left, "state": state,
            "total_months": total_months,
            "last_date": last["date"], "last_months": last["months"],
        })
    result.sort(key=lambda x: x["days_left"])
    return result


def format_status(status_list):
    lines = ["📊 <b>YouTube Premium 결제 현황</b>", ""]
    for s in status_list:
        emoji = {"safe": "🟢", "soon": "🟡", "expired": "🔴"}[s["state"]]
        dday = f"D+{abs(s['days_left'])}" if s["days_left"] < 0 else f"D-{s['days_left']}"
        lines.append(f"{emoji} <b>{s['name']}</b>  {dday}")
        lines.append(f"    만료: {s['cover_end']}  ({s['total_months']}개월 누적)")
        lines.append("")
    lines.append(f"<i>{datetime.now(KST).strftime('%Y-%m-%d %H:%M')} KST</i>")
    return "\n".join(lines)


# ─── 이름 퍼지 매칭 ───

def find_member(query, members):
    """정확히 일치 → 포함 매칭 → 실패"""
    query = query.strip()
    # 정확히 일치
    for m in members:
        if m == query:
            return m
    # 부분 매칭 (query가 멤버 이름에 포함)
    matches = [m for m in members if query in m]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return None  # 애매함
    # 역방향 (멤버 이름이 query에 포함)
    matches = [m for m in members if m in query]
    if len(matches) == 1:
        return matches[0]
    return None


# ─── 명령어 처리 ───

def handle_message(msg):
    chat_id = msg["chat"]["id"]
    if not is_allowed(chat_id):
        send_msg(chat_id, f"⛔ 권한이 없습니다.\n채팅 ID: <code>{chat_id}</code>")
        return

    text = msg.get("text", "").strip()
    if not text:
        return

    # 봇 유저네임 제거 (/add@botname → /add)
    if "@" in text.split()[0]:
        parts = text.split()
        parts[0] = parts[0].split("@")[0]
        text = " ".join(parts)

    cmd = text.split()[0].lower()
    args = text.split()[1:]

    if cmd in ("/start", "/help"):
        send_msg(chat_id, (
            "🎬 <b>YouTube Premium 결제 관리 봇</b>\n\n"
            "📌 <b>명령어:</b>\n\n"
            "<b>/add 이름 개월수</b>\n"
            "  결제 추가 (오늘 날짜)\n"
            "  예: <code>/add 구회원 3</code>\n\n"
            "<b>/add 이름 개월수 날짜</b>\n"
            "  날짜 지정 추가\n"
            "  예: <code>/add 류동헌 5 2026-03-01</code>\n\n"
            "<b>/del 이름</b>\n"
            "  마지막 결제 기록 삭제\n"
            "  예: <code>/del 구회원</code>\n\n"
            "<b>/status</b> — 전체 현황\n"
            "<b>/members</b> — 멤버 목록\n\n"
            "💡 이름은 일부만 입력해도 됩니다\n"
            "  예: <code>/add 동헌 5</code> → 류동헌"
        ))
        return

    if cmd == "/status":
        payments, _ = load_data()
        if not payments:
            send_msg(chat_id, "데이터가 없습니다")
            return
        send_msg(chat_id, format_status(compute_status(payments)))
        return

    if cmd == "/members":
        payments, _ = load_data()
        members = sorted(set(p["name"] for p in payments))
        if not members:
            send_msg(chat_id, "등록된 멤버가 없습니다")
            return
        lines = ["👥 <b>등록된 멤버</b>", ""]
        for m in members:
            lines.append(f"  • {m}")
        send_msg(chat_id, "\n".join(lines))
        return

    if cmd == "/add":
        handle_add(chat_id, args)
        return

    if cmd == "/del":
        handle_del(chat_id, args)
        return

    send_msg(chat_id, "❓ 알 수 없는 명령어입니다.\n/help 를 입력해보세요.")


def handle_add(chat_id, args):
    if len(args) < 2:
        send_msg(chat_id, (
            "⚠️ 형식: <code>/add 이름 개월수</code>\n\n"
            "예시:\n"
            "  <code>/add 구회원 3</code>\n"
            "  <code>/add 류동헌 5 2026-03-01</code>"
        ))
        return

    name_query = args[0]
    try:
        months = int(args[1])
        if months < 1:
            raise ValueError
    except ValueError:
        send_msg(chat_id, "⚠️ 개월 수는 1 이상 숫자여야 합니다")
        return

    # 날짜 파싱
    today = datetime.now(KST).strftime("%Y-%m-%d")
    pay_date = today
    if len(args) >= 3:
        try:
            date.fromisoformat(args[2])
            pay_date = args[2]
        except ValueError:
            send_msg(chat_id, "⚠️ 날짜 형식은 YYYY-MM-DD\n예: <code>2026-04-22</code>")
            return

    # 데이터 로드 & 이름 매칭
    payments, sha = load_data()
    if not sha:
        send_msg(chat_id, "❌ data.json을 불러올 수 없습니다")
        return

    members = sorted(set(p["name"] for p in payments))
    matched = find_member(name_query, members)

    if not matched:
        similar = [m for m in members if any(c in m for c in name_query)]
        msg = f"⚠️ '<b>{name_query}</b>' 멤버를 찾을 수 없습니다\n\n"
        if similar:
            msg += "혹시?\n" + "\n".join(f"  • {m}" for m in similar) + "\n\n"
        msg += "전체 멤버: " + ", ".join(members)
        send_msg(chat_id, msg)
        return

    # 추가
    new_id = "t" + datetime.now(KST).strftime("%Y%m%d%H%M%S")
    payments.append({"id": new_id, "name": matched, "date": pay_date, "months": months})

    commit_msg = f"Add payment: {matched} {months}mo ({pay_date}) via Telegram"
    if save_data(payments, sha, commit_msg):
        status = compute_status(payments)
        ms = next((s for s in status if s["name"] == matched), None)
        result = f"✅ <b>저장 완료!</b>\n\n👤 {matched} — {months}개월 추가\n📅 결제일: {pay_date}\n"
        if ms:
            emoji = {"safe": "🟢", "soon": "🟡", "expired": "🔴"}[ms["state"]]
            dday = f"D+{abs(ms['days_left'])}" if ms["days_left"] < 0 else f"D-{ms['days_left']}"
            result += f"\n{emoji} 만료일: <b>{ms['cover_end']}</b>  {dday}\n    총 {ms['total_months']}개월 누적"
        send_msg(chat_id, result)
    else:
        send_msg(chat_id, "❌ GitHub 저장 실패. 다시 시도해주세요.")


def handle_del(chat_id, args):
    if not args:
        send_msg(chat_id, "⚠️ 형식: <code>/del 이름</code>\n예: <code>/del 구회원</code>")
        return

    name_query = args[0]
    payments, sha = load_data()
    if not sha:
        send_msg(chat_id, "❌ data.json을 불러올 수 없습니다")
        return

    members = sorted(set(p["name"] for p in payments))
    matched = find_member(name_query, members)

    if not matched:
        send_msg(chat_id, f"⚠️ '<b>{name_query}</b>' 멤버를 찾을 수 없습니다\n전체: {', '.join(members)}")
        return

    member_payments = sorted([p for p in payments if p["name"] == matched], key=lambda x: x["date"])
    last = member_payments[-1]
    payments = [p for p in payments if p["id"] != last["id"]]
    commit_msg = f"Delete payment: {matched} {last['months']}mo ({last['date']}) via Telegram"

    if save_data(payments, sha, commit_msg):
        result = f"🗑️ <b>삭제 완료</b>\n\n👤 {matched}\n📅 {last['date']} / {last['months']}개월 삭제"
        if any(p["name"] == matched for p in payments):
            status = compute_status(payments)
            ms = next((s for s in status if s["name"] == matched), None)
            if ms:
                result += f"\n\n현재 만료일: {ms['cover_end']} (D-{ms['days_left']})"
        else:
            result += "\n\n⚠️ 이 멤버의 기록이 모두 삭제됨"
        send_msg(chat_id, result)
    else:
        send_msg(chat_id, "❌ GitHub 저장 실패. 다시 시도해주세요.")


def is_allowed(chat_id):
    return str(chat_id) in ALLOWED_CHATS


# ─── 메인 ───

def process_updates():
    offset, offset_sha = load_offset()
    params = {"timeout": 0, "allowed_updates": '["message"]'}
    if offset > 0:
        params["offset"] = offset + 1

    result = tg_api(f"getUpdates?{urllib.parse.urlencode(params)}")
    if not result.get("ok") or not result.get("result"):
        print("No new updates")
        return

    updates = result["result"]
    print(f"Processing {len(updates)} updates")
    max_id = offset

    for update in updates:
        uid = update["update_id"]
        if uid > max_id:
            max_id = uid
        if "message" in update:
            handle_message(update["message"])

    if max_id > offset:
        save_offset(max_id, offset_sha)
        print(f"Offset → {max_id}")


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set"); sys.exit(1)
    if not GH_TOKEN:
        print("ERROR: GH_TOKEN not set"); sys.exit(1)
    if not GH_REPO:
        print("ERROR: GH_REPO not set"); sys.exit(1)
    if not ALLOWED_CHATS:
        print("WARNING: TELEGRAM_CHAT_ID not set")
    process_updates()
