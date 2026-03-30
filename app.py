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


def env_str(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name, "")
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            return value
    return default


def env_int(names: List[str], default: int = 0) -> int:
    for name in names:
        raw = os.getenv(name, "")
        if raw is None:
            continue
        value = str(raw).strip()
        if value.isdigit():
            return int(value)
    return default


BOT_TOKEN = env_str("BOT_TOKEN")
OWNER_ID = env_int(["OWNER_ID", "OWNER_CHAT_ID"], 0)
CHANNEL_ID = env_str("CHANNEL_ID", "CHANNEL_CHAT_ID")
WEBHOOK_URL = env_str("WEBHOOK_URL")
PORT_RAW = env_str("PORT")
PORT = int(PORT_RAW) if PORT_RAW.isdigit() else 10000

MODE_GAME = "mode_game"
MODE_SIDE = "mode_side"
MODE_BOARD = "mode_board"
MODE_HALF = "mode_half"
MODE_WIN = "mode_win"

KEY_GAME_DRAFT = "game_draft"
KEY_GAME_TEXT = "game_text"

KEY_SIDE_DRAFT = "side_draft"
KEY_SIDE_TEXT = "side_text"
KEY_SIDE_TITLE = "side_title"
KEY_SIDE_SECTIONS = "side_sections"

KEY_BOARD_DRAFT = "board_draft"
KEY_BOARD_TEXT = "board_text"
KEY_BOARD_TITLE = "board_title"
KEY_BOARD_SECTIONS = "board_sections"

KEY_HALF_DRAFT = "half_draft"
KEY_HALF_TEXT = "half_text"
KEY_HALF_TITLE = "half_title"
KEY_HALF_SECTIONS = "half_sections"

KEY_WIN_DRAFT = "win_draft"
KEY_WIN_TEXT = "win_text"
KEY_WIN_SECTIONS = "win_sections"

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
    "⚠️ Disclaimer: Plays are for informational and entertainment purposes only. "
    "No result is guaranteed. Bet responsibly and only risk what you can afford to lose.\n\n"
    "🔁 If any leg is too juiced for your liking, you can swap it for a lesser prop replacement "
    "that still fits the same player role and ticket job."
)

SIDE_HEADERS = [
    "Game Line Ticket",
    "Money Line Ticket",
]

PREGAME_HEADERS = [
    "Today's Selections",
    "Straight Bets Board",
    "Road to $25",
    "Road to $50",
    "Profit Boost Ticket",
    "+MoneyBet Ticket",
    "Magician Ticket",
    "SGP Ticket",
]

HALFTIME_HEADERS = [
    "Halftime Live Board",
    "Live Profit Boost Ticket",
    "Live +MoneyBet Ticket",
    "Live SGP Ticket",
]

PREGAME_VIEW_COMMAND_MAP = {
    "today": "Today's Selections",
    "straight": "Straight Bets Board",
    "road25": "Road to $25",
    "road50": "Road to $50",
    "profitboost": "Profit Boost Ticket",
    "plusmoney": "+MoneyBet Ticket",
    "magician": "Magician Ticket",
    "sgp": "SGP Ticket",
    "sides": "__PROP_SIDES__",
}

SIDE_VIEW_COMMAND_MAP = {
    "gameline": "Game Line Ticket",
    "moneyline": "Money Line Ticket",
}

HALFTIME_VIEW_COMMAND_MAP = {
    "liveprofitboost": "Live Profit Boost Ticket",
    "liveplusmoney": "Live +MoneyBet Ticket",
    "livesgp": "Live SGP Ticket",
}

PROP_SIDE_HEADERS = [
    "Profit Boost Ticket",
    "+MoneyBet Ticket",
    "Magician Ticket",
    "SGP Ticket",
]


WINNER_SIDE_PREFIXES = [
    "Profit Boost",
    "+MoneyBet",
    "Magician",
    "SGP",
    "Game Line",
    "Money Line",
]


def build_pregame_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Today's Selections"), KeyboardButton("Straight Bets")],
            [KeyboardButton("Road to $25"), KeyboardButton("Road to $50")],
            [KeyboardButton("Profit Boost"), KeyboardButton("+MoneyBet")],
            [KeyboardButton("Magician"), KeyboardButton("SGP")],
            [KeyboardButton("Show Prop Side Tickets"), KeyboardButton("Show Full Board")],
            [KeyboardButton("Refresh Menu")],
        ],
        resize_keyboard=True,
    )



