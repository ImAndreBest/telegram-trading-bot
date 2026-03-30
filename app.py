import logging
import os
import re
from functools import wraps
from typing import Dict, List, Tuple

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    if raw is None:
        return default
    raw = str(raw).strip()
    return int(raw) if raw.isdigit() else default


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = env_int("OWNER_ID", 0)
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
PORT = env_int("PORT", 10000)

MODE_GAME = "mode_game"
MODE_BOARD = "mode_board"
MODE_WIN = "mode_win"
MODE_HALF = "mode_half"

KEY_GAME_DRAFT = "game_draft"
KEY_GAME_TEXT = "game_text"
KEY_BOARD_DRAFT = "board_draft"
KEY_BOARD_TEXT = "board_text"
KEY_BOARD_MATCHUP = "board_matchup"
KEY_BOARD_SECTIONS = "board_sections"
KEY_WIN_DRAFT = "win_draft"
KEY_WIN_TEXT = "win_text"
KEY_WIN_SECTIONS = "win_sections"
KEY_HALF_DRAFT = "half_draft"
KEY_HALF_TEXT = "half_text"
KEY_HALF_MATCHUP = "half_matchup"
KEY_HALF_SECTIONS = "half_sections"

PREVIEW_TEXT = (
    "🎯 Today’s Selections preview is loading.\n\n"
    "Today’s Selections will be posted first.\n"
    "Full ticket reveals will follow after that.\n\n"
    "🔒 Stay locked."
)

LOADING_TEXT = (
    "🎯 Tonight’s board is loading.\n\n"
    "📌 Today’s Selections will be posted first.\n"
    "🎟️ Full ticket reveals will follow after that.\n\n"
    "🔒 Stay locked."
)

LIVE_TEXT = (
    "✅ Full card is live.\n\n"
    "📌 Today’s Selections are posted.\n"
    "🎟️ All ticket reveals for tonight have been sent.\n\n"
    "🔄 Anything else posted after this is a true adjustment only."
)

DISCLAIMER_TEXT = (
    "⚠️ Disclaimer: Plays are for informational and entertainment purposes only. No result is guaranteed. "
    "Bet responsibly and only risk what you can afford to lose.\n\n"
    "🔁 If any leg is too juiced for your liking, you can swap it for a lesser prop replacement that still fits the same player role and ticket job."
)

PREGAME_HEADERS = [
    "Today's Selections",
    "Straight Bets Board",
    "Road to $25",
    "Road to $50",
    "Profit Boost Ticket",
    "+MoneyBet Ticket",
    "Magician Ticket",
    "SGP Ticket",
    "Game Line Ticket",
    "Money Line Ticket",
]

HALFTIME_HEADERS = [
    "Halftime Live Board",
    "Live Profit Boost Ticket",
    "Live +MoneyBet Ticket",
    "Live SGP Ticket",
]

WINNER_HEADERS = [
    "Straight 1 Winner",
    "Straight 2 Winner",
    "Straight 3 Winner",
    "Straight 4 Winner",
    "Straight 5 Winner",
    "Road 25 Ticket 1 Winner",
    "Road 25 Ticket 2 Winner",
    "Road 25 Ticket 3 Winner",
    "Road 25 Ticket 4 Winner",
    "Road 25 Ticket 5 Winner",
    "Road 50 Ticket 1 Winner",
    "Road 50 Ticket 2 Winner",
    "Road 50 Ticket 3 Winner",
    "Road 50 Ticket 4 Winner",
    "Road 50 Ticket 5 Winner",
    "Profit Boost Winner",
    "+MoneyBet Winner",
    "Magician Winner",
    "SGP Winner",
    "Game Line Winner",
    "Money Line Winner",
    "All Straights Winner",
    "All Road 25 Winners",
    "All Road 50 Winners",
    "All Roads Winner",
    "All Side Tickets Winner",
    "Combo Winner",
    "Sweep Winner",
]

PREGAME_COMMAND_MAP = {
    "today": "Today's Selections",
    "straight": "Straight Bets Board",
    "road25": "Road to $25",
    "road50": "Road to $50",
    "profitboost": "Profit Boost Ticket",
    "plusmoney": "+MoneyBet Ticket",
    "magician": "Magician Ticket",
    "sgp": "SGP Ticket",
    "gameline": "Game Line Ticket",
    "moneyline": "Money Line Ticket",
}

