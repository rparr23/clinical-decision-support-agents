"""Amazon Bedrock AgentCore Runtime entrypoint.

Deployed by agentcore/deploy.sh. The runtime runs the supervisor in bedrock mode (Claude via
Strands) and returns the same JSON the web app's /api/ask returns.
"""

from __future__ import annotations

import os

os.environ.setdefault("CDS_MODE", "bedrock")

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402

from cds.agents.supervisor import Supervisor  # noqa: E402
from cds.safety import redact  # noqa: E402

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict) -> dict:
    answer = Supervisor(mode="bedrock").ask(
        payload.get("prompt", ""),
        payload.get("patient_id"),
        payload.get("report_text"),
        payload.get("order"),
        payload.get("setting"),
    )
    app.logger.info("answered %s agents=%s refused=%s", redact(answer.question)[:80], answer.agents, answer.refused)
    return answer.as_dict()


if __name__ == "__main__":
    app.run()