def build_side_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Game Line Ticket"), KeyboardButton("Money Line Ticket")],
            [KeyboardButton("Show Full Side Board"), KeyboardButton("Refresh Side Menu")],
        ],
        resize_keyboard=True,
    )



def build_halftime_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Live Profit Boost"), KeyboardButton("Live +MoneyBet")],
            [KeyboardButton("Live SGP"), KeyboardButton("Show Full Halftime")],
            [KeyboardButton("Refresh Halftime Menu")],
        ],
        resize_keyboard=True,
    )



def build_winner_menu(sections: Dict[str, str]) -> ReplyKeyboardMarkup:
    rows: List[List[KeyboardButton]] = [[KeyboardButton("All Cashed Today")]]

    if get_straight_winner_blocks(sections):
        rows.append([KeyboardButton("Straight Winners")])

    if get_road_winner_blocks(sections):
        rows.append([KeyboardButton("Road Winners")])

    if get_side_winner_blocks(sections):
        rows.append([KeyboardButton("Side Ticket Winners")])

    rows.append([KeyboardButton("Full Winner Board")])
    rows.append([KeyboardButton("Push Winners"), KeyboardButton("Push Full Winner Board")])
    rows.append([KeyboardButton("Refresh Winner Menu")])

    return ReplyKeyboardMarkup(rows, resize_keyboard=True)



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
    lines = [line.rstrip() for line in text.split("\n")]
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
        stripped = line.strip()
        if stripped.startswith("⚠️ Disclaimer"):
            skipping = True
            continue
        if skipping:
            continue
        out.append(line)
    return "\n".join(out).strip()



def find_title_index(lines: List[str]) -> int:
    matchup_patterns = [r".+\s@\s.+", r".+\sat\s.+"]
    for i, line in enumerate(lines):
        stripped = line.strip()
        if any(re.fullmatch(pattern, stripped) for pattern in matchup_patterns):
            return i
    return 0



def preprocess_board_text(text: str) -> str:
    text = clean_text(text)
    text = strip_disclaimer_block(text)
    lines = text.split("\n")
    idx = find_title_index(lines)
    return "\n".join(lines[idx:]).strip()



def line_matches_header(line: str, header: str) -> bool:
    stripped = line.strip()
    if stripped == header:
        return True
    emoji_suffixes = ["🎯", "📈", "🛣️", "🔥", "💸", "🪄", "🎮", "📊", "💼", "🏀"]
    return any(stripped == f"{header} {emoji}" for emoji in emoji_suffixes)



def parse_named_sections(text: str, headers: List[str]) -> Tuple[str, Dict[str, str]]:
    text = clean_text(text)
    lines = text.split("\n")
    idx = find_title_index(lines)
    lines = lines[idx:]
    title = lines[0].strip() if lines else ""

    header_positions: List[Tuple[int, str]] = []
    for i, line in enumerate(lines[1:], start=1):
        for header in headers:
            if line_matches_header(line, header):
                header_positions.append((i, header))
                break

    sections: Dict[str, str] = {}
    if not header_positions:
        return title, sections

    for pos, (start_idx, header) in enumerate(header_positions):
        end_idx = header_positions[pos + 1][0] if pos + 1 < len(header_positions) else len(lines)
        block = "\n".join(lines[start_idx:end_idx]).strip()
        sections[header] = block

    return title, sections



def parse_winner_sections(text: str) -> Dict[str, str]:
    text = clean_text(text)
    lines = text.split("\n")
    idx = find_title_index(lines)
    lines = lines[idx:] if lines else []
    if not lines:
        return {}

    header_positions: List[Tuple[int, str]] = []
    for i, line in enumerate(lines[1:], start=1):
        stripped = line.strip()
        if re.fullmatch(r".+\bWinner$", stripped) or re.fullmatch(r".+\bWinners$", stripped):
            header_positions.append((i, stripped))

    sections: Dict[str, str] = {}
    for pos, (start_idx, header) in enumerate(header_positions):
        end_idx = header_positions[pos + 1][0] if pos + 1 < len(header_positions) else len(lines)
        sections[header] = "\n".join(lines[start_idx:end_idx]).strip()

    return sections



