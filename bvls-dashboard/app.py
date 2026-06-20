#!/usr/bin/env python3
"""BVLS World Meet 2026 live Streamlit dashboard."""

import hmac
import importlib.util
import os
import time
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import plotly.express as px
import streamlit as st

ADULT_PACKAGES = [
    "Beaver Bronze",
    "Moose Silver",
    "Cobra Chicken Gold",
    "Lion VIP Diamond",
]
LUAU_TITLE = "Lakeshore Luau - Pre BVWM 2026 Mini Event"
LUAU_PACKAGE = "Lakeshore Luau Mini Event"
CORRECTIONS_FILE = "09_dashboard_corrections.csv"
FILES = {
    "summary": "00_run_summary.csv",
    "raw": "01_raw_order_lines.csv",
    "package_totals": "02_package_totals.csv",
    "fixed_items": "03_fixed_items_to_order.csv",
    "meal_counts": "04_meal_counts.csv",
    "shirt_counts": "05_shirt_size_counts.csv",
    "hat_counts": "06_hat_choice_counts.csv",
    "exceptions": "07_exceptions_review.csv",
    "attendee_detail": "08_attendee_order_detail.csv",
}
DEFAULT_FOLDER = os.getenv("DATA_DIR", "bvls_worldmeet_results")
DEFAULT_SHOP_DOMAIN = "bearded-villains-lakeshore.myshopify.com"
EXPORTER_FILENAME = "bvls_worldmeet_export.py"

st.set_page_config(
    page_title="BVLS World Meet 2026 Dashboard",
    page_icon=":material/monitoring:",
    layout="wide",
)


def empty_df() -> pd.DataFrame:
    return pd.DataFrame()


