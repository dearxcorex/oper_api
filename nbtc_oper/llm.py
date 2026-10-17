"""Tool definitions for a chat model, in the Anthropic Messages format
({name, description, input_schema}) that fm-station-tracker's askTools.ts uses.

Each tool's input maps one-to-one onto an NbtcOper method's keyword arguments:
find_oper_stations onto find_stations, count_oper_inspections onto count_stations,
find_content_inspections onto content_inspections.

Inspections are two kinds of work on two portal pages, never mixed: งานตรวจสอบ
(technical checks, count_oper_inspections) and งานคุ้มครอง (content and adverts,
find_content_inspections). Each inspection tool says which it is, and tells the
model to ask the user when the question does not make that clear.
"""

from .api import ANY_VIOLATION, CONTENT_RESULTS, CONTENT_SOURCE_TYPES

# Shared by both inspection tools, so they draw the same line.
WHICH_WORK = (
    " Inspections are two kinds of work, never mixed: งานตรวจสอบ (technical checks: "
    "ความถี่, กำลังส่ง, ใบอนุญาต, หนังสือเตือน) and งานคุ้มครอง (content and adverts: "
    "เนื้อหา, โฆษณา, รายการ, e.g. โฆษณายา). If the user has not said or clearly implied "
    "which one, do not call any inspection tool: ask them \"งานตรวจสอบ หรือ งานคุ้มครอง?\" first."
)

FIND_STATIONS_TOOL = {
    "name": "find_oper_stations",
    "description": (
        "Search the NBTC OPER station register (the station picker on the inspection "
        "form) for radio stations. Filter by province, district (อำเภอ), sub-district, "
        "exact frequency in MHz, name, or data source; give at least one of province, "
        "district, frequency or name. Thai place names, with or without the จ./อ./ต. "
        "prefix. With no place given, only นครราชสีมา and ชัยภูมิ are searched. A "
        "district alone is enough; a name shared with another province means the one in "
        "นครราชสีมา or ชัยภูมิ. Returns short summaries; total counts "
        "every match, shown how many came back. When the answer comes from the saved "
        "register (as_of is set), each station has contact_name and contact_phone from its "
        "station record (contact_date: when the record was last updated), or null when it "
        "has none, and lat/lng "
        "(the register's coordinates, null when it has none); a live answer carries lat/lng "
        "only with details."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "province": {"type": "string", "description": "Province, e.g. ชัยภูมิ; โคราช means นครราชสีมา"},
            "district": {"type": "string", "description": "District (อำเภอ), e.g. ภูเขียว"},
            "subdistrict": {"type": "string", "description": "Sub-district (ตำบล); needs district"},
            "frequency": {
                "type": "number",
                "description": "Exact frequency in MHz, e.g. 91.75 (no tolerance)",
            },
            "name": {"type": "string", "description": "Part of the station name"},
            "source": {
                "type": "string",
                "enum": ["ASMS", "WEB", "BCS", "BCS2", "BCS3", "OPER"],
                "description": "Data source (แหล่งข้อมูล); omit for BCS and OPER together",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            "details": {
                "type": "boolean",
                "description": "Add licence number, expiry, operator and coordinates (slower when live: one request per station)",
                "default": False,
            },
        },
        "additionalProperties": False,
    },
}

