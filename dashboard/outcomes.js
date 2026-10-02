/* Read-only outcome views. All facts come from the recomputed snapshot. */
function figureURL(f, index = 0, download = false) {
  return (
    "/api/figure?id=" +
    encodeURIComponent(f.figure_id) +
    "&file=" +
    index +
    (download ? "&download=1" : "")
  );
}
function figureWord(key) {
  const labels = {
    data: ["结果图", "Data figure"],
    concept: ["结构示意图", "Editable concept"],
    illustration: ["生图示意图", "Generated illustration"],
    brief_draft: ["来自当前图约的 prompt 草稿", "Current brief prompt draft"],
    recorded_current: [
      "已记录，与当前图约一致",
      "Recorded; matches current brief",
    ],
    request_stale: [
      "图约已变，请重新记录生成请求",
      "Brief changed; refresh request",
    ],
    recorded_only: [
      "已记录 prompt，图约未核对",
      "Recorded prompt; brief not verified",
    ],
    incomplete_brief: ["图约未完整填写", "Incomplete brief"],
    not_reviewed: ["尚未评审", "Not reviewed"],
    pending: ["待评审", "Pending review"],
  };
  return labels[key]?.[lang === "zh" ? 0 : 1] || word(key);
}
function resultRows(questions) {
  const rows = [];
  for (const q of questions) {
    const approved = new Set();
    for (const claim of q.writer_claims || [])
      for (const r of claim.results || []) {
        approved.add(r.result_id);
        rows.push({
          question: q.question_id,
          result: r,
          state: tr("写作包引用", "Writer package reference"),
          path: data.question_workbench.source_paths.writer_package,
        });
      }
    for (const output of q.executed_outputs || []) {
      if (approved.has(output.result?.result_id)) continue;
      rows.push({
        question: q.question_id,
        result: output.result,
        state: q.model_source_stale
          ? tr(
              "模型源已变 · 历史运行结果",
              "Model source changed · historical output",
            )
          : output.freshness !== "current"
            ? tr("来源未绑定或已改变", "Source unbound or changed")
            : output.exit_code !== 0
              ? tr("失败执行产物", "Failed run output")
              : output.selected
                ? tr("探索结果 · 已选执行", "Exploratory · selected run")
                : tr("探索结果 · 未选执行", "Exploratory · unselected run"),
        path: output.path,
        receipt: output.receipt_id,
      });
    }
  }
  return rows;
}
function renderOutcomes() {
  const qs = data.question_workbench?.questions || [];
  const fs = data.figures || [];
  const ids = [
    ...new Set([
      ...qs.map((q) => q.question_id),
      ...fs.flatMap((f) => f.question_ids),
    ]),
  ].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const chosen = qs.filter(
    (q) => questionFilter === "all" || q.question_id === questionFilter,
  );
  const figures = fs.filter(
    (f) =>
      questionFilter === "all" ||
      (questionFilter === "unlinked"
        ? !f.question_ids.length
        : f.question_ids.includes(questionFilter)),
  );
  $("content").innerHTML =
    head(
      tr("每问成果", "Question outcomes"),
      tr(
        "从小问到结果、图表和验证，保留每项成果的实际来源。",
        "Results, figures and validation for each question, with their actual sources.",
      ),
    ) +
    `<div class="question-switch"><button data-question="all" aria-pressed="${questionFilter === "all"}">${tr("全部小问", "All questions")}</button>${ids.map((id) => `<button data-question="${esc(id)}" aria-pressed="${questionFilter === id}"><b>${esc(id.toUpperCase())}</b><span>${fs.filter((f) => f.question_ids.includes(id)).length} ${tr("图", "figures")}</span></button>`).join("")}<button data-question="unlinked" aria-pressed="${questionFilter === "unlinked"}">${tr("未关联图", "Unlinked figures")} · ${fs.filter((f) => !f.question_ids.length).length}</button></div>` +
    `<div class="outcome-tabs">${[
      ["all", tr("全部成果", "All outcomes")],
      ["figures", tr("图册", "Figures")],
      ["results", tr("结果", "Results")],
      ["validation", tr("验证与论文边界", "Validation & writing boundaries")],
    ]
      .map(
        ([id, label]) =>
          `<button data-outcome-tab="${id}" aria-pressed="${outcomeTab === id}">${label}</button>`,
      )
      .join("")}</div>`;
  if (outcomeTab === "all" || outcomeTab === "results") {
    const results = questionFilter === "unlinked" ? [] : resultRows(chosen);
    $("content").innerHTML +=
      `<div class="section-head"><h2>${tr("结果一览", "Result summary")}</h2><span class="small muted">${results.length} ${tr("条来源记录", "source records")}</span></div>` +
      (results.length
        ? `<div class="result-scroll"><table class="result-table"><thead><tr><th>${tr("小问 / 指标", "Question / metric")}</th><th>${tr("数值 / 单位", "Value / unit")}</th><th>${tr("使用边界与来源", "Boundary & source")}</th></tr></thead><tbody>${results.map((r) => `<tr><td><b>${esc(r.question.toUpperCase())}</b><br>${esc(r.result?.name || r.result?.result_id || "—")}</td><td><span class="number">${esc(r.result?.display_value ?? r.result?.value ?? "—")}</span> ${esc(r.result?.unit || "")}<br><span class="small muted">${esc(r.result?.statistical_definition || "")}</span></td><td><span class="badge">${esc(r.state)}</span><p class="small">${esc(r.result?.boundary || "")}</p><code>${esc(r.path)}</code><br><code>${esc(r.receipt || "")}</code></td></tr>`).join("")}</tbody></table></div>`
        : `<div class="empty">${tr("没有明确关联的结果。先完成真实执行并登记来源。", "No explicitly linked results. Run the model and register its sources.")}</div>`) +
      `<p class="outcome-note small">${tr("探索结果用于排查和比较；进入论文仍须满足冻结、验证及写作证据要求。来源变更时不展示旧回执绑定的数值。", "Explore and compare results here; paper use still requires frozen, validated writer evidence. Changed sources supply no receipt-bound values.")}</p>`;
  }
  if (outcomeTab === "all" || outcomeTab === "figures") {
    $("content").innerHTML +=
      `<div class="section-head"><h2>${tr("本问图册", "Question figures")}</h2><span class="small muted">${figures.length} ${tr("项图约", "figure briefs")}</span></div>` +
      (figures.length
        ? `<div class="atlas">${figures
            .map((f) => {
              const index = f.previews.findIndex((p) => p.exists && p.raster);
              return `<button class="figure-tile" data-kind="figure" data-id="${esc(f.figure_id)}" aria-pressed="${selection?.kind === "figure" && selection.id === f.figure_id}"><div class="figure-sheet">${index >= 0 ? `<img loading="lazy" src="${figureURL(f, index)}" alt="${esc(f.message || f.figure_id)}">` : `<div class="empty-figure"><strong>${esc(f.figure_id)}</strong>${tr("尚无可预览图片", "No preview image yet")}</div>`}</div><div class="figure-copy"><span class="badge">${esc(figureWord(f.kind))}</span><span class="badge">${esc(f.question_ids.join(" · ") || tr("未关联小问", "Unlinked"))}</span><h2>${esc(f.message || f.purpose || f.figure_id)}</h2><p class="small muted">${esc(f.figure_id)} · ${esc(figureWord(f.review_status))}${f.prompt ? " · " + tr("可复制生图 prompt", "Prompt available") : ""}</p></div></button>`;
            })
            .join("")}</div>`
        : `<div class="empty">${tr("本问还没有图约。通过论文计划的 claim_ids 关联小问；未关联图保留在独立入口。", "No linked figure briefs. Link through paper-plan claims; unlinked briefs remain separate.")}</div>`);
  }
  if (outcomeTab === "all" || outcomeTab === "validation")
    $("content").innerHTML +=
      `<div class="section-head"><h2>${tr("验证与论文边界", "Validation & writing boundaries")}</h2></div>` +
      list(questionFilter === "unlinked" ? [] : chosen, (q) =>
        row(
          "question",
          q.question_id,
          q.question_id.toUpperCase() + " · " + q.task,
          word(q.writer_eligibility),
          q.validation_obligations
            .map((v) => v.obligation_id + "=" + v.status)
            .join(" · "),
        ),
      );
}
function inspectFigure(id) {
  const f = (data.figures || []).find((f) => f.figure_id === id);
  if (!f) return { title: tr("图不可用", "Figure unavailable"), body: "" };
  let body = `<p class="badge">${esc(figureWord(f.kind))}</p><h2>${esc(f.message || f.purpose || tr("图约待填写", "Fill the figure brief"))}</h2><dl><dt>${tr("关联小问", "Linked questions")}</dt><dd>${esc(f.question_ids.join(" · ") || tr("未关联；不能按文件名推断", "Unlinked; filenames supply no question ids"))}</dd><dt>${tr("图注 / 主张", "Caption / claim")}</dt><dd>${esc(f.caption || "—")}</dd><dt>${tr("评审记录", "Review record")}</dt><dd>${esc(figureWord(f.review_status))} · QA ${esc(f.qa_status)}</dd><dt>${tr("实际图文件", "Actual files")}</dt><dd>${f.previews.map((p, i) => `<p><code>${esc(p.path)}</code><br>${esc(p.exists ? word(p.freshness) : tr("尚未生成", "Not produced"))} · ${p.registered ? tr("已登记", "Registered") : tr("图约引用，未登记", "Plan reference, unregistered")}<br>${p.exists ? `<a href="${figureURL(f, i, true)}" download>${tr("下载原文件", "Download original")}</a>` : ""}</p>`).join("") || tr("没有声明图文件", "No declared visual file")}</dd></dl>${f.brief_exists ? `<button data-kind="source" data-id="${esc("figure:" + f.figure_id + ":brief")}">${tr("查看图约", "View figure brief")}</button>` : ""}`;
  if (f.prompt)
    body += `<section class="prompt-panel"><h2>${tr("生图 prompt", "Generation prompt")}</h2><p class="small">${esc(figureWord(f.prompt_state))}<br><code>${esc(f.prompt_source)}</code></p><pre>${esc(f.prompt)}</pre><button class="primary" data-atlas-copy="prompt">${tr("复制完整 prompt", "Copy full prompt")}</button></section><p class="small muted">${tr("先核对比赛 AI 规则。在可用生图工具中粘贴 prompt，生成图片仍需科学、视觉和最终尺寸复核。", "Confirm competition AI rules. Paste into an available tool; scientific, visual and final-size review remain required.")}</p><details><summary>${tr("生成与收回流程", "Generation & collection")}</summary><p class="small">${tr("仅在规则明确允许且工具可用时，先运行请求命令。生成 PNG 后保存到下列路径，再收回、登记 AI 使用并评审。复制不会执行。", "Only if allowed and a tool is available, record the request. Save the PNG at the path below, collect, disclose AI use and review. Copying does not execute.")}</p><pre>${esc(f.request_command.powershell)}</pre><button data-atlas-copy="request">${tr("复制请求命令", "Copy request command")}</button><button data-atlas-copy="request-posix">${tr("复制 bash 请求命令", "Copy bash request")}</button><pre>${esc(f.collect_command.powershell)}</pre><button data-atlas-copy="collect">${tr("复制收回命令", "Copy collection command")}</button></details>`;
  else
    body += `<p class="outcome-note small">${f.kind === "data" ? tr("结果图必须由数据与绘图脚本生成。", "Plot data figures from evidence and code.") : f.kind === "concept" ? tr("结构图保留可编辑源；需要生图替代时，应在图约中明确声明。", "Keep editable concept sources; declare any illustration alternative.") : tr("先完整填写图约并声明图类型，才能提供生图 prompt。", "Fill the brief and declare its route for a generation prompt.")}</p>${f.prompt_error ? `<details><summary>${tr("图约缺项", "Brief diagnostics")}</summary><pre>${esc(f.prompt_error)}</pre></details>` : ""}`;
  if (f.previews.some((p) => p.exists && p.inline))
    $("content").insertAdjacentHTML(
      "beforeend",
      `<section class="gallery-large"><h2>${esc(f.figure_id)} · ${tr("大图预览", "Full preview")}</h2>${f.previews.map((p, i) => (p.exists && p.inline ? `<p class="small muted"><code>${esc(p.path)}</code> · ${esc(word(p.freshness))}</p>${p.raster ? `<img src="${figureURL(f, i)}" alt="${esc(f.message || f.figure_id)}">` : `<iframe src="${figureURL(f, i)}" title="${esc(f.figure_id)} PDF"></iframe>`}` : "")).join("")}</section>`,
    );
  return { title: f.figure_id, body };
}
document.addEventListener("click", async (e) => {
  const button = e.target.closest(
    "[data-question],[data-outcome-tab],[data-atlas-copy]",
  );
  if (!button) return;
  if (button.dataset.atlasCopy) {
    const f = (data.figures || []).find((f) => f.figure_id === selection?.id);
    if (!f) return;
    const key = button.dataset.atlasCopy;
    const text =
      key === "prompt"
        ? f.prompt
        : key === "collect"
          ? f.collect_command.powershell
          : key === "request-posix"
            ? f.request_command.posix
            : f.request_command.powershell;
    try {
      await navigator.clipboard.writeText(text);
      $("notice").textContent =
        key === "prompt"
          ? tr("已复制完整 prompt", "Full prompt copied")
          : tr("已复制完整命令", "Full command copied");
    } catch {
      $("notice").textContent = text;
    }
    return;
  }
  if (button.dataset.question) questionFilter = button.dataset.question;
  if (button.dataset.outcomeTab) outcomeTab = button.dataset.outcomeTab;
  selection = null;
  render();
});
