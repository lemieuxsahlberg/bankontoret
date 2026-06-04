import streamlit as st
import pandas as pd
from datetime import date
from db import get_supabase

st.set_page_config(page_title="Bankontoret", page_icon="🏌️", layout="wide")
supabase = get_supabase()

SURFACE_OPTIONS = ["eterniitti", "betoni", "huopa", "MOS"]
PAR_BY_SURFACE = {"eterniitti": 18, "betoni": 27, "huopa": 36, "MOS": 36}
MAX_HOLES_PER_COURSE = 18


def init_state():
    defaults = {
        "access_token": None,
        "refresh_token": None,
        "user": None,
        "current_round_id": None,
        "current_course_id": None,
        "current_holes": [],
        "current_hole_pos": 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def restore_auth_session():
    if st.session_state.access_token and st.session_state.refresh_token:
        try:
            supabase.auth.set_session(st.session_state.access_token, st.session_state.refresh_token)
            u = supabase.auth.get_user()
            st.session_state.user = u.user if u else None
        except Exception:
            st.session_state.access_token = None
            st.session_state.refresh_token = None
            st.session_state.user = None


def save_auth_session(auth_response):
    session = getattr(auth_response, "session", None)
    user = getattr(auth_response, "user", None)
    if session:
        st.session_state.access_token = session.access_token
        st.session_state.refresh_token = session.refresh_token
    st.session_state.user = user


def clear_round_state():
    st.session_state.current_round_id = None
    st.session_state.current_course_id = None
    st.session_state.current_holes = []
    st.session_state.current_hole_pos = 0


def current_user_id():
    return st.session_state.user.id if st.session_state.user else None


def ensure_profile_exists(user_id, display_name):
    rows = supabase.table("profiles").select("user_id, display_name").eq("user_id", user_id).execute().data or []
    if not rows:
        supabase.table("profiles").insert({"user_id": user_id, "display_name": display_name or "Pelaaja"}).execute()


def get_all_courses():
    try:
        return supabase.table("courses").select("*").order("name").execute().data or []
    except Exception:
        return []


def get_course_holes(course_id):
    return supabase.table("course_holes").select("*").eq("course_id", course_id).order("hole_number").execute().data or []


def get_rounds(user_id):
    return supabase.table("rounds").select("*").eq("user_id", user_id).order("played_at", desc=True).execute().data or []


def get_round_holes(round_id):
    return supabase.table("round_holes").select("*").eq("round_id", round_id).order("hole_sequence_number").execute().data or []


def get_result_band(surface, total_score):
    if not surface or total_score is None:
        return ("Tuntematon", "#6b7280")
    if surface == "eterniitti":
        if 18 <= total_score <= 20: return ("Sininen", "#2563eb")
        if 21 <= total_score <= 24: return ("Vihreä", "#16a34a")
        if 25 <= total_score <= 29: return ("Punainen", "#dc2626")
        if total_score > 29: return ("Musta", "#111827")
    if surface == "betoni":
        if 18 <= total_score <= 27: return ("Sininen", "#2563eb")
        if 28 <= total_score <= 30: return ("Vihreä", "#16a34a")
        if 31 <= total_score <= 35: return ("Punainen", "#dc2626")
        if total_score > 35: return ("Musta", "#111827")
    if surface in ["huopa", "MOS"]:
        if 18 <= total_score <= 29: return ("Sininen", "#2563eb")
        if 30 <= total_score <= 35: return ("Vihreä", "#16a34a")
        if 36 <= total_score <= 39: return ("Punainen", "#dc2626")
        if total_score > 39: return ("Musta", "#111827")
    return ("Alle rajan", "#6b7280")


def render_band_badge(surface, total_score):
    label, color = get_result_band(surface, total_score)
    st.markdown(f"<div style='display:inline-block;padding:0.35rem 0.7rem;border-radius:999px;background:{color};color:white;font-weight:600'>{label}</div>", unsafe_allow_html=True)


def auth_view():
    st.title("🏌️ Bankontoret")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Kirjaudu")
        with st.form("login"):
            email = st.text_input("Sähköposti")
            password = st.text_input("Salasana", type="password")
            if st.form_submit_button("Kirjaudu"):
                try:
                    r = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    save_auth_session(r)
                    ensure_profile_exists(current_user_id(), email.split("@")[0])
                    st.rerun()
                except Exception as e:
                    st.error(f"Kirjautuminen epäonnistui: {e}")
    with c2:
        st.subheader("Luo käyttäjä")
        with st.form("signup"):
            name = st.text_input("Näyttönimi")
            email = st.text_input("Sähköposti", key="se")
            password = st.text_input("Salasana", type="password", key="sp")
            if st.form_submit_button("Luo käyttäjä"):
                try:
                    supabase.auth.sign_up({"email": email, "password": password, "options": {"data": {"display_name": name}}})
                    st.success("Käyttäjä luotu. Kirjaudu sisään vasemmalta.")
                except Exception as e:
                    st.error(f"Käyttäjän luonti epäonnistui: {e}")


def render_courses(user_id):
    st.subheader("Kentät")
    all_courses = get_all_courses()
    with st.form("new_course", clear_on_submit=True):
        course_name = st.text_input("Kentän nimi")
        location = st.text_input("Sijainti (valinnainen)")
        surface = st.selectbox("Alusta", SURFACE_OPTIONS)
        if st.form_submit_button("Tallenna kenttä"):
            if not course_name.strip():
                st.error("Anna kentälle nimi.")
            elif any((c.get("name") or "").strip().lower() == course_name.strip().lower() for c in all_courses):
                st.warning("Kenttä löytyy jo. Käytä olemassa olevaa kenttää listalta.")
            else:
                try:
                    supabase.table("courses").insert({"name": course_name.strip(), "location": location.strip() or None, "surface": surface, "owner_user_id": user_id}).execute()
                    st.success("Kenttä tallennettu.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Kentän tallennus epäonnistui: {e}")

    if not all_courses:
        st.info("Ei vielä kenttiä.")
        return
    course_map = {f'{c["name"]} ({c.get("surface") or "ei alustaa"})': c for c in all_courses}
    selected = st.selectbox("Valitse kenttä ratojen hallintaan", list(course_map.keys()))
    course = course_map[selected]
    holes = get_course_holes(course["id"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Alusta", course.get("surface") or "–")
    c2.metric("Par", PAR_BY_SURFACE.get(course.get("surface"), "–"))
    c3.metric("Sijainti", course.get("location") or "–")
    c4.metric("Ratoja", f"{len(holes)}/18")

    if holes:
        st.dataframe(pd.DataFrame([{"#": h["hole_number"], "Nimi": h.get("hole_name") or "", "Tyyppi": "Päättyvä" if h.get("is_ending_hole") else "Kenttärata", "Esteellinen": "Kyllä" if h.get("has_obstacle") else "Ei"} for h in holes]), use_container_width=True, hide_index=True)

    if len(holes) >= 18:
        st.success("Tällä kentällä on 18/18 rataa.")
        return
    next_no = len(holes) + 1
    with st.form("new_hole", clear_on_submit=True):
        st.text_input("Radan numero", value=str(next_no), disabled=True)
        hole_name = st.text_input("Radan nimi (valinnainen)")
        hole_type = st.radio("Ratatyyppi", ["Päättyvä rata", "Kenttärata"], horizontal=True)
        has_obstacle = st.checkbox("Esteellinen")
        if st.form_submit_button(f"Tallenna rata {next_no}/18"):
            try:
                supabase.table("course_holes").insert({"course_id": course["id"], "hole_number": next_no, "hole_name": hole_name.strip() or None, "is_ending_hole": hole_type == "Päättyvä rata", "is_lane_hole": hole_type == "Kenttärata", "has_obstacle": bool(has_obstacle)}).execute()
                st.success(f"Rata {next_no}/18 tallennettu.")
                st.rerun()
            except Exception as e:
                st.error(f"Radan tallennus epäonnistui: {e}")


def render_new_round(user_id):
    st.subheader("Uusi kierros")
    courses = get_all_courses()
    if not courses:
        st.info("Luo ensin kenttä.")
        return
    course_map = {f'{c["name"]} ({c.get("surface") or "ei alustaa"})': c for c in courses}

    if st.session_state.current_round_id is None:
        with st.form("start_round"):
            label = st.selectbox("Kenttä", list(course_map.keys()))
            course = course_map[label]
            holes = get_course_holes(course["id"])
            played_at = st.date_input("Päivä", value=date.today())
            visibility = st.selectbox("Näkyvyys", ["private", "shared"])
            notes = st.text_area("Muistiinpanot (valinnainen)")
            can_start = len(holes) == 18
            if not can_start:
                st.warning(f"Tällä kentällä on {len(holes)}/18 rataa.")
            if st.form_submit_button("Aloita kierros", disabled=not can_start):
                try:
                    r = supabase.table("rounds").insert({"user_id": user_id, "course_id": course["id"], "played_at": played_at.isoformat(), "visibility": visibility, "notes": notes.strip() or None}).execute()
                    st.session_state.current_round_id = r.data[0]["id"]
                    st.session_state.current_course_id = course["id"]
                    st.session_state.current_holes = holes
                    st.session_state.current_hole_pos = 0
                    st.rerun()
                except Exception as e:
                    st.error(f"Kierroksen aloitus epäonnistui: {e}")
        return

    holes = st.session_state.current_holes
    pos = st.session_state.current_hole_pos
    if pos >= len(holes):
        course = next((c for c in courses if c["id"] == st.session_state.current_course_id), None)
        rhs = get_round_holes(st.session_state.current_round_id)
        total_score = sum(r.get("total_strokes", 0) for r in rhs)
        st.success("Kierros valmis 🎉")
        c1, c2, c3 = st.columns(3)
        c1.metric("Tulos", total_score)
        c2.metric("Alusta", course.get("surface") if course else "–")
        c3.metric("Par", PAR_BY_SURFACE.get((course or {}).get("surface"), "–"))
        render_band_badge((course or {}).get("surface"), total_score)
        if st.button("Päätä kierros"):
            clear_round_state()
            st.rerun()
        return

    hole = holes[pos]
    hole_id = hole["id"]
    st.markdown(f"### Rata {hole['hole_number']}")
    if hole.get("hole_name"):
        st.caption(hole["hole_name"])

    strokes = st.segmented_control("Lyönnit", options=list(range(1, 8)), selection_mode="single", default=1, key=f"strokes_{hole_id}")
    if strokes is None:
        strokes = 1
    notes = st.text_input("Muistiinpanot radasta (valinnainen)", key=f"notes_{hole_id}")

    shot_rows = []
    if int(strokes) > 1:
        st.markdown("### Lyöntikortit")
        for i in range(1, int(strokes) + 1):
            st.markdown(f"**Lyönti {i}**")
            c1, c2, c3 = st.columns(3)
            with c1:
                went_in = st.checkbox("Sisään", value=(i == int(strokes)), key=f"in_{hole_id}_{i}")
            with c2:
                went_through = st.checkbox("Läpi", key=f"through_{hole_id}_{i}") if hole.get("is_lane_hole") else False
            with c3:
                hit_obstacle = st.checkbox("Este", key=f"obst_{hole_id}_{i}") if hole.get("has_obstacle") else False
            c4, c5 = st.columns(2)
            with c4:
                direction_error = st.radio("Suunta", ["none", "left", "right"], horizontal=True, key=f"dir_{hole_id}_{i}", format_func=lambda x: {"none":"ei","left":"vasen","right":"oikea"}[x])
            with c5:
                speed_error = st.radio("Vauhti", ["none", "too_slow", "too_hard"], horizontal=True, key=f"spd_{hole_id}_{i}", format_func=lambda x: {"none":"ei","too_slow":"hidas","too_hard":"liian luja"}[x])
            shot_rows.append({"shot_number": i, "went_in": bool(went_in), "went_through": bool(went_through), "hit_obstacle": bool(hit_obstacle), "direction_error": direction_error, "speed_error": speed_error})
            st.divider()

    col_a, col_b = st.columns(2)
    if col_b.button("Peruuta tämän radan tiedot"):
        st.rerun()
    if col_a.button("Tallenna rata", type="primary"):
        try:
            rh = supabase.table("round_holes").insert({"round_id": st.session_state.current_round_id, "course_hole_id": hole_id, "hole_sequence_number": hole["hole_number"], "total_strokes": int(strokes), "went_straight_in": int(strokes) == 1, "notes": notes.strip() or None}).execute()
            rh_id = rh.data[0]["id"]
            if int(strokes) == 1:
                supabase.table("shots").insert({"round_hole_id": rh_id, "shot_number": 1, "went_in": True, "went_through": False, "hit_obstacle": False, "direction_error": "none", "speed_error": "none"}).execute()
            else:
                if shot_rows and not shot_rows[-1]["went_in"]:
                    shot_rows[-1]["went_in"] = True
                payload = []
                for row in shot_rows:
                    row = row.copy()
                    row["round_hole_id"] = rh_id
                    payload.append(row)
                supabase.table("shots").insert(payload).execute()
            st.session_state.current_hole_pos += 1
            st.rerun()
        except Exception as e:
            st.error(f"Radan tallennus epäonnistui: {e}")


def render_history(user_id):
    st.subheader("Historia")
    rounds = get_rounds(user_id)
    courses = {c["id"]: c for c in get_all_courses()}
    if not rounds:
        st.info("Ei vielä tallennettuja kierroksia.")
        return
    rows = []
    for rnd in rounds:
        rhs = get_round_holes(rnd["id"])
        course = courses.get(rnd["course_id"], {})
        total = sum(r.get("total_strokes", 0) for r in rhs)
        rows.append({"Päivä": rnd.get("played_at"), "Kenttä": course.get("name", "Tuntematon"), "Alusta": course.get("surface") or "–", "Par": PAR_BY_SURFACE.get(course.get("surface"), "–"), "Ratoja": len(rhs), "Lyönnit yhteensä": total, "Väri": get_result_band(course.get("surface"), total)[0], "Muistiinpanot": rnd.get("notes") or ""})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_analysis(user_id):
    st.subheader("Analyysi")
    metrics = calculate_metrics(user_id)
    if not metrics:
        st.info("Analyysi näkyy, kun olet tallentanut ainakin yhden kierroksen.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Piikki %", f"{metrics['piikki']} %" if metrics['piikki'] is not None else "–")
    c2.metric("Instant recover %", f"{metrics['instant_recover']} %" if metrics['instant_recover'] is not None else "–")
    c3.metric("Attempts (avg)", str(metrics['attempts_avg']) if metrics['attempts_avg'] is not None else "–")
    c4.metric("Pitkät sarjat %", f"{metrics['pitkat_sarjat']} %" if metrics['pitkat_sarjat'] is not None else "–")


def main_view():
    user_id = current_user_id()
    profile = get_profile(user_id)
    st.title("🏌️ Bankontoret")
    st.caption(f"Kirjautunut: {(profile or {}).get('display_name') or 'Pelaaja'}")
    with st.sidebar:
        st.markdown("### Kenttäsäännöt")
        st.markdown("- Eterniitti → par 18"
- Betoni → par 27
- Huopa / MOS → par 36
- Jokaisella kentällä täytyy olla tasan 18 rataa")
        if st.button("Kirjaudu ulos"):
            try: supabase.auth.sign_out()
            except Exception: pass
            st.session_state.access_token = None
            st.session_state.refresh_token = None
            st.session_state.user = None
            clear_round_state()
            st.rerun()
    t1, t2, t3, t4 = st.tabs(["Kentät", "Uusi kierros", "Historia", "Analyysi"])
    with t1: render_courses(user_id)
    with t2: render_new_round(user_id)
    with t3: render_history(user_id)
    with t4: render_analysis(user_id)


init_state()
restore_auth_session()
if current_user_id() is None:
    auth_view()
else:
    main_view()
