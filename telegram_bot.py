"""
Telegram Bot for YouTube Premium Payment Tracker
-------------------------------------------------
GitHub Actions에서 schedule(폴링)로 실행됩니다.

동작 흐름:
1. Telegram getUpdates로 새 메시지/콜백 확인
2. 인라인 키보드 버튼으로 이름 → 개월 수 선택
3. 확인되면 data.json을 GitHub API로 업데이트 + 커밋
4. 결과를 Telegram으로 응답

환경변수:
  TELEGRAM_BOT_TOKEN  - Telegram Bot API 토큰
  TELEGRAM_CHAT_ID    - 허용할 채팅 ID (쉼표 구분으로 여러개 가능)
  GH_TOKEN            - GitHub Personal Access Token (repo 권한)
  GH_REPO             - owner/repo 형식 (예: myuser/yt-premium)
  DATA_PATH            - JSON 파일 경로 (기본: data.json)
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
GH_REPO = os.environ.get("GH_REPO", "")  # owner/repo
DATA_PATH = os.environ.get("DATA_PATH", "data.json")
OFFSET_FILE = "/tmp/tg_offset.txt"  # Actions에서 offset 유지용

KST = timezone(timedelta(hours=9))

# ─── 멤버 목록 (data.json에서 동적으로도 읽지만 버튼용 기본값) ───
# 실행 시 data.json에서 자동 로드됩니다.


def tg_api(method, data=None):
    """Telegram Bot API 호출"""
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
        err = e.read().decode()
        print(f"TG API error: {e.code} {err}")
        return {"ok": False, "error": err}


def gh_api(endpoint, method="GET", data=None):
    """GitHub REST API 호출"""
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
        err = e.read().decode()
        print(f"GH API error: {e.code} {err}")
        return None


# ─── data.json 읽기/쓰기 ───

def load_data():
    """GitHub에서 data.json 읽기"""
    result = gh_api(f"contents/{DATA_PATH}")
    if not result or "content" not in result:
        print("Failed to load data.json from GitHub")
        return [], None
    content = base64.b64decode(result["content"]).decode("utf-8")
    return json.loads(content), result["sha"]


def save_data(payments, sha, commit_msg="Update payment via Telegram bot"):
    """GitHub에 data.json 커밋"""
    content = base64.b64encode(
        (json.dumps(payments, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    ).decode("ascii")
    result = gh_api(f"contents/{DATA_PATH}", method="PUT", data={
        "message": commit_msg,
        "content": content,
        "sha": sha,
    })
    return result is not None


# ─── 상태 계산 ───

def add_months(d, months):
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    max_days = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(d.day, max_days[month - 1])
    return date(year, month, day)


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
            "name": name,
            "cover_end": cover_end.isoformat(),
            "days_left": days_left,
            "state": state,
            "total_months": total_months,
            "last_date": last["date"],
            "last_months": last["months"],
        })
    result.sort(key=lambda x: x["days_left"])
    return result


# ─── Telegram 메시지/키보드 ───

def send_msg(chat_id, text, reply_markup=None, parse_mode="HTML"):
    data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        data["reply_markup"] = reply_markup
    return tg_api("sendMessage", data)


def edit_msg(chat_id, msg_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    return tg_api("editMessageText", data)


def answer_callback(callback_id, text=""):
    return tg_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def make_member_keyboard(members):
    """멤버 선택 인라인 키보드"""
    buttons = []
    row = []
    for name in members:
        row.append({"text": name, "callback_data": f"member:{name}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"text": "❌ 취소", "callback_data": "cancel"}])
    return {"inline_keyboard": buttons}


def make_months_keyboard(name):
    """개월 수 선택 인라인 키보드"""
    presets = [1, 3, 5, 6, 12, 15]
    buttons = []
    row = []
    for m in presets:
        row.append({"text": f"{m}개월", "callback_data": f"months:{name}:{m}"})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"text": "⬅️ 뒤로", "callback_data": "back"}, {"text": "❌ 취소", "callback_data": "cancel"}])
    return {"inline_keyboard": buttons}


def make_confirm_keyboard(name, months):
    """확인 키보드"""
    return {"inline_keyboard": [
        [{"text": "✅ 확인", "callback_data": f"confirm:{name}:{months}"},
         {"text": "❌ 취소", "callback_data": "cancel"}]
    ]}


def format_status(status_list):
    """현황 메시지 포맷"""
    lines = ["📊 <b>YouTube Premium 결제 현황</b>", ""]
    for s in status_list:
        emoji = "🟢" if s["state"] == "safe" else ("🟡" if s["state"] == "soon" else "🔴")
        dday = f"D+{abs(s['days_left'])}" if s["days_left"] < 0 else f"D-{s['days_left']}"
        lines.append(f"{emoji} <b>{s['name']}</b>  {dday}")
        lines.append(f"    만료: {s['cover_end']}  ({s['total_months']}개월 누적)")
        lines.append("")
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    lines.append(f"<i>기준: {now} KST</i>")
    return "\n".join(lines)


# ─── offset 관리 ───

def load_offset():
    """마지막 처리한 update_id를 GitHub에서 로드"""
    result = gh_api("contents/.tg_offset")
    if result and "content" in result:
        content = base64.b64decode(result["content"]).decode("utf-8").strip()
        try:
            return int(content), result["sha"]
        except ValueError:
            pass
    return 0, None


def save_offset(offset, sha=None):
    """offset을 GitHub에 저장"""
    content = base64.b64encode(str(offset).encode()).decode("ascii")
    data = {
        "message": "Update telegram bot offset",
        "content": content,
    }
    if sha:
        data["sha"] = sha
    gh_api("contents/.tg_offset", method="PUT", data=data)


# ─── 메인 처리 ───

def is_allowed(chat_id):
    return str(chat_id) in ALLOWED_CHATS


def process_updates():
    """메인 로직: 새 업데이트 처리"""
    offset, offset_sha = load_offset()

    params = {"timeout": 0, "allowed_updates": '["message","callback_query"]'}
    if offset > 0:
        params["offset"] = offset + 1

    url_params = urllib.parse.urlencode(params)
    result = tg_api(f"getUpdates?{url_params}")

    if not result.get("ok") or not result.get("result"):
        print("No new updates")
        return

    updates = result["result"]
    print(f"Processing {len(updates)} updates")

    max_update_id = offset

    for update in updates:
        uid = update["update_id"]
        if uid > max_update_id:
            max_update_id = uid

        # 일반 메시지 처리
        if "message" in update:
            handle_message(update["message"])

        # 콜백 쿼리 처리 (버튼 클릭)
        if "callback_query" in update:
            handle_callback(update["callback_query"])

    # offset 저장
    if max_update_id > offset:
        save_offset(max_update_id, offset_sha)
        print(f"Offset updated to {max_update_id}")


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    if not is_allowed(chat_id):
        print(f"Unauthorized chat: {chat_id}")
        send_msg(chat_id, "⛔ 권한이 없습니다.\n\n이 채팅 ID를 관리자에게 전달하세요:\n<code>{}</code>".format(chat_id))
        return

    text = msg.get("text", "").strip()

    if text == "/start" or text == "/help":
        send_msg(chat_id, (
            "🎬 <b>YouTube Premium 결제 관리 봇</b>\n\n"
            "📌 <b>명령어:</b>\n"
            "/add — 결제 기록 추가\n"
            "/status — 전체 현황 보기\n"
            "/help — 도움말\n\n"
            "버튼을 눌러서 간편하게 입력할 수 있습니다!"
        ))
        return

    if text == "/status":
        payments, _ = load_data()
        if not payments:
            send_msg(chat_id, "데이터가 없습니다")
            return
        status = compute_status(payments)
        send_msg(chat_id, format_status(status))
        return

    if text == "/add":
        payments, _ = load_data()
        members = sorted(set(p["name"] for p in payments))
        if not members:
            send_msg(chat_id, "등록된 멤버가 없습니다. data.json에 먼저 추가해주세요.")
            return
        send_msg(chat_id,
                 "👤 <b>결제할 멤버를 선택하세요</b>",
                 reply_markup=make_member_keyboard(members))
        return

    # 알 수 없는 메시지
    send_msg(chat_id, "명령어를 선택해주세요: /add, /status, /help")


def handle_callback(callback):
    chat_id = callback["message"]["chat"]["id"]
    msg_id = callback["message"]["message_id"]
    cb_id = callback["id"]
    data = callback.get("data", "")

    if not is_allowed(chat_id):
        answer_callback(cb_id, "권한 없음")
        return

    # ── 취소 ──
    if data == "cancel":
        answer_callback(cb_id, "취소됨")
        edit_msg(chat_id, msg_id, "❌ 취소되었습니다.")
        return

    # ── 뒤로 (멤버 선택으로 돌아감) ──
    if data == "back":
        answer_callback(cb_id)
        payments, _ = load_data()
        members = sorted(set(p["name"] for p in payments))
        edit_msg(chat_id, msg_id,
                 "👤 <b>결제할 멤버를 선택하세요</b>",
                 reply_markup=make_member_keyboard(members))
        return

    # ── 멤버 선택 → 개월 수 ──
    if data.startswith("member:"):
        name = data.split(":", 1)[1]
        answer_callback(cb_id, f"{name} 선택")
        today = datetime.now(KST).strftime("%Y-%m-%d")
        edit_msg(chat_id, msg_id,
                 f"👤 <b>{name}</b>\n📅 결제일: {today}\n\n⏱ <b>개월 수를 선택하세요</b>",
                 reply_markup=make_months_keyboard(name))
        return

    # ── 개월 수 선택 → 확인 ──
    if data.startswith("months:"):
        parts = data.split(":")
        name, months = parts[1], int(parts[2])
        answer_callback(cb_id)
        today = datetime.now(KST).strftime("%Y-%m-%d")

        # 미리보기: 이 결제 후 만료일 계산
        payments, _ = load_data()
        preview_payments = payments + [{"name": name, "date": today, "months": months, "id": "preview"}]
        preview_status = [s for s in compute_status(preview_payments) if s["name"] == name]
        preview_text = ""
        if preview_status:
            ps = preview_status[0]
            preview_text = f"\n\n📊 결제 후 만료일: <b>{ps['cover_end']}</b> (D-{ps['days_left']})"

        edit_msg(chat_id, msg_id,
                 f"📝 <b>결제 확인</b>\n\n"
                 f"👤 이름: <b>{name}</b>\n"
                 f"📅 결제일: <b>{today}</b>\n"
                 f"⏱ 개월: <b>{months}개월</b>"
                 f"{preview_text}\n\n"
                 f"이대로 저장할까요?",
                 reply_markup=make_confirm_keyboard(name, months))
        return

    # ── 최종 확인 → 저장 ──
    if data.startswith("confirm:"):
        parts = data.split(":")
        name, months = parts[1], int(parts[2])
        today = datetime.now(KST).strftime("%Y-%m-%d")

        payments, sha = load_data()
        if not sha:
            answer_callback(cb_id, "데이터 로드 실패")
            edit_msg(chat_id, msg_id, "❌ 데이터를 불러올 수 없습니다. 다시 시도해주세요.")
            return

        # 새 기록 추가
        new_id = "t" + datetime.now(KST).strftime("%Y%m%d%H%M%S")
        payments.append({
            "id": new_id,
            "name": name,
            "date": today,
            "months": months,
        })

        # GitHub에 저장
        commit_msg = f"Add payment: {name} {months}mo ({today}) via Telegram"
        success = save_data(payments, sha, commit_msg)

        if success:
            answer_callback(cb_id, "저장 완료!")
            # 업데이트된 현황
            status = compute_status(payments)
            member_status = next((s for s in status if s["name"] == name), None)
            result_text = (
                f"✅ <b>저장 완료!</b>\n\n"
                f"👤 {name} — {months}개월 추가\n"
                f"📅 결제일: {today}\n"
            )
            if member_status:
                emoji = "🟢" if member_status["state"] == "safe" else ("🟡" if member_status["state"] == "soon" else "🔴")
                result_text += (
                    f"\n{emoji} 만료일: <b>{member_status['cover_end']}</b>\n"
                    f"    D-{member_status['days_left']} | 총 {member_status['total_months']}개월 누적"
                )
            edit_msg(chat_id, msg_id, result_text)
        else:
            answer_callback(cb_id, "저장 실패")
            edit_msg(chat_id, msg_id, "❌ GitHub 저장에 실패했습니다. 다시 시도해주세요.")
        return

    answer_callback(cb_id)


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)
    if not GH_TOKEN:
        print("ERROR: GH_TOKEN not set")
        sys.exit(1)
    if not GH_REPO:
        print("ERROR: GH_REPO not set")
        sys.exit(1)
    if not ALLOWED_CHATS:
        print("WARNING: TELEGRAM_CHAT_ID not set — all chats will be rejected")

    process_updates()