HALFTIME_COMMAND_MAP = {
    "liveprofitboost": "Live Profit Boost Ticket",
    "liveplusmoney": "Live +MoneyBet Ticket",
    "livesgp": "Live SGP Ticket",
}

WINNER_COMMAND_MAP = {
    "win_straight_1": "Straight 1 Winner",
    "win_straight_2": "Straight 2 Winner",
    "win_straight_3": "Straight 3 Winner",
    "win_straight_4": "Straight 4 Winner",
    "win_straight_5": "Straight 5 Winner",
    "win_road25_1": "Road 25 Ticket 1 Winner",
    "win_road25_2": "Road 25 Ticket 2 Winner",
    "win_road25_3": "Road 25 Ticket 3 Winner",
    "win_road25_4": "Road 25 Ticket 4 Winner",
    "win_road25_5": "Road 25 Ticket 5 Winner",
    "win_road50_1": "Road 50 Ticket 1 Winner",
    "win_road50_2": "Road 50 Ticket 2 Winner",
    "win_road50_3": "Road 50 Ticket 3 Winner",
    "win_road50_4": "Road 50 Ticket 4 Winner",
    "win_road50_5": "Road 50 Ticket 5 Winner",
    "win_profitboost": "Profit Boost Winner",
    "win_plusmoney": "+MoneyBet Winner",
    "win_magician": "Magician Winner",
    "win_sgp": "SGP Winner",
    "win_gameline": "Game Line Winner",
    "win_moneyline": "Money Line Winner",
    "win_all_straights": "All Straights Winner",
    "win_all_road25": "All Road 25 Winners",
    "win_all_road50": "All Road 50 Winners",
    "win_all_roads": "All Roads Winner",
    "win_all_sides": "All Side Tickets Winner",
    "win_combo": "Combo Winner",
    "win_sweep": "Sweep Winner",
}

PREGAME_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("Today's Selections"), KeyboardButton("Straight Bets")],
        [KeyboardButton("Road to $25"), KeyboardButton("Road to $50")],
        [KeyboardButton("Profit Boost"), KeyboardButton("+MoneyBet")],
        [KeyboardButton("Magician"), KeyboardButton("SGP")],
        [KeyboardButton("Game Line"), KeyboardButton("Money Line")],
        [KeyboardButton("Show Full Board"), KeyboardButton("Refresh Menu")],
    ],
    resize_keyboard=True,
)

HALFTIME_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("Live Profit Boost"), KeyboardButton("Live +MoneyBet")],
        [KeyboardButton("Live SGP"), KeyboardButton("Show Full Halftime")],
        [KeyboardButton("Refresh Halftime Menu")],
    ],
    resize_keyboard=True,
)

WINNER_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("Straight Winners"), KeyboardButton("Road 25 Winners")],
        [KeyboardButton("Road 50 Winners"), KeyboardButton("Side Ticket Winners")],
        [KeyboardButton("All Roads"), KeyboardButton("Full Winner Board")],
        [KeyboardButton("Refresh Winner Menu")],
    ],
    resize_keyboard=True,
)


def owner_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if OWNER_ID and (not user or user.id != OWNER_ID):
            if update.effective_message:
                await update.effective_message.reply_text("⛔ Owner only.")
            return
        return await func(update, context)

    return wrapper


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def strip_disclaimer_block(text: str) -> str:
    lines = text.split("\n")
    out: List[str] = []
    skipping = False
    for line in lines:
        if line.strip().startswith("⚠️ Disclaimer"):
            skipping = True
            continue
        if skipping:
            continue
        out.append(line)
    return "\n".join(out).strip()


def find_matchup_line(lines: List[str]) -> int:
    matchup_patterns = [r".+\s@\s.+", r".+\sat\s.+"]
    for i, line in enumerate(lines):
        stripped = line.strip()
        if any(re.fullmatch(pat, stripped) for pat in matchup_patterns):
            return i
    return 0


def preprocess_board_text(text: str) -> str:
    text = clean_text(text)
    text = strip_disclaimer_block(text)
    lines = text.split("\n")
    idx = find_matchup_line(lines)
    return "\n".join(lines[idx:]).strip()