COUNT_INSPECTIONS_TOOL = {
    "name": "count_oper_inspections",
    "description": (
        "Count the radio station inspections recorded in NBTC OPER between two inspection "
        "dates, inclusive, and name the stations. Filter by province, district (อำเภอ) or "
        "result. inspections is the portal's own total, the headline number; stations is "
        "how many distinct stations those were, given in brackets; by_result splits both by "
        "result. station_list names up to limit stations, latest inspection first, each with "
        "its frequency, place, licence, that inspection's date, result and warning document, "
        "and how many times it was inspected; truncated means some were left out. Every page "
        "is walked, so a long date range is slow. This is งานตรวจสอบ only, not งานคุ้มครอง."
        + WHICH_WORK
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "inspected_from": {"type": "string", "description": "First day, YYYY-MM-DD (CE)"},
            "inspected_to": {"type": "string", "description": "Last day, YYYY-MM-DD (CE)"},
            "province": {"type": "string", "description": "Province, e.g. ชัยภูมิ; โคราช means นครราชสีมา"},
            "district": {"type": "string", "description": "District (อำเภอ), e.g. ภูเขียว"},
            "result": {
                "type": "string",
                "enum": ["ตรงตามมาตรฐาน", "ไม่ตรงตามมาตรฐาน"],
                "description": "Only when the question is about a result: passed -> ตรงตามมาตรฐาน, "
                "failed -> ไม่ตรงตามมาตรฐาน; omit for every result",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
        },
        "required": ["inspected_from", "inspected_to"],
        "additionalProperties": False,
    },
}

CONTENT_INSPECTIONS_TOOL = {
    "name": "find_content_inspections",
    "description": (
        "งานคุ้มครอง, not งานตรวจสอบ: the content and advertising inspections of radio "
        "stations in NBTC OPER. Answers when a station was inspected and what was found "
        "(ผลการตรวจสอบ), or which stations broke the rules. Filter by exact frequency, "
        "station name, programme name, province, district, result, source type and "
        "inspection dates; with no dates, from 1 January this year. station_list groups "
        "the inspections by station: flagged stations (any result that is a wrongdoing) "
        "first, then the most recently inspected; each station's checks pair every "
        "inspection date with its result, programme, follow-up step (process, e.g. ส่ง สสจ.) "
        "and approval status, newest first. Lead the answer with the dates and results. "
        "inspections and stations count every match; truncated means some stations were "
        "left out. Every page is walked."
        + WHICH_WORK
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "inspected_from": {"type": "string", "description": "First day, YYYY-MM-DD (CE); omit for 1 January this year"},
            "inspected_to": {"type": "string", "description": "Last day, YYYY-MM-DD (CE); omit for up to today"},
            "frequency": {"type": "number", "description": "Exact frequency in MHz, e.g. 88.0"},
            "freq_from": {"type": "number", "description": "Lowest frequency in MHz, for a range"},
            "freq_to": {"type": "number", "description": "Highest frequency in MHz, for a range"},
            "station_name": {"type": "string", "description": "Part of the station name"},
            "programme": {"type": "string", "description": "Part of the programme name (รายการ)"},
            "province": {"type": "string", "description": "Province, e.g. ชัยภูมิ; โคราช means นครราชสีมา"},
            "district": {"type": "string", "description": "District (อำเภอ), e.g. ภูเขียว"},
            "result": {
                "type": "string",
                "enum": [*CONTENT_RESULTS, ANY_VIOLATION],
                "description": "Only when the question is about a result, e.g. โฆษณายา -> "
                "เนื้อหาโฆษณา ยา; " + ANY_VIOLATION + " for any wrongdoing; omit for every result",
            },
            "source_type": {
                "type": "string",
                "enum": list(CONTENT_SOURCE_TYPES),
                "description": "Why the inspection was made, e.g. เรื่องร้องเรียน; omit for every kind",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
        },
        "additionalProperties": False,
    },
}

TOOLS = [FIND_STATIONS_TOOL, COUNT_INSPECTIONS_TOOL, CONTENT_INSPECTIONS_TOOL]


def run_tool(api, name: str, tool_input: dict) -> dict:
    """Dispatch one tool call to the NbtcOper method behind it."""
    if name == FIND_STATIONS_TOOL["name"]:
        return api.find_stations(**tool_input)
    if name == COUNT_INSPECTIONS_TOOL["name"]:
        return api.count_stations(**tool_input)
    if name == CONTENT_INSPECTIONS_TOOL["name"]:
        return api.content_inspections(**tool_input)
    raise KeyError(f"unknown tool {name!r}")
