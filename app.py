import streamlit as st
import pandas as pd
from datetime import date
from db import get_supabase

st.set_page_config(page_title="Bankontoret", page_icon="🏌️", layout="wide")
supabase = get_supabase()

SURFACE_OPTIONS = ["eterniitti", "betoni", "huopa", "MOS"]
PAR_BY_SURFACE = {"eterniitti": 18, "betoni": 27, "huopa": 36, "MOS": 36}
ROUND_TYPE_OPTIONS = ["harjoitus", "kisa"]
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
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def restore_auth_session():
    if st.session_state.access_token and st.session_state.refresh_token:
        try:
            supabase.auth.set_session(
                st.session_state.access_token,
                st.session_state.refresh_token,
            )
            user_response = supabase.auth.get_user()
            st.session_state.user = user_response.user if user_response else None
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
    rows = (
        supabase.table("profiles")
        .select("user_id, display_name")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    wanted_name = (display_name or "Pelaaja").strip() or "Pelaaja"
    if not rows:
        supabase.table("profiles").insert(
            {"user_id": user_id, "display_name": wanted_name}
        ).execute()
    elif rows[0].get("display_name") != wanted_name:
        supabase.table("profiles").update({"display_name": wanted_name}).eq(
            "user_id", user_id
        ).execute()


def get_profile(user_id):
    rows = (
        supabase.table("profiles")
        .select("*")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def get_all_courses():
    try:
        return supabase.table("courses").select("*").order("name").execute().data or []
    except Exception:
        return []


def get_course_holes(course_id):
    return (
        supabase.table("course_holes")
        .select("*")
        .eq("course_id", course_id)
        .order("hole_number")
        .execute()
        .data
        or []
    )


def get_rounds(user_id):
    return (
        supabase.table("rounds")
        .select("*")
        .eq("user_id", user_id)
        .order("played_at", desc=True)
        .execute()
        .data
        or []
    )


def get_round(round_id):
    rows = (
        supabase.table("rounds").select("*").eq("id", round_id).execute().data or []
    )
    return rows[0] if rows else None


def get_round_holes(round_id):
    return (
        supabase.table("round_holes")
        .select("*")
        .eq("round_id", round_id)
        .order("hole_sequence_number")
        .execute()
        .data
        or []
    )


def get_round_hole_by_sequence(round_id, hole_sequence_number):
    rows = (
        supabase.table("round_holes")
        .select("*")
        .eq("round_id", round_id)
        .eq("hole_sequence_number", hole_sequence_number)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def get_shots(round_hole_id):
    return (
        supabase.table("shots")
        .select("*")
        .eq("round_hole_id", round_hole_id)
        .order("shot_number")
        .execute()
        .data
        or []
    )


def delete_round(round_id):
    supabase.table("rounds").delete().eq("id", round_id).execute()


def delete_round_hole_shots(round_hole_id):
    supabase.table("shots").delete().eq("round_hole_id", round_hole_id).execute()


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
        round_hole_id = existing["id"]
        supabase.table("round_holes").update(payload).eq("id", round_hole_id).execute()
        delete_round_hole_shots(round_hole_id)
    else:
        result = supabase.table("round_holes").insert(payload).execute()
        round_hole_id = result.data[0]["id"]

    if int(total_strokes) == 1:
        supabase.table("shots").insert(
            {
                "round_hole_id": round_hole_id,
                "shot_number": 1,
                "went_in": True,
                "went_through": False,
                "hit_obstacle": False,
                "direction_error": "none",
                "speed_error": "none",
            }
        ).execute()
    else:
        rows = []
        for shot in shot_rows:
            row = shot.copy()
            row["round_hole_id"] = round_hole_id
            rows.append(row)
        if rows:
            if not rows[-1]["went_in"]:
                rows[-1]["went_in"] = True
            supabase.table("shots").insert(rows).execute()


def get_course_par(surface):
    return PAR_BY_SURFACE.get(surface or "", None)


def get_result_band(surface, total_score):
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
    label, color = get_result_band(surface, total_score)
    st.markdown(
        f"<div style='display:inline-block;padding:0.35rem 0.7rem;border-radius:999px;background:{color};color:white;font-weight:600'>{label}</div>",
        unsafe_allow_html=True,
    )


def get_course_hole_averages(user_id, course_id):
    rounds = (
        supabase.table("rounds")
        .select("id")
        .eq("user_id", user_id)
        .eq("course_id", course_id)
        .execute()
        .data
        or []
    )
    if not rounds:
        return []

    round_holes_all = []
    for r in rounds:
        round_holes_all.extend(get_round_holes(r["id"]))

    if not round_holes_all:
        return []

    course_holes = get_course_holes(course_id)
    hole_number_map = {h["id"]: h["hole_number"] for h in course_holes}
    rows = []
    for rh in round_holes_all:
        rows.append(
            {
                "Rata": hole_number_map.get(
                    rh["course_hole_id"], rh.get("hole_sequence_number")
                ),
                "Lyönnit": rh.get("total_strokes", 0),
            }
        )

    df = pd.DataFrame(rows)
    avg_df = df.groupby("Rata", as_index=False)["Lyönnit"].mean().sort_values("Rata")
    avg_df["Lyönnit"] = avg_df["Lyönnit"].round(2)
    return avg_df.to_dict("records")


def choose_sidebar_course(user_id):
    if st.session_state.current_course_id:
        return st.session_state.current_course_id
    rounds = get_rounds(user_id)
    if rounds:
        return rounds[0].get("course_id")
    return None


def get_analysis_metrics(user_id):
    rounds = get_rounds(user_id)
    if not rounds:
        return None

    all_round_holes = []
    ending_attempts = []
    direction_counts = {"left": 0, "right": 0}
    speed_counts = {"too_slow": 0, "too_hard": 0}
    eterniitti_scores = []
    courses = {c["id"]: c for c in get_all_courses()}

    for rnd in rounds:
        rhs = get_round_holes(rnd["id"])
        for rh in rhs:
            all_round_holes.append(rh)
            shots = get_shots(rh["id"])
            for shot in shots:
                if shot.get("direction_error") == "left":
                    direction_counts["left"] += 1
                elif shot.get("direction_error") == "right":
                    direction_counts["right"] += 1

                if shot.get("speed_error") == "too_slow":
                    speed_counts["too_slow"] += 1
                elif shot.get("speed_error") == "too_hard":
                    speed_counts["too_hard"] += 1

            ch = (
                supabase.table("course_holes")
                .select("is_ending_hole")
                .eq("id", rh["course_hole_id"])
                .execute()
                .data
                or []
            )
            if ch and ch[0].get("is_ending_hole"):
                ending_attempts.append(rh.get("total_strokes", 0))

            course = courses.get(rnd["course_id"])
            if course and course.get("surface") == "eterniitti":
                score = rh.get("total_strokes", 0)
                if 1 <= score <= 7:
                    eterniitti_scores.append(score)

    if not all_round_holes:
        return None

    metrics = {
        "piikki": round(
            pd.Series([1 if h.get("went_straight_in") else 0 for h in all_round_holes]).mean()
            * 100,
            1,
        ),
        "attempts_avg": round(pd.Series(ending_attempts).mean(), 2)
        if ending_attempts
        else None,
        "pitkat": round((pd.Series(ending_attempts) >= 4).mean() * 100, 1)
        if ending_attempts
        else None,
        "left_count": direction_counts["left"],
        "right_count": direction_counts["right"],
        "slow_count": speed_counts["too_slow"],
        "hard_count": speed_counts["too_hard"],
        "eterniitti": None,
    }

    if eterniitti_scores:
        total = len(eterniitti_scores)
        piikki_count = sum(1 for s in eterniitti_scores if s == 1)
        two_count = sum(1 for s in eterniitti_scores if s == 2)
        bad_count = sum(1 for s in eterniitti_scores if 3 <= s <= 7)
        non_piikki = [s for s in eterniitti_scores if s > 1]
        non_piikki_total = len(non_piikki)
        pelastettu_count = sum(1 for s in non_piikki if s == 2)
        jatkuu_count = sum(1 for s in non_piikki if 3 <= s <= 7)

        metrics["eterniitti"] = {
            "piikki_pct": round((piikki_count / total) * 100, 1),
            "kakkonen_pct": round((two_count / total) * 100, 1),
            "three_to_seven_pct": round((bad_count / total) * 100, 1),
            "pelastettu_kakkoseen_pct": round(
                (pelastettu_count / non_piikki_total) * 100, 1
            )
            if non_piikki_total > 0
            else None,
            "jatkuu_huono_pct": round((jatkuu_count / non_piikki_total) * 100, 1)
            if non_piikki_total > 0
            else None,
        }

    return metrics


def render_sidebar(user_id):
    with st.sidebar:
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

        course_id = choose_sidebar_course(user_id)
        if not course_id:
            return

        courses = {c["id"]: c for c in get_all_courses()}
        course = courses.get(course_id)
        averages = get_course_hole_averages(user_id, course_id)

        if course and averages:
            st.markdown("### Oma keskiarvo")
            st.caption(course.get("name", "Kenttä"))
            for row in averages:
                st.write(f"Rata {row['Rata']}: {row['Lyönnit']}")


def auth_view():
    st.title("🏌️ Bankontoret")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Kirjaudu")
        with st.form("login"):
            email = st.text_input("Sähköposti")
            password = st.text_input("Salasana", type="password")
            if st.form_submit_button("Kirjaudu"):
                try:
                    r = supabase.auth.sign_in_with_password(
                        {"email": email, "password": password}
                    )
                    save_auth_session(r)
                    ensure_profile_exists(current_user_id(), email.split("@")[0])
                    st.rerun()
                except Exception as e:
                    st.error(f"Kirjautuminen epäonnistui: {e}")

    with col2:
        st.subheader("Luo käyttäjä")
        with st.form("signup"):
            name = st.text_input("Näyttönimi")
            email = st.text_input("Sähköposti", key="signup_email")
            password = st.text_input("Salasana", type="password", key="signup_password")
            if st.form_submit_button("Luo käyttäjä"):
                try:
                    supabase.auth.sign_up(
                        {
                            "email": email,
                            "password": password,
                            "options": {"data": {"display_name": name}},
                        }
                    )
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
            elif any(
                (c.get("name") or "").strip().lower() == course_name.strip().lower()
                for c in all_courses
            ):
                st.warning("Kenttä löytyy jo. Käytä olemassa olevaa kenttää listalta.")
            else:
                try:
                    supabase.table("courses").insert(
                        {
                            "name": course_name.strip(),
                            "location": location.strip() or None,
                            "surface": surface,
                            "owner_user_id": user_id,
                        }
                    ).execute()
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
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "#": h["hole_number"],
                        "Nimi": h.get("hole_name") or "",
                        "Tyyppi": "Päättyvä" if h.get("is_ending_hole") else "Kenttärata",
                        "Esteellinen": "Kyllä" if h.get("has_obstacle") else "Ei",
                    }
                    for h in holes
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

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
                supabase.table("course_holes").insert(
                    {
                        "course_id": course["id"],
                        "hole_number": next_no,
                        "hole_name": hole_name.strip() or None,
                        "is_ending_hole": hole_type == "Päättyvä rata",
                        "is_lane_hole": hole_type == "Kenttärata",
                        "has_obstacle": bool(has_obstacle),
                    }
                ).execute()
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
            round_type = st.selectbox("Kierroksen tyyppi", ROUND_TYPE_OPTIONS)
            can_start = len(holes) == 18
            if not can_start:
                st.warning(f"Tällä kentällä on {len(holes)}/18 rataa.")
            if st.form_submit_button("Aloita kierros", disabled=not can_start):
                try:
                    r = supabase.table("rounds").insert(
                        {
                            "user_id": user_id,
                            "course_id": course["id"],
                            "played_at": played_at.isoformat(),
                            "visibility": visibility,
                            "notes": notes.strip() or None,
                            "round_type": round_type,
                        }
                    ).execute()
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
        total = sum(r.get("total_strokes", 0) for r in rhs)
        st.success("Kierros valmis 🎉")
        c1, c2, c3 = st.columns(3)
        c1.metric("Tulos", total)
        c2.metric("Alusta", course.get("surface") if course else "–")
        c3.metric("Par", PAR_BY_SURFACE.get((course or {}).get("surface"), "–"))
        render_band_badge((course or {}).get("surface"), total)
        if st.button("Päätä kierros"):
            clear_round_state()
            st.rerun()
        return

    existing_map = {
        rh["hole_sequence_number"]: rh for rh in get_round_holes(st.session_state.current_round_id)
    }
    hole = holes[pos]
    hole_id = hole["id"]
    existing = existing_map.get(hole["hole_number"])

    st.markdown(f"### Rata {hole['hole_number']}")
    if hole.get("hole_name"):
        st.caption(hole["hole_name"])
    st.write(f"**Tyyppi:** {'Päättyvä rata' if hole.get('is_ending_hole') else 'Kenttärata'}")
    st.write(f"**Esteellinen:** {'Kyllä' if hole.get('has_obstacle') else 'Ei'}")

    default_strokes = existing.get("total_strokes", 1) if existing else 1
    strokes = st.segmented_control(
        "Lyönnit",
        options=list(range(1, 8)),
        selection_mode="single",
        default=default_strokes if default_strokes in list(range(1, 8)) else 1,
        key=f"strokes_{hole_id}_{pos}",
    )
    if strokes is None:
        strokes = 1

    notes = st.text_input(
        "Muistiinpanot radasta (valinnainen)",
        value=existing.get("notes", "") if existing else "",
        key=f"notes_{hole_id}_{pos}",
    )

    existing_shots = get_shots(existing["id"]) if existing else []
    existing_shot_map = {s["shot_number"]: s for s in existing_shots}

    shot_rows = []
    if int(strokes) > 1:
        st.markdown("### Lyöntikortit")
        for i in range(1, int(strokes) + 1):
            prev = existing_shot_map.get(i, {})
            st.markdown(f"**Lyönti {i}**")
            c1, c2, c3 = st.columns(3)
            with c1:
                went_in = st.checkbox(
                    "Sisään",
                    value=prev.get("went_in", i == int(strokes)),
                    key=f"in_{hole_id}_{pos}_{i}",
                )
            with c2:
                went_through = (
                    st.checkbox(
                        "Läpi",
                        value=prev.get("went_through", False),
                        key=f"through_{hole_id}_{pos}_{i}",
                    )
                    if hole.get("is_lane_hole")
                    else False
                )
            with c3:
                hit_obstacle = (
                    st.checkbox(
                        "Este",
                        value=prev.get("hit_obstacle", False),
                        key=f"obst_{hole_id}_{pos}_{i}",
                    )
                    if hole.get("has_obstacle")
                    else False
                )

            c4, c5 = st.columns(2)
            with c4:
                direction_error = st.radio(
                    "Suunta",
                    ["none", "left", "right"],
                    horizontal=True,
                    index=["none", "left", "right"].index(prev.get("direction_error", "none")),
                    key=f"dir_{hole_id}_{pos}_{i}",
                    format_func=lambda x: {"none": "ei", "left": "vasen", "right": "oikea"}[x],
                )
            with c5:
                speed_error = st.radio(
                    "Vauhti",
                    ["none", "too_slow", "too_hard"],
                    horizontal=True,
                    index=["none", "too_slow", "too_hard"].index(prev.get("speed_error", "none")),
                    key=f"spd_{hole_id}_{pos}_{i}",
                    format_func=lambda x: {
                        "none": "ei",
                        "too_slow": "hidas",
                        "too_hard": "liian luja",
                    }[x],
                )

            shot_rows.append(
                {
                    "shot_number": i,
                    "went_in": bool(went_in),
                    "went_through": bool(went_through),
                    "hit_obstacle": bool(hit_obstacle),
                    "direction_error": direction_error,
                    "speed_error": speed_error,
                }
            )
            st.divider()

    col_a, col_b, col_c = st.columns(3)

    if col_a.button("⬅ Edellinen rata", disabled=(pos == 0)):
        st.session_state.current_hole_pos = max(0, pos - 1)
        st.rerun()

    if col_c.button("Tallenna rata", type="primary"):
        try:
            upsert_round_hole(st.session_state.current_round_id, hole, strokes, notes, shot_rows)
            st.session_state.current_hole_pos = min(len(holes), pos + 1)
            st.rerun()
        except Exception as e:
            st.error(f"Radan tallennus epäonnistui: {e}")

    if col_b.button("Peruuta tämän radan tiedot"):
        st.rerun()


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
        band_color = get_result_band(course.get("surface"), total)[1]
        rows.append(
            {
                "round_id": rnd["id"],
                "Päivä": rnd.get("played_at"),
                "Kenttä": course.get("name", "Tuntematon"),
                "Tyyppi": rnd.get("round_type", "harjoitus"),
                "Alusta": course.get("surface") or "–",
                "Par": PAR_BY_SURFACE.get(course.get("surface"), "–"),
                "Ratoja": len(rhs),
                "Tulos": total,
                "Muistiinpanot": rnd.get("notes") or "",
                "_score_color": band_color,
            }
        )

    df = pd.DataFrame(rows)
    display_df = df[
        ["Päivä", "Kenttä", "Tyyppi", "Alusta", "Par", "Ratoja", "Tulos", "Muistiinpanot"]
    ].copy()

    def style_scores(row):
        color = df.loc[row.name, "_score_color"]
        return [
            "color: " + color + "; font-weight: 700" if col == "Tulos" else ""
            for col in display_df.columns
        ]

    st.dataframe(
        display_df.style.apply(style_scores, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Keskiarvot")
    avg_all = round(df["Tulos"].mean(), 2) if not df.empty else None
    avg_practice = (
        round(df[df["Tyyppi"] == "harjoitus"]["Tulos"].mean(), 2)
        if not df[df["Tyyppi"] == "harjoitus"].empty
        else None
    )
    avg_comp = (
        round(df[df["Tyyppi"] == "kisa"]["Tulos"].mean(), 2)
        if not df[df["Tyyppi"] == "kisa"].empty
        else None
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Kaikkien kierrosten keskiarvo", avg_all if avg_all is not None else "–")
    c2.metric(
        "Harjoituskierrosten keskiarvo",
        avg_practice if avg_practice is not None else "–",
    )
    c3.metric("Kisakierrosten keskiarvo", avg_comp if avg_comp is not None else "–")

    st.markdown("### Muokkaa tai poista tallennettu kierros")
    round_map = {
        f"{row['Päivä']} – {row['Kenttä']} ({row['Tulos']})": row["round_id"]
        for _, row in df.iterrows()
    }
    selected_label = st.selectbox("Valitse kierros", list(round_map.keys()))
    selected_round_id = round_map[selected_label]
    round_record = next(r for r in rounds if r["id"] == selected_round_id)

    with st.form("edit_round_form"):
        round_type = st.selectbox(
            "Kierroksen tyyppi",
            ROUND_TYPE_OPTIONS,
            index=ROUND_TYPE_OPTIONS.index(round_record.get("round_type", "harjoitus"))
            if round_record.get("round_type", "harjoitus") in ROUND_TYPE_OPTIONS
            else 0,
        )
        notes = st.text_area("Kierroksen muistiinpanot", value=round_record.get("notes") or "")

        rhs = get_round_holes(selected_round_id)
        edited_scores = {}
        for rh in rhs:
            course_hole = (
                supabase.table("course_holes")
                .select("hole_number")
                .eq("id", rh["course_hole_id"])
                .execute()
                .data
                or []
            )
            hole_no = course_hole[0]["hole_number"] if course_hole else rh.get("hole_sequence_number")
            edited_scores[rh["id"]] = st.number_input(
                f"Rata {hole_no} – lyönnit",
                min_value=1,
                max_value=20,
                value=int(rh.get("total_strokes", 1)),
                step=1,
                key=f"edit_rh_{rh['id']}",
            )

        save_changes = st.form_submit_button("Tallenna muutokset")
        if save_changes:
            try:
                supabase.table("rounds").update(
                    {"round_type": round_type, "notes": notes.strip() or None}
                ).eq("id", selected_round_id).execute()

                for rh in rhs:
                    supabase.table("round_holes").update(
                        {
                            "total_strokes": int(edited_scores[rh["id"]]),
                            "went_straight_in": int(edited_scores[rh["id"]]) == 1,
                        }
                    ).eq("id", rh["id"]).execute()

                st.success("Kierros päivitetty.")
                st.rerun()
            except Exception as e:
                st.error(f"Kierroksen päivitys epäonnistui: {e}")

    if st.button("Poista valittu kierros", type="secondary"):
        try:
            delete_round(selected_round_id)
            st.success("Kierros poistettu.")
            st.rerun()
        except Exception as e:
            st.error(f"Kierroksen poisto epäonnistui: {e}")


def render_analysis(user_id):
    st.subheader("Analyysi")
    metrics = get_analysis_metrics(user_id)
    if not metrics:
        st.info("Analyysi näkyy, kun olet tallentanut ainakin yhden kierroksen.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Piikki %", f"{metrics['piikki']} %" if metrics["piikki"] is not None else "–")
    c2.metric(
        "Attempts (avg)",
        str(metrics["attempts_avg"]) if metrics["attempts_avg"] is not None else "–",
    )
    c3.metric(
        "Pitkät sarjat %",
        f"{metrics['pitkat']} %" if metrics["pitkat"] is not None else "–",
    )

    st.markdown("### Virhejakaumat")
    c4, c5, c6, c7 = st.columns(4)
    c4.metric("Oikealle ohi", metrics["right_count"])
    c5.metric("Vasemmalle ohi", metrics["left_count"])
    c6.metric("Hitaat vauhtivirheet", metrics["slow_count"])
    c7.metric("Liian lujat vauhtivirheet", metrics["hard_count"])

    if metrics.get("eterniitti"):
        et = metrics["eterniitti"]
        st.markdown("### Eterniitti – piikin jälkeen")
        e1, e2, e3, e4, e5 = st.columns(5)
        e1.metric("Piikki %", f"{et['piikki_pct']} %")
        e2.metric("Kakkonen %", f"{et['kakkonen_pct']} %")
        e3.metric("3–7 %", f"{et['three_to_seven_pct']} %")
        e4.metric(
            "Pelastettu 2 %",
            "–" if et["pelastettu_kakkoseen_pct"] is None else f"{et['pelastettu_kakkoseen_pct']} %",
        )
        e5.metric(
            "Jatkuu 3–7 %",
            "–" if et["jatkuu_huono_pct"] is None else f"{et['jatkuu_huono_pct']} %",
        )


def main_view():
    user_id = current_user_id()
    profile = get_profile(user_id)

    st.title("🏌️ Bankontoret")
    st.caption(f"Kirjautunut: {(profile or {}).get('display_name') or 'Pelaaja'}")
    render_sidebar(user_id)

    t1, t2, t3, t4 = st.tabs(["Kentät", "Uusi kierros", "Historia", "Analyysi"])
    with t1:
        render_courses(user_id)
    with t2:
        render_new_round(user_id)
    with t3:
        render_history(user_id)
    with t4:
        render_analysis(user_id)


init_state()
restore_auth_session()

if current_user_id() is None:
    auth_view()
else:
    main_view()
)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(app_code)

py_compile.compile('app.py', doraise=True)
print('saved ok', os.path.getsize('app.py'))
"}
