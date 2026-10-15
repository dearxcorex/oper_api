"""Province / district / sub-district names <-> the portal's numeric codes.

The portal ships the whole gazetteer in one script (_inc/js/dpv.js):
PV2 is 'code,name,code,name,…' for provinces; AM2[province] and TB2[district]
hold the same shape for the levels below.
"""

import re

DPV_PATH = "/Oper/_inc/js/dpv.js"
_PREFIXES = ("จ.", "อ.", "ต.", "เขต", "แขวง")


class UnknownPlace(ValueError):
    pass


def _pairs(csv: str) -> dict:
    parts = csv.split(",")
    return {code: name for code, name in zip(parts[0::2], parts[1::2])}


def parse_dpv(js: str) -> dict:
    province = re.search(r"PV2\s*=\s*'([^']*)'", js)
    if not province:
        raise ValueError("PV2 not found in dpv.js")

    def table(var):
        found = re.findall(var + r"\['?(\d+)'?\]\s*=\s*'([^']*)'", js)
        return {parent: _pairs(csv) for parent, csv in found}

    return {
        "provinces": _pairs(province.group(1)),
        "districts": table("AM2"),
        "subdistricts": table("TB2"),
    }


def _bare(name: str) -> str:
    name = re.sub(r"\s+", "", name)
    for prefix in _PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _lookup(value, options: dict, what: str) -> str:
    """A code passes through; a Thai name (prefix optional) is resolved."""
    if value in (None, "", 0, "0"):
        return "0"
    text = str(value).strip()
    if text.isdigit():
        return text
    matches = [code for code, name in options.items() if _bare(name) == _bare(text)]
    if len(matches) != 1:
        raise UnknownPlace(f"{what} {text!r} not found")
    return matches[0]


def provinces_with_district(places: dict, district) -> list[str]:
    """Province codes that have a district by this name (prefix optional)."""
    return [
        prov
        for prov, districts in places["districts"].items()
        if any(_bare(name) == _bare(str(district)) for name in districts.values())
    ]


def resolve(places: dict, province=None, district=None, subdistrict=None) -> tuple[str, str, str]:
    """-> (sProv1, sAumphoe1, sTambol1) values for the search form."""
    prov = _lookup(province, places["provinces"], "province")
    if prov == "0" and (district or subdistrict) and not str(district or subdistrict).isdigit():
        raise UnknownPlace("a district or sub-district name needs its province")
    dist = _lookup(district, places["districts"].get(prov, {}), "district")
    if dist == "0" and subdistrict and not str(subdistrict).isdigit():
        raise UnknownPlace("a sub-district name needs its district")
    sub = _lookup(subdistrict, places["subdistricts"].get(dist, {}), "sub-district")
    return prov, dist, sub
