"""Agent tools: web, LLM wrapper, and AWS exec-on-existing-GPU.

No tool in this package provisions compute. The AWS exec tool only runs
commands on existing EC2 instances.
"""

from formica.tools.web import web_search, web_fetch
from formica.tools.aws_exec import aws_exec_on_instance

__all__ = ["web_search", "web_fetch", "aws_exec_on_instance"]
