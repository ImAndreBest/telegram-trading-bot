import os
import re
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, jsonify, request

# ============================================================
# ENVIRONMENT
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable")

PUBLIC_CHANNEL_CHAT_ID = os.getenv("PUBLIC_CHANNEL_CHAT_ID", "").strip()
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID", "").strip()
BRAND_NAME = os.getenv("BRAND_NAME", "US30 Mastery").strip() or "US30 Mastery"
DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
FILE_BASE = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"

app = Flask(__name__)

# ============================================================
# STORAGE
# ============================================================

CASES_DIR = DATA_DIR / "cases"
WEEKS_DIR = DATA_DIR / "weekly_reviews"
INDEX_DIR = DATA_DIR / "indexes"

for folder in (DATA_DIR, CASES_DIR, WEEKS_DIR, INDEX_DIR):
    folder.mkdir(parents=True, exist_ok=True)

# ============================================================
# RUNTIME STATE
# ============================================================

ACTIVE_CASES: Dict[str, Dict[str, Any]] = {}
ACTIVE_WEEKS: Dict[str, Dict[str, Any]] = {}
PENDING_TEXT_INPUTS: Dict[str, Dict[str, str]] = {}

CHART_ORDER = ["4h", "1h", "15m"]
VALID_STATUSES = {
    "no_trade",
    "trade_active",
    "tp_hit",
    "stop_out",
    "manual_exit",
    "lesson",
    "missed_trade",
}
CLOSED_STATUSES = {"tp_hit", "stop_out", "manual_exit"}
REAL_TRADE_STATUSES = {"trade_active", "tp_hit", "stop_out", "manual_exit"}

REQUIRED_BREAKDOWN_HEADERS = [
    "📊 {asset} — Market Snapshot",
    "📘 What’s Happening?",
    "🏗️ Structure",
    "💧 Liquidity",
    "🎯 Trade Logic",
    "⚠️ Risk",
    "🧠 Trader Insight",
    "✅ Bottom Line",
]

# ============================================================
# TELEGRAM HELPERS
# ============================================================

def tg(method: str, payload: Optional[dict] = None, files: Optional[dict] = None) -> dict:
    url = f"{API_BASE}/{method}"
    if files:
        resp = requests.post(url, data=payload or {}, files=files, timeout=60)
    else:
        resp = requests.post(url, json=payload or {}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def send_message(chat_id: str, text: str, parse_mode: Optional[str] = None) -> dict:
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return tg("sendMessage", payload)


def send_long_message(
    chat_id: str,
    text: str,
    parse_mode: Optional[str] = None,
    chunk_size: int = 3500,
) -> List[dict]:
    """
    Telegram messages can fail when they exceed the practical 4096 character limit.
    This helper splits long text cleanly on line boundaries and sends it in sequence.
    """
    text = safe_text(text)
    if not text:
        return []

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for line in text.splitlines(True):
        if current and current_len + len(line) > chunk_size:
            chunks.append("".join(current).strip())
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)

    if current:
        chunks.append("".join(current).strip())

    normalized: List[str] = []
    for chunk in chunks:
        if len(chunk) <= chunk_size:
            normalized.append(chunk)
            continue
        start = 0
        while start < len(chunk):
            normalized.append(chunk[start:start + chunk_size].strip())
            start += chunk_size

    results: List[dict] = []
    for chunk in normalized:
        if chunk:
            results.append(send_message(chat_id, chunk, parse_mode=parse_mode))
    return results


def send_media_group(chat_id: str, media: List[dict]) -> dict:
    payload = {"chat_id": chat_id, "media": media}
    return tg("sendMediaGroup", payload)

# ============================================================
# GENERAL HELPERS
# ============================================================

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_header_text(value: str) -> str:
    value = safe_text(value)
    value = value.replace("’", "'")
    value = value.replace("–", "—")
    value = re.sub(r"[ \t]+", " ", value)
    return value


def next_case_id() -> str:
    today = utc_now().strftime("%Y_%m_%d")
    existing = sorted(CASES_DIR.glob(f"case_{today}_*.json"))
    seq = len(existing) + 1
    return f"case_{today}_{seq:03d}"


def current_week_id() -> str:
    dt = utc_now()
    year, week, _ = dt.isocalendar()
    return f"weekly_review_{year}_week_{week:02d}"


def case_path(case_id: str) -> Path:
    return CASES_DIR / f"{case_id}.json"


def week_path(review_id: str) -> Path:
    return WEEKS_DIR / f"{review_id}.json"