def build_full_board(title: str, sections: Dict[str, str], headers: List[str]) -> str:
    parts = [title] if title else []
    for header in headers:
        block = sections.get(header)
        if block:
            parts.append(block)
    return "\n\n".join(parts).strip()



def build_grouped_text(title: str, sections: Dict[str, str], wanted: List[str]) -> str:
    parts = [title] if title else []
    for header in wanted:
        block = sections.get(header)
        if block:
            parts.append(block)
    return "\n\n".join(parts).strip()



def build_preview(title: str) -> str:
    return f"{title}\n\n{PREVIEW_TEXT}".strip()



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
    for chunk in split_message(text):
        await context.bot.send_chat_action(chat_id=CHANNEL_ID, action=ChatAction.TYPING)
        await context.bot.send_message(chat_id=CHANNEL_ID, text=chunk)



def get_straight_winner_blocks(sections: Dict[str, str]) -> List[str]:
    return [block for header, block in sections.items() if header.startswith("Straight ") or header == "All Straights Winner"]



def get_road_winner_blocks(sections: Dict[str, str]) -> List[str]:
    return [
        block
        for header, block in sections.items()
        if header.startswith("Road 25 ")
        or header.startswith("Road 50 ")
        or header == "All Road 25 Winners"
        or header == "All Road 50 Winners"
        or header == "All Roads Winner"
    ]



def get_side_winner_blocks(sections: Dict[str, str]) -> List[str]:
    return [
        block
        for header, block in sections.items()
        if header == "All Side Tickets Winner" or any(header.startswith(prefix) for prefix in WINNER_SIDE_PREFIXES)
    ]



def get_all_cashed_today_text(sections: Dict[str, str], fallback_text: str) -> str:
    if not sections:
        return fallback_text.strip()
    return "\n\n".join(sections.values()).strip()


async def show_help_text(message):
    await reply_long(
        message,
        "Sports Betting OS Commands\n\n"
        "Main workflow\n"
        "/gamepost /gamedone /gameview /push_gameselect\n"
        "/sidepost /sidedone /sidemenu /sideview /push_lines\n"
        "/post /done /menu /full\n"
        "/halfpost /halfdone /halfmenu /halfview /push_halftime\n"
        "/winpost /windone /winmenu /winfull /push_winners\n\n"
        "Use the private menus for detailed section viewing.",
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
    text = context.application.bot_data.get(KEY_GAME_TEXT, "")
    if not text:
        await update.effective_message.reply_text("No Game Selection Board is stored.")
        return
    await reply_long(update.effective_message, text)


@owner_only
async def push_gameselect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_GAME_TEXT, "")
    if not text:
        await update.effective_message.reply_text("No Game Selection Board is stored.")
        return
    await push_to_channel(context, text)
    await update.effective_message.reply_text("✅ Game Selection pushed to channel.")


@owner_only
async def sidepost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[MODE_SIDE] = True
    context.user_data.pop(KEY_SIDE_DRAFT, None)
    await update.effective_message.reply_text(
        "📝 Early Slate Side Board intake started. Paste the Telegram-ready Early Slate Side Board, then send /sidedone when finished."
    )


@owner_only
async def sidedone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = context.user_data.get(KEY_SIDE_DRAFT, "").strip()
    if not draft:
        await update.effective_message.reply_text("No side board draft is stored.")
        return

    preprocessed = preprocess_board_text(draft)
    title, sections = parse_named_sections(preprocessed, SIDE_HEADERS)
    if not title or not sections:
        await update.effective_message.reply_text(
            "❌ Could not parse the side board. Check that the title line and side-ticket headers are intact."
        )
        return

    context.application.bot_data[KEY_SIDE_TITLE] = title
    context.application.bot_data[KEY_SIDE_SECTIONS] = sections
    context.application.bot_data[KEY_SIDE_TEXT] = build_full_board(title, sections, SIDE_HEADERS)

    context.user_data.pop(MODE_SIDE, None)
    context.user_data.pop(KEY_SIDE_DRAFT, None)

    await update.effective_message.reply_text(
        "✅ Early Slate Side Board stored privately. Nothing has been posted to the channel.\n\n"
        "Use /push_lines when you're ready.",
        reply_markup=build_side_menu(),
    )


