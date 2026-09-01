(function () {
  "use strict";

  const DURATION = 16.2;
  const MESSAGE_START = 0.75;
  const THINKING_START = 3.05;
  const THINKING_END = 3.88;
  const ACTIVITY_START = 3.48;
  const COLLAPSE_START = 6.72;
  const ANSWER_START = 7.12;
  const FADE_START = 15.32;
  const FADE_END = 16.10;
  const TOOL_STARTS = [3.72, 4.38, 5.03, 5.69];
  const ANSWER_STARTS = [7.18, 8.12, 9.32];

  const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
  const easeOut = (value) => 1 - Math.pow(1 - clamp(value), 3);
  const fade = (time, start, duration) => easeOut((time - start) / duration);
  const setStyles = (element, styles) => Object.assign(element.style, styles);

  const userMessage = document.querySelector("#user-message");
  const thinkingRow = document.querySelector("#thinking-row");
  const activityCard = document.querySelector("#activity-card");
  const activityMeta = document.querySelector("#activity-meta");
  const activitySummary = document.querySelector("#activity-summary");
  const assistantMessage = document.querySelector("#assistant-message");
  const conversationLayer = document.querySelector(".conversation-layer");
  const toolRows = [...document.querySelectorAll(".tool-row")];
  const answerLines = [...document.querySelectorAll(".answer-line")];

  function render(time) {
    const loopTime = ((time % DURATION) + DURATION) % DURATION;
    const overallFade = loopTime < FADE_START ? 1 : 1 - fade(loopTime, FADE_START, FADE_END - FADE_START);

    const messageProgress = fade(loopTime, MESSAGE_START, 0.48);
    setStyles(userMessage, {
      opacity: String(messageProgress * overallFade),
      transform: `translateY(${(1 - messageProgress) * 10}px)`,
    });

    const thinkingProgress = loopTime < THINKING_START
      ? 0
      : loopTime < THINKING_END
        ? fade(loopTime, THINKING_START, 0.25)
        : 1 - fade(loopTime, THINKING_END, 0.25);
    setStyles(thinkingRow, {
      opacity: String(thinkingProgress * overallFade),
      transform: `translateY(${(1 - thinkingProgress) * 4}px)`,
    });

    const activityProgress = fade(loopTime, ACTIVITY_START, 0.34);
    const collapsed = loopTime >= COLLAPSE_START;
    const activityHeight = collapsed ? 35 : 35 + 8 + 25 * 4;
    setStyles(activityCard, {
      height: `${activityHeight}px`,
      opacity: String(activityProgress * overallFade),
      transform: `translateY(${(1 - activityProgress) * 5}px)`,
    });
    activityMeta.textContent = collapsed ? "snapshot local" : "consultando dados locais";
    activitySummary.style.opacity = collapsed ? String(overallFade) : "0";

    toolRows.forEach((row, index) => {
      const rowProgress = fade(loopTime, TOOL_STARTS[index], 0.28);
      const active = loopTime >= TOOL_STARTS[index] && loopTime < TOOL_STARTS[index] + 0.66;
      const done = loopTime >= TOOL_STARTS[index] + 0.66;
      row.classList.toggle("is-active", active);
      row.classList.toggle("is-done", done);
      setStyles(row, {
        opacity: String(rowProgress * (collapsed ? 0 : 1) * overallFade),
        transform: `translateY(${(1 - rowProgress) * 3}px)`,
      });
    });

    const answerProgress = fade(loopTime, ANSWER_START, 0.34);
    setStyles(assistantMessage, {
      opacity: String(answerProgress * overallFade),
      transform: `translateY(${(1 - answerProgress) * 6}px)`,
    });
    answerLines.forEach((line, index) => {
      const lineProgress = fade(loopTime, ANSWER_STARTS[index], 0.4);
      setStyles(line, {
        opacity: String(lineProgress * overallFade),
        transform: `translateY(${(1 - lineProgress) * 4}px)`,
      });
    });

    conversationLayer.style.opacity = String(overallFade);
  }

  let manualTime = null;
  let startedAt = performance.now();

  window.setDemoTime = function (seconds) {
    manualTime = Number(seconds);
    render(manualTime);
  };

  window.resetDemoTime = function () {
    manualTime = null;
    startedAt = performance.now();
  };

  function tick(now) {
    if (manualTime === null) {
      render((now - startedAt) / 1000);
    }
    window.requestAnimationFrame(tick);
  }

  render(0);
  window.requestAnimationFrame(tick);
})();
