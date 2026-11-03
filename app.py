"""JalRakshak AI - Streamlit web app.  Run: streamlit run app.py"""
import json
import time
from datetime import timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from jalrakshak import alerts, allocator, engine, i18n, savings, storage, weather
from jalrakshak.crops import CROPS, EFFICIENCY, SOILS
from jalrakshak.timeutil import today_ist

st.set_page_config(page_title="JalRakshak AI", page_icon="💧", layout="wide")
storage.init()

# ---------------------------------------------------------------- language
st.session_state.setdefault("lang", "mr")
lang = st.sidebar.radio("भाषा / Language", ["mr", "en"], key="lang", horizontal=True,
                        format_func=lambda x: "मराठी" if x == "mr" else "English")


def T(key, **kw):
    return i18n.t(lang, key, **kw)


# ---------------------------------------------------------------- auth
def auth_gate():
    if st.session_state.get("user"):
        return st.session_state["user"]
    st.title("💧 " + T("app_title"))
    st.caption(T("tagline"))
    tab_login, tab_reg = st.tabs([T("login"), T("register")])
    with tab_login:
        with st.form("login_form"):
            u = st.text_input(T("username"))
            p = st.text_input(T("password"), type="password")
            if st.form_submit_button(T("login")):
                fails = st.session_state.get("fails", 0)
                time.sleep(min(fails, 5))                      # slow down brute force
                user = storage.verify_user(u.strip(), p)
                if user:
                    st.session_state.update(user=user, fails=0)
                    st.rerun()
                st.session_state["fails"] = fails + 1
                st.error(T("bad_login"))
    with tab_reg:
        with st.form("register_form"):
            u2 = st.text_input(T("username"), key="reg_u")
            p2 = st.text_input(T("password"), type="password", key="reg_p")
            if st.form_submit_button(T("create_account")):
                ok, err = storage.create_user(u2.strip(), p2)
                st.success(T("account_created")) if ok else st.error(T(err))
    st.stop()


user = auth_gate()
st.sidebar.write(T("welcome", name=user["username"]))
if st.sidebar.button(T("logout")):
    st.session_state.pop("user", None)
    st.rerun()

# ---------------------------------------------------------------- sidebar: add field
today = today_ist()
with st.sidebar.expander("➕ " + T("add_field"), expanded=not storage.list_fields(user["id"])):
    with st.form("add_field", clear_on_submit=False):
        name = st.text_input(T("field_name"), "Plot 1", max_chars=60)
        crop = st.selectbox(T("crop"), list(CROPS), format_func=lambda k: i18n.label(lang, "crops", k))
        sow = st.date_input(T("sowing"), today - timedelta(days=30), max_value=today)
        area = st.number_input(T("area"), 0.05, 500.0, 1.0, step=0.5)
        soil = st.selectbox(T("soil"), list(SOILS), format_func=lambda k: i18n.label(lang, "soils", k))
        irr = st.selectbox(T("irrigation"), list(EFFICIENCY), format_func=lambda k: i18n.label(lang, "irrs", k))
        flow = st.number_input(T("flow"), 5.0, 5000.0, 100.0, step=10.0)
        last = st.date_input(T("last_irr"), today - timedelta(days=5), max_value=today)
        lat = st.number_input(T("lat"), value=17.98, format="%.4f")   # Phaltan default
        lon = st.number_input(T("lon"), value=74.43, format="%.4f")
        if st.form_submit_button(T("add")):
            try:
                storage.add_field(user["id"], dict(
                    name=name, crop=crop, sowing_date=str(sow), area_acre=area, soil=soil,
                    irrigation=irr, flow_lpm=flow, lat=lat, lon=lon, last_irrigation=str(last)))
                st.rerun()
            except ValueError as e:
                st.error(str(e))

if st.sidebar.button("🧪 " + T("demo")):
    demos = [
        ("Sugarcane plot", "sugarcane", 150, "sandy", "drip", 2.0, 17),
        ("Onion plot", "onion", 45, "loam", "sprinkler", 1.0, 9),
        ("Wheat plot", "wheat", 12, "black", "flood", 1.5, 3),
    ]
    for n, c, age, s, i, a, ago in demos:
        storage.add_field(user["id"], dict(
            name=n, crop=c, soil=s, irrigation=i, area_acre=a, flow_lpm=100, lat=17.98, lon=74.43,
            sowing_date=(today - timedelta(days=age)).isoformat(),
            last_irrigation=(today - timedelta(days=ago)).isoformat()))
    st.rerun()

simulate = st.sidebar.toggle(T("sim_rain"))

with st.sidebar.expander("📲 " + T("contact")):
    phone = st.text_input(T("phone"), user.get("phone") or "")
    chat_id = st.text_input(T("chat_id"), user.get("telegram_chat_id") or "")
    if st.button(T("save")):
        try:
            storage.update_contact(user["id"], phone, chat_id)
            st.session_state["user"] = storage.get_user(user["id"])
            st.success(T("saved_ok"))
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------- main
st.title("💧 " + T("app_title"))
st.caption(T("tagline"))

rows = storage.list_fields(user["id"])
if not rows:
    st.info(T("no_fields"))
    st.stop()

for f in rows:
    wx = weather.fetch(f["lat"], f["lon"])
    if simulate:
        wx = weather.with_simulated_rain(wx)
    f["wx"], f["reco"] = wx, engine.recommend(f, wx)
ranked = engine.priority(rows)