@owner_only
async def sidecancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(MODE_SIDE, None)
    context.user_data.pop(KEY_SIDE_DRAFT, None)
    await update.effective_message.reply_text("🗑️ Side board intake cancelled.")


@owner_only
async def sidemenu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.application.bot_data.get(KEY_SIDE_TEXT):
        await update.effective_message.reply_text("No side board is stored.")
        return
    await update.effective_message.reply_text("✅ Side selector ready.", reply_markup=build_side_menu())


@owner_only
async def sideview_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_SIDE_TEXT, "")
    if not text:
        await update.effective_message.reply_text("No side board is stored.")
        return
    await reply_long(update.effective_message, text, keyboard=build_side_menu())


async def show_side_section(update: Update, context: ContextTypes.DEFAULT_TYPE, header: str):
    title = context.application.bot_data.get(KEY_SIDE_TITLE, "")
    sections = context.application.bot_data.get(KEY_SIDE_SECTIONS, {})
    block = sections.get(header)
    if not title or not block:
        await update.effective_message.reply_text(f"No stored side section found for {header}.")
        return
    await reply_long(update.effective_message, f"{title}\n\n{block}".strip(), keyboard=build_side_menu())


@owner_only
async def push_lines_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_SIDE_TEXT, "")
    if not text:
        await update.effective_message.reply_text("No side board is stored.")
        return
    await push_to_channel(context, text)
    await update.effective_message.reply_text("✅ Early Slate Side Board pushed to channel.")


@owner_only
async def post_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[MODE_BOARD] = True
    context.user_data.pop(KEY_BOARD_DRAFT, None)
    await update.effective_message.reply_text(
        "📝 Pregame player-prop board intake started. Paste the Telegram-ready final player-prop board without the disclaimer block, then send /done when finished."
    )


@owner_only
async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = context.user_data.get(KEY_BOARD_DRAFT, "").strip()
    if not draft:
        await update.effective_message.reply_text("No pregame board draft is stored.")
        return

    preprocessed = preprocess_board_text(draft)
    title, sections = parse_named_sections(preprocessed, PREGAME_HEADERS)
    if not title or not sections:
        await update.effective_message.reply_text(
            "❌ Could not parse the pregame board. Check that the title line and player-prop section headers are intact."
        )
        return

    context.application.bot_data[KEY_BOARD_TITLE] = title
    context.application.bot_data[KEY_BOARD_SECTIONS] = sections
    context.application.bot_data[KEY_BOARD_TEXT] = build_full_board(title, sections, PREGAME_HEADERS)

    context.user_data.pop(MODE_BOARD, None)
    context.user_data.pop(KEY_BOARD_DRAFT, None)

    warnings: List[str] = []
    for label in ["Road to $25", "Road to $50"]:
        block = sections.get(label, "")
        if block and not all(f"Ticket {i}" in block for i in range(1, 6)):
            warnings.append(f"⚠️ {label} is missing one or more tickets.")

    note = ("\n" + "\n".join(warnings)) if warnings else ""

    await update.effective_message.reply_text(
        "✅ Pregame player-prop board stored privately. Nothing has been posted to the channel.\n\n"
        "Use /push_loading, /push_preview, /push_today, /push_disclaimer, or any /push_* command when you're ready."
        + note,
        reply_markup=build_pregame_menu(),
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
    await update.effective_message.reply_text("✅ Pregame selector ready.", reply_markup=build_pregame_menu())


@owner_only
async def full_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_BOARD_TEXT, "")
    if not text:
        await update.effective_message.reply_text("No pregame board is stored.")
        return
    await reply_long(update.effective_message, text, keyboard=build_pregame_menu())


async def show_pregame_section(update: Update, context: ContextTypes.DEFAULT_TYPE, header: str):
    title = context.application.bot_data.get(KEY_BOARD_TITLE, "")
    sections = context.application.bot_data.get(KEY_BOARD_SECTIONS, {})
    block = sections.get(header)
    if not title or not block:
        await update.effective_message.reply_text(f"No stored section found for {header}.")
        return
    await reply_long(update.effective_message, f"{title}\n\n{block}".strip(), keyboard=build_pregame_menu())