def line_matches_header(line: str, header: str) -> bool:
    stripped = line.strip()
    return (
        stripped == header
        or stripped.startswith(header + " ")
        or stripped.startswith(header + "\t")
        or stripped.startswith(header + "🎯")
        or stripped.startswith(header + "📈")
        or stripped.startswith(header + "🛣️")
        or stripped.startswith(header + "🔥")
        or stripped.startswith(header + "💸")
        or stripped.startswith(header + "🪄")
        or stripped.startswith(header + "🎮")
        or stripped.startswith(header + "📊")
        or stripped.startswith(header + "💼")
    )


def parse_sections(text: str, headers: List[str]) -> Tuple[str, Dict[str, str]]:
    text = clean_text(text)
    lines = text.split("\n")
    matchup_idx = find_matchup_line(lines)
    lines = lines[matchup_idx:]
    matchup = lines[0].strip() if lines else ""

    header_positions: List[Tuple[int, str]] = []
    for idx, line in enumerate(lines[1:], start=1):
        for header in headers:
            if line_matches_header(line, header):
                header_positions.append((idx, header))
                break

    sections: Dict[str, str] = {}
    if not header_positions:
        return matchup, sections

    for i, (start_idx, header) in enumerate(header_positions):
        end_idx = header_positions[i + 1][0] if i + 1 < len(header_positions) else len(lines)
        block = "\n".join(lines[start_idx:end_idx]).strip()
        sections[header] = block

    return matchup, sections


def build_full_board(matchup: str, sections: Dict[str, str], headers: List[str]) -> str:
    parts = [matchup]
    for header in headers:
        block = sections.get(header)
        if block:
            parts.append(block)
    return "\n\n".join(parts).strip()


def build_preview(matchup: str) -> str:
    return f"{matchup}\n\n{PREVIEW_TEXT}".strip()


def matchup_plus_section(matchup: str, section: str) -> str:
    return f"{matchup}\n\n{section}".strip()


def split_message(text: str, limit: int = 4096) -> List[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for line in text.split("\n"):
        add_len = len(line) + 1
        if current and current_len + add_len > limit:
            chunks.append("\n".join(current).strip())
            current = [line]
            current_len = len(line) + 1
        else:
            current.append(line)
            current_len += add_len
    if current:
        chunks.append("\n".join(current).strip())
    return chunks


async def reply_long(message, text: str, keyboard=None):
    chunks = split_message(text)
    for i, chunk in enumerate(chunks):
        kwargs = {}
        if i == len(chunks) - 1 and keyboard is not None:
            kwargs["reply_markup"] = keyboard
        await message.reply_text(chunk, **kwargs)


async def push_to_channel(context: ContextTypes.DEFAULT_TYPE, text: str):
    if not CHANNEL_ID:
        raise ValueError("CHANNEL_ID is not set.")
    chunks = split_message(text)
    for chunk in chunks:
        await context.bot.send_chat_action(chat_id=CHANNEL_ID, action=ChatAction.TYPING)
        await context.bot.send_message(chat_id=CHANNEL_ID, text=chunk)


async def show_help_text(message):
    await reply_long(
        message,
        "Sports Betting OS Commands\n\n"
        "Game Selection\n"
        "/gamepost, /gamedone, /gamecancel, /gameview, /push_gameselect\n\n"
        "Pregame Board\n"
        "/post, /done, /cancel, /menu, /today, /straight, /road25, /road50, /profitboost, /plusmoney, /magician, /sgp, /gameline, /moneyline, /full\n\n"
        "Pregame Push\n"
        "/push_loading, /push_preview, /push_today, /push_straight, /push_road25, /push_road50, /push_profitboost, /push_plusmoney, /push_magician, /push_sgp, /push_gameline, /push_moneyline, /push_disclaimer, /push_full, /push_live\n\n"
        "Halftime\n"
        "/halfpost, /halfdone, /halfcancel, /halfmenu, /halfview, /liveprofitboost, /liveplusmoney, /livesgp\n\n"
        "Halftime Push\n"
        "/push_halftime, /push_liveprofitboost, /push_liveplusmoney, /push_livesgp\n\n"
        "Winners\n"
        "/winpost, /windone, /wincancel, /winmenu, /winfull plus /win_* and /push_win_* commands."
    )


@owner_only
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help_text(update.effective_message)


@owner_only
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help_text(update.effective_message)


@owner_only
async def gamepost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[MODE_GAME] = True
    context.user_data.pop(KEY_GAME_DRAFT, None)
    await update.effective_message.reply_text(
        "📝 Game Selection intake started. Paste the Telegram-ready Game Selection Board, then send /gamedone when finished."
    )


@owner_only
async def gamedone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = context.user_data.get(KEY_GAME_DRAFT, "").strip()
    if not draft:
        await update.effective_message.reply_text("No Game Selection draft is stored.")
        return
    context.application.bot_data[KEY_GAME_TEXT] = clean_text(draft)
    context.user_data.pop(MODE_GAME, None)
    context.user_data.pop(KEY_GAME_DRAFT, None)
    await update.effective_message.reply_text(
        "✅ Game Selection stored privately. Nothing has been posted to the channel.\n\n"
        "Use /push_gameselect when you're ready.",
        reply_markup=ReplyKeyboardRemove(),
    )


@owner_only
async def gamecancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(MODE_GAME, None)
    context.user_data.pop(KEY_GAME_DRAFT, None)
    await update.effective_message.reply_text("🗑️ Game Selection intake cancelled.")


@owner_only
async def gameview_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_GAME_TEXT)
    if not text:
        await update.effective_message.reply_text("No Game Selection Board is stored.")
        return
    await reply_long(update.effective_message, text)


