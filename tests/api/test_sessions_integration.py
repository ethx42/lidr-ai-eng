from pathlib import Path

import pytest

from tests.factories import breakdown

pytestmark = pytest.mark.asyncio

SPEC_PDF = Path("tests/fixtures/attachments/spec.pdf").read_bytes()
FORM = {"project_type": "mobile_app", "detail_level": "medium", "output_format": "phases_table"}


async def test_two_requests_update_project_metadata(async_client, fake_provider) -> None:
    sid = (await async_client.post("/sessions")).json()["session_id"]
    fake_provider.queue(breakdown(project_name="Yoga Booking", technologies=["Stripe"]))
    await async_client.post(
        f"/sessions/{sid}/estimate", data={"transcript": "first turn transcript", **FORM}
    )
    fake_provider.queue(breakdown(project_name="Yoga Booking", technologies=["Twilio"]))
    r = await async_client.post(
        f"/sessions/{sid}/estimate", data={"transcript": "second turn transcript", **FORM}
    )
    assert r.status_code == 200
    assert r.json()["project_metadata"]["mentioned_technologies"] == ["Stripe", "Twilio"]


async def test_pdf_attachment_changes_the_estimate(async_client, echo_provider) -> None:
    # echo_provider returns a breakdown whose technologies list every "Redsys"-like marker it sees
    # in the last user message
    sid = (await async_client.post("/sessions")).json()["session_id"]
    without = (
        await async_client.post(
            f"/sessions/{sid}/estimate", data={"transcript": "we need payments", **FORM}
        )
    ).json()
    sid2 = (await async_client.post("/sessions")).json()["session_id"]
    with_pdf = (
        await async_client.post(
            f"/sessions/{sid2}/estimate",
            data={"transcript": "we need payments", **FORM},
            files=[("attachments", ("spec.pdf", SPEC_PDF, "application/pdf"))],
        )
    ).json()
    assert "Redsys" not in without["breakdown"]["technologies"]
    assert "Redsys" in with_pdf["breakdown"]["technologies"]


async def test_eight_turns_never_send_more_than_max_turns(async_client, fake_provider) -> None:
    sid = (await async_client.post("/sessions")).json()["session_id"]
    for i in range(8):
        r = await async_client.post(
            f"/sessions/{sid}/estimate", data={"transcript": f"turn {i} transcript text", **FORM}
        )
        assert r.status_code == 200
    sent_pairs = [
        sum(1 for m in c["messages"] if m.role == "assistant") for c in fake_provider.calls
    ]
    assert max(sent_pairs) <= 6
    assert r.json()["history_turns"] == 6