async def show_grouped_pregame(update: Update, context: ContextTypes.DEFAULT_TYPE, headers: List[str]):
    title = context.application.bot_data.get(KEY_BOARD_TITLE, "")
    sections = context.application.bot_data.get(KEY_BOARD_SECTIONS, {})
    text = build_grouped_text(title, sections, headers)
    if not text.strip():
        await update.effective_message.reply_text("No grouped pregame sections are stored.")
        return
    await reply_long(update.effective_message, text, keyboard=build_pregame_menu())


async def push_pregame_section(update: Update, context: ContextTypes.DEFAULT_TYPE, header: str):
    title = context.application.bot_data.get(KEY_BOARD_TITLE, "")
    sections = context.application.bot_data.get(KEY_BOARD_SECTIONS, {})
    block = sections.get(header)
    if not title or not block:
        await update.effective_message.reply_text(f"No stored section found for {header}.")
        return
    await push_to_channel(context, f"{title}\n\n{block}".strip())
    await update.effective_message.reply_text(f"✅ {header} pushed to channel.")


async def push_grouped_pregame(update: Update, context: ContextTypes.DEFAULT_TYPE, headers: List[str], label: str):
    title = context.application.bot_data.get(KEY_BOARD_TITLE, "")
    sections = context.application.bot_data.get(KEY_BOARD_SECTIONS, {})
    text = build_grouped_text(title, sections, headers)
    if not text.strip():
        await update.effective_message.reply_text(f"No stored grouped sections found for {label}.")
        return
    await push_to_channel(context, text)
    await update.effective_message.reply_text(f"✅ {label} pushed to channel.")


@owner_only
async def push_loading_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await push_to_channel(context, LOADING_TEXT)
    await update.effective_message.reply_text("✅ Loading broadcast pushed.")


@owner_only
async def push_preview_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = context.application.bot_data.get(KEY_BOARD_TITLE, "")
    if not title:
        await update.effective_message.reply_text("No pregame board is stored.")
        return
    await push_to_channel(context, build_preview(title))
    await update.effective_message.reply_text("✅ Preview pushed.")


@owner_only
async def push_disclaimer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await push_to_channel(context, DISCLAIMER_TEXT)
    await update.effective_message.reply_text("✅ Disclaimer pushed.")


@owner_only
async def push_full_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_BOARD_TEXT, "")
    if not text:
        await update.effective_message.reply_text("No pregame board is stored.")
        return
    await push_to_channel(context, text)
    await update.effective_message.reply_text("✅ Full pregame board pushed.")


@owner_only
async def push_live_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await push_to_channel(context, LIVE_TEXT)
    await update.effective_message.reply_text("✅ Live-close broadcast pushed.")


@owner_only
async def push_sides_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await push_grouped_pregame(update, context, PROP_SIDE_HEADERS, "Prop side tickets")


@owner_only
async def halfpost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[MODE_HALF] = True
    context.user_data.pop(KEY_HALF_DRAFT, None)
    await update.effective_message.reply_text(
        "📝 Halftime intake started. Paste the Telegram-ready halftime board, then send /halfdone when finished."
    )


@owner_only
async def halfdone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = context.user_data.get(KEY_HALF_DRAFT, "").strip()
    if not draft:
        await update.effective_message.reply_text("No halftime board draft is stored.")
        return

    preprocessed = preprocess_board_text(draft)
    title, sections = parse_named_sections(preprocessed, HALFTIME_HEADERS)
    if not title or not sections:
        await update.effective_message.reply_text(
            "❌ Could not parse the halftime board. Check that the title line and halftime section headers are intact."
        )
        return

    context.application.bot_data[KEY_HALF_TITLE] = title
    context.application.bot_data[KEY_HALF_SECTIONS] = sections
    context.application.bot_data[KEY_HALF_TEXT] = build_full_board(title, sections, HALFTIME_HEADERS)

    context.user_data.pop(MODE_HALF, None)
    context.user_data.pop(KEY_HALF_DRAFT, None)

    await update.effective_message.reply_text(
        "✅ Halftime board stored privately. Nothing has been posted to the channel.\n\n"
        "Use /push_halftime when you're ready.",
        reply_markup=build_halftime_menu(),
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
    await update.effective_message.reply_text("✅ Halftime selector ready.", reply_markup=build_halftime_menu())


@owner_only
async def halfview_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_HALF_TEXT, "")
    if not text:
        await update.effective_message.reply_text("No halftime board is stored.")
        return
    await reply_long(update.effective_message, text, keyboard=build_halftime_menu())