def save_json(path: Path, payload: dict) -> None:
    payload = dict(payload)
    payload["updated_at"] = now_iso()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def set_pending_text(chat_id: str, target: str) -> None:
    PENDING_TEXT_INPUTS[chat_id] = {"target": target}


def clear_pending_text(chat_id: str) -> None:
    PENDING_TEXT_INPUTS.pop(chat_id, None)


def is_owner(chat_id: str) -> bool:
    return bool(OWNER_CHAT_ID) and str(chat_id) == OWNER_CHAT_ID


def parse_kv_block(block: str) -> Dict[str, str]:
    """
    Parses blocks like:
    key: value
    other_key: another value
    """
    data: Dict[str, str] = {}
    for raw in block.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip().lower()] = value.strip()
    return data


def build_caption_from_breakdown(asset: str, breakdown: str) -> str:
    """
    Builds a short Telegram image caption from the top of the new analysis format.
    Telegram media captions are capped around 1024 chars, so keep this compact.
    """
    asset = safe_text(asset).upper()
    lines = [line.strip() for line in breakdown.splitlines() if line.strip()]
    if not lines:
        return f"📊 {asset} — Market Snapshot"

    header = lines[0]
    if "Market Snapshot" not in header:
        header = f"📊 {asset} — Market Snapshot"

    bias = next((line for line in lines if line.lower().startswith("bias:")), "")
    structure = next((line for line in lines if line.lower().startswith("structure:")), "")
    flow = next((line for line in lines if line.lower().startswith("short-term flow:")), "")

    caption_lines = [header]
    if bias:
        caption_lines.append(bias)
    if structure:
        caption_lines.append(structure)
    if flow:
        caption_lines.append(flow)

    caption = "\n".join(caption_lines).strip()
    return caption[:1024].strip()


def parse_analysis_sections(asset: str, block: str) -> Dict[str, str]:
    """
    Live format:
    Full block is the breakdown itself, starting with:
    📊 ASSET — Market Snapshot

    Legacy tagged formats are still tolerated silently so old saved habits do not hard-break.
    """
    sections = {"internal_read": "", "caption_draft": "", "breakdown_draft": ""}
    raw = safe_text(block)
    if not raw:
        return sections

    # Legacy tagged format support
    tag_pattern = re.compile(r"\[(INTERNAL|CAPTION|BREAKDOWN)\]", re.IGNORECASE)
    matches = list(tag_pattern.finditer(raw))
    if matches:
        for i, match in enumerate(matches):
            tag = match.group(1).lower()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            content = raw[start:end].strip()
            if tag == "internal":
                sections["internal_read"] = content
            elif tag == "caption":
                sections["caption_draft"] = content
            elif tag == "breakdown":
                sections["breakdown_draft"] = content

        if sections["breakdown_draft"] and not sections["caption_draft"]:
            sections["caption_draft"] = build_caption_from_breakdown(asset, sections["breakdown_draft"])
        return sections

    # Legacy label-based support
    lines = raw.splitlines()
    current_key = None
    buffer: List[str] = []

    def flush() -> None:
        nonlocal current_key, buffer
        if current_key:
            sections[current_key] = "\n".join(buffer).strip()
        current_key = None
        buffer = []

    mapping = {
        "internal_read:": "internal_read",
        "caption_draft:": "caption_draft",
        "breakdown_draft:": "breakdown_draft",
    }

    for line in lines:
        stripped = line.strip().lower()
        if stripped in mapping:
            flush()
            current_key = mapping[stripped]
            continue
        if current_key:
            buffer.append(line.rstrip())

    flush()

    if sections["breakdown_draft"]:
        if not sections["caption_draft"]:
            sections["caption_draft"] = build_caption_from_breakdown(asset, sections["breakdown_draft"])
        return sections

    # Live format: the full pasted block is the breakdown
    sections["breakdown_draft"] = raw
    sections["caption_draft"] = build_caption_from_breakdown(asset, raw)
    return sections


def validate_breakdown_draft(asset: str, breakdown: str) -> Tuple[bool, str]:
    asset = safe_text(asset).upper()
    breakdown_norm = normalize_header_text(breakdown)

    required_headers = [
        normalize_header_text(header.format(asset=asset) if "{asset}" in header else header)
        for header in REQUIRED_BREAKDOWN_HEADERS
    ]

    for header in required_headers:
        if header not in breakdown_norm:
            return False, f"Analysis block incomplete ⚠️\nMissing header: {header}"

    return True, ""


def best_photo_id(message: dict) -> str:
    photos = message.get("photo", [])
    if not photos:
        return ""
    return photos[-1].get("file_id", "")


