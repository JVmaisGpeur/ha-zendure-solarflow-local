# Zendure SolarFlow Local

[🇫🇷 Français](README.md) · 🇬🇧 English

Home Assistant integration to control **Zendure SolarFlow** batteries **100 % locally**, through the battery's zenSDK HTTP API: no cloud, no MQTT, no YAML. One battery on its own, or a **group of 2 to 4 batteries** working together.

Models with the zenSDK API: SolarFlow 800 / 800 Plus / 800 Pro (2), 1600 AC+, 2400 AC / AC+ / Pro, 3000 Mix AC+, 4000 Mix AC+ / Pro.
Does **not** work with: Hyper 2000, Hub 1200/2000, AIO 2400, Ace 1500 (no local API).

## Requirements

1. A fixed IP for each battery (DHCP reservation on your router), recommended.
2. **Enable the local API** in the Zendure app: device settings → local API / **HEMS**. It is off by default since EN 18031.
3. Quick check in a browser: `http://BATTERY_IP/properties/report` must return JSON.

> ⚠️ **One battery, one controller.** If another integration already controls the battery (for example the Zendure-HA “Zendure Manager”, or a smart-meter mode in the Zendure app), both will fight each other. Set the other controller to `off` for the batteries managed here.

## Installation (HACS)

1. HACS → ⋮ → **Custom repositories** → `https://github.com/JVmaisGpeur/ha-zendure-solarflow-local`, category **Integration**.
2. Install **Zendure SolarFlow Local**, then restart Home Assistant.
3. **Settings → Devices & services → Add integration** → *Zendure SolarFlow Local*. The integration searches the network for batteries (a few seconds), then offers:
   - **Add the batteries found**: tick them, they are all added at once. With two or more batteries, the **Create a group** box (ticked by default) also creates their group;
   - **Add a battery by its IP address**, if it was not found;
   - **Create a battery group**, as soon as two batteries are added.

   The wizard then asks for the **power sensor at the meter** (required: positive when the home draws from the grid, negative when it exports) and, optionally, the **solar production sensor**. If Home Assistant's **Energy dashboard** is set up, both fields are already filled with its sensors: just confirm. The card has nothing left to ask.

   Everything else comes from the battery: charge levels, power limits set in the Zendure app, capacity computed from the packs. **Configure** shows only the essentials; fine settings are in collapsed sections.

Manual installation: copy `custom_components/zendure_local` into `config/custom_components/` and restart.

The interface (entities, options, alerts, card) is in **English** and **French**, following Home Assistant's language.

## Settings explained

Most settings have a default that suits. Each field also has a short explanation shown under it in Home Assistant.

### When adding

| Screen | Setting | What it does |
|---|---|---|
| Batteries found | **Batteries** | Batteries found on your network. Untick those not to manage. |
| | **Create a group** | One mode for all the batteries, with charging and discharging shared between them. **Essential if they are on the same meter**, otherwise they fight each other. |
| IP address | **IP address** | Only if the battery was not found. Reserve a fixed IP for it in your router. |
| Electrical circuit | **Each on its own circuit / All on the same circuit** | Groups only. If the batteries share a breaker, their total power is limited so it never exceeds it. |
| Shared circuit | **Circuit limit** | Choose the breaker rating (16 A ≈ 3,600 W). The “output / charge” values are plug limits used in some countries. The W fields are for a value not in the list. |
| Sensors | **Power sensor at the meter** | What enters the home from the grid (positive) or leaves it (negative), e.g. the Shelly Pro 3EM phase on the incoming supply. The regulation tries to bring it to 0. Pre-filled from the Energy dashboard. |
| | **Invert sign** | Only if your sensor is positive when the home **exports**. |
| | **Solar production sensor** | Optional. Used by the “Store solar” mode and the card. |

### Configure (battery or group)

**At the top, the essentials:**

| Setting | What it does |
|---|---|
| **Minimum / maximum charge level** | Single battery. The battery never goes below the minimum nor above the maximum. Written to the battery, as in the Zendure app. |
| **Group batteries** | Group only. Removing a battery gives it back its previous mode. |
| **Sensors** | Same as when adding. Not needed on a group member: the group regulates. |

**“Power limits and capacity” section** (battery). Empty = follow the battery.

