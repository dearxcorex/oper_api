"""Tool definitions for a chat model, in the Anthropic Messages format
({name, description, input_schema}) that fm-station-tracker's askTools.ts uses.

Each tool's input maps one-to-one onto an NbtcOper method's keyword arguments.
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
        "นครราชสีมา or ชัยภูมิ. Returns short summaries without coordinates; total counts "
        "every match, shown how many came back. When the answer comes from the saved "
        "register (as_of is set), each station has contact_name and contact_phone from its "
        "latest inspection (contact_date), or null when it was never inspected."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "province": {"type": "string", "description": "Province, e.g. ชัยภูมิ"},
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
                "description": "Data source (แหล่งข้อมูล); omit for BCS",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            "details": {
                "type": "boolean",
                "description": "Add licence number, expiry and operator (slower: one request per station)",
                "default": False,
            },
        },
        "additionalProperties": False,
    },
}

TOOLS = [FIND_STATIONS_TOOL]


def run_tool(api, name: str, tool_input: dict) -> dict:
    """Dispatch one tool call to the NbtcOper method behind it."""
    if name == FIND_STATIONS_TOOL["name"]:
        return api.find_stations(**tool_input)
    raise KeyError(f"unknown tool {name!r}")
