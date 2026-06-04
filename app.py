import streamlit as st
import pandas as pd
from datetime import date
from db import get_supabase

st.set_page_config(page_title="Bankontoret", page_icon="🏌️", layout="wide")

supabase = get_supabase()

# =============================
# Session state
# =============================
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


def clear_round_state():
    st.session_state.current_round_id = None
    st.session_state.current_course_id = None
    st.session_state.current_holes = []
    st.session_state.current_hole_pos = 0


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


def save_auth_session(auth_response):
    session = getattr(auth_response, "session", None)
    user = getattr(auth_response, "user", None)
    if session:
        st.session_state.access_token = session.access_token
        st.session_state.refresh_token = session.refresh_token
    st.session_state.user = user


init_state()
restore_auth_session()

# =============================
# Helpers
# =============================
def current_user_id():
    return st.session_state.user.id if st.session_state.user else None


def ensure_profile_exists(user_id: str, display_name: str | None):
    existing = supabase.table("profiles").select("user_id, display_name").eq("user_id", user_id).execute().data or []
    wanted_name = (display_name or "Pelaaja").strip() or "Pelaaja"

    if not existing:
        supabase.table("profiles").insert({
            "user_id": user_id,
            "display_name": wanted_name,
        }).execute()
    else:
        current_name = existing[0].get("display_name") or ""
        if wanted_name and wanted_name != current_name:
            supabase.table("profiles").update({"display_name": wanted_name}).eq("user_id", user_id).execute()


def get_profile(user_id: str):
    rows = supabase.table("profiles").select("*").eq("user_id", user_id).execute().data or []
    return rows[0] if rows else None


def get_courses(user_id: str):
    return supabase.table("courses").select("*").eq("owner_user_id", user_id).order("created_at").execute().data or []


def get_course_holes(course_id: str):
    return supabase.table("course_holes").select("*").eq("course_id", course_id).order("hole_number").execute().data or []


def get_rounds(user_id: str):
    return supabase.table("rounds").select("*").eq("user_id", user_id).order("played_at", desc=True).execute().data or []


def get_round_holes(round_id: str):
    return supabase.table("round_holes").select("*").eq("round_id", round_id).order("hole_sequence_number").execute().data or []


def get_shots(round_hole_id: str):
    return supabase.table("shots").select("*").eq("round_hole_id", round_hole_id).order("shot_number").execute().data or []


def good_hole_from_row(rh_row: dict, shots: list[dict]) -> bool:
    if rh_row.get("went_straight_in"):
        return True
    if rh_row.get("total_strokes", 0) != 1:
        return False

    if not shots:
        return True

    for shot in shots:
        if shot.get("went_through"):
            return False
        if shot.get("hit_obstacle"):
            return False
        if shot.get("direction_error") not in (None, "none"):
            return False
        if shot.get("speed_error") not in (None, "none"):
            return False
    return True


def failed_hole_from_row(rh_row: dict, shots: list[dict]) -> bool:
    if rh_row.get("total_strokes", 0) > 1:
        return True
    for shot in shots:
        if shot.get("went_through"):
            return True
        if shot.get("hit_obstacle"):
            return True
        if shot.get("direction_error") not in (None, "none"):
            return True
        if shot.get("speed_error") not in (None, "none"):
            return True
    return False