async def show_halftime_section(update: Update, context: ContextTypes.DEFAULT_TYPE, header: str):
    title = context.application.bot_data.get(KEY_HALF_TITLE, "")
    sections = context.application.bot_data.get(KEY_HALF_SECTIONS, {})
    block = sections.get(header)
    if not title or not block:
        await update.effective_message.reply_text(f"No stored halftime section found for {header}.")
        return
    await reply_long(update.effective_message, f"{title}\n\n{block}".strip(), keyboard=build_halftime_menu())


async def push_halftime_section(update: Update, context: ContextTypes.DEFAULT_TYPE, header: str):
    title = context.application.bot_data.get(KEY_HALF_TITLE, "")
    sections = context.application.bot_data.get(KEY_HALF_SECTIONS, {})
    block = sections.get(header)
    if not title or not block:
        await update.effective_message.reply_text(f"No stored halftime section found for {header}.")
        return
    await push_to_channel(context, f"{title}\n\n{block}".strip())
    await update.effective_message.reply_text(f"✅ {header} pushed to channel.")


@owner_only
async def push_halftime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_HALF_TEXT, "")
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
    sections = parse_winner_sections(text)

    context.application.bot_data[KEY_WIN_TEXT] = clean_text(text)
    context.application.bot_data[KEY_WIN_SECTIONS] = sections

    context.user_data.pop(MODE_WIN, None)
    context.user_data.pop(KEY_WIN_DRAFT, None)

    await update.effective_message.reply_text(
        "✅ Winner Board stored privately. Nothing has been posted to the channel.\n\n"
        "Use /winmenu to review privately, then /push_winners when you're ready.",
        reply_markup=build_winner_menu(sections),
    )


@owner_only
async def wincancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(MODE_WIN, None)
    context.user_data.pop(KEY_WIN_DRAFT, None)
    await update.effective_message.reply_text("🗑️ Winner intake cancelled.")


@owner_only
async def winmenu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_WIN_TEXT, "")
    sections = context.application.bot_data.get(KEY_WIN_SECTIONS, {})
    if not text:
        await update.effective_message.reply_text("No Winner Board is stored.")
        return
    await update.effective_message.reply_text("✅ Winner selector ready.", reply_markup=build_winner_menu(sections))


@owner_only
async def winfull_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_WIN_TEXT, "")
    sections = context.application.bot_data.get(KEY_WIN_SECTIONS, {})
    if not text:
        await update.effective_message.reply_text("No Winner Board is stored.")
        return
    await reply_long(update.effective_message, text, keyboard=build_winner_menu(sections))


@owner_only
async def push_winners_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_WIN_TEXT, "")
    sections = context.application.bot_data.get(KEY_WIN_SECTIONS, {})
    if not text:
        await update.effective_message.reply_text("No Winner Board is stored.")
        return
    grouped = get_all_cashed_today_text(sections, text)
    await push_to_channel(context, grouped)
    await update.effective_message.reply_text("✅ Winner recap pushed to channel.")


@owner_only
async def push_winfull_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_WIN_TEXT, "")
    if not text:
        await update.effective_message.reply_text("No Winner Board is stored.")
        return
    await push_to_channel(context, text)
    await update.effective_message.reply_text("✅ Full Winner Board pushed to channel.")


@owner_only
async def show_all_cashed_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.application.bot_data.get(KEY_WIN_TEXT, "")
    sections = context.application.bot_data.get(KEY_WIN_SECTIONS, {})
    if not text:
        await update.effective_message.reply_text("No Winner Board is stored.")
        return
    grouped = get_all_cashed_today_text(sections, text)
    await reply_long(update.effective_message, grouped, keyboard=build_winner_menu(sections))