def best_photo_unique_id(message: dict) -> str:
    photos = message.get("photo", [])
    if not photos:
        return ""
    return photos[-1].get("file_unique_id", "")


def count_attached_charts(case: dict) -> int:
    return sum(1 for tf in CHART_ORDER if safe_text(case["charts"].get(tf, {}).get("file_id")))

# ============================================================
# CASE MODEL
# ============================================================

def make_case(chat_id: str, instrument: str, status: str) -> dict:
    case_id = next_case_id()
    return {
        "case_id": case_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "owner_chat_id": str(chat_id),
        "brand_name": BRAND_NAME,
        "instrument": instrument.upper().strip(),
        "status": status.strip(),
        "upload_order": CHART_ORDER[:],
        "next_chart_index": 0,
        "charts_complete": False,
        "charts": {
            "4h": {"file_id": "", "file_unique_id": "", "received_at": ""},
            "1h": {"file_id": "", "file_unique_id": "", "received_at": ""},
            "15m": {"file_id": "", "file_unique_id": "", "received_at": ""},
        },
        "analysis": {
            "internal_read": "",
            "caption_draft": "",
            "breakdown_draft": "",
            "mode_label": "",
            "format_version": "market_snapshot_v2",
            "last_generated_at": "",
        },
        "trade": {
            "entry_price": "",
            "stop_loss": "",
            "take_profit": "",
            "lot_size": "",
            "direction": "",
            "risk_note": "",
            "timing_note": "",
            "result_type": "",
            "pnl": "",
            "rr_if_known": "",
            "outcome_summary": "",
            "lesson": "",
            "grade": "",
            "clean_or_forced": "",
            "what_was_done_well": "",
            "biggest_mistake": "",
            "emotional_leak": "",
            "what_i_need_to_improve": "",
        },
        "archive": {
            "private_preview_message_ids": [],
            "public_message_ids": [],
        },
    }


def save_case(case: dict) -> None:
    save_json(case_path(case["case_id"]), case)


def current_case(chat_id: str) -> Optional[dict]:
    return ACTIVE_CASES.get(str(chat_id))


def format_status_label(status: str) -> str:
    return status.replace("_", " ").title()


def case_ready_for_analysis(case: dict) -> Tuple[bool, str]:
    if not safe_text(case.get("instrument")):
        return False, "Missing instrument."
    if case.get("status") not in VALID_STATUSES:
        return False, "Missing or invalid status."
    if not case.get("charts_complete"):
        return False, "Missing required chart packet (4H + 1H + 15M)."
    return True, ""


def case_ready_for_push(case: dict) -> Tuple[bool, str]:
    ready, reason = case_ready_for_analysis(case)
    if not ready:
        return False, reason
    if not safe_text(case["analysis"].get("breakdown_draft")):
        return False, "Missing analysis block. Run /analysis first."
    if not PUBLIC_CHANNEL_CHAT_ID:
        return False, "Missing PUBLIC_CHANNEL_CHAT_ID env var."
    return True, ""

# ============================================================
# WEEKLY MODEL
# ============================================================

