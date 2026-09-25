(function () {
  const typeSelect = document.getElementById("config_type");
  const sequencePanel = document.getElementById("sequence-panel");
  const staticFields = document.getElementById("static-fields");
  const stepsList = document.getElementById("steps-list");
  const addStepBtn = document.getElementById("add-step");
  const form = document.getElementById("config-form");
  const sequenceJson = document.getElementById("sequence_json");

  const DEFAULT_STEPS = [
    { color: "#ff0000", duration_sec: 3, bri: 160, fx: 0 },
    { color: "#0044ff", duration_sec: 3, bri: 160, fx: 0 },
  ];

  function isSequenceType(value) {
    return value === "sequence" || value === "playlist";
  }

  function toggleMode() {
    const seq = isSequenceType(typeSelect.value);
    sequencePanel.classList.toggle("hidden", !seq);
    // Mantener campos estáticos visibles también en secuencia (brillo/fx por defecto)
    if (seq && stepsList.children.length === 0) {
      DEFAULT_STEPS.forEach((s) => addStep(s));
    }
  }

  function addStep(preset) {
    const data = preset || { color: "#00ff88", duration_sec: 2, bri: 160, fx: 0 };
    const row = document.createElement("div");
    row.className =
      "step-row grid gap-2 sm:grid-cols-[auto_1fr_1fr_1fr_auto] items-end rounded-lg border border-line bg-panel/60 p-3";
    row.innerHTML = `
      <label class="block">
        <span class="mb-1 block text-xs text-mist">Color</span>
        <input type="color" class="step-color h-10 w-14 cursor-pointer rounded border border-line bg-ink p-1" value="${data.color}" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs text-mist">Duración (s)</span>
        <input type="number" min="0.1" step="0.1" class="step-duration field" value="${data.duration_sec}" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs text-mist">Brillo</span>
        <input type="number" min="1" max="255" class="step-bri field" value="${data.bri}" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs text-mist">Efecto fx</span>
        <input type="number" min="0" max="255" class="step-fx field" value="${data.fx}" />
      </label>
      <button type="button" class="remove-step rounded border border-red-500/40 px-2 py-2 text-xs text-red-300 hover:bg-red-500/10">Quitar</button>
    `;
    row.querySelector(".remove-step").addEventListener("click", () => {
      if (stepsList.children.length <= 1) return;
      row.remove();
    });
    stepsList.appendChild(row);
  }

  function collectSteps() {
    return Array.from(stepsList.querySelectorAll(".step-row")).map((row) => ({
      color: row.querySelector(".step-color").value,
      duration_sec: Number(row.querySelector(".step-duration").value || 1),
      bri: Number(row.querySelector(".step-bri").value || 128),
      fx: Number(row.querySelector(".step-fx").value || 0),
    }));
  }

  addStepBtn.addEventListener("click", () => addStep());
  typeSelect.addEventListener("change", toggleMode);

  form.addEventListener("submit", (event) => {
    if (!isSequenceType(typeSelect.value)) {
      sequenceJson.value = "";
      return;
    }
    const steps = collectSteps();
    if (!steps.length) {
      event.preventDefault();
      alert("Agrega al menos un paso a la secuencia.");
      return;
    }
    sequenceJson.value = JSON.stringify(steps);
  });

  toggleMode();
})();
