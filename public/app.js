const DATA_URL = "./data/dashboard-data.json";
const MONTHS = [
  "Janeiro",
  "Fevereiro",
  "Março",
  "Abril",
  "Maio",
  "Junho",
  "Julho",
  "Agosto",
  "Setembro",
  "Outubro",
  "Novembro",
  "Dezembro",
];

const state = {
  data: null,
  activeTab: "geral",
  filters: {
    year: "",
    month: "",
    function: "",
    chapa: "",
    query: "",
  },
};

const elements = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  loadData();
});

function cacheElements() {
  [
    "sourceStatus",
    "reloadButton",
    "filterYear",
    "filterMonth",
    "filterFunction",
    "filterChapa",
    "searchInput",
    "clearFilters",
    "generalKpis",
    "monthSummary",
    "monthChart",
    "functionChart",
    "employeeList",
    "cidList",
    "doctorList",
    "awayKpis",
    "awayMonthChart",
    "awayEmployeeList",
    "awayCidList",
    "awayTable",
    "recordCount",
    "recordsTable",
    "exportCsv",
    "exportAwayCsv",
    "validationPanel",
    "sourcePanel",
    "cidQualityPanel",
    "toast",
  ].forEach((id) => {
    elements[id] = document.getElementById(id);
  });
}

function bindEvents() {
  elements.reloadButton.addEventListener("click", loadData);
  elements.clearFilters.addEventListener("click", clearFilters);
  elements.exportCsv.addEventListener("click", () => exportCsv(filteredAtestados(), "atestados-filtrados.csv"));
  elements.exportAwayCsv.addEventListener("click", () => exportCsv(filteredAfastados(), "afastados-filtrados.csv"));

  [
    ["filterYear", "year"],
    ["filterMonth", "month"],
    ["filterFunction", "function"],
    ["filterChapa", "chapa"],
  ].forEach(([id, key]) => {
    elements[id].addEventListener("change", (event) => {
      state.filters[key] = event.target.value;
      render();
    });
  });

  elements.searchInput.addEventListener("input", (event) => {
    state.filters.query = event.target.value.trim().toLowerCase();
    render();
  });

  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTab = button.dataset.tab;
      document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab === button));
      document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
      document.getElementById(`panel-${state.activeTab}`).classList.add("active");
      render();
    });
  });
}