| Setting | Empty = | When to fill it |
|---|---|---|
| **Maximum charge power** | Zendure app limit | to charge more gently |
| **Maximum discharge power** | Zendure app output limit | to supply less to the home |
| **Circuit limit** | none | battery alone on a small breaker (10 A ≈ 2,300 W) |
| **Capacity** | computed from the packs | wrong capacity or “Unknown capacity” alert |

**“Advanced regulation settings” section**: defaults almost always suit.

| Setting | Default | Effect |
|---|---|---|
| **Target at the meter** | 0 W | Value aimed for at the meter. E.g. 20 W keeps a small margin to never export. |
| **Import limit** | 6,000 W | In “Grid charge”, maximum power drawn from the grid, home included. Keep **at least 10 %** margin on your contract. |
| **Deadband** | 25 W | Deviation tolerated before correcting. Larger = fewer corrections. |
| **Minimum delay between two calculations** | 1 s | Adapted automatically by auto-tuning. |
| **Reading while regulating** | 2 s | How often the battery is read while regulating. |
| **Scan interval** | 10 s | How often it is read at rest. |
| **Write to RAM** | yes | Avoids wearing out the battery's permanent memory. Leave ticked. |

**Group-only sections:**

| Setting | What it does |
|---|---|
| **Priority order** | Only with the “Priority” strategy: no. 1 works alone as long as it is enough, then the next ones take over. |
| **Shared circuits A / B** | When **only some** batteries share a circuit (group of 3 or 4). For each circuit: its batteries, output limit and charge limit (empty = same value). |

### In the card or the entities (changeable at any time)

