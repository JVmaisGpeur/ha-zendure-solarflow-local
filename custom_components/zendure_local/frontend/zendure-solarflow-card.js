/*
 * Zendure SolarFlow Card — carte Lovelace livrée avec l'intégration zendure_local.
 * Aucune configuration requise : la carte trouve seule les entités de la batterie.
 *
 *   type: custom:zendure-solarflow-card
 *   device_id: ...        # optionnel : choisir la batterie s'il y en a plusieurs
 *   name: ...             # optionnel : titre
 *   capacity: 8           # optionnel : capacité en kWh (sinon déduite du modèle)
 *   solar_entity: sensor.production_solaire   # optionnel, YAML : remplace le capteur solaire de l'intégration
 *   consumers:            # optionnel : jusqu'à 5 appareils affichés dans les flux
 *     - sensor.refrigerateur_puissance
 *   show_history: true    # courbe des dernières 24 h
 *   show_flow: true       # schéma des flux d'énergie
 */
const CARD_VERSION = "1.3.2";
const DOMAIN = "zendure_local";

const I18N = {
  fr: {
    grid: "Réseau", home: "Maison", battery: "Batterie", solar: "Solaire",
    standby: "Veille", charging: "Charge", discharging: "Décharge", unavailable: "Indisponible",
    last24: "Dernières 24 h", available: "Disponible", capacity: "Capacité", cycles: "Cycles", efficiency: "Rendement",
    temp: "Température", flows: "Flux d'énergie", control: "Pilotage", mode: "Mode de fonctionnement",
    setpoint: "Consigne", statusLbl: "Statut",
    socLimits: "Niveaux de charge", socMin: "Minimum", socMax: "Maximum",
    manualTitle: "Puissance manuelle", manualCharge: "Charge manuelle", manualDischarge: "Décharge manuelle",
    power: "Puissance", rest: "Mettre au repos (0 W)",
    gridCharge: "Charge réseau", importLimit: "Limite de soutirage", chargeTarget: "SOC cible de charge",
    ignoredBy: "Ignoré : réglé par le groupe {g}", pilotedBy: "Pilotée par le groupe {g}",
    strategy: "Stratégie de répartition", batteries: "Batteries", activeBatteries: "Actives",
    strategies: { simultaneous: "Simultanée", soc_balance: "Équilibrage des SOC", priority: "Priorité" },
    notFound: "Aucune batterie Zendure trouvée. Vérifie que l'intégration « Zendure SolarFlow Local » est configurée.",
    noSensor: "Ce mode a besoin d'un capteur réseau : Paramètres → Appareils et services → Zendure → Configurer.",
    ed: { device_id: "Batterie ou groupe de batteries", name: "Titre", capacity: "Capacité (kWh, vide = automatique)",
          solar_entity: "Capteur de production solaire (facultatif)", consumers: "Appareils à afficher dans les flux (5 max)",
          show_history: "Afficher la courbe 24 h", show_flow: "Afficher les flux d'énergie" },
    modes: { off: "Arrêt", manual: "Puissance manuelle", smart: "Couplage intelligent",
             smart_discharge: "Décharge intelligente", smart_charge: "Charge intelligente", solar: "Stocker le solaire", grid_charge: "Charge réseau",
             group: "Pilotée par le groupe" },
  },
  en: {
    grid: "Grid", home: "Home", battery: "Battery", solar: "Solar",
    standby: "Standby", charging: "Charging", discharging: "Discharging", unavailable: "Unavailable",
    last24: "Last 24 h", available: "Available", capacity: "Capacity", cycles: "Cycles", efficiency: "Efficiency",
    temp: "Temperature", flows: "Energy flow", control: "Control", mode: "Operating mode",
    setpoint: "Setpoint", statusLbl: "Status",
    socLimits: "Charge levels", socMin: "Minimum", socMax: "Maximum",
    manualTitle: "Manual power", manualCharge: "Manual charge", manualDischarge: "Manual discharge",
    power: "Power", rest: "Set to idle (0 W)",
    gridCharge: "Grid charge", importLimit: "Grid import limit", chargeTarget: "Charge target SOC",
    ignoredBy: "Ignored: set by group {g}", pilotedBy: "Controlled by group {g}",
    strategy: "Dispatch strategy", batteries: "Batteries", activeBatteries: "Active",
    strategies: { simultaneous: "Simultaneous", soc_balance: "SOC balancing", priority: "Priority" },
    notFound: "No Zendure battery found. Make sure the “Zendure SolarFlow Local” integration is set up.",
    noSensor: "This mode needs a grid sensor: Settings → Devices & services → Zendure → Configure.",
    ed: { device_id: "Battery or battery group", name: "Title", capacity: "Capacity (kWh, empty = auto)",
          solar_entity: "Solar production sensor (optional)", consumers: "Devices shown in the flow (max 5)",
          show_history: "Show 24 h chart", show_flow: "Show energy flow" },
    modes: { off: "Off", manual: "Manual power", smart: "Smart matching",
             smart_discharge: "Smart discharge", smart_charge: "Smart charge", solar: "Store solar", grid_charge: "Grid charge",
             group: "Controlled by the group" },
  },
};

const MODES = ["off", "manual", "smart", "smart_discharge", "smart_charge", "solar", "grid_charge"];
const STRATEGIES = ["simultaneous", "soc_balance", "priority"];
const REGULATED = ["smart", "smart_discharge", "smart_charge", "solar", "grid_charge"];
const COLORS = { grid: "#4a90d9", solar: "#ff9800", battery: "#26c6a8", home: "#4a90d9" };
const CONSUMER_COLORS = ["#d4e157", "#ba68c8", "#ab47bc", "#4dd0e1", "#f06292"];

// Coordonnées du schéma de flux (viewBox 540 × 390)
const POS = {
  grid: [60, 195], solar: [185, 68], battery: [185, 322], home: [300, 195],
  c: [[300, 68], [420, 68], [300, 322], [420, 322], [490, 195]],
};
const W = 540, H = 390;