async function loadData() {
  try {
    elements.sourceStatus.textContent = "Carregando dados...";
    const response = await fetch(`${DATA_URL}?v=${Date.now()}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    state.data = await response.json();
    populateFilters();
    render();
    showToast("Dados carregados");
  } catch (error) {
    elements.sourceStatus.textContent = "Falha ao carregar dados";
    showToast("Nao foi possivel carregar o JSON");
    console.error(error);
  }
}

function populateFilters() {
  const options = state.data.options;
  setOptions(elements.filterYear, options.anos.map(String), "Todos");
  setOptions(elements.filterMonth, options.meses, "Todos");
  setOptions(elements.filterFunction, options.funcoes, "Todas");
  setOptions(elements.filterChapa, options.chapas, "Todas");
}

function setOptions(select, values, allLabel) {
  const current = select.value;
  select.innerHTML = `<option value="">${allLabel}</option>`;
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  select.value = values.includes(current) ? current : "";
}

function clearFilters() {
  state.filters = { year: "", month: "", function: "", chapa: "", query: "" };
  elements.filterYear.value = "";
  elements.filterMonth.value = "";
  elements.filterFunction.value = "";
  elements.filterChapa.value = "";
  elements.searchInput.value = "";
  render();
}

function render() {
  if (!state.data) {
    return;
  }
  const generated = formatDateTime(state.data.metadata.generatedAt);
  elements.sourceStatus.textContent = `Dados gerados em ${generated}`;

  renderGeneral();
  renderAway();
  renderRecords();
  renderQuality();
}

function filteredAtestados() {
  const records = state.data.records.atestados;
  return records.filter((record) => {
    if (state.filters.year && String(record.ano) !== state.filters.year) return false;
    if (state.filters.month && record.mes !== state.filters.month) return false;
    if (state.filters.function && record.funcao !== state.filters.function) return false;
    if (state.filters.chapa && record.chapa !== state.filters.chapa) return false;
    if (state.filters.query && !recordMatches(record, state.filters.query)) return false;
    return true;
  });
}

function filteredAfastados() {
  const records = state.data.records.afastados;
  return records.filter((record) => {
    if (state.filters.month && record.mes !== state.filters.month) return false;
    if (state.filters.function && record.funcao !== state.filters.function) return false;
    if (state.filters.chapa && record.chapa !== state.filters.chapa) return false;
    if (state.filters.query && !recordMatches(record, state.filters.query)) return false;
    return true;
  });
}

function recordMatches(record, query) {
  return Object.values(record).join(" ").toLowerCase().includes(query);
}

function renderGeneral() {
  const records = filteredAtestados();
  const totals = {
    registros: records.length,
    dias: sum(records, "totalNoMes"),
    atestados: sum(records, "atestados"),
    colaboradores: new Set(records.map((record) => record.nome).filter(Boolean)).size,
    chapas: new Set(records.map((record) => record.chapa).filter(Boolean)).size,
  };

  elements.generalKpis.innerHTML = [
    kpi("Atestados", formatNumber(totals.atestados)),
    kpi("Dias", formatNumber(totals.dias)),
    kpi("Registros", formatNumber(totals.registros)),
    kpi("Colaboradores", formatNumber(totals.colaboradores)),
    kpi("Chapas", formatNumber(totals.chapas)),
  ].join("");

  const byMonth = groupMain(records, "mes", MONTHS);
  const byFunction = groupMain(records, "funcao");
  const topEmployees = groupMain(records, "nome").slice(0, 12);
  const topCid = groupMain(records, "capituloCid").slice(0, 12);
  const topDoctors = countBy(records, "medico").slice(0, 12);

  elements.monthSummary.textContent = `${formatNumber(totals.dias)} dias | ${formatNumber(totals.atestados)} atestados`;
  renderMonthChart(elements.monthChart, byMonth, "dias", "atestados");
  renderBars(elements.functionChart, byFunction, "dias", "dias");
  renderBars(elements.employeeList, topEmployees, "dias", "dias");
  renderBars(elements.cidList, topCid, "dias", "dias");
  renderRanks(elements.doctorList, topDoctors, "atestados");
}

function renderAway() {
  const records = filteredAfastados();
  const totals = {
    registros: records.length,
    dias: sum(records, "total"),
    colaboradores: new Set(records.map((record) => record.colaborador).filter(Boolean)).size,
    chapas: new Set(records.map((record) => record.chapa).filter(Boolean)).size,
    medicos: new Set(records.map((record) => record.medico).filter(Boolean)).size,
  };

  elements.awayKpis.innerHTML = [
    kpi("Dias Afastados", formatNumber(totals.dias)),
    kpi("Registros", formatNumber(totals.registros)),
    kpi("Colaboradores", formatNumber(totals.colaboradores)),
    kpi("Chapas", formatNumber(totals.chapas)),
    kpi("Médicos", formatNumber(totals.medicos)),
  ].join("");

  const byMonth = groupSum(records, "mes", "total", MONTHS);
  const topEmployees = groupSum(records, "colaborador", "total").slice(0, 12);
  const topCid = groupSum(records, "capituloCid", "total").slice(0, 12);
  renderMonthChart(elements.awayMonthChart, byMonth, "valor", "registros");
  renderBars(elements.awayEmployeeList, topEmployees, "valor", "dias");
  renderBars(elements.awayCidList, topCid, "valor", "dias");
  renderAwayTable(records);
}

function renderRecords() {
  const records = filteredAtestados();
  elements.recordCount.textContent = `${formatNumber(records.length)} registros`;
  const visible = records.slice(0, 250);
  elements.recordsTable.innerHTML = visible.map((record) => `
    <tr>
      <td>${escapeHtml(record.chapa)}</td>
      <td>${escapeHtml(record.nome)}</td>
      <td>${escapeHtml(record.funcao)}</td>
      <td>${escapeHtml(record.periodo)}</td>
      <td>${formatDate(record.dataInicial)}</td>
      <td>${formatDate(record.dataFinal)}</td>
      <td>${formatNumber(record.totalNoMes)}</td>
      <td>${record.ano ?? ""}</td>
      <td>${formatNumber(record.atestados)}</td>
      <td>${escapeHtml(record.mes)}</td>
      <td>${escapeHtml(record.medico)}</td>
      <td>${escapeHtml(record.capituloCid)}</td>
      <td>${escapeHtml(record.subcategoriaCid)}</td>
    </tr>
  `).join("");
}

function renderAwayTable(records) {
  elements.awayTable.innerHTML = records.slice(0, 250).map((record) => `
    <tr>
      <td>${escapeHtml(record.colaborador)}</td>
      <td>${escapeHtml(record.chapa)}</td>
      <td>${escapeHtml(record.funcao)}</td>
      <td>${escapeHtml(record.periodo)}</td>
      <td>${formatNumber(record.total)}</td>
      <td>${escapeHtml(record.mes)}</td>
      <td>${escapeHtml(record.medico)}</td>
      <td>${escapeHtml(record.capituloCid)}</td>
      <td>${escapeHtml(record.subcategoriaCid)}</td>
    </tr>
  `).join("");
}

function renderQuality() {
  const validation = state.data.validation.atestados;
  const quality = state.data.validation.qualidadeCid;
  const statusClass = validation.status === "ok" ? "status-ok" : "status-attention";

  elements.validationPanel.innerHTML = [
    qualityRow("Status", `<span class="badge ${statusClass}">${validation.status.toUpperCase()}</span>`),
    qualityRow("Registros", formatNumber(validation.registrosImportados)),
    qualityRow("Dias", `${formatNumber(validation.somaDiasImportada)} / ${formatNumber(validation.somaDiasEsperada)}`),
    qualityRow("Atestados", `${formatNumber(validation.somaAtestadosImportada)} / ${formatNumber(validation.somaAtestadosEsperada)}`),
    qualityRow("Linha total", validation.linhaTotalExcel),
    qualityRow("Campos vazios", Object.keys(validation.camposObrigatoriosVazios).length),
  ].join("");

  elements.sourcePanel.innerHTML = [
    qualityRow("Arquivo", escapeHtml(state.data.metadata.sourceFile)),
    qualityRow("Tabela atestados", `${state.data.sourceTables.atestados.table} (${formatNumber(state.data.sourceTables.atestados.records)})`),
    qualityRow("Tabela afastados", `${state.data.sourceTables.afastados.table} (${formatNumber(state.data.sourceTables.afastados.records)})`),
    qualityRow("Schema", state.data.metadata.schemaVersion),
  ].join("");

  if (!quality.possiveisVariacoesTextoCid.length) {
    elements.cidQualityPanel.innerHTML = qualityRow("Variações encontradas", "0");
    return;
  }

  elements.cidQualityPanel.innerHTML = quality.possiveisVariacoesTextoCid.map((variant) => `
    <div class="quality-row">
      <span>${variant.map(escapeHtml).join("<br>")}</span>
      <span class="rank-value">${variant.length}</span>
    </div>
  `).join("");
}

function kpi(label, value) {
  return `<article class="kpi-card"><strong>${value}</strong><span>${label}</span></article>`;
}

function groupMain(records, key, orderedLabels) {
  const grouped = new Map();
  records.forEach((record) => {
    const label = String(record[key] || "Nao informado");
    const item = grouped.get(label) || { label, registros: 0, dias: 0, atestados: 0 };
    item.registros += 1;
    item.dias += Number(record.totalNoMes || 0);
    item.atestados += Number(record.atestados || 0);
    grouped.set(label, item);
  });
  return sortGrouped([...grouped.values()], orderedLabels, "dias");
}

function groupSum(records, key, valueKey, orderedLabels) {
  const grouped = new Map();
  records.forEach((record) => {
    const label = String(record[key] || "Nao informado");
    const item = grouped.get(label) || { label, registros: 0, valor: 0 };
    item.registros += 1;
    item.valor += Number(record[valueKey] || 0);
    grouped.set(label, item);
  });
  return sortGrouped([...grouped.values()], orderedLabels, "valor");
}

function countBy(records, key) {
  const grouped = new Map();
  records.forEach((record) => {
    const label = String(record[key] || "Nao informado");
    const item = grouped.get(label) || { label, valor: 0 };
    item.valor += 1;
    grouped.set(label, item);
  });
  return [...grouped.values()].sort((a, b) => b.valor - a.valor || a.label.localeCompare(b.label));
}

function sortGrouped(items, orderedLabels, valueKey) {
  if (orderedLabels) {
    const order = new Map(orderedLabels.map((label, index) => [label, index]));
    return items.sort((a, b) => (order.get(a.label) ?? 999) - (order.get(b.label) ?? 999));
  }
  return items.sort((a, b) => b[valueKey] - a[valueKey] || a.label.localeCompare(b.label));
}

function renderMonthChart(container, items, valueKey, secondaryKey) {
  if (!items.length) {
    container.innerHTML = emptyState();
    return;
  }
  const max = Math.max(...items.map((item) => item[valueKey]), 1);
  container.innerHTML = items.map((item) => {
    const height = Math.max(3, (item[valueKey] / max) * 100);
    return `
      <div class="month-column" title="${escapeHtml(item.label)}: ${formatNumber(item[valueKey])}">
        <div class="month-bar-wrap">
          <div class="month-bar" style="height:${height}%"></div>
        </div>
        <strong>${formatNumber(item[valueKey])}</strong>
        <small>${escapeHtml(item.label.slice(0, 3))} · ${formatNumber(item[secondaryKey] || 0)}</small>
      </div>
    `;
  }).join("");
}

function renderBars(container, items, valueKey, suffix) {
  if (!items.length) {
    container.innerHTML = emptyState();
    return;
  }
  const max = Math.max(...items.map((item) => item[valueKey]), 1);
  container.innerHTML = items.map((item) => {
    const width = Math.max(2, (item[valueKey] / max) * 100);
    return `
      <div class="bar-item">
        <div class="bar-label">
          <span title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</span>
          <span>${formatNumber(item[valueKey])} ${suffix}</span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width:${width}%"></div>
        </div>
      </div>
    `;
  }).join("");
}

function renderRanks(container, items, suffix) {
  if (!items.length) {
    container.innerHTML = emptyState();
    return;
  }
  container.innerHTML = items.map((item) => `
    <div class="rank-row">
      <span>${escapeHtml(item.label)}</span>
      <span class="rank-value">${formatNumber(item.valor)} ${suffix}</span>
    </div>
  `).join("");
}

function qualityRow(label, value) {
  return `<div class="quality-row"><span>${label}</span><span class="rank-value">${value}</span></div>`;
}

function emptyState() {
  return `<p class="empty-state">Sem dados para os filtros atuais.</p>`;
}

function sum(records, key) {
  return records.reduce((total, record) => total + Number(record[key] || 0), 0);
}

function formatNumber(value) {
  return new Intl.NumberFormat("pt-BR").format(Number(value || 0));
}

function formatDate(value) {
  if (!value) return "";
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function formatDateTime(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function exportCsv(records, filename) {
  if (!records.length) {
    showToast("Sem dados para exportar");
    return;
  }
  const headers = Object.keys(records[0]).filter((key) => key !== "id");
  const rows = [headers, ...records.map((record) => headers.map((key) => record[key]))];
  const csv = rows.map((row) => row.map(csvCell).join(";")).join("\n");
  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function csvCell(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("show");
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => {
    elements.toast.classList.remove("show");
  }, 1800);
}
