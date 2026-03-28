import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_CHAT_ID = int(os.environ.get("OWNER_CHAT_ID", "0"))
CHANNEL_CHAT_ID = os.environ["CHANNEL_CHAT_ID"]
WEBHOOK_SECRET_PATH = os.environ["WEBHOOK_SECRET_PATH"]
BRAND_NAME = os.environ.get("BRAND_NAME", "Random Parlay Guy")
LOADBOARD_TEMPLATE = os.environ.get(
    "LOADBOARD_TEMPLATE",
    "🎯 Tonight’s board is loading.\n\n📌 Today’s Selections will be posted first.\n🎟️ Full ticket reveals will follow after that.\n\n🔒 Stay locked.\n\n⚠️ Disclaimer: Plays are for informational and entertainment purposes only. No result is guaranteed. Bet responsibly and only risk what you can afford to lose.\n\n🔁 If any leg is too juiced for your liking, you can swap it for a lesser prop replacement that still fits the same player role and ticket job.",
)
FULLCARD_TEMPLATE = os.environ.get(
    "FULLCARD_TEMPLATE",
    "✅ Full card is live.\n\n📌 Today’s Selections are posted.\n🎟️ All ticket reveals for tonight have been sent.\n\n🔄 Anything else posted after this is a true adjustment only.\n\n🔁 If any leg is too juiced for your liking, you can swap it for a lesser prop replacement that still fits the same player role and ticket job.\n\n⚠️ Disclaimer: Plays are for informational and entertainment purposes only. No result is guaranteed. Bet responsibly and only risk what you can afford to lose.",
)
DISCLAIMER_TEMPLATE = os.environ.get(
    "DISCLAIMER_TEMPLATE",
    "⚠️ Disclaimer: Plays are for informational and entertainment purposes only. No result is guaranteed. Bet responsibly and only risk what you can afford to lose.",
)
REPLACEMENT_TEMPLATE = os.environ.get(
    "REPLACEMENT_TEMPLATE",
    "🔁 If any leg is too juiced for your liking, you can swap it for a lesser prop replacement that still fits the same player role and ticket job.",
)

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

MAIN_SECTION_ORDER = [
    "Best Clickable Core Read",
    "Straight Bets Board",
    "Road to $25",
    "Road to $50",
    "Road to $75",
    "Road to $100",
    "Profit Boost Ticket",
    "No Sweat Ticket",
    "+MoneyBet Ticket",
    "Exploitable Edges Ticket",
    "Magician Ticket",
    "SGP Ticket",
    "Daily Ticket",
    "Box Score Ticket",
    "Lottery Ticket",
    "Money Line Ticket",
]

SECTION_COMMAND_MAP = {
    "/today": "Best Clickable Core Read",
    "/straight": "Straight Bets Board",
    "/road25": "Road to $25",
    "/road50": "Road to $50",
    "/road75": "Road to $75",
    "/road100": "Road to $100",
    "/profitboost": "Profit Boost Ticket",
    "/nosweat": "No Sweat Ticket",
    "/plusmoney": "+MoneyBet Ticket",
    "/edges": "Exploitable Edges Ticket",
    "/magician": "Magician Ticket",
    "/sgp": "SGP Ticket",
    "/daily": "Daily Ticket",
    "/boxscore": "Box Score Ticket",
    "/lottery": "Lottery Ticket",
    "/moneyline": "Money Line Ticket",
}

PUSH_COMMAND_MAP = {
    "/push_today": "Best Clickable Core Read",
    "/push_straight": "Straight Bets Board",
    "/push_road25": "Road to $25",
    "/push_road50": "Road to $50",
    "/push_road75": "Road to $75",
    "/push_road100": "Road to $100",
    "/push_profitboost": "Profit Boost Ticket",
    "/push_nosweat": "No Sweat Ticket",
    "/push_plusmoney": "+MoneyBet Ticket",
    "/push_edges": "Exploitable Edges Ticket",
    "/push_magician": "Magician Ticket",
    "/push_sgp": "SGP Ticket",
    "/push_daily": "Daily Ticket",
    "/push_boxscore": "Box Score Ticket",
    "/push_lottery": "Lottery Ticket",
    "/push_moneyline": "Money Line Ticket",
}