@owner_only
async def push_gameselect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_GAME_TEXT)
    if not text:
        await update.effective_message.reply_text("No Game Selection Board is stored.")
        return
    await push_to_channel(context, text)
    await update.effective_message.reply_text("✅ Game Selection pushed to channel.")


@owner_only
async def post_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[MODE_BOARD] = True
    context.user_data.pop(KEY_BOARD_DRAFT, None)
    await update.effective_message.reply_text(
        "📝 Pregame board intake started. Paste the Telegram-ready final board without the disclaimer block, then send /done when finished."
    )


@owner_only
async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = context.user_data.get(KEY_BOARD_DRAFT, "").strip()
    if not draft:
        await update.effective_message.reply_text("No final board draft is stored.")
        return

    preprocessed = preprocess_board_text(draft)
    matchup, sections = parse_sections(preprocessed, PREGAME_HEADERS)
    if not matchup or not sections:
        await update.effective_message.reply_text(
            "❌ Could not parse the board. Check that the matchup line and section headers are intact."
        )
        return

    missing_roads = []
    road25 = sections.get("Road to $25", "")
    road50 = sections.get("Road to $50", "")
    for label, block in (("Road to $25", road25), ("Road to $50", road50)):
        if block and not all(f"Ticket {i}" in block for i in range(1, 6)):
            missing_roads.append(label)

    context.application.bot_data[KEY_BOARD_TEXT] = build_full_board(matchup, sections, PREGAME_HEADERS)
    context.application.bot_data[KEY_BOARD_MATCHUP] = matchup
    context.application.bot_data[KEY_BOARD_SECTIONS] = sections
    context.user_data.pop(MODE_BOARD, None)
    context.user_data.pop(KEY_BOARD_DRAFT, None)

    note = ""
    if missing_roads:
        note = f"\n\n⚠️ Road validator warning: {', '.join(missing_roads)} does not contain Ticket 1 through Ticket 5."

    await update.effective_message.reply_text(
        "✅ Board stored privately. Nothing has been posted to the channel.\n\n"
        "Use /push_loading, /push_preview, /push_today, /push_disclaimer, or any /push_* command when you're ready."
        + note,
        reply_markup=PREGAME_MENU,
    )


@owner_only
async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(MODE_BOARD, None)
    context.user_data.pop(KEY_BOARD_DRAFT, None)
    await update.effective_message.reply_text("🗑️ Pregame board intake cancelled.")


@owner_only
async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.application.bot_data.get(KEY_BOARD_TEXT):
        await update.effective_message.reply_text("No pregame board is stored.")
        return
    await update.effective_message.reply_text("✅ Pregame selector ready.", reply_markup=PREGAME_MENU)