def calculate_metrics(user_id: str):
    rounds = get_rounds(user_id)
    if not rounds:
        return None

    all_round_holes = []
    ending_round_holes = []
    next_hole_pairs = []
    start_scores = []
    finish_scores = []

    for rnd in rounds:
        rhs = get_round_holes(rnd["id"])
        if not rhs:
            continue

        enriched = []
        for rh in rhs:
            ch_rows = supabase.table("course_holes").select("*").eq("id", rh["course_hole_id"]).execute().data or []
            ch = ch_rows[0] if ch_rows else {}
            shots = get_shots(rh["id"])
            enriched.append({
                "round_hole": rh,
                "course_hole": ch,
                "shots": shots,
                "good": good_hole_from_row(rh, shots),
                "failed": failed_hole_from_row(rh, shots),
            })

        enriched.sort(key=lambda x: x["round_hole"]["hole_sequence_number"])
        all_round_holes.extend(enriched)

        # next-hole analysis
        for i in range(len(enriched) - 1):
            current_hole = enriched[i]
            next_hole = enriched[i + 1]
            if current_hole["failed"]:
                next_hole_pairs.append({
                    "next_good": next_hole["good"],
                    "next_failed": next_hole["failed"],
                })

        # start / finish analysis: first third vs last third
        part = max(1, len(enriched) // 3)
        start_scores.append(pd.Series([1 if row["good"] else 0 for row in enriched[:part]]).mean() * 100)
        finish_scores.append(pd.Series([1 if row["good"] else 0 for row in enriched[-part:]]).mean() * 100)

        for row in enriched:
            if row["course_hole"].get("is_ending_hole"):
                ending_round_holes.append(row)

    if not all_round_holes:
        return None

    metrics = {
        "piikki": round(pd.Series([1 if x["round_hole"].get("went_straight_in") else 0 for x in all_round_holes]).mean() * 100, 1),
        "instant_recover": None,
        "attempts_avg": None,
        "pitkat_sarjat": None,
        "full_reset": None,
        "virhe_jatkuu": None,
        "vahva_startti": round(pd.Series(start_scores).mean(), 1) if start_scores else None,
        "vahva_paatos": round(pd.Series(finish_scores).mean(), 1) if finish_scores else None,
    }

    if ending_round_holes:
        attempts = [x["round_hole"].get("total_strokes", 0) for x in ending_round_holes]
        metrics["attempts_avg"] = round(pd.Series(attempts).mean(), 2)
        metrics["pitkat_sarjat"] = round((pd.Series(attempts) >= 4).mean() * 100, 1)

        instant_candidates = []
        for row in ending_round_holes:
            shots = row["shots"]
            first = next((s for s in shots if s.get("shot_number") == 1), None)
            second = next((s for s in shots if s.get("shot_number") == 2), None)
            if first and first.get("went_in") is False:
                instant_candidates.append(1 if second and second.get("went_in") is True else 0)
        if instant_candidates:
            metrics["instant_recover"] = round(pd.Series(instant_candidates).mean() * 100, 1)

    if next_hole_pairs:
        metrics["full_reset"] = round(pd.Series([1 if x["next_good"] else 0 for x in next_hole_pairs]).mean() * 100, 1)
        metrics["virhe_jatkuu"] = round(pd.Series([1 if x["next_failed"] else 0 for x in next_hole_pairs]).mean() * 100, 1)

    return metrics


# =============================
# Auth UI
# =============================
def auth_view():
    st.title("🏌️ Bankontoret")
    st.caption("Minigolftilastot kentittäin")

    col1, col2 = st.columns(2)

    with col1:
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
                    save_auth_session(auth_response)

                    user_id = current_user_id()
                    user_meta = getattr(st.session_state.user, "user_metadata", {}) or {}
                    display_name = user_meta.get("display_name") or email.split("@")[0]
                    ensure_profile_exists(user_id, display_name)

                    st.success("Kirjautuminen onnistui")
                    st.rerun()
                except Exception as e:
                    st.error(f"Kirjautuminen epäonnistui: {e}")

    with col2:
        st.subheader("Luo käyttäjä")
        with st.form("signup_form"):
            display_name = st.text_input("Näyttönimi", key="signup_display_name")
            email = st.text_input("Sähköposti", key="signup_email")
            password = st.text_input("Salasana", type="password", key="signup_password")
            submitted = st.form_submit_button("Luo käyttäjä")
            if submitted:
                try:
                    supabase.auth.sign_up({
                        "email": email,
                        "password": password,
                        "options": {
                            "data": {"display_name": display_name}
                        }
                    })
                    st.success(
                        "Käyttäjä luotu. Jos sähköpostivahvistus on käytössä, vahvista sähköposti ja kirjaudu sitten sisään."
                    )
                except Exception as e:
                    st.error(f"Käyttäjän luonti epäonnistui: {e}")


# =============================
# Main UI
# =============================
def render_courses_tab(user_id: str):
    st.subheader("Kentät")

    with st.form("course_form", clear_on_submit=True):
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

    courses = get_courses(user_id)
    if not courses:
        st.info("Et ole vielä lisännyt kenttiä.")
        return

    course_map = {course["name"]: course for course in courses}
    selected_name = st.selectbox("Valitse kenttä ratojen hallintaan", list(course_map.keys()))
    selected_course = course_map[selected_name]

    st.markdown(f"**Valittu kenttä:** {selected_course['name']}")
    holes = get_course_holes(selected_course["id"])

    if holes:
        df = pd.DataFrame([
            {
                "#": h["hole_number"],
                "Nimi": h.get("hole_name") or "",
                "Tyyppi": "Päättyvä" if h.get("is_ending_hole") else "Kenttärata",
                "Esteellinen": "Kyllä" if h.get("has_obstacle") else "Ei",
            }
            for h in holes
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Kentälle ei ole vielä lisätty ratoja.")

    st.markdown("### Lisää rata")
    with st.form("hole_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            hole_number = st.number_input("Radan numero", min_value=1, max_value=60, value=(len(holes) + 1 if holes else 1), step=1)
        with c2:
            hole_name = st.text_input("Radan nimi (valinnainen)")
        with c3:
            hole_type = st.radio("Ratatyyppi", ["Päättyvä rata", "Kenttärata"], horizontal=True)
        has_obstacle = st.checkbox("Esteellinen")
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


def render_new_round_tab(user_id: str):
    st.subheader("Uusi kierros")
    courses = get_courses(user_id)
    if not courses:
        st.info("Luo ensin kenttä Kentät-välilehdellä.")
        return

    course_map = {course["name"]: course for course in courses}

    if st.session_state.current_round_id is None:
        with st.form("start_round_form"):
            selected_name = st.selectbox("Kenttä", list(course_map.keys()))
            played_at = st.date_input("Päivä", value=date.today())
            visibility = st.selectbox("Näkyvyys", ["private", "shared"])
            notes = st.text_area("Muistiinpanot (valinnainen)")
            submitted = st.form_submit_button("Aloita kierros")
            if submitted:
                selected_course = course_map[selected_name]
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
                        st.session_state.current_round_id = result.data[0]["id"]
                        st.session_state.current_course_id = selected_course["id"]
                        st.session_state.current_holes = holes
                        st.session_state.current_hole_pos = 0
                        st.success("Kierros aloitettu.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Kierroksen aloitus epäonnistui: {e}")
        return

    holes = st.session_state.current_holes or []
    pos = st.session_state.current_hole_pos or 0

    if pos >= len(holes):
        st.success("Kierros valmis 🎉")
        if st.button("Päätä kierros"):
            clear_round_state()
            st.rerun()
        return

    hole = holes[pos]
    st.markdown(f"### Rata {hole['hole_number']}")
    if hole.get("hole_name"):
        st.caption(hole["hole_name"])

    st.write(f"**Tyyppi:** {'Päättyvä rata' if hole['is_ending_hole'] else 'Kenttärata'}")
    st.write(f"**Esteellinen:** {'Kyllä' if hole['has_obstacle'] else 'Ei'}")

    with st.form(f"play_hole_{hole['id']}"):
        strokes = st.number_input("Lyönnit", min_value=1, max_value=20, value=1, step=1)

        shot_rows = []
        if strokes == 1:
            st.info("Piikki – yksi lyönti, ei lisäkysymyksiä.")
        else:
            st.markdown("### Lyöntikohtaiset tiedot")
            for i in range(1, int(strokes) + 1):
                with st.expander(f"Lyönti {i}", expanded=(i == 1 or i == int(strokes))):
                    went_in = st.checkbox(
                        f"Lyönti {i} meni sisään",
                        value=(i == int(strokes)),
                        key=f"went_in_{hole['id']}_{i}",
                    )
                    went_through = st.checkbox(
                        f"Lyönti {i} meni läpi",
                        key=f"went_through_{hole['id']}_{i}",
                    ) if hole["is_lane_hole"] else False
                    hit_obstacle = st.checkbox(
                        f"Lyönti {i} osui esteeseen",
                        key=f"hit_obstacle_{hole['id']}_{i}",
                    ) if hole["has_obstacle"] else False
                    direction_error = st.selectbox(
                        f"Suunta – lyönti {i}",
                        ["none", "left", "right"],
                        key=f"direction_error_{hole['id']}_{i}",
                        format_func=lambda x: {
                            "none": "Ei suuntavirhettä",
                            "left": "Vasen",
                            "right": "Oikea",
                        }[x],
                    )
                    speed_error = st.selectbox(
                        f"Vauhti – lyönti {i}",
                        ["none", "too_slow", "too_hard"],
                        key=f"speed_error_{hole['id']}_{i}",
                        format_func=lambda x: {
                            "none": "Ei vauhtivirhettä",
                            "too_slow": "Liian hidas",
                            "too_hard": "Liian luja",
                        }[x],
                    )
                    shot_rows.append({
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
                    if shot_rows and shot_rows[-1]["went_in"] is not True:
                        shot_rows[-1]["went_in"] = True
                    payload = []
                    for row in shot_rows:
                        item = row.copy()
                        item["round_hole_id"] = round_hole_id
                        payload.append(item)
                    supabase.table("shots").insert(payload).execute()

                st.session_state.current_hole_pos += 1
                st.success("Rata tallennettu.")
                st.rerun()
            except Exception as e:
                st.error(f"Radan tallennus epäonnistui: {e}")


def render_history_tab(user_id: str):
    st.subheader("Historia")
    rounds = get_rounds(user_id)
    courses = {c["id"]: c["name"] for c in get_courses(user_id)}

    if not rounds:
        st.info("Ei vielä tallennettuja kierroksia.")
        return

    rows = []
    for rnd in rounds:
        rhs = get_round_holes(rnd["id"])
        rows.append({
            "Päivä": rnd["played_at"],
            "Kenttä": courses.get(rnd["course_id"], "Tuntematon kenttä"),
            "Näkyvyys": rnd["visibility"],
            "Ratoja": len(rhs),
            "Lyönnit yhteensä": sum(rh.get("total_strokes", 0) for rh in rhs),
            "Muistiinpanot": rnd.get("notes") or "",
            "round_id": rnd["id"],
        })

    df = pd.DataFrame(rows)
    st.dataframe(df.drop(columns=["round_id"]), use_container_width=True, hide_index=True)

    st.markdown("### Kierroksen tarkemmat tiedot")
    round_map = {
        f"{row['Päivä']} – {row['Kenttä']} ({row['Lyönnit yhteensä']} lyöntiä)": row["round_id"]
        for _, row in df.iterrows()
    }
    selected = st.selectbox("Valitse kierros", list(round_map.keys()))
    selected_round_id = round_map[selected]

    details = []
    rhs = get_round_holes(selected_round_id)
    for rh in rhs:
        ch_rows = supabase.table("course_holes").select("*").eq("id", rh["course_hole_id"]).execute().data or []
        ch = ch_rows[0] if ch_rows else {}
        details.append({
            "Rata": ch.get("hole_number", rh["hole_sequence_number"]),
            "Nimi": ch.get("hole_name") or "",
            "Tyyppi": "Päättyvä" if ch.get("is_ending_hole") else "Kenttärata",
            "Lyönnit": rh.get("total_strokes", 0),
            "Piikki": "Kyllä" if rh.get("went_straight_in") else "Ei",
            "Muistiinpanot": rh.get("notes") or "",
        })

    st.dataframe(pd.DataFrame(details), use_container_width=True, hide_index=True)


def render_analysis_tab(user_id: str):
    st.subheader("Analyysi")
    metrics = calculate_metrics(user_id)
    if not metrics:
        st.info("Analyysi näkyy, kun olet tallentanut ainakin yhden kierroksen.")
        return

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
- **Attempts (avg)** = päättyvien ratojen keskimääräinen yritys-/lyöntimäärä.
- **Pitkät sarjat** = päättyvien ratojen osuus, joissa tarvittiin vähintään 4 yritystä.
- **Full reset** = osuus tilanteista, joissa epäonnistunutta rataa seurasi hyvä seuraava rata.
- **Virhe jatkuu** = osuus tilanteista, joissa epäonnistunutta rataa seurasi myös epäonnistunut seuraava rata.
- **Vahva startti / Vahva päätös** = kierrosten ensimmäisen ja viimeisen kolmanneksen hyvien ratojen osuus.
        """
    )


def main_view():
    user_id = current_user_id()
    profile = get_profile(user_id)
    display_name = (profile or {}).get("display_name") or "Pelaaja"

    st.title("🏌️ Bankontoret")
    st.caption(f"Kirjautunut: {display_name}")

    top_left, top_right = st.columns([5, 1])
    with top_right:
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

    tab1, tab2, tab3, tab4 = st.tabs(["Kentät", "Uusi kierros", "Historia", "Analyysi"])
    with tab1:
        render_courses_tab(user_id)
    with tab2:
        render_new_round_tab(user_id)
    with tab3:
        render_history_tab(user_id)
    with tab4:
        render_analysis_tab(user_id)


if current_user_id() is None:
    auth_view()
else:
    main_view()