@owner_only
async def show_straight_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sections = context.application.bot_data.get(KEY_WIN_SECTIONS, {})
    blocks = get_straight_winner_blocks(sections)
    if not blocks:
        await update.effective_message.reply_text("No straight winners are stored.")
        return
    await reply_long(update.effective_message, "\n\n".join(blocks), keyboard=build_winner_menu(sections))


@owner_only
async def show_road_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sections = context.application.bot_data.get(KEY_WIN_SECTIONS, {})
    blocks = get_road_winner_blocks(sections)
    if not blocks:
        await update.effective_message.reply_text("No road winners are stored.")
        return
    await reply_long(update.effective_message, "\n\n".join(blocks), keyboard=build_winner_menu(sections))


@owner_only
async def show_side_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sections = context.application.bot_data.get(KEY_WIN_SECTIONS, {})
    blocks = get_side_winner_blocks(sections)
    if not blocks:
        await update.effective_message.reply_text("No side ticket winners are stored.")
        return
    await reply_long(update.effective_message, "\n\n".join(blocks), keyboard=build_winner_menu(sections))


@owner_only
async def text_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.effective_message.text or ""

    if context.user_data.get(MODE_GAME):
        context.user_data[KEY_GAME_DRAFT] = text
        await update.effective_message.reply_text("✅ Game Selection draft received. Send /gamedone to store it.")
        return

    if context.user_data.get(MODE_SIDE):
        context.user_data[KEY_SIDE_DRAFT] = text
        await update.effective_message.reply_text("✅ Side board draft received. Send /sidedone to store it.")
        return

    if context.user_data.get(MODE_BOARD):
        context.user_data[KEY_BOARD_DRAFT] = text
        await update.effective_message.reply_text("✅ Pregame board draft received. Send /done to store it.")
        return

    if context.user_data.get(MODE_HALF):
        context.user_data[KEY_HALF_DRAFT] = text
        await update.effective_message.reply_text("✅ Halftime board draft received. Send /halfdone to store it.")
        return

    if context.user_data.get(MODE_WIN):
        context.user_data[KEY_WIN_DRAFT] = text
        await update.effective_message.reply_text("✅ Winner Board draft received. Send /windone to store it.")
        return

    pregame_button_map = {
        "Today's Selections": "Today's Selections",
        "Straight Bets": "Straight Bets Board",
        "Road to $25": "Road to $25",
        "Road to $50": "Road to $50",
        "Profit Boost": "Profit Boost Ticket",
        "+MoneyBet": "+MoneyBet Ticket",
        "Magician": "Magician Ticket",
        "SGP": "SGP Ticket",
    }

    if text in pregame_button_map:
        await show_pregame_section(update, context, pregame_button_map[text])
        return

    if text == "Show Prop Side Tickets":
        await show_grouped_pregame(update, context, PROP_SIDE_HEADERS)
        return

    if text == "Show Full Board":
        await full_cmd(update, context)
        return

    if text == "Refresh Menu":
        await menu_cmd(update, context)
        return

    side_button_map = {
        "Game Line Ticket": "Game Line Ticket",
        "Money Line Ticket": "Money Line Ticket",
    }

    if text in side_button_map:
        await show_side_section(update, context, side_button_map[text])
        return

    if text == "Show Full Side Board":
        await sideview_cmd(update, context)
        return

    if text == "Refresh Side Menu":
        await sidemenu_cmd(update, context)
        return

    halftime_button_map = {
        "Live Profit Boost": "Live Profit Boost Ticket",
        "Live +MoneyBet": "Live +MoneyBet Ticket",
        "Live SGP": "Live SGP Ticket",
    }

    if text in halftime_button_map:
        await show_halftime_section(update, context, halftime_button_map[text])
        return

    if text == "Show Full Halftime":
        await halfview_cmd(update, context)
        return

    if text == "Refresh Halftime Menu":
        await halfmenu_cmd(update, context)
        return

    if text == "All Cashed Today":
        await show_all_cashed_today(update, context)
        return

    if text == "Straight Winners":
        await show_straight_winners(update, context)
        return

    if text == "Road Winners":
        await show_road_winners(update, context)
        return

    if text == "Side Ticket Winners":
        await show_side_winners(update, context)
        return

    if text == "Full Winner Board":
        await winfull_cmd(update, context)
        return

    if text == "Push Winners":
        await push_winners_cmd(update, context)
        return

    if text == "Push Full Winner Board":
        await push_winfull_cmd(update, context)
        return

    if text == "Refresh Winner Menu":
        await winmenu_cmd(update, context)
        return