async def show_pregame_section(update: Update, context: ContextTypes.DEFAULT_TYPE, header: str):
    matchup = context.application.bot_data.get(KEY_BOARD_MATCHUP)
    sections = context.application.bot_data.get(KEY_BOARD_SECTIONS, {})
    block = sections.get(header)
    if not matchup or not block:
        await update.effective_message.reply_text(f"No stored section found for {header}.")
        return
    await reply_long(update.effective_message, matchup_plus_section(matchup, block), keyboard=PREGAME_MENU)


async def push_pregame_section(update: Update, context: ContextTypes.DEFAULT_TYPE, header: str):
    matchup = context.application.bot_data.get(KEY_BOARD_MATCHUP)
    sections = context.application.bot_data.get(KEY_BOARD_SECTIONS, {})
    block = sections.get(header)
    if not matchup or not block:
        await update.effective_message.reply_text(f"No stored section found for {header}.")
        return
    await push_to_channel(context, matchup_plus_section(matchup, block))
    await update.effective_message.reply_text(f"✅ {header} pushed to channel.")


@owner_only
async def full_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_BOARD_TEXT)
    if not text:
        await update.effective_message.reply_text("No pregame board is stored.")
        return
    await reply_long(update.effective_message, text, keyboard=PREGAME_MENU)


@owner_only
async def push_loading_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await push_to_channel(context, LOADING_TEXT)
    await update.effective_message.reply_text("✅ Loading broadcast pushed.")


@owner_only
async def push_preview_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    matchup = context.application.bot_data.get(KEY_BOARD_MATCHUP)
    if not matchup:
        await update.effective_message.reply_text("No pregame board is stored.")
        return
    await push_to_channel(context, build_preview(matchup))
    await update.effective_message.reply_text("✅ Preview pushed.")


@owner_only
async def push_disclaimer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await push_to_channel(context, DISCLAIMER_TEXT)
    await update.effective_message.reply_text("✅ Disclaimer pushed.")


@owner_only
async def push_full_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_BOARD_TEXT)
    if not text:
        await update.effective_message.reply_text("No pregame board is stored.")
        return
    await push_to_channel(context, text)
    await update.effective_message.reply_text("✅ Full board pushed.")


@owner_only
async def push_live_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await push_to_channel(context, LIVE_TEXT)
    await update.effective_message.reply_text("✅ Live-close broadcast pushed.")


@owner_only
async def halfpost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[MODE_HALF] = True
    context.user_data.pop(KEY_HALF_DRAFT, None)
    await update.effective_message.reply_text(
        "📝 Halftime intake started. Paste the Telegram-ready halftime live board, then send /halfdone when finished."
    )


@owner_only
async def halfdone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = context.user_data.get(KEY_HALF_DRAFT, "").strip()
    if not draft:
        await update.effective_message.reply_text("No halftime draft is stored.")
        return

    preprocessed = preprocess_board_text(draft)
    matchup, sections = parse_sections(preprocessed, HALFTIME_HEADERS)
    if not matchup or not sections:
        await update.effective_message.reply_text(
            "❌ Could not parse the halftime board. Check that the matchup line and halftime headers are intact."
        )
        return

    context.application.bot_data[KEY_HALF_TEXT] = build_full_board(matchup, sections, HALFTIME_HEADERS)
    context.application.bot_data[KEY_HALF_MATCHUP] = matchup
    context.application.bot_data[KEY_HALF_SECTIONS] = sections
    context.user_data.pop(MODE_HALF, None)
    context.user_data.pop(KEY_HALF_DRAFT, None)

    await update.effective_message.reply_text(
        "✅ Halftime board stored privately. Nothing has been posted to the channel.\n\n"
        "Use /push_halftime, /push_liveprofitboost, /push_liveplusmoney, or /push_livesgp when you're ready.",
        reply_markup=HALFTIME_MENU,
    )


@owner_only
async def halfcancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(MODE_HALF, None)
    context.user_data.pop(KEY_HALF_DRAFT, None)
    await update.effective_message.reply_text("🗑️ Halftime intake cancelled.")


