"""Client for a deployed AgentCore Runtime (CDS_MODE=agentcore)."""

from __future__ import annotations

import json
import time
import uuid

from cds.config import get_settings


def ask(question, patient_id, report_text, order, setting, t0):
    import boto3

    from cds.agents.supervisor import Answer

    s = get_settings()
    if not s.agentcore_arn:
        raise RuntimeError("Set CDS_AGENTCORE_ARN to the runtime ARN printed by agentcore/deploy.sh")
    client = boto3.client("bedrock-agentcore", region_name=s.region)
    payload = {"prompt": question, "patient_id": patient_id, "report_text": report_text, "order": order,
               "setting": setting}
    resp = client.invoke_agent_runtime(agentRuntimeArn=s.agentcore_arn, runtimeSessionId=uuid.uuid4().hex + "cds00",
                                       payload=json.dumps(payload).encode())
    body = json.loads(resp["response"].read())
    body.pop("latency_ms", None)
    body["mode"] = "agentcore"
    return Answer(**{k: v for k, v in body.items() if k in Answer.__dataclass_fields__},
                  latency_ms=round((time.perf_counter() - t0) * 1000, 1))