def clean(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def find_col(df: pd.DataFrame, names: list[str]) -> Optional[str]:
    lookup = {column.lower().strip(): column for column in df.columns}
    for name in names:
        hit = lookup.get(name.lower().strip())
        if hit:
            return hit
    return None


def qty(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0).astype(int)


@st.cache_data(ttl=30, show_spinner=False)
def load_from_folder(folder: str) -> Dict[str, pd.DataFrame]:
    base = Path(folder).expanduser()
    data = {}
    for key, filename in FILES.items():
        path = base / filename
        data[key] = pd.read_csv(path, encoding="utf-8-sig") if path.exists() else empty_df()
    return data


def count_df(df: pd.DataFrame, name_cols: list[str], qty_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return empty_df()
    name_col = find_col(df, name_cols)
    qty_col = find_col(df, qty_cols)
    if not name_col or not qty_col:
        return empty_df()
    out = df[[name_col, qty_col]].copy()
    out.columns = ["Name", "Quantity"]
    out["Name"] = out["Name"].apply(clean).replace("", "Not Specified")
    out["Quantity"] = qty(out["Quantity"])
    return out.groupby("Name", as_index=False)["Quantity"].sum().sort_values("Quantity", ascending=False)


def metric_from_summary(summary: pd.DataFrame, metric_name: str, default: str = "") -> str:
    if summary.empty:
        return default
    metric_col = find_col(summary, ["Metric", "key"])
    value_col = find_col(summary, ["Value", "value"])
    if not metric_col or not value_col:
        return default
    mask = summary[metric_col].astype(str).str.strip().str.lower() == metric_name.lower()
    return str(summary.loc[mask, value_col].iloc[0]) if mask.any() else default


def to_int(value) -> int:
    try:
        return int(float(value))
    except Exception:
        return 0


def bar_chart(df: pd.DataFrame, title: str, x_title: str = "", horizontal: bool = False, height: int = 360):
    if df.empty:
        st.info(f"No data loaded for {title}.")
        return
    if horizontal:
        plot_df = df.sort_values("Quantity", ascending=True)
        figure = px.bar(plot_df, x="Quantity", y="Name", orientation="h", text="Quantity", title=title)
        figure.update_layout(xaxis_title="Quantity", yaxis_title=x_title or "Item", height=height)
    else:
        figure = px.bar(df, x="Name", y="Quantity", text="Quantity", title=title)
        figure.update_layout(xaxis_title=x_title or "Option", yaxis_title="Quantity", height=height)
    figure.update_traces(textposition="outside")
    figure.update_layout(margin=dict(l=20, r=20, t=60, b=20))
    st.plotly_chart(figure, use_container_width=True)


def download_button(df: pd.DataFrame, filename: str, label: str):
    st.download_button(
        label=label,
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=filename,
        mime="text/csv",
        use_container_width=True,
    )


def missing_qty(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    mask = df["Name"].astype(str).str.lower().eq("not specified")
    return int(df.loc[mask, "Quantity"].sum()) if mask.any() else 0


def prepare_fixed_df(fixed: pd.DataFrame) -> pd.DataFrame:
    if fixed.empty:
        return empty_df()
    item_col = find_col(fixed, ["Item", "item"])
    qty_col = find_col(fixed, ["Quantity", "quantity"])
    if not item_col or not qty_col:
        return empty_df()
    out = fixed.copy()
    out[item_col] = out[item_col].apply(clean)
    out[qty_col] = qty(out[qty_col])
    return out


def normalized_choice(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().replace("", "Not Specified")


def add_record_ids(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    order_col = find_col(out, ["Order", "order_name"])
    package_col = find_col(out, ["Package"])
    quantity_col = find_col(out, ["Quantity", "Orderable Quantity", "Current Quantity"])
    order = out[order_col].fillna("").astype(str) if order_col else pd.Series("", index=out.index)
    package = out[package_col].fillna("").astype(str) if package_col else pd.Series("", index=out.index)
    quantity = out[quantity_col].fillna(0).astype(str) if quantity_col else pd.Series("0", index=out.index)
    base = order + "|" + package + "|" + quantity
    occurrence = base.groupby(base).cumcount().add(1).astype(str)
    out.insert(0, "Record ID", base + "|" + occurrence)
    return out


def load_corrections(base: Optional[Path]) -> pd.DataFrame:
    if base is None or not (base / CORRECTIONS_FILE).exists():
        return empty_df()
    return pd.read_csv(base / CORRECTIONS_FILE, encoding="utf-8-sig").fillna("")


def apply_corrections(df: pd.DataFrame, corrections: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = add_record_ids(df)
    if corrections.empty or "Record ID" not in corrections.columns:
        return out
    saved = corrections.drop_duplicates("Record ID", keep="last").set_index("Record ID")
    editable_cols = ["Attendee Names", "Food Choice", "T-Shirt Size", "Hat Choice", "Review Status", "Review Notes"]
    for column in editable_cols:
        if column not in out.columns:
            out[column] = ""
        if column in saved.columns:
            mapped = out["Record ID"].map(saved[column])
            mask = mapped.notna()
            out.loc[mask, column] = mapped[mask]
    return out


def save_corrections(base: Path, edited: pd.DataFrame, existing: pd.DataFrame):
    editable_cols = ["Record ID", "Attendee Names", "Food Choice", "T-Shirt Size", "Hat Choice", "Review Status", "Review Notes"]
    saved = edited.copy()
    for column in editable_cols:
        if column not in saved.columns:
            saved[column] = ""
    saved = saved[editable_cols].fillna("")
    combined = saved if existing.empty else pd.concat([existing, saved], ignore_index=True).drop_duplicates("Record ID", keep="last")
    combined.to_csv(base / CORRECTIONS_FILE, index=False, encoding="utf-8-sig")


def counts_from_details(details_df: pd.DataFrame, field: str, eligible_packages: Optional[list[str]] = None) -> pd.DataFrame:
    if details_df.empty or field not in details_df.columns:
        return empty_df()
    out = details_df.copy()
    if eligible_packages and "Package" in out.columns:
        out = out[out["Package"].isin(eligible_packages)]
    quantity_col = find_col(out, ["Quantity", "Orderable Quantity"])
    if not quantity_col:
        return empty_df()
    result = pd.DataFrame({"Name": normalized_choice(out[field]), "Quantity": qty(out[quantity_col])})
    return result.groupby("Name", as_index=False)["Quantity"].sum().sort_values("Quantity", ascending=False)


def luau_counts(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return empty_df()
    product_col = find_col(raw_df, ["Product Title"])
    variant_col = find_col(raw_df, ["Variant Title"])
    quantity_col = find_col(raw_df, ["Orderable Quantity", "Current Quantity", "Quantity"])
    if not product_col or not variant_col or not quantity_col:
        return empty_df()
    luau = raw_df[raw_df[product_col].astype(str).str.strip().eq(LUAU_TITLE)].copy()
    if luau.empty:
        return empty_df()
    names = luau[variant_col].fillna("").astype(str).str.strip().replace({
        "With Beef Brisket": "With brisket",
        "Without Beef Brisket": "Without brisket",
        "": "Not Specified",
    })
    result = pd.DataFrame({"Name": names, "Quantity": qty(luau[quantity_col])})
    return result.groupby("Name", as_index=False)["Quantity"].sum().sort_values("Quantity", ascending=False)


def secret_or_env(name: str, default: str = "") -> str:
    value = os.getenv(name, "")
    if value:
        return value
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


def active_shopify_credentials() -> dict[str, str]:
    session = st.session_state.get("shopify_credentials", {})
    return {
        "shop_domain": session.get("shop_domain") or secret_or_env("SHOPIFY_SHOP_DOMAIN", DEFAULT_SHOP_DOMAIN),
        "access_token": session.get("access_token") or secret_or_env("SHOPIFY_ADMIN_ACCESS_TOKEN"),
        "client_id": session.get("client_id") or secret_or_env("SHOPIFY_CLIENT_ID"),
        "client_secret": session.get("client_secret") or secret_or_env("SHOPIFY_CLIENT_SECRET"),
    }


def has_shopify_credentials() -> bool:
    credentials = active_shopify_credentials()
    return bool(credentials["access_token"] or (credentials["client_id"] and credentials["client_secret"]))


def require_dashboard_access():
    required_password = secret_or_env("DASHBOARD_PASSWORD")
    if not required_password or st.session_state.get("dashboard_authenticated"):
        return
    st.title("BVLS World Meet 2026 Dashboard")
    st.caption("Enter the stakeholder password to continue.")
    with st.form("dashboard_login"):
        supplied_password = st.text_input("Dashboard password", type="password")
        submitted = st.form_submit_button("Open dashboard", type="primary")
    if submitted:
        st.session_state["dashboard_authenticated"] = hmac.compare_digest(supplied_password, required_password)
        if st.session_state["dashboard_authenticated"]:
            st.rerun()
        st.error("Incorrect password.")
    st.stop()


def load_exporter():
    exporter_path = Path(__file__).resolve().parent / EXPORTER_FILENAME
    spec = importlib.util.spec_from_file_location("bvls_worldmeet_export", exporter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the Shopify export helper.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sync_from_shopify(data_folder: Path) -> dict:
    exporter = load_exporter()
    credentials = active_shopify_credentials()
    access_token = credentials["access_token"]
    if not access_token:
        if not credentials["client_id"] or not credentials["client_secret"]:
            raise RuntimeError("Shopify credentials are not configured.")
        token_body = exporter.http_post_form(
            f"https://{credentials['shop_domain']}/admin/oauth/access_token",
            {"Content-Type": "application/x-www-form-urlencoded"},
            {
                "grant_type": "client_credentials",
                "client_id": credentials["client_id"],
                "client_secret": credentials["client_secret"],
            },
        )
        access_token = token_body.get("access_token", "")
        if not access_token:
            raise RuntimeError("Shopify did not return an access token.")
    return exporter.export_orders(
        shop_domain=credentials["shop_domain"],
        token=access_token,
        since_date=secret_or_env("SINCE_DATE", "2026-01-01"),
        expected_total=to_int(secret_or_env("EXPECTED_ADULT_PACKAGES", "114")),
        output_dir=data_folder,
    )


require_dashboard_access()
st.title("BVLS World Meet 2026 Order Dashboard")
st.caption("Live vendor ordering, attendee review, and exception cleanup from Shopify.")

data_folder = Path(DEFAULT_FOLDER).expanduser()
data_folder.mkdir(parents=True, exist_ok=True)

st.sidebar.header("Shopify sync")
if has_shopify_credentials():
    st.sidebar.success("Connected to Shopify.")
else:
    st.sidebar.warning("Shopify credentials are required before syncing.")
    with st.sidebar.expander("Connect Shopify", expanded=True):
        st.caption("Local setup only. The hosted dashboard uses protected server secrets.")
        with st.form("shopify_credentials_form"):
            shop_domain_input = st.text_input("Shop domain", value=DEFAULT_SHOP_DOMAIN)
            client_id_input = st.text_input("SHOPIFY_CLIENT_ID", type="password")
            client_secret_input = st.text_input("SHOPIFY_CLIENT_SECRET", type="password")
            save_credentials = st.form_submit_button("Connect Shopify", type="primary")
        if save_credentials:
            if not client_id_input or not client_secret_input:
                st.error("Enter both the client ID and client secret.")
            else:
                st.session_state["shopify_credentials"] = {
                    "shop_domain": shop_domain_input.strip(),
                    "client_id": client_id_input.strip(),
                    "client_secret": client_secret_input.strip(),
                    "access_token": "",
                }
                st.rerun()

auto_sync = st.sidebar.toggle("Keep dashboard current", value=True, disabled=not has_shopify_credentials())
sync_interval = st.sidebar.selectbox(
    "Check interval",
    [30, 60, 120, 300],
    index=1,
    format_func=lambda seconds: f"{seconds} seconds" if seconds < 60 else f"{seconds // 60} minutes",
    disabled=not auto_sync or not has_shopify_credentials(),
)
sync_now = st.sidebar.button("Sync Shopify now", type="primary", use_container_width=True, disabled=not has_shopify_credentials())
sync_due = auto_sync and has_shopify_credentials() and time.time() - st.session_state.get("last_shopify_sync", 0.0) >= sync_interval
if sync_now or sync_due:
    try:
        with st.sidebar.status("Syncing Shopify orders...", expanded=True) as status:
            result = sync_from_shopify(data_folder)
            st.cache_data.clear()
            status.update(label=f"Synced {result['orders_fetched']:,} orders; {result['line_rows']:,} event lines.", state="complete")
        st.session_state["last_shopify_sync"] = time.time()
        st.session_state["last_shopify_sync_message"] = f"{result['adult_total']:,} adult packages | {result['exceptions']:,} review rows"
    except Exception as exc:
        st.sidebar.error(f"Shopify sync failed: {exc}")
        st.session_state["last_shopify_sync"] = time.time()

if auto_sync and has_shopify_credentials():
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=sync_interval * 1000, key="shopify_auto_refresh")

if st.session_state.get("last_shopify_sync_message"):
    st.sidebar.success(st.session_state["last_shopify_sync_message"])
if st.sidebar.button("Refresh display", use_container_width=True):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption("Paid and partially refunded orders are read through Shopify Admin GraphQL.")

data = load_from_folder(str(data_folder))
summary = data["summary"]
raw = data["raw"]
package_totals = count_df(data["package_totals"], ["Package", "package"], ["Quantity", "quantity"])
fixed_items = prepare_fixed_df(data["fixed_items"])
exceptions = data["exceptions"].copy()
details = data["attendee_detail"].copy() if not data["attendee_detail"].empty else raw.copy()
corrections = load_corrections(data_folder)
details = apply_corrections(details, corrections)
exceptions = apply_corrections(exceptions, corrections)
meal_counts = counts_from_details(details, "Food Choice", ADULT_PACKAGES)
shirt_counts = counts_from_details(details, "T-Shirt Size", ["Cobra Chicken Gold", "Lion VIP Diamond"])
hat_counts = counts_from_details(details, "Hat Choice", ["Lion VIP Diamond"])
luau_options = luau_counts(raw)
luau_total = int(luau_options["Quantity"].sum()) if not luau_options.empty else 0

if raw.empty and details.empty:
    st.info("Waiting for the first Shopify sync.")
    st.stop()

open_exceptions = exceptions.copy()
if not open_exceptions.empty and "Review Status" in open_exceptions.columns:
    open_exceptions = open_exceptions[~open_exceptions["Review Status"].astype(str).str.strip().eq("Resolved")]

adult_total = int(package_totals.loc[package_totals["Name"].isin(ADULT_PACKAGES), "Quantity"].sum()) if not package_totals.empty else 0
expected = to_int(metric_from_summary(summary, "Expected adult packages", "114"))
difference = adult_total - expected
other_total = 0
if not package_totals.empty:
    non_adult_total = int(package_totals.loc[~package_totals["Name"].isin(ADULT_PACKAGES), "Quantity"].sum())
    other_total = max(0, non_adult_total - luau_total)

kpis = st.columns(8)
kpis[0].metric("Adult packages", f"{adult_total:,}", f"Expected {expected:,}")
kpis[1].metric("Difference", f"{difference:,}")
kpis[2].metric("Luau tickets", f"{luau_total:,}")
kpis[3].metric("Missing meals", f"{missing_qty(meal_counts):,}")
kpis[4].metric("Missing shirts", f"{missing_qty(shirt_counts):,}")
kpis[5].metric("Missing hats", f"{missing_qty(hat_counts):,}")
kpis[6].metric("Open review rows", f"{len(open_exceptions):,}")
kpis[7].metric("Other unknown rows", f"{other_total:,}")
st.divider()

overview_tab, vendor_tab, detail_tab, exception_tab, download_tab = st.tabs([
    "Overview", "Vendor ordering", "Who ordered what", "Exceptions", "Downloads"
])

with overview_tab:
    display_packages = package_totals.copy()
    left, right = st.columns([1.3, 1])
    with left:
        bar_chart(display_packages, "Ticket and package totals", "Package")
    with right:
        st.dataframe(display_packages, hide_index=True, use_container_width=True)
    st.subheader("Lakeshore Luau tickets")
    luau_left, luau_right = st.columns([1.3, 1])
    with luau_left:
        bar_chart(luau_options, "Brisket selection", "Ticket option")
    with luau_right:
        st.dataframe(luau_options, hide_index=True, use_container_width=True)
    unresolved = pd.DataFrame([
        {"Name": "Missing food choices", "Quantity": missing_qty(meal_counts)},
        {"Name": "Missing shirt sizes", "Quantity": missing_qty(shirt_counts)},
        {"Name": "Missing hat choices", "Quantity": missing_qty(hat_counts)},
    ])
    st.subheader("Unresolved fields")
    gap_left, gap_right = st.columns(2)
    with gap_left:
        bar_chart(unresolved, "Manual review gaps", "Field")
    with gap_right:
        st.dataframe(unresolved, hide_index=True, use_container_width=True)

with vendor_tab:
    st.subheader("Fixed items to order")
    fixed_left, fixed_right = st.columns([1.4, 1])
    with fixed_left:
        if not fixed_items.empty:
            item_col = find_col(fixed_items, ["Item", "item"])
            qty_col = find_col(fixed_items, ["Quantity", "quantity"])
            chart_df = fixed_items[[item_col, qty_col]].copy()
            chart_df.columns = ["Name", "Quantity"]
            bar_chart(chart_df, "Fixed vendor quantities", "Item", horizontal=True, height=500)
    with fixed_right:
        st.dataframe(fixed_items, hide_index=True, use_container_width=True)
    st.subheader("Variable options")
    col1, col2, col3 = st.columns(3)
    with col1:
        bar_chart(meal_counts, "Meal choices", "Meal")
        st.dataframe(meal_counts, hide_index=True, use_container_width=True)
    with col2:
        bar_chart(shirt_counts, "T-shirt sizes", "Size")
        st.dataframe(shirt_counts, hide_index=True, use_container_width=True)
    with col3:
        bar_chart(hat_counts, "Hat choices", "Hat")
        st.dataframe(hat_counts, hide_index=True, use_container_width=True)

with detail_tab:
    st.subheader("Who ordered exactly what")
    df = details.copy()
    filter_cols = st.columns(2)
    packages = sorted(df["Package"].fillna("").astype(str).unique()) if "Package" in df.columns else []
    selected_packages = filter_cols[0].multiselect("Package", packages, default=[package for package in packages if package in ADULT_PACKAGES])
    if selected_packages:
        df = df[df["Package"].astype(str).isin(selected_packages)]
    search = filter_cols[1].text_input("Search order/name")
    if search:
        mask = pd.Series(False, index=df.index)
        for column in [find_col(df, ["Order"]), find_col(df, ["Attendee Names"])]:
            if column:
                mask |= df[column].astype(str).str.contains(search, case=False, na=False)
        df = df[mask]
    preferred = ["Record ID", "Order", "Package", "Quantity", "Attendee Names", "Food Choice", "T-Shirt Size", "Hat Choice", "Review Status", "Review Notes"]
    visible = [column for column in preferred if column in df.columns]
    editable = {"Attendee Names", "Food Choice", "T-Shirt Size", "Hat Choice", "Review Status", "Review Notes"}
    edited_detail = st.data_editor(
        df[visible], hide_index=True, use_container_width=True, height=560,
        disabled=[column for column in visible if column not in editable],
        column_config={"Review Status": st.column_config.SelectboxColumn("Review Status", options=["", "Needs review", "Resolved"])},
    )
    if st.button("Save attendee edits", type="primary", use_container_width=True):
        save_corrections(data_folder, edited_detail, corrections)
        st.cache_data.clear()
        st.rerun()

with exception_tab:
    st.subheader("Manual review and exception cleanup")
    if exceptions.empty:
        st.success("No exceptions loaded.")
    else:
        df = exceptions.copy()
        show_resolved = st.toggle("Show resolved rows", value=False)
        if not show_resolved and "Review Status" in df.columns:
            df = df[~df["Review Status"].astype(str).str.strip().eq("Resolved")]
        preferred = ["Record ID", "Order", "Package", "Orderable Quantity", "Attendee Names", "Food Choice", "T-Shirt Size", "Hat Choice", "Issues", "Review Status", "Review Notes"]
        visible = [column for column in preferred if column in df.columns]
        editable = {"Attendee Names", "Food Choice", "T-Shirt Size", "Hat Choice", "Review Status", "Review Notes"}
        edited_exceptions = st.data_editor(
            df[visible], hide_index=True, use_container_width=True, height=560,
            disabled=[column for column in visible if column not in editable],
            column_config={"Review Status": st.column_config.SelectboxColumn("Review Status", options=["", "Needs review", "Resolved"])},
        )
        if st.button("Save exception edits", type="primary", use_container_width=True):
            save_corrections(data_folder, edited_exceptions, corrections)
            st.cache_data.clear()
            st.rerun()

with download_tab:
    downloads = [
        ("Summary", summary, "00_run_summary.csv"),
        ("Raw order lines", raw, "01_raw_order_lines.csv"),
        ("Package totals", package_totals, "dashboard_package_totals.csv"),
        ("Luau brisket choices", luau_options, "dashboard_luau_brisket_counts.csv"),
        ("Fixed items", fixed_items, "03_fixed_items_to_order.csv"),
        ("Meal counts", meal_counts, "dashboard_meal_counts.csv"),
        ("Shirt counts", shirt_counts, "dashboard_shirt_size_counts.csv"),
        ("Hat counts", hat_counts, "dashboard_hat_choice_counts.csv"),
        ("Exceptions", exceptions, "07_exceptions_review.csv"),
        ("Attendee detail", details, "08_attendee_order_detail.csv"),
        ("Saved corrections", corrections, CORRECTIONS_FILE),
    ]
    for label, frame, filename in downloads:
        left, right = st.columns([2, 1])
        left.write(label)
        with right:
            if frame.empty:
                st.button("No data", key=f"no_{filename}", disabled=True, use_container_width=True)
            else:
                download_button(frame, filename, f"Download {label}")
