"""HTML/JSON -> plain dicts. No network in this module."""

import re

from bs4 import BeautifulSoup

from .dates import from_dotnet_date, from_portal_date

# Thai column header -> key. Matched by header text, not position.
SEARCH_COLUMNS = {
    "ลำดับ": "no",
    "วันที่บันทึก": "recorded_date",
    "วันที่ตรวจสอบ": "inspected_date",
    "สำนักงานกสทช. เขต": "area",
    "รหัสสถานี": "station_code",
    "ชื่อสถานี": "station_name",
    "ความถี่": "frequency_mhz",
    "เลขที่ใบอนุญาต": "licence_no",
    "จังหวัด": "province",
    "อำเภอ": "district",
    "ตำบล": "subdistrict",
    "ที่ตั้ง": "location",
    "ผลการตรวจสอบ": "result",
    "เครื่องมือวัด": "instrument",
    "หนังสือแจ้งเตือน/วันที่": "warning_doc",
    "สถานะ": "status",
}
_DATE_KEYS = {"recorded_date", "inspected_date"}
_PLACE_PREFIX = {"province": "จ.", "district": "อ.", "subdistrict": "ต."}

# Station-search (mStnSch.aspx) column header -> key.
STATION_COLUMNS = {
    "ลำดับ": "no",
    "สถานี": "station_type",
    "ประเภทสถานี": "station_subtype",
    "รหัสสถานี": "station_code",
    "ชื่อสถานี": "name",
    "ความถี่": "frequency_mhz",
    "ที่อยู่": "location",
    "แหล่งข้อมูล": "source",
}

# form_options() table -> (select id on the add form, parent key). A "_raw"
# select holds every option as "parent,child"; the page filters it client-side.
FORM_OPTION_SELECTS = {
    "regions": ("RegID", None),
    "areas": ("AreaID_raw", "region_id"),
    "source_types": ("SrcTypeID", None),
    "issues": ("IssueID_raw", "source_type_id"),
    "inspectors": ("ChkAuthID_1_raw", "area_id"),
    "approvers": ("ApvNaID_raw", "area_id"),
    "test_equipment": ("TestEq_raw", "area_id"),
    "antennas": ("AntID", None),
    "cables": ("CableID", None),
}

# Detail-page control id -> key. Everything else stays under "raw".
DETAIL_FIELDS = {
    "StnID": "stn_id",
    "RegID": "region",
    "AreaID": "area",
    "SrcTypeID": "source_type",
    "CoopNa": "contact_name",
    "CoopTel": "contact_phone",
    "DetFrq": "measured_frequency",
    "DetFrqUnit": "measured_frequency_unit",
    "AntID": "antenna",
    "CableID": "cable",
    "DetPow": "power",
    "DetDBI": "antenna_gain_dbi",
    "DetAntHeight": "antenna_height",
    "OpinionDet": "result",
    "OpinionProc": "action",
    "DocNFNo": "warning_doc_no",
    "DtDocNF": "warning_doc_date",
    "DtTest": "inspected_date",
    "DtTest2": "inspected_to_date",
    "DtTestRep": "reported_date",
    "ApvNaID": "approver",
    "DtApv": "approved_date",
}
_DETAIL_NUMBERS = {"measured_frequency", "power", "antenna_gain_dbi", "antenna_height"}
_PLACEHOLDERS = {"กรุณาเลือก", "เลือก"}


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _number(text):
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def is_login_page(html: str) -> bool:
    return 'id="bLogin"' in html and 'id="UserName"' in html


def parse_login_form(html: str) -> tuple[dict, list[str]]:
    """Hidden fields to post back, and the VerID values the form offers."""
    soup = BeautifulSoup(html, "lxml")
    hidden = {
        el["name"]: el.get("value", "")
        for el in soup.select("form#Login input[type=hidden][name]")
    }
    versions = [o.get("value", "") for o in soup.select("select#VerID option")]
    return hidden, versions


def _total_and_pages(soup) -> tuple[int | None, int]:
    total = None
    total_el = soup.select_one("p.total-result")
    if total_el:
        m = re.search(r"([\d,]+)", _text(total_el))
        total = int(m.group(1).replace(",", "")) if m else None

    page_numbers = [
        int(n)
        for a in soup.select(".nbtc-pagination a[href]")
        for n in re.findall(r"[?&]page=(\d+)", a["href"])
    ]
    return total, max(page_numbers, default=1)


