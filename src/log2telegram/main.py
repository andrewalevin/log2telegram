import asyncio
import os
import pathlib
import signal
import sys
import socket
import logging
import re
from enum import Enum
from string import Template
from telegram import Bot

from log2telegram.cron import run_periodically


BOT_TOKEN = os.getenv('L2T_BOT_TOKEN', '')
CHAT_ID = os.getenv('L2T_CHAT_ID', '')
NOTIFICATION_REFRESH_TIME_SEC = os.getenv('L2T_NOTIFICATION_REFRESH_TIME_SEC', 60 * 5)
DELAY_SEC = os.getenv('L2T_DELAY_SEC', 1)

TARGET_PATH = os.getenv('L2T_PATH', 'no-fil.log')

LOG_FORMAT_ORIGINAL = os.getenv('L2T_LOG_FORMAT_ORIGINAL', '')
LOG_FORMAT_REPRESENTATION = os.getenv('L2T_LOG_FORMAT_REPRESENTATION', '')

# "Remove ANSI color codes from lines before sending."
FILTER_ANSI_COLORS = os.getenv('L2T_FILTER_ANSI_COLORS', 'true').lower() == 'true'


TELEGRAM_MAX_TEXT_SIZE = 4096

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize the Telegram bot
if not BOT_TOKEN or not CHAT_ID:
    logger.error("🚫 LOG2TELEGRAM_BOT_TOKEN and LOG2TELEGRAM_CHAT_ID must be set in the .env file.")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)

# Welcome message template
WELCOME_TEXT_TEMPLATE = Template('''
<b>👋 Log2Telegram starting for:</b>

Host: ${hostname}
File: ${path}

Number lines: ${line_count}
Displaying the last ${number_last_lines} lines: 
...
...
${displayed_lines}

⬇️ Monitoring running: 
''')

MAX_TELEGRAM_MESSAGE_LEN = 4081  # Max message length for Telegram with buffer



class Status(Enum):
    NOT_INITIALIZED = "Not initialized"
    INITIALIZED = "Initialized"
    AVAILABLE = "Available"
    NOT_AVAILABLE = "Not available"
    UNREADABLE = "Unreadable"
    NOT_A_FILE = "Not a file"
    PATH_NOT_SET = "Path not set"


class StatusManager:
    STATUSES = [status.value for status in Status]  # Список всех статусов

    def __init__(self):
        self.status = Status.NOT_INITIALIZED
        self._path = None

    def initialize(self, path: pathlib.Path):
        """Инициализирует менеджер с переданным путем."""
        if not isinstance(path, pathlib.Path):
            raise ValueError("Path must be a pathlib.Path object.")
        self._path = path
        self.status = Status.INITIALIZED

    def check_status(self):
        """
        Проверяет статус файла:
        - AVAILABLE: если файл существует и доступен для чтения.
        - NOT_AVAILABLE: если файл не существует.
        - UNREADABLE: если файл существует, но недоступен для чтения.
        - NOT_A_FILE: если путь не является файлом.
        - PATH_NOT_SET: если путь не установлен.
        """
        if self.status == Status.NOT_INITIALIZED:
            return self.status

        if self._path is None:
            self.status = Status.PATH_NOT_SET
        elif not self._path.exists():
            self.status = Status.NOT_AVAILABLE
        elif not self._path.is_file():
            self.status = Status.NOT_A_FILE
        elif not os.access(self._path, os.R_OK):
            self.status = Status.UNREADABLE
        else:
            self.status = Status.AVAILABLE

        return self.status


    @classmethod
    def get_all_statuses(cls):
        """Возвращает список всех возможных статусов."""
        return cls.STATUSES


async def get_hostname() -> str:
    """Retrieve the hostname of the current machine."""
    try:
        hostname = socket.gethostname()
    except Exception as e:
        logger.error(f"Error retrieving hostname: {e}")
        hostname = "unknown_host"
    return hostname


async def send_message(text: str):
    """Send a message to the specified Telegram chat."""
    await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='HTML')


