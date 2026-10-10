/*
 * Kroner og renter: live widget til mikkelbohnke.com (GitHub Pages).
 *
 * Brug:
 *   <div class="kr-widget"
 *        data-src="https://<public-konto>.blob.core.windows.net/public/kroner-og-renter/v1/latest.json"
 *        data-catalog="https://<din-django-app>.azurewebsites.net/"
 *        data-repo="https://github.com/iamboehnke/azure-kroner-og-renter"></div>
 *   <script src="/assets/kroner-og-renter.js" defer></script>
 *
 * Ingen afhængigheder. Læser kun den offentlige latest.json, som pipelinen
 * publicerer hver hverdag.
 */
(function () {
  "use strict";

  var CSS = [
    ".kr-widget{--kr-bg:#fff;--kr-text:#1d1f22;--kr-muted:#5f6368;--kr-line:#e3e1da;--kr-accent:#1f5c4a;",
    "--kr-up:#b3261e;--kr-down:#1e7a4c;--kr-warn:#9a6200;font:15px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;",
    "color:var(--kr-text);background:var(--kr-bg);border:1px solid var(--kr-line);border-radius:12px;padding:20px;max-width:640px}",
    "@media (prefers-color-scheme:dark){.kr-widget{--kr-bg:#1c1e21;--kr-text:#e8e6e1;--kr-muted:#a3a29d;--kr-line:#2e3034;",
    "--kr-accent:#7cc4a8;--kr-up:#f08a80;--kr-down:#6cc28f;--kr-warn:#e0b04f}}",
    ".kr-widget *{box-sizing:border-box}",
    ".kr-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:14px}",
    ".kr-title{font-weight:650;font-size:1.05rem;margin:0}",
    ".kr-sub{color:var(--kr-muted);font-size:.82rem}",
    ".kr-rates{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}",
    ".kr-rate{border:1px solid var(--kr-line);border-radius:10px;padding:10px 12px}",
    ".kr-rate .k{font-size:.78rem;color:var(--kr-muted)}",
    ".kr-rate .v{font-size:1.4rem;font-weight:650;font-variant-numeric:tabular-nums}",
    ".kr-table{width:100%;border-collapse:collapse;font-size:.9rem}",
    ".kr-table th{font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:var(--kr-muted);text-align:left;font-weight:600;padding:6px 4px;border-bottom:1px solid var(--kr-line)}",
    ".kr-table td{padding:7px 4px;border-bottom:1px solid var(--kr-line);font-variant-numeric:tabular-nums}",
    ".kr-table tr:last-child td{border-bottom:0}",
    ".kr-num{text-align:right}",
    ".kr-up{color:var(--kr-up)}.kr-down{color:var(--kr-down)}.kr-flat{color:var(--kr-muted)}",
    ".kr-spark{display:block;width:100%;max-width:120px;height:26px}",
    ".kr-spark path{fill:none;stroke:var(--kr-accent);stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}",
    ".kr-foot{margin-top:12px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:.8rem;color:var(--kr-muted)}",
    ".kr-foot a{color:var(--kr-accent)}",
    ".kr-badge{display:inline-block;border:1px solid currentColor;border-radius:99px;padding:1px 8px;font-weight:600}",
    ".kr-badge.ok{color:var(--kr-down)}.kr-badge.warn{color:var(--kr-warn)}",
    ".kr-hide-sm{display:table-cell}@media (max-width:480px){.kr-hide-sm{display:none}}",
    ".kr-msg{color:var(--kr-muted)}"
  ].join("");

  var nf = function (digits) {
    return new Intl.NumberFormat("da-DK", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  };
  var fmt2 = nf(2), fmt4 = nf(4);

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function spark(values) {
    if (!values || values.length < 2) return "";
    var w = 120, h = 26, pad = 2;
    var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    var span = max - min || 1;
    var d = values.map(function (v, i) {
      var x = pad + (i * (w - 2 * pad)) / (values.length - 1);
      var y = h - pad - ((v - min) / span) * (h - 2 * pad);
      return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }).join(" ");
    return '<svg class="kr-spark" viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none" aria-hidden="true"><path d="' + d + '"/></svg>';
  }

  function change(v, unit) {
    if (v === null || v === undefined) return '<span class="kr-flat">-</span>';
    var cls = v > 0 ? "kr-up" : v < 0 ? "kr-down" : "kr-flat";
    var sign = v > 0 ? "+" : "";
    return '<span class="' + cls + '">' + sign + fmt2.format(v) + " " + unit + "</span>";
  }

  function danishDate(iso) {
    var d = new Date(iso + (iso.length === 10 ? "T12:00:00" : ""));
    return d.toLocaleDateString("da-DK", { day: "numeric", month: "long", year: "numeric" });
  }

  function render(el, data) {
    var byId = {};
    (data.rates || []).forEach(function (r) { byId[r.instrument] = r; });
    var policy = byId.OFONAA, destr = byId.DESNAA;
    var q = data.quality || {};
    var qClass = q.errors ? "warn" : "ok";
    var catalog = el.getAttribute("data-catalog");
    var repo = el.getAttribute("data-repo");
    var maxRows = parseInt(el.getAttribute("data-rows") || "6", 10);

    var rates = "";
    if (policy) {
      rates += '<div class="kr-rate"><div class="k">' + esc(policy.name) + '</div><div class="v">' +
        fmt2.format(policy.rate_pct) + ' %</div><div class="kr-sub">' + danishDate(policy.date) + "</div></div>";
    }
    if (destr) {
      rates += '<div class="kr-rate"><div class="k">' + esc(destr.name) + '</div><div class="v">' +
        fmt4.format(destr.rate_pct) + ' %</div><div class="kr-sub">' + danishDate(destr.date) + " &middot; " +
        change(destr.change_bp, "bp") + "</div></div>";
    }

    var rows = (data.fx || []).slice(0, maxRows).map(function (f) {
      return "<tr><td><strong>" + esc(f.currency) + '</strong> <span class="kr-sub">' + esc(f.name) + "</span></td>" +
        '<td class="kr-num">' + fmt4.format(f.dkk_per_unit) + "</td>" +
        '<td class="kr-num">' + change(f.change_1d_pct, "%") + "</td>" +
        '<td class="kr-hide-sm">' + spark(f.spark) + "</td></tr>";
    }).join("");
    var asOf = data.fx && data.fx[0] ? danishDate(data.fx[0].date) : "";

    var links = [];
    if (catalog) links.push('<a href="' + esc(catalog) + '">Datakatalog og API</a>');
    if (repo) links.push('<a href="' + esc(repo) + '">Kode</a>');

    el.innerHTML =
      '<div class="kr-head"><p class="kr-title">Kroner og renter</p>' +
      '<span class="kr-sub">Nationalbankens tal for ' + esc(asOf) + "</span></div>" +
      (rates ? '<div class="kr-rates">' + rates + "</div>" : "") +
      '<table class="kr-table"><thead><tr><th>Valuta</th><th class="kr-num">Kroner</th>' +
      '<th class="kr-num">1 dag</th><th class="kr-hide-sm">30 bankdage</th></tr></thead><tbody>' +
      rows + "</tbody></table>" +
      '<div class="kr-foot"><span><span class="kr-badge ' + qClass + '">' + (q.passed || 0) + " af " +
      (q.total || 0) + " kvalitetstjek bestået</span> &middot; opdateret " +
      esc(new Date(data.generated_at).toLocaleString("da-DK", { dateStyle: "short", timeStyle: "short" })) +
      "</span><span>" + links.join(" &middot; ") + "</span></div>";
  }

  function load(el) {
    var src = el.getAttribute("data-src");
    if (!src) { el.innerHTML = '<p class="kr-msg">Mangler data-src.</p>'; return; }
    el.innerHTML = '<p class="kr-msg">Henter dagens tal ...</p>';
    fetch(src, { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (data) { render(el, data); })
      .catch(function () {
        el.innerHTML = '<p class="kr-msg">Tallene kunne ikke hentes lige nu. Pipelinen kører hver hverdag morgen.</p>';
      });
  }

  function init() {
    if (!document.getElementById("kr-widget-css")) {
      var style = document.createElement("style");
      style.id = "kr-widget-css";
      style.textContent = CSS;
      document.head.appendChild(style);
    }
    Array.prototype.forEach.call(document.querySelectorAll(".kr-widget"), load);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  // Til test i Node
  if (typeof module !== "undefined") module.exports = { render: render, spark: spark };
})();