src = rows[0]["wx"]["source"]
if src.startswith("synthetic"):
    st.warning(T("wx_synthetic"))
elif src.startswith("stale"):
    st.warning(T("wx_stale"))

ICON = {"IRRIGATE_NOW": "🔴", "IRRIGATE_IN_2_DAYS": "🟡", "NO_NEED": "🟢", "WAIT": "🔵"}
st.subheader(T("plan_title"))
for rank, f in enumerate(ranked, 1):
    r = f["reco"]
    with st.container(border=True):
        st.markdown(f"### {rank}. {ICON[r['action']]} {f['name']} · {i18n.label(lang, 'crops', f['crop'])}")
        c1, c2, c3 = st.columns(3)
        c1.metric("➡", i18n.action_label(lang, r["action"]))
        mins = max(1, round(r["litres"] / f["flow_lpm"])) if r["litres"] else 0
        c2.metric(T("water"), f"{r['litres']:,} L", f"{mins} {T('min')}" if mins else None, delta_color="off")
        c3.metric(T("stress"), r["stress_ratio"])
        st.write(i18n.reason(lang, r))
        with st.expander(T("details")):
            st.write(f"Day after sowing: {r['das']} ({r['stage']}) · ETc today: {r['etc_today_mm']} {T('mm_per_day')}")
            st.write(f"Depletion {r['depletion_mm']} mm · RAW {r['raw_mm']} mm · TAW {r['taw_mm']} mm · "
                     f"Gross water {r['gross_mm']} mm · Rain 48h {r['rain48_mm']} mm ({r['rain_prob']}%)")
            st.caption(f"Priority score {f['score']} · weather: {r['weather_source']}")
        b1, b2, _ = st.columns([1, 1, 4])
        if b1.button("💧 " + T("irrigated_today"), key=f"irr{f['id']}"):
            storage.set_last_irrigation(user["id"], f["id"], today.isoformat())
            st.rerun()
        if b2.button("🗑 " + T("delete"), key=f"del{f['id']}"):
            storage.delete_field(user["id"], f["id"])
            st.rerun()

# ---- limited water
st.subheader(T("alloc_title"))
budget = st.number_input(T("budget"), 0, 100_000_000, 0, step=5000)
if budget > 0:
    plan, left = allocator.allocate(ranked, budget)
    st.dataframe(pd.DataFrame([{T("field"): p["name"], T("needed"): f"{p['needed']:,}",
                                T("litres_given"): f"{p['given']:,}", T("status"): T(p["status"])}
                               for p in plan]), hide_index=True, use_container_width=True)
    st.write(T("left", n=f"{left:,}"))

# ---- savings
st.subheader(T("savings_title"))
st.caption(T("savings_note"))
s1, s2, s3 = st.columns(3)
habit_days = s1.number_input(T("habit_every"), 2, 30, 7)
habit_mm = s2.number_input(T("habit_mm"), 5.0, 200.0, 50.0)
cost = s3.number_input(T("cost_kl"), 0.0, 1000.0, 0.0)
tot = {"saved_litres": 0, "habit_litres": 0, "smart_litres": 0, "saved_rupees": 0.0}
for f in ranked:
    est = savings.estimate(f, f["wx"], habit_days, habit_mm, cost)
    for k in tot:
        tot[k] += est[k]
pct = round(100 * tot["saved_litres"] / tot["habit_litres"]) if tot["habit_litres"] else 0
m1, m2, m3 = st.columns(3)
m1.metric(T("habit"), f"{tot['habit_litres']:,} L")
m2.metric(T("smart"), f"{tot['smart_litres']:,} L")
m3.metric(T("saved"), f"{tot['saved_litres']:,} L", f"{pct}%" + (f" · ₹{tot['saved_rupees']:,}" if cost else ""))

# ---- chart for first field
f0 = ranked[0]
cutoff_a, cutoff_b = (today - timedelta(days=14)).isoformat(), (today + timedelta(days=5)).isoformat()
df = pd.DataFrame([d for d in f0["wx"]["days"] if cutoff_a <= d["date"] <= cutoff_b])
if not df.empty:
    st.subheader(T("chart_title"))
    df = df.rename(columns={"et0": "ET0 (evaporation)", "rain": "Rain"}).set_index("date")
    st.bar_chart(df[["ET0 (evaporation)", "Rain"]])

# ---- alerts + voice
st.subheader(T("alerts_title"))
messages = [i18n.alert_message(lang, f) for f in ranked]
st.text("\n".join(messages))
a1, a2 = st.columns([1, 3])
if a1.button("📲 " + T("send_alert")):
    ok, errs = alerts.send_all(user, "\n".join(messages))
    if ok:
        st.success(T("sent", ch=", ".join(ok)))
    elif not errs:
        st.warning(T("no_channel"))
    for e in errs:
        st.error(e)

speech = json.dumps(" ".join(messages)).replace("</", "<\\/")
components.html(f"""
<button id="b" style="font-size:18px;padding:10px 18px;border-radius:8px;border:1px solid #888;cursor:pointer">
🔊 {T('speak')}</button>
<script>
document.getElementById('b').addEventListener('click', function() {{
  var u = new SpeechSynthesisUtterance({speech});
  u.lang = {json.dumps('mr-IN' if lang == 'mr' else 'en-IN')};
  window.speechSynthesis.cancel(); window.speechSynthesis.speak(u);
}});
</script>""", height=70)

st.caption(T("disclaimer"))
