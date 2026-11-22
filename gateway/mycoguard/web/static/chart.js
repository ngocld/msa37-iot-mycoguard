/* Biểu đồ đường tự vẽ bằng canvas: không cần thư viện, chạy được khi không có Internet.
   Có dải ngưỡng tô nền, mốc cảnh báo / xử lý, chú thích khi rê chuột. */
(function () {
  "use strict";

  const MIN = 60e3, HOUR = 3600e3, DAY = 86400e3;
  const X_STEPS = [5 * MIN, 10 * MIN, 15 * MIN, 30 * MIN, HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY];

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function niceStep(span, target) {
    const raw = span / target;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const n = raw / mag;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag;
  }

  function pad2(n) { return String(n).padStart(2, "0"); }

  class MiniChart {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.data = null;
      this.hoverX = null;
      canvas.addEventListener("mousemove", (e) => {
        const r = canvas.getBoundingClientRect();
        this.hoverX = e.clientX - r.left;
        this.draw();
      });
      canvas.addEventListener("mouseleave", () => { this.hoverX = null; this.draw(); });
      if (window.ResizeObserver) new ResizeObserver(() => this.draw()).observe(canvas);
      if (window.matchMedia) {
        window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => this.draw());
      }
    }

    set(data) {
      this.data = data;
      this.draw();
    }

    draw() {
      const c = this.canvas, ctx = this.ctx;
      const w = c.clientWidth, h = c.clientHeight;
      if (!w || !h) return;
      const dpr = window.devicePixelRatio || 1;
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const colors = {
        fg: css("--fg"), muted: css("--muted"), line: css("--line"), surface: css("--surface"),
        ok: css("--ok"), bad: css("--bad"), series: css(this.data?.color || "--accent"),
      };
      ctx.font = "12px " + css("--font");

      const d = this.data;
      if (!d || !d.points.length) {
        ctx.fillStyle = colors.muted;
        ctx.textAlign = "center";
        ctx.fillText(d ? "Chưa có dữ liệu trong khoảng thời gian này" : "Đang tải…", w / 2, h / 2);
        return;
      }

      const pad = { l: 48, r: 16, t: 14, b: 28 };
      const pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
      const x0 = d.from, x1 = d.to;
      let lo = Infinity, hi = -Infinity;
      for (const [, v] of d.points) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      if (d.band) { lo = Math.min(lo, d.band[0]); hi = Math.max(hi, d.band[1]); }
      if (hi - lo < 1) { hi += 0.5; lo -= 0.5; }
      const margin = (hi - lo) * 0.08;
      lo -= margin; hi += margin;
      if (d.metric !== "temp") lo = Math.max(0, lo);
      if (d.metric === "humidity") hi = Math.min(100, hi);
      const step = niceStep(hi - lo, 5);
      lo = Math.floor(lo / step) * step;
      hi = Math.ceil(hi / step) * step;

      const X = (t) => pad.l + ((t - x0) / (x1 - x0)) * pw;
      const Y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * ph;

      // Lưới ngang và nhãn trục Y
      ctx.strokeStyle = colors.line;
      ctx.lineWidth = 1;
      ctx.fillStyle = colors.muted;
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      for (let v = lo; v <= hi + step / 2; v += step) {
        const y = Math.round(Y(v)) + 0.5;
        ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
        ctx.fillText(Number.isInteger(step) ? Math.round(v).toString() : v.toFixed(1), pad.l - 8, y);
      }

      // Nhãn trục X
      const span = x1 - x0;
      const xs = X_STEPS.find((s) => span / s <= 7) || DAY;
      const tz = new Date().getTimezoneOffset() * MIN;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      for (let t = Math.ceil((x0 - tz) / xs) * xs + tz; t <= x1; t += xs) {
        const dt = new Date(t);
        const label = xs >= DAY ? `${pad2(dt.getDate())}/${pad2(dt.getMonth() + 1)}` : `${pad2(dt.getHours())}:${pad2(dt.getMinutes())}`;
        const x = X(t);
        if (x < pad.l + 10 || x > w - pad.r - 10) continue;
        ctx.fillText(label, x, h - pad.b + 8);
        ctx.strokeStyle = colors.line;
        ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, h - pad.b); ctx.lineTo(Math.round(x) + 0.5, h - pad.b + 4); ctx.stroke();
      }

      // Dải ngưỡng
      if (d.band) {
        const yTop = Y(d.band[1]), yBot = Y(d.band[0]);
        ctx.fillStyle = colors.ok;
        ctx.globalAlpha = 0.1;
        ctx.fillRect(pad.l, yTop, pw, yBot - yTop);
        ctx.globalAlpha = 0.7;
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = colors.ok;
        for (const y of [yTop, yBot]) {
          ctx.beginPath(); ctx.moveTo(pad.l, Math.round(y) + 0.5); ctx.lineTo(w - pad.r, Math.round(y) + 0.5); ctx.stroke();
        }
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      }

      // Mốc cảnh báo và mốc xử lý
      for (const m of d.marks || []) {
        if (m.t < x0 || m.t > x1) continue;
        const x = Math.round(X(m.t)) + 0.5;
        ctx.strokeStyle = m.kind === "handled" ? colors.ok : colors.bad;
        ctx.lineWidth = 1.5;
        ctx.setLineDash(m.kind === "handled" ? [] : [3, 3]);
        ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, h - pad.b); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = ctx.strokeStyle;
        ctx.beginPath(); ctx.arc(x, pad.t + 3, 3.5, 0, Math.PI * 2); ctx.fill();
      }

      // Đường số liệu: ngắt đoạn khi thiếu dữ liệu quá 3 khoảng
      const gap = (d.bucket_s || 10) * 1000 * 3.5;
      const segments = [];
      let seg = [];
      for (let i = 0; i < d.points.length; i++) {
        if (i && d.points[i][0] - d.points[i - 1][0] > gap) { segments.push(seg); seg = []; }
        seg.push(d.points[i]);
      }
      segments.push(seg);

      const grad = ctx.createLinearGradient(0, pad.t, 0, h - pad.b);
      grad.addColorStop(0, colors.series);
      grad.addColorStop(1, "transparent");
      for (const s of segments) {
        if (!s.length) continue;
        ctx.beginPath();
        s.forEach(([t, v], i) => (i ? ctx.lineTo(X(t), Y(v)) : ctx.moveTo(X(t), Y(v))));
        ctx.lineTo(X(s[s.length - 1][0]), h - pad.b);
        ctx.lineTo(X(s[0][0]), h - pad.b);
        ctx.closePath();
        ctx.globalAlpha = 0.14;
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.beginPath();
        s.forEach(([t, v], i) => (i ? ctx.lineTo(X(t), Y(v)) : ctx.moveTo(X(t), Y(v))));
        ctx.strokeStyle = colors.series;
        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        ctx.stroke();
      }

      // Điểm cuối
      const [lt, lv] = d.points[d.points.length - 1];
      ctx.fillStyle = colors.surface;
      ctx.strokeStyle = colors.series;
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(X(lt), Y(lv), 4, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

      // Chú thích khi rê chuột
      if (this.hoverX !== null && this.hoverX >= pad.l && this.hoverX <= w - pad.r) {
        const t = x0 + ((this.hoverX - pad.l) / pw) * (x1 - x0);
        let best = d.points[0];
        for (const p of d.points) if (Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
        const bx = X(best[0]), by = Y(best[1]);
        ctx.strokeStyle = colors.muted;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(Math.round(bx) + 0.5, pad.t); ctx.lineTo(Math.round(bx) + 0.5, h - pad.b); ctx.stroke();
        ctx.fillStyle = colors.series;
        ctx.beginPath(); ctx.arc(bx, by, 4, 0, Math.PI * 2); ctx.fill();
        const dt = new Date(best[0]);
        const label = `${pad2(dt.getHours())}:${pad2(dt.getMinutes())}  ${best[1]} ${d.unit || ""}`;
        ctx.font = "600 12px " + css("--font");
        const tw = ctx.measureText(label).width + 16;
        let tx = bx + 10;
        if (tx + tw > w - pad.r) tx = bx - tw - 10;
        const ty = Math.max(pad.t, Math.min(by - 14, h - pad.b - 26));
        ctx.fillStyle = colors.fg;
        ctx.beginPath();
        ctx.roundRect ? ctx.roundRect(tx, ty, tw, 24, 6) : ctx.rect(tx, ty, tw, 24);
        ctx.fill();
        ctx.fillStyle = colors.surface;
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText(label, tx + 8, ty + 12);
      }
    }
  }

  window.MiniChart = MiniChart;
})();