@owner_only
async def halfmenu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.application.bot_data.get(KEY_HALF_TEXT):
        await update.effective_message.reply_text("No halftime board is stored.")
        return
    await update.effective_message.reply_text("✅ Halftime selector ready.", reply_markup=HALFTIME_MENU)


@owner_only
async def halfview_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_HALF_TEXT)
    if not text:
        await update.effective_message.reply_text("No halftime board is stored.")
        return
    await reply_long(update.effective_message, text, keyboard=HALFTIME_MENU)


async def show_halftime_section(update: Update, context: ContextTypes.DEFAULT_TYPE, header: str):
    matchup = context.application.bot_data.get(KEY_HALF_MATCHUP)
    sections = context.application.bot_data.get(KEY_HALF_SECTIONS, {})
    block = sections.get(header)
    if not matchup or not block:
        await update.effective_message.reply_text(f"No stored halftime section found for {header}.")
        return
    await reply_long(update.effective_message, matchup_plus_section(matchup, block), keyboard=HALFTIME_MENU)


async def push_halftime_section(update: Update, context: ContextTypes.DEFAULT_TYPE, header: str):
    matchup = context.application.bot_data.get(KEY_HALF_MATCHUP)
    sections = context.application.bot_data.get(KEY_HALF_SECTIONS, {})
    block = sections.get(header)
    if not matchup or not block:
        await update.effective_message.reply_text(f"No stored halftime section found for {header}.")
        return
    await push_to_channel(context, matchup_plus_section(matchup, block))
    await update.effective_message.reply_text(f"✅ {header} pushed to channel.")


@owner_only
async def push_halftime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_HALF_TEXT)
    if not text:
        await update.effective_message.reply_text("No halftime board is stored.")
        return
    await push_to_channel(context, text)
    await update.effective_message.reply_text("✅ Halftime board pushed.")


@owner_only
async def winpost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[MODE_WIN] = True
    context.user_data.pop(KEY_WIN_DRAFT, None)
    await update.effective_message.reply_text(
        "📝 Winner intake started. Paste the Telegram-ready Winner Board, then send /windone when finished."
    )


@owner_only
async def windone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = context.user_data.get(KEY_WIN_DRAFT, "").strip()
    if not draft:
        await update.effective_message.reply_text("No Winner Board draft is stored.")
        return

    text = preprocess_board_text(draft)
    matchup, sections = parse_sections(text, WINNER_HEADERS)
    context.application.bot_data[KEY_WIN_TEXT] = build_full_board(matchup, sections, WINNER_HEADERS) if matchup else clean_text(text)
    context.application.bot_data[KEY_WIN_SECTIONS] = sections
    context.user_data.pop(MODE_WIN, None)
    context.user_data.pop(KEY_WIN_DRAFT, None)

    await update.effective_message.reply_text(
        "✅ Winner Board stored privately. Nothing has been posted to the channel.\n\n"
        "Use /winmenu or any /push_win_* command when you're ready.",
        reply_markup=WINNER_MENU,
    )


@owner_only
async def wincancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(MODE_WIN, None)
    context.user_data.pop(KEY_WIN_DRAFT, None)
    await update.effective_message.reply_text("🗑️ Winner intake cancelled.")


@owner_only
async def winmenu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.application.bot_data.get(KEY_WIN_TEXT):
        await update.effective_message.reply_text("No Winner Board is stored.")
        return
    await update.effective_message.reply_text("✅ Winner selector ready.", reply_markup=WINNER_MENU)


@owner_only
async def winfull_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_WIN_TEXT)
    if not text:
        await update.effective_message.reply_text("No Winner Board is stored.")
        return
    await reply_long(update.effective_message, text, keyboard=WINNER_MENU)


async def show_winner_section(update: Update, context: ContextTypes.DEFAULT_TYPE, header: str):
    sections = context.application.bot_data.get(KEY_WIN_SECTIONS, {})
    block = sections.get(header)
    if not block:
        await update.effective_message.reply_text(f"No stored winner section found for {header}.")
        return
    await reply_long(update.effective_message, block, keyboard=WINNER_MENU)