HELP_TEXT = """Available commands:\n\nCore\n/start\n/help\n/status\n/whoami\n/clearstage\n/preview\n/approve\n/reject\n/push\n\nStaging\n/stage_text\n/stage_image\n/stage_pdf\n\nBroadcast templates\n/loadboard\n/fullcard\n/adjustment\n/halftime\n/recap\n/disclaimer\n/replacementnote\n\nBoard intake\n/post\n/done\n/cancel\n/menu\n/full\n\nSection view\n/today\n/straight\n/road25\n/road50\n/road75\n/road100\n/profitboost\n/nosweat\n/plusmoney\n/edges\n/magician\n/sgp\n/daily\n/boxscore\n/lottery\n/moneyline\n\nChart breakdown\n/chartpost\n/chartimage\n/charttext\n/chartview\n/chartdone\n/chartcancel\n\nChannel push\n/push_loading\n/push_fullcard\n/push_disclaimer\n/push_replacement\n/push_full\n/push_today\n/push_straight\n/push_road25\n/push_road50\n/push_road75\n/push_road100\n/push_profitboost\n/push_nosweat\n/push_plusmoney\n/push_edges\n/push_magician\n/push_sgp\n/push_daily\n/push_boxscore\n/push_lottery\n/push_moneyline\n/push_chart\n/push_chartbreakdown\n\nPDF\n/linkpdf\n"""

app = Flask(__name__)


@dataclass
class StageState:
    status: str = "empty"
    post_type: str = ""
    target_chat_id: str = CHANNEL_CHAT_ID
    text_body: str = ""
    caption: str = ""
    media_type: str = "none"  # none|image|pdf
    file_id: str = ""
    approved: bool = False


state = {
    "intake_mode": None,  # post|stage_text|stage_image|stage_pdf|linkpdf|chart_image|chart_text
    "staged_game_text": "",
    "staged_board_text": "",
    "board_title": "",
    "board_sections": {},
    "stage": StageState(),
    "chart_draft": {
        "image_file_id": "",
        "image_caption": "",
        "breakdown_text": "",
        "ready": False,
    },
}


def tg_api(method: str, data: Optional[dict] = None, files=None):
    url = f"{BASE_URL}/{method}"
    resp = requests.post(url, data=data, files=files, timeout=30)
    try:
        payload = resp.json()
    except Exception:
        logger.error("Telegram non-JSON response: %s", resp.text)
        resp.raise_for_status()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error on {method}: {payload}")
    return payload["result"]


def send_message(chat_id: str, text: str):
    return tg_api("sendMessage", {"chat_id": chat_id, "text": text})


def send_photo(chat_id: str, file_id: str, caption: str = ""):
    return tg_api("sendPhoto", {"chat_id": chat_id, "photo": file_id, "caption": caption})


def send_document(chat_id: str, file_id: str, caption: str = ""):
    return tg_api("sendDocument", {"chat_id": chat_id, "document": file_id, "caption": caption})


def is_owner(message: dict) -> bool:
    user_id = int(message.get("from", {}).get("id", 0))
    return OWNER_CHAT_ID == 0 or user_id == OWNER_CHAT_ID


def strip_disclaimer_blocks(text: str) -> str:
    lines = text.splitlines()
    out = []
    skip = False
    for line in lines:
        s = line.strip()
        if s.startswith("⚠️ Disclaimer:") or s.startswith("Disclaimer:"):
            skip = True
            continue
        if skip and not s:
            continue
        if skip and (s.startswith("🔁 If any leg") or s.startswith("If any leg")):
            continue
        out.append(line)
    return "\n".join(out).strip()


def strip_brand_header(text: str) -> str:
    lines = [ln for ln in text.splitlines()]
    if lines and BRAND_NAME.lower() in lines[0].lower():
        return "\n".join(lines[1:]).strip()
    return text


def parse_sections(full_text: str):
    lines = [ln.rstrip() for ln in full_text.splitlines()]
    title = ""
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx < len(lines):
        title = lines[idx].strip()
        idx += 1
    current_header = None
    buf: List[str] = []
    sections: Dict[str, str] = {}
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        matched = next((h for h in MAIN_SECTION_ORDER if stripped == h or stripped.startswith(h + " ")), None)
        if matched:
            if current_header:
                sections[current_header] = "\n".join(buf).strip()
                buf = []
            current_header = matched
            buf.append(line)
        else:
            if current_header:
                buf.append(line)
        idx += 1
    if current_header:
        sections[current_header] = "\n".join(buf).strip()
    return title, sections


def road_has_all_tickets(section_text: str) -> bool:
    needed = [f"Ticket {n}" for n in range(1, 6)]
    return all(t in section_text for t in needed)


def validate_roads(sections: Dict[str, str]):
    problems = []
    if "Road to $25" in sections and not road_has_all_tickets(sections["Road to $25"]):
        problems.append("Road to $25 is missing one or more tickets.")
    if "Road to $50" in sections and not road_has_all_tickets(sections["Road to $50"]):
        problems.append("Road to $50 is missing one or more tickets.")
    return problems


