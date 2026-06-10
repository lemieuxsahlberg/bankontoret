
import streamlit as st
import pandas as pd
from datetime import date, datetime
from db import get_supabase

st.set_page_config(page_title="Bankontoret", layout="wide")
supabase = get_supabase()

SURFACE_OPTIONS = ["eterniitti", "betoni", "huopa", "MOS"]
PAR_BY_SURFACE = {"eterniitti": 18, "betoni": 27, "huopa": 36, "MOS": 36}
ROUND_TYPE_OPTIONS = ["harjoitus", "kisa"]
ROUND_STATUS_OPTIONS = ["completed", "draft", "abandoned"]
ADMIN_EMAIL = "gretasofiaisabella@gmail.com"
MAX_HOLES = 18

STATUS_LABELS = {
    "completed": "valmis",
    "draft": "kesken",
    "abandoned": "hylätty",
}
STATUS_LABEL_TO_VALUE = {v: k for k, v in STATUS_LABELS.items()}


def apply_custom_css():
    st.markdown(
        """
        <style>
            .block-container {padding-top: 1rem; padding-bottom: 2rem; max-width: 1100px;}
            div[data-testid="stMetric"] {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                padding: .65rem .85rem;
            }
            #MainMenu {visibility: hidden;}
            header[data-testid="stHeader"] {visibility: hidden; height: 0;}
            [data-testid="stToolbar"] {display: none !important;}
            [data-testid="stDecoration"] {display: none !important;}
            footer {visibility: hidden;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def safe_data(resp):
    return getattr(resp, "data", None) or []


def ui_error(message, err):
    st.error(f"{message} {err}")


def to_date(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except Exception:
        return None


def title_block(title, subtitle=None):
    st.subheader(title)
    if subtitle:
        st.caption(subtitle)


def format_status(value):
    return STATUS_LABELS.get(value, value)


def band_for_score(surface, total_score):
    if not surface or total_score is None:
        return ("Tuntematon", "#6b7280")
    if surface == "eterniitti":
        if 18 <= total_score <= 20:
            return ("Sininen", "#2563eb")
        if 21 <= total_score <= 24:
            return ("Vihreä", "#16a34a")
        if 25 <= total_score <= 29:
            return ("Punainen", "#dc2626")
        if total_score > 29:
            return ("Musta", "#111827")
    if surface == "betoni":
        if 18 <= total_score <= 27:
            return ("Sininen", "#2563eb")
        if 28 <= total_score <= 30:
            return ("Vihreä", "#16a34a")
        if 31 <= total_score <= 35:
            return ("Punainen", "#dc2626")
        if total_score > 35:
            return ("Musta", "#111827")
    if surface in ["huopa", "MOS"]:
        if 18 <= total_score <= 29:
            return ("Sininen", "#2563eb")
        if 30 <= total_score <= 35:
            return ("Vihreä", "#16a34a")
        if 36 <= total_score <= 39:
            return ("Punainen", "#dc2626")
        if total_score > 39:
            return ("Musta", "#111827")
    return ("Alle rajan", "#6b7280")


def render_band_badge(surface, total_score):
    label, color = band_for_score(surface, total_score)
    st.markdown(
        f"<span style='display:inline-block;padding:.35rem .7rem;border-radius:999px;background:{color};color:#fff;font-weight:600'>{label}</span>",
        unsafe_allow_html=True,
    )


# -----------------------------
# Auth & session
# -----------------------------
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
            user_resp = supabase.auth.get_user()
            st.session_state.user = user_resp.user if user_resp else None
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


def current_user_id():
    return st.session_state.user.id if st.session_state.user else None


def current_user_email():
    return getattr(st.session_state.user, "email", None) if st.session_state.user else None


def clear_round_state():
    st.session_state.current_round_id = None
    st.session_state.current_course_id = None
    st.session_state.current_holes = []
    st.session_state.current_hole_pos = 0


def is_admin():
    email = current_user_email()
    return bool(email and email.strip().lower() == ADMIN_EMAIL.strip().lower())


def send_password_reset(email: str):
    email = (email or "").strip()
    if not email:
        raise ValueError("Anna sähköpostiosoite.")
    auth_obj = supabase.auth
    if hasattr(auth_obj, "reset_password_for_email"):
        return auth_obj.reset_password_for_email(email)
    if hasattr(auth_obj, "reset_password_email"):
        return auth_obj.reset_password_email(email)
    raise AttributeError("Salasanan palautusmetodia ei löytynyt Supabase-kirjastosta.")


# -----------------------------
# Profiilit
# -----------------------------
def ensure_profile_exists(user_id, display_name):
    rows = safe_data(supabase.table("profiles").select("user_id, display_name").eq("user_id", user_id).execute())
    wanted = (display_name or "Pelaaja").strip() or "Pelaaja"
    if not rows:
        supabase.table("profiles").insert({"user_id": user_id, "display_name": wanted}).execute()
    elif rows[0].get("display_name") != wanted:
        supabase.table("profiles").update({"display_name": wanted}).eq("user_id", user_id).execute()


def get_profile(user_id):
    rows = safe_data(supabase.table("profiles").select("*").eq("user_id", user_id).execute())
    return rows[0] if rows else None


def update_profile_name(user_id, display_name):
    value = (display_name or "").strip()
    if not value:
        raise ValueError("Anna näkyvä nimi.")
    existing = get_profile(user_id)
    if existing:
        supabase.table("profiles").update({"display_name": value}).eq("user_id", user_id).execute()
    else:
        supabase.table("profiles").insert({"user_id": user_id, "display_name": value}).execute()


def get_display_name(user_id):
    profile = get_profile(user_id)
    if profile and profile.get("display_name"):
        return profile["display_name"]
    return "Pelaaja"


# -----------------------------
# Kentät
# -----------------------------
def get_all_courses():
    try:
        return safe_data(supabase.table("courses").select("*").order("name").execute())
    except Exception:
        return []


def get_course(course_id):
    rows = safe_data(supabase.table("courses").select("*").eq("id", course_id).execute())
    return rows[0] if rows else None


def get_course_holes(course_id):
    return safe_data(supabase.table("course_holes").select("*").eq("course_id", course_id).order("hole_number").execute())


def can_edit_course(course):
    return bool(course and (is_admin() or course.get("owner_user_id") == current_user_id()))


def update_course(course_id, name, location, surface):
    supabase.table("courses").update({
        "name": name.strip(),
        "location": location.strip() or None,
        "surface": surface,
    }).eq("id", course_id).execute()


def update_course_hole(hole_id, hole_number, hole_name, is_ending_hole, has_obstacle):
    supabase.table("course_holes").update({
        "hole_number": int(hole_number),
        "hole_name": hole_name.strip() or None,
        "is_ending_hole": bool(is_ending_hole),
        "is_lane_hole": not bool(is_ending_hole),
        "has_obstacle": bool(has_obstacle),
    }).eq("id", hole_id).execute()


def replace_hole_order(edited_rows):
    nums = [int(r["hole_number"]) for r in edited_rows]
    if sorted(nums) != list(range(1, len(nums) + 1)):
        raise ValueError("Ratanumeroiden pitää olla ilman duplikaatteja järjestyksessä 1..n.")
    for row in edited_rows:
        update_course_hole(row["id"], row["hole_number"], row["hole_name"], row["is_ending_hole"], row["has_obstacle"])


def delete_course(course_id):
    supabase.table("course_holes").delete().eq("course_id", course_id).execute()
    supabase.table("courses").delete().eq("id", course_id).execute()


# -----------------------------
# Kierrokset
# -----------------------------
def get_rounds(user_id):
    return safe_data(supabase.table("rounds").select("*").eq("user_id", user_id).order("played_at", desc=True).execute())


def get_round(round_id):
    rows = safe_data(supabase.table("rounds").select("*").eq("id", round_id).execute())
    return rows[0] if rows else None


def get_round_holes(round_id):
    return safe_data(supabase.table("round_holes").select("*").eq("round_id", round_id).order("hole_sequence_number").execute())


def get_round_hole_by_sequence(round_id, seq):
    rows = safe_data(supabase.table("round_holes").select("*").eq("round_id", round_id).eq("hole_sequence_number", seq).execute())
    return rows[0] if rows else None


def get_shots(round_hole_id):
    return safe_data(supabase.table("shots").select("*").eq("round_hole_id", round_hole_id).order("shot_number").execute())


def update_round_status(round_id, status_value):
    supabase.table("rounds").update({"status": status_value}).eq("id", round_id).execute()


def update_round_meta(round_id, round_type, notes, status_value=None):
    payload = {"round_type": round_type, "notes": notes.strip() or None}
    if status_value is not None:
        payload["status"] = status_value
    supabase.table("rounds").update(payload).eq("id", round_id).execute()


def delete_round(round_id):
    rhs = get_round_holes(round_id)
    for rh in rhs:
        supabase.table("shots").delete().eq("round_hole_id", rh["id"]).execute()
    supabase.table("round_holes").delete().eq("round_id", round_id).execute()
    supabase.table("rounds").delete().eq("id", round_id).execute()


def upsert_round_hole(round_id, hole, total_strokes, notes, shot_rows):
    existing = get_round_hole_by_sequence(round_id, hole["hole_number"])
    payload = {
        "round_id": round_id,
        "course_hole_id": hole["id"],
        "hole_sequence_number": hole["hole_number"],
        "total_strokes": int(total_strokes),
        "went_straight_in": int(total_strokes) == 1,
        "notes": notes.strip() or None,
    }
    if existing:
        rh_id = existing["id"]
        supabase.table("round_holes").update(payload).eq("id", rh_id).execute()
        supabase.table("shots").delete().eq("round_hole_id", rh_id).execute()
    else:
        res = supabase.table("round_holes").insert(payload).execute()
        rh_id = res.data[0]["id"]

    if int(total_strokes) == 1:
        supabase.table("shots").insert({
            "round_hole_id": rh_id,
            "shot_number": 1,
            "went_in": True,
            "went_through": False,
            "hit_obstacle": False,
            "direction_error": "none",
            "speed_error": "none",
        }).execute()
    else:
        rows = []
        for row in shot_rows:
            item = row.copy()
            item["round_hole_id"] = rh_id
            rows.append(item)
        if rows:
            if not rows[-1]["went_in"]:
                rows[-1]["went_in"] = True
            supabase.table("shots").insert(rows).execute()


def load_round_into_state(round_row):
    holes = get_course_holes(round_row["course_id"])
    saved = get_round_holes(round_row["id"])
    st.session_state.current_round_id = round_row["id"]
    st.session_state.current_course_id = round_row["course_id"]
    st.session_state.current_holes = holes
    st.session_state.current_hole_pos = min(len(saved), len(holes))


# -----------------------------
# Analyysi / historia
# -----------------------------
def get_course_hole_averages(user_id, course_id):
    rounds = safe_data(supabase.table("rounds").select("id").eq("user_id", user_id).eq("course_id", course_id).eq("status", "completed").execute())
    if not rounds:
        return []
    all_rhs = []
    for rnd in rounds:
        all_rhs.extend(get_round_holes(rnd["id"]))
    if not all_rhs:
        return []
    hole_map = {h["id"]: h["hole_number"] for h in get_course_holes(course_id)}
    rows = [{"Rata": hole_map.get(rh["course_hole_id"], rh.get("hole_sequence_number")), "Lyönnit": rh.get("total_strokes", 0)} for rh in all_rhs]
    df = pd.DataFrame(rows)
    grouped = df.groupby("Rata", as_index=False)["Lyönnit"].mean().sort_values("Rata")
    grouped["Lyönnit"] = grouped["Lyönnit"].round(2)
    return grouped.to_dict("records")


def filter_rounds_for_stats(rounds, surface_filter, date_from, date_to, type_filter):
    courses = {c["id"]: c for c in get_all_courses()}
    filtered = []
    for rnd in rounds:
        if rnd.get("status") != "completed":
            continue
        if type_filter != "kaikki" and rnd.get("round_type", "harjoitus") != type_filter:
            continue
        played_date = to_date(rnd.get("played_at"))
        if date_from and played_date and played_date < date_from:
            continue
        if date_to and played_date and played_date > date_to:
            continue
        course = courses.get(rnd["course_id"])
        if surface_filter != "kaikki" and course and course.get("surface") != surface_filter:
            continue
        filtered.append((rnd, course))
    return filtered


def get_analysis_metrics(user_id, surface_filter="kaikki", date_from=None, date_to=None, type_filter="kaikki"):
    rounds = get_rounds(user_id)
    rounds_with_course = filter_rounds_for_stats(rounds, surface_filter, date_from, date_to, type_filter)
    if not rounds_with_course:
        return None
    all_rhs = []
    ending_attempts = []
    direction_counts = {"left": 0, "right": 0}
    speed_counts = {"too_slow": 0, "too_hard": 0}
    eterniitti_scores = []
    for rnd, course in rounds_with_course:
        rhs = get_round_holes(rnd["id"])
        for rh in rhs:
            all_rhs.append(rh)
            for shot in get_shots(rh["id"]):
                if shot.get("direction_error") == "left":
                    direction_counts["left"] += 1
                elif shot.get("direction_error") == "right":
                    direction_counts["right"] += 1
                if shot.get("speed_error") == "too_slow":
                    speed_counts["too_slow"] += 1
                elif shot.get("speed_error") == "too_hard":
                    speed_counts["too_hard"] += 1
            ch = safe_data(supabase.table("course_holes").select("is_ending_hole").eq("id", rh["course_hole_id"]).execute())
            if ch and ch[0].get("is_ending_hole"):
                ending_attempts.append(rh.get("total_strokes", 0))
            if course and course.get("surface") == "eterniitti":
                score = rh.get("total_strokes", 0)
                if 1 <= score <= 7:
                    eterniitti_scores.append(score)
    metrics = {
        "piikki": round(pd.Series([1 if rh.get("went_straight_in") else 0 for rh in all_rhs]).mean() * 100, 1),
        "attempts_avg": round(pd.Series(ending_attempts).mean(), 2) if ending_attempts else None,
        "pitkat": round((pd.Series(ending_attempts) >= 4).mean() * 100, 1) if ending_attempts else None,
        "left_count": direction_counts["left"],
        "right_count": direction_counts["right"],
        "slow_count": speed_counts["too_slow"],
        "hard_count": speed_counts["too_hard"],
        "eterniitti": None,
    }
    if eterniitti_scores:
        total = len(eterniitti_scores)
        piikit = sum(1 for s in eterniitti_scores if s == 1)
        twos = sum(1 for s in eterniitti_scores if s == 2)
        bads = sum(1 for s in eterniitti_scores if 3 <= s <= 7)
        non_piikki = [s for s in eterniitti_scores if s > 1]
        rescued = sum(1 for s in non_piikki if s == 2)
        continues = sum(1 for s in non_piikki if 3 <= s <= 7)
        non_total = len(non_piikki)
        metrics["eterniitti"] = {
            "piikki_pct": round((piikit / total) * 100, 1),
            "kakkonen_pct": round((twos / total) * 100, 1),
            "three_to_seven_pct": round((bads / total) * 100, 1),
            "pelastettu_kakkoseen_pct": round((rescued / non_total) * 100, 1) if non_total else None,
            "jatkuu_huono_pct": round((continues / non_total) * 100, 1) if non_total else None,
        }
    return metrics


# -----------------------------
# UI views
# -----------------------------
def render_sidebar(user_id):
    with st.sidebar:
        st.markdown("### Tilanne")
        if st.button("Kirjaudu ulos"):
            try:
                supabase.auth.sign_out()
            except Exception:
                pass
            st.session_state.access_token = None
            st.session_state.refresh_token = None
            st.session_state.user = None
            clear_round_state()
            st.rerun()
        rounds = get_rounds(user_id)
        st.metric("Valmiit kierrokset", len([r for r in rounds if r.get("status") == "completed"]))
        st.metric("Keskeneräiset", len([r for r in rounds if r.get("status") == "draft"]))


def render_dashboard(user_id):
    title_block("Tervetuloa", "Huom: joukkueet on poistettu tästä vakaasta versiosta, jotta kierrossyöttö toimii varmasti.")
    rounds = get_rounds(user_id)
    courses = get_all_courses()
    c1, c2, c3 = st.columns(3)
    c1.metric("Kentät", len(courses))
    c2.metric("Valmiit kierrokset", len([r for r in rounds if r.get("status") == "completed"]))
    c3.metric("Keskeneräiset kierrokset", len([r for r in rounds if r.get("status") == "draft"]))
    st.info("Aloita näin: 1) lisää tai tarkista kenttä 2) aloita kierros 3) tallenna keskeneräinen tarvittaessa 4) katso historia ja analyysi.")


def auth_view():
    st.title("Bankontoret")
    st.caption("Kirjaudu tai luo käyttäjä. Jos sähköpostivahvistus ei toimi, korjaa Supabasen Auth asetusten Site URL / Redirect URL.")
    col1, col2 = st.columns(2)
    with col1:
        title_block("Kirjaudu")
        with st.form("login"):
            email = st.text_input("Sähköposti")
            password = st.text_input("Salasana", type="password")
            if st.form_submit_button("Kirjaudu"):
                try:
                    response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    save_auth_session(response)
                    ensure_profile_exists(current_user_id(), email.split("@")[0])
                    st.rerun()
                except Exception as e:
                    ui_error("Kirjautuminen epäonnistui.", e)
    with col2:
        title_block("Luo käyttäjä")
        with st.form("signup"):
            name = st.text_input("Näyttönimi")
            email = st.text_input("Sähköposti", key="signup_email")
            password = st.text_input("Salasana", type="password", key="signup_password")
            if st.form_submit_button("Luo käyttäjä"):
                try:
                    supabase.auth.sign_up({"email": email, "password": password, "options": {"data": {"display_name": name}}})
                    st.success("Käyttäjä luotu. Jos vahvistuslinkki ei toimi, korjaa se Supabasessa ennen käyttöönottoa.")
                except Exception as e:
                    ui_error("Käyttäjän luonti epäonnistui.", e)
        with st.expander("Unohtuiko salasana?"):
            with st.form("reset_password_form"):
                reset_email = st.text_input("Sähköposti salasanan palautusta varten", key="reset_email")
                if st.form_submit_button("Lähetä palautuslinkki"):
                    try:
                        send_password_reset(reset_email)
                        st.success("Jos sähköposti löytyy järjestelmästä, palautuslinkki on lähetetty.")
                    except Exception as e:
                        ui_error("Salasanan palautus ei onnistunut.", e)


def render_courses(user_id):
    title_block("Kentät", "Kaikki kirjautuneet näkevät samat kentät. Kentän omistaja tai pääkäyttäjä voi muokata ja poistaa kentän.")
    all_courses = get_all_courses()
    with st.expander("Luo uusi kenttä"):
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
                        ui_error("Kentän tallennus epäonnistui.", e)
    if not all_courses:
        st.info("Ei vielä kenttiä.")
        return
    course_map = {f"{c['name']} ({c.get('surface') or 'ei alustaa'})": c for c in all_courses}
    selected_label = st.selectbox("Valitse kenttä", list(course_map.keys()))
    course = course_map[selected_label]
    holes = get_course_holes(course["id"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Alusta", course.get("surface") or "–")
    c2.metric("Par", PAR_BY_SURFACE.get(course.get("surface"), "–"))
    c3.metric("Sijainti", course.get("location") or "–")
    c4.metric("Ratoja", f"{len(holes)}/18")
    if holes:
        st.dataframe(pd.DataFrame([{"#": h["hole_number"], "Nimi": h.get("hole_name") or "", "Tyyppi": "Päättyvä" if h.get("is_ending_hole") else "Kenttärata", "Esteellinen": "Kyllä" if h.get("has_obstacle") else "Ei"} for h in holes]), use_container_width=True, hide_index=True)
    else:
        st.info("Kentällä ei ole vielä ratoja.")

    if len(holes) < MAX_HOLES:
        with st.expander("Lisää uusi rata"):
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
                        ui_error("Radan tallennus epäonnistui.", e)

    if can_edit_course(course):
        st.markdown("### Muokkaa / poista kenttä")
        with st.expander("Muokkaa tätä kenttää"):
            with st.form(f"edit_course_{course['id']}"):
                new_name = st.text_input("Kentän nimi", value=course.get("name") or "")
                new_location = st.text_input("Sijainti", value=course.get("location") or "")
                new_surface = st.selectbox("Alusta", SURFACE_OPTIONS, index=SURFACE_OPTIONS.index(course.get("surface")) if course.get("surface") in SURFACE_OPTIONS else 0)
                edited = []
                for hole in holes:
                    st.markdown(f"**Nykyinen rata {hole['hole_number']}**")
                    ec1, ec2, ec3 = st.columns(3)
                    with ec1:
                        hole_number = st.number_input(f"Ratanumero #{hole['id']}", min_value=1, max_value=18, value=int(hole['hole_number']), step=1, key=f"edit_num_{hole['id']}")
                    with ec2:
                        hole_name = st.text_input(f"Radan nimi #{hole['id']}", value=hole.get("hole_name") or "", key=f"edit_name_{hole['id']}")
                    with ec3:
                        hole_type = st.radio(f"Ratatyyppi #{hole['id']}", ["Päättyvä rata", "Kenttärata"], horizontal=True, index=0 if hole.get("is_ending_hole") else 1, key=f"edit_type_{hole['id']}")
                    has_obstacle = st.checkbox(f"Esteellinen #{hole['id']}", value=bool(hole.get("has_obstacle")), key=f"edit_obs_{hole['id']}")
                    edited.append({"id": hole["id"], "hole_number": int(hole_number), "hole_name": hole_name, "is_ending_hole": hole_type == "Päättyvä rata", "has_obstacle": bool(has_obstacle)})
                    st.divider()
                if st.form_submit_button("Tallenna kentän muutokset"):
                    try:
                        update_course(course["id"], new_name, new_location, new_surface)
                        replace_hole_order(edited)
                        st.success("Kenttä päivitetty.")
                        st.rerun()
                    except Exception as e:
                        ui_error("Kentän päivitys epäonnistui.", e)
        st.markdown("### Poista tämä kenttä")
        confirm_delete_course = st.checkbox("Ymmärrän, että kentän poisto voi epäonnistua, jos kentällä on jo kierroksia.", key=f"confirm_delete_course_{course['id']}")
        if st.button("Poista tämä kenttä", type="secondary", disabled=not confirm_delete_course, key=f"delete_course_btn_{course['id']}"):
            try:
                delete_course(course["id"])
                st.success("Kenttä poistettu.")
                st.rerun()
            except Exception as e:
                ui_error("Kentän poisto epäonnistui. Todennäköinen syy: kenttään liittyy jo tallennettuja kierroksia.", e)


def render_draft_rounds(user_id):
    rounds = [r for r in get_rounds(user_id) if r.get("status") == "draft"]
    if not rounds:
        return
    courses = {c["id"]: c for c in get_all_courses()}
    title_block("Jatka keskeneräistä kierrosta")
    labels, label_to_round = [], {}
    for rnd in rounds:
        course = courses.get(rnd["course_id"], {})
        rhs = get_round_holes(rnd["id"])
        label = f"{rnd.get('played_at')} – {course.get('name', 'Tuntematon')} ({len(rhs)}/18)"
        labels.append(label)
        label_to_round[label] = rnd
    selected = st.selectbox("Valitse keskeneräinen kierros", labels)
    c1, c2 = st.columns(2)
    if c1.button("Jatka valittua kierrosta"):
        load_round_into_state(label_to_round[selected])
        st.rerun()
    if c2.button("Poista valittu keskeneräinen kierros"):
        try:
            delete_round(label_to_round[selected]["id"])
            st.success("Keskeneräinen kierros poistettu.")
            st.rerun()
        except Exception as e:
            ui_error("Kierroksen poisto epäonnistui.", e)


def render_current_round_controls(round_id):
    c1, c2 = st.columns(2)
    if c1.button("Tallenna kierros keskeneräisenä"):
        try:
            update_round_status(round_id, "draft")
            clear_round_state()
            st.success("Kierros tallennettu keskeneräisenä.")
            st.rerun()
        except Exception as e:
            ui_error("Kierroksen tallennus epäonnistui.", e)
    if c2.button("Poista tämä kierros", type="secondary"):
        try:
            delete_round(round_id)
            clear_round_state()
            st.success("Kierros poistettu.")
            st.rerun()
        except Exception as e:
            ui_error("Kierroksen poisto epäonnistui.", e)


def render_new_round(user_id):
    title_block("Kierros", "Aloita uusi kierros tai jatka keskeneräistä. Tämä vakaa versio ei käytä joukkueita, jotta syöttö toimii nopeasti.")
    courses = get_all_courses()
    if not courses:
        st.info("Luo ensin kenttä Kentät-välilehdellä.")
        return
    render_draft_rounds(user_id)
    st.divider()
    course_map = {f"{c['name']} ({c.get('surface') or 'ei alustaa'})": c for c in courses}
    if st.session_state.current_round_id is None:
        with st.form("start_round_form"):
            selected_label = st.selectbox("Kenttä", list(course_map.keys()))
            selected_course = course_map[selected_label]
            holes = get_course_holes(selected_course["id"])
            played_at = st.date_input("Päivä", value=date.today())
            round_type = st.selectbox("Kierroksen tyyppi", ROUND_TYPE_OPTIONS)
            notes = st.text_area("Muistiinpanot (valinnainen)")
            can_start = len(holes) == 18
            if not can_start:
                st.warning(f"Tällä kentällä on {len(holes)}/18 rataa.")
            if st.form_submit_button("Aloita kierros", disabled=not can_start):
                try:
                    payload = {"user_id": user_id, "course_id": selected_course["id"], "played_at": played_at.isoformat(), "visibility": "private", "notes": notes.strip() or None, "round_type": round_type, "status": "draft"}
                    result = supabase.table("rounds").insert(payload).execute()
                    st.session_state.current_round_id = result.data[0]["id"]
                    st.session_state.current_course_id = selected_course["id"]
                    st.session_state.current_holes = holes
                    st.session_state.current_hole_pos = 0
                    st.rerun()
                except Exception as e:
                    ui_error("Kierroksen aloitus epäonnistui.", e)
        return

    current_round = get_round(st.session_state.current_round_id)
    if not current_round:
        clear_round_state()
        st.warning("Kierrosta ei löytynyt enää.")
        st.rerun()
        return
    render_current_round_controls(current_round["id"])
    st.divider()
    holes = st.session_state.current_holes
    pos = st.session_state.current_hole_pos
    progress = min((pos) / len(holes), 1.0) if holes else 0
    st.progress(progress, text=f"Vaihe {min(pos+1, len(holes))}/{len(holes)}")
    if pos >= len(holes):
        course = get_course(st.session_state.current_course_id)
        rhs = get_round_holes(st.session_state.current_round_id)
        total = sum(r.get("total_strokes", 0) for r in rhs)
        st.success("Kierros valmis")
        c1, c2, c3 = st.columns(3)
        c1.metric("Tulos", total)
        c2.metric("Alusta", course.get("surface") if course else "–")
        c3.metric("Par", PAR_BY_SURFACE.get(course.get("surface"), "–") if course else "–")
        render_band_badge(course.get("surface") if course else None, total)
        if st.button("Päätä kierros valmiina", type="primary"):
            try:
                update_round_status(st.session_state.current_round_id, "completed")
                clear_round_state()
                st.success("Kierros tallennettu valmiina.")
                st.rerun()
            except Exception as e:
                ui_error("Kierroksen päättäminen epäonnistui.", e)
        return
    existing_map = {rh["hole_sequence_number"]: rh for rh in get_round_holes(st.session_state.current_round_id)}
    hole = holes[pos]
    existing = existing_map.get(hole["hole_number"])
    hole_id = hole["id"]
    title_block(f"Rata {hole['hole_number']}", hole.get("hole_name") or None)
    st.write(f"**Tyyppi:** {'Päättyvä rata' if hole.get('is_ending_hole') else 'Kenttärata'}")
    st.write(f"**Esteellinen:** {'Kyllä' if hole.get('has_obstacle') else 'Ei'}")
    default_strokes = existing.get("total_strokes", 1) if existing else 1
    choices = list(range(1, 8))
    strokes = st.radio("Lyönnit", choices, horizontal=True, index=choices.index(default_strokes if default_strokes in choices else 1), key=f"strokes_{hole_id}_{pos}")
    notes = st.text_input("Muistiinpanot radasta (valinnainen)", value=existing.get("notes", "") if existing else "", key=f"notes_{hole_id}_{pos}")
    existing_shots = get_shots(existing["id"]) if existing else []
    existing_shot_map = {s["shot_number"]: s for s in existing_shots}
    shot_rows = []
    if int(strokes) > 1:
        st.markdown("#### Lyöntikortit")
        for i in range(1, int(strokes) + 1):
            prev = existing_shot_map.get(i, {})
            st.markdown(f"**Lyönti {i}**")
            c1, c2, c3 = st.columns(3)
            with c1:
                went_in = st.checkbox("Sisään", value=prev.get("went_in", i == int(strokes)), key=f"in_{hole_id}_{pos}_{i}")
            with c2:
                went_through = st.checkbox("Läpi", value=prev.get("went_through", False), key=f"through_{hole_id}_{pos}_{i}") if hole.get("is_lane_hole") else False
            with c3:
                hit_obstacle = st.checkbox("Este", value=prev.get("hit_obstacle", False), key=f"obst_{hole_id}_{pos}_{i}") if hole.get("has_obstacle") else False
            c4, c5 = st.columns(2)
            with c4:
                direction_error = st.radio("Suunta", ["none", "left", "right"], horizontal=True, index=["none", "left", "right"].index(prev.get("direction_error", "none")), key=f"dir_{hole_id}_{pos}_{i}", format_func=lambda x: {"none": "ei", "left": "vasen", "right": "oikea"}[x])
            with c5:
                speed_error = st.radio("Vauhti", ["none", "too_slow", "too_hard"], horizontal=True, index=["none", "too_slow", "too_hard"].index(prev.get("speed_error", "none")), key=f"spd_{hole_id}_{pos}_{i}", format_func=lambda x: {"none": "ei", "too_slow": "hidas", "too_hard": "liian luja"}[x])
            shot_rows.append({"shot_number": i, "went_in": bool(went_in), "went_through": bool(went_through), "hit_obstacle": bool(hit_obstacle), "direction_error": direction_error, "speed_error": speed_error})
            st.divider()
    c_prev, c_skip, c_save = st.columns(3)
    if c_prev.button("⬅ Edellinen rata", disabled=(pos == 0)):
        st.session_state.current_hole_pos = max(0, pos - 1)
        st.rerun()
    if c_save.button("Tallenna rata", type="primary"):
        try:
            upsert_round_hole(st.session_state.current_round_id, hole, strokes, notes, shot_rows)
            st.session_state.current_hole_pos = min(len(holes), pos + 1)
            st.rerun()
        except Exception as e:
            ui_error("Radan tallennus epäonnistui.", e)
    if c_skip.button("Peruuta tämän radan tiedot"):
        st.rerun()


def render_history(user_id):
    title_block("Historia", "Suodata päivämäärän, alustan, tyypin ja tilan mukaan.")
    rounds = get_rounds(user_id)
    if not rounds:
        st.info("Ei vielä tallennettuja kierroksia.")
        return
    courses = {c["id"]: c for c in get_all_courses()}
    f1, f2, f3, f4, f5 = st.columns(5)
    date_from = f1.date_input("Alkaen", value=None)
    date_to = f2.date_input("Asti", value=None)
    surface_filter = f3.selectbox("Alusta", ["kaikki"] + SURFACE_OPTIONS)
    type_filter = f4.selectbox("Tyyppi", ["kaikki"] + ROUND_TYPE_OPTIONS)
    status_filter = f5.selectbox("Kierroksen tila", ["kaikki"] + [STATUS_LABELS[s] for s in ROUND_STATUS_OPTIONS])
    rows = []
    for rnd in rounds:
        course = courses.get(rnd["course_id"], {})
        played_date = to_date(rnd.get("played_at"))
        if date_from and played_date and played_date < date_from:
            continue
        if date_to and played_date and played_date > date_to:
            continue
        if surface_filter != "kaikki" and course.get("surface") != surface_filter:
            continue
        if type_filter != "kaikki" and rnd.get("round_type", "harjoitus") != type_filter:
            continue
        if status_filter != "kaikki" and format_status(rnd.get("status", "completed")) != status_filter:
            continue
        rhs = get_round_holes(rnd["id"])
        total = sum(r.get("total_strokes", 0) for r in rhs)
        color = band_for_score(course.get("surface"), total)[1]
        rows.append({"round_id": rnd["id"], "Päivä": rnd.get("played_at"), "Kenttä": course.get("name", "Tuntematon"), "Tyyppi": rnd.get("round_type", "harjoitus"), "Tila": format_status(rnd.get("status", "completed")), "Alusta": course.get("surface") or "–", "Par": PAR_BY_SURFACE.get(course.get("surface"), "–"), "Ratoja": len(rhs), "Tulos": total, "Muistiinpanot": rnd.get("notes") or "", "color": color})
    if not rows:
        st.info("Ei hakuehdoilla löytyviä kierroksia.")
        return
    header = "<table style='width:100%; border-collapse:collapse'><tr><th align='left'>Päivä</th><th align='left'>Kenttä</th><th align='left'>Tyyppi</th><th align='left'>Tila</th><th align='left'>Alusta</th><th align='left'>Par</th><th align='left'>Ratoja</th><th align='left'>Tulos</th><th align='left'>Muistiinpanot</th></tr>"
    body = ""
    for row in rows:
        body += f"<tr><td>{row['Päivä']}</td><td>{row['Kenttä']}</td><td>{row['Tyyppi']}</td><td>{row['Tila']}</td><td>{row['Alusta']}</td><td>{row['Par']}</td><td>{row['Ratoja']}</td><td style='color:{row['color']}; font-weight:700'>{row['Tulos']}</td><td>{row['Muistiinpanot']}</td></tr>"
    st.markdown(header + body + "</table>", unsafe_allow_html=True)
    df = pd.DataFrame(rows)
    completed_df = df[df["Tila"] == STATUS_LABELS["completed"]]
    c1, c2, c3 = st.columns(3)
    c1.metric("Valmiiden kierrosten keskiarvo", round(completed_df["Tulos"].mean(), 2) if not completed_df.empty else "–")
    prac = completed_df[completed_df["Tyyppi"] == "harjoitus"]
    comp = completed_df[completed_df["Tyyppi"] == "kisa"]
    c2.metric("Valmiit harjoituskierrokset", round(prac["Tulos"].mean(), 2) if not prac.empty else "–")
    c3.metric("Valmiit kisakierrokset", round(comp["Tulos"].mean(), 2) if not comp.empty else "–")
    st.markdown("### Muokkaa tai poista tallennettu kierros")
    round_map = {f"{row['Päivä']} – {row['Kenttä']} ({row['Tulos']})": row["round_id"] for row in rows}
    selected_label = st.selectbox("Valitse kierros", list(round_map.keys()))
    selected_round_id = round_map[selected_label]
    round_record = get_round(selected_round_id)
    rhs = get_round_holes(selected_round_id)
    if round_record and round_record.get("status") == "draft" and st.button("Jatka tätä keskeneräistä kierrosta"):
        load_round_into_state(round_record)
        st.rerun()
    with st.form("edit_round_form"):
        round_type = st.selectbox("Kierroksen tyyppi", ROUND_TYPE_OPTIONS, index=ROUND_TYPE_OPTIONS.index(round_record.get("round_type", "harjoitus")) if round_record.get("round_type", "harjoitus") in ROUND_TYPE_OPTIONS else 0)
        status_ui = st.selectbox("Kierroksen tila", [STATUS_LABELS[s] for s in ROUND_STATUS_OPTIONS], index=ROUND_STATUS_OPTIONS.index(round_record.get("status", "completed")) if round_record.get("status", "completed") in ROUND_STATUS_OPTIONS else 0)
        notes = st.text_area("Kierroksen muistiinpanot", value=round_record.get("notes") or "")
        edited_scores = {}
        for rh in rhs:
            course_hole = safe_data(supabase.table("course_holes").select("hole_number").eq("id", rh["course_hole_id"]).execute())
            hole_no = course_hole[0]["hole_number"] if course_hole else rh.get("hole_sequence_number")
            edited_scores[rh["id"]] = st.number_input(f"Rata {hole_no} – lyönnit", min_value=1, max_value=20, value=int(rh.get("total_strokes", 1)), step=1, key=f"edit_rh_{rh['id']}")
        if st.form_submit_button("Tallenna muutokset"):
            try:
                update_round_meta(selected_round_id, round_type, notes, STATUS_LABEL_TO_VALUE[status_ui])
                for rh in rhs:
                    supabase.table("round_holes").update({"total_strokes": int(edited_scores[rh['id']]), "went_straight_in": int(edited_scores[rh['id']]) == 1}).eq("id", rh["id"]).execute()
                st.success("Kierros päivitetty.")
                st.rerun()
            except Exception as e:
                ui_error("Kierroksen päivitys epäonnistui.", e)
    if st.button("Poista valittu kierros", type="secondary"):
        try:
            delete_round(selected_round_id)
            st.success("Kierros poistettu.")
            st.rerun()
        except Exception as e:
            ui_error("Kierroksen poisto epäonnistui.", e)


def render_analysis(user_id):
    title_block("Analyysi", "Vain valmiit kierrokset huomioidaan analyysissä.")
    a1, a2, a3, a4 = st.columns(4)
    date_from = a1.date_input("Alkaen", value=None, key="analysis_from")
    date_to = a2.date_input("Asti", value=None, key="analysis_to")
    surface_filter = a3.selectbox("Alusta", ["kaikki"] + SURFACE_OPTIONS, key="analysis_surface")
    type_filter = a4.selectbox("Tyyppi", ["kaikki"] + ROUND_TYPE_OPTIONS, key="analysis_type")
    metrics = get_analysis_metrics(user_id, surface_filter=surface_filter, date_from=date_from, date_to=date_to, type_filter=type_filter)
    if not metrics:
        st.info("Analyysi näkyy, kun suodattimilla löytyy valmiita kierroksia.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Piikki %", f"{metrics['piikki']} %" if metrics['piikki'] is not None else "–")
    c2.metric("Attempts (avg)", str(metrics['attempts_avg']) if metrics['attempts_avg'] is not None else "–")
    c3.metric("Pitkät sarjat %", f"{metrics['pitkat']} %" if metrics['pitkat'] is not None else "–")
    st.caption("Pitkät sarjat % = kuinka usein päättyvillä radoilla tarvittiin vähintään 4 lyöntiä.")
    c4, c5, c6, c7 = st.columns(4)
    c4.metric("Oikealle ohi", metrics['right_count'])
    c5.metric("Vasemmalle ohi", metrics['left_count'])
    c6.metric("Hitaat vauhtivirheet", metrics['slow_count'])
    c7.metric("Liian lujat vauhtivirheet", metrics['hard_count'])
    if metrics.get("eterniitti"):
        et = metrics["eterniitti"]
        st.markdown("### Eterniitti – piikin jälkeen")
        e1, e2, e3, e4, e5 = st.columns(5)
        e1.metric("Piikki %", f"{et['piikki_pct']} %")
        e2.metric("Kakkonen %", f"{et['kakkonen_pct']} %")
        e3.metric("3–7 %", f"{et['three_to_seven_pct']} %")
        e4.metric("Pelastettu 2 %", "–" if et['pelastettu_kakkoseen_pct'] is None else f"{et['pelastettu_kakkoseen_pct']} %")
        e5.metric("Jatkuu 3–7 %", "–" if et['jatkuu_huono_pct'] is None else f"{et['jatkuu_huono_pct']} %")


def render_profile_tab(user_id):
    profile = get_profile(user_id)
    current_name = (profile or {}).get("display_name") or current_user_email() or "Pelaaja"
    title_block("Profiili", "Vaihda näkyvä nimi. Tätä nimeä käytetään historiassa ja muualla sovelluksessa.")
    st.write(f"**Sähköposti:** {current_user_email() or '–'}")
    with st.form("profile_form"):
        display_name = st.text_input("Näkyvä nimi", value=current_name)
        if st.form_submit_button("Tallenna profiili"):
            try:
                update_profile_name(user_id, display_name)
                st.success("Profiili päivitetty.")
                st.rerun()
            except Exception as e:
                ui_error("Profiilin päivitys epäonnistui.", e)


def main_view():
    user_id = current_user_id()
    profile = get_profile(user_id)
    title_block("Bankontoret", f"Kirjautunut: {(profile or {}).get('display_name') or 'Pelaaja'}")
    if is_admin():
        st.info("Olet pääkäyttäjä. Voit muokata kenttiä, ratoja ja poistaa kenttiä.")
    render_sidebar(user_id)
    tabs = st.tabs(["Etusivu", "Kentät", "Kierros", "Historia", "Analyysi", "Profiili"])
    with tabs[0]:
        render_dashboard(user_id)
    with tabs[1]:
        render_courses(user_id)
    with tabs[2]:
        render_new_round(user_id)
    with tabs[3]:
        render_history(user_id)
    with tabs[4]:
        render_analysis(user_id)
    with tabs[5]:
        render_profile_tab(user_id)


apply_custom_css()
init_state()
restore_auth_session()
if current_user_id() is None:
    auth_view()
else:
    main_view()
