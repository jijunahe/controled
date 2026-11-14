(function () {
  const canvas = document.getElementById("strip");
  const sourceEl = document.getElementById("scene-source");
  const nameEl = document.getElementById("scene-name");
  const detailEl = document.getElementById("scene-detail");
  const stepEl = document.getElementById("scene-step");
  const clockEl = document.getElementById("scene-clock");
  const boot = document.getElementById("scene-data");
  if (!canvas || !boot) return;

  const ctx = canvas.getContext("2d");
  let scene = JSON.parse(boot.textContent || "{}");
  let skew = (scene.now || Date.now() / 1000) - Date.now() / 1000;

  function clock() {
    return Date.now() / 1000 + skew;
  }

  function pick(steps, moment) {
    const total = steps.reduce(function (sum, step) { return sum + step.seconds; }, 0);
    if (!total) return null;
    let cursor = ((moment % total) + total) % total;
    for (let index = 0; index < steps.length; index += 1) {
      const step = steps[index];
      if (cursor < step.seconds) return { step: step, into: cursor };
      cursor -= step.seconds;
    }
    return { step: steps[0], into: 0 };
  }

  function resolvePreset(presetId, into, fallback) {
    const item = scene.presets[String(presetId)];
    if (!item) return { segments: [], bri: scene.bri || 160, label: fallback || "" };
    if (item.playlist && item.playlist.length) {
      const chosen = pick(item.playlist, into);
      if (!chosen) return { segments: [], bri: 160, label: fallback || "" };
      return resolvePreset(chosen.step.id, chosen.into, chosen.step.name);
    }
    return { segments: item.seg || [], bri: item.bri || scene.bri || 160, label: fallback || "" };
  }

  function frameOf(now) {
    if (scene.mode !== "run") return { segments: [], bri: 0, label: "" };
    if (scene.kind === "segments") return { segments: scene.segments || [], bri: scene.bri || 160, label: scene.name || "" };
    const chosen = pick(scene.steps || [], now);
    if (!chosen) return { segments: [], bri: 0, label: "" };
    return resolvePreset(chosen.step.id, chosen.into, chosen.step.name);
  }

  function mix(a, b, t) {
    const amount = Math.max(0, Math.min(1, t));
    return [
      Math.round(a[0] + (b[0] - a[0]) * amount),
      Math.round(a[1] + (b[1] - a[1]) * amount),
      Math.round(a[2] + (b[2] - a[2]) * amount),
    ];
  }

  function scale(color, amount) {
    return color.map(function (channel) { return Math.round(channel * amount); });
  }

  function palette(seg) {
    const cols = (seg.col || []).filter(function (color) {
      return color && color.length >= 3;
    });
    const paints = cols.filter(function (color) {
      return color[0] + color[1] + color[2] > 8;
    });
    return paints.length ? paints : [[255, 255, 255]];
  }

  function brightest(cols) {
    return cols.slice().sort(function (a, b) {
      return (b[0] + b[1] + b[2]) - (a[0] + a[1] + a[2]);
    })[0];
  }

  function kindOf(seg) {
    if (seg.motion) return seg.motion;
    const fx = Number(seg.fx) || 0;
    const known = {
      0: "solid", 1: "blink", 2: "breathe", 3: "wipe", 8: "colorloop", 9: "rainbow",
      10: "scan", 12: "fade", 13: "theater", 15: "chase", 17: "twinkle", 20: "spark",
      28: "chase", 30: "rainbow", 40: "scanner", 41: "comet", 42: "fireworks",
      43: "rain", 44: "tetrix", 45: "fire", 57: "lightning", 66: "fire", 67: "waves",
      76: "meteor", 151: "pacman"
    };
    return known[fx] || (fx ? "waves" : "solid");
  }

  function effectColor(seg, index, now) {
    const cols = palette(seg);
    const span = Math.max(1, seg.b - seg.a);
    const at = index - seg.a;
    const along = at / span;
    const sx = Number(seg.sx);
    const speed = 0.25 + ((Number.isFinite(sx) ? sx : 128) / 255) * 1.8;
    const phase = now * speed;
    const kind = kindOf(seg);
    const black = [0, 0, 0];

    if (kind === "solid") return cols[0];
    if (kind === "blink") return Math.sin(phase * 4) > 0 ? cols[Math.floor(phase) % cols.length] : black;
    if (kind === "breathe") {
      const cycle = phase * 0.25;
      const color = mix(cols[Math.floor(cycle) % cols.length], cols[(Math.floor(cycle) + 1) % cols.length], cycle % 1);
      return scale(color, 0.12 + 0.88 * (0.5 + 0.5 * Math.sin(phase * 2.2)));
    }
    if (kind === "wipe") {
      const turn = phase * 0.28;
      const frontier = turn % 1;
      const color = cols[Math.floor(turn) % cols.length];
      const previous = cols.length > 1 ? cols[(Math.floor(turn) + cols.length - 1) % cols.length] : black;
      return along < frontier ? color : previous;
    }
    if (kind === "fade") {
      if (cols.length === 1) return scale(cols[0], 0.15 + 0.85 * (0.5 + 0.5 * Math.sin(phase * 1.6)));
      const cycle = phase * 0.22;
      return mix(cols[Math.floor(cycle) % cols.length], cols[(Math.floor(cycle) + 1) % cols.length], cycle % 1);
    }
    if (kind === "colorloop") return hsl((phase * 0.05) % 1, 0.95, 0.52);
    if (kind === "rainbow") {
      if (cols.length >= 3) {
        const x = (along + phase * 0.07) % 1;
        const scaled = x * cols.length;
        const slot = Math.floor(scaled) % cols.length;
        return mix(cols[slot], cols[(slot + 1) % cols.length], scaled % 1);
      }
      return hsl((along + phase * 0.07) % 1, 0.95, 0.52);
    }
    if (kind === "chase") {
      if (cols.length === 1) {
        const block = Math.max(4, Math.round(span / 6));
        const pos = Math.floor(phase * 8) % span;
        const dist = (at - pos + span) % span;
        return dist < block ? cols[0] : black;
      }
      const block = Math.max(4, Math.round(span / (cols.length * 4)));
      const slot = Math.floor((at + phase * 8) / block) % cols.length;
      return cols[(slot + cols.length) % cols.length];
    }
    if (kind === "theater") {
      const shift = Math.floor(phase * 6);
      if ((at + shift) % 3 !== 0) return black;
      return cols[Math.floor((at + shift) / 3) % cols.length];
    }
    if (kind === "scan" || kind === "scanner") {
      const tri = kind === "scanner" ? Math.abs((phase * 0.18) % 2 - 1) : (phase * 0.16) % 1;
      const pos = tri * span;
      const dist = Math.abs(at - pos);
      return dist < 2.4 ? brightest(cols) : scale(cols[0], 0.06);
    }
    if (kind === "comet" || kind === "meteor") {
      const pos = ((phase * (kind === "meteor" ? 0.22 : 0.14)) % 1) * span;
      const behind = (pos - at + span) % span;
      const tail = kind === "meteor" ? 22 : 14;
      if (behind > tail) return black;
      return scale(brightest(cols), Math.pow(1 - behind / tail, kind === "meteor" ? 1.2 : 1.8));
    }
    if (kind === "fire") {
      const heat = 0.25 + along * 0.75;
      const flicker = 0.45 + 0.55 * Math.abs(Math.sin(phase * 11 + index * 1.9) * Math.sin(phase * 4 + index * 0.7));
      const hot = cols[0];
      const cool = cols[1] || [255, 140, 0];
      return scale(mix(cool, hot, Math.min(1, heat)), heat * flicker);
    }
    if (kind === "spark" || kind === "twinkle") {
      const bucket = Math.floor(phase * (kind === "spark" ? 7 : 3));
      const roll = Math.abs(Math.sin(index * 12.9898 + bucket * 78.233));
      const gate = kind === "spark" ? 0.78 : 0.9;
      if (roll < gate) return black;
      return cols[Math.floor(roll * 17) % cols.length];
    }
    if (kind === "fireworks") {
      const burst = Math.floor(phase * 1.4);
      const center = Math.abs(Math.sin(burst * 4.7)) * span;
      const age = (phase * 1.4) % 1;
      const dist = Math.abs(at - center);
      if (dist < age * span * 0.35 && dist > age * span * 0.18) return cols[burst % cols.length];
      return scale(cols[cols.length - 1] || black, 0.08);
    }
    if (kind === "rain") {
      const drop = Math.floor(at + phase * 14) % 8;
      return drop === 0 ? cols[0] : scale(cols[1] || [0, 10, 30], 0.35);
    }
    if (kind === "tetrix") {
      const fall = Math.floor(phase * 5);
      const row = (at + fall) % Math.max(6, Math.round(span / 8));
      return row < 2 ? cols[Math.floor((at + fall) / 6) % cols.length] : black;
    }
    if (kind === "lightning") {
      const flash = Math.sin(phase * 0.7) > 0.92;
      return flash ? [210, 220, 255] : scale(cols[0], 0.08);
    }
    if (kind === "waves") {
      const wave = 0.5 + 0.5 * Math.sin(along * 10 + phase * 2);
      return mix(cols[0], cols[1] || cols[0], wave);
    }
    if (kind === "pacman") {
      const pos = ((phase * 0.12) % 1) * span;
      if (Math.abs(at - pos) < 1.6) return [252, 209, 22];
      if (at > pos && (Math.floor(at) % 4) === 0) return cols[at % cols.length];
      return black;
    }
    const wave = 0.5 + 0.5 * Math.sin(along * 8 + phase * 2);
    return mix(cols[0], cols[1] || cols[0], wave);
  }

  function hsl(h, s, l) {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    function channel(shift) {
      let t = h + shift;
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    }
    return [Math.round(channel(1 / 3) * 255), Math.round(channel(0) * 255), Math.round(channel(-1 / 3) * 255)];
  }

  function ledsFor(now) {
    const count = scene.leds || 98;
    const picture = frameOf(now);
    const gain = picture.bri / 255;
    const leds = Array.from({ length: count }, function () { return scene.mode === "run" ? [6, 8, 12] : [8, 10, 14]; });
    picture.segments.forEach(function (seg) {
      for (let index = seg.a; index < seg.b && index < count; index += 1) {
        leds[index] = scale(effectColor(seg, index, now), gain);
      }
    });
    return { leds: leds, label: picture.label };
  }

  function draw() {
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (width < 2 || height < 2) {
      requestAnimationFrame(draw);
      return;
    }
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const now = clock();
    const picture = ledsFor(now);
    if (stepEl) stepEl.textContent = picture.label || "";
    const count = picture.leds.length;
    const gap = Math.max(1, height / count * 0.18);
    const cell = (height - gap * (count + 1)) / count;
    const ledWidth = Math.min(width * 0.62, 54);
    const x = (width - ledWidth) / 2;
    picture.leds.forEach(function (color, index) {
      const y = gap + index * (cell + gap);
      const lit = color[0] + color[1] + color[2] > 24;
      ctx.shadowColor = lit ? "rgba(" + color.join(",") + ",0.9)" : "transparent";
      ctx.shadowBlur = lit ? 10 : 0;
      ctx.fillStyle = "rgb(" + color.join(",") + ")";
      const radius = Math.min(4, cell / 2);
      ctx.beginPath();
      ctx.roundRect(x, y, ledWidth, Math.max(1.5, cell), radius);
      ctx.fill();
    });
    requestAnimationFrame(draw);
  }

  function show(next) {
    scene = next;
    skew = (scene.now || Date.now() / 1000) - Date.now() / 1000;
    if (sourceEl) sourceEl.textContent = scene.source || "";
    if (nameEl) nameEl.textContent = scene.name || "";
    if (detailEl) detailEl.textContent = scene.detail || "";
    if (clockEl) clockEl.textContent = scene.clock ? "Hora Colombia " + scene.clock : "";
  }

  async function refresh() {
    try {
      const response = await fetch("/simulacion/datos", { headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const next = await response.json();
      const same = next.mode === scene.mode && next.id === scene.id && next.name === scene.name && next.detail === scene.detail;
      if (!same) show(next);
      else if (clockEl && next.clock) clockEl.textContent = "Hora Colombia " + next.clock;
    } catch (error) {
      return;
    }
  }

  show(scene);
  draw();
  setInterval(refresh, 8000);
})();
