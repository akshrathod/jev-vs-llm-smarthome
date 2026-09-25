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

System A uses one chat-completions JSON call for the selected domain decision.

System B uses one Jev Decisions API call for the selected domain decision.

## Calls Per Event

For ordinary actionable events:

- System A makes exactly two LLM decision calls: supervisor, then selected domain agent.
- System B makes exactly two Jev decision calls: supervisor, then selected domain agent.

If the supervisor chooses `none`, only the supervisor call is made.

System B applies the confidence-threshold LLM fallback independently after each Jev call. Low-confidence fields within a call are batched into one fallback request for that call. The fallback is not part of the normal Jev decision count.

## Confirmations

Confirmation text is deterministic code, not a model decision and not a model generation call. Each tool function has a fixed confirmation template based on the chosen domain fields.
