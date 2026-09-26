"""B-26 / SCN-022: the SPA and the API live on different origins in production
(`CORS_ORIGINS` is the web host; the API is another), and a browser hides every
response header from cross-origin script unless the server names it in
`Access-Control-Expose-Headers`. The members route reports a capped list ONLY in
`X-Total-Count` / `X-Result-Capped` (F-PROJ-13), so without the exposure the client
reads null and presents a partial list as the whole team.
"""

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_a_cross_origin_response_exposes_the_completeness_headers():
    origin = settings.cors_origins[0]
    # No `with`: the context manager runs the lifespan — reconciles, cron loops and
    # process-wide singletons — and leaking that into the rest of the unit suite broke
    # 27 tests that ran after this one. The CORS middleware answers without it.
    client = TestClient(app)
    resp = client.get("/api/health", headers={"Origin": origin})
    exposed = {
        h.strip().lower() for h in resp.headers.get("access-control-expose-headers", "").split(",")
    }
    assert {"x-total-count", "x-result-capped"} <= exposed
