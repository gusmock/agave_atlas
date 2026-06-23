const state = {
  summary: null,
  facets: null,
  worldMap: null,
  keywords: [],
  filters: { q: "", office: "", year: "", status: "", category: "" },
};

let keywordCloudResizeToken = null;

const $ = (selector) => document.querySelector(selector);

function text(value, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function clip(value, length = 260) {
  const str = text(value, "");
  return str.length > length ? `${str.slice(0, length - 1)}...` : str;
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Erro na requisicao");
  return data;
}

function fillSelect(selector, rows) {
  const select = $(selector);
  const first = select.querySelector("option");
  select.innerHTML = "";
  select.append(first);
  rows.forEach((row) => {
    const option = document.createElement("option");
    option.value = row.value;
    option.textContent = `${row.value} (${row.count})`;
    select.append(option);
  });
}

function renderMetrics(summary) {
  $("#metricTotal").textContent = summary.total ?? 0;
  $("#metricPending").textContent = summary.pending ?? 0;
  $("#metricAlive").textContent = summary.alive ?? 0;
  $("#metricYears").textContent =
    summary.first_year && summary.last_year ? `${summary.first_year}-${summary.last_year}` : "-";
}

function renderBars(selector, rows, limit = 12) {
  const root = $(selector);
  root.innerHTML = "";
  const visible = rows.slice(0, limit);
  const max = Math.max(1, ...visible.map((row) => row.count));
  visible.forEach((row) => {
    const item = document.createElement("div");
    item.className = "barRow";
    item.innerHTML = `
      <span class="barLabel" title="${text(row.value)}">${text(row.value)}</span>
      <span class="barTrack"><span class="barFill" style="width:${(row.count / max) * 100}%"></span></span>
      <span class="barCount">${row.count}</span>
    `;
    root.append(item);
  });
}

function renderYears(rows) {
  const root = $("#yearBars");
  root.innerHTML = "";
  const parsed = rows
    .map((row) => ({ year: Number(row.value), count: row.count }))
    .filter((row) => Number.isFinite(row.year))
    .sort((a, b) => a.year - b.year);
  const max = Math.max(1, ...parsed.map((row) => row.count));
  parsed.forEach((row) => {
    const bar = document.createElement("div");
    bar.className = "yearBar";
    bar.style.height = `${18 + (row.count / max) * 110}px`;
    bar.dataset.label = `${row.year}: ${row.count}`;
    root.append(bar);
  });
}

function activateView(viewName) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === viewName);
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id === `view-${viewName}`);
  });
}

function applyFilter(key, value) {
  state.filters[key] = value;
  const input = $(`#${key}`);
  if (input) input.value = value;
  activateView("documents");
  loadDocuments().catch(console.error);
}

function renderWorldMap(mapData) {
  const markers = $("#worldMapMarkers");
  const legend = $("#worldMapLegend");
  markers.innerHTML = "";
  legend.innerHTML = "";
  const points = mapData.points || [];
  if (!points.length) {
    legend.innerHTML = "<span class=\"chip\">Sem localizações disponíveis</span>";
    return;
  }
  points.forEach((point) => {
    const marker = document.createElement("button");
    marker.className = "mapMarker";
    marker.type = "button";
    marker.style.setProperty("--x", `${point.x}%`);
    marker.style.setProperty("--y", `${point.y}%`);
    marker.style.setProperty("--size", `${point.radius}px`);
    marker.title = `${point.office} · ${point.name}: ${point.count} documento(s)`;
    marker.setAttribute(
      "aria-label",
      `Filtrar por ${point.office}, ${point.name}, ${point.count} documentos`
    );
    marker.addEventListener("click", () => applyFilter("office", point.office));
    markers.append(marker);

    const button = document.createElement("button");
    button.className = "mapLegendButton";
    button.type = "button";
    button.textContent = `${point.office} · ${point.name} (${point.count})`;
    button.addEventListener("click", () => applyFilter("office", point.office));
    legend.append(button);
  });
  if (mapData.unlocated) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = `Sem localização: ${mapData.unlocated}`;
    legend.append(chip);
  }
}

