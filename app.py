
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
STATUS_LABELS = {"completed": "valmis", "draft": "kesken", "abandoned": "hylätty"}
STATUS_LABEL_TO_VALUE = {v: k for k, v in STATUS_LABELS.items()}
VISIBILITY_LABELS = {"private": "Ei", "shared": "Kyllä"}
VISIBILITY_UI = {"Vain minulle": "private", "Joukkueelle näkyvä": "shared"}
ADMIN_EMAIL = "gretasofiaisabella@gmail.com"
NAV_ITEMS = ["Etusivu", "Kentät", "Kierros", "Historia", "Analyysi", "Profiili"]
MAX_HOLES = 18

# =========================================================
# UI / helper
# =========================================================
def apply_custom_css():
    st.markdown(
        """
        <style>
            .block-container {padding-top: 0.9rem; padding-bottom: 2rem; max-width: 1120px;}
            #MainMenu {visibility: hidden;}
            header[data-testid="stHeader"] {visibility: hidden; height: 0;}
            [data-testid="stToolbar"] {display: none !important;}
            [data-testid="stDecoration"] {display: none !important;}
            section[data-testid="stSidebar"] {display:none !important;}
            footer {visibility: hidden;}
            div[data-testid="stMetric"] {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                padding: .65rem .85rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def safe_data(resp):
    return getattr(resp, "data", None) or []


def title_block(title, subtitle=None):
    st.subheader(title)
    if subtitle:
        st.caption(subtitle)


def ui_error(msg, err):
    st.error(f"{msg} {err}")


def to_date(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except Exception:
        return None


def fmt_date(value):
    d = to_date(value)
    return d.strftime("%d.%m.%Y") if d else str(value or "")


def format_status(value):
    return STATUS_LABELS.get(value, value)


def current_user_id():
    return st.session_state.user.id if st.session_state.user else None


def current_user_email():
    return getattr(st.session_state.user, "email", None) if st.session_state.user else None


def is_admin():
    email = current_user_email()
    return bool(email and email.strip().lower() == ADMIN_EMAIL.strip().lower())


def band_for_score(surface, total_score):
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


def score_color(surface, total_score):
    return band_for_score(surface, total_score)[1]


def render_band_badge(surface, total_score):
    label, color = band_for_score(surface, total_score)
    st.markdown(
        f"<span style='display:inline-block;padding:.35rem .7rem;border-radius:999px;background:{color};color:#fff;font-weight:600'>{label}</span>",
        unsafe_allow_html=True,
    )

# =========================================================
# Session / auth
# =========================================================
def init_state():
    defaults = {
        "access_token": None,
        "refresh_token": None,
        "user": None,
        "view": "Etusivu",
        "current_round_id": None,
        "current_course_id": None,
        "current_holes": [],
        "current_hole_pos": 0,
        "current_round_holes_map": {},
        "current_round_shots_map": {},
        "remember_me": False,
        "history_selected_round_id": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def restore_auth_session():
    if st.session_state.access_token and st.session_state.refresh_token:
        try:
            supabase.auth.set_session(st.session_state.access_token, st.session_state.refresh_token)
            resp = supabase.auth.get_user()
            st.session_state.user = resp.user if resp else None
        except Exception:
            st.session_state.access_token = None
            st.session_state.refresh_token = None
            st.session_state.user = None


def save_auth_session(auth_response, remember_me=False):
    session = getattr(auth_response, "session", None)
    user = getattr(auth_response, "user", None)
    if session:
        st.session_state.access_token = session.access_token
        st.session_state.refresh_token = session.refresh_token
    st.session_state.user = user
    st.session_state.remember_me = remember_me


def clear_round_state():
    st.session_state.current_round_id = None
    st.session_state.current_course_id = None
    st.session_state.current_holes = []
    st.session_state.current_hole_pos = 0
    st.session_state.current_round_holes_map = {}
    st.session_state.current_round_shots_map = {}


def send_password_reset(email: str):
    email = (email or "").strip()
    if not email:
        raise ValueError("Anna sähköpostiosoite.")
    auth_obj = supabase.auth
    if hasattr(auth_obj, "reset_password_for_email"):
        return auth_obj.reset_password_for_email(email)
    if hasattr(auth_obj, "reset_password_email"):
        return auth_obj.reset_password_email(email)
    raise AttributeError("Salasanan palautusmetodia ei löytynyt.")

# =========================================================
# Cache
# =========================================================
@st.cache_data(ttl=60)
def cached_get_profile(user_id):
    rows = safe_data(supabase.table("profiles").select("*").eq("user_id", user_id).execute())
    return rows[0] if rows else None

@st.cache_data(ttl=60)
def cached_get_all_courses():
    return safe_data(supabase.table("courses").select("*").order("name").execute())

@st.cache_data(ttl=60)
def cached_get_course(course_id):
    rows = safe_data(supabase.table("courses").select("*").eq("id", course_id).execute())
    return rows[0] if rows else None

@st.cache_data(ttl=60)
def cached_get_course_holes(course_id):
    return safe_data(supabase.table("course_holes").select("*").eq("course_id", course_id).order("hole_number").execute())

@st.cache_data(ttl=30)
def cached_get_rounds(user_id):
    return safe_data(supabase.table("rounds").select("*").eq("user_id", user_id).order("played_at", desc=True).execute())


def clear_app_caches():
    cached_get_profile.clear(); cached_get_all_courses.clear(); cached_get_course.clear(); cached_get_course_holes.clear(); cached_get_rounds.clear()

# =========================================================
# Profile / course
# =========================================================
def ensure_profile_exists(user_id, display_name):
    rows = safe_data(supabase.table("profiles").select("user_id, display_name").eq("user_id", user_id).execute())
    wanted = (display_name or "Pelaaja").strip() or "Pelaaja"
    if not rows:
        supabase.table("profiles").insert({"user_id": user_id, "display_name": wanted}).execute()
    elif rows[0].get("display_name") != wanted:
        supabase.table("profiles").update({"display_name": wanted}).eq("user_id", user_id).execute()
    clear_app_caches()


def get_profile(user_id): return cached_get_profile(user_id)
def get_all_courses(): return cached_get_all_courses()
def get_course(course_id): return cached_get_course(course_id)
def get_course_holes(course_id): return cached_get_course_holes(course_id)

def get_all_courses_fresh():
    return safe_data(supabase.table("courses").select("*").order("name").execute())


def get_course_holes_fresh(course_id):
    return safe_data(supabase.table("course_holes").select("*").eq("course_id", course_id).order("hole_number").execute())


def update_profile_name(user_id, display_name):
    value = (display_name or "").strip()
    if not value:
        raise ValueError("Anna näkyvä nimi.")
    existing = get_profile(user_id)
    if existing:
        supabase.table("profiles").update({"display_name": value}).eq("user_id", user_id).execute()
    else:
        supabase.table("profiles").insert({"user_id": user_id, "display_name": value}).execute()
    clear_app_caches()


def can_edit_course(course):
    return bool(course and (is_admin() or course.get("owner_user_id") == current_user_id()))


def update_course(course_id, name, location, surface):
    supabase.table("courses").update({"name": name.strip(), "location": location.strip() or None, "surface": surface}).eq("id", course_id).execute()
    clear_app_caches()


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
    clear_app_caches()


def delete_course(course_id):
    safe_data(supabase.table("course_holes").delete().eq("course_id", course_id).execute())
    safe_data(supabase.table("courses").delete().eq("id", course_id).execute())
    clear_app_caches()


# =========================================================
# Round helpers
# =========================================================
def get_rounds(user_id): return cached_get_rounds(user_id)

def get_round(round_id):
    rows = safe_data(supabase.table("rounds").select("*").eq("id", round_id).execute())
    return rows[0] if rows else None


def fetch_round_holes(round_id):
    return safe_data(supabase.table("round_holes").select("*").eq("round_id", round_id).order("hole_sequence_number").execute())


def fetch_shots(round_hole_id):
    return safe_data(supabase.table("shots").select("*").eq("round_hole_id", round_hole_id).order("shot_number").execute())


def load_round_into_state(round_row):
    holes = get_course_holes(round_row["course_id"])
    rhs = fetch_round_holes(round_row["id"])
    holes_map = {rh["hole_sequence_number"]: rh for rh in rhs}
    shots_map = {rh["id"]: fetch_shots(rh["id"]) for rh in rhs}
    st.session_state.current_round_id = round_row["id"]
    st.session_state.current_course_id = round_row["course_id"]
    st.session_state.current_holes = holes
    st.session_state.current_hole_pos = min(len(rhs), len(holes))
    st.session_state.current_round_holes_map = holes_map
    st.session_state.current_round_shots_map = shots_map


def update_round_status(round_id, status_value):
    supabase.table("rounds").update({"status": status_value}).eq("id", round_id).execute()
    clear_app_caches()


def upsert_round_hole(round_id, hole, total_strokes, notes, shot_rows):
    existing = st.session_state.current_round_holes_map.get(hole["hole_number"])
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
        existing = {"id": rh_id, **payload}
    if int(total_strokes) == 1:
        final_rows = [{"round_hole_id": rh_id, "shot_number": 1, "went_in": True, "went_through": False, "hit_obstacle": False, "direction_error": "none", "speed_error": "none"}]
        supabase.table("shots").insert(final_rows).execute()
    else:
        final_rows = []
        for row in shot_rows:
            item = row.copy(); item["round_hole_id"] = rh_id; final_rows.append(item)
        if final_rows and not final_rows[-1]["went_in"]:
            final_rows[-1]["went_in"] = True
        if final_rows:
            supabase.table("shots").insert(final_rows).execute()
    existing.update({"id": rh_id})
    st.session_state.current_round_holes_map[hole["hole_number"]] = existing
    st.session_state.current_round_shots_map[rh_id] = final_rows
    clear_app_caches()


def delete_round(round_id):
    rhs = fetch_round_holes(round_id)
    for rh in rhs:
        supabase.table("shots").delete().eq("round_hole_id", rh["id"]).execute()
    supabase.table("round_holes").delete().eq("round_id", round_id).execute()
    supabase.table("rounds").delete().eq("id", round_id).execute()
    clear_app_caches()


def round_visibility_label(value):
    return VISIBILITY_LABELS.get(value or "private", "Ei")

# =========================================================
# Analysis helpers
# =========================================================
def filter_rounds_for_stats(rounds, surface_filter, date_from, date_to, type_filter):
    courses = {c["id"]: c for c in get_all_courses()}
    out = []
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
        out.append((rnd, course))
    return out


def get_analysis_metrics(user_id, surface_filter="kaikki", date_from=None, date_to=None, type_filter="kaikki"):
    rounds_with_course = filter_rounds_for_stats(get_rounds(user_id), surface_filter, date_from, date_to, type_filter)
    if not rounds_with_course:
        return None
    all_rhs, ending_attempts, eterniitti_scores = [], [], []
    direction_counts = {"left": 0, "right": 0}
    speed_counts = {"too_slow": 0, "too_hard": 0}
    miss_by_type = {"Päättyvä rata": 0, "Kenttärata": 0}
    obstacle_hits_total = obstacle_followup_total = obstacle_followup_success = 0
    hole_meta_cache = {}

    for rnd, course in rounds_with_course:
        course_id = rnd["course_id"]
        if course_id not in hole_meta_cache:
            hole_meta_cache[course_id] = {h["id"]: h for h in get_course_holes(course_id)}
        meta_by_id = hole_meta_cache[course_id]
        rhs = fetch_round_holes(rnd["id"])
        for rh in rhs:
            all_rhs.append(rh)
            meta = meta_by_id.get(rh["course_hole_id"], {})
            hole_type = "Päättyvä rata" if meta.get("is_ending_hole") else "Kenttärata"
            shots = fetch_shots(rh["id"])
            for idx, shot in enumerate(shots):
                if shot.get("direction_error") == "left":
                    direction_counts["left"] += 1
                elif shot.get("direction_error") == "right":
                    direction_counts["right"] += 1
                if shot.get("speed_error") == "too_slow":
                    speed_counts["too_slow"] += 1
                elif shot.get("speed_error") == "too_hard":
                    speed_counts["too_hard"] += 1
                miss = False
                if not shot.get("went_in"):
                    if shot.get("direction_error") in ["left", "right"]:
                        miss = True
                    if meta.get("is_lane_hole") and shot.get("went_through"):
                        miss = True
                if miss:
                    miss_by_type[hole_type] += 1
                if shot.get("hit_obstacle"):
                    obstacle_hits_total += 1
                    if idx + 1 < len(shots):
                        obstacle_followup_total += 1
                        if shots[idx + 1].get("went_in"):
                            obstacle_followup_success += 1
            if meta.get("is_ending_hole"):
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
        "miss_by_type": miss_by_type,
        "obstacle_hits_total": obstacle_hits_total,
        "obstacle_followup_total": obstacle_followup_total,
        "obstacle_followup_success": obstacle_followup_success,
        "paikko_pct": round((obstacle_followup_success / obstacle_followup_total) * 100, 1) if obstacle_followup_total else None,
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


def build_history_rows(user_id):
    rounds = get_rounds(user_id)
    courses = {c["id"]: c for c in get_all_courses()}
    rows = []
    for rnd in rounds:
        course = courses.get(rnd["course_id"], {})
        rhs = fetch_round_holes(rnd["id"])
        total = sum(r.get("total_strokes", 0) for r in rhs)
        rows.append({
            "round_id": rnd["id"],
            "Päivä": fmt_date(rnd.get("played_at")),
            "Kenttä": course.get("name", "Tuntematon"),
            "Tyyppi": rnd.get("round_type", "harjoitus"),
            "Tulos": total,
            "Alusta": course.get("surface"),
            "Joukkueelle näkyvä": round_visibility_label(rnd.get("visibility", "private")),
            "Muistiinpanot": rnd.get("notes") or "",
            "Tila": format_status(rnd.get("status", "completed")),
        })
    return rows


def render_history_detail(round_id):
    rnd = get_round(round_id)
    if not rnd:
        st.warning("Kierrosta ei löytynyt.")
        return
    course = get_course(rnd["course_id"])
    rhs = fetch_round_holes(round_id)
    holes_meta = {h["id"]: h for h in get_course_holes(rnd["course_id"])}
    total = sum(r.get("total_strokes", 0) for r in rhs)
    st.markdown("### Kierroksen tiedot")
    a, b, c, d = st.columns(4)
    a.metric("Päivä", fmt_date(rnd.get("played_at")))
    b.metric("Kenttä", course.get("name", "Tuntematon") if course else "Tuntematon")
    c.metric("Tyyppi", rnd.get("round_type", "harjoitus"))
    d.metric("Tulos", total)
    e, f, g = st.columns(3)
    e.metric("Tila", format_status(rnd.get("status", "completed")))
    f.metric("Joukkueelle näkyvä", round_visibility_label(rnd.get("visibility", "private")))
    g.metric("Alusta", course.get("surface", "–") if course else "–")

    detail_rows = []
    for rh in rhs:
        meta = holes_meta.get(rh["course_hole_id"], {})
        shots = fetch_shots(rh["id"])
        desc_parts = []
        for shot in shots:
            bits = [f"L{shot.get('shot_number')}"]
            if shot.get("went_in"):
                bits.append("sisään")
            if shot.get("went_through"):
                bits.append("läpi")
            if shot.get("hit_obstacle"):
                bits.append("este")
            if shot.get("direction_error") == "left":
                bits.append("vasen")
            elif shot.get("direction_error") == "right":
                bits.append("oikea")
            if shot.get("speed_error") == "too_slow":
                bits.append("hidas")
            elif shot.get("speed_error") == "too_hard":
                bits.append("liian luja")
            desc_parts.append(", ".join(bits))
        detail_rows.append({
            "Rata": rh.get("hole_sequence_number"),
            "Nimi": meta.get("hole_name") or "",
            "Tyyppi": "Päättyvä" if meta.get("is_ending_hole") else "Kenttä",
            "Esteellinen": "Kyllä" if meta.get("has_obstacle") else "Ei",
            "Lyönnit": rh.get("total_strokes"),
            "Muistiinpanot": rh.get("notes") or "",
            "Lyöntitiedot": " | ".join(desc_parts),
        })
    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)


# ---------------- views ----------------
def render_topbar(user_id):
    profile = get_profile(user_id)
    left, middle, right = st.columns([4, 3, 1])
    with left:
        title_block("Bankontoret", f"Kirjautunut: {(profile or {}).get('display_name') or 'Pelaaja'}")
    with middle:
        current = st.session_state.view if st.session_state.view in NAV_ITEMS else "Etusivu"
        st.session_state.view = st.selectbox("Näkymä", NAV_ITEMS, index=NAV_ITEMS.index(current), label_visibility="collapsed")
    with right:
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


def auth_view():
    st.title("Bankontoret")
    st.caption("Kirjaudu tai luo käyttäjä.")
    st.warning("Pysy kirjautuneena näkyy valintana, mutta tätä versiota ei ole vielä sidottu turvalliseen pysyvään selaintallennukseen.")
    st.info("Sähköpostivahvistuslinkin 'sivu ei toimi' -ongelma liittyy yleensä Supabase Authin Site URL / Redirect URL -asetuksiin.")
    c1, c2 = st.columns(2)
    with c1:
        title_block("Kirjaudu")
        with st.form("login"):
            email = st.text_input("Sähköposti")
            password = st.text_input("Salasana", type="password")
            remember_me = st.checkbox("Pysy kirjautuneena")
            if st.form_submit_button("Kirjaudu"):
                response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                save_auth_session(response, remember_me=remember_me)
                ensure_profile_exists(current_user_id(), email.split("@")[0])
                st.rerun()
    with c2:
        title_block("Luo käyttäjä")
        with st.form("signup"):
            name = st.text_input("Näyttönimi")
            email = st.text_input("Sähköposti", key="signup_email")
            password = st.text_input("Salasana", type="password", key="signup_password")
            if st.form_submit_button("Luo käyttäjä"):
                supabase.auth.sign_up({"email": email, "password": password, "options": {"data": {"display_name": name}}})
                st.success("Käyttäjä luotu. Jos vahvistuslinkki ei toimi, korjaa Redirect URL Supabasessa.")
        with st.expander("Unohtuiko salasana?"):
            with st.form("reset_password_form"):
                reset_email = st.text_input("Sähköposti salasanan palautusta varten", key="reset_email")
                if st.form_submit_button("Lähetä palautuslinkki"):
                    send_password_reset(reset_email)
                    st.success("Jos sähköposti löytyy järjestelmästä, palautuslinkki on lähetetty.")


def render_dashboard(user_id):
    title_block("Etusivu")
    rounds = get_rounds(user_id)
    courses = get_all_courses()
    a, b, c = st.columns(3)
    a.metric("Kentät", len(courses))
    b.metric("Valmiit kierrokset", len([r for r in rounds if r.get("status") == "completed"]))
    c.metric("Keskeneräiset kierrokset", len([r for r in rounds if r.get("status") == "draft"]))


def render_courses(user_id):
    title_block("Kentät")
    all_courses = get_all_courses_fresh()
    with st.expander("Luo uusi kenttä"):
        with st.form("new_course", clear_on_submit=True):
            course_name = st.text_input("Kentän nimi")
            location = st.text_input("Sijainti (valinnainen)")
            surface = st.selectbox("Alusta", SURFACE_OPTIONS)
            if st.form_submit_button("Tallenna kenttä"):
                if not course_name.strip():
                    st.error("Anna kentälle nimi.")
                else:
                    supabase.table("courses").insert({"name": course_name.strip(), "location": location.strip() or None, "surface": surface, "owner_user_id": user_id}).execute()
                    clear_app_caches(); st.success("Kenttä tallennettu."); st.rerun()
    if not all_courses:
        st.info("Ei vielä kenttiä.")
        return
    course_map = {f"{c['name']} ({c.get('surface') or 'ei alustaa'})": c for c in all_courses}
    selected_label = st.selectbox("Valitse kenttä", list(course_map.keys()))
    course = course_map[selected_label]
    holes = get_course_holes_fresh(course["id"])
    a, b, c, d = st.columns(4)
    a.metric("Alusta", course.get("surface") or "–")
    b.metric("Par", PAR_BY_SURFACE.get(course.get("surface"), "–"))
    c.metric("Sijainti", course.get("location") or "–")
    d.metric("Ratoja", f"{len(holes)}/18")
    if holes:
        st.dataframe(pd.DataFrame([{"#": h["hole_number"], "Nimi": h.get("hole_name") or "", "Tyyppi": "Päättyvä" if h.get("is_ending_hole") else "Kenttärata", "Esteellinen": "Kyllä" if h.get("has_obstacle") else "Ei"} for h in holes]), use_container_width=True, hide_index=True)
    if len(holes) < MAX_HOLES:
        with st.expander("Lisää uusi rata"):
            next_no = len(holes) + 1
            with st.form("new_hole", clear_on_submit=True):
                st.text_input("Radan numero", value=str(next_no), disabled=True)
                hole_name = st.text_input("Radan nimi (valinnainen)")
                hole_type = st.radio("Ratatyyppi", ["Päättyvä rata", "Kenttärata"], horizontal=True)
                has_obstacle = st.checkbox("Esteellinen")
                if st.form_submit_button(f"Tallenna rata {next_no}/18"):
                    supabase.table("course_holes").insert({"course_id": course["id"], "hole_number": next_no, "hole_name": hole_name.strip() or None, "is_ending_hole": hole_type == "Päättyvä rata", "is_lane_hole": hole_type == "Kenttärata", "has_obstacle": bool(has_obstacle)}).execute()
                    clear_app_caches(); st.success(f"Rata {next_no}/18 tallennettu."); st.rerun()
    if can_edit_course(course):
        with st.expander("Muokkaa tätä kenttää"):
            editable_holes = get_course_holes_fresh(course["id"])
            with st.form(f"edit_course_{course['id']}"):
                new_name = st.text_input("Kentän nimi", value=course.get("name") or "")
                new_location = st.text_input("Sijainti", value=course.get("location") or "")
                new_surface = st.selectbox("Alusta", SURFACE_OPTIONS, index=SURFACE_OPTIONS.index(course.get("surface")) if course.get("surface") in SURFACE_OPTIONS else 0)
                edited = []
                for hole in editable_holes:
                    st.markdown(f"**Rata {hole['hole_number']}**")
                    x1, x2, x3 = st.columns([1, 3, 2])
                    with x1:
                        hole_number = st.number_input("Ratanumero", min_value=1, max_value=18, value=int(hole['hole_number']), step=1, key=f"num_{hole['id']}")
                    with x2:
                        hole_name = st.text_input("Radan nimi", value=hole.get("hole_name") or "", key=f"name_{hole['id']}")
                    with x3:
                        hole_type = st.radio("Ratatyyppi", ["Päättyvä rata", "Kenttärata"], horizontal=True, index=0 if hole.get("is_ending_hole") else 1, key=f"type_{hole['id']}")
                    has_obstacle = st.checkbox("Esteellinen", value=bool(hole.get("has_obstacle")), key=f"obs_{hole['id']}")
                    edited.append({"id": hole["id"], "hole_number": int(hole_number), "hole_name": hole_name, "is_ending_hole": hole_type == "Päättyvä rata", "has_obstacle": bool(has_obstacle)})
                    st.divider()
                if st.form_submit_button("Tallenna kentän muutokset"):
                    update_course(course["id"], new_name, new_location, new_surface)
                    replace_hole_order(edited)
                    st.success("Kenttä päivitetty.")
                    st.rerun()
        confirm = st.checkbox("Ymmärrän kentän poiston seuraukset.", key=f"confirm_delete_course_{course['id']}")
        if st.button("Poista tämä kenttä", disabled=not confirm, key=f"delete_btn_{course['id']}"):
            delete_course(course["id"])
            st.success("Kenttä poistettu.")
            st.rerun()


def render_draft_rounds(user_id):
    rounds = [r for r in get_rounds(user_id) if r.get("status") == "draft"]
    if not rounds:
        return
    courses = {c["id"]: c for c in get_all_courses()}
    title_block("Jatka keskeneräistä kierrosta")
    labels, round_map = [], {}
    for rnd in rounds:
        rhs = fetch_round_holes(rnd["id"])
        course = courses.get(rnd["course_id"], {})
        label = f"{rnd.get('played_at')} – {course.get('name', 'Tuntematon')} ({len(rhs)}/18)"
        labels.append(label); round_map[label] = rnd
    selected = st.selectbox("Valitse keskeneräinen kierros", labels)
    a, b = st.columns(2)
    if a.button("Jatka valittua kierrosta"):
        load_round_into_state(round_map[selected]); st.rerun()
    if b.button("Poista valittu keskeneräinen kierros"):
        delete_round(round_map[selected]["id"]); st.success("Keskeneräinen kierros poistettu."); st.rerun()


def render_current_round_controls(round_id):
    a, b = st.columns(2)
    if a.button("Tallenna kierros keskeneräisenä"):
        update_round_status(round_id, "draft"); clear_round_state(); st.success("Kierros tallennettu keskeneräisenä."); st.rerun()
    if b.button("Poista tämä kierros"):
        delete_round(round_id); clear_round_state(); st.success("Kierros poistettu."); st.rerun()


def render_new_round(user_id):
    title_block("Kierros")
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
            visibility_ui = st.selectbox("Näkyvyys", list(VISIBILITY_UI.keys()))
            notes = st.text_area("Muistiinpanot (valinnainen)")
            can_start = len(holes) == 18
            if st.form_submit_button("Aloita kierros", disabled=not can_start):
                payload = {"user_id": user_id, "course_id": selected_course["id"], "played_at": played_at.isoformat(), "visibility": VISIBILITY_UI[visibility_ui], "notes": notes.strip() or None, "round_type": round_type, "status": "draft"}
                result = supabase.table("rounds").insert(payload).execute()
                st.session_state.current_round_id = result.data[0]["id"]
                st.session_state.current_course_id = selected_course["id"]
                st.session_state.current_holes = holes
                st.session_state.current_hole_pos = 0
                st.session_state.current_round_holes_map = {}
                st.session_state.current_round_shots_map = {}
                clear_app_caches(); st.rerun()
        return
    current_round = get_round(st.session_state.current_round_id)
    if not current_round:
        clear_round_state(); st.warning("Kierrosta ei löytynyt enää."); st.rerun(); return
    render_current_round_controls(current_round["id"])
    st.divider()
    holes = st.session_state.current_holes
    pos = st.session_state.current_hole_pos
    st.progress(min((pos) / len(holes), 1.0) if holes else 0, text=f"Vaihe {min(pos+1, len(holes))}/{len(holes)}")
    if pos >= len(holes):
        total = sum(r.get("total_strokes", 0) for r in st.session_state.current_round_holes_map.values())
        course = get_course(st.session_state.current_course_id)
        a, b, c = st.columns(3)
        a.metric("Tulos", total); b.metric("Alusta", course.get("surface") if course else "–"); c.metric("Par", PAR_BY_SURFACE.get(course.get("surface"), "–") if course else "–")
        render_band_badge(course.get("surface") if course else None, total)
        if st.button("Päätä kierros valmiina"):
            update_round_status(st.session_state.current_round_id, "completed")
            clear_round_state(); st.success("Kierros tallennettu valmiina."); st.rerun()
        return
    hole = holes[pos]
    existing = st.session_state.current_round_holes_map.get(hole["hole_number"])
    hole_id = hole["id"]
    title_block(f"Rata {hole['hole_number']}", hole.get("hole_name") or None)
    st.write(f"**Tyyppi:** {'Päättyvä rata' if hole.get('is_ending_hole') else 'Kenttärata'}")
    st.write(f"**Esteellinen:** {'Kyllä' if hole.get('has_obstacle') else 'Ei'}")
    choices = list(range(1, 8))
    default_strokes = existing.get("total_strokes", 1) if existing else 1
    strokes = st.radio("Lyönnit", choices, horizontal=True, index=choices.index(default_strokes if default_strokes in choices else 1), key=f"strokes_{hole_id}_{pos}")
    notes = st.text_input("Muistiinpanot radasta (valinnainen)", value=existing.get("notes", "") if existing else "", key=f"notes_{hole_id}_{pos}")
    existing_shots = st.session_state.current_round_shots_map.get(existing["id"], []) if existing else []
    existing_shot_map = {s["shot_number"]: s for s in existing_shots}
    shot_rows = []
    if int(strokes) > 1:
        st.markdown("#### Lyöntikortit")
        for i in range(1, int(strokes) + 1):
            prev = existing_shot_map.get(i, {})
            x1, x2, x3 = st.columns(3)
            with x1:
                went_in = st.checkbox("Sisään", value=prev.get("went_in", i == int(strokes)), key=f"in_{hole_id}_{pos}_{i}")
            with x2:
                went_through = st.checkbox("Läpi", value=prev.get("went_through", False), key=f"through_{hole_id}_{pos}_{i}") if hole.get("is_lane_hole") else False
            with x3:
                hit_obstacle = st.checkbox("Este", value=prev.get("hit_obstacle", False), key=f"obst_{hole_id}_{pos}_{i}") if hole.get("has_obstacle") else False
            y1, y2 = st.columns(2)
            with y1:
                direction_error = st.radio("Suunta", ["none", "left", "right"], horizontal=True, index=["none", "left", "right"].index(prev.get("direction_error", "none")), key=f"dir_{hole_id}_{pos}_{i}", format_func=lambda x: {"none": "ei", "left": "vasen", "right": "oikea"}[x])
            with y2:
                speed_error = st.radio("Vauhti", ["none", "too_slow", "too_hard"], horizontal=True, index=["none", "too_slow", "too_hard"].index(prev.get("speed_error", "none")), key=f"spd_{hole_id}_{pos}_{i}", format_func=lambda x: {"none": "ei", "too_slow": "hidas", "too_hard": "liian luja"}[x])
            shot_rows.append({"shot_number": i, "went_in": bool(went_in), "went_through": bool(went_through), "hit_obstacle": bool(hit_obstacle), "direction_error": direction_error, "speed_error": speed_error})
            st.divider()
    p, s, n = st.columns(3)
    if p.button("⬅ Edellinen rata", disabled=(pos == 0)):
        st.session_state.current_hole_pos = max(0, pos - 1); st.rerun()
    if n.button("Tallenna rata"):
        upsert_round_hole(st.session_state.current_round_id, hole, strokes, notes, shot_rows)
        st.session_state.current_hole_pos = min(len(holes), pos + 1); st.rerun()
    if s.button("Peruuta tämän radan tiedot"):
        st.rerun()


def render_history(user_id):
    title_block("Historia")
    rows = build_history_rows(user_id)
    if not rows:
        st.info("Ei vielä tallennettuja kierroksia.")
        return

    header = st.columns([1.2, 2.6, 1.2, 1.0, 1.4, 0.8])
    header[0].markdown("**Päivä**")
    header[1].markdown("**Kenttä**")
    header[2].markdown("**Tyyppi**")
    header[3].markdown("**Tulos**")
    header[4].markdown("**Joukkueelle näkyvä**")
    header[5].markdown("**Avaa**")

    for row in rows:
        cols = st.columns([1.2, 2.6, 1.2, 1.0, 1.4, 0.8])
        cols[0].write(row["Päivä"])
        cols[1].write(row["Kenttä"])
        cols[2].write("Harjoitus" if row["Tyyppi"] == "harjoitus" else "Kisa")
        cols[3].markdown(f"<span style='color:{score_color(row['Alusta'], row['Tulos'])}; font-weight:700'>{row['Tulos']}</span>", unsafe_allow_html=True)
        cols[4].write(row["Joukkueelle näkyvä"])
        if cols[5].button("Avaa", key=f"open_round_{row['round_id']}"):
            st.session_state.history_selected_round_id = row["round_id"]
            st.rerun()

    if st.session_state.history_selected_round_id:
        st.divider()
        render_history_detail(st.session_state.history_selected_round_id)


def render_analysis(user_id):
    title_block("Analyysi")
    a, b, c, d = st.columns(4)
    date_from = a.date_input("Alkaen", value=None, key="anaf")
    date_to = b.date_input("Asti", value=None, key="anat")
    surface_filter = c.selectbox("Alusta", ["kaikki"] + SURFACE_OPTIONS, key="anas")
    type_filter = d.selectbox("Tyyppi", ["kaikki"] + ROUND_TYPE_OPTIONS, key="anat2")
    metrics = get_analysis_metrics(user_id, surface_filter=surface_filter, date_from=date_from, date_to=date_to, type_filter=type_filter)
    if not metrics:
        st.info("Analyysi näkyy, kun valmiita kierroksia löytyy.")
        return
    x1, x2, x3 = st.columns(3)
    x1.metric("Piikki %", f"{metrics['piikki']} %" if metrics['piikki'] is not None else "–")
    x2.metric("Attempts (avg)", str(metrics['attempts_avg']) if metrics['attempts_avg'] is not None else "–")
    x3.metric("Pitkät sarjat %", f"{metrics['pitkat']} %" if metrics['pitkat'] is not None else "–")
    y1, y2, y3, y4 = st.columns(4)
    y1.metric("Oikealle ohi", metrics['right_count'])
    y2.metric("Vasemmalle ohi", metrics['left_count'])
    y3.metric("Hitaat vauhtivirheet", metrics['slow_count'])
    y4.metric("Liian lujat vauhtivirheet", metrics['hard_count'])

    st.markdown("### Ohilyönnit ratatyypeittäin")
    miss_df = pd.DataFrame([
        {"Ratatyyppi": "Päättyvä rata", "Ohilyönnit": metrics['miss_by_type']['Päättyvä rata']},
        {"Ratatyyppi": "Kenttärata", "Ohilyönnit": metrics['miss_by_type']['Kenttärata']},
    ])
    st.bar_chart(miss_df.set_index("Ratatyyppi")[["Ohilyönnit"]])
    st.dataframe(miss_df, use_container_width=True, hide_index=True)
    st.caption("Ohilyönti = lyönti, joka ei mennyt sisään. Kenttäradoilla myös 'läpi' lasketaan ohiksi.")

    st.markdown("### Paikko-%")
    p1, p2, p3 = st.columns(3)
    p1.metric("Esteosumat", metrics['obstacle_hits_total'])
    p2.metric("Paikko-yritykset", metrics['obstacle_followup_total'])
    p3.metric("Paikko-%", "–" if metrics['paikko_pct'] is None else f"{metrics['paikko_pct']} %")
    st.caption("Paikko-% = jos lyönti osui esteeseen ja seuraava lyönti meni sisään.")

    if metrics.get('eterniitti'):
        et = metrics['eterniitti']
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
    title_block("Profiili")
    st.write(f"**Sähköposti:** {current_user_email() or '–'}")
    with st.form("profile_form"):
        display_name = st.text_input("Näkyvä nimi", value=current_name)
        if st.form_submit_button("Tallenna profiili"):
            update_profile_name(user_id, display_name)
            st.success("Profiili päivitetty.")
            st.rerun()


def main_view():
    user_id = current_user_id()
    render_topbar(user_id)
    if is_admin():
        st.info("Olet pääkäyttäjä. Voit muokata kenttiä, ratoja ja poistaa kenttiä.")
    view = st.session_state.view
    if view == "Etusivu":
        render_dashboard(user_id)
    elif view == "Kentät":
        render_courses(user_id)
    elif view == "Kierros":
        render_new_round(user_id)
    elif view == "Historia":
        render_history(user_id)
    elif view == "Analyysi":
        render_analysis(user_id)
    elif view == "Profiili":
        render_profile_tab(user_id)


apply_custom_css()
init_state()
restore_auth_session()
if current_user_id() is None:
    auth_view()
else:
    main_view()