const fmtW = (w) => {
  if (w === null || w === undefined || isNaN(w)) return "—";
  const a = Math.abs(w);
  return a >= 1000 ? `${(a / 1000).toFixed(2)} kW` : `${Math.round(a)} W`;
};
// Format compact pour les cercles du schéma (évite les débordements)
const fmtS = (w) => {
  if (w === null || w === undefined || isNaN(w)) return "—";
  const a = Math.abs(w);
  return a >= 1000 ? `${(a / 1000).toFixed(a >= 10000 ? 0 : 1)} kW` : `${Math.round(a)} W`;
};
// « solarFlow3000MixAC+ » → « SolarFlow 3000 Mix AC+ »
const prettyModel = (name) => {
  if (!name) return name;
  let rest = String(name).replace(/^zendure\s*/i, "");
  let head = "";
  const m = rest.match(/^solar\s*flow/i);
  if (m) {
    head = "SolarFlow";
    rest = rest.slice(m[0].length);
  }
  rest = rest
    .replace(/([a-z])([A-Z0-9])/g, "$1 $2")
    .replace(/([0-9])([A-Za-z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .trim();
  return [head, rest].filter(Boolean).join(" ");
};
const num = (v) => {
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
};

class ZendureSolarflowCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("zendure-solarflow-card-editor");
  }
  static getStubConfig() {
    return { show_history: true, show_flow: true };
  }

  setConfig(config) {
    this._config = { show_history: true, show_flow: true, ...(config || {}) };
    this._built = false;
    this._history = null;
    this._historyAt = 0;
    if (this._hass) this._render();
  }
  set hass(hass) {
    this._hass = hass;
    this._render();
  }
  getCardSize() {
    return 12;
  }
  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }
  disconnectedCallback() {
    clearInterval(this._timer);
    this._timer = null;
  }
  connectedCallback() {
    if (!this._timer) this._timer = setInterval(() => this._loadHistory(true), 10 * 60 * 1000);
  }

  get _t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").slice(0, 2);
    return I18N[lang] || I18N.en;
  }

  /* -------- recherche des entités par translation_key (indépendant des noms et de la langue) -------- */
  _resolve() {
    const all = Object.values(this._hass.entities || {}).filter((e) => e.platform === DOMAIN);
    const deviceId = this._config.device_id || all.find((e) => e.translation_key === "operating_mode")?.device_id;
    if (!deviceId) return null;
    const map = { deviceId };
    for (const e of all) {
      if (e.device_id === deviceId && e.translation_key && !(e.translation_key in map)) map[e.translation_key] = e.entity_id;
    }
    return map;
  }
  _state(key) {
    const id = this._ents?.[key];
    return id ? this._hass.states[id] : undefined;
  }
  _val(key) {
    return num(this._state(key)?.state);
  }
  _watts(entityId) {
    const s = entityId && this._hass.states[entityId];
    if (!s) return null;
    let v = num(s.state);
    if (v !== null && s.attributes.unit_of_measurement === "kW") v *= 1000;
    return v;
  }
  _gridPower() {
    const sel = this._state("operating_mode");
    const v = this._watts(sel?.attributes?.capteur_reseau);
    return v === null ? null : sel.attributes.inverser_signe ? -v : v;
  }
  _fmt(st) {
    if (!st) return "—";
    if (st.state === "unavailable") return this._t.unavailable;
    try {
      return this._hass.formatEntityState ? this._hass.formatEntityState(st) : st.state;
    } catch (e) {
      return st.state;
    }
  }
  get _isGroup() {
    return !!this._ents?.strategy;
  }
  // Entités d'une batterie membre d'un groupe (par l'appareil rattaché à son entrée)
  _memberEnts(entryId) {
    const dev = Object.values(this._hass.devices || {}).find((d) => (d.config_entries || []).includes(entryId));
    if (!dev) return null;
    const map = { deviceId: dev.id };
    for (const e of Object.values(this._hass.entities || {})) {
      if (e.device_id === dev.id && e.platform === DOMAIN && e.translation_key && !(e.translation_key in map)) map[e.translation_key] = e.entity_id;
    }
    return map;
  }
  _capacity() {
    if (num(this._config.capacity)) return num(this._config.capacity);
    const usable = this._val("usable_capacity");
    if (usable) return usable;
    const model = `${this._device?.model || ""} ${this._device?.name || ""}`.toLowerCase();
    if (/mix/.test(model)) return 8; // SolarFlow 3000 / 4000 Mix : 8 kWh
    const packs = this._val("pack_num") || 1;
    if (/800/.test(model)) return 1.92 * packs; // packs AB2000
    return 2.88 * packs; // packs AB3000X (2400 AC, 1600 AC+…)
  }
  _solarEntity() {
    return this._config.solar_entity || this._state("operating_mode")?.attributes?.capteur_solaire || null;
  }
  _moreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  /* --------------------------------------- historique --------------------------------------- */
  async _loadHistory(force = false) {
    if (!this._config.show_history || !this._hass || !this._ents?.electric_level) return;
    if (!force && Date.now() - this._historyAt < 10 * 60 * 1000) return;
    this._historyAt = Date.now();
    const id = this._ents.electric_level;
    try {
      const res = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: new Date(Date.now() - 24 * 3600 * 1000).toISOString(),
        entity_ids: [id],
        minimal_response: true,
        no_attributes: true,
      });
      this._history = (res[id] || [])
        .map((p) => [((p.lu ?? p.last_updated) * (p.lu ? 1000 : 1)) || Date.parse(p.last_updated), num(p.s ?? p.state)])
        .filter((p) => p[1] !== null && !isNaN(p[0]));
      this._drawHistory();
    } catch (e) {
      this._history = [];
    }
  }
  _drawHistory() {
    const svg = this._$("spark");
    if (!svg) return;
    const pts = [...(this._history || [])];
    const now = Date.now(), start = now - 24 * 3600 * 1000;
    const cur = this._val("electric_level");
    if (cur !== null) pts.push([now, cur]);
    if (pts.length < 2) {
      svg.innerHTML = "";
      return;
    }
    const x = (t) => ((Math.max(t, start) - start) / (now - start)) * 300;
    const y = (v) => 46 - (v / 100) * 42;
    // Courbe en escalier : la valeur tient jusqu'au point suivant
    let d = `M0 ${y(pts[0][1])}`;
    for (let i = 0; i < pts.length; i++) {
      d += ` L${x(pts[i][0]).toFixed(1)} ${y(i ? pts[i - 1][1] : pts[0][1]).toFixed(1)} L${x(pts[i][0]).toFixed(1)} ${y(pts[i][1]).toFixed(1)}`;
    }
    d += ` L300 ${y(pts[pts.length - 1][1]).toFixed(1)}`;
    svg.innerHTML = `
      <defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="var(--z-green)" stop-opacity=".35"/><stop offset="1" stop-color="var(--z-green)" stop-opacity="0"/>
      </linearGradient></defs>
      <path d="${d} L300 48 L0 48 Z" fill="url(#sg)"/>
      <path d="${d}" fill="none" stroke="var(--z-green)" stroke-width="1.6" vector-effect="non-scaling-stroke"/>`;
  }

  /* --------------------------------------- construction --------------------------------------- */
  _build() {
    const t = this._t;
    const cfg = this._config;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const consumers = (cfg.consumers || []).slice(0, 5).map((c) => (typeof c === "string" ? { entity: c } : c));
    this._consumers = consumers;

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card id="card">
        <!-- ======================= Batterie ======================= -->
        <div class="head">
          <div class="title" id="name"></div>
          <div class="pill" id="state"><i></i><span></span></div>
        </div>

        <div class="hero">
          <div class="bat" id="bat-click">
            <svg viewBox="0 0 100 150">
              <defs><clipPath id="bclip"><rect x="8" y="16" width="84" height="128" rx="14"/></clipPath></defs>
              <rect x="34" y="2" width="32" height="12" rx="4" class="cap"/>
              <rect x="6" y="14" width="88" height="132" rx="16" class="shell"/>
              <g clip-path="url(#bclip)">
                <g id="liquid">
                  <path class="wave w2" d="M0 6 Q12.5 0 25 6 T50 6 T75 6 T100 6 T125 6 T150 6 T175 6 T200 6 V200 H0 Z"/>
                  <path class="wave w1" d="M0 6 Q12.5 12 25 6 T50 6 T75 6 T100 6 T125 6 T150 6 T175 6 T200 6 V200 H0 Z"/>
                </g>
                <rect x="16" y="24" width="7" height="100" rx="3.5" class="shine"/>
              </g>
              <line id="minline" x1="10" x2="90" y1="140" y2="140" class="minline"/>
            </svg>
          </div>
          <div class="big">
            <div class="pct"><span id="soc">—</span><sup>%</sup></div>
            <div class="kwh" id="kwh">—</div>
            <div class="flowtxt" id="battxt"></div>
          </div>
        </div>

        ${cfg.show_flow ? "" : `<div class="tiles2">
          <div class="tile" id="t-home"><div class="tl"><ha-icon icon="mdi:home"></ha-icon>${t.home}</div><b id="v-home">—</b></div>
          <div class="tile" id="t-grid"><div class="tl"><ha-icon icon="mdi:transmission-tower"></ha-icon>${t.grid}</div><b id="v-grid">—</b></div>
        </div>`}

        ${cfg.show_history ? `
        <div class="hist" id="hist">
          <div class="hrow"><span>${t.last24}</span><b id="h-now"></b></div>
          <svg id="spark" viewBox="0 0 300 48" preserveAspectRatio="none"></svg>
        </div>` : ""}

        <div class="members" id="members"></div>

        <div class="tiles4">
          <div class="stat" id="s-avail"><small>${t.available}</small><b id="v-avail">—</b></div>
          <div class="stat" id="s-cap"><small>${t.capacity}</small><b id="v-cap">—</b></div>
          <div class="stat" id="s-cyc"><small>${t.cycles}</small><b id="v-cyc">—</b></div>
          <div class="stat" id="s-eff"><small>${t.efficiency}</small><b id="v-eff">—</b></div>
        </div>
        <div class="chips">
          <div class="chip" id="c-temp"><ha-icon icon="mdi:thermometer"></ha-icon>${t.temp} <b id="v-temp">—</b></div>
          <div class="chip" id="c-status"><ha-icon icon="mdi:information-outline"></ha-icon>${t.statusLbl} <b id="v-status">—</b></div>
        </div>

        <!-- ======================= Flux ======================= -->
        ${cfg.show_flow ? `
        <div class="sect"><ha-icon icon="mdi:transmission-tower"></ha-icon>${t.flows}</div>
        <div class="flowbox">
          <div class="flow" id="flow">
            <svg id="flowsvg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"></svg>
            <div id="nodes"></div>
          </div>
        </div>` : ""}

        <!-- ======================= Pilotage ======================= -->
        <div class="sect"><ha-icon icon="mdi:tune-vertical-variant"></ha-icon>${t.control}</div>
        <div class="ctrl">
          <div class="crow">
            <div class="cicon"><ha-icon icon="mdi:cog-transfer"></ha-icon></div>
            <div><div class="ctitle">${t.mode}</div><div class="csub" id="mode-sub">—</div></div>
          </div>
          <div class="selwrap">
            <select id="mode">${MODES.map((m) => `<option value="${m}">${t.modes[m]}</option>`).join("")}</select>
            <ha-icon icon="mdi:menu-down"></ha-icon>
          </div>
          <div class="hint" id="hint"></div>
          <div class="note" id="member-note"></div>
          <div class="slabel" id="strat-label">${t.strategy}</div>
          <div class="selwrap" id="strat-wrap">
            <select id="strategy">${STRATEGIES.map((m) => `<option value="${m}">${t.strategies[m]}</option>`).join("")}</select>
            <ha-icon icon="mdi:menu-down"></ha-icon>
          </div>
          <div class="manual" id="manual">
            <div class="crow">
              <div class="cicon"><ha-icon icon="mdi:hand-back-right-outline"></ha-icon></div>
              <div><div class="ctitle">${t.manualTitle}</div><div class="csub" id="man-sub">—</div></div>
            </div>
            <div class="dirgrid">
              <button class="dir" id="d-charge" data-dir="-1"><ha-icon icon="mdi:battery-arrow-down"></ha-icon><span>${t.manualCharge}</span></button>
              <button class="dir" id="d-dis" data-dir="1"><ha-icon icon="mdi:battery-arrow-up"></ha-icon><span>${t.manualDischarge}</span></button>
            </div>
            <label class="socin"><span>${t.power} <small id="rg-pw"></small></span>
              <div class="field"><input type="number" id="in-pw" inputmode="numeric" step="10" min="0" /><em>W</em></div></label>
            <button class="rest" id="b-rest"><ha-icon icon="mdi:pause-circle-outline"></ha-icon>${t.rest}</button>
          </div>
          <div class="socbox" id="gcbox">
            <div class="crow">
              <div class="cicon"><ha-icon icon="mdi:transmission-tower-import"></ha-icon></div>
              <div><div class="ctitle">${t.gridCharge}</div><div class="csub warn" id="gc-ignored"></div></div>
            </div>
            <div class="socgrid">
              <label class="socin"><span>${t.importLimit}</span>
                <div class="field"><input type="number" id="in-imp" inputmode="numeric" step="100" min="0" /><em>W</em></div></label>
              <label class="socin"><span>${t.chargeTarget}</span>
                <div class="field"><input type="number" id="in-tgt" inputmode="numeric" step="1" min="0" max="100" /><em>%</em></div></label>
            </div>
          </div>
          <div class="socbox" id="socbox">
            <div class="crow">
              <div class="cicon"><ha-icon icon="mdi:battery-sync-outline"></ha-icon></div>
              <div class="ctitle">${t.socLimits}</div>
            </div>
            <div class="socgrid">
              <label class="socin"><span>${t.socMin} <small id="rg-min"></small></span>
                <div class="field"><input type="number" id="in-min" inputmode="numeric" step="1" /><em>%</em></div></label>
              <label class="socin"><span>${t.socMax} <small id="rg-max"></small></span>
                <div class="field"><input type="number" id="in-max" inputmode="numeric" step="1" /><em>%</em></div></label>
            </div>
          </div>
        </div>
      </ha-card>
      <ha-card class="empty" id="empty"><div>${t.notFound}</div></ha-card>
    `;
    const $ = (id) => this.shadowRoot.getElementById(id);
    this._$ = $;

    // Sélecteur de mode
    $("mode").addEventListener("change", (ev) => {
      const mode = ev.target.value;
      const sel = this._state("operating_mode");
      if (REGULATED.includes(mode) && !sel?.attributes?.capteur_reseau) {
        $("hint").textContent = this._t.noSensor;
        $("hint").classList.add("show");
        ev.target.value = sel?.state;
        return;
      }
      this._hass.callService("select", "select_option", { entity_id: this._ents.operating_mode, option: mode });
    });

    // Mode manuel : sens (cases) + puissance (saisie), envoyé à la validation
    this._dir = 1;
    const pw = $("in-pw");
    const sendManual = () => {
      const max = num(this._state("power_setpoint")?.attributes?.max) ?? 3000;
      let w = Math.round((num(pw.value) ?? 0) / 10) * 10;
      w = Math.max(0, Math.min(max, w));
      pw.value = w;
      this._hass.callService("number", "set_value", { entity_id: this._ents.power_setpoint, value: this._dir * w });
    };
    pw.addEventListener("focus", () => (this._editing = "in-pw"));
    pw.addEventListener("blur", () => (this._editing = null));
    pw.addEventListener("keydown", (ev) => ev.key === "Enter" && pw.blur());
    pw.addEventListener("change", sendManual);
    for (const b of this.shadowRoot.querySelectorAll(".dir")) {
      b.addEventListener("click", () => {
        this._dir = Number(b.dataset.dir);
        this._dirPicked = Date.now();
        this._renderDir();
        if ((num(pw.value) ?? 0) > 0) sendManual();
      });
    }
    $("b-rest").addEventListener("click", () => {
      pw.value = 0;
      this._hass.callService("number", "set_value", { entity_id: this._ents.power_setpoint, value: 0 });
    });

    $("strategy").addEventListener("change", (ev) => {
      this._hass.callService("select", "select_option", { entity_id: this._ents.strategy, option: ev.target.value });
    });

    // SOC min / max, limite de soutirage, SOC cible : envoi à la validation (Entrée ou sortie du champ)
    for (const [id, key] of [["in-min", "min_soc"], ["in-max", "soc_set"], ["in-imp", "import_limit"], ["in-tgt", "charge_target_soc"]]) {
      const input = $(id);
      input.addEventListener("focus", () => (this._editing = id));
      input.addEventListener("blur", () => (this._editing = null));
      input.addEventListener("keydown", (ev) => ev.key === "Enter" && input.blur());
      input.addEventListener("change", () => {
        const st = this._state(key);
        let v = Math.round(num(input.value));
        if (v === null || isNaN(v) || !st) return;
        v = Math.max(st.attributes.min ?? 0, Math.min(st.attributes.max ?? 100, v));
        input.value = v;
        this._hass.callService("number", "set_value", { entity_id: this._ents[key], value: v });
      });
    }

    // Ouvertures « plus d'infos »
    const mi = (id, fn) => $(id)?.addEventListener("click", () => this._moreInfo(fn()));
    mi("bat-click", () => this._ents.electric_level);
    mi("state", () => this._ents.operating_mode);
    mi("t-home", () => this._ents.output_home_power);
    mi("t-grid", () => this._state("operating_mode")?.attributes?.capteur_reseau);
    mi("hist", () => this._ents.electric_level);
    mi("s-avail", () => this._ents.electric_level);
    mi("s-cyc", () => this._ents.energy_discharged);
    mi("s-eff", () => this._ents.energy_charged);
    mi("c-temp", () => this._ents.temperature);
    mi("c-status", () => this._ents.operating_mode);

    this._ents = this._resolve();
    if (cfg.show_flow) this._buildFlow();
    this._built = true;
  }

  _buildFlow() {
    const t = this._t;
    const nodes = [
      { id: "grid", pos: POS.grid, color: COLORS.grid, icon: "mdi:transmission-tower", label: t.grid },
      { id: "battery", pos: POS.battery, color: COLORS.battery, icon: "mdi:home-battery", label: t.battery },
      { id: "home", pos: POS.home, color: COLORS.home, icon: "mdi:home", label: "", big: true },
    ];
    if (this._solarEntity())
      nodes.push({ id: "solar", pos: POS.solar, color: COLORS.solar, icon: "mdi:solar-power-variant", label: t.solar });
    this._consumers.forEach((c, i) => {
      const st = this._hass.states[c.entity];
      nodes.push({
        id: `c${i}`, pos: POS.c[i], color: c.color || CONSUMER_COLORS[i],
        icon: c.icon || st?.attributes?.icon || "mdi:flash",
        label: c.name || st?.attributes?.friendly_name || c.entity, entity: c.entity,
      });
    });
    this._nodes = nodes;
    // Recadre le schéma s'il n'y a rien en haut ou en bas
    const hy0 = POS.home[1];
    const y0 = nodes.some((n) => n.pos[1] < hy0) ? -26 : 115;
    const y1 = nodes.some((n) => n.pos[1] > hy0) ? H + 26 : H - 115;
    this._vb = [y0, y1];
    const flow = this._$("flow");
    flow.style.aspectRatio = `${W} / ${y1 - y0}`;
    this._$("flowsvg").setAttribute("viewBox", `0 ${y0} ${W} ${y1 - y0}`);

    const [hx, hy] = POS.home;
    const path = (n) => {
      const [x, y] = n.pos;
      if (y === hy) return `M${x} ${y} L${hx} ${hy}`;
      // Coude arrondi : vertical depuis le nœud, puis horizontal vers la maison
      const dir = y < hy ? 1 : -1, r = 26;
      const midY = hy - dir * 12;
      if (x === hx) return `M${x} ${y} L${hx} ${hy}`;
      const sx = x < hx ? 1 : -1;
      return `M${x} ${y} L${x} ${midY - dir * r} Q${x} ${midY} ${x + sx * r} ${midY} L${hx} ${midY}`;
    };
    const svg = this._$("flowsvg");
    svg.innerHTML = nodes
      .filter((n) => n.id !== "home")
      .map((n) => `<path id="p-${n.id}" d="${path(n)}" class="fl" style="--c:${n.color}"/><g id="d-${n.id}"></g>`)
      .join("");

    this._$("nodes").innerHTML = nodes
      .map((n) => {
        const left = (n.pos[0] / W) * 100, top = ((n.pos[1] - this._vb[0]) / (this._vb[1] - this._vb[0])) * 100;
        return `<div class="node ${n.big ? "big" : ""}" id="n-${n.id}" style="left:${left}%;top:${top}%;--c:${n.color}">
          ${n.label && n.pos[1] < POS.home[1] ? `<div class="nl above">${n.label}</div>` : ""}
          <div class="circle" id="r-${n.id}">
            <ha-icon icon="${n.icon}"></ha-icon>
            <div class="nv" id="nv-${n.id}">—</div>
            ${n.id === "grid" || n.id === "battery" ? `<div class="nv2" id="nv2-${n.id}"></div>` : ""}
          </div>
          ${n.label && n.pos[1] >= POS.home[1] ? `<div class="nl">${n.label}</div>` : ""}
        </div>`;
      })
      .join("");
    this._dotSig = {};
    for (const n of nodes) {
      const el = this._$(`n-${n.id}`);
      el.addEventListener("click", () => {
        const map = {
          grid: this._state("operating_mode")?.attributes?.capteur_reseau,
          battery: this._ents.battery_power,
          home: this._ents.output_home_power,
          solar: this._solarEntity(),
        };
        this._moreInfo(n.entity || map[n.id]);
      });
    }
  }

  /* Points animés le long d'un trait. towardHome = sens nœud → maison */
  _setDots(id, power, towardHome) {
    const g = this._$(`d-${id}`);
    const p = this._$(`p-${id}`);
    if (!g || !p) return;
    const active = power !== null && Math.abs(power) >= 5;
    p.classList.toggle("on", active);
    const speed = active ? Math.max(1.2, 4 - Math.min(Math.abs(power), 3000) / 1000) : 0;
    const sig = active ? `${towardHome}-${speed.toFixed(1)}` : "off";
    if (this._dotSig[id] === sig) return;
    this._dotSig[id] = sig;
    if (!active) {
      g.innerHTML = "";
      return;
    }
    const kp = towardHome ? "0;1" : "1;0";
    const color = this._nodes.find((n) => n.id === id)?.color || "#fff";
    g.innerHTML = [0, 1, 2]
      .map(
        (i) => `<circle r="4.5" fill="${color}"><animateMotion dur="${speed}s" begin="${(-i * speed) / 3}s"
          repeatCount="indefinite" keyPoints="${kp}" keyTimes="0;1" calcMode="linear"><mpath href="#p-${id}"/></animateMotion></circle>`
      )
      .join("");
  }

  _spLabel(w) {
    if (!w) return this._t.standby;
    return `${w > 0 ? this._t.discharging : this._t.charging} · ${fmtW(w)}`;
  }
  _renderDir() {
    this._$("d-charge").classList.toggle("active", this._dir < 0);
    this._$("d-dis").classList.toggle("active", this._dir > 0);
  }

  /* --------------------------------------- mise à jour --------------------------------------- */
  _render() {
    if (!this._hass || !this._config) return;
    if (!this._built) this._build();
    const $ = this._$, t = this._t;
    this._ents = this._resolve();
    if (!this._ents || !this._ents.operating_mode) {
      $("card").style.display = "none";
      $("empty").style.display = "";
      return;
    }
    $("card").style.display = "";
    $("empty").style.display = "none";

    this._device = this._hass.devices?.[this._ents.deviceId];
    $("name").textContent =
      this._config.name || this._device?.name_by_user || prettyModel(this._device?.model || this._device?.name) || "Zendure SolarFlow";

    const sel = this._state("operating_mode");
    const mode = sel?.state;
    const unavailable = !sel || sel.state === "unavailable";
    $("card").classList.toggle("unavailable", unavailable);

    // ---- Batterie
    const soc = this._val("electric_level");
    const bat = this._val("battery_power"); // + = charge
    const minSoc = this._val("min_soc") ?? 0;
    const cap = this._capacity();
    const state = unavailable ? "unavailable" : bat > 5 ? "charging" : bat < -5 ? "discharging" : "standby";
    $("state").className = `pill ${state}`;
    $("state").querySelector("span").textContent = t[state];

    $("soc").textContent = soc === null ? "—" : Math.round(soc);
    const avail = soc === null ? null : Math.max(0, ((soc - minSoc) / 100) * cap);
    $("kwh").textContent = soc === null ? "—" : `${((soc / 100) * cap).toFixed(2)} kWh`;
    $("battxt").textContent = state === "charging" || state === "discharging" ? `${t[state]} · ${fmtW(bat)}` : "";
    $("battxt").className = `flowtxt ${state}`;
    // Liquide : 0 % → y=144, 100 % → y=16 (vague incluse)
    const lvl = soc ?? 0;
    $("liquid").setAttribute("transform", `translate(0 ${144 - (lvl / 100) * 128 - 6})`);
    $("liquid").setAttribute("class", lvl <= Math.max(minSoc, 5) ? "crit" : lvl < 20 ? "low" : "");
    const my = 144 - (minSoc / 100) * 128;
    $("minline").setAttribute("y1", my);
    $("minline").setAttribute("y2", my);
    $("minline").style.display = minSoc > 0 ? "" : "none";
    this.shadowRoot.querySelectorAll(".wave").forEach((w) => w.classList.toggle("still", state === "standby"));

    // ---- Maison / Réseau
    const grid = this._gridPower();
    const solar = this._solarEntity() ? this._watts(this._solarEntity()) : null;
    // Conso maison = réseau + solaire + décharge batterie (− charge)
    const home = grid === null ? this._val("output_home_power") : grid + (solar ?? 0) - (bat ?? 0);
    if ($("v-home")) $("v-home").innerHTML = `${home !== null && Math.abs(home) >= 5 ? `<i class="arr ${home > 0 ? "up" : "down"}"></i>` : ""}${fmtW(home)}`;
    if ($("v-grid")) $("v-grid").innerHTML = grid === null ? "—" : `${Math.abs(grid) >= 5 ? `<i class="arr ${grid > 0 ? "in" : "out"}"></i>` : ""}${fmtW(grid)}`;

    // ---- Historique
    if (this._config.show_history) {
      $("h-now").textContent = soc === null ? "" : `${Math.round(soc)} %`;
      this._loadHistory();
      this._drawHistory();
    }

    // ---- Statistiques
    const eIn = this._val("energy_charged"), eOut = this._val("energy_discharged");
    $("v-avail").innerHTML = avail === null ? "—" : `${avail.toFixed(2)}<small>kWh</small>`;
    $("v-cap").innerHTML = `${cap.toFixed(2)}<small>kWh</small>`;
    const availE = this._val("available_energy");
    if (availE !== null) $("v-avail").innerHTML = `${availE.toFixed(2)}<small>kWh</small>`;
    $("v-cyc").textContent = eOut === null ? "—" : Math.floor(eOut / cap);
    $("v-eff").innerHTML = eIn && eOut && eIn > 0.5 ? `${Math.min(100, Math.round((eOut / eIn) * 100))}<small>%</small>` : "—";
    const temp = this._val("temperature");
    const lang = this._hass?.locale?.language || this._hass?.language || "en";
    $("v-temp").textContent = temp === null ? "—" : `${temp.toLocaleString(lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} °C`;
    $("v-status").textContent = this._fmt(this._state("regulation_state"));
    $("s-cyc").style.display = this._ents.energy_discharged ? "" : "none";
    $("s-eff").style.display = this._ents.energy_charged ? "" : "none";
    $("c-temp").style.display = this._ents.temperature ? "" : "none";
    this._renderMembers();

    // ---- Flux
    if (this._config.show_flow && this._nodes) this._renderFlow({ grid, solar, bat, home, soc });

    // ---- Pilotage
    const select = $("mode");
    const opts = sel?.attributes?.options || MODES;
    const sig = opts.join(",");
    if (this._modeSig !== sig) {
      this._modeSig = sig;
      select.innerHTML = opts.map((m) => `<option value="${m}">${t.modes[m] || m}</option>`).join("");
    }
    if (this.shadowRoot.activeElement !== select) select.value = mode;
    select.disabled = unavailable && !this._isGroup;
    $("mode-sub").textContent = t.modes[mode] || mode || "—";
    // Batterie membre d'un groupe (G4, G11)
    const groupName = sel?.attributes?.group_name;
    const member = mode === "group" && groupName;
    if (member) $("mode-sub").textContent = t.pilotedBy.replace("{g}", groupName);
    $("member-note").classList.remove("show");
    // Stratégie (groupe)
    $("strat-wrap").style.display = $("strat-label").style.display = this._isGroup ? "" : "none";
    if (this._isGroup && this.shadowRoot.activeElement !== $("strategy")) $("strategy").value = this._state("strategy")?.state;
    // Charge réseau (Z1, Z4) ; réglages ignorés sur une batterie membre (G3 bis)
    $("gcbox").style.display = this._ents.import_limit ? "" : "none";
    const ignored = this._state("import_limit")?.attributes?.ignored_by_group;
    $("gc-ignored").textContent = ignored ? t.ignoredBy.replace("{g}", ignored) : "";
    $("gcbox").classList.toggle("ignored", !!ignored);
    $("socbox").style.display = this._ents.min_soc ? "" : "none";
    if (sel?.attributes?.capteur_reseau) $("hint").classList.remove("show");
    for (const [id, key] of [["in-min", "min_soc"], ["in-max", "soc_set"], ["in-imp", "import_limit"], ["in-tgt", "charge_target_soc"]]) {
      const st = this._state(key), input = $(id);
      input.disabled = !st || st.state === "unavailable";
      if (st) {
        input.min = st.attributes.min ?? 0;
        input.max = st.attributes.max ?? 100;
        if ($(id.replace("in-", "rg-"))) $(id.replace("in-", "rg-")).textContent = `(${input.min} – ${input.max} %)`;
        if (this._editing !== id) input.value = num(st.state) === null ? "" : Math.round(num(st.state));
      }
    }
    const sp = this._state("power_setpoint");
    $("manual").classList.toggle("show", mode === "manual");
    if (sp) {
      const w = num(sp.state) ?? 0;
      const max = num(sp.attributes.max) ?? 3000;
      $("in-pw").max = max;
      $("rg-pw").textContent = `(0 – ${max} W)`;
      $("man-sub").textContent = this._spLabel(w);
      // Le sens suit la consigne réelle, sauf juste après un clic sur une case
      if (w !== 0 && Date.now() - (this._dirPicked || 0) > 3000) this._dir = w > 0 ? 1 : -1;
      this._renderDir();
      if (this._editing !== "in-pw") $("in-pw").value = Math.abs(w);
      $("in-pw").disabled = $("b-rest").disabled = sp.state === "unavailable";
    }
  }

  _renderMembers() {
    const box = this._$("members");
    const list = this._isGroup ? this._state("operating_mode")?.attributes?.batteries || [] : [];
    box.style.display = list.length ? "" : "none";
    if (!list.length) return;
    const t = this._t;
    const rows = list.map((b) => {
      const ents = this._memberEnts(b.entry_id) || {};
      const st = (k) => (ents[k] ? this._hass.states[ents[k]] : undefined);
      const soc = num(st("electric_level")?.state);
      const p = num(st("battery_power")?.state);
      const state = b.active ? this._fmt(st("regulation_state")) : t.unavailable;
      const cls = !b.active ? "off" : p > 5 ? "charging" : p < -5 ? "discharging" : "";
      return `<div class="mrow2 ${cls}" data-e="${ents.electric_level || ""}">
        <div class="mname">${prettyModel(b.name) || b.name}</div>
        <div class="mbar"><i style="width:${soc ?? 0}%"></i></div>
        <div class="msoc">${soc === null ? "—" : Math.round(soc) + " %"}</div>
        <div class="mpow">${p === null ? "—" : (p > 5 ? "↓ " : p < -5 ? "↑ " : "") + fmtW(p)}</div>
        <div class="mstate">${state}</div></div>`;
    });
    const html = `<div class="mhead"><span>${t.batteries}</span><b>${t.activeBatteries} : ${this._val("active_batteries") ?? "—"} / ${list.length}</b></div>${rows.join("")}`;
    if (html !== this._membersHtml) {
      this._membersHtml = html;
      box.innerHTML = html;
      box.querySelectorAll(".mrow2").forEach((r) => r.addEventListener("click", () => this._moreInfo(r.dataset.e)));
    }
  }

  _renderFlow({ grid, solar, bat, home, soc }) {
    const $ = this._$;
    // Réseau : ← injection / → soutirage
    $("nv-grid").innerHTML = `<span class="out">← ${fmtS(grid !== null && grid < 0 ? -grid : 0)}</span>`;
    $("nv2-grid").innerHTML = `<span class="in">→ ${fmtS(grid !== null && grid > 0 ? grid : 0)}</span>`;
    this._setDots("grid", grid, grid > 0);

    // Batterie : SOC + ↓ charge / ↑ décharge
    $("nv-battery").textContent = soc === null ? "—" : `${Math.round(soc)} %`;
    $("nv2-battery").innerHTML =
      bat > 5 ? `<span class="in">↓ ${fmtS(bat)}</span>` : bat < -5 ? `<span class="out">↑ ${fmtS(-bat)}</span>` : "0 W";
    this._setDots("battery", bat, bat < 0);

    if (this._$("nv-solar")) {
      $("nv-solar").textContent = fmtS(solar);
      this._setDots("solar", solar, true);
    }

    // Maison + anneau de répartition des sources
    $("nv-home").textContent = fmtS(home);
    const srcGrid = Math.max(grid ?? 0, 0), srcSolar = Math.max(solar ?? 0, 0), srcBat = Math.max(-(bat ?? 0), 0);
    const tot = srcGrid + srcSolar + srcBat;
    const ring = $("r-home");
    if (tot > 5) {
      const a = (srcSolar / tot) * 360, b = a + (srcBat / tot) * 360;
      ring.style.setProperty(
        "--ring",
        `conic-gradient(${COLORS.solar} 0 ${a}deg, ${COLORS.battery} ${a}deg ${b}deg, ${COLORS.grid} ${b}deg 360deg)`
      );
    } else ring.style.setProperty("--ring", `conic-gradient(${COLORS.grid} 0 360deg)`);

    // Appareils
    this._consumers.forEach((c, i) => {
      const w = this._watts(c.entity);
      $(`nv-c${i}`).textContent = fmtS(w);
      this._setDots(`c${i}`, w, false);
    });
  }
}

/* ------------------------------------------ éditeur ------------------------------------------ */
class ZendureSolarflowCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...(config || {}) };
    this._render();
  }
  set hass(hass) {
    this._hass = hass;
    this._render();
  }
  _render() {
    if (!this._hass || !this._config) return;
    const lang = (this._hass.locale?.language || "en").slice(0, 2);
    const t = (I18N[lang] || I18N.en).ed;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.schema = [
        { name: "device_id", selector: { device: { integration: DOMAIN } } },
        { name: "name", selector: { text: {} } },
        { name: "capacity", selector: { number: { min: 0.5, max: 60, step: 0.01, mode: "box", unit_of_measurement: "kWh" } } },
        { name: "consumers", selector: { entity: { domain: "sensor", device_class: "power", multiple: true } } },
        { name: "show_history", selector: { boolean: {} } },
        { name: "show_flow", selector: { boolean: {} } },
      ];
      this._form.computeLabel = (s) => t[s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => {
        const cfg = { ...this._config, ...ev.detail.value };
        for (const k of Object.keys(cfg)) {
          if (cfg[k] === "" || cfg[k] === undefined || cfg[k] === null || (Array.isArray(cfg[k]) && !cfg[k].length)) delete cfg[k];
        }
        if (Array.isArray(cfg.consumers)) cfg.consumers = cfg.consumers.slice(0, 5);
        this._config = cfg;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: cfg }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    const data = { show_history: true, show_flow: true, ...this._config };
    // L'éditeur gère les appareils sous forme de liste d'entités
    if (Array.isArray(data.consumers)) data.consumers = data.consumers.map((c) => (typeof c === "string" ? c : c.entity));
    this._form.data = data;
  }
}

const STYLE = `
  :host {
    --z-green: #2ecc71; --z-orange: #ff9800; --z-red: #ef5350; --z-blue: #4a90d9; --z-teal: #26c6a8;
    --z-muted: var(--secondary-text-color); --z-panel: rgba(127,127,127,.12); --z-line: rgba(127,127,127,.22);
  }
  ha-card {
    padding: 18px; display: flex; flex-direction: column; gap: 14px; overflow: hidden; container-type: inline-size;
    background: linear-gradient(160deg,
      color-mix(in srgb, var(--z-blue) 9%, var(--ha-card-background, var(--card-background-color))) 0%,
      var(--ha-card-background, var(--card-background-color)) 60%);
  }
  ha-card.unavailable { opacity: .55; }
  ha-card.empty { padding: 24px; color: var(--z-muted); text-align: center; background: var(--ha-card-background, var(--card-background-color)); }
  ha-icon { --mdc-icon-size: 18px; }

  /* En-tête */
  .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .title { font-size: 1.15em; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pill { display: flex; align-items: center; gap: 6px; padding: 5px 11px; border-radius: 999px; background: var(--z-panel);
          font-size: .8em; cursor: pointer; flex: none; }
  .pill i { width: 8px; height: 8px; border-radius: 50%; background: var(--z-muted); }
  .pill.charging i { background: var(--z-green); box-shadow: 0 0 8px var(--z-green); }
  .pill.discharging i { background: var(--z-orange); box-shadow: 0 0 8px var(--z-orange); }
  .pill.unavailable i { background: var(--z-red); }

  /* Batterie liquide */
  .hero { display: flex; align-items: center; gap: 22px; }
  .bat { width: 112px; flex: none; cursor: pointer; }
  .bat svg { width: 100%; display: block; overflow: visible; }
  .shell { fill: rgba(127,127,127,.10); stroke: rgba(150,150,150,.55); stroke-width: 3; }
  .cap { fill: rgba(150,150,150,.55); }
  #liquid { transition: transform 1.2s ease; }
  .wave { fill: var(--z-green); }
  .wave.w2 { opacity: .45; animation: wave 6s linear infinite reverse; }
  .wave.w1 { animation: wave 4s linear infinite; }
  .wave.still { animation-duration: 14s; }
  #liquid.low .wave { fill: var(--z-orange); }
  #liquid.crit .wave { fill: var(--z-red); }
  @keyframes wave { from { transform: translateX(0); } to { transform: translateX(-50px); } }
  .shine { fill: rgba(255,255,255,.18); }
  .minline { stroke: var(--z-red); stroke-width: 2; stroke-dasharray: 5 4; }
  .big { min-width: 0; }
  .pct { font-size: 3.4em; font-weight: 800; line-height: 1; letter-spacing: -1px; }
  .pct sup { font-size: .38em; font-weight: 600; margin-left: 3px; vertical-align: top; position: relative; top: .25em; }
  .kwh { color: var(--z-muted); font-weight: 600; margin-top: 6px; }
  .flowtxt { font-size: .85em; font-weight: 600; margin-top: 8px; min-height: 1.2em; }
  .flowtxt.charging { color: var(--z-green); }
  .flowtxt.discharging { color: var(--z-orange); }

  /* Tuiles */
  .tiles2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .tile, .stat, .chip { background: var(--z-panel); border-radius: 14px; cursor: pointer; transition: background .2s; }
  .tile:hover, .stat:hover, .chip:hover { background: rgba(127,127,127,.18); }
  .tile { padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
  .tl { display: flex; align-items: center; gap: 6px; font-size: .8em; color: var(--z-muted); }
  #t-home ha-icon { color: #ec6a9c; }
  #t-grid ha-icon { color: var(--z-blue); }
  .tile b { font-size: 1.15em; display: flex; align-items: center; gap: 4px; }
  .arr { font-style: normal; font-size: .9em; }
  .arr.up::before { content: "↑"; color: #ec6a9c; }
  .arr.down::before { content: "↓"; color: var(--z-green); }
  .arr.in::before { content: "→"; color: var(--z-blue); }
  .arr.out::before { content: "←"; color: var(--z-green); }

  .hist { cursor: pointer; }
  .hrow { display: flex; justify-content: space-between; font-size: .78em; color: var(--z-muted); margin-bottom: 6px; }
  .hrow b { color: var(--primary-text-color); }
  #spark { width: 100%; height: 56px; display: block; border-bottom: 1px solid var(--z-line); }

  .tiles4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
  .stat { padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .stat small { font-size: .66em; font-weight: 700; letter-spacing: .4px; text-transform: uppercase; color: var(--z-muted); }
  .stat b { font-size: 1.1em; white-space: nowrap; }
  .stat b small, .tile b small { font-size: .62em; margin-left: 2px; color: var(--z-muted); text-transform: none; letter-spacing: 0; }
  .chips { display: flex; gap: 8px; flex-wrap: wrap; }
  .chip { display: flex; align-items: center; gap: 6px; padding: 7px 12px; font-size: .8em; color: var(--z-muted); }
  .chip b { color: var(--primary-text-color); }

  /* Sections */
  .sect { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 1.02em; margin-top: 6px;
          padding-top: 14px; border-top: 1px solid var(--z-line); }

  /* Flux */
  .flowbox { border-radius: 18px; padding: 6px; border: 1px solid var(--z-line);
             background: radial-gradient(ellipse at 30% 20%, color-mix(in srgb, var(--z-blue) 16%, transparent), transparent 70%), var(--z-panel); }
  .flow { position: relative; width: 100%; aspect-ratio: ${W} / ${H}; container-type: inline-size; }
  #flowsvg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .fl { fill: none; stroke: var(--c); stroke-opacity: .35; stroke-width: 2; }
  .fl.on { stroke-opacity: .9; }
  .node { position: absolute; transform: translate(-50%, -50%); display: flex; flex-direction: column; align-items: center;
          cursor: pointer; width: 0; }
  .circle { --size: clamp(54px, 18.5cqw, 92px); width: var(--size); height: var(--size); border-radius: 50%; flex: none;
            border: 2.5px solid var(--c); background: var(--ha-card-background, var(--card-background-color));
            display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px; box-sizing: border-box; }
  .node.big .circle { --size: clamp(64px, 23cqw, 112px); border: none; padding: 4px; position: relative;
                      background: var(--ring, var(--z-blue)); }
  .node.big .circle::before { content: ""; position: absolute; inset: 4px; border-radius: 50%;
                              background: var(--ha-card-background, var(--card-background-color)); }
  .node.big .circle > * { position: relative; }
  .circle ha-icon { --mdc-icon-size: clamp(16px, 5.4cqw, 26px); color: var(--c); }
  .node.big .circle ha-icon { color: var(--primary-text-color); --mdc-icon-size: clamp(18px, 5.4cqw, 28px); }
  .nv { font-size: clamp(10px, 3.1cqw, 14px); font-weight: 700; white-space: nowrap; max-width: 86%; overflow: hidden; }
  .nv2 { font-size: clamp(8px, 2.4cqw, 11px); font-weight: 600; white-space: nowrap; max-width: 86%; overflow: hidden; }
  .node.big .nv { font-size: clamp(11px, 3.8cqw, 17px); }
  .nv .out, .nv2 .out { color: #ec6a9c; }
  .nv .in, .nv2 .in { color: var(--z-blue); }
  #n-battery .nv2 .in { color: var(--z-green); }
  #n-battery .nv2 .out { color: #ec6a9c; }
  #n-grid .nv .out { color: var(--z-green); }
  .nl { font-size: clamp(10px, 3cqw, 13px); white-space: nowrap; max-width: 24cqw; overflow: hidden; text-overflow: ellipsis;
        position: absolute; top: calc(50% + var(--lbl, 46px)); }
  .nl.above { top: auto; bottom: calc(50% + var(--lbl, 46px)); }
  .node { --lbl: clamp(32px, 10.4cqw, 52px); }

  /* Pilotage */
  .ctrl { background: var(--z-panel); border: 1px solid var(--z-line); border-radius: 18px; padding: 14px;
          display: flex; flex-direction: column; gap: 12px; }
  .crow { display: flex; align-items: center; gap: 12px; }
  .cicon ha-icon { --mdc-icon-size: 26px; }
  .ctitle { font-weight: 700; }
  .csub { font-size: .82em; color: var(--z-muted); }
  .selwrap { position: relative; }
  select { width: 100%; appearance: none; -webkit-appearance: none; font: inherit; color: var(--primary-text-color);
           background: rgba(127,127,127,.16); border: none; border-radius: 14px; padding: 13px 42px 13px 16px; cursor: pointer; }
  select:focus { outline: 2px solid var(--primary-color); }
  select option { color: #111; }
  .selwrap ha-icon { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); pointer-events: none; --mdc-icon-size: 24px; }
  .socbox { display: flex; flex-direction: column; gap: 10px; padding-top: 12px; border-top: 1px solid var(--z-line); }
  .socgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .socin small { opacity: .75; }
  .socin { display: flex; flex-direction: column; gap: 6px; font-size: .8em; color: var(--z-muted); }
  .field { display: flex; align-items: center; background: rgba(127,127,127,.16); border-radius: 14px; padding: 0 14px; }
  .field:focus-within { outline: 2px solid var(--primary-color); }
  .field input { flex: 1; min-width: 0; background: none; border: none; outline: none; font: inherit; font-size: 1.35em;
                 font-weight: 700; color: var(--primary-text-color); padding: 10px 0; -moz-appearance: textfield; }
  .field input::-webkit-inner-spin-button, .field input::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
  .field em { font-style: normal; color: var(--z-muted); font-size: 1.1em; }
  .slabel { font-size: .8em; color: var(--z-muted); margin-bottom: -4px; }
  .note { display: none; font-size: .82em; color: var(--z-accent, var(--primary-color)); font-weight: 600; }
  .note.show { display: block; }
  .csub.warn { color: var(--z-orange); }
  #gcbox.ignored .field { opacity: .5; }
  #strat-wrap { margin-top: -2px; }
  .members { display: flex; flex-direction: column; gap: 6px; }
  .mhead { display: flex; justify-content: space-between; font-size: .78em; color: var(--z-muted); }
  .mhead b { color: var(--primary-text-color); font-weight: 600; }
  .mrow2 { display: grid; grid-template-columns: minmax(0, 1.6fr) 1fr auto auto; grid-template-rows: auto auto; gap: 2px 10px;
           align-items: center; padding: 10px 12px; border-radius: 14px; background: var(--z-panel); cursor: pointer; }
  .mrow2 .mname { font-weight: 600; font-size: .88em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .mrow2 .mbar { height: 6px; border-radius: 3px; background: rgba(127,127,127,.25); overflow: hidden; }
  .mrow2 .mbar i { display: block; height: 100%; background: var(--z-green); border-radius: 3px; }
  .mrow2 .msoc { font-weight: 700; font-size: .88em; text-align: right; }
  .mrow2 .mpow { font-size: .82em; text-align: right; min-width: 64px; }
  .mrow2 .mstate { grid-column: 1 / -1; font-size: .72em; color: var(--z-muted); }
  .mrow2.charging .mpow { color: var(--z-green); }
  .mrow2.discharging .mpow { color: var(--z-orange); }
  .mrow2.off { opacity: .55; }
  .hint { display: none; font-size: .78em; color: var(--z-orange); }
  .hint.show { display: block; }
  .manual { display: none; flex-direction: column; gap: 10px; padding-top: 12px; border-top: 1px solid var(--z-line); }
  .manual.show { display: flex; }
  .dirgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .dir { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 12px 8px; border-radius: 14px;
         border: 2px solid transparent; background: rgba(127,127,127,.16); color: var(--primary-text-color);
         font: inherit; font-size: .88em; font-weight: 600; cursor: pointer; transition: background .2s, border-color .2s; }
  .dir ha-icon { --mdc-icon-size: 22px; }
  #d-charge.active { border-color: var(--z-green); background: color-mix(in srgb, var(--z-green) 18%, transparent); }
  #d-charge.active ha-icon { color: var(--z-green); }
  #d-dis.active { border-color: var(--z-orange); background: color-mix(in srgb, var(--z-orange) 18%, transparent); }
  #d-dis.active ha-icon { color: var(--z-orange); }
  .rest { align-self: flex-start; display: flex; align-items: center; gap: 6px; background: none; border: none;
          color: var(--z-muted); font: inherit; font-size: .82em; cursor: pointer; padding: 4px 0; }
  .rest:hover { color: var(--primary-text-color); }

  @container (max-width: 400px) {
    .tiles4 { grid-template-columns: repeat(2, 1fr); }
    .bat { width: 92px; } .pct { font-size: 2.8em; }
  }
`;

if (!customElements.get("zendure-solarflow-card")) {
  customElements.define("zendure-solarflow-card", ZendureSolarflowCard);
  customElements.define("zendure-solarflow-card-editor", ZendureSolarflowCardEditor);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "zendure-solarflow-card",
    name: "Zendure SolarFlow",
    description: "Batterie, flux d'énergie et pilotage de la Zendure SolarFlow",
    preview: true,
    documentationURL: "https://github.com/JVmaisGpeur/ha-zendure-solarflow-local",
  });
  console.info(`%c ZENDURE-SOLARFLOW-CARD %c v${CARD_VERSION} `, "background:#2ecc71;color:#fff", "");
}
