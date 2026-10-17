"""Tool definitions for a chat model, in the Anthropic Messages format
({name, description, input_schema}) that fm-station-tracker's askTools.ts uses.

Each tool's input maps one-to-one onto an NbtcOper method's keyword arguments:
find_oper_stations onto find_stations, count_oper_inspections onto count_stations.
"""

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
        "is walked, so a long date range is slow."
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

TOOLS = [FIND_STATIONS_TOOL, COUNT_INSPECTIONS_TOOL]


def run_tool(api, name: str, tool_input: dict) -> dict:
    """Dispatch one tool call to the NbtcOper method behind it."""
    if name == FIND_STATIONS_TOOL["name"]:
        return api.find_stations(**tool_input)
    if name == COUNT_INSPECTIONS_TOOL["name"]:
        return api.count_stations(**tool_input)
    raise KeyError(f"unknown tool {name!r}")
