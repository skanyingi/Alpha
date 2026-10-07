/* AquaAsk answer-card modes: Answer text + Graphs */
(function () {
  var graphTip = null;

  function setTab(root, name) {
    root.querySelectorAll(".mode-tab").forEach(function (btn) {
      btn.classList.toggle("is-on", btn.getAttribute("data-tab") === name);
    });
    root.querySelectorAll(".mode-panel").forEach(function (panel) {
      panel.classList.toggle("is-on", panel.getAttribute("data-panel") === name);
    });
  }

  function catmull(points, n) {
    var out = [];
    if (!points.length) return out;
    for (var i = 0; i < n; i++) {
      var t = i / (n - 1);
      var x = t * (points.length - 1);
      var i0 = Math.floor(x);
      var i1 = Math.min(points.length - 1, i0 + 1);
      var f = x - i0;
      out.push(points[i0] * (1 - f) + points[i1] * f);
    }
    return out;
  }

  function drawGraph(svg, spec) {
    var w = 640, h = 280, pad = { l: 36, r: 18, t: 28, b: 36 };
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    svg.innerHTML = "";
    var labels = spec.labels || [];
    var series = spec.series || [];
    if (!labels.length || !series.length) {
      svg.innerHTML = "<text x='40' y='140' fill='#5f6368'>No comparable series in this answer.</text>";
      return;
    }
    var all = [];
    series.forEach(function (s) { (s.points || []).forEach(function (p) { all.push(p); }); });
    var min = Math.min.apply(null, all.concat([0]));
    var max = Math.max.apply(null, all.concat([1]));
    var span = max - min || 1;
    function x(i) { return pad.l + i * (w - pad.l - pad.r) / Math.max(1, labels.length - 1); }
    function y(v) { return h - pad.b - ((v - min) / span) * (h - pad.t - pad.b); }
    var ns = "http://www.w3.org/2000/svg";
    function el(name, attrs) {
      var node = document.createElementNS(ns, name);
      Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
      return node;
    }
    svg.appendChild(el("rect", { x: 0, y: 0, width: w, height: h, fill: "transparent" }));
    for (var g = 0; g < 4; g++) {
      var gy = pad.t + g * (h - pad.t - pad.b) / 3;
      svg.appendChild(el("line", { x1: pad.l, x2: w - pad.r, y1: gy, y2: gy, stroke: "rgba(95,99,104,.18)", "stroke-dasharray": "3 6" }));
    }
    series.forEach(function (s, si) {
      var pts = s.points || [];
      var dense = catmull(pts, 48);
      var d = "";
      dense.forEach(function (v, i) {
        var px = pad.l + i * (w - pad.l - pad.r) / Math.max(1, dense.length - 1);
        d += (i ? "L" : "M") + px + " " + y(v);
      });
      var area = d + " L" + (w - pad.r) + " " + (h - pad.b) + " L" + pad.l + " " + (h - pad.b) + " Z";
      svg.appendChild(el("path", { d: area, fill: s.color || "#12b5c4", "fill-opacity": si ? "0.16" : "0.22" }));
      svg.appendChild(el("path", { d: d, fill: "none", stroke: s.color || "#12b5c4", "stroke-width": "3.2", filter: "url(#glow)" }));
      pts.forEach(function (v, i) {
        svg.appendChild(el("circle", { cx: x(i), cy: y(v), r: 4.2, fill: s.color || "#12b5c4", stroke: "#fff", "stroke-width": "2" }));
      });
    });
    var defs = el("defs", {});
    defs.innerHTML = '<filter id="glow"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>';
    svg.insertBefore(defs, svg.firstChild);
    labels.forEach(function (lab, i) {
      var t = el("text", { x: x(i), y: h - 12, fill: "#5f6368", "font-size": "11", "text-anchor": "middle" });
      t.textContent = lab;
      svg.appendChild(t);
    });
    if (spec.highlight_value) {
      var hx = x(Math.max(0, labels.indexOf(spec.highlight_label)));
      var hv = spec.highlight_value + (spec.highlight_unit ? " " + spec.highlight_unit : "");
      var ht = el("text", { x: hx, y: 22, fill: "#202124", "font-size": "20", "font-weight": "600", "text-anchor": "middle" });
      ht.textContent = hv;
      svg.appendChild(ht);
    }
    svg.onmousemove = function (ev) {
      var box = svg.getBoundingClientRect();
      var t = (ev.clientX - box.left) / box.width;
      var idx = Math.round(t * (labels.length - 1));
      idx = Math.max(0, Math.min(labels.length - 1, idx));
      if (!graphTip) return;
      graphTip.textContent = labels[idx] + " · " + series.map(function (s) { return s.name + " " + s.points[idx]; }).join("  ·  ");
    };
  }

  window.renderAquaModes = function (root, modes) {
    if (!root) return;
    modes = modes || {};
    var startTab = modes.default_tab === "graphs" || modes.default_tab === "map" ? modes.default_tab : "answer";
    setTab(root, startTab);
    graphTip = root.querySelector("#graphTip");
    var graphSvg = root.querySelector("#graphSvg");
    root.querySelectorAll(".mode-tab").forEach(function (btn) {
      btn.onclick = function () {
        setTab(root, btn.getAttribute("data-tab"));
        if (btn.getAttribute("data-tab") === "map" && window.showCatmodMap) window.showCatmodMap();
      };
    });
    if (graphSvg) drawGraph(graphSvg, modes.graph || {});
    if (startTab === "map" && window.showCatmodMap) window.showCatmodMap();
  };
})();
