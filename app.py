#!/usr/bin/env python3
"""
Denní topic sender:
- zavolá OpenAI (chat completions) s českým promptem
- pošle výsledek do Telegram chatu
- uloží historii do SQLite (topics.db)
"""

import os
import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
import requests

# ----- CONFIG (z prostředí) -----
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")  # nebo jiný model
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")  # číslo nebo @username (doporučeno chat id číslo)
# volitelné
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "600"))
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.4"))
DB_PATH = os.environ.get("DB_PATH", "topics.db")
SEND_AS_MARKDOWN = os.environ.get("SEND_AS_MARKDOWN", "1") == "1"

if not (OPENAI_API_KEY and TG_BOT_TOKEN and TG_CHAT_ID):
    raise SystemExit("Chybí env proměnné. Nastav OPENAI_API_KEY, TG_BOT_TOKEN, TG_CHAT_ID.")

# ----- PROMPT (česky). Upravit podle chuti. -----
PROMPT = """
Jsi učitel, který každý den navrhne jedno praktické téma k samostudiu. Výstup dej v češtině přesně v tomto formátu:

Téma: <název>
Kategorie: <např. historie, programování, jazyky, věda>
Úroveň: <začátečník | středně | pokročilý>
Cíl učení (1 věta): <konkrétní měřitelný cíl>
10–30s shrnutí (co to je):
3 nápady, jak se tomu učit dnes (konkrétní činnosti, s časy):
Rychlé zdroje (1–3 odkazy nebo názvy knih / videí):
Následující krok na zítra (jedna věc):
Krátká motivační věta (max 20 slov).

Vygeneruj jedno originální téma — buď konkrétní a praktický. Nepiš nic jiného než výstup v přesném tvaru.
"""

# ----- OpenAI call (Chat Completions) -----
def call_openai(prompt: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    # bezpečné načtení textu
    content = ""
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        content = json.dumps(data, ensure_ascii=False, indent=2)
    return content.strip()

# ----- SQLite logging -----
def init_db(path: str = DB_PATH):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_utc TEXT,
            content TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_topic(content: str, path: str = DB_PATH):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("INSERT INTO topics (created_utc, content) VALUES (?, ?)",
                (datetime.utcnow().isoformat(), content))
    conn.commit()
    conn.close()

# ----- Telegram send -----
def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        # parse_mode = MarkdownV2 or HTML if you want formatting
    }
    if SEND_AS_MARKDOWN:
        payload["parse_mode"] = "Markdown"
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()

# ----- Helper: shorten long text to Telegram limit -----
def ensure_telegram_length(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    # zkrátit hezky na odstavci
    cut = text[:limit-200]
    last_newline = cut.rfind("\n")
    if last_newline > 0:
        cut = cut[:last_newline]
    return cut + "\n\n*(zkráceno — otevři úplnou historii v DB)*"

# ----- Main -----
def main():
    init_db()
    try:
        topic = call_openai(PROMPT)
    except Exception as e:
        print("Chyba při volání OpenAI:", str(e))
        raise

    # uložíme do DB
    save_topic(topic)

    # připravíme zprávu pro Telegram
    header = f"📚 Denní téma — {datetime.now(timezone.utc).astimezone(tz=timezone(timedelta(hours=1))).strftime('%Y-%m-%d %H:%M %Z')}\n\n"
    msg = header + topic
    msg = ensure_telegram_length(msg)
    # pokud používáme Markdown, musíme escapovat některé znaky — jednoduché řešení: poslat bez Markdownu nebo použít HTML
    if SEND_AS_MARKDOWN:
        # jednoduché escapování pro Markdown (hlavně projekty s _ * ` [ ])
        esc = msg.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")
        msg_to_send = esc
    else:
        msg_to_send = msg

    send_telegram(msg_to_send)
    print("Topic úspěšně poslány a uloženy.")

if __name__ == "__main__":
    main()