def generate_weekly_review(chat_id: str) -> dict:
    review_id = current_week_id()
    now = utc_now()
    year, week, weekday = now.isocalendar()
    week_start = (now - timedelta(days=weekday - 1)).date().isoformat()
    week_end = (now + timedelta(days=(7 - weekday))).date().isoformat()

    case_files = sorted(CASES_DIR.glob("case_*.json"))
    cases = [load_json(p) for p in case_files]

    def in_current_week(case: dict) -> bool:
        try:
            dt = datetime.fromisoformat(case["created_at"].replace("Z", "+00:00"))
            y, w, _ = dt.isocalendar()
            return y == year and w == week
        except Exception:
            return False

    cases = [c for c in cases if in_current_week(c)]
    total_cases = len(cases)
    trade_cases = [
        c for c in cases
        if c.get("status") in REAL_TRADE_STATUSES or safe_text(c.get("trade", {}).get("entry_price"))
    ]
    closed_cases = [
        c for c in trade_cases
        if c.get("status") in CLOSED_STATUSES or safe_text(c.get("trade", {}).get("result_type"))
    ]

    wins = 0
    losses = 0
    break_even = 0
    clean = 0
    forced = 0
    setup_counts: Dict[str, int] = {}
    mistake_counts: Dict[str, int] = {}
    leak_counts: Dict[str, int] = {}
    strong_counts: Dict[str, int] = {}
    lesson_counts: Dict[str, int] = {}

    for case in trade_cases:
        trade = case.get("trade", {})
        status = case.get("status", "")
        result_type = safe_text(trade.get("result_type")) or status

        if result_type == "tp_hit":
            wins += 1
        elif result_type == "stop_out":
            losses += 1
        elif result_type == "manual_exit":
            break_even += 1

        grade = safe_text(trade.get("grade")).lower()
        clean_or_forced = safe_text(trade.get("clean_or_forced")).lower()
        if grade == "clean" or clean_or_forced == "clean":
            clean += 1
        if grade == "forced" or clean_or_forced == "forced":
            forced += 1

        setup = safe_text(case.get("status"))
        if setup:
            setup_counts[setup] = setup_counts.get(setup, 0) + 1

        mistake = safe_text(trade.get("biggest_mistake"))
        if mistake:
            mistake_counts[mistake] = mistake_counts.get(mistake, 0) + 1

        leak = safe_text(trade.get("emotional_leak"))
        if leak:
            leak_counts[leak] = leak_counts.get(leak, 0) + 1

        strong = safe_text(trade.get("what_was_done_well"))
        if strong:
            strong_counts[strong] = strong_counts.get(strong, 0) + 1

        lesson = safe_text(trade.get("lesson"))
        if lesson:
            lesson_counts[lesson] = lesson_counts.get(lesson, 0) + 1

    def top_key(counts: Dict[str, int], default: str) -> str:
        if not counts:
            return default
        return sorted(counts.items(), key=lambda x: (-x[1], x[0]))[0][0]

    best_setup = top_key(setup_counts, "none logged")
    worst_mistake = top_key(mistake_counts, "none material")
    dominant_emotional_leak = top_key(leak_counts, "minimal")
    strongest_behavior = top_key(strong_counts, "followed process and respected structure")
    doctrine_reinforced = "confirmation beats prediction" if clean >= forced else "discipline must tighten"
    weekly_lesson = top_key(lesson_counts, "The week improves when structure stays ahead of urgency")
    bottom_line = doctrine_reinforced

    return {
        "review_id": review_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "owner_chat_id": str(chat_id),
        "week_start": week_start,
        "week_end": week_end,
        "status": "draft",
        "total_cases": total_cases,
        "total_trades": len(trade_cases),
        "closed_trades": len(closed_cases),
        "clean_trades": clean,
        "forced_trades": forced,
        "wins": wins,
        "losses": losses,
        "break_even": break_even,
        "best_setup": best_setup,
        "worst_mistake": worst_mistake,
        "dominant_emotional_leak": dominant_emotional_leak,
        "strongest_behavior": strongest_behavior,
        "doctrine_reinforced": doctrine_reinforced,
        "weekly_lesson": weekly_lesson,
        "bottom_line": bottom_line,
        "included_case_ids": [c["case_id"] for c in cases],
    }


def save_week(review: dict) -> None:
    save_json(week_path(review["review_id"]), review)

# ============================================================
# PREVIEW BUILDERS
# ============================================================

def build_case_summary(case: dict) -> str:
    analysis = case["analysis"]
    trade = case["trade"]
    chart_count = count_attached_charts(case)

    lines = [
        "Case Preview 📘",
        f"ID: {case['case_id']}",
        f"Instrument: {case['instrument']}",
        f"Status: {format_status_label(case['status'])}",
        f"Charts: {chart_count}/3",
        f"4H: {'✅' if case['charts']['4h']['file_id'] else '—'}",
        f"1H: {'✅' if case['charts']['1h']['file_id'] else '—'}",
        f"15M: {'✅' if case['charts']['15m']['file_id'] else '—'}",
        "",
        f"Analysis Ready: {'✅' if safe_text(analysis['breakdown_draft']) else '—'}",
        f"Caption Ready: {'✅' if safe_text(analysis['caption_draft']) else '—'}",
    ]

    has_trade = any(safe_text(v) for v in trade.values())
    if has_trade:
        lines += [
            "",
            "Trade Block 🎯",
            f"Entry: {safe_text(trade['entry_price']) or '—'} | Stop: {safe_text(trade['stop_loss']) or '—'} | TP: {safe_text(trade['take_profit']) or '—'}",
            f"Result: {safe_text(trade['result_type']) or '—'} | PnL: {safe_text(trade['pnl']) or '—'}",
            f"Grade: {safe_text(trade['grade']) or safe_text(trade['clean_or_forced']) or '—'}",
        ]

    if safe_text(analysis["caption_draft"]):
        lines += ["", "Telegram-Ready Image Caption 📲", analysis["caption_draft"]]

    if safe_text(analysis["breakdown_draft"]):
        lines += ["", "Telegram-Ready Breakdown Post 🧠", analysis["breakdown_draft"]]

    return "\n".join(lines).strip()


