"""
Bulk Google Indexing Checker — Streamlit app (v2)
-----------------------------------------------------
Run with:  streamlit run indexchecker.py

ONE-TIME SETUP — see the setup guide already shared. Requires
credentials.json (OAuth Desktop app client) in this same folder.

New in this version:
  - Shows which Google account is currently authenticated
  - "Logout / switch account" button to clear cached login
  - Clearer summary: indexed pages, not-indexed pages + reasons

Install: pip install streamlit google-api-python-client google-auth-httplib2 google-auth-oauthlib pandas
"""

import os
import pickle
import time

import pandas as pd
import streamlit as st

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Added userinfo.email so we can show which account is logged in
SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

st.set_page_config(page_title="Google Indexing Checker", page_icon="🔎", layout="wide")


def get_redirect_uri():
    """
    Must exactly match one of the 'Authorized redirect URIs' on the
    Web application OAuth client in Google Cloud Console.
    Set this in .streamlit/secrets.toml as app_url, e.g.:
        app_url = "https://your-app-name.streamlit.app"
    """
    return st.secrets["google_oauth"]["app_url"].rstrip("/") + "/"


def build_flow():
    client_config = {
        "web": {
            "client_id": st.secrets["google_oauth"]["client_id"],
            "client_secret": st.secrets["google_oauth"]["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [get_redirect_uri()],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=get_redirect_uri(),
        autogenerate_code_verifier=True,
    )
    return flow


# ---------- Auth ----------
def get_credentials():
    """
    Returns valid credentials if logged in, otherwise None.
    Call ensure_login() first to trigger the redirect flow.
    """
    creds = st.session_state.get("creds")
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        st.session_state["creds"] = creds
    return creds if creds and creds.valid else None


def ensure_login():
    """
    Handles the OAuth redirect dance for a hosted (non-local) Streamlit app.
    - If not logged in: shows a 'Login with Google' link.
    - If Google just redirected back with ?code=...: exchanges it for credentials.
    """
    creds = get_credentials()
    if creds:
        return creds

    params = st.query_params
    if "code" in params:
        try:
            flow = build_flow()
            # Restore the code_verifier generated when the login link was built —
            # a fresh Flow object here otherwise has none, causing
            # "Missing code verifier" since Streamlit reruns the whole script.
            code_verifier = st.session_state.get("code_verifier")
            if code_verifier:
                flow.code_verifier = code_verifier
            flow.fetch_token(code=params["code"])
            creds = flow.credentials
            st.session_state["creds"] = creds
            st.session_state.pop("code_verifier", None)
            st.query_params.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Login failed: {e}")
            st.query_params.clear()
        return None
    else:
        flow = build_flow()
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="select_account",
        )
        # Save the verifier now so we can restore it after the redirect
        st.session_state["code_verifier"] = flow.code_verifier
        st.link_button("🔑 Login with Google", auth_url, type="primary")
        return None


def get_logged_in_email(creds):
    try:
        oauth2_service = build("oauth2", "v2", credentials=creds)
        info = oauth2_service.userinfo().get().execute()
        return info.get("email", "Unknown")
    except Exception:
        return "Unknown"


def logout():
    for key in ("creds", "logged_in_email", "results", "quota_hit"):
        st.session_state.pop(key, None)
    st.query_params.clear()


def inspect_url(service, site_url, inspection_url):
    body = {"inspectionUrl": inspection_url, "siteUrl": site_url}
    response = service.urlInspection().index().inspect(body=body).execute()
    result = response.get("inspectionResult", {})
    index_status = result.get("indexStatusResult", {})

    return {
        "URL": inspection_url,
        "Verdict": index_status.get("verdict", "UNKNOWN"),
        "Coverage State": index_status.get("coverageState", ""),
        "Indexing State": index_status.get("indexingState", ""),
        "Last Crawl Time": index_status.get("lastCrawlTime", ""),
        "Google Canonical": index_status.get("googleCanonical", ""),
        "User Canonical": index_status.get("userCanonical", ""),
        "Robots.txt State": index_status.get("robotsTxtState", ""),
        "Page Fetch State": index_status.get("pageFetchState", ""),
    }


# ---------- UI ----------
st.title("🔎 Bulk Google Indexing Checker")
st.caption("Uses Google's official Search Console URL Inspection API — the real index data, not a guess.")

with st.expander("⚙️ Setup checklist (click to expand)"):
    st.markdown(
        """
        1. Create a project at [Google Cloud Console](https://console.cloud.google.com/)
        2. Enable the **Google Search Console API** (APIs & Services → Library)
        3. Configure the **OAuth consent screen / Google Auth Platform** (External, add your login email as a test user)
        4. Create an OAuth client ID with **Application type: Web application**
           (not Desktop app — this app runs on a server, not your machine)
        5. Under **Authorized redirect URIs**, add your deployed app's URL exactly,
           e.g. `https://your-app-name.streamlit.app/`
        6. In Streamlit Cloud → your app → Settings → Secrets, add:
           ```
           [google_oauth]
           client_id = "your-client-id.apps.googleusercontent.com"
           client_secret = "your-client-secret"
           app_url = "https://your-app-name.streamlit.app"
           ```
        7. Make sure the Google account you log in with has access to the site's Search Console property
        """
    )

# ---------- Account status bar / login ----------
creds = ensure_login()

if creds:
    if "logged_in_email" not in st.session_state:
        st.session_state["logged_in_email"] = get_logged_in_email(creds)
    acc_col1, acc_col2 = st.columns([4, 1])
    with acc_col1:
        st.success(f"Logged in as: **{st.session_state['logged_in_email']}**")
    with acc_col2:
        if st.button("🔓 Logout / switch account"):
            logout()
            st.rerun()
else:
    st.warning("Please log in with Google to continue.")
    st.stop()

st.divider()

col1, col2 = st.columns([2, 1])
with col1:
    site_url = st.text_input(
        "Search Console property (must match exactly)",
        value="https://www.reset.in/",
        help="Use 'sc-domain:reset.in' instead if yours is set up as a Domain property.",
    )
with col2:
    delay = st.number_input("Delay between checks (seconds)", min_value=0.0, value=1.0, step=0.5)

input_mode = st.radio("How do you want to provide URLs?", ["Paste URLs", "Upload a .txt file"], horizontal=True)

urls = []
if input_mode == "Paste URLs":
    urls_text = st.text_area(
        "One URL per line",
        height=200,
        placeholder="https://www.reset.in/\nhttps://www.reset.in/products/emulsion\n...",
    )
    if urls_text.strip():
        urls = [u.strip() for u in urls_text.splitlines() if u.strip()]
else:
    uploaded = st.file_uploader("Upload a .txt file with one URL per line", type=["txt"])
    if uploaded:
        urls = [u.decode("utf-8").strip() for u in uploaded.readlines() if u.strip()]

if urls:
    st.info(f"{len(urls)} URL(s) loaded.")

run = st.button("🚀 Check indexing status", type="primary", disabled=not urls)

if run:
    try:
        service = build("searchconsole", "v1", credentials=creds)
    except Exception as e:
        st.error(f"Could not start Search Console service: {e}")
        st.stop()

    results = []
    progress = st.progress(0.0, text="Starting...")
    status_area = st.empty()
    quota_hit = False

    for i, url in enumerate(urls, 1):
        status_area.text(f"[{i}/{len(urls)}] Checking {url}")
        try:
            row = inspect_url(service, site_url, url)
            results.append(row)
        except HttpError as e:
            status = getattr(e, "resp", None)
            if status is not None and status.status == 429:
                st.warning("Daily quota (2,000/property) hit — stopping. Partial results below.")
                quota_hit = True
                break
            else:
                results.append({"URL": url, "Verdict": "ERROR", "Coverage State": str(e)})
        progress.progress(i / len(urls), text=f"{i}/{len(urls)} checked")
        time.sleep(delay)

    progress.empty()
    status_area.empty()

    # Persist results across reruns (e.g. clicking Download) so they aren't lost
    st.session_state["results"] = results
    st.session_state["quota_hit"] = quota_hit

# Render results from session_state if present — survives download-button reruns
if "results" in st.session_state and st.session_state["results"]:
    results = st.session_state["results"]
    quota_hit = st.session_state.get("quota_hit", False)

    if results:
        df = pd.DataFrame(results)
        indexed_df = df[df["Verdict"] == "PASS"].copy()
        not_indexed_df = df[df["Verdict"] != "PASS"].copy()

        st.subheader("📊 Summary")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total checked", len(df))
        c2.metric("✅ Indexed", len(indexed_df))
        c3.metric("❌ Not indexed / issues", len(not_indexed_df))

        st.subheader("✅ Indexed pages")
        if not indexed_df.empty:
            show_cols = ["URL", "Last Crawl Time", "Coverage State"]
            indexed_sorted = indexed_df[show_cols].sort_values("Last Crawl Time", ascending=False)
            st.dataframe(indexed_sorted, use_container_width=True, hide_index=True)
        else:
            st.write("None of the checked URLs are indexed yet.")

        st.subheader("❌ Not indexed yet — with reason")
        if not not_indexed_df.empty:
            show_cols = ["URL", "Verdict", "Coverage State", "Robots.txt State", "Page Fetch State"]
            st.dataframe(not_indexed_df[show_cols], use_container_width=True, hide_index=True)
        else:
            st.write("Everything checked is indexed. 🎉")

        with st.expander("Full raw data (all columns)"):
            st.dataframe(df, use_container_width=True, hide_index=True)

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download full results as CSV",
            data=csv_bytes,
            file_name="indexed_results.csv",
            mime="text/csv",
            key="download_results_csv",
        )

        if st.button("🗑️ Clear results"):
            st.session_state.pop("results", None)
            st.session_state.pop("quota_hit", None)
            st.rerun()

        if quota_hit:
            st.info("Re-run tomorrow with the remaining URLs once quota resets.")
    else:
        st.warning("No results returned.")
