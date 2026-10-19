from fastapi.testclient import TestClient
from onboarding.api import app
c = TestClient(app)
for d in ["1712345678","0900000001","0900000002","0900000003","0900000004","0900000005"]:
    r = c.post("/api/v1/onboarding/start", json={"prospect_name":"Juan Perez","document_id":d,"product":"cuenta_ahorros"}).json()
    print(d, r["status"], r["current_step"], [e["reason"] for e in r["escalations"]])
    if r["status"]=="ESCALATED":
        r2 = c.post(f"/api/v1/onboarding/{r['onboarding_id']}/resolve", json={"escalation_id":r["escalations"][0]["id"],"action":"approve","notes":"ok oficial"}).json()
        print("   resolve ->", r2["status"], r2["current_step"])
print(c.post("/api/v1/onboarding/start", json={"prospect_name":"Juan Perez","document_id":"1712345678","product":"hipoteca"}).json()["status"])
print(c.post("/api/v1/onboarding/start", json={"prospect_name":"Juan Perez","document_id":"12","product":"x"}).status_code)
