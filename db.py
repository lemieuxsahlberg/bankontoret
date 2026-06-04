from supabase import create_client, Client
import streamlit as st

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["https://jwzsqzwmiihxmmyptuvu.supabase.co/rest/v1/"]
    key = st.secrets["sb_publishable_J9UQ5m5EaMe-4GFZgclCCw_WEMLHz1Q"]
    return create_client(url, key)
