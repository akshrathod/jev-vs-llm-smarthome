# Smart Home Hub Benchmark: LLM vs Jev

A multi-agent smart-home simulation, built specifically to put two
decision-making layers head to head on speed, cost, and accuracy:

- **System A**: every decision made by a general-purpose LLM (`openai/gpt-6-luna`
  via OpenRouter, configurable).
- **System B**: every decision made by [TypeSafe's Jev](https://www.typesafe.ai)
  (`typesafe/jev-1.13`, via OpenRouter's Decisions API at
  `https://openrouter.ai/api/alpha/decisions`), with a confidence-based fallback
  to the LLM when Jev isn't sure enough to trust on its own.

Both systems share the exact same architecture, agents, tools, and event data.
The only thing that differs is who makes the decision.

## Architecture

A supervisor decides which one of four domain agents should handle an incoming
command, then that agent decides its specific action:

```
Command -> Supervisor (picks a domain) -> Domain Agent (picks room + action) -> Tool call -> Confirmation
```

Note: "tool call" here means a deterministic Python function (e.g. `set_light`,
`adjust_thermostat`), not native LLM/Jev function-calling. The model only
outputs structured fields; a separate dispatch step (`agents.py`) calls the
matching function based on those fields. Neither system's API request ever
includes a `tools`/`functions` parameter.

If the supervisor determines no domain applies, the graph stops after that
decision instead of routing to an agent.

**Domains:** `lighting`, `climate`, `security`, `appliance`, each with its own
pair of mocked tools (e.g. `set_light`, `adjust_thermostat`). Every command is
designed to map to exactly one domain, which keeps the comparison clean and
avoids overstating what a single-choice decision layer can do.

Both systems make exactly **2 decision calls per command** (supervisor, then
domain agent). System B adds a small conditional fallback call only when Jev's
own confidence falls below a risk-weighted threshold (security requires more
confidence than lighting before it's trusted unsupervised).

Jev is not given an easier task. Both systems receive the same command and the
same decision definitions, but they are represented differently: System A gets
chat-style system/user prompts, while System B gets Jev's structured
`state`/`questions`/`criteria` payload. That structured Jev payload can be
larger in token count even though the decision model is still faster and cheaper
overall.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full breakdown.

## Setup

```powershell
pip install -r requirements.txt
copy .env.example .env
```

Add your OpenRouter API key and model settings to `.env`:

```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_CHAT_MODEL=openai/gpt-6-luna
```

## Usage

**Check connectivity:** runs one event and makes one direct call to the chat
endpoint plus one direct call to the Jev endpoint.
```powershell
python -m smart_home_hub.cli check
```

**Run the full benchmark:**
```powershell
python -m smart_home_hub.cli run --events docs/smart_home_events.json --out runs/latest.json
```

**Live interactive dashboard** (type a command, see both systems respond in real time):
```powershell
python -m smart_home_hub.live_server
```
Then open `http://127.0.0.1:8765/`. Each panel is labeled by which layer made
the decision ("System A - LLM decision" / "System B - Jev decision"). Every
result shows a decision-layer speed/cost comparison; if a confidence-based
fallback fired, a second line reports the end-to-end comparison including
that fallback's cost.

You can also load any saved run's JSON output into the dashboard to replay it
with synchronized, real-latency-driven playback.

## Evaluation

Decisions are scored two ways:

- **Categorical accuracy** (exact match): for fields with one correct answer,
  which domain, which room, which door, which appliance.
- **Magnitude directional correctness**: for subjective fields like brightness
  and target temperature, exact-match scoring doesn't make sense (there's no
  single "correct" brightness for "dim the lights a bit"). Instead, this checks
  whether the decision moved in the right direction from the real current
  reading, by a reasonable amount.

## Results

From a 100-command benchmark run (System A: `openai/gpt-6-luna`, System B: `typesafe/jev-1.13`):

| Metric | System A (LLM) | System B (Jev) |
|---|---|---|
| Decision-layer speed (excludes fallback) | 336.3 s total | 39.1 s total (**~8.6x faster**) |
| End-to-end speed (includes fallback) | 336.3 s total | 75.9 s total (**~4.4x faster**) |
| Decision-layer cost (excludes fallback) | $0.00873 | $0.00402 (**~2.2x cheaper**) |
| End-to-end cost (includes fallback) | $0.00873 | $0.00452 (**~1.9x cheaper**) |
| Fallback rate | n/a | 7.0% |
| Categorical accuracy (domain, room, door, appliance) | 100% | 99.1% |
| Magnitude directional accuracy (brightness, temperature) | 75.6% | 84.4% |
| Inter-system domain agreement | 100% | |
| Inter-system domain-field agreement | 86.5% | |

The decision layer alone is dramatically faster and cheaper. Once System B's
own confidence-based fallback calls are included honestly, the advantage
narrows but remains real. Both numbers are reported because they answer
different questions: decision-layer speed shows Jev's raw capability, while
end-to-end speed shows what actually happens once its own uncertainty is
accounted for.

Both systems agreed perfectly on *which domain* should handle each command.
The remaining differences were in the selected domain fields: exact categorical
choices such as lock/unlock or start/stop, and subjective magnitude choices
such as brightness or target temperature. In this 100-command run, System B
triggered fallback on 19 of 270 checked fields, and 15 of those fallbacks
changed Jev's original answer. Some fallback changes helped; some overrode an
already reasonable or correct Jev choice. This is a genuine tradeoff: Jev's
speed/cost advantage is real, but confidence-based fallback is not automatically
safer just because it uses a general LLM as the backup.

## Notes
- All sensor readings and device states are mocked. This does not control real
  hardware.
- This benchmark uses single-domain commands by design, to keep the comparison
  fair to a single-choice decision layer. Commands genuinely requiring multiple
  domains at once are outside its current scope.