def stage_text(post_type: str, text_body: str):
    state["stage"] = StageState(status="drafted", post_type=post_type, text_body=text_body)


def stage_file(post_type: str, media_type: str, file_id: str, caption: str = ""):
    state["stage"] = StageState(status="drafted", post_type=post_type, media_type=media_type, file_id=file_id, caption=caption)


def reset_chart_draft():
    state["chart_draft"] = {
        "image_file_id": "",
        "image_caption": "",
        "breakdown_text": "",
        "ready": False,
    }


def render_preview() -> str:
    s: StageState = state["stage"]
    return (
        f"[Preview]\n"
        f"Status: {s.status}\n"
        f"Type: {s.post_type}\n"
        f"Media: {s.media_type}\n"
        f"Approved: {s.approved}\n\n"
        f"Text:\n{s.text_body or s.caption or '(none)'}"
    )


def push_stage():
    s: StageState = state["stage"]
    if s.status == "empty":
        return "Nothing is staged."
    if not s.approved:
        return "Stage not approved. Run /preview then /approve before /push."
    if s.media_type == "image":
        send_photo(s.target_chat_id, s.file_id, s.caption)
    elif s.media_type == "pdf":
        send_document(s.target_chat_id, s.file_id, s.caption)
    else:
        send_message(s.target_chat_id, s.text_body)
    s.status = "posted"
    return "Posted to channel."


def make_public_preview() -> str:
    title = state.get("board_title") or "Tonight’s Board"
    lines = [BRAND_NAME, title, "", "Today’s Selections", ""]
    if "Best Clickable Core Read" in state["board_sections"]:
        lines.append(state["board_sections"]["Best Clickable Core Read"])
        lines.append("")
    remaining = [h for h in MAIN_SECTION_ORDER if h != "Best Clickable Core Read"]
    lines.extend(remaining)
    return "\n".join(lines).strip()


