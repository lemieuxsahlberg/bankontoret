import streamlit as st
import pandas as pd
from datetime import date
from db import get_supabase

st.set_page_config(page_title="Bankontoret", page_icon="🏌️", layout="wide")

supabase = get_supabase()

# -----------------------------
# Session helpers
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
            current_user = supabase.auth.get_user()
            st.session_state.user = current_user.user if current_user else None
        except Exception:
            st.session_state.access_token = None
            st.session_state.refresh_token = None
            st.session_state.user = None


def persist_session_from_auth_response(auth_response):
    session = getattr(auth_response, "session", None)
    user = getattr(auth_response, "user", None)
    if session:
        st.session_state.access_token = session.access_token
        st.session_state.refresh_token = session.refresh_token
    st.session_state.user = user


init_state()
restore_auth_session()


# -----------------------------
# Data helpers
# -----------------------------
def get_current_user_id():
    if st.session_state.user:
        return st.session_state.user.id
    return None


def ensure_profile_exists(user_id: str, display_name: str):
    existing = supabase.table("profiles").select("user_id, display_name").eq("user_id", user_id).execute().data
    if not existing:
        supabase.table("profiles").insert({
            "user_id": user_id,
            "display_name": display_name or "Pelaaja"
        }).execute()
    elif display_name and existing[0].get("display_name") != display_name:
        supabase.table("profiles").update({"display_name": display_name}).eq("user_id", user_id).execute()


def get_profile(user_id: str):
    data = supabase.table("profiles").select("*").eq("user_id", user_id).execute().data
    return data[0] if data else None


def get_user_courses(user_id: str):
    data = supabase.table("courses").select("*").eq("owner_user_id", user_id).order("created_at").execute().data
    return data or []


def get_course_holes(course_id: str):
    data = supabase.table("course_holes").select("*").eq("course_id", course_id).order("hole_number").execute().data
    return data or []


def get_user_rounds(user_id: str):
    rounds = supabase.table("rounds").select("id, course_id, played_at, visibility, notes, created_at").eq("user_id", user_id).order("played_at", desc=True).execute().data or []
    courses = {c["id"]: c["name"] for c in get_user_courses(user_id)}

    enriched = []
    for r in rounds:
        holes = supabase.table("round_holes").select("total_strokes").eq("round_id", r["id"]).execute().data or []
        enriched.append({
            "Päivä": r["played_at"],
            "Kenttä": courses.get(r["course_id"], "Tuntematon kenttä"),
            "Näkyvyys": r["visibility"],
            "Ratoja": len(holes),
            "Lyönnit yhteensä": sum(h["total_strokes"] for h in holes),
            "Muistiinpanot": r.get("notes") or "",
            "round_id": r["id"],
        })
    return enriched


def get_analysis_data(user_id: str):
    rounds = supabase.table("rounds").select("id, played_at, course_id").eq("user_id", user_id).execute().data or []
    if not rounds:
        return None

    round_ids = [r["id"] for r in rounds]
    round_holes = []
    shots = []
    course_holes_cache = {}

    for rid in round_ids:
        rhs = supabase.table("round_holes").select("*").eq("round_id", rid).order("hole_sequence_number").execute().data or []
        round_holes.extend(rhs)
        for rh in rhs:
            if rh["course_hole_id"] not in course_holes_cache:
                ch = supabase.table("course_holes").select("*").eq("id", rh["course_hole_id"]).execute().data
                if ch:
                    course_holes_cache[rh["course_hole_id"]] = ch[0]
            sh = supabase.table("shots").select("*").eq("round_hole_id", rh["id"]).order("shot_number").execute().data or []
            shots.extend(sh)

    if not round_holes:
        return None

    rh_df = pd.DataFrame(round_holes)
    sh_df = pd.DataFrame(shots) if shots else pd.DataFrame(columns=["round_hole_id", "shot_number", "went_in", "went_through", "hit_obstacle", "direction_error", "speed_error"])
    ch_df = pd.DataFrame(course_holes_cache.values()) if course_holes_cache else pd.DataFrame(columns=["id", "is_ending_hole", "is_lane_hole", "has_obstacle"])

    if not ch_df.empty:
        ch_df = ch_df.rename(columns={"id": "course_hole_id"})
        rh_df = rh_df.merge(ch_df[["course_hole_id", "is_ending_hole", "is_lane_hole", "has_obstacle", "hole_number", "hole_name"]], on="course_hole_id", how="left")
    else:
        rh_df["is_ending_hole"] = False
        rh_df["is_lane_hole"] = False
        rh_df["has_obstacle"] = False

    return rh_df, sh_df