function renderKeywordCloud(items) {
  const root = $("#keywordCloud");
  root.innerHTML = "";
  if (!items.length) {
    root.innerHTML = "<span class=\"chip\">Sem palavras-chave disponíveis</span>";
    return;
  }
  const palette = ["#1d5f76", "#2c6e49", "#8a5a14", "#8f3b2f", "#455b73"];
  const counts = items.map((item) => item.count);
  const min = Math.min(...counts);
  const max = Math.max(...counts);
  const stage = document.createElement("div");
  stage.className = "keywordCloudStage";
  root.append(stage);

  const visibleItems = [...items]
    .sort((a, b) => b.count - a.count || a.term.localeCompare(b.term))
    .slice(0, window.innerWidth < 560 ? 24 : 36);

  const stageWidth = Math.max(280, root.clientWidth - 28);
  const stageHeight = Math.max(260, window.innerWidth < 560 ? 280 : 320);
  stage.style.height = `${stageHeight}px`;

  const placed = [];
  const intersects = (candidate) =>
    placed.some(
      (rect) =>
        !(
          candidate.x + candidate.width < rect.x ||
          candidate.x > rect.x + rect.width ||
          candidate.y + candidate.height < rect.y ||
          candidate.y > rect.y + rect.height
        )
    );

  visibleItems.forEach((item, index) => {
    const weight = max === min ? 0.5 : (item.count - min) / (max - min);
    const button = document.createElement("button");
    button.className = "keywordButton keywordCloudWord";
    button.type = "button";
    button.textContent = item.term;
    button.title = `${item.term}: ${item.count}`;
    button.style.setProperty("--font-size", `${13 + weight * 18}px`);
    button.style.setProperty("--word-color", palette[index % palette.length]);
    button.style.setProperty("--word-rotate", `${index % 5 === 0 ? -8 : index % 4 === 0 ? 8 : 0}deg`);
    button.addEventListener("click", () => applyFilter("q", item.term));
    stage.append(button);

    const wordWidth = Math.ceil(button.offsetWidth);
    const wordHeight = Math.ceil(button.offsetHeight);
    let chosen = null;

    for (let step = 0; step < 1400; step += 1) {
      const angle = step * 0.42;
      const radius = 3.4 * Math.sqrt(step);
      const x = stageWidth / 2 - wordWidth / 2 + Math.cos(angle) * radius * 7.2;
      const y = stageHeight / 2 - wordHeight / 2 + Math.sin(angle) * radius * 5.1;
      const candidate = {
        x: Math.round(x),
        y: Math.round(y),
        width: wordWidth + 2,
        height: wordHeight + 1,
      };
      if (
        candidate.x < 0 ||
        candidate.y < 0 ||
        candidate.x + candidate.width > stageWidth ||
        candidate.y + candidate.height > stageHeight ||
        intersects(candidate)
      ) {
        continue;
      }
      chosen = candidate;
      break;
    }

    if (!chosen) {
      button.remove();
      return;
    }
    placed.push(chosen);
    button.style.left = `${chosen.x}px`;
    button.style.top = `${chosen.y}px`;
  });
}

function queueKeywordCloudRender() {
  window.clearTimeout(keywordCloudResizeToken);
  keywordCloudResizeToken = window.setTimeout(() => {
    if (state.keywords?.length) renderKeywordCloud(state.keywords);
  }, 120);
}

function renderInsights(summary) {
  const topCategory = summary.categories?.[0]?.value || "rotas tecnologicas";
  const topOffice = summary.offices?.[0]?.value || "diferentes escritorios";
  const panel = $("#insightPanel");
  panel.innerHTML = `
    <p>A base importada concentra ${summary.total} documentos relevantes, com registros entre ${text(summary.first_year)} e ${text(summary.last_year)}.</p>
    <p>O eixo mais frequente na classificacao analitica e <strong>${topCategory}</strong>, indicando onde a prospeccao encontrou maior densidade de evidencias tecnicas.</p>
    <p>O escritorio com maior volume e <strong>${topOffice}</strong>. Use os filtros para comparar titulares, familias vivas e documentos pendentes por rota tecnologica.</p>
  `;
}

function renderDocuments(items) {
  $("#resultCount").textContent = `${items.length} registros`;
  const root = $("#documents");
  root.innerHTML = "";
  if (!items.length) {
    root.innerHTML = "<p>Nenhum documento encontrado.</p>";
    return;
  }
  items.forEach((doc) => {
    const card = document.createElement("article");
    card.className = "documentCard";
    card.innerHTML = `
      <div class="documentMeta">
        <span class="chip">${text(doc.office, "sem escritorio")}</span>
        <span class="chip">${text(doc.application_year, "sem ano")}</span>
        <span class="chip">${text(doc.family_legal_status, "sem status")}</span>
        <span class="chip">${text(doc.family_legal_state, "sem estado")}</span>
      </div>
      <h3>${text(doc.title, doc.primary_identifier || "Documento sem titulo")}</h3>
      <p>${clip(doc.abstract || doc.assignees || doc.publication_numbers)}</p>
      <footer>
        <span class="chip">${text(doc.primary_identifier, "sem identificador")}</span>
        <button class="linkButton" type="button" data-id="${doc.id}">Abrir</button>
      </footer>
    `;
    card.querySelector("button").addEventListener("click", () => openDetail(doc.id));
    root.append(card);
  });
}

function categoryChips(categories) {
  if (!categories?.length) return "";
  const grouped = categories.slice(0, 18).map((cat) => {
    const label = cat.subgroup_name || cat.group_name || cat.field_label;
    const value = cat.flag_value ? cat.field_label : cat.value_text;
    return `<span class="chip" title="${text(cat.value_text)}">${text(label)}${value && value !== label ? `: ${clip(value, 46)}` : ""}</span>`;
  });
  return `<div class="chips">${grouped.join("")}</div>`;
}