def command_response(text: str, sender_id: Optional[int] = None) -> Optional[str]:
    s = state["stage"]
    if text == "/start":
        return "Bot is live. Use /help to see commands."
    if text == "/help":
        return HELP_TEXT
    if text == "/whoami":
        return f"Configured OWNER_CHAT_ID: {OWNER_CHAT_ID or 'not locked yet'}\nSender ID: {sender_id}"
    if text == "/status":
        return json.dumps(
            {
                "stage_status": s.status,
                "post_type": s.post_type,
                "media_type": s.media_type,
                "approved": s.approved,
                "board_title": state["board_title"],
                "loaded_sections": list(state["board_sections"].keys()),
                "intake_mode": state["intake_mode"],
                "chart_ready": state["chart_draft"]["ready"],
                "chart_has_image": bool(state["chart_draft"]["image_file_id"]),
                "chart_has_text": bool(state["chart_draft"]["breakdown_text"]),
            },
            indent=2,
        )
    if text == "/clearstage":
        state["stage"] = StageState()
        state["intake_mode"] = None
        state["staged_board_text"] = ""
        reset_chart_draft()
        return "Stage and chart draft cleared."
    if text == "/cancel":
        state["intake_mode"] = None
        state["staged_board_text"] = ""
        return "Current intake cancelled."
    if text == "/preview":
        state["stage"].status = "previewed"
        return render_preview()
    if text == "/approve":
        state["stage"].approved = True
        state["stage"].status = "approved"
        return "Stage approved."
    if text == "/reject":
        state["stage"].approved = False
        state["stage"].status = "drafted"
        return "Stage rejected and returned to drafted state."
    if text == "/push":
        return push_stage()

    if text == "/post":
        state["intake_mode"] = "post"
        state["staged_board_text"] = ""
        return "Paste the full final board now. Then send /done."
    if text == "/done":
        raw = state["staged_board_text"].strip()
        if not raw:
            return "No board text staged. Use /post first."
        cleaned = strip_brand_header(strip_disclaimer_blocks(raw))
        title, sections = parse_sections(cleaned)
        state["board_title"] = title
        state["board_sections"] = sections
        problems = validate_roads(sections)
        state["intake_mode"] = None
        msg = [f"Board stored. Title: {title}", f"Sections loaded: {', '.join(sections.keys()) or 'none'}"]
        if problems:
            msg.append("Validation issues:")
            msg.extend([f"- {p}" for p in problems])
        else:
            msg.append("Road validation passed.")
        return "\n".join(msg)
    if text == "/menu":
        if not state["board_sections"]:
            return "No board stored yet. Use /post and /done first."
        items = [cmd for cmd in SECTION_COMMAND_MAP]
        return "Available private view commands:\n" + "\n".join(items)
    if text == "/full":
        if not state["board_sections"]:
            return "No board stored yet."
        body = [state["board_title"], ""]
        for h in MAIN_SECTION_ORDER:
            if h in state["board_sections"]:
                body.append(state["board_sections"][h])
                body.append("")
        return "\n".join(body).strip()

    if text in SECTION_COMMAND_MAP:
        header = SECTION_COMMAND_MAP[text]
        section = state["board_sections"].get(header)
        if not section:
            return f"No stored section found for {header}."
        return f"{state['board_title']}\n\n{section}" if state["board_title"] else section

    if text == "/loadboard":
        stage_text("loadboard", LOADBOARD_TEMPLATE)
        return "Board loading alert staged. Run /preview then /approve then /push."
    if text == "/fullcard":
        stage_text("fullcard", FULLCARD_TEMPLATE)
        return "Full-card-live post staged."
    if text == "/adjustment":
        state["intake_mode"] = "stage_text"
        state["stage"] = StageState(status="drafted", post_type="adjustment")
        return "Send the adjustment text now."
    if text == "/halftime":
        state["intake_mode"] = "stage_text"
        state["stage"] = StageState(status="drafted", post_type="halftime")
        return "Send the halftime/live alert text now."
    if text == "/recap":
        state["intake_mode"] = "stage_text"
        state["stage"] = StageState(status="drafted", post_type="recap")
        return "Send the recap text now."
    if text == "/disclaimer":
        stage_text("disclaimer", DISCLAIMER_TEMPLATE)
        return "Disclaimer staged."
    if text == "/replacementnote":
        stage_text("replacementnote", REPLACEMENT_TEMPLATE)
        return "Replacement note staged."

    if text == "/stage_text":
        state["intake_mode"] = "stage_text"
        state["stage"] = StageState(status="drafted", post_type="text_only")
        return "Send the text body now."
    if text == "/stage_image":
        state["intake_mode"] = "stage_image"
        state["stage"] = StageState(status="drafted", post_type="image_post", media_type="image")
        return "Send one image now with or without a caption."
    if text == "/stage_pdf":
        state["intake_mode"] = "stage_pdf"
        state["stage"] = StageState(status="drafted", post_type="pdf_post", media_type="pdf")
        return "Send one PDF/document now with or without a caption."
    if text == "/linkpdf":
        state["intake_mode"] = "linkpdf"
        return "Send the Telegram file_id and caption separated by a new line."

    if text == "/chartpost":
        reset_chart_draft()
        return "Chart breakdown intake started. Use /chartimage, then /charttext, then /chartview, then /chartdone."
    if text == "/chartimage":
        state["intake_mode"] = "chart_image"
        return "Send the chart image now with a short caption."
    if text == "/charttext":
        state["intake_mode"] = "chart_text"
        return "Send the full chart breakdown text now."
    if text == "/chartview":
        chart = state["chart_draft"]
        if not chart["image_file_id"] and not chart["breakdown_text"]:
            return "No chart draft stored yet."
        preview_lines = [
            "[Chart Preview]",
            f"Image staged: {'yes' if chart['image_file_id'] else 'no'}",
            f"Caption staged: {'yes' if chart['image_caption'] else 'no'}",
            f"Breakdown staged: {'yes' if chart['breakdown_text'] else 'no'}",
            "",
            "Image caption:",
            chart["image_caption"] or "(none)",
            "",
            "Breakdown preview:",
            chart["breakdown_text"][:1000] + ("..." if len(chart["breakdown_text"]) > 1000 else ""),
        ]
        return "\n".join(preview_lines)
    if text == "/chartdone":
        chart = state["chart_draft"]
        if not chart["image_file_id"]:
            return "Chart draft is missing an image."
        if not chart["breakdown_text"]:
            return "Chart draft is missing breakdown text."
        chart["ready"] = True
        state["intake_mode"] = None
        return "Chart draft stored and ready. Use /push_chart and /push_chartbreakdown."
    if text == "/chartcancel":
        reset_chart_draft()
        state["intake_mode"] = None
        return "Chart draft cancelled."
    if text == "/push_chart":
        chart = state["chart_draft"]
        if not chart["ready"]:
            return "Chart draft is not ready. Use /chartdone first."
        send_photo(CHANNEL_CHAT_ID, chart["image_file_id"], chart["image_caption"])
        return "Chart image posted."
    if text == "/push_chartbreakdown":
        chart = state["chart_draft"]
        if not chart["ready"]:
            return "Chart draft is not ready. Use /chartdone first."
        send_message(CHANNEL_CHAT_ID, chart["breakdown_text"])
        return "Chart breakdown posted."

    if text == "/push_loading":
        send_message(CHANNEL_CHAT_ID, LOADBOARD_TEMPLATE)
        return "Loading alert posted."
    if text == "/push_fullcard":
        send_message(CHANNEL_CHAT_ID, FULLCARD_TEMPLATE)
        return "Full card live posted."
    if text == "/push_disclaimer":
        send_message(CHANNEL_CHAT_ID, DISCLAIMER_TEMPLATE)
        return "Disclaimer posted."
    if text == "/push_replacement":
        send_message(CHANNEL_CHAT_ID, REPLACEMENT_TEMPLATE)
        return "Replacement note posted."
    if text == "/push_preview":
        send_message(CHANNEL_CHAT_ID, make_public_preview())
        return "Preview posted."
    if text == "/push_full":
        full = command_response("/full")
        if full and not full.startswith("No board"):
            send_message(CHANNEL_CHAT_ID, full)
            return "Full board posted."
        return full
    if text in PUSH_COMMAND_MAP:
        header = PUSH_COMMAND_MAP[text]
        section = state["board_sections"].get(header)
        if not section:
            return f"No stored section found for {header}."
        msg = f"{state['board_title']}\n\n{section}" if state["board_title"] else section
        send_message(CHANNEL_CHAT_ID, msg)
        return f"Posted {header}."

    return None


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.post(f"/webhook/{WEBHOOK_SECRET_PATH}")
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify({"ok": True})

    if not is_owner(message):
        return jsonify({"ok": True})

    chat_id = str(message["chat"]["id"])
    text = (message.get("text") or "").strip()

    try:
        if text.startswith("/"):
            response = command_response(text, int(message.get("from", {}).get("id", 0)))
            if response:
                send_message(chat_id, response)
            return jsonify({"ok": True})

        mode = state["intake_mode"]
        if mode == "post":
            state["staged_board_text"] += ("\n" if state["staged_board_text"] else "") + (message.get("text") or "")
            send_message(chat_id, "Board text appended. Send /done when finished.")
            return jsonify({"ok": True})

        if mode == "stage_text":
            body = message.get("text") or ""
            stage_text(state["stage"].post_type or "text_only", body)
            state["intake_mode"] = None
            send_message(chat_id, "Text staged. Run /preview then /approve then /push.")
            return jsonify({"ok": True})

        if mode == "linkpdf":
            body = message.get("text") or ""
            parts = body.splitlines()
            if not parts:
                send_message(chat_id, "Missing file_id.")
                return jsonify({"ok": True})
            file_id = parts[0].strip()
            caption = "\n".join(parts[1:]).strip()
            stage_file("pdf_post", "pdf", file_id, caption)
            state["intake_mode"] = None
            send_message(chat_id, "PDF staged from file_id. Run /preview then /approve then /push.")
            return jsonify({"ok": True})

        if mode == "chart_image" and message.get("photo"):
            photo_sizes = message["photo"]
            file_id = photo_sizes[-1]["file_id"]
            caption = (message.get("caption") or "").strip()
            state["chart_draft"]["image_file_id"] = file_id
            state["chart_draft"]["image_caption"] = caption
            state["intake_mode"] = None
            send_message(chat_id, "Chart image stored. Now run /charttext and send the full breakdown.")
            return jsonify({"ok": True})

        if mode == "chart_text":
            body = message.get("text") or ""
            state["chart_draft"]["breakdown_text"] = body
            state["intake_mode"] = None
            send_message(chat_id, "Chart breakdown text stored. Run /chartview, then /chartdone when ready.")
            return jsonify({"ok": True})

        if mode == "stage_image" and message.get("photo"):
            photo_sizes = message["photo"]
            file_id = photo_sizes[-1]["file_id"]
            caption = (message.get("caption") or "").strip()
            stage_file("image_post", "image", file_id, caption)
            state["intake_mode"] = None
            send_message(chat_id, "Image staged. Run /preview then /approve then /push.")
            return jsonify({"ok": True})

        if mode == "stage_pdf" and message.get("document"):
            file_id = message["document"]["file_id"]
            caption = (message.get("caption") or "").strip()
            stage_file("pdf_post", "pdf", file_id, caption)
            state["intake_mode"] = None
            send_message(chat_id, "PDF staged. Run /preview then /approve then /push.")
            return jsonify({"ok": True})

        send_message(chat_id, "No active intake mode. Use /help.")
    except Exception as exc:
        logger.exception("Webhook handling failed")
        send_message(chat_id, f"Error: {exc}")

    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
