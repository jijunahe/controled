(function () {
  const statusEl = document.getElementById("status");
  const swatch = document.getElementById("swatch");
  const briLabel = document.getElementById("bri-label");
  const canvas = document.getElementById("viz");
  const ctx = canvas.getContext("2d");
  const deviceSelect = document.getElementById("device_id");
  const sensitivity = document.getElementById("sensitivity");
  const baseColor = document.getElementById("base_color");
  const bpmInput = document.getElementById("bpm");

  const btnConnect = document.getElementById("btn-connect");
  const btnMic = document.getElementById("btn-mic");
  const btnSim = document.getElementById("btn-sim");
  const btnStop = document.getElementById("btn-stop");

  let ws = null;
  let audioCtx = null;
  let analyser = null;
  let micStream = null;
  let rafId = null;
  let simTimer = null;
  let mode = null; // mic | sim
  let framesOk = 0;
  let lastSend = 0;

  function setStatus(text, ok) {
    statusEl.textContent = text;
    statusEl.className =
      "mt-4 rounded-lg border px-3 py-2 font-mono text-xs " +
      (ok
        ? "border-glow/30 bg-glow/10 text-glow"
        : "border-line bg-ink/60 text-mist");
  }

  function hexToRgb(hex) {
    const h = hex.replace("#", "");
    return [
      parseInt(h.slice(0, 2), 16),
      parseInt(h.slice(2, 4), 16),
      parseInt(h.slice(4, 6), 16),
    ];
  }

  function mixColor(base, energy) {
    const [r, g, b] = hexToRgb(base);
    const boost = Math.min(1, energy);
    return [
      Math.min(255, Math.round(r + (255 - r) * boost * 0.35)),
      Math.min(255, Math.round(g * (0.55 + boost * 0.45))),
      Math.min(255, Math.round(b + (255 - b) * (1 - boost) * 0.2)),
    ];
  }

  function wsUrl(source) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const params = new URLSearchParams({ source });
    if (deviceSelect.value) params.set("device_id", deviceSelect.value);
    return `${proto}://${location.host}/ws/music?${params.toString()}`;
  }

  function sendFrame(col, bri, fx) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const now = performance.now();
    if (now - lastSend < 45) return; // ~22 fps cliente
    lastSend = now;
    const payload = {
      type: "frame",
      on: true,
      bri: Math.max(1, Math.min(255, Math.round(bri))),
      fx: fx || 0,
      transition: 0,
      col,
    };
    ws.send(JSON.stringify(payload));
    swatch.style.background = `rgb(${col[0]},${col[1]},${col[2]})`;
    briLabel.textContent = `bri ${payload.bri}`;
  }

  function drawBars(levels) {
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    const n = levels.length;
    const barW = w / n;
    for (let i = 0; i < n; i++) {
      const v = levels[i];
      const barH = v * h;
      ctx.fillStyle = `hsla(${(i / n) * 280 + 10}, 85%, ${40 + v * 30}%, 0.9)`;
      ctx.fillRect(i * barW, h - barH, barW * 0.7, barH);
    }
  }

  function stopAudio() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
    if (simTimer) clearInterval(simTimer);
    simTimer = null;
    if (micStream) {
      micStream.getTracks().forEach((t) => t.stop());
      micStream = null;
    }
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
    }
    analyser = null;
    mode = null;
  }

  function disconnect() {
    stopAudio();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }));
      ws.close();
    }
    ws = null;
    btnConnect.disabled = false;
    btnMic.disabled = true;
    btnSim.disabled = true;
    btnStop.disabled = true;
    setStatus("Desconectado", false);
  }

  function connect(source) {
    return new Promise((resolve, reject) => {
      if (ws) {
        try {
          ws.close();
        } catch (_) {}
        ws = null;
      }
      setStatus("Conectando…", false);
      ws = new WebSocket(wsUrl(source || "websocket"));
      ws.onopen = () => {
        btnConnect.disabled = true;
        btnMic.disabled = false;
        btnSim.disabled = false;
        btnStop.disabled = false;
      };
      ws.onmessage = (ev) => {
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (msg.type === "ready") {
          setStatus(
            `Listo · IP ${msg.device_ip} · dry_run=${msg.dry_run} · max_fps=${msg.max_fps || "—"}`,
            true
          );
          resolve(msg);
        } else if (msg.type === "ack") {
          framesOk = msg.frames_ok;
          setStatus(
            `Enviando · ok=${msg.frames_ok} drop=${msg.frames_dropped}`,
            true
          );
        } else if (msg.type === "error") {
          setStatus(`Error: ${msg.detail}`, false);
          reject(new Error(msg.detail));
        } else if (msg.type === "stopped") {
          setStatus(`Detenido · frames=${msg.frames_ok}`, false);
        }
      };
      ws.onclose = () => {
        stopAudio();
        btnConnect.disabled = false;
        btnMic.disabled = true;
        btnSim.disabled = true;
        btnStop.disabled = true;
      };
      ws.onerror = () => {
        setStatus("Error de WebSocket", false);
        reject(new Error("ws error"));
      };
    });
  }

  btnConnect.addEventListener("click", () => {
    connect("websocket").catch(() => {});
  });

  btnStop.addEventListener("click", () => disconnect());

  btnMic.addEventListener("click", async () => {
    stopAudio();
    mode = "mic";
    try {
      await connect("mic_wled");
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: false,
      });
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioCtx.createMediaStreamSource(micStream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);

      const loop = () => {
        analyser.getByteFrequencyData(data);
        const bass = average(data, 0, 8);
        const mid = average(data, 8, 40);
        const high = average(data, 40, 90);
        const sens = Number(sensitivity.value) || 1;
        const energy = Math.min(1, ((bass * 1.4 + mid + high * 0.6) / 3 / 255) * sens);
        const levels = [];
        for (let i = 0; i < 32; i++) {
          const idx = Math.floor((i / 32) * data.length);
          levels.push(data[idx] / 255);
        }
        drawBars(levels);
        const col = mixColor(baseColor.value, energy);
        const bri = 40 + energy * 215;
        const fx = energy > 0.75 ? 1 : 0;
        sendFrame(col, bri, fx);
        rafId = requestAnimationFrame(loop);
      };
      loop();
      setStatus("Micrófono activo · enviando frames", true);
    } catch (err) {
      setStatus(`Micrófono no disponible: ${err.message}`, false);
    }
  });

  btnSim.addEventListener("click", async () => {
    stopAudio();
    mode = "sim";
    try {
      await connect("playlist_sim");
    } catch (_) {
      return;
    }
    let t0 = performance.now();
    const tick = () => {
      const bpm = Math.max(60, Number(bpmInput.value) || 120);
      const elapsed = (performance.now() - t0) / 1000;
      const phase = (elapsed * bpm) / 60;
      const beat = Math.pow(Math.max(0, Math.sin(phase * Math.PI * 2)), 8);
      const pulse = 0.25 + beat * 0.75;
      const levels = Array.from({ length: 32 }, (_, i) => {
        const wave = Math.abs(Math.sin(phase * 2 + i * 0.35));
        return Math.min(1, wave * 0.45 + beat * 0.7);
      });
      drawBars(levels);
      const hueShift = (phase * 40) % 360;
      const base = hexToRgb(baseColor.value);
      const col = [
        Math.min(255, Math.round(base[0] * (0.5 + pulse * 0.5) + (hueShift % 80))),
        Math.min(255, Math.round(base[1] * pulse + beat * 40)),
        Math.min(255, Math.round(base[2] * (0.4 + pulse * 0.6))),
      ];
      sendFrame(col, 50 + pulse * 205, beat > 0.6 ? 1 : 0);
    };
    simTimer = setInterval(tick, 50);
    setStatus(`Simulador @ ${bpmInput.value} BPM`, true);
  });

  function average(arr, from, to) {
    let s = 0;
    const end = Math.min(to, arr.length);
    const start = Math.min(from, end);
    if (end <= start) return 0;
    for (let i = start; i < end; i++) s += arr[i];
    return s / (end - start);
  }
})();