def build_week_preview(review: dict) -> str:
    return "\n".join([
        "Weekly Review Preview 📊",
        f"ID: {review['review_id']}",
        f"Week: {review['week_start']} → {review['week_end']}",
        f"Cases: {review['total_cases']}",
        f"Trades: {review['total_trades']} | Closed: {review['closed_trades']}",
        f"Clean: {review['clean_trades']} | Forced: {review['forced_trades']}",
        f"Wins: {review['wins']} | Losses: {review['losses']} | BE: {review['break_even']}",
        f"Best Setup: {review['best_setup']}",
        f"Worst Mistake: {review['worst_mistake']}",
        f"Emotional Leak: {review['dominant_emotional_leak']}",
        f"Strongest Behavior: {review['strongest_behavior']}",
        f"Doctrine Reinforced: {review['doctrine_reinforced']}",
        f"Weekly Lesson: {review['weekly_lesson']}",
        f"Bottom Line: {review['bottom_line']}",
    ]).strip()


def build_week_recap(review: dict) -> str:
    return "\n".join([
        f"{BRAND_NAME} — Weekly Recap 📊",
        "",
        f"Week Window: {review['week_start']} → {review['week_end']}",
        f"Cases Logged: {review['total_cases']}",
        f"Trades Logged: {review['total_trades']}",
        f"Wins / Losses / BE: {review['wins']} / {review['losses']} / {review['break_even']}",
        "",
        "Best Setup",
        f"{review['best_setup']}",
        "",
        "Strongest Behavior ✅",
        f"{review['strongest_behavior']}",
        "",
        "Main Leak ⚠️",
        f"{review['dominant_emotional_leak']}",
        "",
        "Weekly Lesson 🧠",
        f"{review['weekly_lesson']}",
        "",
        "Bottom Line ✅",
        f"{review['bottom_line']}",
    ]).strip()

# ============================================================
# COMMANDS
# ============================================================

def cmd_help(chat_id: str) -> None:
    text = "\n".join([
        f"{BRAND_NAME} — Unified Case System 📘",
        "",
        "Daily Core",
        "/case BTCUSD no_trade",
        "/analysis",
        "/trade",
        "/preview",
        "/push",
        "/status",
        "/cancel",
        "",
        "Weekly Core",
        "/week_generate",
        "/week_preview",
        "/week_save",
        "/week_recap",
        "",
        "Live analysis block format",
        "📊 ASSET — Market Snapshot",
        "Bias: ...",
        "Structure: ...",
        "Short-Term Flow: ...",
        "",
        "📘 What’s Happening?",
        "...",
        "",
        "🏗️ Structure",
        "...",
        "",
        "💧 Liquidity",
        "...",
        "",
        "🎯 Trade Logic",
        "...",
        "",
        "⚠️ Risk",
        "...",
        "",
        "🧠 Trader Insight",
        "...",
        "",
        "✅ Bottom Line",
        "...",
        "",
        "Trade block format",
        "entry_price: 66680",
        "stop_loss: 66914",
        "take_profit: 65516",
        "lot_size: 0.05",
        "direction: sell",
        "result_type: tp_hit",
        "pnl: 58.40",
        "rr_if_known: 1:2.1",
        "lesson: patience after location produced cleaner execution",
        "grade: clean",
    ])
    send_long_message(chat_id, text)


def cmd_status(chat_id: str) -> None:
    case = current_case(chat_id)
    week = ACTIVE_WEEKS.get(str(chat_id))
    text = "\n".join([
        "System Status 🧾",
        f"Active case: {case['case_id'] if case else 'None'}",
        f"Instrument: {case['instrument'] if case else '—'}",
        f"Status: {case['status'] if case else '—'}",
        f"Charts loaded: {count_attached_charts(case) if case else 0}/3",
        f"Analysis ready: {'yes' if case and safe_text(case['analysis']['breakdown_draft']) else 'no'}",
        f"Weekly review: {week['review_id'] if week else 'None'}",
    ])
    send_message(chat_id, text)


def cmd_case(chat_id: str, arg: str) -> None:
    parts = arg.split()
    if len(parts) < 2:
        send_message(chat_id, "Usage: /case INSTRUMENT STATUS\nExample: /case BTCUSD no_trade")
        return

    instrument = parts[0].upper().strip()
    status = parts[1].strip().lower()

    if status not in VALID_STATUSES:
        send_message(
            chat_id,
            "Invalid status. Use one of:\nno_trade, trade_active, tp_hit, stop_out, manual_exit, lesson, missed_trade",
        )
        return

    case = make_case(chat_id, instrument, status)
    ACTIVE_CASES[str(chat_id)] = case
    clear_pending_text(chat_id)
    save_case(case)

    send_message(
        chat_id,
        f"Case opened ✅\nID: {case['case_id']}\nInstrument: {instrument}\nStatus: {status}\n\nSend 4H, then 1H, then 15M now 📘",
    )