async def push_winner_section(update: Update, context: ContextTypes.DEFAULT_TYPE, header: str):
    sections = context.application.bot_data.get(KEY_WIN_SECTIONS, {})
    block = sections.get(header)
    if not block:
        await update.effective_message.reply_text(f"No stored winner section found for {header}.")
        return
    await push_to_channel(context, block)
    await update.effective_message.reply_text(f"✅ {header} pushed to channel.")


@owner_only
async def text_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.effective_message.text or ""

    if context.user_data.get(MODE_GAME):
        context.user_data[KEY_GAME_DRAFT] = text
        await update.effective_message.reply_text("✅ Game Selection draft received. Send /gamedone to store it.")
        return

    if context.user_data.get(MODE_BOARD):
        context.user_data[KEY_BOARD_DRAFT] = text
        await update.effective_message.reply_text("✅ Pregame board draft received. Send /done to store it.")
        return

    if context.user_data.get(MODE_WIN):
        context.user_data[KEY_WIN_DRAFT] = text
        await update.effective_message.reply_text("✅ Winner Board draft received. Send /windone to store it.")
        return

    if context.user_data.get(MODE_HALF):
        context.user_data[KEY_HALF_DRAFT] = text
        await update.effective_message.reply_text("✅ Halftime board draft received. Send /halfdone to store it.")
        return

    mapping = {
        "Today's Selections": PREGAME_COMMAND_MAP["today"],
        "Straight Bets": PREGAME_COMMAND_MAP["straight"],
        "Road to $25": PREGAME_COMMAND_MAP["road25"],
        "Road to $50": PREGAME_COMMAND_MAP["road50"],
        "Profit Boost": PREGAME_COMMAND_MAP["profitboost"],
        "+MoneyBet": PREGAME_COMMAND_MAP["plusmoney"],
        "Magician": PREGAME_COMMAND_MAP["magician"],
        "SGP": PREGAME_COMMAND_MAP["sgp"],
        "Game Line": PREGAME_COMMAND_MAP["gameline"],
        "Money Line": PREGAME_COMMAND_MAP["moneyline"],
    }
    if text in mapping:
        await show_pregame_section(update, context, mapping[text])
        return
    if text == "Show Full Board":
        await full_cmd(update, context)
        return
    if text == "Refresh Menu":
        await menu_cmd(update, context)
        return

    halftime_mapping = {
        "Live Profit Boost": HALFTIME_COMMAND_MAP["liveprofitboost"],
        "Live +MoneyBet": HALFTIME_COMMAND_MAP["liveplusmoney"],
        "Live SGP": HALFTIME_COMMAND_MAP["livesgp"],
    }
    if text in halftime_mapping:
        await show_halftime_section(update, context, halftime_mapping[text])
        return
    if text == "Show Full Halftime":
        await halfview_cmd(update, context)
        return
    if text == "Refresh Halftime Menu":
        await halfmenu_cmd(update, context)
        return

    if text == "Straight Winners":
        blocks = []
        for header in [h for h in WINNER_HEADERS if h.startswith("Straight")]:
            block = context.application.bot_data.get(KEY_WIN_SECTIONS, {}).get(header)
            if block:
                blocks.append(block)
        if not blocks:
            await update.effective_message.reply_text("No straight winners are stored.")
            return
        await reply_long(update.effective_message, "\n\n".join(blocks), keyboard=WINNER_MENU)
        return

    if text == "Road 25 Winners":
        blocks = []
        for header in [h for h in WINNER_HEADERS if h.startswith("Road 25")]:
            block = context.application.bot_data.get(KEY_WIN_SECTIONS, {}).get(header)
            if block:
                blocks.append(block)
        if not blocks:
            await update.effective_message.reply_text("No Road 25 winners are stored.")
            return
        await reply_long(update.effective_message, "\n\n".join(blocks), keyboard=WINNER_MENU)
        return

    if text == "Road 50 Winners":
        blocks = []
        for header in [h for h in WINNER_HEADERS if h.startswith("Road 50")]:
            block = context.application.bot_data.get(KEY_WIN_SECTIONS, {}).get(header)
            if block:
                blocks.append(block)
        if not blocks:
            await update.effective_message.reply_text("No Road 50 winners are stored.")
            return
        await reply_long(update.effective_message, "\n\n".join(blocks), keyboard=WINNER_MENU)
        return

    if text == "Side Ticket Winners":
        blocks = []
        for header in ["Profit Boost Winner", "+MoneyBet Winner", "Magician Winner", "SGP Winner", "Game Line Winner", "Money Line Winner"]:
            block = context.application.bot_data.get(KEY_WIN_SECTIONS, {}).get(header)
            if block:
                blocks.append(block)
        if not blocks:
            await update.effective_message.reply_text("No side ticket winners are stored.")
            return
        await reply_long(update.effective_message, "\n\n".join(blocks), keyboard=WINNER_MENU)
        return

    if text == "All Roads":
        block = context.application.bot_data.get(KEY_WIN_SECTIONS, {}).get("All Roads Winner")
        if not block:
            await update.effective_message.reply_text("No All Roads winner block is stored.")
            return
        await reply_long(update.effective_message, block, keyboard=WINNER_MENU)
        return

    if text == "Full Winner Board":
        await winfull_cmd(update, context)
        return
    if text == "Refresh Winner Menu":
        await winmenu_cmd(update, context)
        return


