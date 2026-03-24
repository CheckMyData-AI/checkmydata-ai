"""Phone number to country resolution via E.164 dialing code prefix matching.

Uses an offline static mapping of ITU-T E.164 international dialing codes
to ISO 3166-1 alpha-2 country codes.  No external dependencies or API calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DIGITS_RE = re.compile(r"\d+")

# fmt: off
_DIALING_CODE_MAP: dict[str, tuple[str, str]] = {
    "1": ("US", "United States"),
    # Canadian area codes (NANP +1 with 3-digit area code)
    "1204": ("CA", "Canada"), "1226": ("CA", "Canada"), "1236": ("CA", "Canada"),
    "1249": ("CA", "Canada"), "1250": ("CA", "Canada"), "1263": ("CA", "Canada"),
    "1289": ("CA", "Canada"), "1306": ("CA", "Canada"), "1343": ("CA", "Canada"),
    "1354": ("CA", "Canada"), "1365": ("CA", "Canada"), "1367": ("CA", "Canada"),
    "1368": ("CA", "Canada"), "1382": ("CA", "Canada"), "1403": ("CA", "Canada"),
    "1416": ("CA", "Canada"), "1418": ("CA", "Canada"), "1428": ("CA", "Canada"),
    "1431": ("CA", "Canada"), "1437": ("CA", "Canada"), "1438": ("CA", "Canada"),
    "1450": ("CA", "Canada"), "1468": ("CA", "Canada"), "1474": ("CA", "Canada"),
    "1506": ("CA", "Canada"), "1514": ("CA", "Canada"), "1519": ("CA", "Canada"),
    "1548": ("CA", "Canada"), "1579": ("CA", "Canada"), "1581": ("CA", "Canada"),
    "1584": ("CA", "Canada"), "1587": ("CA", "Canada"), "1600": ("CA", "Canada"),
    "1604": ("CA", "Canada"), "1613": ("CA", "Canada"), "1639": ("CA", "Canada"),
    "1647": ("CA", "Canada"), "1672": ("CA", "Canada"), "1683": ("CA", "Canada"),
    "1705": ("CA", "Canada"), "1709": ("CA", "Canada"), "1742": ("CA", "Canada"),
    "1753": ("CA", "Canada"), "1778": ("CA", "Canada"), "1780": ("CA", "Canada"),
    "1782": ("CA", "Canada"), "1807": ("CA", "Canada"), "1819": ("CA", "Canada"),
    "1825": ("CA", "Canada"), "1867": ("CA", "Canada"), "1873": ("CA", "Canada"),
    "1879": ("CA", "Canada"), "1902": ("CA", "Canada"), "1905": ("CA", "Canada"),
    # Caribbean NANP codes
    "1242": ("BS", "Bahamas"),
    "1246": ("BB", "Barbados"),
    "1264": ("AI", "Anguilla"),
    "1268": ("AG", "Antigua and Barbuda"),
    "1284": ("VG", "British Virgin Islands"),
    "1340": ("VI", "US Virgin Islands"),
    "1345": ("KY", "Cayman Islands"),
    "1441": ("BM", "Bermuda"),
    "1473": ("GD", "Grenada"),
    "1649": ("TC", "Turks and Caicos"),
    "1664": ("MS", "Montserrat"),
    "1670": ("MP", "Northern Mariana Islands"),
    "1671": ("GU", "Guam"),
    "1684": ("AS", "American Samoa"),
    "1721": ("SX", "Sint Maarten"),
    "1758": ("LC", "Saint Lucia"),
    "1767": ("DM", "Dominica"),
    "1784": ("VC", "Saint Vincent"),
    "1787": ("PR", "Puerto Rico"),
    "1809": ("DO", "Dominican Republic"),
    "1829": ("DO", "Dominican Republic"),
    "1849": ("DO", "Dominican Republic"),
    "1868": ("TT", "Trinidad and Tobago"),
    "1869": ("KN", "Saint Kitts and Nevis"),
    "1876": ("JM", "Jamaica"),
    "7": ("RU", "Russia"),
    "77": ("KZ", "Kazakhstan"),
    "20": ("EG", "Egypt"),
    "27": ("ZA", "South Africa"),
    "30": ("GR", "Greece"),
    "31": ("NL", "Netherlands"),
    "32": ("BE", "Belgium"),
    "33": ("FR", "France"),
    "34": ("ES", "Spain"),
    "36": ("HU", "Hungary"),
    "39": ("IT", "Italy"),
    "40": ("RO", "Romania"),
    "41": ("CH", "Switzerland"),
    "43": ("AT", "Austria"),
    "44": ("GB", "United Kingdom"),
    "45": ("DK", "Denmark"),
    "46": ("SE", "Sweden"),
    "47": ("NO", "Norway"),
    "48": ("PL", "Poland"),
    "49": ("DE", "Germany"),
    "51": ("PE", "Peru"),
    "52": ("MX", "Mexico"),
    "53": ("CU", "Cuba"),
    "54": ("AR", "Argentina"),
    "55": ("BR", "Brazil"),
    "56": ("CL", "Chile"),
    "57": ("CO", "Colombia"),
    "58": ("VE", "Venezuela"),
    "60": ("MY", "Malaysia"),
    "61": ("AU", "Australia"),
    "62": ("ID", "Indonesia"),
    "63": ("PH", "Philippines"),
    "64": ("NZ", "New Zealand"),
    "65": ("SG", "Singapore"),
    "66": ("TH", "Thailand"),
    "81": ("JP", "Japan"),
    "82": ("KR", "South Korea"),
    "84": ("VN", "Vietnam"),
    "86": ("CN", "China"),
    "90": ("TR", "Turkey"),
    "91": ("IN", "India"),
    "92": ("PK", "Pakistan"),
    "93": ("AF", "Afghanistan"),
    "94": ("LK", "Sri Lanka"),
    "95": ("MM", "Myanmar"),
    "98": ("IR", "Iran"),
    "211": ("SS", "South Sudan"),
    "212": ("MA", "Morocco"),
    "213": ("DZ", "Algeria"),
    "216": ("TN", "Tunisia"),
    "218": ("LY", "Libya"),
    "220": ("GM", "Gambia"),
    "221": ("SN", "Senegal"),
    "222": ("MR", "Mauritania"),
    "223": ("ML", "Mali"),
    "224": ("GN", "Guinea"),
    "225": ("CI", "Ivory Coast"),
    "226": ("BF", "Burkina Faso"),
    "227": ("NE", "Niger"),
    "228": ("TG", "Togo"),
    "229": ("BJ", "Benin"),
    "230": ("MU", "Mauritius"),
    "231": ("LR", "Liberia"),
    "232": ("SL", "Sierra Leone"),
    "233": ("GH", "Ghana"),
    "234": ("NG", "Nigeria"),
    "235": ("TD", "Chad"),
    "236": ("CF", "Central African Republic"),
    "237": ("CM", "Cameroon"),
    "238": ("CV", "Cape Verde"),
    "239": ("ST", "Sao Tome and Principe"),
    "240": ("GQ", "Equatorial Guinea"),
    "241": ("GA", "Gabon"),
    "242": ("CG", "Congo"),
    "243": ("CD", "DR Congo"),
    "244": ("AO", "Angola"),
    "245": ("GW", "Guinea-Bissau"),
    "246": ("IO", "British Indian Ocean Territory"),
    "248": ("SC", "Seychelles"),
    "249": ("SD", "Sudan"),
    "250": ("RW", "Rwanda"),
    "251": ("ET", "Ethiopia"),
    "252": ("SO", "Somalia"),
    "253": ("DJ", "Djibouti"),
    "254": ("KE", "Kenya"),
    "255": ("TZ", "Tanzania"),
    "256": ("UG", "Uganda"),
    "257": ("BI", "Burundi"),
    "258": ("MZ", "Mozambique"),
    "260": ("ZM", "Zambia"),
    "261": ("MG", "Madagascar"),
    "262": ("RE", "Reunion"),
    "263": ("ZW", "Zimbabwe"),
    "264": ("NA", "Namibia"),
    "265": ("MW", "Malawi"),
    "266": ("LS", "Lesotho"),
    "267": ("BW", "Botswana"),
    "268": ("SZ", "Eswatini"),
    "269": ("KM", "Comoros"),
    "290": ("SH", "Saint Helena"),
    "291": ("ER", "Eritrea"),
    "297": ("AW", "Aruba"),
    "298": ("FO", "Faroe Islands"),
    "299": ("GL", "Greenland"),
    "350": ("GI", "Gibraltar"),
    "351": ("PT", "Portugal"),
    "352": ("LU", "Luxembourg"),
    "353": ("IE", "Ireland"),
    "354": ("IS", "Iceland"),
    "355": ("AL", "Albania"),
    "356": ("MT", "Malta"),
    "357": ("CY", "Cyprus"),
    "358": ("FI", "Finland"),
    "359": ("BG", "Bulgaria"),
    "370": ("LT", "Lithuania"),
    "371": ("LV", "Latvia"),
    "372": ("EE", "Estonia"),
    "373": ("MD", "Moldova"),
    "374": ("AM", "Armenia"),
    "375": ("BY", "Belarus"),
    "376": ("AD", "Andorra"),
    "377": ("MC", "Monaco"),
    "378": ("SM", "San Marino"),
    "380": ("UA", "Ukraine"),
    "381": ("RS", "Serbia"),
    "382": ("ME", "Montenegro"),
    "383": ("XK", "Kosovo"),
    "385": ("HR", "Croatia"),
    "386": ("SI", "Slovenia"),
    "387": ("BA", "Bosnia and Herzegovina"),
    "389": ("MK", "North Macedonia"),
    "420": ("CZ", "Czech Republic"),
    "421": ("SK", "Slovakia"),
    "423": ("LI", "Liechtenstein"),
    "500": ("FK", "Falkland Islands"),
    "501": ("BZ", "Belize"),
    "502": ("GT", "Guatemala"),
    "503": ("SV", "El Salvador"),
    "504": ("HN", "Honduras"),
    "505": ("NI", "Nicaragua"),
    "506": ("CR", "Costa Rica"),
    "507": ("PA", "Panama"),
    "508": ("PM", "Saint Pierre and Miquelon"),
    "509": ("HT", "Haiti"),
    "590": ("GP", "Guadeloupe"),
    "591": ("BO", "Bolivia"),
    "592": ("GY", "Guyana"),
    "593": ("EC", "Ecuador"),
    "594": ("GF", "French Guiana"),
    "595": ("PY", "Paraguay"),
    "596": ("MQ", "Martinique"),
    "597": ("SR", "Suriname"),
    "598": ("UY", "Uruguay"),
    "599": ("CW", "Curacao"),
    "670": ("TL", "Timor-Leste"),
    "672": ("NF", "Norfolk Island"),
    "673": ("BN", "Brunei"),
    "674": ("NR", "Nauru"),
    "675": ("PG", "Papua New Guinea"),
    "676": ("TO", "Tonga"),
    "677": ("SB", "Solomon Islands"),
    "678": ("VU", "Vanuatu"),
    "679": ("FJ", "Fiji"),
    "680": ("PW", "Palau"),
    "681": ("WF", "Wallis and Futuna"),
    "682": ("CK", "Cook Islands"),
    "683": ("NU", "Niue"),
    "685": ("WS", "Samoa"),
    "686": ("KI", "Kiribati"),
    "687": ("NC", "New Caledonia"),
    "688": ("TV", "Tuvalu"),
    "689": ("PF", "French Polynesia"),
    "690": ("TK", "Tokelau"),
    "691": ("FM", "Micronesia"),
    "692": ("MH", "Marshall Islands"),
    "850": ("KP", "North Korea"),
    "852": ("HK", "Hong Kong"),
    "853": ("MO", "Macao"),
    "855": ("KH", "Cambodia"),
    "856": ("LA", "Laos"),
    "880": ("BD", "Bangladesh"),
    "886": ("TW", "Taiwan"),
    "960": ("MV", "Maldives"),
    "961": ("LB", "Lebanon"),
    "962": ("JO", "Jordan"),
    "963": ("SY", "Syria"),
    "964": ("IQ", "Iraq"),
    "965": ("KW", "Kuwait"),
    "966": ("SA", "Saudi Arabia"),
    "967": ("YE", "Yemen"),
    "968": ("OM", "Oman"),
    "970": ("PS", "Palestine"),
    "971": ("AE", "United Arab Emirates"),
    "972": ("IL", "Israel"),
    "973": ("BH", "Bahrain"),
    "974": ("QA", "Qatar"),
    "975": ("BT", "Bhutan"),
    "976": ("MN", "Mongolia"),
    "977": ("NP", "Nepal"),
    "992": ("TJ", "Tajikistan"),
    "993": ("TM", "Turkmenistan"),
    "994": ("AZ", "Azerbaijan"),
    "995": ("GE", "Georgia"),
    "996": ("KG", "Kyrgyzstan"),
    "998": ("UZ", "Uzbekistan"),
}
# fmt: on

_SORTED_PREFIXES: list[str] = sorted(
    _DIALING_CODE_MAP.keys(), key=lambda p: -len(p)
)


@dataclass(frozen=True)
class PhoneCountryResult:
    country_code: str
    country_name: str


_UNKNOWN = PhoneCountryResult(country_code="", country_name="Unknown")


class PhoneCountryService:
    """Resolves phone numbers to country via E.164 dialing code prefixes."""

    def lookup(self, phone: str) -> PhoneCountryResult:
        if not phone:
            return _UNKNOWN

        digits = "".join(_DIGITS_RE.findall(phone))
        if not digits:
            return _UNKNOWN

        for prefix in _SORTED_PREFIXES:
            if digits.startswith(prefix):
                cc, cn = _DIALING_CODE_MAP[prefix]
                return PhoneCountryResult(country_code=cc, country_name=cn)

        return _UNKNOWN

    def lookup_batch(self, phones: list[str]) -> list[PhoneCountryResult]:
        return [self.lookup(p) for p in phones]


_service_instance: PhoneCountryService | None = None


def get_phone_country_service() -> PhoneCountryService:
    """Return the module-level PhoneCountryService singleton."""
    global _service_instance
    if _service_instance is None:
        _service_instance = PhoneCountryService()
    return _service_instance