def _headers(table) -> list[str]:
    return [_text(th).replace(" ", "").replace("่่", "่") for th in table.select("thead th")]


def parse_search_page(html: str) -> dict:
    """One results page -> {"total", "pages", "rows"}."""
    soup = BeautifulSoup(html, "lxml")
    total, pages = _total_and_pages(soup)

    rows = []
    table = soup.select_one("table.table-bordered")
    if table and table.find("thead"):
        headers = _headers(table)
        header_keys = {k.replace(" ", ""): v for k, v in SEARCH_COLUMNS.items()}
        for tr in table.select("tbody tr") or table.find_all("tr")[1:]:
            link = tr.select_one('a[href*="FF11Chk.aspx?ChkID="]')
            if not link:
                continue
            row = {"chk_id": int(re.search(r"ChkID=(\d+)", link["href"]).group(1))}
            raw = {}
            for header, td in zip(headers, tr.find_all("td")):
                key = header_keys.get(header)
                if not key:
                    continue
                value = _text(td)
                raw[header] = value
                if key in _DATE_KEYS:
                    value = from_portal_date(value)
                elif key == "frequency_mhz":
                    value = _number(value)
                elif key == "no":
                    value = int(value) if value.isdigit() else None
                elif key in _PLACE_PREFIX:
                    value = value.removeprefix(_PLACE_PREFIX[key]) or None
                elif key == "warning_doc":
                    row["warning_doc_date"] = from_portal_date(value)
                    value = re.sub(r"\s*\d{1,2}/\d{1,2}/\d{4}\s*", "", value).strip(" -") or None
                    key = "warning_doc_no"
                row[key] = value if value != "" else None
            row["raw"] = raw
            rows.append(row)

    return {"total": total, "pages": pages, "rows": rows}


def parse_station_search_page(html: str) -> dict:
    """One mStnSch.aspx results page -> {"total", "pages", "rows"}."""
    soup = BeautifulSoup(html, "lxml")
    total, pages = _total_and_pages(soup)

    rows = []
    table = soup.select_one("table.table-bordered")
    if table and table.find("thead"):
        headers = _headers(table)
        for tr in table.select("tbody tr"):
            link = tr.select_one('a[href*="selStn("]')
            if not link:
                continue
            row = {"stn_id": int(re.search(r"selStn\('(\d+)'", link["href"]).group(1))}
            raw = {}
            for header, td in zip(headers, tr.find_all("td")):
                key = STATION_COLUMNS.get(header)
                if not key:
                    continue
                value = _text(td)
                raw[header] = value
                if key == "frequency_mhz":
                    # Shown with its unit ("90.50MHz"); other units stay under raw.
                    m = re.fullmatch(r"([\d.,]+)\s*MHz", value, re.I)
                    value = _number(m.group(1)) if m else None
                elif key == "no":
                    value = int(value) if value.isdigit() else None
                row[key] = value if value != "" else None
            row["raw"] = raw
            rows.append(row)

    return {"total": total, "pages": pages, "rows": rows}


def _options(soup, select_id: str, parent_key: str | None) -> list[dict]:
    select = soup.find("select", id=select_id)
    out = []
    for option in select.find_all("option") if select else []:
        value, name = option.get("value", ""), _text(option)
        if parent_key:
            parent, _, value = value.partition(",")
            if not value:
                continue
        if value in ("", "0") or name in _PLACEHOLDERS:
            continue
        entry = {"id": int(value) if value.isdigit() else value, "name": name}
        if parent_key:
            entry[parent_key] = int(parent) if parent.isdigit() else parent
        out.append(entry)
    return out


def parse_form_options(add_form_html: str) -> dict:
    """The add form's dropdowns -> {table: [{"id", "name", parent id?}]}."""
    soup = BeautifulSoup(add_form_html, "lxml")
    return {
        table: _options(soup, select_id, parent)
        for table, (select_id, parent) in FORM_OPTION_SELECTS.items()
    }


