# Smart Home Hub Architecture

## Shape

The benchmark uses a two-level Supervisor + Domain Agent graph.

1. `supervisor_node` makes one structured decision from the raw event text.
2. Conditional routing sends the event to exactly one domain node: `climate_agent`, `lighting_agent`, `security_agent`, or `appliance_agent`.
3. If the supervisor chooses `none`, the graph skips domain execution and goes straight to `aggregate_node`.
4. The selected domain agent makes one structured decision.
5. The selected domain node calls one mocked tool and creates a deterministic confirmation string in code.
6. `aggregate_node` returns the final record. It does not call a model.

## Supervisor Decision

The supervisor has no tools. It outputs exactly one field:

- `target_domain`: Choice among `climate`, `lighting`, `security`, `appliance`, `none`

System A uses one chat-completions JSON call for this decision.

System B uses one Jev Decisions API call for this decision.

## Domain Decisions

Only the domain selected by the supervisor runs.

Climate outputs:

- `target_room`: Choice among `living_room`, `bedroom`
- `target_temperature`: Choice among `65`, `68`, `72`, `75`, `78`

The climate tool is `adjust_thermostat(room, target)`. Each `target_temperature` option is used directly as the target.

Lighting outputs:

- `target_room`: Choice among `living_room`, `bedroom`, `kitchen`, `entrance`
- `brightness`: Choice among `off`, `25`, `50`, `75`, `100`

The lighting tool is `set_light(room, state, brightness)`. `off` maps to `state=off` and `brightness=0`; every numeric option maps directly to that integer percentage with `state=on`.

Security outputs:

- `door`: Choice among `entrance_front_door`, `kitchen_back_door`
- `state`: Choice among `locked`, `unlocked`

The security tool is `set_door_lock(door, state)`.

Appliance outputs:

- `appliance`: Choice among `fridge`, `microwave`, `stove`
- `action`: Choice among `start`, `stop`

The appliance tool is `control_appliance(appliance, action)`.

### Tool Execution Is Not Native Function-Calling

In this project, "tool" means a deterministic Python function in `tools.py`, not an OpenAI-style native function-calling or tool-calling API. System A and System B only output structured decision fields such as domain, room, brightness, target temperature, door, state, appliance, and action.

After those fields are decided, `agents.py` uses plain conditional logic to dispatch to the matching Python function. For example, if the chosen domain is `lighting`, it reads the decided `target_room` and `brightness`, derives the on/off state, and calls `set_light(room, state, brightness)`. The OpenRouter chat-completions payload for System A never includes a `tools` or `functions` parameter, and the Jev Decisions API payload for System B does not use native function-calling either.

System A uses one chat-completions JSON call for the selected domain decision.

System B uses one Jev Decisions API call for the selected domain decision.

### System B Confidence Thresholds

System B applies the LLM fallback when a Jev answer's confidence is below the threshold for that decision:

- `security`: `0.8`
- `climate`: `0.65`
- `appliance`: `0.65`
- `lighting`: `0.5`

These thresholds differ by domain because higher-stakes domains require more confidence before trusting Jev's answer unsupervised. Security actions use the highest threshold because lock decisions are riskier; lighting uses the lowest threshold because an imperfect lighting choice is lower impact. Climate and appliance decisions sit between those two.

## Calls Per Event

For ordinary actionable events:

- System A makes exactly two LLM decision calls: supervisor, then selected domain agent.
- System B makes exactly two Jev decision calls: supervisor, then selected domain agent.

If the supervisor chooses `none`, only the supervisor call is made.

System B applies the confidence-threshold LLM fallback independently after each Jev call. Low-confidence fields within a call are batched into one fallback request for that call. The fallback is not part of the normal Jev decision count.

## Confirmations

Confirmation text is deterministic code, not a model decision and not a model generation call. Each tool function has a fixed confirmation template based on the chosen domain fields.
