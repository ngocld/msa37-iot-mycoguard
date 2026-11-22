/* MycoGuard dashboard: hỏi /api/state mỗi 2 giây, vẽ lại phần thay đổi, gửi lệnh khi người vận hành bấm. */
(function () {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const LEVEL_CLASS = ["pill-ok", "pill-warn", "pill-bad"];
  const LEVEL_TEXT = ["Ổn định", "Chú ý", "Nguy hiểm"];
  const STATE_TEXT = { OPEN: "Đang mở", ACKED: "Đã nhận", HANDLED: "Đã xử lý", REOPEN: "Chưa hiệu quả", RESOLVED: "Đã khắc phục" };
  const STATE_CLASS = { OPEN: "pill-bad", ACKED: "pill-warn", HANDLED: "pill-ok", REOPEN: "pill-bad", RESOLVED: "pill-off" };
  const METRIC = {
    temp: { unit: "°C", color: "--c-temp", digits: 1 },
    humidity: { unit: "%", color: "--c-humidity", digits: 1 },
    light: { unit: "lux", color: "--c-light", digits: 0 },
  };

  const ui = {
    metric: "temp", range: "1h", page: 1, pages: 1, date: "",
    profiles: [], activeId: null, editId: null,
    alertSig: null, fetchedAt: 0, last: null, sliderBusy: false, openForms: {},
    simBuilt: false, busy: false,
  };
  const chart = new MiniChart($("#chart"));

  // ============================================================
  //  Tiện ích
  // ============================================================
  async function api(path, opts = {}) {
    const init = { method: opts.method || "GET", headers: {} };
    if (opts.json !== undefined) {
      init.method = opts.method || "POST";
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.json);
    }
    const res = await fetch(path, init);
    let data = null;
    try { data = await res.json(); } catch (e) { /* không phải JSON */ }
    if (!res.ok || (data && data.ok === false)) throw new Error((data && data.error) || `Lỗi máy chủ ${res.status}`);
    return data;
  }

  let toastTimer = null;
  function toast(msg, isError) {
    const el = $("#toast");
    el.textContent = msg;
    el.className = "toast" + (isError ? " err" : "");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 5000 : 3000);
  }

  function fmtNum(v, digits) {
    return v === null || v === undefined ? "—" : Number(v).toFixed(digits);
  }

  function fmtDur(s) {
    if (s === null || s === undefined || isNaN(s)) return "—";
    s = Math.max(0, Math.round(s));
    if (s < 60) return `${s} giây`;
    if (s < 3600) return `${Math.floor(s / 60)} phút ${s % 60} giây`;
    return `${Math.floor(s / 3600)} giờ ${Math.floor((s % 3600) / 60)} phút`;
  }

  function fmtClock(s) {
    s = Math.max(0, Math.round(s));
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }

  function parseTs(text) {
    return text ? new Date(text.replace(" ", "T")) : null;
  }

  function diffS(a, b) {
    const x = parseTs(a), y = parseTs(b);
    return x && y ? (y - x) / 1000 : null;
  }

  function shortTs(text) {
    const d = parseTs(text);
    if (!d) return "—";
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())} ${p(d.getDate())}/${p(d.getMonth() + 1)}`;
  }

  function storageGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function storageSet(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* trình duyệt chặn lưu trữ */ }
  }

  const operatorInput = $("#operatorInput");
  operatorInput.value = storageGet("mg.operator") || "";
  operatorInput.addEventListener("change", () => storageSet("mg.operator", operatorInput.value.trim()));
  const operator = () => operatorInput.value.trim() || "Người vận hành";

  // ============================================================
  //  Trạng thái tổng
  // ============================================================
  async function refreshState() {
    if (ui.busy) return;
    ui.busy = true;
    try {
      const s = await api("/api/state");
      ui.last = s;
      ui.fetchedAt = Date.now();
      renderState(s);
    } catch (e) {
      setOverall(-1, "Mất kết nối tới gateway");
    } finally {
      ui.busy = false;
    }
  }

  function renderState(s) {
    $("#clock").textContent = s.now;
    setOverall(s.status, s.online ? null : (s.reading ? "Mất tín hiệu Arduino" : "Chờ dữ liệu Arduino"));
    renderLinkChip(s.link);
    renderKpis(s);
    renderProfileBar(s);
    renderAlerts(s.alerts);
    renderDevice(s.device);
    renderLink(s.link, s.tm1637);
    if (s.sim) renderSim(s.sim);
  }

  function setOverall(status, text) {
    const el = $("#overall");
    el.className = "pill " + (status >= 0 ? LEVEL_CLASS[status] : "pill-off");
    el.textContent = text || LEVEL_TEXT[status];
    document.title = `${status === 2 ? "⚠ " : ""}MycoGuard · ${el.textContent}`;
  }

  function renderLinkChip(link) {
    const el = $("#linkChip");
    if (!link.active) { el.textContent = "Chưa có kênh truyền"; return; }
    const l = link.links.find((x) => x.name === link.active);
    const lat = link.latency_ms !== null ? ` · ${link.latency_ms} ms` : "";
    el.textContent = `${link.active} · mất gói ${l ? l.loss_pct : 0}%${lat}`;
  }

  function renderKpis(s) {
    for (const key of ["temp", "humidity", "light"]) {
      const card = $(`#kpi-${key}`);
      const m = s.metrics && s.metrics[key];
      const meta = METRIC[key];
      const pill = card.querySelector("[data-role=pill]");
      card.querySelector("[data-role=value]").textContent = m && m.value !== null ? fmtNum(m.value, meta.digits) : "—";
      card.querySelector("[data-role=range]").textContent = m ? `Ngưỡng ${m.min}–${m.max} ${meta.unit}` : "Ngưỡng —";
      card.querySelector("[data-role=note]").textContent = m ? m.note : "";
      const inactive = key === "light" && m && !m.active;
      if (!s.online || !m) {
        pill.className = "pill pill-off"; pill.textContent = "Không có dữ liệu"; card.className = "kpi";
      } else if (inactive) {
        pill.className = "pill pill-off"; pill.textContent = "Ngoài giờ sáng"; card.className = "kpi";
      } else {
        pill.className = "pill " + LEVEL_CLASS[m.level]; pill.textContent = LEVEL_TEXT[m.level];
        card.className = `kpi lvl-${m.level}`;
      }
      // Thanh vị trí: giữa thanh là dải ngưỡng, hai bên là vùng lệch
      const bar = card.querySelector("[data-role=bar]");
      if (m && m.value !== null) {
        const span = m.max - m.min;
        const pos = (m.value - (m.min - span / 2)) / (span * 2);
        bar.style.width = `${Math.max(2, Math.min(100, pos * 100))}%`;
        bar.style.background = `var(${m.level === 2 ? "--bad" : m.level === 1 ? "--warn" : "--ok"})`;
      } else {
        bar.style.width = "0";
      }
    }
    const score = s.grow_score;
    $("#scoreValue").textContent = score === null ? "--" : score;
    $("#scoreBar").style.width = `${score || 0}%`;
    $("#scoreBar").style.background = `var(${score >= 85 ? "--ok" : score >= 60 ? "--warn" : "--bad"})`;
    $("#scoreNote").textContent = score === null ? "Chưa có dữ liệu" :
      score >= 85 ? "Rất phù hợp cho nấm phát triển" : score >= 60 ? "Tạm ổn, nên điều chỉnh" : "Cần xử lý ngay";
  }

  function renderProfileBar(s) {
    const p = s.profile;
    if (p.id !== ui.activeId) {
      ui.activeId = p.id;
      loadProfiles();
    }
    const hours = p.light_on && p.light_off ? `, chiếu sáng ${p.light_on}–${p.light_off}` : "";
    $("#profileInfo").textContent = `${p.t_min}–${p.t_max} °C · ${p.h_min}–${p.h_max} % · ${p.lux_min}–${p.lux_max} lux${hours}`;
    $("#nextVent").textContent = s.next_vent ? `Nhắc thông gió lúc ${s.next_vent}` : "";
  }

  // ============================================================
  //  Việc cần làm
  // ============================================================
  function alertCard(a) {
    const meta = METRIC[a.group];
    const valueText = a.value !== null && meta ? `${fmtNum(a.value, meta.digits)} ${meta.unit}` : null;
    const level = a.group === "vent"
      ? `<span class="pill pill-off">Nhắc lịch</span>`
      : `<span class="pill ${LEVEL_CLASS[a.level]}">${LEVEL_TEXT[a.level]}</span>`;
    const metaLine = [valueText && `Giá trị lúc báo: ${valueText}`, `Trạng thái: ${STATE_TEXT[a.state]}`]
      .filter(Boolean).join(" · ");

    let actions = "";
    if (a.state === "HANDLED") {
      actions = `<span class="a-progress">Đã xử lý, đang theo dõi kết quả · còn <span data-verify="${a.verify_left_s || 0}">${fmtClock(a.verify_left_s || 0)}</span></span>`;
    } else {
      if (a.state === "REOPEN") actions += `<span class="a-progress reopen">Đã xử lý nhưng chưa về ngưỡng</span>`;
      if (a.state === "OPEN" || a.state === "REOPEN") actions += `<button class="btn btn-small" data-ack="${a.id}">Đã nhận</button>`;
      actions += `<button class="btn btn-small btn-primary" data-handle="${a.id}">Đã xử lý…</button>`;
    }

    const options = window.MG.actions.map((x) =>
      `<option${x === a.default_action ? " selected" : ""}>${esc(x)}</option>`).join("");
    return `
      <article class="alert lvl-${a.level} grp-${esc(a.group)} state-${esc(a.state)}" data-id="${a.id}">
        <div class="stripe"></div>
        <div class="a-body">
          <div class="a-head">${level}<b>${esc(a.message)}</b>
            <span class="a-age">mở <span data-age="${a.age_s}">${fmtDur(a.age_s)}</span> trước</span></div>
          <div class="a-meta">${esc(metaLine)}</div>
          <div class="a-tip">${esc(a.suggestion)}</div>
          <div class="a-actions">${actions}</div>
          <form class="handle-form" data-form="${a.id}" hidden>
            <label>Việc đã làm<select name="action">${options}</select></label>
            <label>Ghi chú<input name="note" maxlength="200" placeholder="Không bắt buộc"></label>
            <div class="row">
              <button class="btn btn-primary" type="submit">Lưu</button>
              <button class="btn" type="button" data-cancel="${a.id}">Hủy</button>
            </div>
          </form>
        </div>
      </article>`;
  }

  function renderAlerts(alerts) {
    $("#todoCount").textContent = alerts.length ? `${alerts.length} việc` : "";
    const sig = alerts.map((a) => `${a.id}:${a.state}:${a.level}`).join(",");
    if (sig !== ui.alertSig) {
      ui.alertSig = sig;
      // Giữ nguyên form đang nhập dở khi danh sách được vẽ lại
      for (const form of document.querySelectorAll(".handle-form:not([hidden])")) {
        ui.openForms[form.dataset.form] = { action: form.elements.action.value, note: form.elements.note.value };
      }
      const list = $("#alertList");
      list.innerHTML = alerts.length ? alerts.map(alertCard).join("")
        : `<div class="empty">Không có việc cần làm. Nhà nấm đang trong ngưỡng của hồ sơ.</div>`;
      for (const [id, saved] of Object.entries(ui.openForms)) {
        const form = list.querySelector(`[data-form="${id}"]`);
        if (!form) { delete ui.openForms[id]; continue; }
        form.hidden = false;
        form.elements.action.value = saved.action;
        form.elements.note.value = saved.note;
      }
      if (ui.last) loadLog();
    } else {
      for (const a of alerts) {
        const age = document.querySelector(`[data-id="${a.id}"] [data-age]`);
        if (age) age.dataset.age = a.age_s;
        const v = document.querySelector(`[data-id="${a.id}"] [data-verify]`);
        if (v) v.dataset.verify = a.verify_left_s || 0;
      }
    }
  }

  function tickClocks() {
    const elapsed = (Date.now() - ui.fetchedAt) / 1000;
    for (const el of document.querySelectorAll("[data-age]")) el.textContent = fmtDur(+el.dataset.age + elapsed);
    for (const el of document.querySelectorAll("[data-verify]")) el.textContent = fmtClock(+el.dataset.verify - elapsed);
  }

  $("#alertList").addEventListener("click", async (e) => {
    const ack = e.target.closest("[data-ack]");
    const handle = e.target.closest("[data-handle]");
    const cancel = e.target.closest("[data-cancel]");
    if (ack) {
      ack.disabled = true;
      try {
        const r = await api(`/api/alerts/${ack.dataset.ack}/ack`, { json: { operator: operator() } });
        toast(r.mute && r.mute.ok ? "Đã nhận cảnh báo, còi đã tắt" : "Đã nhận cảnh báo");
      } catch (err) { toast(err.message, true); ack.disabled = false; }
      refreshState();
    } else if (handle) {
      const form = document.querySelector(`[data-form="${handle.dataset.handle}"]`);
      form.hidden = !form.hidden;
      if (!form.hidden) form.elements.action.focus();
    } else if (cancel) {
      const form = document.querySelector(`[data-form="${cancel.dataset.cancel}"]`);
      form.hidden = true;
      delete ui.openForms[cancel.dataset.cancel];
    }
  });

  $("#alertList").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const id = form.dataset.form;
    const btn = form.querySelector("[type=submit]");
    btn.disabled = true;
    try {
      await api(`/api/alerts/${id}/handle`, {
        json: { action: form.elements.action.value, note: form.elements.note.value, operator: operator() },
      });
      delete ui.openForms[id];
      toast(`Đã ghi nhận: ${form.elements.action.value}. Hệ thống sẽ theo dõi kết quả.`);
    } catch (err) {
      toast(err.message, true);
      btn.disabled = false;
    }
    refreshState();
  });

  // ============================================================
  //  Thiết bị
  // ============================================================
  const slider = $("#lightSlider");
  const toggle = $("#lightToggle");

  function renderDevice(dev) {
    const on = dev.light_pct > 0;
    toggle.setAttribute("aria-checked", on ? "true" : "false");
    $("#lightState").textContent = on ? `Đang bật ${dev.light_pct}%` : "Tắt";
    if (!ui.sliderBusy && on) {
      slider.value = dev.light_pct;
      $("#lightOut").textContent = `${dev.light_pct}%`;
    }
    $("#btnBacklight").textContent = dev.backlight ? "Tắt đèn nền LCD" : "Bật đèn nền LCD";
    $("#btnBacklight").dataset.next = dev.backlight ? "0" : "1";
    const mute = $("#btnMute");
    mute.classList.toggle("btn-danger", dev.buzzing);
    mute.textContent = dev.buzzing ? "Tắt còi (đang kêu)" : "Tắt còi";
  }

  async function deviceCmd(cmd, value, btn) {
    if (btn) btn.disabled = true;
    try {
      const r = await api("/api/device", { json: { cmd, value, operator: operator() } });
      const res = r.result || {};
      toast(`${r.text} · ACK ${res.latency_ms ?? "—"} ms qua ${res.link || "—"}`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      if (btn) btn.disabled = false;
      refreshState();
      loadLog();
    }
  }

  slider.addEventListener("input", () => {
    ui.sliderBusy = true;
    $("#lightOut").textContent = `${slider.value}%`;
  });
  $("#lightApply").addEventListener("click", (e) => {
    ui.sliderBusy = false;
    deviceCmd("light", +slider.value, e.currentTarget);
  });
  toggle.addEventListener("click", () => {
    const on = toggle.getAttribute("aria-checked") === "true";
    ui.sliderBusy = false;
    deviceCmd("light", on ? 0 : +slider.value, toggle);
  });
  $("#btnMute").addEventListener("click", (e) => deviceCmd("mute", 1, e.currentTarget));
  $("#btnTest").addEventListener("click", (e) => deviceCmd("test", 1, e.currentTarget));
  $("#btnBacklight").addEventListener("click", (e) => deviceCmd("backlight", e.currentTarget.dataset.next !== "0", e.currentTarget));
  $("#msgForm").addEventListener("submit", (e) => {
    e.preventDefault();
    deviceCmd("msg", $("#msgInput").value, e.target.querySelector("button"));
    $("#msgInput").value = "";
  });

  // ============================================================
  //  Kết nối
  // ============================================================
  function renderLink(link, tm1637) {
    $("#linkActive").textContent = link.active ? `Đang dùng ${link.active}` : "Chưa có kênh nào";
    $("#linkRows").innerHTML = link.links.map((l) => `
      <div class="link-row">
        <span class="dot ${l.alive ? "on" : l.connected ? "wait" : ""}"></span>
        <div class="name"><b>${esc(l.name)}</b>${l.name === link.active ? '<span class="badge-active">đang dùng</span>' : ""}<br><span>${esc(l.port)}</span></div>
        <div class="num">${l.frames} khung · mất ${l.loss_pct}%<br>${l.last_rx_age !== null ? `nhận ${l.last_rx_age}s trước` : "chưa nhận"}</div>
      </div>`).join("");
    $("#linkStats").innerHTML = `
      <dt>Độ trễ lệnh gần nhất</dt><dd>${link.latency_ms ?? "—"} ms</dd>
      <dt>Độ trễ trung bình</dt><dd>${link.avg_latency_ms ?? "—"} ms</dd>
      <dt>Số lần chuyển kênh</dt><dd>${link.failovers}</dd>
      <dt>LED 4 số TM1637</dt><dd>${tm1637 ? "Đang hiển thị" : "Chưa lắp"}</dd>`;
    $("#linkEvents").innerHTML = link.events.map((ev) =>
      `<li><time>${esc(ev.ts)}</time><span>Chuyển kênh ${esc(ev.text)}</span></li>`).join("");
  }

  // ============================================================
  //  Mô phỏng
  // ============================================================
  function renderSim(sim) {
    const lcd = $("#simLcd");
    lcd.textContent = sim.lcd.join("\n");
    lcd.classList.toggle("dim", !sim.lcd_backlight);
    $("#ledGreen").classList.toggle("on", sim.leds.green);
    $("#ledYellow").classList.toggle("on", sim.leds.yellow);
    $("#ledRed").classList.toggle("on", sim.leds.red);
    $("#ledLamp").classList.toggle("on", sim.leds.light > 0);
    $("#buzz").classList.toggle("on", sim.leds.buzzer);
    const e = sim.env;
    let envText = `Trong nhà ${e.temp} °C · ${e.rh}% · ${e.lux} lux. Ngoài trời ${e.t_out} °C · ${e.rh_out}%.`;
    if (sim.scenario.key !== "binh_thuong") {
      envText += ` Kịch bản: ${sim.scenario.label}${sim.scenario.left_s ? ` (còn ${fmtDur(sim.scenario.left_s)})` : ""}.`;
    }
    const down = Object.entries(sim.links).filter(([, on]) => !on).map(([n]) => n);
    if (down.length) envText += ` Kênh đang rớt: ${down.join(", ")}.`;
    $("#simEnv").textContent = envText;

    if (!ui.simBuilt) {
      ui.simBuilt = true;
      $("#simActions").innerHTML = Object.entries(sim.actions).map(([k, label]) =>
        `<button class="chip-btn" data-sim-action="${esc(k)}">${esc(label)}</button>`).join("");
      $("#simScenarios").innerHTML = Object.entries(sim.scenarios).map(([k, label]) =>
        `<button class="chip-btn" data-sim-scenario="${esc(k)}">${esc(label)}</button>`).join("");
    }
    for (const btn of document.querySelectorAll("[data-sim-action]")) {
      const k = btn.dataset.simAction;
      const left = sim.running[k];
      const running = !!left || (k === "che_sang" && sim.shade);
      btn.classList.toggle("running", running);
      btn.textContent = sim.actions[k] + (left ? ` · ${left}s` : k === "che_sang" && sim.shade ? " · đang che" : "");
    }
    $("#simEvents").innerHTML = sim.events.map((ev) =>
      `<li><time>${esc(ev.ts)}</time><span>${esc(ev.text)}</span></li>`).join("");
  }

  document.addEventListener("click", async (e) => {
    const act = e.target.closest("[data-sim-action]");
    const sc = e.target.closest("[data-sim-scenario]");
    if (!act && !sc) return;
    try {
      const r = act
        ? await api("/api/sim/action", { json: { name: act.dataset.simAction } })
        : await api("/api/sim/scenario", { json: { name: sc.dataset.simScenario } });
      toast(r.text);
    } catch (err) { toast(err.message, true); }
    refreshState();
  });

  // ============================================================
  //  Biểu đồ
  // ============================================================
  async function loadChart() {
    try {
      const d = await api(`/api/history?metric=${ui.metric}&range=${ui.range}`);
      chart.set({ ...d, unit: METRIC[ui.metric].unit, color: METRIC[ui.metric].color });
    } catch (err) { /* thử lại ở lần sau */ }
  }

  for (const btn of document.querySelectorAll("[data-metric]")) {
    btn.addEventListener("click", () => {
      ui.metric = btn.dataset.metric;
      for (const b of document.querySelectorAll("[data-metric]")) {
        b.classList.toggle("active", b === btn);
        b.setAttribute("aria-selected", b === btn ? "true" : "false");
      }
      chart.set(null);
      loadChart();
    });
  }
  for (const btn of document.querySelectorAll("[data-range]")) {
    btn.addEventListener("click", () => {
      ui.range = btn.dataset.range;
      for (const b of document.querySelectorAll("[data-range]")) b.classList.toggle("active", b === btn);
      chart.set(null);
      loadChart();
    });
  }

  // ============================================================
  //  Nhật ký xử lý
  // ============================================================
  async function loadLog() {
    let d;
    try { d = await api("/api/alerts"); } catch (err) { return; }
    const k = d.kpi;
    $("#kpiRow").innerHTML = `
      <span class="stat">Cảnh báo hôm nay<b>${k.alerts_today}</b></span>
      <span class="stat">Phản hồi trung bình<b>${fmtDur(k.avg_response_s)}</b></span>
      <span class="stat">Khắc phục trung bình<b>${fmtDur(k.avg_fix_s)}</b></span>`;
    $("#logBody").innerHTML = d.alerts.length ? d.alerts.map((a) => {
      const level = a.metric === "vent" ? `<span class="pill pill-off">Nhắc lịch</span>`
        : `<span class="pill ${LEVEL_CLASS[a.level]}">${LEVEL_TEXT[a.level]}</span>`;
      const fix = a.resolution === "AUTO" ? "tự về ngưỡng" : a.resolution === "HUMAN" ? fmtDur(diffS(a.opened_at, a.resolved_at)) : "—";
      return `<tr>
        <td class="nowrap">${shortTs(a.opened_at)}</td>
        <td>${esc(a.message)}</td>
        <td>${level}</td>
        <td><span class="pill ${STATE_CLASS[a.state]}">${STATE_TEXT[a.state]}</span></td>
        <td>${esc(a.action || "—")}${a.note ? `<br><span class="muted small">${esc(a.note)}</span>` : ""}</td>
        <td>${esc(a.operator || "—")}</td>
        <td>${a.acked_at ? fmtDur(diffS(a.opened_at, a.acked_at)) : "—"}</td>
        <td>${fix}</td>
      </tr>`;
    }).join("") : `<tr><td colspan="8" class="muted">Chưa có cảnh báo nào</td></tr>`;
    $("#deviceLog").innerHTML = d.device_actions.length ? d.device_actions.map((x) =>
      `<li><time>${esc(x.ts.slice(11))}</time><span>${esc(x.action)} · ${esc(x.operator || "")}</span></li>`).join("")
      : `<li class="muted">Chưa có thao tác</li>`;
  }

  // ============================================================
  //  Lịch sử số đo
  // ============================================================
  const STATUS_PILL = (st) => st === null || st === undefined ? "—"
    : `<span class="pill ${LEVEL_CLASS[st]}">${LEVEL_TEXT[st]}</span>`;

  async function loadHistory() {
    let d;
    const q = new URLSearchParams({ page: ui.page, size: 15 });
    if (ui.date) q.set("date", ui.date);
    try { d = await api(`/api/readings?${q}`); } catch (err) { toast(err.message, true); return; }
    ui.pages = Math.max(1, Math.ceil(d.total / d.size));
    $("#historyBody").innerHTML = d.rows.length ? d.rows.map((r) => `<tr>
        <td>${esc(shortTs(r.ts))}</td>
        <td>${fmtNum(r.temp, 1)} °C</td>
        <td>${fmtNum(r.humidity, 1)} %</td>
        <td>${r.lux ?? "—"} lux</td>
        <td>${r.light ? Math.round(r.light / 2.55) + "%" : "Tắt"}</td>
        <td>${STATUS_PILL(r.status)}</td>
        <td>${esc(r.link || "")}</td></tr>`).join("")
      : `<tr><td colspan="7" class="muted">Không có số đo${ui.date ? " trong ngày này" : ""}</td></tr>`;
    $("#pageInfo").textContent = `Trang ${ui.page}/${ui.pages} · ${d.total.toLocaleString("vi-VN")} dòng`;
    $("#prevPage").disabled = ui.page <= 1;
    $("#nextPage").disabled = ui.page >= ui.pages;
    $("#exportLink").href = "/api/export.csv" + (ui.date ? `?date=${ui.date}` : "");
  }

  $("#prevPage").addEventListener("click", () => { ui.page = Math.max(1, ui.page - 1); loadHistory(); });
  $("#nextPage").addEventListener("click", () => { ui.page = Math.min(ui.pages, ui.page + 1); loadHistory(); });
  $("#dateInput").addEventListener("change", (e) => { ui.date = e.target.value; ui.page = 1; loadHistory(); });

  // ============================================================
  //  Hồ sơ nấm
  // ============================================================
  async function loadProfiles() {
    let d;
    try { d = await api("/api/profiles"); } catch (err) { return; }
    ui.profiles = d.profiles;
    const active = d.profiles.find((p) => p.active) || d.profiles[0];
    if (ui.editId === null || !d.profiles.some((p) => p.id === ui.editId)) ui.editId = active.id;
    const opts = d.profiles.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
    $("#profileSelect").innerHTML = opts;
    $("#profileSelect").value = active.id;
    $("#profileEditSelect").innerHTML = opts;
    $("#profileEditSelect").value = ui.editId;
    fillProfileForm();
  }

  function fillProfileForm() {
    const p = ui.profiles.find((x) => x.id === ui.editId);
    if (!p) return;
    const f = $("#profileForm");
    for (const key of ["name", "t_min", "t_max", "h_min", "h_max", "lux_min", "lux_max", "vent_remind_hours"]) {
      f.elements[key].value = p[key] ?? "";
    }
    f.elements.light_on.value = p.light_on || "";
    f.elements.light_off.value = p.light_off || "";
    $("#activateBtn").disabled = !!p.active;
    $("#activateBtn").textContent = p.active ? "Đang dùng hồ sơ này" : "Dùng hồ sơ này";
  }

  async function activateProfile(id) {
    try {
      const r = await api(`/api/profiles/${id}/activate`, { json: { operator: operator() } });
      toast(`Đã chuyển sang hồ sơ ${r.profile.name}, ngưỡng mới đã gửi xuống Arduino`);
      ui.activeId = r.profile.id;
      await loadProfiles();
      loadChart();
      refreshState();
    } catch (err) { toast(err.message, true); }
  }

  $("#profileSelect").addEventListener("change", (e) => activateProfile(+e.target.value));
  $("#profileEditSelect").addEventListener("change", (e) => { ui.editId = +e.target.value; fillProfileForm(); });
  $("#activateBtn").addEventListener("click", () => activateProfile(ui.editId));
  $("#profileForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    try {
      await api(`/api/profiles/${ui.editId}`, { method: "PUT", json: data });
      toast("Đã lưu hồ sơ");
      await loadProfiles();
      loadChart();
    } catch (err) { toast(err.message, true); }
  });

  // ============================================================
  //  Khởi động
  // ============================================================
  refreshState().then(() => { loadChart(); loadLog(); });
  loadHistory();
  setInterval(refreshState, 2000);
  setInterval(tickClocks, 1000);
  setInterval(loadChart, 15000);
  setInterval(loadLog, 10000);
  setInterval(() => { if (ui.page === 1 && !ui.date) loadHistory(); }, 30000);
})();