def cmd_analysis(chat_id: str, block: str) -> None:
    case = current_case(chat_id)
    if not case:
        send_message(chat_id, "No active case. Start with /case INSTRUMENT STATUS")
        return

    ready, reason = case_ready_for_analysis(case)
    if not ready:
        send_message(chat_id, f"Analysis blocked ⚠️\n{reason}")
        return

    if not block.strip():
        set_pending_text(chat_id, "analysis")
        asset = case["instrument"].upper().strip()
        template = "\n".join([
            "Paste the analysis block now 📲",
            "",
            "Use this format:",
            f"📊 {asset} — Market Snapshot",
            "Bias: ...",
            "Structure: ...",
            "Short-Term Flow: ...",
            "",
            "📘 What’s Happening?",
            "...",
            "",
            "🏗️ Structure",
            "...",
            "",
            "💧 Liquidity",
            "...",
            "",
            "🎯 Trade Logic",
            "...",
            "",
            "⚠️ Risk",
            "...",
            "",
            "🧠 Trader Insight",
            "...",
            "",
            "✅ Bottom Line",
            "...",
        ])
        send_message(chat_id, template)
        return

    sections = parse_analysis_sections(case["instrument"], block)
    breakdown = safe_text(sections["breakdown_draft"])
    if not breakdown:
        send_message(chat_id, "Analysis block incomplete ⚠️\nMissing analysis content.")
        return

    ok, error_msg = validate_breakdown_draft(case["instrument"], breakdown)
    if not ok:
        send_message(chat_id, error_msg)
        return

    case["analysis"]["internal_read"] = ""
    case["analysis"]["breakdown_draft"] = breakdown
    case["analysis"]["caption_draft"] = sections["caption_draft"] or build_caption_from_breakdown(case["instrument"], breakdown)
    case["analysis"]["mode_label"] = format_status_label(case["status"])
    case["analysis"]["format_version"] = "market_snapshot_v2"
    case["analysis"]["last_generated_at"] = now_iso()
    save_case(case)
    clear_pending_text(chat_id)
    send_message(chat_id, "Analysis package saved ✅")


def cmd_trade(chat_id: str, block: str) -> None:
    case = current_case(chat_id)
    if not case:
        send_message(chat_id, "No active case. Start with /case INSTRUMENT STATUS")
        return

    if not block.strip():
        set_pending_text(chat_id, "trade")
        template = "\n".join([
            "Paste the trade block now 🎯",
            "",
            "Example:",
            "entry_price: 66680",
            "stop_loss: 66914",
            "take_profit: 65516",
            "lot_size: 0.05",
            "direction: sell",
            "result_type: tp_hit",
            "pnl: 58.40",
            "rr_if_known: 1:2.1",
            "risk_note: structure first, size fitted to invalidation",
            "timing_note: entered after failed reclaim confirmation",
            "outcome_summary: downside delivery completed into target liquidity",
            "clean_or_forced: clean",
            "what_was_done_well: waited for confirmation at location",
            "biggest_mistake: none material",
            "emotional_leak: minimal",
            "lesson: patience after location produced cleaner execution",
            "what_i_need_to_improve: continue avoiding anticipation",
            "grade: clean",
        ])
        send_message(chat_id, template)
        return

    data = parse_kv_block(block)
    trade = case["trade"]

    for key in trade.keys():
        if key in data:
            trade[key] = data[key]

    if safe_text(data.get("direction")):
        trade["direction"] = data["direction"]

    if safe_text(trade.get("direction")):
        case["trade"]["direction"] = trade["direction"]

    save_case(case)
    clear_pending_text(chat_id)
    send_message(chat_id, "Trade block saved ✅")


def cmd_preview(chat_id: str) -> None:
    case = current_case(chat_id)
    if not case:
        send_message(chat_id, "No active case. Start with /case INSTRUMENT STATUS")
        return

    preview_text = build_case_summary(case)
    results = send_long_message(chat_id, preview_text)

    try:
        for result in results:
            msg_id = result.get("result", {}).get("message_id")
            if msg_id:
                case["archive"]["private_preview_message_ids"].append(msg_id)
        save_case(case)
    except Exception:
        pass


