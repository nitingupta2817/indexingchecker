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
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Added userinfo.email so we can show which account is logged in
SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
TOKEN_FILE = "token.pickle"
CREDENTIALS_FILE = "credentials.json"

st.set_page_config(page_title="Google Indexing Checker", page_icon="🔎", layout="wide")


# ---------- Auth ----------
def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"{CREDENTIALS_FILE} not found. Download it from Google Cloud "
                    "Console (OAuth client, Desktop app type) and place it in the "
                    "same folder as this script."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return creds


def get_logged_in_email(creds):
    try:
        oauth2_service = build("oauth2", "v2", credentials=creds)
        info = oauth2_service.userinfo().get().execute()
        return info.get("email", "Unknown")
    except Exception:
        return "Unknown"


def logout():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    for key in ("creds", "logged_in_email"):
        st.session_state.pop(key, None)


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

with st.expander("⚙️ First-time setup checklist (click to expand)"):
    st.markdown(
        """
        1. Create a project at [Google Cloud Console](https://console.cloud.google.com/)
        2. Enable the **Google Search Console API** (APIs & Services → Library)
        3. Configure the **OAuth consent screen / Google Auth Platform** (External, add your login email as a test user)
        4. Create an **OAuth client ID** (Application type: **Desktop app**), download the JSON
        5. Rename it to `credentials.json`, place it in the same folder as this script
        6. Make sure the Google account you log in with has access to the site's Search Console property
        """
    )

# ---------- Account status bar ----------
if "creds" not in st.session_state:
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "rb") as f:
                st.session_state["creds"] = pickle.load(f)
        except Exception:
            pass

acc_col1, acc_col2 = st.columns([4, 1])
with acc_col1:
    if "creds" in st.session_state and st.session_state["creds"]:
        if "logged_in_email" not in st.session_state:
            st.session_state["logged_in_email"] = get_logged_in_email(st.session_state["creds"])
        st.success(f"Logged in as: **{st.session_state['logged_in_email']}**")
    else:
        st.info("Not logged in yet. You'll be prompted when you run a check.")
with acc_col2:
    if st.button("🔓 Logout / switch account"):
        logout()
        st.rerun()

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
        with st.spinner("Authenticating with Google (a browser window may open)..."):
            creds = get_credentials()
            st.session_state["creds"] = creds
            st.session_state["logged_in_email"] = get_logged_in_email(creds)
        service = build("searchconsole", "v1", credentials=creds)
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    except Exception as e:
        st.error(f"Authentication failed: {e}")
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