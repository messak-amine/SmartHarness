// Presentation only: no MQTT publication, database writes or event subscriptions.
export default {
  data() {
    return { filter: 'all', ecuFilter: 'all', typeFilter: 'all', section: 'overview', routeReady: false, collapsed: false, hovered: null, tooltip: null, navTooltipStyle: {}, activity: {}, navigation: [
      { id: 'overview', icon: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z', label: 'Vue d’ensemble' },
      { id: 'circuits', icon: 'M5 3v18 M19 3v18 M2 8h6v8H2z M16 6h6v8h-6z M8 12h8', label: 'Circuits' },
      { id: 'analytics', icon: 'M3 3v18h18 M7 16v-5 M12 16V6 M17 16v-8', label: 'Analyses' },
      { id: 'history', icon: 'M5 4h14v17H5z M9 2h6v4H9z M8 10h8 M8 14h8 M8 18h4', label: 'Historique' }
    ] };
  },
  computed: {
    currentView() { return this.navigation.find(item => item.id === this.section).label; },
    ecuCounts() {
      return ['A', 'B'].map(ecu => ({ ecu, count: this.data.history.filter(row => row.ecu === ecu).length }));
    },
    data() { return this.msg.payload; },
    summary() {
      return this.data.circuits.reduce((counts, c) => {
        if (c.status === 'FAULT' || c.status === 'INTERMITTENT') counts.fault++;
        else if (c.status === 'RECOVERED') counts.recovered++;
        else counts.unknown++;
        return counts;
      }, { fault: 0, recovered: 0, unknown: 0 });
    },
    gatewayLabel() { return { online: 'En ligne', offline: 'Hors ligne', unknown: 'Inconnu' }[this.data.gateway] || 'Inconnu'; },
    lastReception() { return this.data.history[0]?.received_at || null; },
    recent() { return this.data.history.slice(0, 4); },
    hasFilters() {
      return [this.filter, this.ecuFilter, this.typeFilter].some(value => value !== 'all');
    },
    selectedCircuit() { return this.data.circuits.find(c => String(c.circuit) === this.filter) || null; },
    rows() {
      return this.data.history.filter(r => (this.filter === 'all' || String(r.circuit) === this.filter)
        && (this.ecuFilter === 'all' || r.ecu === this.ecuFilter)
        && (this.typeFilter === 'all' || String(r.fault_code) === this.typeFilter));
    },
    circuitCounts() {
      const counts = this.data.circuits.map(c => ({ circuit: c.circuit, name: c.name,
        count: this.data.history.filter(r => r.circuit === c.circuit).length }));
      const max = Math.max(1, ...counts.map(c => c.count));
      return counts.map(c => ({ ...c, percent: c.count / max * 100 }));
    },
    typeCounts() {
      return [{ code: 1, label: 'Déconnexions', tone: 'bad' },
        { code: 0, label: 'Résolutions', tone: 'good' },
        { code: 2, label: 'Intermittences', tone: 'warning' }]
        .map(t => ({ ...t, count: this.data.history.filter(r => r.fault_code === t.code).length }));
    },
    donutBackground() {
      if (!this.data.history.length) return 'var(--border)';
      const fault = this.typeCounts[0].count / this.data.history.length * 100;
      const recovery = fault + this.typeCounts[1].count / this.data.history.length * 100;
      return `conic-gradient(var(--red) 0% ${fault}%, var(--green) ${fault}% ${recovery}%, var(--amber) ${recovery}% 100%)`;
    }
  },
  watch: {
    $route() { this.readRoute(); },
    filter() { this.saveFilters(); },
    ecuFilter() { this.saveFilters(); },
    typeFilter() { this.saveFilters(); },
    msg(next, previous) {
      this.markNewReceptions(next?.payload?.history, previous?.payload?.history);
    }
  },
  mounted() { this.readRoute(); },
  methods: {
    showNavTooltip(event, id) {
      const rect = event.currentTarget.getBoundingClientRect();
      this.navTooltipStyle = { left: `${rect.right + 10}px`, top: `${rect.top + rect.height / 2}px` };
      this.tooltip = id;
    },
    // Reuse FlowFuse's Vue Router. Namespaced query parameters leave its page
    // path and socket subscription intact. Vue disposes these watchers itself.
    routeValues(query) {
      return {
        section: this.navigation.some(item => item.id === query.shView) ? query.shView : 'overview',
        filter: ['1', '2', '3', '4'].includes(query.shCircuit) ? query.shCircuit : 'all',
        ecuFilter: ['A', 'B'].includes(query.shEcu) ? query.shEcu : 'all',
        typeFilter: ['0', '1', '2'].includes(query.shType) ? query.shType : 'all'
      };
    },
    readRoute() {
      const values = this.routeValues(this.$route.query);
      const changed = this.section !== values.section;
      Object.assign(this, values);
      this.routeReady = true;
      this.tooltip = null;
      this.hovered = null;
      if (changed) this.resetViewPosition();
    },
    routeQuery(section) {
      const query = { ...this.$route.query, shView: section };
      for (const [key, value] of [['shCircuit', this.filter], ['shEcu', this.ecuFilter], ['shType', this.typeFilter]]) {
        if (value === 'all') delete query[key];
        else query[key] = value;
      }
      return query;
    },
    saveFilters() {
      if (!this.routeReady) return;
      const query = this.routeQuery(this.section);
      if (JSON.stringify(query) !== JSON.stringify(this.$route.query)) {
        this.$router.replace({ path: this.$route.path, query, hash: this.$route.hash });
      }
    },
    resetViewPosition() {
      this.$nextTick(() => {
        this.$refs.viewTitle?.focus({ preventScroll: true });
        this.$el.scrollIntoView({ behavior: 'instant', block: 'start' });
      });
    },
    // Use SQLite reception IDs, including repeated ECU sequences. Initial
    // archives and unchanged snapshots must never restart the visual feedback.
    markNewReceptions(next, previous) {
      if (!previous || !next) return;
      const lastId = previous[0]?.event_id || 0;
      for (const circuit of this.data.circuits) {
        const latest = next.find(row => row.circuit === circuit.circuit);
        if (circuit.last && latest && latest.event_id > lastId) {
          this.activity[circuit.circuit] = latest.event_id;
        }
      }
    },
    number(value) { return Number(value).toLocaleString('fr-FR'); },
    time(value) { return value ? value.replace('T', ' ').replace('Z', '') : 'Aucune réception'; },
    label(value) { return { UNKNOWN: 'INCONNU', FAULT: 'PANNE · déconnexion', INTERMITTENT: 'PANNE · intermittence', RECOVERED: 'RÉSOLUTION REÇUE' }[value]; },
    faultLabel(code) { return { 0: 'Résolution reçue', 1: 'Déconnexion', 2: 'Intermittence (code 2)' }[code]; },
    tone(c) { return c.status === 'RECOVERED' ? 'recovered' : ['FAULT', 'INTERMITTENT'].includes(c.status) ? 'fault' : 'unknown'; },
    circuitName(id) { return this.data.circuits.find(c => c.circuit === id)?.name || `Circuit ${id}`; },
    markerStyle(id) {
      const positions = { 1: [22, 20], 2: [22, 80], 3: [80, 50], 4: [52, 40] };
      return { left: positions[id][0] + '%', top: positions[id][1] + '%' };
    },
    selectCircuit(id) { this.filter = String(id); this.ecuFilter = 'all'; this.typeFilter = 'all'; },
    openCircuit(id) { this.selectCircuit(id); this.goTo('circuits'); },
    inspectCircuit(id) { this.selectCircuit(id); this.goTo('history'); },
    highlighted(c) { return this.filter === String(c.circuit); },
    inspectType(code) {
      this.typeFilter = String(code);
      this.goTo('history');
    },
    resetFilters() { this.filter = this.ecuFilter = this.typeFilter = 'all'; },
    goTo(section) {
      // Apply the destination before filter watchers run in the next Vue tick.
      this.section = section;
      this.routeReady = false;
      this.tooltip = null;
      this.hovered = null;
      this.$router.push({ path: this.$route.path, query: this.routeQuery(section), hash: this.$route.hash })
        .then(() => this.readRoute());
      this.resetViewPosition();
    }
  }
};