def make_show_pregame_callback(header: str):
    @owner_only
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await show_pregame_section(update, context, header)
    return _callback


def make_push_pregame_callback(header: str):
    @owner_only
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await push_pregame_section(update, context, header)
    return _callback


def make_show_halftime_callback(header: str):
    @owner_only
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await show_halftime_section(update, context, header)
    return _callback


def make_push_halftime_callback(header: str):
    @owner_only
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await push_halftime_section(update, context, header)
    return _callback


def make_show_winner_callback(header: str):
    @owner_only
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await show_winner_section(update, context, header)
    return _callback


def make_push_winner_callback(header: str):
    @owner_only
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await push_winner_section(update, context, header)
    return _callback


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    app.add_handler(CommandHandler("gamepost", gamepost_cmd))
    app.add_handler(CommandHandler("gamedone", gamedone_cmd))
    app.add_handler(CommandHandler("gamecancel", gamecancel_cmd))
    app.add_handler(CommandHandler("gameview", gameview_cmd))
    app.add_handler(CommandHandler("push_gameselect", push_gameselect_cmd))

    app.add_handler(CommandHandler("post", post_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("full", full_cmd))

    for cmd, header in PREGAME_COMMAND_MAP.items():
        app.add_handler(CommandHandler(cmd, make_show_pregame_callback(header)))
        app.add_handler(CommandHandler(f"push_{cmd}", make_push_pregame_callback(header)))

    app.add_handler(CommandHandler("push_loading", push_loading_cmd))
    app.add_handler(CommandHandler("push_preview", push_preview_cmd))
    app.add_handler(CommandHandler("push_disclaimer", push_disclaimer_cmd))
    app.add_handler(CommandHandler("push_full", push_full_cmd))
    app.add_handler(CommandHandler("push_live", push_live_cmd))

    app.add_handler(CommandHandler("halfpost", halfpost_cmd))
    app.add_handler(CommandHandler("halfdone", halfdone_cmd))
    app.add_handler(CommandHandler("halfcancel", halfcancel_cmd))
    app.add_handler(CommandHandler("halfmenu", halfmenu_cmd))
    app.add_handler(CommandHandler("halfview", halfview_cmd))
    app.add_handler(CommandHandler("push_halftime", push_halftime_cmd))

    for cmd, header in HALFTIME_COMMAND_MAP.items():
        app.add_handler(CommandHandler(cmd, make_show_halftime_callback(header)))
        app.add_handler(CommandHandler(f"push_{cmd}", make_push_halftime_callback(header)))

    app.add_handler(CommandHandler("winpost", winpost_cmd))
    app.add_handler(CommandHandler("windone", windone_cmd))
    app.add_handler(CommandHandler("wincancel", wincancel_cmd))
    app.add_handler(CommandHandler("winmenu", winmenu_cmd))
    app.add_handler(CommandHandler("winfull", winfull_cmd))

    for cmd, header in WINNER_COMMAND_MAP.items():
        app.add_handler(CommandHandler(cmd, make_show_winner_callback(header)))
        if cmd.startswith("win_"):
            app.add_handler(CommandHandler(f"push_{cmd}", make_push_winner_callback(header)))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_capture))
    return app


if __name__ == "__main__":
    application = build_application()
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
