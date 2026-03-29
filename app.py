import os
import re
import json
import uuid
import shutil
import logging
from datetime import datetime, date
from pathlib import Path
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, request, jsonify

# =========================
# Environment / Config
# =========================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PUBLIC_CHANNEL_CHAT_ID = os.getenv("PUBLIC_CHANNEL_CHAT_ID", "")
PRIVATE_ARCHIVE_CHAT_ID = os.getenv("PRIVATE_ARCHIVE_CHAT_ID", "")
DATA_DIR = Path(os.getenv("DATA_DIR", "/mnt/data/us30_mastery"))
TIMEZONE_NAME = os.getenv("TIMEZONE_NAME", "America/New_York")
DEFAULT_INSTRUMENTS = {"US30", "BTCUSD"}

if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("us30_mastery_bot")

# =========================
# Directories
# =========================
CHART_DIR = DATA_DIR / "charts"
JOURNAL_DIR = DATA_DIR / "journals"
WEEK_DIR = DATA_DIR / "weekly_reviews"
PDFQ_DIR = DATA_DIR / "pdf_queue"
BACKUP_DIR = DATA_DIR / "backups"
STATE_DIR = DATA_DIR / "state"
for p in [CHART_DIR, JOURNAL_DIR, WEEK_DIR, PDFQ_DIR, BACKUP_DIR, STATE_DIR]:
    p.mkdir(parents=True, exist_ok=True)

ARCHIVE_INDEX = BACKUP_DIR / "archive_index.json"
if not ARCHIVE_INDEX.exists():
    ARCHIVE_INDEX.write_text(json.dumps({"journal_archives": {}, "chart_archives": {}}, indent=2))

# =========================
# In-memory active state
# =========================
ACTIVE_CHARTS: Dict[str, Dict[str, Any]] = {}
ACTIVE_JOURNALS: Dict[str, Dict[str, Any]] = {}
ACTIVE_WEEKS: Dict[str, Dict[str, Any]] = {}
PENDING_UPLOADS: Dict[str, Dict[str, str]] = {}
PENDING_TEXT_INPUTS: Dict[str, Dict[str, str]] = {}

