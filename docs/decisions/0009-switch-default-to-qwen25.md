# ADR 0009: Switch default open-weight model from Mistral-7B to Qwen2.5-7B-AWQ

- Status: Accepted (amends ADR-0007)
- Date: 2026-04-21

## Context

ADR-0007 pinned the default open-weight model to
`TheBloke/Mistral-7B-Instruct-v0.2-AWQ`, inherited from the rome AMI
(`ami-079c82d610e02e480`). That default got us to a working end-to-end
smoke test (PR #23 landed the two LLM wiring fixes: missing `api_key`
and forced system/user role merging), but the first real run surfaced
three intrinsic limits of Mistral-7B-Instruct as the Formica model:

1. The Mistral chat template rejects a leading `system` role with
   HTTP 400 "Conversation roles must alternate user/assistant/...".
   We already work around this in `formica/tools/llm.py` by folding
   the system prompt into the first user turn, but losing the
   separate system role weakens every caste's instruction adherence.
2. Mistral-7B-Instruct-v0.2 has no native tool-calling support, and
   vLLM therefore refuses `tool_choice="auto"` with
   `'"auto" tool choice requires --enable-auto-tool-choice and
   --tool-call-parser to be set'`. The forager caste, which passes
   `tools=[...]`, falls back to non-LLM behavior on every tick
   (tracked in issue #24).
3. Mistral-7B is a weak math / reasoning model (MATH pass rate around
   13%). The first smoke run produced 16 validator verdicts, all
   `needs_expert`, and 0 `validated` evidence. Formica's validator
   caste is a bottleneck on model quality, not on plumbing.

Separately, the user has an explicit preference to avoid hosted OpenAI
for this project on business-model grounds, reinforcing the
open-weight-first posture from ADR-0007.

## Decision

Change the default model to `Qwen/Qwen2.5-7B-Instruct-AWQ` and update
the vLLM Deployment to expose native tool calling.

Concretely:

- `FormicaConfig.model_id` default becomes
  `Qwen/Qwen2.5-7B-Instruct-AWQ` (was
  `TheBloke/Mistral-7B-Instruct-v0.2-AWQ`).
- `FormicaConfig.model_base_url` is unchanged
  (`http://vllm.formica.svc.cluster.local:8080/v1`).
- `FormicaConfig.model_provider` is unchanged (`openai` protocol).
- The vLLM Deployment in both `deploy/k8s/base/vllm.yaml` and the Helm
  chart gains:
  - `--model=/models/qwen-awq` (was `/models/mistral-awq`)
  - `--served-model-name=Qwen/Qwen2.5-7B-Instruct-AWQ`
  - `--quantization=awq_marlin` (Qwen documents the marlin kernel as
    the preferred AWQ backend on Ampere/Ada; falls back to `awq` if
    unavailable)
  - `--enable-auto-tool-choice`
  - `--tool-call-parser=hermes`
- A `download-model` initContainer is added to the vLLM pod. It checks
  for `$DEST/config.json` and, if missing, runs
  `huggingface-cli download Qwen/Qwen2.5-7B-Instruct-AWQ --local-dir
  /models/qwen-awq --local-dir-use-symlinks False`. This lets the
  existing rome AMI keep working: the one-time ~5GB pull happens on
  first pod startup, and subsequent restarts are instant. Pre-staging
  the directory (e.g. via SSM) skips the download entirely.
- The `merged_input` workaround in `formica/tools/llm.py` stays as-is.
  Qwen2.5 supports a native system role, but keeping the merge keeps
  the wrapper portable across any OpenAI-compatible backend a user
  might plug in later.

## Rationale

- Native system-role support: Qwen2.5-Instruct's chat template
  accepts a leading `system` message, removing the root cause of the
  alternation 400 fix.
- Native tool calling: Qwen2.5 emits Hermes-style tool calls; vLLM's
  `hermes` parser decodes them. This directly closes issue #24 and
  unblocks the forager caste.
- Reasoning quality: Qwen2.5-7B scores roughly 50%+ on MATH vs
  ~13% for Mistral-7B-Instruct-v0.2, and substantially higher on
  GSM8K and MMLU. Validator and scout outputs should improve in
  kind without changing any agent code.
- Same VRAM footprint: AWQ-quantized 7B fits comfortably on the A10G
  in the existing `g5.xlarge` with `--gpu-memory-utilization=0.85`.
- No vendor lock-in: weights are Apache-2.0-licensed and hosted on
  Hugging Face; nothing in Formica's runtime depends on Alibaba
  infrastructure.
- Aligns with the user's "no OpenAI dependency" posture without
  reopening the ADR-0007 decision to default to open weights.

## Alternatives considered

- **Stay on Mistral-7B and just add `--enable-auto-tool-choice +
  --tool-call-parser=mistral`.** Rejected: fixes #24 only. Does not
  fix the system-role rejection (still need the merge workaround)
  and leaves the reasoning gap, which is the actual cause of the
  0-validated-evidence smoke result.
- **Llama-3.1-8B-Instruct-AWQ.** Competitive on reasoning and also
  supports tool calling, but its license forbids using outputs to
  train other models and has extra use restrictions. Qwen2.5's
  Apache-2.0 is friendlier for a research project that may later
  fine-tune on Formica traces.
- **Qwen2.5-14B-AWQ.** Stronger, but ~9GB in AWQ-INT4; combined with
  KV cache at 4096 context this is borderline on 24GB A10G with
  other pods on the box. Revisit if we move off g5.xlarge.
- **Switch to Bedrock / hosted Claude or GPT-4o for validators only.**
  Contradicts the user's no-OpenAI posture and reintroduces the cost
  and dependency concerns ADR-0007 was written to avoid. The hosted
  path remains available via `FORMICA_MODEL_PROVIDER=bedrock` for
  users who want it.

## Consequences

- Issue #24 is expected to close once a smoke run confirms the forager
  caste reaches the model cleanly with `tool_choice="auto"`.
- The rome AMI does not need to be rebuilt; the initContainer handles
  the one-time Qwen weight stage. Pod cold start on a fresh AMI grows
  by several minutes the first time (HF download), then returns to
  the usual 60-120s.
- The previous Mistral weights at `/opt/models/mistral-awq` remain on
  the host. They are unused by Formica, but cost nothing and make it
  trivial to switch back for A/B comparisons via
  `FORMICA_MODEL_ID=TheBloke/Mistral-7B-Instruct-v0.2-AWQ` and a
  matching override on the vLLM args.
- `test_default_model_is_mistral_awq` is replaced by
  `test_default_model_is_qwen25_awq`.
- Existing CI still runs without a GPU: unit and integration tests use
  `FakeForum`, and the e2e toy-math test monkeypatches
  `Validator._judge`.
