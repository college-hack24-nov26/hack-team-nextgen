"""Marathi / English alert messages + Telegram sender."""
import os

import requests

CROP_MR = {"sugarcane": "ऊस", "soybean": "सोयाबीन", "onion": "कांदा",
           "wheat": "गहू", "jowar": "ज्वारी", "cotton": "कापूस"}


def mr_digits(s):
    return str(s).translate(str.maketrans("0123456789", "०१२३४५६७८९"))


def _round_l(n):
    return f"{int(round(n, -2)):,}"


def message(f, lang="mr"):
    r = f["reco"]
    a, name = r["action"], f["name"]
    crop = CROP_MR.get(f["crop"], f["crop"]) if lang == "mr" else f["crop"]
    if lang == "mr":
        if a == "IRRIGATE_NOW":
            m = f"💧 {name} ({crop}): आज {mr_digits(r['minutes'])} मिनिटे पाणी द्या (सुमारे {mr_digits(_round_l(r['litres']))} लिटर)."
        elif a == "IRRIGATE_IN_2_DAYS":
            m = f"🟡 {name} ({crop}): २ दिवसांत पाणी द्यावे लागेल."
        elif a == "WAIT":
            m = f"🔵 {name} ({crop}): पावसाची शक्यता आहे ({mr_digits(round(r['rain48']))} मिमी). आज पाणी देऊ नका."
        elif a == "NOT_SOWN":
            m = f"⚪ {name} ({crop}): पेरणी अजून झालेली नाही."
        elif a == "SEASON_OVER":
            m = f"⚪ {name} ({crop}): पिकाचा हंगाम संपला आहे."
        else:
            m = f"🟢 {name} ({crop}): आज पाण्याची गरज नाही."
        return m
    if a == "IRRIGATE_NOW":
        return f"💧 {name} ({crop}): irrigate today for {r['minutes']} min (about {_round_l(r['litres'])} L)."
    if a == "IRRIGATE_IN_2_DAYS":
        return f"🟡 {name} ({crop}): irrigation needed within 2 days."
    if a == "WAIT":
        return f"🔵 {name} ({crop}): rain expected ({round(r['rain48'])} mm). Do not irrigate today."
    if a in ("NOT_SOWN", "SEASON_OVER"):
        return f"⚪ {name} ({crop}): {'not sown yet' if a == 'NOT_SOWN' else 'season over'}."
    return f"🟢 {name} ({crop}): no irrigation needed today."


def summary(ranked_fields, lang="mr"):
    head = "🌾 JalRakshak AI — आजचे पाणी नियोजन" if lang == "mr" else "🌾 JalRakshak AI — today's water plan"
    lines = [message(f, lang) for f in ranked_fields]
    return "\n".join([head, *lines])


def send_telegram(text, token=None, chat_id=None):
    """Returns (ok, info). Token/chat id come from args or TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID."""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "Telegram token / chat id not set"
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat_id, "text": text}, timeout=10)
        return r.ok, ("sent" if r.ok else r.text)
    except Exception as e:  # network errors
        return False, str(e)