def cmd_push(chat_id: str) -> None:
    case = current_case(chat_id)
    if not case:
        send_message(chat_id, "No active case. Start with /case INSTRUMENT STATUS")
        return

    ready, reason = case_ready_for_push(case)
    if not ready:
        send_message(chat_id, f"Push blocked ⚠️\n{reason}")
        return

    caption = safe_text(case["analysis"]["caption_draft"]) or build_caption_from_breakdown(
        case["instrument"],
        case["analysis"]["breakdown_draft"],
    )
    breakdown = case["analysis"]["breakdown_draft"]

    media = []
    for i, tf in enumerate(CHART_ORDER):
        item = {
            "type": "photo",
            "media": case["charts"][tf]["file_id"],
        }
        if i == 0 and caption:
            item["caption"] = caption[:1024]
        media.append(item)

    try:
        media_resp = send_media_group(PUBLIC_CHANNEL_CHAT_ID, media)
        msg_responses = send_long_message(PUBLIC_CHANNEL_CHAT_ID, breakdown)
        public_ids = []
        if isinstance(media_resp.get("result"), list):
            public_ids.extend([m.get("message_id") for m in media_resp["result"] if m.get("message_id")])
        for response in msg_responses:
            msg_id = response.get("result", {}).get("message_id")
            if msg_id:
                public_ids.append(msg_id)
        case["archive"]["public_message_ids"] = public_ids
        save_case(case)
        send_message(chat_id, "Push completed ✅")
    except Exception as exc:
        send_message(chat_id, f"Push failed ⚠️\n{exc}")


def cmd_push_chart(chat_id: str) -> None:
    case = current_case(chat_id)
    if not case:
        send_message(chat_id, "No active case.")
        return
    if not PUBLIC_CHANNEL_CHAT_ID:
        send_message(chat_id, "Push blocked ⚠️\nMissing PUBLIC_CHANNEL_CHAT_ID env var.")
        return

    caption = safe_text(case["analysis"]["caption_draft"]) or build_caption_from_breakdown(
        case["instrument"],
        case["analysis"]["breakdown_draft"],
    )

    media = []
    for i, tf in enumerate(CHART_ORDER):
        if not case["charts"][tf]["file_id"]:
            send_message(chat_id, "Push blocked ⚠️\nMissing full chart packet.")
            return
        item = {"type": "photo", "media": case["charts"][tf]["file_id"]}
        if i == 0 and caption:
            item["caption"] = caption[:1024]
        media.append(item)

    try:
        send_media_group(PUBLIC_CHANNEL_CHAT_ID, media)
        send_message(chat_id, "Chart packet pushed ✅")
    except Exception as exc:
        send_message(chat_id, f"Push failed ⚠️\n{exc}")


def cmd_push_chartbreakdown(chat_id: str) -> None:
    case = current_case(chat_id)
    if not case:
        send_message(chat_id, "No active case.")
        return
    if not PUBLIC_CHANNEL_CHAT_ID:
        send_message(chat_id, "Push blocked ⚠️\nMissing PUBLIC_CHANNEL_CHAT_ID env var.")
        return
    if not safe_text(case["analysis"]["breakdown_draft"]):
        send_message(chat_id, "Push blocked ⚠️\nMissing analysis block.")
        return
    try:
        send_long_message(PUBLIC_CHANNEL_CHAT_ID, case["analysis"]["breakdown_draft"])
        send_message(chat_id, "Breakdown pushed ✅")
    except Exception as exc:
        send_message(chat_id, f"Push failed ⚠️\n{exc}")


def cmd_cancel(chat_id: str) -> None:
    ACTIVE_CASES.pop(str(chat_id), None)
    clear_pending_text(chat_id)
    send_message(chat_id, "Active case cancelled ✅")


def cmd_week_generate(chat_id: str) -> None:
    review = generate_weekly_review(chat_id)
    ACTIVE_WEEKS[str(chat_id)] = review
    send_message(chat_id, "Weekly review generated ✅")


def cmd_week_preview(chat_id: str) -> None:
    review = ACTIVE_WEEKS.get(str(chat_id))
    if not review:
        send_message(chat_id, "No active weekly review. Run /week_generate first.")
        return
    send_long_message(chat_id, build_week_preview(review))


def cmd_week_save(chat_id: str) -> None:
    review = ACTIVE_WEEKS.get(str(chat_id))
    if not review:
        send_message(chat_id, "No active weekly review. Run /week_generate first.")
        return
    review["status"] = "saved"
    save_week(review)
    send_message(chat_id, f"Weekly review saved ✅\nID: {review['review_id']}")