async function openDetail(id) {
  const doc = await api(`/api/documents/${id}`);
  const download = doc.stored_filename
    ? `<a href="/api/documents/${doc.id}/download">Arquivo salvo</a>`
    : "";
  $("#detailContent").innerHTML = `
    <h2>${text(doc.title, doc.primary_identifier || "Documento")}</h2>
    <div class="documentMeta">
      <span class="chip">${text(doc.document_type)}</span>
      <span class="chip">${text(doc.primary_identifier)}</span>
      <span class="chip">${text(doc.office)}</span>
      <span class="chip">${text(doc.application_year)}</span>
      <span class="chip">${text(doc.family_legal_status)}</span>
      ${download}
    </div>
    ${categoryChips(doc.categories)}
    <div class="detailGrid">
      <section class="detailBlock"><h3>Resumo</h3><p>${text(doc.abstract, "Sem resumo.")}</p></section>
      <section class="detailBlock"><h3>Titulares e inventores</h3><p>${text(doc.assignees)}\n${text(doc.inventors)}</p></section>
      <section class="detailBlock"><h3>Classificacao</h3><p>CPC: ${text(doc.cpc)}\nIPC: ${text(doc.ipc)}</p></section>
      <section class="detailBlock"><h3>Datas e publicacoes</h3><p>${text(doc.publication_numbers)}\n${text(doc.publication_dates)}\nPrioridade: ${text(doc.priority_date)}</p></section>
    </div>
    <section class="detailBlock"><h3>Reivindicacoes</h3><p>${text(doc.claims, "Sem texto de reivindicacoes.")}</p></section>
    <section class="detailBlock"><h3>Descricao da invencao</h3><p>${text(doc.invention_description, "Sem descricao.")}</p></section>
  `;
  $("#detailDialog").showModal();
}

async function loadSummary() {
  state.summary = await api("/api/summary");
  state.facets = await api("/api/facets");
  state.worldMap = await api("/api/world-map");
  state.keywords = (await api("/api/keywords?limit=50")).items || [];
  renderMetrics(state.summary);
  renderWorldMap(state.worldMap);
  renderKeywordCloud(state.keywords);
  renderBars("#categoryBars", state.summary.categories || [], 14);
  renderBars("#officeBars", state.summary.offices || [], 12);
  renderBars("#assigneeBars", state.summary.assignees || [], 12);
  renderYears(state.summary.years || []);
  renderInsights(state.summary);
  fillSelect("#office", state.facets.offices || []);
  fillSelect("#year", state.facets.years || []);
  fillSelect("#status", state.facets.statuses || []);
  fillSelect("#category", state.facets.categories || []);
}

async function loadDocuments() {
  const params = new URLSearchParams();
  Object.entries(state.filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const data = await api(`/api/documents?${params.toString()}`);
  renderDocuments(data.items || []);
}

function bindFilters() {
  ["q", "office", "year", "status", "category"].forEach((id) => {
    const el = $(`#${id}`);
    el.addEventListener("input", () => {
      state.filters[id] = el.value;
      loadDocuments().catch(console.error);
    });
  });
  $("#clearFilters").addEventListener("click", () => {
    Object.keys(state.filters).forEach((key) => {
      state.filters[key] = "";
      $(`#${key}`).value = "";
    });
    loadDocuments().catch(console.error);
  });
}

function bindTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      activateView(button.dataset.view);
    });
  });
}

function updateSession(me) {
  $("#sessionLabel").textContent = me.username || "Visitante";
  $("#logoutButton").classList.toggle("hidden", !me.logged_in);
  $("#loginBox").classList.toggle("hidden", me.logged_in);
  $("#uploadBox").classList.toggle("hidden", !me.logged_in);
}

function bindAuth() {
  $("#loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const data = await api("/api/login", { method: "POST", body: form });
      updateSession({ logged_in: true, username: data.username });
    } catch (error) {
      alert(error.message);
    }
  });
  $("#logoutButton").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST" });
    updateSession({ logged_in: false });
  });
}

function bindUploads() {
  $("#uploadForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("#uploadStatus").textContent = "Processando documento...";
    try {
      const data = await api("/api/upload", {
        method: "POST",
        body: new FormData(event.currentTarget),
      });
      $("#uploadStatus").textContent = `Documento salvo: ${data.stored_filename}`;
      await loadSummary();
      await loadDocuments();
    } catch (error) {
      $("#uploadStatus").textContent = error.message;
    }
  });
  $("#spreadsheetForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("#uploadStatus").textContent = "Importando planilha...";
    try {
      const data = await api("/api/import-spreadsheet", {
        method: "POST",
        body: new FormData(event.currentTarget),
      });
      $("#uploadStatus").textContent = `${data.result.rows_imported} linhas importadas.`;
      await loadSummary();
      await loadDocuments();
    } catch (error) {
      $("#uploadStatus").textContent = error.message;
    }
  });
}

async function init() {
  bindTabs();
  bindFilters();
  bindAuth();
  bindUploads();
  window.addEventListener("resize", queueKeywordCloudRender);
  $("#closeDialog").addEventListener("click", () => $("#detailDialog").close());
  updateSession(await api("/api/me"));
  await loadSummary();
  await loadDocuments();
}

init().catch((error) => {
  console.error(error);
  document.body.insertAdjacentHTML("beforeend", `<p class="fatal">${error.message}</p>`);
});