def compute_metrics(user_id: str):
    result = get_analysis_data(user_id)
    if result is None:
        return None
    rh_df, sh_df = result

    metrics = {
        "piikki": None,
        "instant_recover": None,
        "attempts_avg": None,
        "pitkat_sarjat": None,
        "full_reset": None,
        "virhe_jatkuu": None,
        "vahva_startti": None,
        "vahva_paatos": None,
    }

    if len(rh_df) == 0:
        return None

    # Piikki: 1 lyönti sisään kaikista radoista
    metrics["piikki"] = round((rh_df["went_straight_in"].astype(bool).mean() * 100), 1)

    # Ending-hole metrics
    ending_df = rh_df[rh_df["is_ending_hole"] == True].copy()
    if not ending_df.empty:
        metrics["attempts_avg"] = round(float(ending_df["total_strokes"].mean()), 2)
        metrics["pitkat_sarjat"] = round(float((ending_df["total_strokes"] >= 4).mean() * 100), 1)

        if not sh_df.empty:
            first_shots = sh_df[sh_df["shot_number"] == 1][["round_hole_id", "went_in"]].rename(columns={"went_in": "first_went_in"})
            second_shots = sh_df[sh_df["shot_number"] == 2][["round_hole_id", "went_in"]].rename(columns={"went_in": "second_went_in"})
            rec_df = ending_df[["id"]].rename(columns={"id": "round_hole_id"}).merge(first_shots, on="round_hole_id", how="left").merge(second_shots, on="round_hole_id", how="left")
            candidates = rec_df[rec_df["first_went_in"] == False]
            if len(candidates) > 0:
                metrics["instant_recover"] = round(float((candidates["second_went_in"] == True).mean() * 100), 1)

    # Hole outcome classification for next-hole rhythm
    if not sh_df.empty:
        shot_summary = sh_df.groupby("round_hole_id").agg(
            any_through=("went_through", "max"),
            any_obstacle=("hit_obstacle", "max"),
        ).reset_index()
        dir_any = sh_df.groupby("round_hole_id")["direction_error"].apply(lambda s: any(x != "none" for x in s)).reset_index(name="any_direction_error")
        speed_any = sh_df.groupby("round_hole_id")["speed_error"].apply(lambda s: any(x != "none" for x in s)).reset_index(name="any_speed_error")
        rh_df = rh_df.merge(shot_summary, left_on="id", right_on="round_hole_id", how="left")
        rh_df = rh_df.merge(dir_any, left_on="id", right_on="round_hole_id", how="left")
        rh_df = rh_df.merge(speed_any, left_on="id", right_on="round_hole_id", how="left")
    else:
        rh_df["any_through"] = False
        rh_df["any_obstacle"] = False
        rh_df["any_direction_error"] = False
        rh_df["any_speed_error"] = False

    rh_df["failed_hole"] = (
        (rh_df["total_strokes"] > 1)
        | (rh_df["any_through"] == True)
        | (rh_df["any_obstacle"] == True)
        | (rh_df["any_direction_error"] == True)
        | (rh_df["any_speed_error"] == True)
    )

    rh_df["good_hole"] = (
        (rh_df["went_straight_in"] == True)
        | (
            (rh_df["total_strokes"] == 1)
            & (rh_df["any_through"] != True)
            & (rh_df["any_obstacle"] != True)
            & (rh_df["any_direction_error"] != True)
            & (rh_df["any_speed_error"] != True)
        )
    )

    next_rows = []
    for round_id, group in rh_df.sort_values(["round_id", "hole_sequence_number"]).groupby("round_id"):
        group = group.sort_values("hole_sequence_number").reset_index(drop=True)
        for i in range(len(group) - 1):
            current_row = group.iloc[i]
            next_row = group.iloc[i + 1]
            if current_row["failed_hole"]:
                next_rows.append({
                    "next_good": bool(next_row["good_hole"]),
                    "next_failed": bool(next_row["failed_hole"]),
                })

    if next_rows:
        next_df = pd.DataFrame(next_rows)
        metrics["full_reset"] = round(float(next_df["next_good"].mean() * 100), 1)
        metrics["virhe_jatkuu"] = round(float(next_df["next_failed"].mean() * 100), 1)

    # Simple segment analysis per round: first third vs last third
    starts = []
    finishes = []
    for round_id, group in rh_df.sort_values(["round_id", "hole_sequence_number"]).groupby("round_id"):
        group = group.sort_values("hole_sequence_number").reset_index(drop=True)
        n = len(group)
        if n < 3:
            continue
        part = max(1, n // 3)
        start = group.iloc[:part]
        finish = group.iloc[-part:]
        starts.append((start["good_hole"].mean()) * 100)
        finishes.append((finish["good_hole"].mean()) * 100)

    if starts:
        metrics["vahva_startti"] = round(float(pd.Series(starts).mean()), 1)
    if finishes:
        metrics["vahva_paatos"] = round(float(pd.Series(finishes).mean()), 1)

    return metrics


# -----------------------------
# Auth UI
# -----------------------------
def auth_view():
    st.title("🏌️ Bankontoret")
    st.caption("Minigolftilastot kentittäin – käyttäjät, kierrokset ja analyysi")

    left, right = st.columns(2)

    with left:
        st.subheader("Kirjaudu")
        with st.form("login_form"):
            email = st.text_input("Sähköposti", key="login_email")
            password = st.text_input("Salasana", type="password", key="login_password")
            submitted = st.form_submit_button("Kirjaudu")
            if submitted:
                try:
                    auth_response = supabase.auth.sign_in_with_password({
                        "email": email,
                        "password": password,
                    })
                    persist_session_from_auth_response(auth_response)
                    user_id = get_current_user_id()
                    user_meta = getattr(st.session_state.user, "user_metadata", {}) or {}
                    display_name = user_meta.get("display_name") or email.split("@")[0]
                    ensure_profile_exists(user_id, display_name)
                    st.success("Kirjautuminen onnistui")
                    st.rerun()
                except Exception as e:
                    st.error(f"Kirjautuminen epäonnistui: {e}")

    with right:
        st.subheader("Luo käyttäjä")
        with st.form("signup_form"):
            display_name = st.text_input("Näyttönimi", key="signup_display_name")
            email = st.text_input("Sähköposti ", key="signup_email")
            password = st.text_input("Salasana ", type="password", key="signup_password")
            submitted = st.form_submit_button("Luo käyttäjä")
            if submitted:
                try:
                    auth_response = supabase.auth.sign_up({
                        "email": email,
                        "password": password,
                        "options": {
                            "data": {"display_name": display_name}
                        }
                    })
                    persist_session_from_auth_response(auth_response)
                    # Jos projektissa on email confirmation päällä, session voi olla None
                    user_obj = getattr(auth_response, "user", None)
                    if user_obj:
                        ensure_profile_exists(user_obj.id, display_name or email.split("@")[0])
                        st.success("Käyttäjä luotu. Jos sähköpostivahvistus on käytössä, vahvista sähköposti ennen kirjautumista.")
                    else:
                        st.success("Käyttäjä luotu. Tarkista sähköposti ja vahvista tili ennen kirjautumista.")
                except Exception as e:
                    st.error(f"Käyttäjän luonti epäonnistui: {e}")


# -----------------------------
# Main app UI
# -----------------------------
def main_app():
    user_id = get_current_user_id()
    profile = get_profile(user_id)
    display_name = (profile or {}).get("display_name", "Pelaaja")

    st.title("🏌️ Bankontoret")
    st.caption(f"Kirjautunut: {display_name}")

    top_col1, top_col2 = st.columns([5, 1])
    with top_col2:
        if st.button("Kirjaudu ulos"):
            try:
                supabase.auth.sign_out()
            except Exception:
                pass
            for key in ["access_token", "refresh_token", "user", "current_round_id", "current_course_id", "current_holes", "current_hole_pos"]:
                st.session_state[key] = None if key not in ("current_holes", "current_hole_pos") else ([] if key == "current_holes" else 0)
            st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(["Kentät", "Uusi kierros", "Historia", "Analyysi"])

    with tab1:
        st.subheader("Luo uusi kenttä")
        with st.form("new_course_form", clear_on_submit=True):
            course_name = st.text_input("Kentän nimi")
            location = st.text_input("Sijainti (valinnainen)")
            submitted = st.form_submit_button("Tallenna kenttä")
            if submitted:
                if not course_name.strip():
                    st.error("Anna kentälle nimi.")
                else:
                    try:
                        supabase.table("courses").insert({
                            "name": course_name.strip(),
                            "location": location.strip() or None,
                            "owner_user_id": user_id,
                        }).execute()
                        st.success("Kenttä tallennettu.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Kentän tallennus epäonnistui: {e}")

        courses = get_user_courses(user_id)
        if not courses:
            st.info("Et ole vielä luonut yhtään kenttää.")
        else:
            course_map = {f'{c["name"]}': c for c in courses}
            selected_label = st.selectbox("Valitse kenttä ratojen hallintaan", list(course_map.keys()))
            selected_course = course_map[selected_label]
            st.markdown(f"**Valittu kenttä:** {selected_course['name']}")

            holes = get_course_holes(selected_course["id"])
            if holes:
                hole_rows = []
                for h in holes:
                    hole_rows.append({
                        "#": h["hole_number"],
                        "Nimi": h.get("hole_name") or "",
                        "Tyyppi": "Päättyvä" if h["is_ending_hole"] else "Kenttärata",
                        "Esteellinen": "Kyllä" if h["has_obstacle"] else "Ei",
                    })
                st.dataframe(pd.DataFrame(hole_rows), use_container_width=True, hide_index=True)
            else:
                st.info("Kentälle ei ole vielä lisätty ratoja.")

            st.subheader("Lisää rata")
            with st.form("new_hole_form", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    hole_number = st.number_input("Radan numero", min_value=1, max_value=60, value=(len(holes) + 1 if holes else 1), step=1)
                with c2:
                    hole_name = st.text_input("Radan nimi (valinnainen)")
                with c3:
                    hole_type = st.radio("Ratatyyppi", ["Päättyvä rata", "Kenttärata"], horizontal=True)
                has_obstacle = st.checkbox("Esteellinen rata")
                submitted = st.form_submit_button("Tallenna rata")
                if submitted:
                    try:
                        supabase.table("course_holes").insert({
                            "course_id": selected_course["id"],
                            "hole_number": int(hole_number),
                            "hole_name": hole_name.strip() or None,
                            "is_ending_hole": hole_type == "Päättyvä rata",
                            "is_lane_hole": hole_type == "Kenttärata",
                            "has_obstacle": bool(has_obstacle),
                        }).execute()
                        st.success("Rata tallennettu.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Radan tallennus epäonnistui: {e}")

    with tab2:
        courses = get_user_courses(user_id)
        if not courses:
            st.info("Luo ensin kenttä Kentät-välilehdellä.")
        else:
            course_map = {f'{c["name"]}': c for c in courses}
            st.subheader("Aloita kierros")

            if st.session_state.current_round_id is None:
                with st.form("start_round_form"):
                    selected_label = st.selectbox("Kenttä", list(course_map.keys()), key="start_round_course")
                    played_at = st.date_input("Päivä", value=date.today())
                    visibility = st.selectbox("Näkyvyys", ["private", "shared"], help="Tiiminäkyvyys lisätään myöhemmin.")
                    notes = st.text_area("Muistiinpanot (valinnainen)")
                    submitted = st.form_submit_button("Aloita kierros")

                    if submitted:
                        selected_course = course_map[selected_label]
                        holes = get_course_holes(selected_course["id"])
                        if not holes:
                            st.error("Valitulla kentällä ei ole ratoja. Lisää radat ensin Kentät-välilehdellä.")
                        else:
                            try:
                                result = supabase.table("rounds").insert({
                                    "user_id": user_id,
                                    "course_id": selected_course["id"],
                                    "played_at": played_at.isoformat(),
                                    "visibility": visibility,
                                    "notes": notes.strip() or None,
                                }).execute()
                                round_id = result.data[0]["id"]
                                st.session_state.current_round_id = round_id
                                st.session_state.current_course_id = selected_course["id"]
                                st.session_state.current_holes = holes
                                st.session_state.current_hole_pos = 0
                                st.success("Kierros aloitettu.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Kierroksen aloitus epäonnistui: {e}")
            else:
                holes = st.session_state.current_holes or []
                pos = st.session_state.current_hole_pos or 0
                if pos >= len(holes):
                    st.success("Kierros on valmis 🎉")
                    if st.button("Päätä kierros"):
                        st.session_state.current_round_id = None
                        st.session_state.current_course_id = None
                        st.session_state.current_holes = []
                        st.session_state.current_hole_pos = 0
                        st.rerun()
                else:
                    hole = holes[pos]
                    st.subheader(f"Rata {hole['hole_number']}")
                    if hole.get("hole_name"):
                        st.caption(hole["hole_name"])
                    st.write(f"**Tyyppi:** {'Päättyvä rata' if hole['is_ending_hole'] else 'Kenttärata'}")
                    st.write(f"**Esteellinen:** {'Kyllä' if hole['has_obstacle'] else 'Ei'}")

                    with st.form(f"hole_form_{hole['id']}"):
                        strokes = st.number_input("Lyönnit", min_value=1, max_value=20, value=1, step=1)

                        shots_payload = []
                        if strokes == 1:
                            st.info("Piikki: yksi lyönti, ei lisäkysymyksiä.")
                        else:
                            st.markdown("### Lyöntikohtaiset tiedot")
                            for i in range(1, int(strokes) + 1):
                                with st.expander(f"Lyönti {i}", expanded=(i == 1 or i == int(strokes))):
                                    default_went_in = (i == int(strokes))
                                    went_in = st.checkbox(f"Lyönti {i} meni sisään", value=default_went_in, key=f"went_in_{hole['id']}_{i}")
                                    went_through = st.checkbox(f"Lyönti {i} meni läpi", key=f"through_{hole['id']}_{i}") if hole["is_lane_hole"] else False
                                    hit_obstacle = st.checkbox(f"Lyönti {i} osui esteeseen", key=f"obst_{hole['id']}_{i}") if hole["has_obstacle"] else False
                                    direction_error = st.selectbox(
                                        f"Suunta – lyönti {i}",
                                        ["none", "left", "right"],
                                        key=f"dir_{hole['id']}_{i}",
                                        format_func=lambda x: {"none": "Ei suuntavirhettä", "left": "Vasen", "right": "Oikea"}[x],
                                    )
                                    speed_error = st.selectbox(
                                        f"Vauhti – lyönti {i}",
                                        ["none", "too_slow", "too_hard"],
                                        key=f"spd_{hole['id']}_{i}",
                                        format_func=lambda x: {"none": "Ei vauhtivirhettä", "too_slow": "Liian hidas", "too_hard": "Liian luja"}[x],
                                    )
                                    shots_payload.append({
                                        "shot_number": i,
                                        "went_in": bool(went_in),
                                        "went_through": bool(went_through),
                                        "hit_obstacle": bool(hit_obstacle),
                                        "direction_error": direction_error,
                                        "speed_error": speed_error,
                                    })

                        notes = st.text_area("Muistiinpanot radasta (valinnainen)")
                        submitted = st.form_submit_button("Tallenna rata")

                        if submitted:
                            try:
                                rh_result = supabase.table("round_holes").insert({
                                    "round_id": st.session_state.current_round_id,
                                    "course_hole_id": hole["id"],
                                    "hole_sequence_number": hole["hole_number"],
                                    "total_strokes": int(strokes),
                                    "went_straight_in": bool(strokes == 1),
                                    "notes": notes.strip() or None,
                                }).execute()
                                round_hole_id = rh_result.data[0]["id"]

                                if strokes == 1:
                                    supabase.table("shots").insert({
                                        "round_hole_id": round_hole_id,
                                        "shot_number": 1,
                                        "went_in": True,
                                        "went_through": False,
                                        "hit_obstacle": False,
                                        "direction_error": "none",
                                        "speed_error": "none",
                                    }).execute()
                                else:
                                    if shots_payload[-1]["went_in"] is not True:
                                        shots_payload[-1]["went_in"] = True
                                    for shot in shots_payload:
                                        shot["round_hole_id"] = round_hole_id
                                    supabase.table("shots").insert(shots_payload).execute()

                                st.session_state.current_hole_pos += 1
                                st.success("Rata tallennettu.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Radan tallennus epäonnistui: {e}")

    with tab3:
        st.subheader("Historia")
        rounds = get_user_rounds(user_id)
        if not rounds:
            st.info("Ei vielä tallennettuja kierroksia.")
        else:
            df = pd.DataFrame(rounds)
            display_df = df.drop(columns=["round_id"])
            st.dataframe(display_df, use_container_width=True, hide_index=True)

            st.markdown("### Kierroksen tarkemmat tiedot")
            round_options = {f"{row['Päivä']} – {row['Kenttä']} ({row['Lyönnit yhteensä']} lyöntiä)": row["round_id"] for _, row in df.iterrows()}
            selected_label = st.selectbox("Valitse kierros", list(round_options.keys()))
            selected_round_id = round_options[selected_label]

            rhs = supabase.table("round_holes").select("*").eq("round_id", selected_round_id).order("hole_sequence_number").execute().data or []
            details = []
            for rh in rhs:
                ch = supabase.table("course_holes").select("hole_number, hole_name, is_ending_hole, is_lane_hole, has_obstacle").eq("id", rh["course_hole_id"]).execute().data
                ch = ch[0] if ch else {}
                details.append({
                    "Rata": ch.get("hole_number", rh["hole_sequence_number"]),
                    "Nimi": ch.get("hole_name") or "",
                    "Tyyppi": "Päättyvä" if ch.get("is_ending_hole") else "Kenttärata",
                    "Lyönnit": rh["total_strokes"],
                    "Piikki": "Kyllä" if rh["went_straight_in"] else "Ei",
                    "Muistiinpanot": rh.get("notes") or "",
                })
            st.dataframe(pd.DataFrame(details), use_container_width=True, hide_index=True)

    with tab4:
        st.subheader("Analyysi")
        metrics = compute_metrics(user_id)
        if not metrics:
            st.info("Analyysi näkyy, kun olet tallentanut ainakin yhden kierroksen.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Piikki %", "–" if metrics["piikki"] is None else f"{metrics['piikki']} %")
            c2.metric("Instant recover %", "–" if metrics["instant_recover"] is None else f"{metrics['instant_recover']} %")
            c3.metric("Attempts (avg)", "–" if metrics["attempts_avg"] is None else str(metrics["attempts_avg"]))
            c4.metric("Pitkät sarjat %", "–" if metrics["pitkat_sarjat"] is None else f"{metrics['pitkat_sarjat']} %")

            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Full reset %", "–" if metrics["full_reset"] is None else f"{metrics['full_reset']} %")
            c6.metric("Virhe jatkuu %", "–" if metrics["virhe_jatkuu"] is None else f"{metrics['virhe_jatkuu']} %")
            c7.metric("Vahva startti %", "–" if metrics["vahva_startti"] is None else f"{metrics['vahva_startti']} %")
            c8.metric("Vahva päätös %", "–" if metrics["vahva_paatos"] is None else f"{metrics['vahva_paatos']} %")

            st.markdown("### Miten luvut on laskettu")
            st.markdown(
                """
- **Piikki** = osuus radoista, jotka menivät suoraan yhdellä lyönnillä.
- **Instant recover** = päättyvillä radoilla osuus tilanteista, joissa 1. yritys epäonnistui mutta 2. meni sisään.
- **Attempts (avg)** = päättyvien ratojen keskimääräinen lyönti-/yritysmäärä.
- **Pitkät sarjat** = päättyvien ratojen osuus, joissa tarvittiin vähintään 4 yritystä.
- **Full reset** = osuus tilanteista, joissa epäonnistunutta rataa seurasi hyvä seuraava rata.
- **Virhe jatkuu** = osuus tilanteista, joissa epäonnistunutta rataa seurasi myös epäonnistunut seuraava rata.
- **Vahva startti / Vahva päätös** = kierrosten ensimmäisen ja viimeisen kolmanneksen hyvien ratojen osuus.
                """
            )


if get_current_user_id() is None:
    auth_view()
else:
    main_app()
