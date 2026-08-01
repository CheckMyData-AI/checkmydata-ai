"""Google Analytics 4 source — the first vendor on the analytics spine.

Three modules, split along the seam that matters:

* :mod:`~app.analytics.ga4.config` — the **knobs** (property ids, backfill window,
  tracked events, currency) kept strictly apart from the **secret** (the service
  account JSON). The knobs are stored in the clear on the connection; the secret
  lives Fernet-encrypted on a ``VendorCredential`` and is handed in already
  decrypted, so nothing here ever reads or writes ciphertext.
* :mod:`~app.analytics.ga4.reports` — the five report definitions, each pinning the
  GA4 API dimension/metric names to the ``ga4_*`` fact table columns.
* :mod:`~app.analytics.ga4.adapter` — the adapter itself: paging (Δ1), empty-row
  retention (Δ2), quota handling (Δ3) and the error taxonomy mapping.
"""

from app.analytics.ga4.adapter import GA4Adapter
from app.analytics.ga4.config import GA4Config, GA4Credentials
from app.analytics.ga4.reports import GA4_REPORTS, REPORT_NAMES, GA4ReportSpec

__all__ = [
    "GA4_REPORTS",
    "REPORT_NAMES",
    "GA4Adapter",
    "GA4Config",
    "GA4Credentials",
    "GA4ReportSpec",
]