def get_formatted_lines(lines: list) -> str:
    """Format lines for better display in Telegram messages."""
    f_lines = ['...', '...'] + lines[-3:]

    f_lines = [f"║ {line.strip()}" for line in f_lines] + ['╚' + '═' * 24]
    f_lines = [line[:20] for line in f_lines]
    return '\n'.join(f_lines)


def get_formatted_lines2(lines: list[str], number_last_lines : int = 3) -> str:
    short_lines = lines[-number_last_lines:] if len(lines) > number_last_lines else lines

    _MAX_LINE_LEN = 64
    return '\n'.join(
        f'{line[:_MAX_LINE_LEN]} ...' if len(line) > _MAX_LINE_LEN else line
        for line in short_lines
    )



async def send_welcome(path: pathlib.Path, lines: list):
    """Send an initial welcome message when monitoring starts."""
    _NUMBER_LAST_LINES_DISPLAY = 3
    welcome_text = WELCOME_TEXT_TEMPLATE.substitute(
        hostname=await get_hostname(),
        path=path.resolve().as_posix(),
        line_count=len(lines),
        number_last_lines=_NUMBER_LAST_LINES_DISPLAY,
        displayed_lines=get_formatted_lines2(lines, _NUMBER_LAST_LINES_DISPLAY))
    await send_message(welcome_text)

def get_file_modified_time(path: pathlib.Path) -> float:
    """Return the last modified timestamp of the file or 0 if unavailable."""
    if not path.exists():
        return 0
    try:
        return path.stat().st_mtime
    except Exception as e:
        logger.error(f"Unable to retrieve modified time for file '{path}': {e}")
        return 0


def get_file_size(path: pathlib.Path) -> int:
    """
    Return the size of the file in bytes or 0 if unavailable.

    Args:
        path (pathlib.Path): The path to the file.

    Returns:
        int: The size of the file in bytes, or 0 if the file does not exist or cannot be accessed.
    """
    if not path.exists():
        return 0
    try:
        return path.stat().st_size
    except Exception as e:
        logger.error(f"Unable to retrieve size for file '{path}': {e}")
        return 0

def filter_color_codes(line: str) -> str:
    """Remove ANSI color codes from a line."""
    ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', line)


def filter_timestamps(line: str) -> str:
    """Remove timestamps at the start of the line in various formats."""
    # This regex matches:
    # - "HH:MM", "HH:MM:SS", "HH:MM:SS,SSS"
    # - "YYYY-MM-DD HH:MM:SS", "YYYY-MM-DD HH:MM:SS,SSS"
    return re.sub(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d{3})?|\d{1,2}:\d{2}(?::\d{2})?(?:,\d{3})?\s*',
                  '', line)


async def read_first_line_from_position(path: pathlib.Path, position: int = 0) -> str:
    """
    Read the first new line from the file starting from a specified position.

    Args:
        path (pathlib.Path): The path to the file.
        position (int): The position to start reading from (default is 0).

    Returns:
        tuple[str, int]: A tuple containing the first line read and the new file position.
                        Returns an empty string and -1 in case of an error.
    """
    if not path.is_file() or not os.access(path, os.R_OK):
        logger.error(f"File '{path}' cannot be read. Check permissions.")
        return ""
    try:
        with path.open('r') as file:
            file.seek(position)
            line = file.readline()
    except Exception as e:
        logger.error(f"Error reading file '{path}': {e}")
        return ""

    return line.strip()


async def read_file_from_position(path: pathlib.Path, position: int = 0):
    """Read new lines from the file starting from a specified position."""
    if not path.is_file() or not os.access(path, os.R_OK):
        logger.error(f"File '{path}' cannot be read. Check permissions.")
        return [], -1  # Return -1 to indicate a read error

    try:
        with path.open('r') as file:
            file.seek(position)
            lines = file.readlines()
            new_position = file.tell()
    except Exception as e:
        logger.error(f"Error reading file '{path}': {e}")
        return [], -1  # Return -1 on read error
    return lines, new_position