def make_show_pregame_callback(header: str):
    @owner_only
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if header == "__PROP_SIDES__":
            await show_grouped_pregame(update, context, PROP_SIDE_HEADERS)
        else:
            await show_pregame_section(update, context, header)
    return _callback



def make_show_side_callback(header: str):
    @owner_only
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await show_side_section(update, context, header)
    return _callback



def make_show_halftime_callback(header: str):
    @owner_only
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await show_halftime_section(update, context, header)
    return _callback



def make_push_pregame_callback(header: str):
    @owner_only
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await push_pregame_section(update, context, header)
    return _callback



def make_push_halftime_callback(header: str):
    @owner_only
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await push_halftime_section(update, context, header)
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

    app.add_handler(CommandHandler("sidepost", sidepost_cmd))
    app.add_handler(CommandHandler("sidedone", sidedone_cmd))
    app.add_handler(CommandHandler("sidecancel", sidecancel_cmd))
    app.add_handler(CommandHandler("sidemenu", sidemenu_cmd))
    app.add_handler(CommandHandler("sideview", sideview_cmd))
    for cmd, header in SIDE_VIEW_COMMAND_MAP.items():
        app.add_handler(CommandHandler(cmd, make_show_side_callback(header)))
    app.add_handler(CommandHandler("push_lines", push_lines_cmd))

    app.add_handler(CommandHandler("post", post_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("full", full_cmd))
    for cmd, header in PREGAME_VIEW_COMMAND_MAP.items():
        app.add_handler(CommandHandler(cmd, make_show_pregame_callback(header)))

    app.add_handler(CommandHandler("push_loading", push_loading_cmd))
    app.add_handler(CommandHandler("push_preview", push_preview_cmd))
    app.add_handler(CommandHandler("push_today", make_push_pregame_callback("Today's Selections")))
    app.add_handler(CommandHandler("push_straight", make_push_pregame_callback("Straight Bets Board")))
    app.add_handler(CommandHandler("push_road25", make_push_pregame_callback("Road to $25")))
    app.add_handler(CommandHandler("push_road50", make_push_pregame_callback("Road to $50")))
    app.add_handler(CommandHandler("push_sides", push_sides_cmd))
    app.add_handler(CommandHandler("push_disclaimer", push_disclaimer_cmd))
    app.add_handler(CommandHandler("push_full", push_full_cmd))
    app.add_handler(CommandHandler("push_live", push_live_cmd))

    app.add_handler(CommandHandler("halfpost", halfpost_cmd))
    app.add_handler(CommandHandler("halfdone", halfdone_cmd))
    app.add_handler(CommandHandler("halfcancel", halfcancel_cmd))
    app.add_handler(CommandHandler("halfmenu", halfmenu_cmd))
    app.add_handler(CommandHandler("halfview", halfview_cmd))
    for cmd, header in HALFTIME_VIEW_COMMAND_MAP.items():
        app.add_handler(CommandHandler(cmd, make_show_halftime_callback(header)))
        app.add_handler(CommandHandler(f"push_{cmd}", make_push_halftime_callback(header)))
    app.add_handler(CommandHandler("push_halftime", push_halftime_cmd))

    app.add_handler(CommandHandler("winpost", winpost_cmd))
    app.add_handler(CommandHandler("windone", windone_cmd))
    app.add_handler(CommandHandler("wincancel", wincancel_cmd))
    app.add_handler(CommandHandler("winmenu", winmenu_cmd))
    app.add_handler(CommandHandler("winfull", winfull_cmd))
    app.add_handler(CommandHandler("push_winners", push_winners_cmd))
    app.add_handler(CommandHandler("push_winfull", push_winfull_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_capture))
    return app


if __name__ == "__main__":
    application = build_application()
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
        )
    else:
        application.run_polling()
