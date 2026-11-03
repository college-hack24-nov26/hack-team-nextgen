# 💧 JalRakshak AI — the water-saving brain for farmers

Tells a farmer **when** to irrigate, **how much** water (litres + pump minutes) and **which field first**,
in Marathi or English. Built on the FAO-56 water-balance method with live weather from Open-Meteo.

## Run it (5 minutes)
```bash
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m unittest -v                               # engine tests
streamlit run app.py
```
Click **डेमो शेते भरा / Load demo fields** in the sidebar. No internet? Tick **Offline demo weather**.

## Files
| File | Job |
|---|---|
| `engine.py` | Kc curve, soil-water bucket, decision, amount, priority score, savings replay, weather + cache + offline fallback |
| `allocator.py` | Limited-water mode (split a litre budget by priority) |
| `alerts.py` | Marathi/English messages + Telegram sender |
| `app.py` | Streamlit UI (plan, charts, savings, alerts, voice) |
| `test_engine.py` | Unit tests |

## Telegram alerts
1. @BotFather → `/newbot` → copy token. Message your bot once, open `https://api.telegram.org/bot<TOKEN>/getUpdates` for `chat_id`.
2. Locally: `export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...`
   On Streamlit Cloud: *App settings → Secrets*:
   ```toml
   TELEGRAM_BOT_TOKEN = "123:abc"
   TELEGRAM_CHAT_ID = "123456789"
   ```

## Deploy
Push to GitHub → share.streamlit.io → pick repo, `app.py` → add secrets → open link on phone.

## How the decision works
- `ETc = ET0 × Kc` (Kc rises/falls through growth stages)
- `TAW = 1000 × (FC−WP) × root depth`, `RAW = p × TAW`
- Depletion is replayed day by day from the last irrigation date using real past rain and ET0
- Irrigate when depletion ≥ trigger (RAW × 0.6 drip / 0.85 sprinkler / 1.0 flood — tunable assumption)
- Forecast ≥10 mm in 48 h at ≥60% probability and irrigation due → **WAIT**
- Litres = depletion ÷ efficiency (drip 0.90, sprinkler 0.75, flood 0.60) × area
- Priority = 55% stress + 25% growth-stage sensitivity + 20% crop value
- A sensor/manual soil-deficit reading overrides the modelled depletion

## Honest limitations (say these to the judges)
- Advisory only; Kc, root depth and soil values are approximate FAO-56 / typical figures, not field-calibrated.
- Weather replay covers 30 days; if the last irrigation was older, depletion is under-estimated.
- "Water saved" is an estimate against an editable habit baseline, not a measured result.
- Offline demo weather is synthetic and for demos only.
- Marathi voice depends on the phone having an `mr-IN` voice.

## 5-minute demo script
1. Load demo fields → show ranked plan (sugarcane/soybean/onion).
2. Enter budget 100000 L → limited-water allocation.
3. Tick **Simulate heavy rain** → advice flips to 🔵 WAIT, shows litres saved (say clearly it is a simulation).
4. Alerts tab → send Marathi Telegram message → press 🔊.
5. Savings tab → estimated saving vs habit.