def split_location(location: str | None) -> dict:
    """'… ต.ผักปัง อ.ภูเขียว จ.ชัยภูมิ' -> the last sub-district, district, province named."""
    out = {}
    for key, prefix in (("subdistrict", "ต."), ("district", "อ."), ("province", "จ.")):
        found = re.findall(re.escape(prefix) + r"\s*(\S+)", location or "")
        out[key] = found[-1] if found else None
    return out


def compact_station(row: dict, record: dict | None = None) -> dict:
    """A station-search row (plus its dSTN record, if fetched) -> a short summary.

    For a chat model: no raw portal fields. The record adds the licence,
    the operator and the coordinates (lat, lng).
    """
    out = {
        "stn_id": row["stn_id"],
        "name": row.get("name"),
        "frequency_mhz": row.get("frequency_mhz"),
        "station_code": row.get("station_code"),
        "station_subtype": row.get("station_subtype"),
        "source": row.get("source"),
        **split_location(row.get("location")),
        "location": row.get("location"),
    }
    if record is not None:
        out["licence_no"] = (record.get("licence_no") or "").strip() or None
        if out["licence_no"] == "0":
            out["licence_no"] = None
        out["licence_expires"] = record.get("licence_expires")
        out["operator"] = (record.get("operator") or "").strip() or None
        out["nbtc_code"] = record.get("nbtc_code")
        out["station_id"] = record.get("station_id")
        out["lat"] = _coordinate(record.get("lat"))
        out["lng"] = _coordinate(record.get("lng"))
    return out


def _coordinate(value):
    """A degree value, or None for the portal's blanks and zeros."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number or None


def parse_detail_page(html: str, chk_id: int) -> dict:
    """Inspection form -> typed core fields plus every control under "raw"."""
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form") or soup

    raw = {}
    for el in form.find_all(["input", "select", "textarea"], id=True):
        if el["id"].startswith("__"):
            continue
        if el.name == "select":
            option = el.find("option", selected=True)
            value = _text(option) if option else ""
            if value in _PLACEHOLDERS:
                value = ""
        elif el.name == "textarea":
            value = el.get_text().strip()
        elif el.get("type") in ("text", "hidden", None):
            value = (el.get("value") or "").strip()
        else:
            continue
        raw[el["id"]] = value

    out = {"chk_id": chk_id}
    for control_id, key in DETAIL_FIELDS.items():
        value = raw.get(control_id, "")
        if key.endswith("_date"):
            value = from_portal_date(value)
        elif key in _DETAIL_NUMBERS:
            value = _number(value)
        elif key == "stn_id":
            value = int(value) if value.isdigit() else None
        out[key] = value if value != "" else None
    out["inspectors"] = [
        raw[k] for k in sorted(raw) if k.startswith("ChkAuthID_") and raw[k]
    ]
    out["raw"] = raw
    return out


def shape_station(record: dict) -> dict:
    """One dSTN.ashx record -> typed core fields plus the record under "raw".

    StnCode and stationId each hold either code system: an RFXL… code for a
    station relicensed under OPER, or the zero-padded legacy numeric id for one
    that was not. They are told apart by shape, not by which field they sit in.
    """
    codes = [(record.get(k) or "").strip() for k in ("stationId", "StnCode")]
    legacy = next((c for c in codes if c.isdigit()), None)
    code = next((c for c in codes if c and not c.isdigit()), None)
    return {
        "stn_id": record.get("StnID"),
        "station_id": legacy,
        "nbtc_code": code,
        "name": record.get("StaNa"),
        "station_type": record.get("StnType"),
        "frequency_mhz": _number(record.get("FreqMhz")),
        "lat": record.get("Lat"),
        "lng": record.get("Lng"),
        "height_m": record.get("Height"),
        "licence_no": record.get("LicNo"),
        "licence_expires": from_dotnet_date(record.get("DtExp")),
        "operator": record.get("OrgName"),
        "location": re.sub(r"\s+", " ", record.get("StaLocFull") or "").strip() or None,
        "pat_code": record.get("PATCode"),
        "source": record.get("SrcData"),
        "updated_at": from_dotnet_date(record.get("DtUpd")),
        "raw": record,
    }


def station_search_provinces(html: str) -> list[str]:
    """The province codes the station picker offers for its area."""
    m = re.search(r"provids\s*=\s*\('([^']*)'\)", html)
    return [c for c in m.group(1).split(",") if c not in ("", "0")] if m else []
