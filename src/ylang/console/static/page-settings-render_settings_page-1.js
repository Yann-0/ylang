document.querySelectorAll(".model-chip").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.target;
    const input = document.getElementById(target);
    if (input) input.value = btn.dataset.value || "";
    window.ylangLoadingDone?.();
  });
});
function applyPreset(preset) {
  const form = document.getElementById("settingsForm");
  if (!form) return;
  const set = (name, value) => {
    const el = form.elements.namedItem(name);
    if (el instanceof HTMLInputElement) el.value = value;
    if (el instanceof HTMLSelectElement) el.value = value;
  };
  const check = (name, on) => {
    const el = form.elements.namedItem(name);
    if (el instanceof HTMLInputElement && el.type === "checkbox") el.checked = on;
  };
  if (preset === "fast") {
    set("models_improve", "mistral/mistral-small-latest,anthropic/claude-haiku-4-5");
    set("improver_timeout_sec", "8");
    set("learned_template_limit", "1");
    check("improver_critique", false);
  } else {
    set("models_improve", "anthropic/claude-sonnet-5,openai/gpt-5.5,mistral/mistral-medium-latest,mistral/mistral-small-latest");
    set("improver_timeout_sec", "20");
    set("learned_template_limit", "3");
    check("improver_critique", true);
  }
  window.ylangLoadingDone?.();
}
document.getElementById("presetFast")?.addEventListener("click", () => applyPreset("fast"));
document.getElementById("presetQuality")?.addEventListener("click", () => applyPreset("quality"));
{_preferred_picker_script()}