| Entity | What it does |
|---|---|
| **Operating mode** | See [Operating modes](#operating-modes). On a group, one choice for all batteries. |
| **Strategy** (group) | How power is shared: **SOC balance** (default, levels converge), **Simultaneous** (in proportion to each one's power), **Priority** (in the chosen order). |
| **Power setpoint** | Manual mode: + supplies the home, − charges. Setting it switches to manual mode. |
| **Import limit / Charge target SOC** | “Grid charge” mode. See below. |
| **Charge / discharge power cap, Power not to cover** | No effect until set. They limit the setpoint without changing mode. See [External control](#external-control). In the card, they only appear when they have an effect. |

## Operating modes

| Mode (key) | What the battery does |
|---|---|
| **Off** (`off`) | Neither charges nor discharges (setpoint 0) |
| **Manual power** (`manual`) | Follows the **Power setpoint** |
| **Smart matching** (`smart`) | Stores solar surplus instead of exporting it, and supplies what the home is missing |
| **Smart discharge** (`smart_discharge`) | Only supplies what the home is missing, never charges |
| **Smart charge** (`smart_charge`) | Only stores solar surplus, never discharges |
| **Store solar** (`solar`) | Charges all solar production (solar production sensor required; otherwise like “Smart charge”) |
| **Grid charge** (`grid_charge`) | Charges from the grid without exceeding the **grid import limit**, up to the **charge target SOC** |
| **Controlled by the group** (`group`) | Battery belonging to a group: the group controls it |

Automatic modes need the **power sensor at the meter** (asked when adding, changeable in Configure), e.g. Shelly Pro 3EM phase A: **positive when importing, negative when exporting** (otherwise tick “Invert sensor sign”).

The integration handles **no tariffs** (peak / off-peak, Tempo…): your automations change the mode.

### Grid charge: import limit and target SOC

- **Grid import limit** (`import_limit`, W): the battery charges as fast as possible while keeping the meter below this value. Adjustable at any time, from the card or an automation.
- **Charge target SOC** (`charge_target_soc`, %): charging stops at this level and the battery stays idle, without discharging. It only resumes when the SOC drops **3 points** below the target.

> ⚠️ The import limit is **not a strict guarantee**: regulation reacts to the meter reading. When a large appliance starts, import may exceed the limit for 2 to 5 s before correction (about 4 s in simulation). Keep a margin of **at least 10 %** of your subscribed power: `import_limit` = subscribed power − expected large loads − margin.

Example: partial charge to 80 % without exceeding 6 kVA, with a 10 % margin.

```yaml
- action: number.set_value
  target: { entity_id: number.zendure_solarflow_2400_ac_grid_import_limit }
  data: { value: 5400 }
- action: number.set_value
  target: { entity_id: number.zendure_solarflow_2400_ac_charge_target_soc }
  data: { value: 80 }
- action: select.select_option
  target: { entity_id: select.zendure_solarflow_2400_ac_operating_mode }
  data: { option: grid_charge }
```

> `entity_id`s depend on the device name: check them in **Settings → Entities**.

## Battery group

Several batteries on the same meter must not regulate on their own: they would fight each other. A **group** brings 2 to 4 already added batteries under **a single regulator**, which reads the meter once and splits the setpoint. Models may differ (e.g. 2400 AC and 2400 AC+).

**Create a group**: once the batteries are added, Add integration (or “Add entry” on the integration page) → *Zendure SolarFlow Local* → **Create a battery group** → name + batteries. The batteries switch to **“Controlled by the group”**.

- The group is a separate device, controlled exactly like a single battery: same modes, setpoint, import limit, target SOC.
- Each battery keeps its own device, sensors and energy counters.
- Regulation settings (grid sensor, target, deadband, solar sensor…) are set on the group. Those of a member battery are kept but **ignored** while it is a member; the card shows it.
- Changing the mode of a member battery **takes it out of group control** (Repairs alert) without breaking the group. Setting “Controlled by the group” again brings it back.
- Removing a battery from the group (group options) or **deleting the group** gives each battery back its previous mode.

**Dispatch strategy** (`strategy`):

| Key | Behaviour |
|---|---|
| `simultaneous` | Setpoint split in proportion to each battery's maximum power |
| `soc_balance` (default) | The fullest discharges more, the emptiest charges more: SOCs converge |
| `priority` | Order set in the options: the first battery works alone up to its limit (power or SOC), then the next one takes over |

**Dispatcher safety**
- Never one battery charging while another discharges.
- Each battery stays within its limits (power, min / max SOC, target SOC); what it cannot take is moved to the others.
- An unreachable, faulty or released battery leaves the dispatch: the group keeps running with the others (**Degraded** state, Repairs alert) and takes it back when it returns.

![Group card](docs/apercu-groupe.png)

## Power limits and circuits

- **Maximum charge / discharge power**: by default, those set in the **Zendure app** (read from the battery). The options (“Power limits and capacity” section) only lower them.
- **Circuit limit** (W): if the battery is plugged on a limited circuit (like Zendure-HA “fuse groups”, e.g. 1200 W), it will never exceed it.
- **Common circuit of a group**: when creating the group, the wizard asks whether the batteries are on the same electrical circuit. If so, pick the limit from a list (taken from the official integration's “fuse groups”: 800 W output / 1,200 W charge, 1,200 W, 2,400 W, 3,600 W for a 16 A breaker…) or enter your own values. Power is then shared between the batteries, following the group strategy, so their total never exceeds the circuit; what one battery cannot take goes to the others.
- **Shared circuits** (group options, collapsed section): up to two circuits A and B, each with its batteries, output limit and charge limit (empty = same value). Useful when only some batteries share a circuit.
- Limits reported by the battery itself (maximum power, thermal derating) are respected too.

The **Max charge power** and **Max discharge power** sensors show the limit actually applied.

## Capacity and energy

**Usable capacity** is computed from the type of each detected pack:

| Pack | Capacity |
|---|---|
| AB3000 | 2.88 kWh |
| AB2000S | 1.92 kWh |
| AB3000L | 2.88 kWh |
| I2400 (built into the 2400 AC+) | 2.40 kWh |
| Built-in pack of the 3000 / 4000 Mix AC+ (packType 70) | 8.0 kWh |

An unknown pack raises an alert: enter the capacity in the battery options. **Available energy** = capacity × (SOC − min SOC); **Missing energy** = capacity × (max SOC − SOC).

## Lovelace card included

The integration installs and loads its own card: **nothing to add to resources or HACS**.

![Card preview](docs/apercu-carte.png)

Dashboard → **Edit** → **Add card** → **Zendure SolarFlow**, or in YAML:

```yaml
type: custom:zendure-solarflow-card
device_id: ...                     # optional: battery or group (otherwise the first one found)
name: My battery                   # optional
solar_entity: sensor.solar_power   # optional: overrides the solar sensor set in the integration
consumers:                         # optional, up to 5 devices
  - sensor.fridge_power
show_history: true
show_flow: true
```

It shows the animated battery (or the global SOC of a group), the 24 h chart, capacity, energy flows, regulation state and controls: mode, strategy (group), Grid charge (import limit, target SOC), min / max charge levels, manual power. For a group, one row per battery: SOC, minimum and maximum charge levels (hatched zones on the bar), power, state.

## Regulation

- Recomputed on **every meter reading** (about 1 s with a Shelly), battery polled every 2 s while regulating.
- Protection against overshoot and oscillation; **fine trim** of small persistent offsets.
- **Auto-tuning** (on by default): learns the meter rate, its noise and the batteries' response time; **Measure battery response** and **Reset learning** buttons.

## Sign conventions

| Value | + | − |
|---|---|---|
| `battery_power` (Battery power sensor) | charging | discharging |
| `power_setpoint` (Power setpoint) | discharging to the home | charging |
| Grid sensor | import | export |

These conventions will not change (harmonising them would break existing automations).

## Interface for other integrations

A single battery and a group expose the same control entities (**interface version 1**). Find them through the Home Assistant registry (device + `translation_key`), never by `entity_id`.

| `translation_key` | Type | Unit / values | Battery | Group |
|---|---|---|---|---|
| `operating_mode` | select | `off`, `manual`, `smart`, `smart_discharge`, `smart_charge`, `solar`, `grid_charge` (+ `group` on a member battery) | ✓ | ✓ |
| `power_setpoint` | number | W, + discharge, − charge | ✓ | ✓ (total, dispatched) |
| `import_limit` | number | W | ✓ | ✓ |
| `charge_target_soc` | number | % | ✓ | ✓ |
| `electric_level` | sensor | % | ✓ | ✓ (capacity-weighted) |
| `usable_capacity` | sensor | kWh | ✓ | ✓ |
| `available_energy` / `missing_energy` | sensor | kWh | ✓ | ✓ |
| `battery_power` | sensor | W, + charge, − discharge | ✓ | ✓ |
| `max_charge_power` / `max_discharge_power` | sensor | W | ✓ | ✓ |
| `regulation_state` | sensor (enum) | `off`, `manual`, `regulating`, `grid_charging`, `target_reached`, `import_limited`, `soc_max_reached`, `soc_min_reached`, `sensor_unavailable`, `error`, `charge_capped`, `discharge_capped`, `load_excluded` (+ `group` on a member, `degraded` on a group) | ✓ | ✓ |
| `external_control` | sensor (enum) | `active`, `inactive` ; attributs `controller`, `controlled_keys` | ✓ | ✓ |
| `charge_power_limit` / `discharge_power_limit` | number | W, maximum value = no cap | ✓ | ✓ (total) |
| `excluded_power` | number | W, 0 = no effect | ✓ | ✓ |
| `calibrating` | binary_sensor | `batteries` attribute on a group | ✓ (if `socStatus`) | ✓ |
| `strategy` | select | `simultaneous`, `soc_balance`, `priority` | — | ✓ |
| `active_batteries` | sensor | count | — | ✓ |

Rules:
- An unknown enum value must be treated as “not handled”.
- Renaming or removing anything in this table, or changing a unit or sign, requires a major version (2.0.0), announced one version ahead in the CHANGELOG.
- Diagnostic sensors, options and attributes are not part of the interface.
- **Key language**: this interface uses English keys, while the ha-tarifs-electricite integration keeps French keys (already published). This is deliberate and must not be “fixed” without a major version.

Usage example: an external controller (an integration or an automation taking tariffs and solar forecast into account) schedules an off-peak charge with `import_limit`, `charge_target_soc` and `operating_mode` = `grid_charge`. The integration simply applies the latest command received, whoever sent it.


### External control

The commands below can be set by hand, by an automation or by any external controller. **As long as nobody sets them, they have no effect.** Their value stays in Home Assistant and is **never written to the battery's memory**: only the resulting setpoints are sent, to RAM, as usual. They are set with the standard `number.set_value` action and applied at the next regulation cycle.

| Command (`translation_key`) | Range | No effect | Effect |
|---|---|---|---|
| **Charge power cap** (`charge_power_limit`) | 0 W to max charge | max charge | The battery never charges above it, solar or grid. 0 W = no charging. |
| **Discharge power cap** (`discharge_power_limit`) | 0 W to max discharge | max discharge | The battery never supplies more to the home. 0 W = no discharging. |
| **Power not to cover** (`excluded_power`) | 0 to 10,000 W | 0 W | Discharge only: the battery never supplies more than the home consumption minus this power (e.g. a water heater running). |

- **Where**: on each group and each battery outside a group. On a group, the cap applies to the total, shared according to the strategy. On a group member, the value is kept but ignored.
- **Modes**: all modes where the regulation commands a power, manual included. The final setpoint is the minimum of the Zendure app limits, the options, the circuit and the cap; in Grid charge, the import limit applies as well.
- **Home consumption** = grid import + battery discharge + solar production. Without a solar sensor, production counts as 0: the battery then covers a little less, never more. A small margin (half the deadband, 50 W at most) keeps a meter noise spike from covering the excluded appliances.
- **Regulation state**: `charge_capped`, `discharge_capped` or `load_excluded` when one of these commands limits the setpoint.
- **Persistence**: a value set by hand survives a restart. A value set by a controller that declares this key (see below) returns to “no effect” when its declaration expires or is withdrawn, even if that happens while Home Assistant is stopped: a battery is never left blocked by a vanished controller. The `set_by` attribute names the controller.

#### Declaring external control: `zendure_local.set_external_control`

An external controller states that it controls the battery (or group), and which settings. The action **does not change how the battery works**: it declares it in the `external_control` sensor.

| Field | Role |
|---|---|
| `device_id` | Battery or group concerned |
| `active` | `true`: take over or renew; `false`: hand back |
| `controller` | Controller name (`controller` attribute) |
| `controlled_keys` | Controlled keys: `operating_mode`, `import_limit`, `charge_target_soc`, `min_soc`, `soc_set`, `charge_power_limit`, `discharge_power_limit`, `excluded_power` |

Without a new call with `active: true`, the declaration **expires after 30 minutes**. It survives a Home Assistant restart as long as it has not expired. On expiry or withdrawal, `charge_power_limit`, `discharge_power_limit` and `excluded_power` set by that controller return to “no effect”; other keys keep their value.

```yaml
action: zendure_local.set_external_control
data:
  device_id: 0123456789abcdef
  active: true
  controller: My controller
  controlled_keys: [discharge_power_limit, excluded_power]
```

#### Charge level calibration

- **Calibrating** (`calibrating`, binary sensor): follows the battery's `socStatus` property (1 = calibrating). Created only if the battery provides `socStatus`. On a group: on if at least one battery calibrates, listed in the `batteries` attribute.
- **Calibration time** (`calibration_time`, diagnostic, disabled by default): `batCalTime` property, in minutes, **read only** (Zendure advises against changing it).
- The integration never interferes with a calibration: the device runs it alone. According to Zendure support, it happens after about 30 days without a full charge; for it to complete, keep the battery powered, its charge limit at 100 %, and do not lock its power at 0 W.
- A calibration lasting more than **72 h** raises an alert in **Repairs**, with the details to give Zendure support.

**Detection by a controller**: by the presence of the entities (device + `translation_key`), not by version number. The keys `charge_power_limit`, `discharge_power_limit`, `excluded_power`, `calibrating` and `calibration_time` will not change anymore.

## Technical details

- Read: `GET http://IP/properties/report`; write: `POST http://IP/properties/write`.
- Discharge: `acMode: 2` + `outputLimit`; charge: `acMode: 1` + `inputLimit`; frequent commands written to RAM (`smartMode: 1`).
- `socSet` / `minSoc` in tenths of %; temperatures in tenths of kelvin.
- Automatic discovery via mDNS `_zendure._tcp`.

## Tests

`tests/` holds tests for the dispatcher, translations, the interface contract and regulation scenarios (single battery, grid charge, 30-minute group run, strategies, unplugged battery, members), run with the real code in simulated time:

```bash
python3 tests/run_all.py
```

## License

MIT © JVmaisGpeur
