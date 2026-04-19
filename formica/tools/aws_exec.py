"""AWS MCP exec tool - run commands on **existing** EC2/GPU instances only.

This tool must NEVER provision new instances. It only runs shell commands on
instances that already exist in the account. SSM `SendCommand` is the transport.
"""

from __future__ import annotations

import time

try:
    from strands import tool
except Exception:  # pragma: no cover
    def tool(fn):
        return fn


@tool
def aws_exec_on_instance(
    instance_id: str,
    command: str,
    region: str | None = None,
    timeout_seconds: int = 300,
) -> str:
    """Run a shell command on an existing EC2 instance via AWS Systems Manager.

    Hard rules:
    - `instance_id` must already exist. This tool performs no provisioning.
    - It does not call `RunInstances`, `CreateFleet`, or any capacity API.
    - It only calls `ssm:SendCommand` and `ssm:GetCommandInvocation`.
    """
    import boto3

    if not instance_id.startswith("i-"):
        return f"refusing: instance_id {instance_id!r} does not look like an EC2 id"

    ssm = boto3.client("ssm", region_name=region)
    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command]},
    )
    cmd_id = resp["Command"]["CommandId"]
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(2)
            continue
        status = inv.get("Status")
        if status in ("Success", "Failed", "TimedOut", "Cancelled"):
            return (
                f"status={status}\n"
                f"stdout:\n{inv.get('StandardOutputContent', '')}\n"
                f"stderr:\n{inv.get('StandardErrorContent', '')}"
            )
        time.sleep(2)
    return f"timeout after {timeout_seconds}s for command {cmd_id}"