def format_representation(text_log: str, format_log_original: str, format_log_representation: str) -> str:

    placeholders = re.compile(r"(%\((\w+)\)[a-z])").findall(format_log_original)
    if not placeholders:
        return text_log

    _SPECIAL_VAR = '!!!!!!!!'
    regex_pattern = format_log_original
    for item in placeholders:
        regex_pattern = regex_pattern.replace(item[0], _SPECIAL_VAR)

    regex_pattern = re.escape(regex_pattern).replace(_SPECIAL_VAR, '(.*)')

    match = re.findall(regex_pattern, text_log)
    if not match:
        return  text_log

    result_log = format_log_representation
    for idx, content in enumerate(list(match[0])):
        result_log = result_log.replace(placeholders[idx][0], content)

    return result_log

async def send_lines(lines: list):
    """Send lines to Telegram, trimming if the message exceeds the maximum allowed length."""
    if FILTER_ANSI_COLORS:
        lines = [filter_color_codes(line) for line in lines]

    if LOG_FORMAT_ORIGINAL and LOG_FORMAT_REPRESENTATION:
        lines = [format_representation(line, LOG_FORMAT_ORIGINAL, LOG_FORMAT_REPRESENTATION)  for line in lines]

    lines = [line.lstrip(" -") for line in lines]

    message = '\n'.join(lines)
    if len(message) > MAX_TELEGRAM_MESSAGE_LEN:
        message = message[:MAX_TELEGRAM_MESSAGE_LEN] + '\n...\n⚔️ Message trimmed'

    try:
        await send_message(message)
    except Exception as e:
        logger.error(f'🔴 Error Sending: \n\n{e}\n\n')



monitoring = StatusManager()

# Enhanced function
async def monitor_file(path: pathlib.Path, seconds_delay: int):
    """Monitor a file for changes, sending new content to Telegram."""
    await asyncio.sleep(2)

    monitoring.initialize(path)
    logger.info("Monitoring initialized.")

    # Read the initial content
    lines, position = await read_file_from_position(path)
    if position == -1:
        logger.error("Failed to read the file initially. Exiting monitoring.")
        return

    await send_welcome(path, lines)

    last_modified_time = get_file_modified_time(path)
    last_size = get_file_size(path)

    while True:
        await asyncio.sleep(seconds_delay)

        # Check if the file's modified time has changed
        if (current_modified_time := get_file_modified_time(path)) == last_modified_time:
            continue  # No changes detected
        last_modified_time = current_modified_time

        # Update position if the file size has decreased
        if (current_size := get_file_size(path)) < last_size:
            position = 0
        last_size = current_size

        lines, new_position = await read_file_from_position(path, position)
        if new_position == -1:
            continue
        position = max(position, new_position)

        if not lines:
            logger.info("No new lines to send.")
            continue

        await send_lines(lines)



async def check_status_and_send_notification(_params: dict):
    pass


def handle_suspend(_signal, _frame):
    """Handle the SIGTSTP signal (Ctrl+Z)."""
    logger.info("Process suspended. Exiting...")
    # No need to pause manually; the system handles the suspension
    sys.exit(0)


def handle_interrupt(_signal, _frame):
    """Handle the SIGINT signal (Ctrl+C)."""
    logger.info("Process interrupted by user. Exiting...")
    sys.exit(0)


async def run():
    signal.signal(signal.SIGTSTP, handle_suspend)
    signal.signal(signal.SIGINT, handle_interrupt)
    logger.info("Running ... Press Ctrl+C to stop or Ctrl+Z to suspend.")

    path = pathlib.Path(TARGET_PATH)
    if not path.exists():
        logger.error(f"🚫 The file '{path}' does not exist.")
        sys.exit(1)
    if not os.access(path, os.R_OK):
        logger.error(f"🚫 The file '{path}' is not readable. Check permissions.")
        sys.exit(1)

    delay = max(1, DELAY_SEC) if DELAY_SEC else 1

    logger.info(f'Start monitoring for: {path} with delay: {delay}')

    await asyncio.gather(
        monitor_file(path, delay),
        run_periodically(10, check_status_and_send_notification, {}))


def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