# =========================
# Helpers
# =========================
def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_parent(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    shutil.move(str(temp), str(path))


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def parse_kv_block(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in text.strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def sanitize(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]+", "_", text).strip("_")


def current_week_id() -> str:
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    return f"weekly_review_{iso_year}_week_{iso_week:02d}"


def _next_seq(directory: Path, prefix: str) -> int:
    nums = []
    for file in directory.glob(f"{prefix}_*.json"):
        m = re.search(r"_(\d{3})\.json$", file.name)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def generate_chart_id() -> str:
    d = date.today()
    seq = _next_seq(CHART_DIR, f"chart_{d:%Y_%m_%d}")
    return f"chart_{d:%Y_%m_%d}_{seq:03d}"


def generate_journal_id() -> str:
    d = date.today()
    seq = _next_seq(JOURNAL_DIR, f"journal_{d:%Y_%m_%d}")
    return f"journal_{d:%Y_%m_%d}_{seq:03d}"


def generate_pdfq_id() -> str:
    d = date.today()
    seq = _next_seq(PDFQ_DIR, f"pdfq_{d:%Y_%m_%d}")
    return f"pdfq_{d:%Y_%m_%d}_{seq:03d}"


def chart_path(chart_id: str) -> Path:
    return CHART_DIR / f"{chart_id}.json"


def journal_path(journal_id: str) -> Path:
    return JOURNAL_DIR / f"{journal_id}.json"


def week_path(review_id: str) -> Path:
    return WEEK_DIR / f"{review_id}.json"


def pdfq_path(pdfq_id: str) -> Path:
    return PDFQ_DIR / f"{pdfq_id}.json"


def get_archive_index() -> Dict[str, Any]:
    return load_json(ARCHIVE_INDEX)


def save_archive_index(data: Dict[str, Any]) -> None:
    save_json(ARCHIVE_INDEX, data)


def tg_request(method: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{TG_API}/{method}"
    r = requests.post(url, json=payload or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def send_message(chat_id: str, text: str) -> Dict[str, Any]:
    return tg_request("sendMessage", {"chat_id": chat_id, "text": text})


def send_photo(chat_id: str, photo_file_id: str, caption: str = "") -> Dict[str, Any]:
    return tg_request("sendPhoto", {"chat_id": chat_id, "photo": photo_file_id, "caption": caption})


def set_webhook() -> Optional[Dict[str, Any]]:
    if not WEBHOOK_URL:
        return None
    payload = {"url": WEBHOOK_URL}
    if WEBHOOK_SECRET:
        payload["secret_token"] = WEBHOOK_SECRET
    return tg_request("setWebhook", payload)

# =========================
# Object templates
# =========================
def new_chart_packet() -> Dict[str, Any]:
    return {
        "chart_id": generate_chart_id(),
        "status": "draft",
        "type": "live_market_read",
        "instrument": "",
        "trade_status": "no_trade",
        "created_at": now_iso(),
        "note": "",
        "images": {"h4": [], "h1": [], "m15": []},
        "outputs": {
            "internal_read": "",
            "caption_draft": "",
            "breakdown_draft": "",
            "mode_label": "",
            "last_generated_at": "",
        },
        "analysis": {"internal_read": "", "telegram_caption": "", "telegram_breakdown": ""},
    }


def new_journal_draft() -> Dict[str, Any]:
    return {
        "journal_id": generate_journal_id(),
        "status": "draft",
        "type": "",
        "created_at": now_iso(),
        "instrument": "US30",
        "direction": "",
        "session": "",
        "setup_type": "",
        "timeframes": {
            "daily_condition": "",
            "h4_condition": "",
            "h1_condition": "",
            "m15_trigger": "",
        },
        "market_context": {
            "poi": "",
            "liquidity_draw": "",
            "confirmation": "",
            "invalidation": "",
            "target_path": "",
        },
        "execution": {
            "entry_price": "",
            "stop_loss": "",
            "take_profit": "",
            "lot_size": "",
            "risk_note": "",
            "timing_note": "",
        },
        "result": {
            "result_type": "",
            "pnl": "",
            "rr_if_known": "",
            "outcome_summary": "",
        },
        "review": {
            "clean_or_forced": "",
            "what_was_done_well": "",
            "biggest_mistake": "",
            "emotional_leak": "",
            "lesson": "",
            "what_i_need_to_improve": "",
        },
        "images": {
            "daily": [],
            "h4": [],
            "h1": [],
            "m15": [],
            "entry": [],
            "exit": [],
            "aftermath": [],
        },
        "tags": [],
    }


def new_week_review() -> Dict[str, Any]:
    review_id = current_week_id()
    return {
        "review_id": review_id,
        "status": "draft",
        "week_start": "",
        "week_end": "",
        "stats": {
            "total_trades": 0,
            "clean_trades": 0,
            "forced_trades": 0,
            "wins": 0,
            "losses": 0,
            "break_even": 0,
        },
        "pattern_summary": {
            "best_setup_type": "",
            "worst_recurring_mistake": "",
            "dominant_emotional_leak": "",
            "strongest_behavior": "",
            "main_doctrine_reinforced": "",
        },
        "weekly_lesson": {
            "title": "",
            "summary": "",
            "bottom_line": "",
        },
        "linked_journals": [],
    }

# =========================
# Preview / render helpers
# =========================
def render_chart_preview(chart: Dict[str, Any]) -> str:
    imgs = chart.get("images", {})
    return (
        "Chart Packet Preview 📘\n"
        f"ID: {chart['chart_id']}\n"
        f"Type: {chart.get('type','')}\n"
        f"Instrument: {chart.get('instrument','')}\n"
        f"Trade Status: {chart.get('trade_status','')}\n"
        f"Attached: 4H {'✅' if imgs.get('h4') else '❌'} | 1H {'✅' if imgs.get('h1') else '❌'} | 15M {'✅' if imgs.get('m15') else '❌'}\n"
        f"Note: {chart.get('note','') or '-'}\n"
        f"Ready for analysis: {'Yes' if chart.get('instrument') and imgs.get('h4') and imgs.get('h1') and imgs.get('m15') else 'No'}"
    )


def journal_missing_fields(j: Dict[str, Any]) -> List[str]:
    missing = []
    required_simple = [
        ("type", j.get("type")),
        ("instrument", j.get("instrument")),
        ("direction", j.get("direction")),
        ("session", j.get("session")),
        ("setup_type", j.get("setup_type")),
        ("POI", j["market_context"].get("poi")),
        ("confirmation", j["market_context"].get("confirmation")),
        ("invalidation", j["market_context"].get("invalidation")),
    ]
    for name, value in required_simple:
        if not str(value).strip():
            missing.append(name)
    return missing


def render_journal_preview(j: Dict[str, Any]) -> str:
    missing = journal_missing_fields(j)
    return (
        "Journal Preview 📓\n"
        f"ID: {j['journal_id']}\n"
        f"Type: {j.get('type','')}\n"
        f"Instrument: {j.get('instrument','')}\n"
        f"Direction: {j.get('direction','')}\n"
        f"Session: {j.get('session','')}\n"
        f"Setup: {j.get('setup_type','')}\n"
        f"Daily: {j['timeframes'].get('daily_condition','')}\n"
        f"4H: {j['timeframes'].get('h4_condition','')}\n"
        f"1H: {j['timeframes'].get('h1_condition','')}\n"
        f"15M Trigger: {j['timeframes'].get('m15_trigger','')}\n"
        f"POI: {j['market_context'].get('poi','')}\n"
        f"Liquidity Draw: {j['market_context'].get('liquidity_draw','')}\n"
        f"Confirmation: {j['market_context'].get('confirmation','')}\n"
        f"Invalidation: {j['market_context'].get('invalidation','')}\n"
        f"Target Path: {j['market_context'].get('target_path','')}\n"
        f"Entry: {j['execution'].get('entry_price','')} | Stop: {j['execution'].get('stop_loss','')} | TP: {j['execution'].get('take_profit','')}\n"
        f"Result: {j['result'].get('result_type','')} | PnL: {j['result'].get('pnl','')}\n"
        f"Grade: {j['review'].get('clean_or_forced','')}\n"
        f"Missing Required: {', '.join(missing) if missing else 'None ✅'}"
    )


def render_week_preview(w: Dict[str, Any]) -> str:
    s = w.get("stats", {})
    p = w.get("pattern_summary", {})
    l = w.get("weekly_lesson", {})
    return (
        "Weekly Review Preview 📊\n"
        f"ID: {w['review_id']}\n"
        f"Trades: {s.get('total_trades',0)} | Clean: {s.get('clean_trades',0)} | Forced: {s.get('forced_trades',0)}\n"
        f"Wins: {s.get('wins',0)} | Losses: {s.get('losses',0)} | BE: {s.get('break_even',0)}\n"
        f"Best Setup: {p.get('best_setup_type','')}\n"
        f"Worst Mistake: {p.get('worst_recurring_mistake','')}\n"
        f"Emotional Leak: {p.get('dominant_emotional_leak','')}\n"
        f"Strongest Behavior: {p.get('strongest_behavior','')}\n"
        f"Doctrine Reinforced: {p.get('main_doctrine_reinforced','')}\n"
        f"Weekly Lesson: {l.get('title','')}\n"
        f"Bottom Line: {l.get('bottom_line','')}"
    )

# =========================
# Builders
# =========================
def mode_label(chart_type: str) -> str:
    labels = {
        "live_market_read": "Live Market Read",
        "pre_trade_setup": "Pre-Trade Setup",
        "active_trade_management": "Active Trade Management",
        "tp_hit_review": "TP Hit Review",
        "stop_out_review": "Stop-Out Review",
        "manual_exit_review": "Manual Exit Review",
        "lesson_post": "Lesson Post",
        "setup_invalidated_no_entry": "Setup Invalidated",
        "missed_trade_review": "Missed Trade Review",
    }
    return labels.get(chart_type, chart_type.replace("_", " ").title() or "Chart Read")


def build_internal_read(chart: Dict[str, Any]) -> str:
    instrument = chart.get("instrument", "US30")
    ctype = chart.get("type", "live_market_read")
    note = chart.get("note", "").strip()
    trade_status = chart.get("trade_status", "no_trade")

    if ctype == "pre_trade_setup":
        execution_lens = "Pre-position only. No entry until reaction and confirmation print at the point of interest."
    elif ctype == "active_trade_management":
        execution_lens = "Management stays rule-based. Hold, reduce, or exit only if structure changes."
    elif ctype == "tp_hit_review":
        execution_lens = "Review completed trade quality, not just PnL."
    elif ctype == "stop_out_review":
        execution_lens = "Respect invalidation. A stopped trade can still be process-clean."
    elif ctype == "lesson_post":
        execution_lens = "Extract the operational lesson and keep the doctrine precise."
    else:
        execution_lens = "No trade until location, reaction, confirmation, and invalidation are aligned."

    return (
        f"{instrument} — {mode_label(ctype)} 📘\n\n"
        f"Condition\n"
        f"{instrument} remains in analyst review mode until the 4H, 1H, and 15M packet is interpreted through current structure.\n\n"
        f"Structure\n"
        f"Use 4H for battlefield condition, 1H for confirmation or challenge, and 15M for trigger quality and acceptance.\n\n"
        f"Liquidity\n"
        f"Identify what side has already been used and what side remains the cleaner draw before promoting any thesis.\n\n"
        f"Delivery\n"
        f"Judge whether price is accepting, rejecting, compressing, stalling, or displacing away from the point of interest.\n\n"
        f"Implication\n"
        f"Promote only the path that aligns condition, structure, liquidity, and delivery.\n\n"
        f"Invalidation\n"
        f"The active read fails if price reclaims or loses the structure that should remain defended.\n\n"
        f"Need Next\n"
        f"Need the next decisive reaction, reclaim, failed reclaim, or close to validate the working path.\n\n"
        f"Execution Lens 🎯\n"
        f"{execution_lens}\n\n"
        f"Trade Status\n"
        f"{trade_status.replace('_', ' ').title()}\n"
        + (f"\nOperator Note\n{note}\n" if note else "")
    )


def build_telegram_caption(source: Dict[str, Any], source_type: str = "chart") -> str:
    instrument = source.get("instrument", "US30")
    if source_type == "journal":
        side = source.get("direction", "").upper() or "TRADE"
        setup = source.get("setup_type", "").replace("_", " ").title() or "Structured Review"
        result_type = source.get("result", {}).get("result_type", "").replace("_", " ").title() or "In Progress"
        lesson = source.get("review", {}).get("lesson", "").strip()
        thesis = f"{setup} remains the focus. Process stayed structure-first and confirmation-led."
        warning = lesson or "Respect invalidation and preserve process integrity."
        return f"{instrument} — {result_type} 📘\n{thesis}\n{warning} ✅"

    ctype = source.get("type", "live_market_read")
    mode = mode_label(ctype)
    note = source.get("note", "").strip()
    trade_status = source.get("trade_status", "no_trade")

    if ctype == "pre_trade_setup":
        thesis = "Price is approaching a meaningful location, but confirmation still needs to print."
        process = "The level is not the trade — the reaction is. 🎯"
    elif ctype == "active_trade_management":
        thesis = "Structure remains the decision point for trade management."
        process = "Management stays rule-based, not emotional. ✅"
    elif ctype == "tp_hit_review":
        thesis = "The move delivered from confirmed location into planned liquidity."
        process = "Process stayed cleaner because confirmation came before execution. ✅"
    elif ctype == "stop_out_review":
        thesis = "The trade failed at invalidation, and the stop did its job."
        process = "A stopped trade is acceptable when the process is still clean. ⚠️"
    elif ctype == "manual_exit_review":
        thesis = "The trade was managed out based on structure, not emotion."
        process = "Review the exit against delivery, not against hindsight. 📊"
    elif ctype == "lesson_post":
        thesis = note or "One operational principle can change execution quality materially."
        process = "Translate the lesson into repeatable process. 🧠"
    elif ctype == "setup_invalidated_no_entry":
        thesis = "The level was real, but the setup never confirmed."
        process = "No entry without reaction and confirmation at location. ⚠️"
    elif ctype == "missed_trade_review":
        thesis = "The move developed, but participation did not occur."
        process = "Review whether the miss was disciplined or avoidable. 📊"
    else:
        thesis = "Current structure remains the focus until price proves otherwise."
        process = "Respect location, reaction, and confirmation before promotion. ⚠️"

    if trade_status == "trade_active" and ctype == "live_market_read":
        process = "Trade is active only while structure remains defended. 🎯"

    return f"{instrument} — {mode} 📘\n{thesis}\n{process}"


def build_telegram_breakdown(source: Dict[str, Any], source_type: str = "chart") -> str:
    instrument = source.get("instrument", "US30")
    if source_type == "journal":
        mc = source.get("market_context", {})
        tf = source.get("timeframes", {})
        ex = source.get("execution", {})
        rv = source.get("review", {})
        result_type = source.get("result", {}).get("result_type", "").replace("_", " ").title() or "Trade Review"
        setup = source.get("setup_type", "").replace("_", " ").title() or "Setup"
        lesson = rv.get("lesson", "").strip() or "Process remains the standard over outcome."
        bottom = rv.get("what_i_need_to_improve", "").strip() or "Confirmation beats prediction."
        return (
            f"{instrument} — {result_type} 📘\n\n"
            f"Setup Type\n{setup}\n\n"
            f"Condition\n"
            f"Daily: {tf.get('daily_condition','')}\n"
            f"4H: {tf.get('h4_condition','')}\n"
            f"1H: {tf.get('h1_condition','')}\n\n"
            f"Structure\n{mc.get('poi','')}\n\n"
            f"Liquidity\n{mc.get('liquidity_draw','')}\n\n"
            f"Execution Lens 🎯\n"
            f"Entry {ex.get('entry_price','')} | Stop {ex.get('stop_loss','')} | TP {ex.get('take_profit','')}\n"
            f"Confirmation: {mc.get('confirmation','')}\n\n"
            f"Invalidation ⚠️\n{mc.get('invalidation','')}\n\n"
            f"What Matters Next\n{lesson}\n\n"
            f"Bottom Line ✅\n{bottom}"
        )

    ctype = source.get("type", "live_market_read")
    mode = mode_label(ctype)
    trade_status = source.get("trade_status", "no_trade").replace("_", " ").title()
    note = source.get("note", "").strip()

    if ctype == "pre_trade_setup":
        condition = "Higher-timeframe condition defines the idea, but execution remains inactive until reaction appears at the point of interest."
        structure = "The chart is in approach mode. The point of interest matters, but the level has not earned the trade by itself."
        liquidity = "Focus on whether price is drawing to opposing liquidity first or preparing to reject from the current zone."
        execution = "No entry without reaction + confirmation at location. 🎯"
        invalidation = "The setup is cancelled if price accepts beyond the level that should fail or hold."
        next_step = "Need a visible reaction, then a lower high or higher low, reclaim, or failed reclaim."
        bottom = "The level is not the trade — the reaction is. ✅"
    elif ctype == "active_trade_management":
        condition = "The trade is active, so structure matters more than emotion."
        structure = "The primary question is whether defended structure remains intact or whether delivery is beginning to fail."
        liquidity = "Track whether price is still moving toward planned target liquidity or stalling before it."
        execution = "Manage according to structure: hold, reduce, or exit only if the thesis changes. 🎯"
        invalidation = "If price accepts beyond the trade's structural invalidation, management shifts from hold to exit."
        next_step = "Need the next shelf defense, close, or acceptance test."
        bottom = "Stay with structure, not fear. ✅"
    elif ctype == "tp_hit_review":
        condition = "The move delivered into planned liquidity from confirmed location."
        structure = "Review whether the thesis, trigger, and invalidation were aligned before the move expanded."
        liquidity = "The target path was respected and the draw completed."
        execution = "Review what was done correctly and preserve that behavior. 🎯"
        invalidation = "No retroactive rewriting. The chart must be reviewed through process, not through excitement."
        next_step = note or "Extract the cleanest lesson from the sequence."
        bottom = "Confirmation beat prediction. ✅"
    elif ctype == "stop_out_review":
        condition = "The trade failed at or through invalidation."
        structure = "The key question is whether the setup was clean and simply lost, or whether structure was misread."
        liquidity = "Determine whether the wrong side of liquidity was targeted or whether delivery simply failed."
        execution = "Respect the stop and preserve process integrity. 🎯"
        invalidation = "Do not turn a stop-out into a wider risk event."
        next_step = note or "Extract the actual mistake or reinforcement point."
        bottom = "Respect invalidation and preserve process. ✅"
    elif ctype == "manual_exit_review":
        condition = "The trade was closed manually before hard target or hard invalidation."
        structure = "Review whether the manual exit was justified by delivery or driven by discomfort."
        liquidity = "Assess whether the intended path remained active or whether the draw changed."
        execution = "Manual exits must still be structure-led. 🎯"
        invalidation = "Avoid hindsight grading. Judge the exit on the information available at the time."
        next_step = note or "Define whether the manual exit improved or weakened process."
        bottom = "Management must remain rule-based. ✅"
    elif ctype == "lesson_post":
        condition = note or "One chart can reinforce a doctrine-level lesson."
        structure = "Translate the chart into a principle the operator can repeat."
        liquidity = "Explain how liquidity interacted with the setup or invalidated it."
        execution = "Show what correct execution looks like. 🎯"
        invalidation = "Do not overstate certainty. Keep the lesson precise."
        next_step = "State the operational takeaway in one clean line."
        bottom = "A lesson is only useful if it sharpens future execution. ✅"
    elif ctype == "setup_invalidated_no_entry":
        condition = "The chart reached the area, but confirmation never completed."
        structure = "The setup failed before execution, which is a valid no-trade outcome."
        liquidity = "The level mattered, but the market did not produce the required shift."
        execution = "Standing down was correct because the trade was never earned. 🎯"
        invalidation = "If the market accepts beyond the supposed reaction point, the setup is dead."
        next_step = "Wait for a new location or a new structure to form."
        bottom = "No entry without confirmation at location. ✅"
    elif ctype == "missed_trade_review":
        condition = "The move happened, but participation did not."
        structure = "Review whether the miss was disciplined or whether process broke down."
        liquidity = "Determine whether the chart offered the expected draw clearly enough to act."
        execution = "A missed trade can still produce a valid lesson. 🎯"
        invalidation = "Do not chase after the fact to repair the miss."
        next_step = "Identify whether the miss was acceptable or avoidable."
        bottom = "The lesson matters more than the regret. ✅"
    else:
        condition = "Higher-timeframe condition remains the anchor until execution timeframes prove otherwise."
        structure = "4H defines the battlefield, 1H tests confirmation, and 15M refines trigger quality."
        liquidity = "Mark what side has already been used and what side remains the cleaner draw."
        execution = (
            "No trade until location, reaction, confirmation, and invalidation are aligned. 🎯"
            if trade_status.lower() == "No Trade".lower()
            else "Trade is active only while structure remains defended. 🎯"
        )
        invalidation = "The active read fails if price reclaims or loses the structure that should remain defended."
        next_step = "Need the next reclaim, failed reclaim, close, or shelf reaction before upgrading the thesis."
        bottom = note or "Respect structure first, then timing. ✅"

    return (
        f"{instrument} — {mode} 📘\n\n"
        f"Condition\n{condition}\n\n"
        f"Structure\n{structure}\n\n"
        f"Liquidity\n{liquidity}\n\n"
        f"Execution Lens 🎯\n{execution}\n\n"
        f"Invalidation ⚠️\n{invalidation}\n\n"
        f"What Matters Next\n{next_step}\n\n"
        f"Bottom Line ✅\n{bottom}"
    )


def render_chart_output_preview(chart: Dict[str, Any]) -> str:
    outputs = chart.get("outputs", {})
    return (
        "Chart Output Preview 📲\n\n"
        f"Mode: {outputs.get('mode_label','') or mode_label(chart.get('type','live_market_read'))}\n\n"
        f"--- Internal Analyst Read ---\n{outputs.get('internal_read','') or '-'}\n\n"
        f"--- Telegram Caption ---\n{outputs.get('caption_draft','') or '-'}\n\n"
        f"--- Telegram Breakdown ---\n{outputs.get('breakdown_draft','') or '-'}"
    )


def build_weekly_lesson(week: Dict[str, Any]) -> None:
    s = week["stats"]
    p = week["pattern_summary"]
    clean = s.get("clean_trades", 0)
    forced = s.get("forced_trades", 0)
    if clean >= forced:
        title = "The week improved when structure came first"
        summary = "The cleanest trades came from waiting for reaction and confirmation at location."
        bottom = "Continue prioritizing structure, patience, and proper invalidation over urgency."
    else:
        title = "The week suffered when urgency outran structure"
        summary = "Forced trades and early entries diluted otherwise workable reads."
        bottom = "Reduce anticipation, cut emotional entries, and wait for clearer confirmation."
    if p.get("main_doctrine_reinforced"):
        bottom = p["main_doctrine_reinforced"]
    week["weekly_lesson"] = {"title": title, "summary": summary, "bottom_line": bottom}

# =========================
# Aggregation
# =========================
def collect_current_week_journals() -> List[Dict[str, Any]]:
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    entries = []
    for file in JOURNAL_DIR.glob("journal_*.json"):
        data = load_json(file)
        created = data.get("created_at", "")
        try:
            dt = datetime.fromisoformat(created)
            y, w, _ = dt.date().isocalendar()
            if y == iso_year and w == iso_week:
                # Include only actual trades and closed trade review types
                if data.get("type") in {"active_trade", "tp_hit_review", "stop_out_review", "manual_exit_review"} or data.get("result", {}).get("result_type") in {"tp_hit", "stop_out", "manual_exit_win", "manual_exit_loss", "break_even"}:
                    entries.append(data)
        except Exception:
            continue
    return sorted(entries, key=lambda x: x.get("created_at", ""))


def grade_week(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    stats = {
        "total_trades": len(entries),
        "clean_trades": 0,
        "forced_trades": 0,
        "wins": 0,
        "losses": 0,
        "break_even": 0,
    }
    setup_counter = Counter()
    mistake_counter = Counter()
    leak_counter = Counter()
    behavior_counter = Counter()

    for e in entries:
        review = e.get("review", {})
        result = e.get("result", {})
        clean = review.get("clean_or_forced", "").strip().lower()
        if clean == "clean":
            stats["clean_trades"] += 1
        elif clean == "forced":
            stats["forced_trades"] += 1

        rt = result.get("result_type", "")
        if rt in {"tp_hit", "manual_exit_win"}:
            stats["wins"] += 1
        elif rt in {"stop_out", "manual_exit_loss"}:
            stats["losses"] += 1
        elif rt == "break_even":
            stats["break_even"] += 1

        if e.get("setup_type"):
            setup_counter[e["setup_type"]] += 1
        if review.get("biggest_mistake"):
            mistake_counter[review["biggest_mistake"]] += 1
        if review.get("emotional_leak"):
            leak_counter[review["emotional_leak"]] += 1
        if review.get("what_was_done_well"):
            behavior_counter[review["what_was_done_well"]] += 1

    pattern_summary = {
        "best_setup_type": setup_counter.most_common(1)[0][0] if setup_counter else "",
        "worst_recurring_mistake": mistake_counter.most_common(1)[0][0] if mistake_counter else "",
        "dominant_emotional_leak": leak_counter.most_common(1)[0][0] if leak_counter else "",
        "strongest_behavior": behavior_counter.most_common(1)[0][0] if behavior_counter else "",
        "main_doctrine_reinforced": "confirmation beats prediction",
    }
    return {"stats": stats, "pattern_summary": pattern_summary}

# =========================
# Command handlers
# =========================
def get_chat_id(message: Dict[str, Any]) -> str:
    return str(message["chat"]["id"])


def get_text(message: Dict[str, Any]) -> str:
    return message.get("text") or message.get("caption") or ""


def current_chart(chat_id: str) -> Dict[str, Any]:
    return ACTIVE_CHARTS.setdefault(chat_id, new_chart_packet())


def current_journal(chat_id: str) -> Dict[str, Any]:
    return ACTIVE_JOURNALS.setdefault(chat_id, new_journal_draft())


def current_week(chat_id: str) -> Dict[str, Any]:
    return ACTIVE_WEEKS.setdefault(chat_id, new_week_review())


def set_pending_text(chat_id: str, target: str) -> None:
    PENDING_TEXT_INPUTS[chat_id] = {"target": target}


def clear_pending_text(chat_id: str) -> None:
    PENDING_TEXT_INPUTS.pop(chat_id, None)


def handle_photo(message: Dict[str, Any]) -> None:
    chat_id = get_chat_id(message)
    pending = PENDING_UPLOADS.get(chat_id)
    if not pending:
        send_message(chat_id, "No pending upload slot ⚠️\nUse /chart_4h, /chart_1h, /chart_15m, or /journal_image [category] first.")
        return
    photos = message.get("photo", [])
    if not photos:
        send_message(chat_id, "No photo detected ⚠️")
        return
    file_id = photos[-1]["file_id"]
    target = pending["target"]
    slot = pending["slot"]

    if target == "chart":
        chart = current_chart(chat_id)
        chart["images"][slot].append(file_id)
        ACTIVE_CHARTS[chat_id] = chart
        send_message(chat_id, f"{slot.upper()} chart attached ✅")
    elif target == "journal":
        journal = current_journal(chat_id)
        journal["images"][slot].append(file_id)
        ACTIVE_JOURNALS[chat_id] = journal
        send_message(chat_id, f"Image attached to `{slot}` ✅")
    PENDING_UPLOADS.pop(chat_id, None)


def cmd_chart_new(chat_id: str) -> None:
    ACTIVE_CHARTS[chat_id] = new_chart_packet()
    send_message(chat_id, "Chart packet opened ✅\nSend the required screenshots:\n- 4H\n- 1H\n- 15M\nOptional: note or trade status.")


def cmd_chart_type(chat_id: str, arg: str) -> None:
    chart = current_chart(chat_id)
    chart["type"] = arg.strip()
    send_message(chat_id, f"Chart mode set: `{arg.strip()}` ✅")


def cmd_chart_instrument(chat_id: str, arg: str) -> None:
    chart = current_chart(chat_id)
    symbol = arg.strip().upper()
    chart["instrument"] = symbol
    send_message(chat_id, f"Instrument set: `{symbol}` ✅")


def cmd_chart_status(chat_id: str, arg: str) -> None:
    chart = current_chart(chat_id)
    chart["trade_status"] = arg.strip()
    send_message(chat_id, f"Trade status set: `{arg.strip()}` ✅")


def cmd_chart_note(chat_id: str, arg: str) -> None:
    chart = current_chart(chat_id)
    chart["note"] = arg.strip()
    send_message(chat_id, "Chart note saved ✅")


def cmd_chart_slot(chat_id: str, slot: str) -> None:
    PENDING_UPLOADS[chat_id] = {"target": "chart", "slot": slot}
    send_message(chat_id, f"Send the {slot.upper()} screenshot now 📎")


def cmd_chart_preview(chat_id: str) -> None:
    send_message(chat_id, render_chart_preview(current_chart(chat_id)))


def cmd_chart_analyze(chat_id: str) -> None:
    chart = current_chart(chat_id)
    if not chart.get("instrument") or not chart["images"].get("h4") or not chart["images"].get("h1") or not chart["images"].get("m15"):
        send_message(chat_id, "Analysis blocked ⚠️\nMissing instrument or required chart packet (4H + 1H + 15M).")
        return
    chart["status"] = "staged"
    internal = build_internal_read(chart)
    caption = build_telegram_caption(chart, source_type="chart")
    breakdown = build_telegram_breakdown(chart, source_type="chart")
    chart["outputs"]["internal_read"] = internal
    chart["outputs"]["caption_draft"] = caption
    chart["outputs"]["breakdown_draft"] = breakdown
    chart["outputs"]["mode_label"] = mode_label(chart.get("type", "live_market_read"))
    chart["outputs"]["last_generated_at"] = now_iso()
    chart["analysis"]["internal_read"] = internal
    chart["analysis"]["telegram_caption"] = caption
    chart["analysis"]["telegram_breakdown"] = breakdown
    save_json(chart_path(chart["chart_id"]), chart)
    send_message(chat_id, "Analysis staged ✅\nUse /chart_output_preview, /chart_caption_preview, or /chart_breakdown_preview.")

def cmd_chart_caption_preview(chat_id: str) -> None:
    chart = current_chart(chat_id)
    caption = chart.get("outputs", {}).get("caption_draft") or chart.get("analysis", {}).get("telegram_caption", "")
    if not caption:
        send_message(chat_id, "Caption preview blocked ⚠️\nRun /chart_analyze first.")
        return
    send_message(chat_id, caption)

def cmd_chart_breakdown_preview(chat_id: str) -> None:
    chart = current_chart(chat_id)
    breakdown = chart.get("outputs", {}).get("breakdown_draft") or chart.get("analysis", {}).get("telegram_breakdown", "")
    if not breakdown:
        send_message(chat_id, "Breakdown preview blocked ⚠️\nRun /chart_analyze first.")
        return
    send_message(chat_id, breakdown)

def cmd_chart_output_preview(chat_id: str) -> None:
    chart = current_chart(chat_id)
    if not chart.get("outputs", {}).get("internal_read"):
        send_message(chat_id, "Output preview blocked ⚠️\nRun /chart_analyze first.")
        return
    send_message(chat_id, render_chart_output_preview(chart))

def cmd_chart_regenerate_caption(chat_id: str) -> None:
    chart = current_chart(chat_id)
    if not chart.get("instrument"):
        send_message(chat_id, "Regeneration blocked ⚠️\nSet chart instrument first.")
        return
    caption = build_telegram_caption(chart, source_type="chart")
    chart["outputs"]["caption_draft"] = caption
    chart["analysis"]["telegram_caption"] = caption
    save_json(chart_path(chart["chart_id"]), chart)
    send_message(chat_id, f"Caption regenerated ✅\n\n{caption}")

def cmd_chart_regenerate_breakdown(chat_id: str) -> None:
    chart = current_chart(chat_id)
    if not chart.get("instrument"):
        send_message(chat_id, "Regeneration blocked ⚠️\nSet chart instrument first.")
        return
    breakdown = build_telegram_breakdown(chart, source_type="chart")
    chart["outputs"]["breakdown_draft"] = breakdown
    chart["analysis"]["telegram_breakdown"] = breakdown
    save_json(chart_path(chart["chart_id"]), chart)
    send_message(chat_id, f"Breakdown regenerated ✅\n\n{breakdown}")

def cmd_chart_to_journal(chat_id: str) -> None:
    chart = current_chart(chat_id)
    if chart.get("trade_status") not in {"trade_active", "trade_closed"}:
        send_message(chat_id, "Blocked ⚠️\nJournal flow only activates when a real trade was taken or closed.")
        return
    journal = new_journal_draft()
    journal["instrument"] = chart.get("instrument", "US30")
    for src, dst in [("h4", "h4"), ("h1", "h1"), ("m15", "m15")]:
        journal["images"][dst] = list(chart["images"].get(src, []))
    ACTIVE_JOURNALS[chat_id] = journal
    send_message(chat_id, "Chart packet promoted to journal draft ✅\nContinue with /journal_type, /journal_context, and /journal_entry.")


def cmd_chart_cancel(chat_id: str) -> None:
    ACTIVE_CHARTS.pop(chat_id, None)
    send_message(chat_id, "Chart packet cancelled 🗑️")


def cmd_journal_new(chat_id: str) -> None:
    ACTIVE_JOURNALS[chat_id] = new_journal_draft()
    send_message(chat_id, "Journal draft opened ✅\nSet the type next with /journal_type")


def cmd_journal_type(chat_id: str, arg: str) -> None:
    journal = current_journal(chat_id)
    journal["type"] = arg.strip()
    send_message(chat_id, f"Journal type set: `{arg.strip()}` ✅")


def cmd_journal_context(chat_id: str, block: str) -> None:
    if not block.strip():
        set_pending_text(chat_id, "journal_context")
        send_message(chat_id, "Paste the journal context block now 🧾")
        return
    data = parse_kv_block(block)
    j = current_journal(chat_id)
    j["instrument"] = data.get("instrument", j["instrument"])
    j["direction"] = data.get("direction", j["direction"])
    j["session"] = data.get("session", j["session"])
    j["setup_type"] = data.get("setup_type", j["setup_type"])
    j["timeframes"]["daily_condition"] = data.get("daily_condition", j["timeframes"]["daily_condition"])
    j["timeframes"]["h4_condition"] = data.get("h4_condition", j["timeframes"]["h4_condition"])
    j["timeframes"]["h1_condition"] = data.get("h1_condition", j["timeframes"]["h1_condition"])
    j["timeframes"]["m15_trigger"] = data.get("m15_trigger", j["timeframes"]["m15_trigger"])
    j["market_context"]["poi"] = data.get("poi", j["market_context"]["poi"])
    j["market_context"]["liquidity_draw"] = data.get("liquidity_draw", j["market_context"]["liquidity_draw"])
    j["market_context"]["confirmation"] = data.get("confirmation", j["market_context"]["confirmation"])
    j["market_context"]["invalidation"] = data.get("invalidation", j["market_context"]["invalidation"])
    j["market_context"]["target_path"] = data.get("target_path", j["market_context"]["target_path"])
    clear_pending_text(chat_id)
    send_message(chat_id, "Journal context saved ✅")

def cmd_journal_entry(chat_id: str, block: str) -> None:
    if not block.strip():
        set_pending_text(chat_id, "journal_entry")
        send_message(chat_id, "Paste the execution block now 🎯")
        return
    data = parse_kv_block(block)
    j = current_journal(chat_id)
    ex = j["execution"]
    ex["entry_price"] = data.get("entry_price", ex["entry_price"])
    ex["stop_loss"] = data.get("stop_loss", ex["stop_loss"])
    ex["take_profit"] = data.get("take_profit", ex["take_profit"])
    ex["lot_size"] = data.get("lot_size", ex["lot_size"])
    ex["risk_note"] = data.get("risk_note", ex["risk_note"])
    ex["timing_note"] = data.get("timing_note", ex["timing_note"])
    clear_pending_text(chat_id)
    send_message(chat_id, "Execution details saved ✅")

def cmd_journal_result(chat_id: str, block: str) -> None:
    if not block.strip():
        set_pending_text(chat_id, "journal_result")
        send_message(chat_id, "Paste the result block now 🏁")
        return
    data = parse_kv_block(block)
    j = current_journal(chat_id)
    r = j["result"]
    r["result_type"] = data.get("result_type", r["result_type"])
    r["pnl"] = data.get("pnl", r["pnl"])
    r["rr_if_known"] = data.get("rr_if_known", r["rr_if_known"])
    r["outcome_summary"] = data.get("outcome_summary", r["outcome_summary"])
    clear_pending_text(chat_id)
    send_message(chat_id, "Journal result saved ✅")

def cmd_journal_lesson(chat_id: str, block: str) -> None:
    if not block.strip():
        set_pending_text(chat_id, "journal_lesson")
        send_message(chat_id, "Paste the lesson/review block now 🧠")
        return
    data = parse_kv_block(block)
    j = current_journal(chat_id)
    rv = j["review"]
    rv["clean_or_forced"] = data.get("clean_or_forced", rv["clean_or_forced"])
    rv["what_was_done_well"] = data.get("what_was_done_well", rv["what_was_done_well"])
    rv["biggest_mistake"] = data.get("biggest_mistake", rv["biggest_mistake"])
    rv["emotional_leak"] = data.get("emotional_leak", rv["emotional_leak"])
    rv["lesson"] = data.get("lesson", rv["lesson"])
    rv["what_i_need_to_improve"] = data.get("what_i_need_to_improve", rv["what_i_need_to_improve"])
    clear_pending_text(chat_id)
    send_message(chat_id, "Lesson and review block saved ✅")

def cmd_journal_image(chat_id: str, arg: str) -> None:
    slot = arg.strip().lower()
    if slot not in {"daily", "h4", "h1", "m15", "entry", "exit", "aftermath"}:
        send_message(chat_id, "Invalid journal image slot ⚠️")
        return
    PENDING_UPLOADS[chat_id] = {"target": "journal", "slot": slot}
    send_message(chat_id, f"Send the screenshot for `{slot}` now 📎")


def cmd_journal_preview(chat_id: str) -> None:
    send_message(chat_id, render_journal_preview(current_journal(chat_id)))


def cmd_journal_save(chat_id: str) -> None:
    j = current_journal(chat_id)
    missing = journal_missing_fields(j)
    if missing:
        send_message(chat_id, f"Save blocked ⚠️\nMissing fields: {', '.join(missing)}")
        return
    j["status"] = "saved"
    save_json(journal_path(j["journal_id"]), j)
    send_message(chat_id, f"Journal saved ✅\nID: `{j['journal_id']}`")


def cmd_journal_archive(chat_id: str) -> None:
    if not PRIVATE_ARCHIVE_CHAT_ID:
        send_message(chat_id, "Archive blocked ⚠️\nMissing PRIVATE_ARCHIVE_CHAT_ID env var.")
        return
    j = current_journal(chat_id)
    if j.get("status") != "saved":
        send_message(chat_id, "Archive blocked ⚠️\nSave the journal first.")
        return
    summary = render_journal_preview(j)
    resp = send_message(PRIVATE_ARCHIVE_CHAT_ID, summary)
    idx = get_archive_index()
    idx.setdefault("journal_archives", {})[j["journal_id"]] = {
        "chat_id": PRIVATE_ARCHIVE_CHAT_ID,
        "message_id": resp.get("result", {}).get("message_id"),
        "archived_at": now_iso(),
    }
    save_archive_index(idx)
    j["status"] = "archived"
    save_json(journal_path(j["journal_id"]), j)
    send_message(chat_id, "Journal archived privately ✅")


def cmd_journal_queue_pdf(chat_id: str) -> None:
    j = current_journal(chat_id)
    if j.get("status") not in {"saved", "archived", "converted_to_post"}:
        send_message(chat_id, "PDF queue blocked ⚠️\nSave the journal first.")
        return
    obj = {
        "pdfq_id": generate_pdfq_id(),
        "status": "queued",
        "source_type": "journal",
        "source_id": j["journal_id"],
        "pdf_type": "trade_breakdown",
        "created_at": now_iso(),
    }
    save_json(pdfq_path(obj["pdfq_id"]), obj)
    j["status"] = "queued_for_pdf"
    save_json(journal_path(j["journal_id"]), j)
    send_message(chat_id, "Journal added to PDF queue ✅")


def cmd_journal_to_post(chat_id: str) -> None:
    j = current_journal(chat_id)
    if j.get("status") not in {"saved", "archived", "queued_for_pdf"}:
        send_message(chat_id, "Post conversion blocked ⚠️\nSave the journal first.")
        return
    j["status"] = "converted_to_post"
    save_json(journal_path(j["journal_id"]), j)
    caption = build_telegram_caption(j, source_type="journal")
    breakdown = build_telegram_breakdown(j, source_type="journal")
    send_message(chat_id, f"Journal converted to post-ready format ✅\n\n--- Caption ---\n{caption}\n\n--- Breakdown ---\n{breakdown}")


def cmd_journal_cancel(chat_id: str) -> None:
    ACTIVE_JOURNALS.pop(chat_id, None)
    send_message(chat_id, "Journal draft cancelled 🗑️")


def cmd_week_open(chat_id: str) -> None:
    ACTIVE_WEEKS[chat_id] = new_week_review()
    send_message(chat_id, "Weekly review opened ✅")


def cmd_week_collect(chat_id: str) -> None:
    week = current_week(chat_id)
    entries = collect_current_week_journals()
    if not entries:
        send_message(chat_id, "No eligible trades found for this week ⚠️\nWeekly review only activates when a real trade was taken and saved.")
        return
    week["linked_journals"] = [e["journal_id"] for e in entries]
    first = datetime.fromisoformat(entries[0]["created_at"]).date().isoformat()
    last = datetime.fromisoformat(entries[-1]["created_at"]).date().isoformat()
    week["week_start"] = first
    week["week_end"] = last
    send_message(chat_id, f"Weekly journals collected ✅\nEntries found: {len(entries)}")


def cmd_week_grade(chat_id: str) -> None:
    week = current_week(chat_id)
    if not week.get("linked_journals"):
        send_message(chat_id, "Weekly grading blocked ⚠️\nRun /week_collect first.")
        return
    entries = [load_json(journal_path(jid)) for jid in week["linked_journals"] if journal_path(jid).exists()]
    graded = grade_week(entries)
    week["stats"] = graded["stats"]
    week["pattern_summary"] = graded["pattern_summary"]
    send_message(chat_id, "Weekly grading complete ✅")


def cmd_week_lesson(chat_id: str) -> None:
    week = current_week(chat_id)
    if not week.get("linked_journals"):
        send_message(chat_id, "Weekly lesson blocked ⚠️\nRun /week_collect first.")
        return
    build_weekly_lesson(week)
    send_message(chat_id, "Weekly lesson generated ✅")


def cmd_week_preview(chat_id: str) -> None:
    send_message(chat_id, render_week_preview(current_week(chat_id)))


def cmd_week_save(chat_id: str) -> None:
    week = current_week(chat_id)
    if not week.get("linked_journals"):
        send_message(chat_id, "Save blocked ⚠️\nNo weekly data collected.")
        return
    week["status"] = "saved"
    save_json(week_path(week["review_id"]), week)
    send_message(chat_id, f"Weekly review saved ✅\nID: `{week['review_id']}`")


def cmd_week_post(chat_id: str) -> None:
    week = current_week(chat_id)
    if week.get("status") != "saved":
        send_message(chat_id, "Post blocked ⚠️\nSave the weekly review first.")
        return
    s = week.get("stats", {})
    l = week.get("weekly_lesson", {})
    post = (
        f"📊 Weekly Review — US30 Mastery\n\n"
        f"Total trades: {s.get('total_trades',0)}\n"
        f"Clean trades: {s.get('clean_trades',0)}\n"
        f"Forced trades: {s.get('forced_trades',0)}\n"
        f"Wins: {s.get('wins',0)} | Losses: {s.get('losses',0)} | BE: {s.get('break_even',0)}\n\n"
        f"Lesson:\n{l.get('title','')}\n{l.get('summary','')}\n\n"
        f"📌 Bottom line:\n{l.get('bottom_line','')}"
    )
    send_message(chat_id, f"Weekly recap post staged ✅\n\n{post}")


def cmd_week_queue_pdf(chat_id: str) -> None:
    week = current_week(chat_id)
    if week.get("status") != "saved":
        send_message(chat_id, "PDF queue blocked ⚠️\nSave the weekly review first.")
        return
    obj = {
        "pdfq_id": generate_pdfq_id(),
        "status": "queued",
        "source_type": "weekly_review",
        "source_id": week["review_id"],
        "pdf_type": "weekly_recap",
        "created_at": now_iso(),
    }
    save_json(pdfq_path(obj["pdfq_id"]), obj)
    week["status"] = "queued_for_pdf"
    save_json(week_path(week["review_id"]), week)
    send_message(chat_id, "Weekly review added to PDF queue ✅")


def cmd_week_cancel(chat_id: str) -> None:
    ACTIVE_WEEKS.pop(chat_id, None)
    send_message(chat_id, "Weekly review cancelled 🗑️")


def cmd_status_all(chat_id: str) -> None:
    chart = ACTIVE_CHARTS.get(chat_id)
    journal = ACTIVE_JOURNALS.get(chat_id)
    week = ACTIVE_WEEKS.get(chat_id)
    send_message(
        chat_id,
        "System Status 🧾\n"
        f"Active chart: {chart['chart_id'] if chart else 'None'}\n"
        f"Active journal: {journal['journal_id'] if journal else 'None'}\n"
        f"Active week: {week['review_id'] if week else 'None'}\n"
        f"Queued PDFs: {len(list(PDFQ_DIR.glob('*.json')))}"
    )


def cmd_status_chart(chat_id: str) -> None:
    chart = ACTIVE_CHARTS.get(chat_id)
    send_message(chat_id, render_chart_preview(chart) if chart else "No active chart packet.")


def cmd_status_journal(chat_id: str) -> None:
    journal = ACTIVE_JOURNALS.get(chat_id)
    send_message(chat_id, render_journal_preview(journal) if journal else "No active journal draft.")


def cmd_status_week(chat_id: str) -> None:
    week = ACTIVE_WEEKS.get(chat_id)
    send_message(chat_id, render_week_preview(week) if week else "No active weekly review.")


def cmd_clear_stale(chat_id: str) -> None:
    ACTIVE_CHARTS.pop(chat_id, None)
    ACTIVE_JOURNALS.pop(chat_id, None)
    ACTIVE_WEEKS.pop(chat_id, None)
    PENDING_UPLOADS.pop(chat_id, None)
    PENDING_TEXT_INPUTS.pop(chat_id, None)
    send_message(chat_id, "Active drafts cleared ✅")


def cmd_help_journal(chat_id: str) -> None:
    send_message(chat_id, "/journal_new\n/journal_type [type]\n/journal_context [kv block]\n/journal_entry [kv block]\n/journal_result [kv block]\n/journal_lesson [kv block]\n/journal_image [daily|h4|h1|m15|entry|exit|aftermath]\n/journal_preview\n/journal_save\n/journal_archive\n/journal_queue_pdf\n/journal_to_post\n/journal_cancel")


def cmd_help_week(chat_id: str) -> None:
    send_message(chat_id, "/week_open\n/week_collect\n/week_grade\n/week_lesson\n/week_preview\n/week_save\n/week_post\n/week_queue_pdf\n/week_cancel")


def cmd_push_chart(chat_id: str) -> None:
    if not PUBLIC_CHANNEL_CHAT_ID:
        send_message(chat_id, "Push blocked ⚠️\nMissing PUBLIC_CHANNEL_CHAT_ID env var.")
        return
    chart = current_chart(chat_id)
    caption = chart.get("outputs", {}).get("caption_draft") or chart["analysis"].get("telegram_caption")
    if not caption:
        send_message(chat_id, "Push blocked ⚠️\nRun /chart_analyze first.")
        return
    file_id = chart["images"].get("h4", [None])[-1]
    if not file_id:
        send_message(chat_id, "Push blocked ⚠️\nNo 4H image attached.")
        return
    send_photo(PUBLIC_CHANNEL_CHAT_ID, file_id, caption)
    send_message(chat_id, "Chart image pushed publicly ✅")


def cmd_push_chartbreakdown(chat_id: str) -> None:
    if not PUBLIC_CHANNEL_CHAT_ID:
        send_message(chat_id, "Push blocked ⚠️\nMissing PUBLIC_CHANNEL_CHAT_ID env var.")
        return
    chart = current_chart(chat_id)
    breakdown = chart.get("outputs", {}).get("breakdown_draft") or chart["analysis"].get("telegram_breakdown")
    if not breakdown:
        send_message(chat_id, "Push blocked ⚠️\nRun /chart_analyze first.")
        return
    send_message(PUBLIC_CHANNEL_CHAT_ID, breakdown)
    send_message(chat_id, "Chart breakdown pushed publicly ✅")

# =========================
# Dispatcher
# =========================
def handle_command(message: Dict[str, Any]) -> None:
    chat_id = get_chat_id(message)
    text = get_text(message).strip()

    if not text.startswith("/"):
        pending = PENDING_TEXT_INPUTS.get(chat_id)
        if pending:
            target = pending.get("target", "")
            if target == "journal_context":
                return cmd_journal_context(chat_id, text)
            if target == "journal_entry":
                return cmd_journal_entry(chat_id, text)
            if target == "journal_result":
                return cmd_journal_result(chat_id, text)
            if target == "journal_lesson":
                return cmd_journal_lesson(chat_id, text)

        send_message(chat_id, "Text received, but no active command handler matched. Use /status_all for current state.")
        return

    parts = text.split(maxsplit=1)
    if len(parts) == 2:
        cmd, arg = parts[0], parts[1]
    else:
        cmd, arg = text, ""

    cmd = cmd.lower()

    # Chart family
    if cmd == "/chart_new": return cmd_chart_new(chat_id)
    if cmd == "/chart_type": return cmd_chart_type(chat_id, arg)
    if cmd == "/chart_instrument": return cmd_chart_instrument(chat_id, arg)
    if cmd == "/chart_status": return cmd_chart_status(chat_id, arg)
    if cmd == "/chart_note": return cmd_chart_note(chat_id, arg)
    if cmd == "/chart_4h": return cmd_chart_slot(chat_id, "h4")
    if cmd == "/chart_1h": return cmd_chart_slot(chat_id, "h1")
    if cmd == "/chart_15m": return cmd_chart_slot(chat_id, "m15")
    if cmd == "/chart_preview": return cmd_chart_preview(chat_id)
    if cmd == "/chart_analyze": return cmd_chart_analyze(chat_id)
    if cmd == "/chart_caption_preview": return cmd_chart_caption_preview(chat_id)
    if cmd == "/chart_breakdown_preview": return cmd_chart_breakdown_preview(chat_id)
    if cmd == "/chart_output_preview": return cmd_chart_output_preview(chat_id)
    if cmd == "/chart_regenerate_caption": return cmd_chart_regenerate_caption(chat_id)
    if cmd == "/chart_regenerate_breakdown": return cmd_chart_regenerate_breakdown(chat_id)
    if cmd == "/chart_to_journal": return cmd_chart_to_journal(chat_id)
    if cmd == "/chart_cancel": return cmd_chart_cancel(chat_id)
    if cmd == "/push_chart": return cmd_push_chart(chat_id)
    if cmd == "/push_chartbreakdown": return cmd_push_chartbreakdown(chat_id)

    # Journal family
    if cmd == "/journal_new": return cmd_journal_new(chat_id)
    if cmd == "/journal_type": return cmd_journal_type(chat_id, arg)
    if cmd == "/journal_context": return cmd_journal_context(chat_id, arg)
    if cmd == "/journal_entry": return cmd_journal_entry(chat_id, arg)
    if cmd == "/journal_result": return cmd_journal_result(chat_id, arg)
    if cmd == "/journal_lesson": return cmd_journal_lesson(chat_id, arg)
    if cmd == "/journal_image": return cmd_journal_image(chat_id, arg)
    if cmd == "/journal_preview": return cmd_journal_preview(chat_id)
    if cmd == "/journal_save": return cmd_journal_save(chat_id)
    if cmd == "/journal_archive": return cmd_journal_archive(chat_id)
    if cmd == "/journal_queue_pdf": return cmd_journal_queue_pdf(chat_id)
    if cmd == "/journal_to_post": return cmd_journal_to_post(chat_id)
    if cmd == "/journal_cancel": return cmd_journal_cancel(chat_id)

    # Weekly family
    if cmd == "/week_open": return cmd_week_open(chat_id)
    if cmd == "/week_collect": return cmd_week_collect(chat_id)
    if cmd == "/week_grade": return cmd_week_grade(chat_id)
    if cmd == "/week_lesson": return cmd_week_lesson(chat_id)
    if cmd == "/week_preview": return cmd_week_preview(chat_id)
    if cmd == "/week_save": return cmd_week_save(chat_id)
    if cmd == "/week_post": return cmd_week_post(chat_id)
    if cmd == "/week_queue_pdf": return cmd_week_queue_pdf(chat_id)
    if cmd == "/week_cancel": return cmd_week_cancel(chat_id)

    # Admin
    if cmd == "/status_all": return cmd_status_all(chat_id)
    if cmd == "/status_chart": return cmd_status_chart(chat_id)
    if cmd == "/status_journal": return cmd_status_journal(chat_id)
    if cmd == "/status_week": return cmd_status_week(chat_id)
    if cmd == "/clear_stale": return cmd_clear_stale(chat_id)
    if cmd == "/help_journal": return cmd_help_journal(chat_id)
    if cmd == "/help_week": return cmd_help_week(chat_id)

    send_message(chat_id, f"Unknown command ⚠️\n`{cmd}`")

# =========================
# Flask routes# =========================
# Flask routes
# =========================
@app.get("/")
def root() -> Any:
    return jsonify({"ok": True, "service": "US30 Mastery Bot", "timezone": TIMEZONE_NAME})


@app.get("/health")
def health() -> Any:
    return jsonify({"ok": True})


@app.route("/set_webhook", methods=["GET", "POST"])
def http_set_webhook() -> Any:
    try:
        resp = set_webhook()
        return jsonify({"ok": True, "telegram": resp})
    except Exception as e:
        logger.exception("set_webhook failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/webhook")
def webhook() -> Any:
    if WEBHOOK_SECRET:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got != WEBHOOK_SECRET:
            return jsonify({"ok": False, "error": "invalid secret"}), 403

    update = request.get_json(force=True, silent=True) or {}
    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify({"ok": True, "ignored": True})

    try:
        if message.get("photo"):
            handle_photo(message)
        else:
            handle_command(message)
    except Exception as e:
        logger.exception("update handling failed")
        try:
            chat_id = get_chat_id(message)
            send_message(chat_id, f"System error ⚠️\n{type(e).__name__}: {e}")
        except Exception:
            pass
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    if WEBHOOK_URL:
        try:
            set_webhook()
        except Exception:
            logger.exception("Automatic webhook setup failed")
    app.run(host="0.0.0.0", port=port)