def cmd_week_recap(chat_id: str) -> None:
    review = ACTIVE_WEEKS.get(str(chat_id))
    if not review:
        send_message(chat_id, "No active weekly review. Run /week_generate first.")
        return
    send_long_message(chat_id, build_week_recap(review))

# ============================================================
# IMAGE HANDLING
# ============================================================

def handle_photo_message(chat_id: str, message: dict) -> None:
    case = current_case(chat_id)
    if not case:
        send_message(chat_id, "No active case. Start with /case INSTRUMENT STATUS before sending charts.")
        return

    idx = int(case.get("next_chart_index", 0))
    if idx >= len(CHART_ORDER):
        send_message(chat_id, "Chart packet already complete ✅\nUse /preview or /analysis next.")
        return

    tf = CHART_ORDER[idx]
    case["charts"][tf]["file_id"] = best_photo_id(message)
    case["charts"][tf]["file_unique_id"] = best_photo_unique_id(message)
    case["charts"][tf]["received_at"] = now_iso()
    case["next_chart_index"] = idx + 1
    case["charts_complete"] = case["next_chart_index"] >= len(CHART_ORDER)
    save_case(case)

    if case["charts_complete"]:
        send_message(
            chat_id,
            "Chart packet saved ✅\n4H + 1H + 15M received.\n\nNext:\n/preview\n/analysis",
        )
    else:
        next_tf = CHART_ORDER[case["next_chart_index"]]
        send_message(chat_id, f"{tf.upper()} chart saved ✅\nSend {next_tf.upper()} next.")

# ============================================================
# COMMAND ROUTER
# ============================================================

def handle_pending_text(chat_id: str, text: str) -> bool:
    pending = PENDING_TEXT_INPUTS.get(str(chat_id))
    if not pending:
        return False

    target = pending.get("target", "")
    if target == "analysis":
        cmd_analysis(chat_id, text)
        return True
    if target == "trade":
        cmd_trade(chat_id, text)
        return True
    return False


def route_command(chat_id: str, text: str) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) == 2:
        cmd, arg = parts[0], parts[1]
    else:
        cmd, arg = text, ""

    cmd = cmd.lower().strip()

    if cmd == "/help":
        return cmd_help(chat_id)
    if cmd == "/status":
        return cmd_status(chat_id)
    if cmd == "/case":
        return cmd_case(chat_id, arg)
    if cmd == "/analysis":
        return cmd_analysis(chat_id, arg)
    if cmd == "/trade":
        return cmd_trade(chat_id, arg)
    if cmd == "/preview":
        return cmd_preview(chat_id)
    if cmd == "/push":
        return cmd_push(chat_id)
    if cmd == "/push_chart":
        return cmd_push_chart(chat_id)
    if cmd == "/push_chartbreakdown":
        return cmd_push_chartbreakdown(chat_id)
    if cmd == "/cancel":
        return cmd_cancel(chat_id)
    if cmd == "/week_generate":
        return cmd_week_generate(chat_id)
    if cmd == "/week_preview":
        return cmd_week_preview(chat_id)
    if cmd == "/week_save":
        return cmd_week_save(chat_id)
    if cmd == "/week_recap":
        return cmd_week_recap(chat_id)

    send_message(chat_id, f"Unknown command ⚠️\n{cmd}\n\nUse /help for the active command set.")


def handle_update(update: dict) -> None:
    message = update.get("message") or update.get("edited_message") or {}
    if not message:
        return

    chat_id = str(message.get("chat", {}).get("id", ""))
    if not chat_id:
        return

    # Optional owner lock
    if OWNER_CHAT_ID and chat_id != OWNER_CHAT_ID:
        send_message(chat_id, "This bot is restricted to the configured owner chat.")
        return

    text = safe_text(message.get("text"))
    if text.startswith("/"):
        route_command(chat_id, text)
        return

    if message.get("photo"):
        handle_photo_message(chat_id, message)
        return

    if text and handle_pending_text(chat_id, text):
        return

    if text:
        send_message(chat_id, "Text received, but no active handler matched. Use /help or /status.")
        return

# ============================================================
# FLASK ROUTES
# ============================================================

@app.get("/")
def root():
    return jsonify({"ok": True, "brand": BRAND_NAME})


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/")
@app.post("/webhook")
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    try:
        handle_update(update)
        return jsonify({"ok": True})
    except Exception as exc:
        print(f"[webhook_error] {exc}", flush=True)
        return jsonify({"ok": False, "error": str(exc)}), 500

# ============================================================
# LOCAL RUN
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
