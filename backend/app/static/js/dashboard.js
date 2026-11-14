(function () {
  const form = document.getElementById("config-form");
  const list = document.getElementById("steps-list");
  const addButton = document.getElementById("add-step");
  const sequenceJson = document.getElementById("sequence_json");
  const colorJson = document.getElementById("color_json");
  const playlistBox = document.getElementById("playlist-box");
  const colorBox = document.getElementById("color-box");
  const segmentsList = document.getElementById("segments-list");
  const addSegment = document.getElementById("add-segment");
  const colorSize = document.getElementById("color-size");
  if (!form || !list || !addButton || !sequenceJson || !colorJson) return;

  const boot = JSON.parse(document.getElementById("edit-data").textContent || "null");
  const effectNames = JSON.parse(document.getElementById("effect-names").textContent || "[]");

  function selectedType() {
    const checked = form.querySelector('input[name="effect_type"]:checked');
    return checked ? checked.value : "playlist";
  }

  function showType(type) {
    const color = type === "color";
    playlistBox.classList.toggle("hidden", color);
    colorBox.classList.toggle("hidden", !color);
  }

  form.querySelectorAll('input[name="effect_type"]').forEach(function (input) {
    input.addEventListener("change", function () {
      const type = selectedType();
      showType(type);
      if (type === "color" && segmentsList.children.length === 0) addSegmentRow(null);
    });
  });

  const presetNode = document.getElementById("preset-catalog");
  const presets = presetNode ? JSON.parse(presetNode.textContent || "[]") : [];

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function presetOptions(selected) {
    const current = Number(selected);
    const known = presets.some(function (preset) { return Number(preset.id) === current; });
    let html = "";
    if (!known && Number.isFinite(current)) {
      html += '<option value="' + current + '" selected>' + current + "</option>";
    }
    ["playlist", "preset"].forEach(function (kind) {
      const group = presets.filter(function (preset) { return preset.kind === kind; });
      if (!group.length) return;
      html += '<optgroup label="' + (kind === "playlist" ? "Playlist" : "Preset") + '">';
      group.forEach(function (preset) {
        const mark = Number(preset.id) === current ? " selected" : "";
        html += '<option value="' + preset.id + '"' + mark + ">" + preset.id + " · " + escapeHtml(preset.name) + "</option>";
      });
      html += "</optgroup>";
    });
    return html;
  }

  function addStep(playlist, seconds) {
    const row = document.createElement("div");
    row.className = "step-row flex flex-wrap items-end gap-3";
    const chooser = presets.length
      ? '<select class="field step-playlist min-w-64" required>' + presetOptions(playlist) + "</select>"
      : '<input type="number" min="1" max="250" value="' + playlist + '" class="field step-playlist w-28" required />';
    row.innerHTML =
      '<label class="block">' +
      '<span class="mb-1 block text-xs text-mist">Preset</span>' +
      chooser +
      "</label>" +
      '<label class="block">' +
      '<span class="mb-1 block text-xs text-mist">Segundos</span>' +
      '<input type="number" min="1" max="3600" value="' + seconds + '" class="field step-seconds w-28" required />' +
      "</label>" +
      '<button type="button" class="remove-step rounded-lg border border-line px-3 py-2 text-sm text-mist hover:border-ember hover:text-ember">Quitar</button>';
    row.querySelector(".remove-step").addEventListener("click", function () {
      if (list.children.length === 1) return;
      row.remove();
    });
    list.appendChild(row);
  }

  function effectOptions(selected) {
    return effectNames
      .map(function (item) {
        const id = item[0];
        const name = item[1];
        const mark = Number(selected) === Number(id) ? " selected" : "";
        return '<option value="' + id + '"' + mark + ">" + id + " · " + name + "</option>";
      })
      .join("");
  }

  function rgbToHex(color) {
    const channels = Array.isArray(color) ? color : [255, 0, 0];
    return (
      "#" +
      channels
        .slice(0, 3)
        .map(function (channel) {
          return Number(channel).toString(16).padStart(2, "0");
        })
        .join("")
    );
  }

  function suggestedRange() {
    const rows = segmentsList.querySelectorAll(".segment-row");
    if (!rows.length) return { start: 0, hasta: 29 };
    const last = rows[rows.length - 1];
    const prevStart = Number(last.querySelector(".seg-start").value) || 0;
    const prevHasta = Number(last.querySelector(".seg-stop").value);
    const length = Math.max(1, (Number.isFinite(prevHasta) ? prevHasta : prevStart + 29) - prevStart + 1);
    const start = (Number.isFinite(prevHasta) ? prevHasta : prevStart + 29) + 1;
    return { start: start, hasta: start + length - 1 };
  }

  function inclusiveEnd(segment, fallbackStart) {
    if (segment && segment.stop != null) return Number(segment.stop) - 1;
    return fallbackStart + 29;
  }

  function addSegmentRow(segment) {
    const suggested = suggestedRange();
    const current = segment || { fx: 0, sx: 128, col: [[255, 200, 0]], start: suggested.start };
    const start = current.start == null ? suggested.start : Number(current.start);
    const hasta = inclusiveEnd(current, start);
    const row = document.createElement("div");
    row.className = "segment-row flex flex-wrap items-end gap-3";
    row.innerHTML =
      '<label class="block"><span class="mb-1 block text-xs text-mist">Desde</span>' +
      '<input type="number" min="0" max="65534" value="' + start + '" class="field seg-start w-24" /></label>' +
      '<label class="block"><span class="mb-1 block text-xs text-mist">Hasta</span>' +
      '<input type="number" min="0" max="65534" value="' + hasta + '" class="field seg-stop w-24" /></label>' +
      '<label class="block"><span class="mb-1 block text-xs text-mist">Efecto</span>' +
      '<select class="field seg-fx w-44">' + effectOptions(current.fx || 0) + "</select></label>" +
      '<label class="block"><span class="mb-1 block text-xs text-mist">Velocidad</span>' +
      '<input type="number" min="0" max="255" value="' + Number(current.sx == null ? 128 : current.sx) + '" class="field seg-sx w-24" /></label>' +
      '<label class="block"><span class="mb-1 block text-xs text-mist">Color</span>' +
      '<input type="color" value="' + rgbToHex(current.col && current.col[0]) + '" class="field seg-color h-10 w-16" /></label>' +
      '<button type="button" class="remove-segment rounded-lg border border-line px-3 py-2 text-sm text-mist hover:border-ember hover:text-ember">Quitar</button>';
    row.querySelector(".remove-segment").addEventListener("click", function () {
      if (segmentsList.children.length === 1) return;
      row.remove();
      refreshSize();
    });
    row.querySelectorAll("input, select").forEach(function (input) {
      input.addEventListener("input", refreshSize);
    });
    segmentsList.appendChild(row);
    refreshSize();
  }

  function hexToRgb(hex) {
    const clean = String(hex || "#ff0000").replace("#", "");
    return [
      parseInt(clean.slice(0, 2), 16) || 0,
      parseInt(clean.slice(2, 4), 16) || 0,
      parseInt(clean.slice(4, 6), 16) || 0,
    ];
  }

  function colorPayload() {
    const segments = Array.from(segmentsList.querySelectorAll(".segment-row")).map(function (row, index) {
      const desde = Number(row.querySelector(".seg-start").value);
      const hasta = Number(row.querySelector(".seg-stop").value);
      return {
        id: index,
        start: desde,
        stop: hasta + 1,
        fx: Number(row.querySelector(".seg-fx").value),
        sx: Number(row.querySelector(".seg-sx").value),
        col: [hexToRgb(row.querySelector(".seg-color").value)],
      };
    });
    return {
      every: Number(document.getElementById("color-every").value),
      on: document.getElementById("color-on").checked,
      bri: Number(document.getElementById("color-bri").value),
      seg: segments,
    };
  }

  function refreshSize() {
    if (!colorSize || colorBox.classList.contains("hidden")) return;
    const bytes = new TextEncoder().encode(JSON.stringify(colorPayload())).length;
    colorSize.textContent =
      bytes <= 250
        ? bytes + " bytes en claro. El máximo del paquete es 250."
        : bytes + " bytes en claro. Al guardar se empaqueta si el resultado cabe en 250.";
  }

  ["color-on", "color-bri", "color-every"].forEach(function (id) {
    const input = document.getElementById(id);
    if (input) input.addEventListener("input", refreshSize);
  });

  function splitEven() {
    const total = Number(document.getElementById("strip-leds").value);
    const rows = Array.from(segmentsList.querySelectorAll(".segment-row"));
    if (!rows.length || !Number.isFinite(total) || total < rows.length) return;
    const base = Math.floor(total / rows.length);
    let extra = total % rows.length;
    let cursor = 0;
    rows.forEach(function (row) {
      const length = base + (extra > 0 ? 1 : 0);
      if (extra > 0) extra -= 1;
      row.querySelector(".seg-start").value = String(cursor);
      row.querySelector(".seg-stop").value = String(cursor + length - 1);
      cursor += length;
    });
    refreshSize();
  }

  const catalogNode = document.getElementById("pattern-catalog");
  const catalog = catalogNode ? JSON.parse(catalogNode.textContent || "[]") : [];
  const patternsById = {};
  catalog.forEach(function (item) { patternsById[item.id] = item; });

  function bandLengths(weights, total) {
    const count = weights.length;
    const sum = weights.reduce(function (acc, weight) { return acc + weight; }, 0) || 1;
    const lengths = weights.map(function () { return 1; });
    let left = total - count;
    const raw = weights.map(function (weight) { return (left * weight) / sum; });
    const extra = raw.map(function (value) { return Math.floor(value); });
    extra.forEach(function (value, index) { lengths[index] += value; });
    let remain = left - extra.reduce(function (acc, value) { return acc + value; }, 0);
    const order = raw
      .map(function (value, index) { return [value - Math.floor(value), index]; })
      .sort(function (a, b) { return b[0] - a[0]; });
    let cursor = 0;
    while (remain > 0 && order.length) {
      lengths[order[cursor % order.length][1]] += 1;
      remain -= 1;
      cursor += 1;
    }
    return lengths;
  }

  function paintBands(bands, fx) {
    const weights = bands.map(function (band) { return band.weight || 1; });
    const strip = document.getElementById("strip-leds");
    let total = Number(strip && strip.value);
    if (!Number.isFinite(total) || total < weights.length) {
      total = Math.max(weights.length, 98);
      if (strip) strip.value = String(total);
    }
    const lengths = bandLengths(weights, total);
    segmentsList.innerHTML = "";
    let cursor = 0;
    bands.forEach(function (band, index) {
      const length = lengths[index];
      addSegmentRow({
        start: cursor,
        stop: cursor + length,
        fx: fx,
        sx: 128,
        col: [hexToRgb(band.hex)],
      });
      cursor += length;
    });
  }

  function useColorMode() {
    const radio = form.querySelector('input[name="effect_type"][value="color"]');
    if (radio) radio.checked = true;
    showType("color");
  }

  document.querySelectorAll(".pattern-card").forEach(function (button) {
    button.addEventListener("click", function () {
      const pattern = patternsById[button.getAttribute("data-pattern")];
      if (!pattern) return;
      useColorMode();
      const name = document.getElementById("config-name");
      if (name && !name.value.trim()) name.value = pattern.name;
      paintBands(pattern.bands, Number(pattern.fx) || 0);
    });
  });

  document.querySelectorAll(".fx-pill").forEach(function (button) {
    button.addEventListener("click", function () {
      useColorMode();
      if (!segmentsList.children.length) addSegmentRow(null);
      const fx = button.getAttribute("data-fx");
      segmentsList.querySelectorAll(".seg-fx").forEach(function (select) {
        select.value = fx;
      });
      refreshSize();
    });
  });

  function pushColor(hex) {
    useColorMode();
    const bands = Array.from(segmentsList.querySelectorAll(".segment-row")).map(function (row) {
      return { hex: row.querySelector(".seg-color").value, weight: 1 };
    });
    const currentFx = segmentsList.querySelector(".seg-fx");
    bands.push({ hex: hex, weight: 1 });
    paintBands(bands, currentFx ? Number(currentFx.value) : 0);
  }

  const addColor = document.getElementById("pd-add-color");
  const addDark = document.getElementById("pd-add-dark");
  const wheel = document.getElementById("pd-wheel");
  if (addColor && wheel) addColor.addEventListener("click", function () { pushColor(wheel.value); });
  if (addDark) addDark.addEventListener("click", function () { pushColor("#000000"); });

  const briNumber = document.getElementById("color-bri");
  const briRange = document.getElementById("color-bri-range");
  if (briNumber && briRange) {
    briRange.addEventListener("input", function () {
      briNumber.value = briRange.value;
      refreshSize();
    });
    briNumber.addEventListener("input", function () {
      briRange.value = briNumber.value;
    });
  }

  addButton.addEventListener("click", function () {
    addStep(1, 10);
  });
  addSegment.addEventListener("click", function () {
    addSegmentRow(null);
  });
  document.getElementById("split-segments").addEventListener("click", splitEven);

  form.addEventListener("submit", function (event) {
    if (selectedType() === "color") {
      const payload = colorPayload();
      if (!payload.seg.length) {
        event.preventDefault();
        return;
      }
      colorJson.value = JSON.stringify(payload);
      sequenceJson.value = "";
      return;
    }
    const steps = Array.from(list.querySelectorAll(".step-row")).map(function (row) {
      return {
        playlist: Number(row.querySelector(".step-playlist").value),
        seg: Number(row.querySelector(".step-seconds").value),
      };
    });
    if (!steps.length) {
      event.preventDefault();
      return;
    }
    sequenceJson.value = JSON.stringify({ loop: true, steps: steps });
    colorJson.value = "";
  });

  if (boot && boot.type === "color") {
    form.querySelector('input[name="effect_type"][value="color"]').checked = true;
    showType("color");
    const payload = boot.payload || {};
    document.getElementById("color-on").checked = payload.on !== false;
    document.getElementById("color-bri").value = payload.bri == null ? 180 : payload.bri;
    const briRangeBoot = document.getElementById("color-bri-range");
    if (briRangeBoot) briRangeBoot.value = document.getElementById("color-bri").value;
    document.getElementById("color-every").value = payload.every || 5;
    const segments = Array.isArray(payload.seg) && payload.seg.length ? payload.seg : [{ id: 0, fx: 0, sx: 128, col: [[255, 0, 0]] }];
    segments.forEach(addSegmentRow);
  } else if (boot && boot.type === "playlist") {
    showType("playlist");
    const steps = (boot.payload && boot.payload.steps) || [];
    if (steps.length) steps.forEach(function (step) { addStep(step.playlist, step.seg || step.seconds || 1); });
    else addStep(1, 3);
  } else {
    showType("playlist");
    addStep(1, 3);
    addStep(4, 2);
  }
})();
