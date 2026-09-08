import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  api,
  jobPhaseLabel,
  mediaUrl,
  normalizeKind,
  type Asset,
  type Bundle,
  type ImageJob,
  type Project,
  type Shot,
} from "./api";
import {
  assetsByKind,
  bookAssetsReady,
  deriveGuide,
  pipelineSteps,
  statusLabel,
  stepProgressIndex,
  type FlowGuide,
  type TabName,
} from "./flow";
import { ScoreBadge, ShotCard } from "./ShotCard";
import { useImageJobPoll } from "./useImageJobPoll";

const LLM_BUSY_TITLE = "参考图生成中";

function isAbortError(e: unknown): boolean {
  if (!e || typeof e !== "object") return false;
  const name = (e as { name?: string }).name;
  return name === "AbortError";
}

type ScoreEntry = { score?: number; comment?: string };
type ScoreCounts = { good: number; ok: number; bad: number; none: number };

function scoreBand(score: number | null | undefined): "good" | "ok" | "bad" | "none" {
  if (score === null || score === undefined || Number.isNaN(score)) return "none";
  if (score > 80) return "good";
  if (score >= 60) return "ok";
  return "bad";
}

function emptyScoreCounts(): ScoreCounts {
  return { good: 0, ok: 0, bad: 0, none: 0 };
}

function countAssetScores(assets: Asset[], kind: string): ScoreCounts {
  const fields =
    kind === "character" ? (["full", "half"] as const) : kind === "scene" ? (["far", "near"] as const) : (["image"] as const);
  const counts = emptyScoreCounts();
  for (const a of assets) {
    for (const field of fields) {
      const path =
        field === "full"
          ? a.full_path
          : field === "half"
            ? a.half_path
            : field === "far"
              ? a.far_path
              : field === "near"
                ? a.near_path
                : a.image_path;
      if (!path) continue;
      const entry = a.image_scores?.[field] as ScoreEntry | undefined;
      const band = scoreBand(entry?.score);
      counts[band] += 1;
    }
  }
  return counts;
}

function countShotScores(shots: Shot[]): ScoreCounts {
  const counts = emptyScoreCounts();
  for (const s of shots) {
    if (!s.first_frame_path) continue;
    counts[scoreBand(s.first_frame_score)] += 1;
  }
  return counts;
}

function ScoreSummary({ counts }: { counts: ScoreCounts }) {
  return (
    <div className="score-summary" data-testid="score-summary">
      <span className="score-chip band-good">较好：{counts.good}</span>
      <span className="score-sep">；</span>
      <span className="score-chip band-ok">一般：{counts.ok}</span>
      <span className="score-sep">；</span>
      <span className="score-chip band-bad">较差：{counts.bad}</span>
      <span className="score-sep">；</span>
      <span className="score-chip band-none">未评估：{counts.none}</span>
    </div>
  );
}

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [tab, setTab] = useState<TabName>("全书资产");
  const [chapterId, setChapterId] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [title, setTitle] = useState("");
  const [style, setStyle] = useState("半写实、东方江湖、电影布光、16:9");
  const [text, setText] = useState("");
  const [keepId, setKeepId] = useState("");
  const [dropId, setDropId] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const [aborting, setAborting] = useState(false);
  const bundleRef = useRef<Bundle | null>(null);
  bundleRef.current = bundle;

  const {
    imageJobs,
    setImageJobs,
    imageBatch,
    imageJobsActiveRef,
    prevActiveCountRef,
    pollImageJobsRef,
    noteImageBatch,
    clearBatchTracking,
  } = useImageJobPoll(
    bundle?.project.id,
    bundle?.active_image_jobs,
    () => bundleRef.current,
    setBundle,
  );

  async function refreshList() {
    setProjects(await api.list());
  }
  useEffect(() => {
    refreshList().catch((e) => setError(String(e)));
  }, []);

  const imageBusy = imageJobs.length > 0;
  const llmBlocked = imageBusy;

  const chapter = bundle?.chapters.find((c) => c.id === chapterId) || bundle?.chapters[0];
  const chapterShots = useMemo(
    () => (bundle?.shots || []).filter((s) => s.chapter_id === (chapter?.id || "")).sort((a, b) => a.order_index - b.order_index),
    [bundle, chapter],
  );
  const guide = useMemo(
    () => (bundle ? deriveGuide(bundle, chapter, chapterShots) : null),
    [bundle, chapter, chapterShots],
  );

  async function run(label: string, job: (signal: AbortSignal) => Promise<void>) {
    const ac = new AbortController();
    abortRef.current = ac;
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await job(ac.signal);
    } catch (e) {
      if (isAbortError(e)) {
        setNotice("已终止");
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      if (abortRef.current === ac) abortRef.current = null;
      setBusy("");
    }
  }

  async function abortWork() {
    setAborting(true);
    setNotice("");
    try {
      abortRef.current?.abort();
      // Image mutex is global: cancel every project's active jobs, not only the open one.
      const all = await api.cancelAllImageJobs();
      setImageJobs([]);
      clearBatchTracking();
      if (bundle) {
        try {
          setBundle(await api.get(bundle.project.id));
        } catch {
          /* ignore refresh errors after cancel */
        }
      }
      setNotice(all.cancelled > 0 ? `已终止参考图任务（${all.cancelled}）` : "已终止");
      setBusy("");
      setError("");
    } catch (e) {
      if (!isAbortError(e)) setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAborting(false);
    }
  }

  function selectChapter(id: string, nextTab: TabName = "原文") {
    setChapterId(id);
    setTab(nextTab);
    const pid = bundle?.project.id;
    if (!pid) return;
    const existing = bundle?.chapters.find((c) => c.id === id);
    if (existing && existing.text != null && existing.text !== "") return;
    void api
      .getChapter(pid, id)
      .then((full) => {
        setBundle((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            chapters: prev.chapters.map((c) => (c.id === id ? { ...c, ...full } : c)),
          };
        });
      })
      .catch(() => {
        /* GET chapter may be unavailable until backend ships slim-bundle support */
      });
  }

  async function actOnGuide(g: FlowGuide) {
    if (!bundle) {
      if (g.tab) setTab(g.tab);
      return;
    }
    const p = bundle.project;
    if (g.step === "style") {
      setSettingsOpen(true);
      await run("保存设置", async (signal) => setBundle(await api.patch(p.id, bundle.project, { signal })));
      return;
    }
    if (g.step === "generate_assets") {
      await run("一键生成全书资产", async (signal) => {
        setBundle(await api.generateAssets(p.id, true, { signal }));
        setTab("全书资产");
      });
      return;
    }
    if (g.step === "upload") {
      setTab("全书资产");
      return;
    }
    if (g.step === "storyboard") {
      if (!chapter) {
        setTab("原文");
        return;
      }
      if (!bookAssetsReady(bundle)) {
        setTab("全书资产");
        return;
      }
      await run("生成分镜", async (signal) => {
        setBundle(await api.storyboard(p.id, chapter.id, overwrite, { signal }));
        setTab("分镜");
      });
      return;
    }
    if (g.step === "review") {
      setTab(g.tab || "分镜");
      return;
    }
    if (g.step === "export") {
      await run("导出", async () => {
        const out = await api.export(p.id);
        alert(`已导出到 ${out.path}`);
      });
      return;
    }
    if (g.step === "next_chapter" && chapter) {
      const next = bundle.chapters
        .slice()
        .sort((a, b) => a.index - b.index)
        .find((c) => c.index > chapter.index && c.status !== "storyboarded");
      if (next) selectChapter(next.id, "原文");
    }
  }

  if (!bundle) {
    return (
      <div className="shell">
        <div className="atmosphere" aria-hidden />
        <div className="app">
          <header className="topbar">
            <div>
              <div className="kicker">NOVEL → STORYBOARD</div>
              <div className="brand">novel<span>2</span>Lens</div>
              <p className="lede">把小说变成可出图、可出视频的分镜策划包。按章节推进，每一步都有明确下一步。</p>
            </div>
          </header>

          <ol className="home-steps">
            <li><strong>1. 导入小说</strong><span>粘贴或上传整本 TXT，按章切分</span></li>
            <li><strong>2. 一键生成全书资产</strong><span>人物形象 / 核心场景 / 核心物品，无需按章确认</span></li>
            <li><strong>3. 上传参考图</strong><span>人物半身+全身；场景/物品各一张</span></li>
            <li><strong>4. 按章出分镜并导出</strong><span>首帧双提示词 + H3 脚本</span></li>
          </ol>

          {error && <p className="error banner-error">{error}</p>}
          {notice && <p className="hint banner-notice">{notice}</p>}
          {(busy || aborting) && (
            <p className="busy-line row">
              <span>{busy ? `${busy}…` : "终止中…"}</span>
              {busy ? (
                <button type="button" className="ghost compact" data-testid="btn-abort" disabled={aborting} onClick={() => abortWork()}>
                  {aborting ? "终止中…" : "终止"}
                </button>
              ) : null}
            </p>
          )}

          <section className="panel create-panel">
            <div className="panel-head">
              <h2>新建项目</h2>
              <p className="hint">导入后进入项目，点「一键生成全书资产」扫描人物 / 场景 / 物品。</p>
            </div>
            <div className="stack">
              <label>书名</label>
              <input data-testid="new-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：青川渡" />
              <label>项目画风（必填）</label>
              <input
                data-testid="new-style"
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                placeholder="例如：半写实、东方江湖、电影布光、16:9"
                required
              />
              {!style.trim() ? <p className="hint warn-text">请填写项目画风后再创建。</p> : null}
              <label>粘贴正文</label>
              <textarea data-testid="new-text" value={text} onChange={(e) => setText(e.target.value)} placeholder="粘贴小说全文，或使用下方上传" />
              <div className="row actions">
                <button
                  data-testid="btn-create"
                  className="primary"
                  disabled={!!busy || !style.trim()}
                  onClick={() =>
                    run("创建", async (signal) => {
                      const data = await api.create({ title: title || "未命名小说", text, style: style.trim() }, { signal });
                      setBundle(data);
                      setChapterId(data.chapters[0]?.id || "");
                      setTab("全书资产");
                      await refreshList();
                    })
                  }
                >
                  粘贴创建并进入
                </button>
                <label className={`file-btn ${!style.trim() || busy ? "disabled" : ""}`}>
                  上传 txt 进入
                  <input
                    data-testid="file-novel"
                    type="file"
                    accept=".txt,.md,.text"
                    disabled={!!busy || !style.trim()}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      if (!style.trim()) {
                        setError("项目画风不能为空");
                        return;
                      }
                      run("上传", async (signal) => {
                        const data = await api.upload(title || file.name.replace(/\.[^.]+$/, ""), style.trim(), file, { signal });
                        setBundle(data);
                        setChapterId(data.chapters[0]?.id || "");
                        setTab("全书资产");
                        await refreshList();
                      });
                    }}
                  />
                </label>
              </div>
            </div>
          </section>

          {projects.length > 0 && (
            <section className="panel">
              <div className="panel-head">
                <h2>已有项目</h2>
                <p className="hint">打开后会根据章节状态告诉你下一步该做什么。</p>
              </div>
              <div className="project-grid">
                {projects.map((p) => (
                  <article className="project-card" key={p.id}>
                    <h3>{p.title}</h3>
                    <p className="muted">{p.style || "未设画风"}</p>
                    <div className="row">
                      <button
                        className="primary"
                        data-testid={`btn-open-${p.title}`}
                        onClick={() =>
                          run("打开", async () => {
                            const data = await api.get(p.id);
                            setBundle(data);
                            setChapterId(data.chapters[0]?.id || "");
                            setTab("原文");
                          })
                        }
                      >
                        继续编辑
                      </button>
                      <button
                        className="danger"
                        data-testid={`btn-delete-${p.title}`}
                        onClick={() =>
                          run("删除", async () => {
                            await api.remove(p.id);
                            await refreshList();
                          })
                        }
                      >
                        删除
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    );
  }

  const p = bundle.project;
  const progress = guide ? stepProgressIndex(guide.step) : 0;

  return (
    <div className="shell">
      <div className="atmosphere" aria-hidden />
      <div className="app workspace-app">
        <header className="topbar compact">
          <div>
            <div className="brand small">novel<span>2</span>Lens</div>
            <div className="sub">{p.title}</div>
          </div>
          <div className="row">
            {(busy || imageBusy || aborting || (error && error.includes("参考图生成中"))) && (
              <>
                {busy ? <span className="busy-line">{busy}…</span> : null}
                {!busy && error?.includes("参考图生成中") ? (
                  <span className="busy-line">其他项目参考图任务占用中</span>
                ) : null}
                <button
                  type="button"
                  className="ghost compact"
                  data-testid="btn-abort"
                  disabled={aborting}
                  onClick={() => abortWork()}
                >
                  {aborting ? "终止中…" : "终止"}
                </button>
              </>
            )}
            <button className="ghost" onClick={() => setSettingsOpen((v) => !v)}>
              {settingsOpen ? "收起设置" : "模型 / 画风"}
            </button>
            <button className="ghost" data-testid="btn-back" onClick={() => { setBundle(null); refreshList(); }}>
              返回列表
            </button>
          </div>
        </header>

        {error && <p className="error banner-error">{error}</p>}
        {notice && <p className="hint banner-notice">{notice}</p>}
        {chapter?.last_error && <p className="error banner-error">本章错误：{chapter.last_error}</p>}

        <nav className="pipeline" aria-label="操作流程">
          {pipelineSteps().map((s, i) => (
            <div key={s.id} className={`pipe-step ${i < progress ? "done" : ""} ${i === progress ? "current" : ""}`}>
              <span className="pipe-num">{i + 1}</span>
              <span className="pipe-label">{s.label}</span>
            </div>
          ))}
        </nav>

        {guide && (
          <section className="coach" data-testid="coach-panel">
            <div className="coach-copy">
              <div className="coach-title">{guide.title}</div>
              <p className="coach-tip">{guide.tip}</p>
            </div>
            <button
              className="primary coach-cta"
              data-testid="btn-coach-cta"
              disabled={!!busy || llmBlocked}
              title={llmBlocked ? LLM_BUSY_TITLE : undefined}
              onClick={() => actOnGuide(guide)}
            >
              {guide.cta}
            </button>
          </section>
        )}

        {settingsOpen && (
          <section className="panel settings-panel">
            <div className="panel-head">
              <h2>画风与模型</h2>
              <p className="hint">主模型默认 Flash-Next（:8080）。未就绪时可降级到 Ollama。</p>
            </div>
            <div className="settings-grid">
              <div className="stack">
                <label>画风</label>
                <input data-testid="proj-style" value={p.style} onChange={(e) => setBundle({ ...bundle, project: { ...p, style: e.target.value } })} />
              </div>
              <div className="stack">
                <label>主模型地址</label>
                <input value={p.llm_base_url} onChange={(e) => setBundle({ ...bundle, project: { ...p, llm_base_url: e.target.value } })} />
              </div>
              <div className="stack">
                <label>主模型名</label>
                <input value={p.llm_model} onChange={(e) => setBundle({ ...bundle, project: { ...p, llm_model: e.target.value } })} />
              </div>
              <div className="stack">
                <label>降级地址</label>
                <input value={p.fallback_base_url} onChange={(e) => setBundle({ ...bundle, project: { ...p, fallback_base_url: e.target.value } })} />
              </div>
              <div className="stack">
                <label>降级模型</label>
                <input value={p.fallback_model} onChange={(e) => setBundle({ ...bundle, project: { ...p, fallback_model: e.target.value } })} />
              </div>
            </div>
            <div className="row actions">
              <label className="check">
                <input type="checkbox" checked={p.allow_fallback} onChange={(e) => setBundle({ ...bundle, project: { ...p, allow_fallback: e.target.checked } })} />
                允许降级
              </label>
              <button data-testid="btn-save-settings" className="primary" onClick={() => run("保存设置", async (signal) => setBundle(await api.patch(p.id, bundle.project, { signal })))}>
                保存设置
              </button>
              <button
                data-testid="btn-prescan"
                className="primary"
                disabled={!!busy || llmBlocked}
                title={llmBlocked ? LLM_BUSY_TITLE : undefined}
                onClick={() =>
                  run("一键生成全书资产", async (signal) => {
                    setBundle(await api.generateAssets(p.id, true, { signal }));
                    setTab("全书资产");
                  })
                }
              >
                一键生成全书资产
              </button>
              <button
                data-testid="btn-export"
                disabled={!!busy}
                onClick={() =>
                  run("导出", async () => {
                    const out = await api.export(p.id);
                    alert(`已导出到 ${out.path}`);
                  })
                }
              >
                导出 JSON
              </button>
            </div>
          </section>
        )}

        <div className="workspace">
          <aside className="rail">
            <div className="rail-title">章节进度</div>
            <p className="hint tight">选中一章，按顶部流程逐步完成。</p>
            {bundle.chapters.map((c) => (
              <button
                key={c.id}
                className={c.id === chapter?.id ? "active" : ""}
                onClick={() => selectChapter(c.id, guide?.tab || "原文")}
              >
                <span className={`dot ${c.status}`} />
                <span className="chap-meta">
                  <span className="chap-name">{c.title}</span>
                  <span className="chap-status">{statusLabel(c.status)}{c.used_fallback_llm ? " ·降级" : ""}</span>
                </span>
              </button>
            ))}
          </aside>

          <main className="main-pane">
            <div className="toolbar">
              <div className="tabs">
                {(["原文", "全书资产", "分镜"] as const).map((name) => (
                  <button key={name} data-testid={`tab-${name}`} className={tab === name ? "active" : ""} onClick={() => setTab(name)}>
                    {name}
                  </button>
                ))}
              </div>
              <div className="row">
                <button
                  data-testid="btn-generate-assets"
                  className={guide?.step === "generate_assets" ? "primary" : ""}
                  disabled={!!busy || llmBlocked}
                  title={llmBlocked ? LLM_BUSY_TITLE : undefined}
                  onClick={() =>
                    run("一键生成全书资产", async (signal) => {
                      setBundle(await api.generateAssets(p.id, true, { signal }));
                      setTab("全书资产");
                    })
                  }
                >
                  一键生成全书资产
                </button>
                <label className="check overwrite-check">
                  <input data-testid="overwrite" type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
                  覆盖已有分镜
                </label>
                <button
                  data-testid="btn-storyboard"
                  className={guide?.step === "storyboard" ? "primary" : ""}
                  disabled={!!busy || llmBlocked || !chapter || !bookAssetsReady(bundle)}
                  title={llmBlocked ? LLM_BUSY_TITLE : undefined}
                  onClick={() =>
                    run("生成分镜", async (signal) => {
                      setBundle(await api.storyboard(p.id, chapter!.id, overwrite, { signal }));
                      setTab("分镜");
                    })
                  }
                >
                  生成本章分镜
                </button>
                <button
                  data-testid="btn-storyboard-all"
                  disabled={!!busy || llmBlocked || !bookAssetsReady(bundle) || !bundle.chapters.length}
                  title={llmBlocked ? LLM_BUSY_TITLE : undefined}
                  onClick={() =>
                    run("生成全部章节分镜", async (signal) => {
                      const next = await api.storyboardAll(p.id, overwrite, { signal });
                      setBundle(next);
                      setTab("分镜");
                      if (next.cancelled) return;
                      const gen = next.generated?.length ?? 0;
                      const skip = next.skipped?.length ?? 0;
                      const errs = next.errors || [];
                      if (errs.length) {
                        alert(
                          `完成 ${gen} 章，跳过 ${skip} 章；部分失败：\n${errs.slice(0, 8).join("\n")}`,
                        );
                      } else {
                        setNotice(`全部章节分镜：生成 ${gen} 章，跳过 ${skip} 章`);
                      }
                    })
                  }
                >
                  一键生成全部章节分镜
                </button>
                <button
                  data-testid="btn-chapter-first-frames"
                  disabled={!!busy || imageJobs.length > 0 || !chapter || chapterShots.length === 0}
                  onClick={() =>
                    run("生成本章首帧", async (signal) => {
                      const next = await api.generateChapterFirstFrames(p.id, chapter!.id, { signal });
                      const jobs = next.jobs || [];
                      const bid = next.batch_id || jobs[0]?.batch_id || "";
                      if (bid) noteImageBatch(bid, jobs.length || next.queued || 1);
                      if (jobs.length) {
                        setImageJobs(jobs);
                        imageJobsActiveRef.current = true;
                        if (prevActiveCountRef.current === 0) prevActiveCountRef.current = jobs.length;
                        pollImageJobsRef.current?.();
                      }
                      setBundle(next);
                      setTab("分镜");
                    })
                  }
                >
                  一键生成本章首帧
                </button>
                <button
                  data-testid="btn-project-first-frames"
                  disabled={!!busy || imageJobs.length > 0 || !(bundle.shots?.length)}
                  onClick={() =>
                    run("生成全部首帧", async (signal) => {
                      const next = await api.generateProjectFirstFrames(p.id, { signal });
                      const jobs = next.jobs || [];
                      const bid = next.batch_id || jobs[0]?.batch_id || "";
                      if (bid) noteImageBatch(bid, jobs.length || next.queued || 1);
                      if (jobs.length) {
                        setImageJobs(jobs);
                        imageJobsActiveRef.current = true;
                        if (prevActiveCountRef.current === 0) prevActiveCountRef.current = jobs.length;
                        pollImageJobsRef.current?.();
                      }
                      setBundle(next);
                      setTab("分镜");
                    })
                  }
                >
                  一键生成全部首帧
                </button>
              </div>
            </div>

            {tab === "原文" && chapter && (
              <section className="panel">
                <div className="panel-head">
                  <h2>{chapter.title}</h2>
                  <p className="hint">全书资产在「全书资产」页一键生成；本章只需生成分镜。</p>
                </div>
                <article className="original">{chapter.text || ""}</article>
              </section>
            )}

            {tab === "全书资产" && (
              <BookAssets
                bundle={bundle}
                busy={!!busy}
                imageJobs={imageJobs}
                imageBatch={imageBatch}
                llmBlocked={llmBlocked}
                keepId={keepId}
                dropId={dropId}
                setKeepId={setKeepId}
                setDropId={setDropId}
                onChange={setBundle}
                onRun={run}
                onBatchQueued={noteImageBatch}
                onBatchCleared={clearBatchTracking}
                onJobsSeen={(jobs) => {
                  setImageJobs(jobs);
                  if (jobs.length) {
                    imageJobsActiveRef.current = true;
                    // Seed prev count so the next poll can detect completion.
                    if (prevActiveCountRef.current === 0) prevActiveCountRef.current = jobs.length;
                  }
                  pollImageJobsRef.current?.();
                }}
              />
            )}

            {tab === "分镜" && (
              <div className="stack">
                {chapterShots.length === 0 ? (
                  <section className="panel empty">
                    <h2>本章还没有分镜</h2>
                    <p className="hint">先点「一键生成全书资产」，再点「生成本章分镜」。无需按章确认资产。</p>
                  </section>
                ) : (
                  <>
                    <section className="panel score-panel-head-wrap">
                      <div className="panel-head score-panel-head">
                        <div>
                          <h2>本章首帧评分</h2>
                          <ScoreSummary counts={countShotScores(chapterShots)} />
                        </div>
                        <button
                          type="button"
                          className="primary"
                          data-testid="btn-score-first-frames"
                          disabled={!!busy || llmBlocked || !chapterShots.some((s) => s.first_frame_path)}
                          title={llmBlocked ? LLM_BUSY_TITLE : undefined}
                          onClick={() =>
                            run("评估首帧", async (signal) => {
                              const next = await api.scoreImages(p.id, { scope: "shots" }, { signal });
                              setBundle(next);
                              if (next.cancelled) return;
                              if (next.errors?.length) {
                                alert(`评估完成 ${next.scored ?? 0} 张；部分失败：\n${next.errors.slice(0, 5).join("\n")}`);
                              }
                            })
                          }
                        >
                          评估图片
                        </button>
                      </div>
                    </section>
                    {chapterShots.map((shot) => (
                      <ShotCard
                        key={shot.id}
                        shot={shot}
                        assets={bundle.assets}
                        firstFrameJob={imageJobs.find(
                          (j) => j.shot_id === shot.id && j.target_field === "first_frame",
                        )}
                        regenDisabled={!!busy || imageJobs.length > 0 || shot.first_frame_unready}
                        onRegen={() =>
                          run(`重跑镜${shot.order_index}首帧`, async (signal) => {
                            const next = await api.generateShotFirstFrame(p.id, shot.id, { signal });
                            const job = next.job;
                            if (job) {
                              const bid = job.batch_id || job.id;
                              noteImageBatch(bid, 1);
                              setImageJobs([job]);
                              imageJobsActiveRef.current = true;
                              if (prevActiveCountRef.current === 0) prevActiveCountRef.current = 1;
                              pollImageJobsRef.current?.();
                            }
                            setBundle(next);
                          })
                        }
                        onChange={async (next) => {
                          const updated = await api.patchShot(p.id, shot.id, next);
                          setBundle({
                            ...bundle,
                            shots: bundle.shots.map((s) => (s.id === shot.id ? updated : s)),
                          });
                        }}
                      />
                    ))}
                  </>
                )}
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}

function BookAssets({
  bundle, busy, imageJobs, imageBatch, llmBlocked, keepId, dropId, setKeepId, setDropId, onChange, onRun, onBatchQueued, onBatchCleared, onJobsSeen,
}: {
  bundle: Bundle;
  busy: boolean;
  imageJobs: ImageJob[];
  imageBatch: { id: string; total: number } | null;
  llmBlocked: boolean;
  keepId: string;
  dropId: string;
  setKeepId: (v: string) => void;
  setDropId: (v: string) => void;
  onChange: (b: Bundle) => void;
  onRun: (label: string, job: (signal: AbortSignal) => Promise<void>) => void;
  onBatchQueued: (batchId: string, total: number) => void;
  onBatchCleared: () => void;
  onJobsSeen: (jobs: ImageJob[]) => void;
}) {
  const { characters, scenes, props } = assetsByKind(bundle);
  const scan = bundle.project.registry_scan;
  const ready = bookAssetsReady(bundle);
  const [view, setView] = useState<"character" | "scene" | "prop">("character");
  const [outDir, setOutDir] = useState(bundle.project.image_output_dir || "");
  const [cancelBusy, setCancelBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [creating, setCreating] = useState(false);
  useEffect(() => setOutDir(bundle.project.image_output_dir || ""), [bundle.project.image_output_dir]);

  const tabs = [
    { id: "character" as const, label: "人物形象", count: characters.length, empty: "还没有人物。点上方一键生成。", assets: characters },
    { id: "scene" as const, label: "核心场景", count: scenes.length, empty: "还没有核心场景。", assets: scenes },
    { id: "prop" as const, label: "核心物品", count: props.length, empty: "还没有核心物品。", assets: props },
  ];
  const active = tabs.find((t) => t.id === view)!;
  const scoreCounts = useMemo(() => countAssetScores(active.assets, view), [active.assets, view]);
  const imageBusy = imageJobs.length > 0;
  const batchId = imageBatch?.id || imageJobs.find((j) => j.batch_id)?.batch_id || "";
  const total = imageBatch?.total || imageJobs.length;
  const done = Math.max(0, total - imageJobs.length);
  const jobsByAsset = useMemo(() => {
    const map = new Map<string, ImageJob[]>();
    for (const j of imageJobs) {
      const list = map.get(j.asset_id) || [];
      list.push(j);
      map.set(j.asset_id, list);
    }
    return map;
  }, [imageJobs]);

  async function cancelBatch() {
    setCancelBusy(true);
    try {
      const next = await api.cancelProjectImageJobs(bundle.project.id);
      onJobsSeen([]);
      onBatchCleared();
      onChange(next);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setCancelBusy(false);
    }
  }

  return (
    <div className="stack">
      <section className="panel attention" data-testid="book-assets-hero">
        <div className="panel-head">
          <h2>全书资产（正本 TXT）</h2>
          <p className="hint">
            对整本小说扫描人物形象、核心场景、核心物品。生成后自动写入，无需按章确认。
            {scan?.passes?.length
              ? ` 已扫描 ${scan.passes.length} 遍：人物 ${scan.counts?.character ?? characters.length} / 场景 ${scan.counts?.scene ?? scenes.length} / 物品 ${scan.counts?.prop ?? props.length}。`
              : " 尚未生成。"}
          </p>
        </div>
        <div className="row actions">
          <button
            data-testid="btn-one-click-assets"
            className="primary"
            disabled={busy || llmBlocked}
            title={llmBlocked ? LLM_BUSY_TITLE : undefined}
            onClick={() =>
              onRun("一键生成全书资产", async (signal) =>
                onChange(await api.generateAssets(bundle.project.id, true, { signal })),
              )
            }
          >
            {ready ? "重新一键生成全书资产" : "一键生成全书资产"}
          </button>
        </div>
        <div className="stack" style={{ marginTop: "0.85rem" }}>
          <label>参考图保存目录（生成落盘；可填绝对路径）</label>
          <div className="row">
            <input
              data-testid="image-output-dir"
              value={outDir}
              placeholder="默认：项目 data/projects/…/generated"
              onChange={(e) => setOutDir(e.target.value)}
            />
            <button
              disabled={busy}
              onClick={() =>
                onRun("保存图片目录", async (signal) =>
                  onChange(await api.patch(bundle.project.id, { image_output_dir: outDir.trim() }, { signal })),
                )
              }
            >
              保存目录
            </button>
            <button
              data-testid="btn-generate-images"
              className="primary"
              disabled={busy || imageBusy || bundle.assets.length === 0}
              onClick={() =>
                onRun("一键生成参考图", async (signal) => {
                  const next = await api.generateImages(bundle.project.id, { signal });
                  const jobs = next.jobs || [];
                  const bid = next.batch_id || jobs[0]?.batch_id || "";
                  const queued =
                    jobs.length ||
                    (typeof next.image_gen?.queued === "number" ? next.image_gen.queued : 0) ||
                    1;
                  if (bid) onBatchQueued(bid, queued);
                  onJobsSeen(jobs);
                  onChange(next);
                })
              }
            >
              一键生成参考图
            </button>
            {imageBusy ? (
              <>
                <span className="busy-line" data-testid="image-gen-progress">
                  生成中 ({done}/{total})
                </span>
                <button
                  type="button"
                  className="danger"
                  data-testid="btn-cancel-image-batch"
                  disabled={cancelBusy}
                  onClick={() => cancelBatch()}
                >
                  {cancelBusy ? "终止中…" : "终止"}
                </button>
              </>
            ) : null}
          </div>
          <p className="hint">人物：全身 9:16 → 半身 3:4（由全身编辑）。场景远景 16:9 + 近景 3:4，物品 1:1。新图写入参考图目录下的「人物 / 场景 / 物品」。Comfy 按需启动 :8189。</p>
        </div>
      </section>

      <section className="panel" data-testid="asset-kind-switcher">
        <div className="asset-kind-tabs" role="tablist" aria-label="资产类型">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={view === t.id}
              data-testid={`btn-view-${t.id}`}
              className={view === t.id ? "primary" : ""}
              onClick={() => setView(t.id)}
            >
              {t.label}
              <span className="muted"> · {t.count}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel" data-testid={`section-${active.label}`}>
        <div className="panel-head score-panel-head">
          <div>
            <h2>{active.label}</h2>
            <ScoreSummary counts={scoreCounts} />
          </div>
          <button
            type="button"
            className="primary"
            data-testid="btn-score-images"
            disabled={busy || imageBusy || active.assets.length === 0}
            title={imageBusy ? LLM_BUSY_TITLE : undefined}
            onClick={() =>
              onRun("评估图片", async (signal) => {
                const next = await api.scoreImages(
                  bundle.project.id,
                  { scope: "assets", kind: view },
                  { signal },
                );
                onChange(next);
                if (next.cancelled) return;
                if (next.errors?.length) {
                  alert(`评估完成 ${next.scored ?? 0} 张；部分失败：\n${next.errors.slice(0, 5).join("\n")}`);
                }
              })
            }
          >
            {busy ? "评估中…" : "评估图片"}
          </button>
        </div>
        {active.assets.length === 0 ? (
          <p className="hint">{active.empty}</p>
        ) : (
          <div className="asset-rows">
            {active.assets.map((asset) => (
              <AssetCard
                key={asset.id}
                asset={asset}
                projectId={bundle.project.id}
                jobs={jobsByAsset.get(asset.id) || []}
                onUpdated={(next) => {
                  onChange({ ...bundle, assets: bundle.assets.map((a) => (a.id === next.id ? next : a)) });
                }}
                onDeleted={(next) => {
                  onChange(next);
                  onJobsSeen(imageJobs.filter((j) => j.asset_id !== asset.id));
                }}
                onJobsEnqueued={(jobs) => {
                  onJobsSeen([...imageJobs.filter((j) => j.asset_id !== asset.id), ...jobs]);
                  const bid = jobs[0]?.batch_id;
                  if (bid) onBatchQueued(bid, (imageBatch?.id === bid ? imageBatch.total : 0) + jobs.length);
                }}
              />
            ))}
          </div>
        )}
        <div className="panel" style={{ marginTop: "0.75rem" }} data-testid="manual-asset-create">
          <div className="panel-head">
            <h3>新增{active.label}</h3>
            <p className="hint">手动登记名称与描述；保存后可再生成或上传参考图，供分镜首帧按名匹配。</p>
          </div>
          <div className="stack">
            <input
              data-testid="manual-asset-name"
              placeholder="名称"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <textarea
              data-testid="manual-asset-desc"
              placeholder={view === "character" ? "样貌描述（含性别、年龄段、身材）" : "视觉描述"}
              value={newDesc}
              rows={3}
              onChange={(e) => setNewDesc(e.target.value)}
            />
            <button
              data-testid="btn-create-asset"
              className="primary"
              disabled={creating || busy || !newName.trim() || !newDesc.trim()}
              onClick={async () => {
                setCreating(true);
                try {
                  const created = await api.createAsset(bundle.project.id, {
                    kind: view,
                    name: newName.trim(),
                    desc_zh: newDesc.trim(),
                  });
                  onChange({ ...bundle, assets: [...bundle.assets, created] });
                  setNewName("");
                  setNewDesc("");
                } catch (e) {
                  alert(e instanceof Error ? e.message : String(e));
                } finally {
                  setCreating(false);
                }
              }}
            >
              {creating ? "创建中…" : "新增资产"}
            </button>
          </div>
        </div>
      </section>

      {view === "character" && (
        <section className="panel">
          <div className="panel-head">
            <h2>合并角色（可选）</h2>
            <p className="hint">若两个条目其实是同一人，保留一份并合并昵称。</p>
          </div>
          <div className="row">
            <select value={keepId} onChange={(e) => setKeepId(e.target.value)}>
              <option value="">保留资产</option>
              {characters.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
            <select value={dropId} onChange={(e) => setDropId(e.target.value)}>
              <option value="">合并进来并删除</option>
              {characters.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
            <button
              data-testid="btn-merge"
              disabled={!keepId || !dropId || keepId === dropId || llmBlocked}
              title={llmBlocked ? LLM_BUSY_TITLE : undefined}
              onClick={() => onRun("合并", async () => onChange(await api.merge(bundle.project.id, keepId, dropId)))}
            >
              合并角色
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

function AutoTextarea({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const fit = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };

  useLayoutEffect(() => {
    fit();
  }, [value]);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => fit());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <textarea
      ref={ref}
      className={`auto-textarea ${className || ""}`}
      value={value}
      placeholder={placeholder}
      rows={Math.max(2, (value || "").split("\n").length)}
      onChange={(e) => onChange(e.target.value)}
      onInput={fit}
    />
  );
}

function defaultAspectForField(kind: string, field: string): string {
  if (field === "full") return "9:16";
  if (field === "half" || field === "near") return "3:4";
  if (field === "far") return "16:9";
  if (kind === "scene") return "16:9";
  if (kind === "prop" || field === "image") return "1:1";
  return "3:4";
}

function assetReady(kind: string, asset: Asset): boolean {
  if (kind === "character") return Boolean(asset.half_path && asset.full_path);
  if (kind === "scene") return Boolean(asset.near_path || asset.far_path || asset.image_path);
  return Boolean(asset.image_path);
}

function AssetCard({
  asset,
  projectId,
  jobs,
  onUpdated,
  onDeleted,
  onJobsEnqueued,
}: {
  asset: Asset;
  projectId: string;
  jobs: ImageJob[];
  onUpdated: (a: Asset) => void;
  onDeleted: (bundle: Bundle) => void;
  onJobsEnqueued: (jobs: ImageJob[]) => void;
}) {
  const [background, setBackground] = useState(asset.background_zh || "");
  const [desc, setDesc] = useState(asset.desc_zh);
  const [imgBusy, setImgBusy] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [editField, setEditField] = useState<string | undefined>(undefined);
  const [preview, setPreview] = useState<{ src: string; label: string } | null>(null);
  useEffect(() => setBackground(asset.background_zh || ""), [asset.background_zh]);
  useEffect(() => setDesc(asset.desc_zh), [asset.desc_zh]);
  useEffect(() => {
    if (!preview) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPreview(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [preview]);
  const kind = normalizeKind(asset.kind);
  const slotBusy = jobs.length > 0 || !!imgBusy;

  async function upload(field: string, file?: File) {
    if (!file) return;
    onUpdated(await api.uploadAsset(projectId, asset.id, field, file));
  }

  async function saveFields() {
    const patch =
      kind === "character"
        ? { background_zh: background, desc_zh: desc }
        : { desc_zh: desc };
    onUpdated(await api.patchAsset(projectId, asset.id, patch));
  }

  async function regen(field?: string) {
    setImgBusy(field ? `排队${field}` : "排队参考图");
    try {
      const res = await api.generateAssetImage(projectId, asset.id, field);
      onUpdated(res.asset);
      onJobsEnqueued(res.jobs || (res.job ? [res.job] : []));
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setImgBusy("");
    }
  }

  async function clearImg(field: string) {
    try {
      onUpdated(await api.clearAssetImage(projectId, asset.id, field));
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    }
  }

  async function deleteWholeAsset() {
    if (
      !confirm(
        `确定删除资产「${asset.name}」？\n分镜中的引用会清空，相关图片文件也会删除。`,
      )
    ) {
      return;
    }
    setImgBusy("删除资产");
    try {
      const next = await api.deleteAsset(projectId, asset.id);
      onDeleted(next);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setImgBusy("");
    }
  }

  const ready = assetReady(kind, asset);
  const phaseHints = jobs
    .map((j) => {
      const label = jobPhaseLabel(j);
      const slot = j.target_field ? `${j.target_field}·` : "";
      return label ? `${slot}${label}` : "";
    })
    .filter(Boolean);

  function slotBadge(field: string) {
    const j = jobs.find((x) => x.target_field === field);
    if (!j) return null;
    const label = jobPhaseLabel(j);
    return label ? <span className="slot-badge">{label}</span> : null;
  }

  function renderSlot(opts: {
    field: string;
    label: string;
    path: string;
    wide?: boolean;
  }) {
    const { field, label, path, wide } = opts;
    const scored = asset.image_scores?.[field] as ScoreEntry | undefined;
    return (
      <div className={`thumb-slot ${wide ? "wide-slot" : ""}`} data-field={field}>
        <div className="thumb-with-score">
          {path ? (
            <button
              type="button"
              className="thumb-open"
              title={`查看大图 · ${label}`}
              onClick={() =>
                setPreview({
                  src: mediaUrl(path, asset.media_version),
                  label: `${asset.name} · ${label}`,
                })
              }
            >
              <img
                key={`${field}-${asset.media_version || 0}`}
                className={wide ? "wide" : undefined}
                src={mediaUrl(path, asset.media_version)}
                alt={label}
              />
            </button>
          ) : (
            <div className={`ph ${wide ? "wide" : ""}`}>{label}</div>
          )}
          {path ? <ScoreBadge score={scored?.score} comment={scored?.comment} /> : null}
        </div>
        {slotBadge(field)}
        <div className="thumb-actions">
          <label className="file-btn compact">
            上传
            <input type="file" accept="image/*" onChange={(e) => upload(field, e.target.files?.[0])} />
          </label>
          <button type="button" className="ghost compact" disabled={slotBusy} onClick={() => regen(field)}>
            重生成
          </button>
          <button
            type="button"
            className="ghost compact"
            disabled={slotBusy}
            data-testid={`btn-edit-${field}`}
            onClick={() => {
              setEditField(field);
              setEditOpen(true);
            }}
          >
            编辑
          </button>
          <button type="button" className="ghost compact" disabled={!path || slotBusy} onClick={() => clearImg(field)}>
            删除
          </button>
        </div>
      </div>
    );
  }

  return (
    <article className={`asset-card asset-row ${ready ? "ready" : "need-img"}`} data-kind={kind}>
      <div className="asset-row-main">
        <div className="asset-head">
          <h3>{asset.name}</h3>
          <span className={`pill ${ready ? "ok" : "warn"}`}>{ready ? "图齐" : "缺图"}</span>
          {phaseHints.length > 0 ? <span className="busy-line">{phaseHints.join(" · ")}</span> : null}
          {imgBusy ? <span className="busy-line">{imgBusy}…</span> : null}
        </div>
        <p className="muted">
          {kind === "character" ? "人物" : kind === "scene" ? "场景" : "物品"}
          {asset.refer_as ? ` · ${asset.refer_as}` : ""}
          {asset.age_band ? ` · ${asset.age_band}` : ""}
          {(asset.aliases || []).length > 0 ? ` · 别名 ${(asset.aliases || []).join("、")}` : ""}
        </p>

        {kind === "character" ? (
          <div className="desc-stack">
            <div className="desc-block view-only">
              <label>① 背景与身份<span className="muted"> · 仅查阅</span></label>
              <AutoTextarea
                value={background}
                onChange={setBackground}
                placeholder="出身、身份、与剧情关系……"
              />
            </div>
            <div className="desc-block look-gen">
              <label>② 样貌身材服饰<span className="muted"> · 生图关键 · 必带性别/年龄段/身材</span></label>
              <AutoTextarea
                value={desc}
                onChange={setDesc}
                placeholder="必带：性别：男/女，年龄段：…，身材：…；再写五官、发型、眼睛外形、饰品、衣服样式颜色……不要写情绪/动作/职业"
              />
            </div>
          </div>
        ) : (
          <div className="desc-block look-gen">
            <label>可视化描述</label>
            <AutoTextarea value={desc} onChange={setDesc} />
          </div>
        )}
        <div className="row">
          <button onClick={() => saveFields()}>保存描述</button>
          <button className="primary" disabled={slotBusy} onClick={() => regen()}>
            自动生成全部参考图
          </button>
          <button
            type="button"
            disabled={slotBusy}
            onClick={() => {
              setEditField(undefined);
              setEditOpen(true);
            }}
          >
            编辑生成
          </button>
          <button
            type="button"
            className="danger"
            data-testid="btn-delete-asset"
            disabled={slotBusy}
            onClick={() => deleteWholeAsset()}
          >
            删除资产
          </button>
        </div>
      </div>

      <div className="asset-row-side">
        <div className={`thumbs ${kind === "scene" ? "thumbs-stack" : ""}`}>
          {kind === "character" ? (
            <>
              {renderSlot({ field: "full", label: "全身 9:16", path: asset.full_path })}
              {renderSlot({ field: "half", label: "半身 3:4", path: asset.half_path })}
            </>
          ) : kind === "scene" ? (
            <>
              {renderSlot({
                field: "far",
                label: "远景 16:9",
                path: asset.far_path || "",
                wide: true,
              })}
              {renderSlot({
                field: "near",
                label: "近景 3:4",
                path: asset.near_path || "",
              })}
            </>
          ) : (
            renderSlot({
              field: "image",
              label: "物品 1:1",
              path: asset.image_path,
              wide: true,
            })
          )}
        </div>
      </div>

      {editOpen ? (
        <EditImageModal
          asset={asset}
          kind={kind}
          projectId={projectId}
          initialField={editField}
          onClose={() => {
            setEditOpen(false);
            setEditField(undefined);
          }}
          onQueued={(job) => {
            onJobsEnqueued([job]);
            setEditOpen(false);
            setEditField(undefined);
          }}
        />
      ) : null}

      {preview ? (
        <div
          className="lightbox-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label={preview.label}
          onClick={() => setPreview(null)}
        >
          <button type="button" className="lightbox-close" aria-label="关闭" onClick={() => setPreview(null)}>
            ×
          </button>
          <img
            className="lightbox-img"
            src={preview.src}
            alt={preview.label}
            onClick={(e) => e.stopPropagation()}
          />
          <p className="lightbox-caption" onClick={(e) => e.stopPropagation()}>
            {preview.label}
          </p>
        </div>
      ) : null}
    </article>
  );
}

function EditImageModal({
  asset,
  kind,
  projectId,
  initialField,
  onClose,
  onQueued,
}: {
  asset: Asset;
  kind: string;
  projectId: string;
  initialField?: string;
  onClose: () => void;
  onQueued: (job: ImageJob) => void;
}) {
  const fieldOptions =
    kind === "character"
      ? [
          { id: "full", label: "全身" },
          { id: "half", label: "半身" },
        ]
      : kind === "scene"
        ? [
            { id: "far", label: "远景" },
            { id: "near", label: "近景" },
          ]
        : [{ id: "image", label: "物品图" }];
  const kindLabel = kind === "character" ? "人物" : kind === "scene" ? "场景" : "物品";
  const [targetField, setTargetField] = useState(
    initialField && fieldOptions.some((f) => f.id === initialField) ? initialField : fieldOptions[0].id,
  );
  const [prompt, setPrompt] = useState(asset.desc_zh || "");
  const [files, setFiles] = useState<File[]>([]);
  const [dirFiles, setDirFiles] = useState<{ name: string; path: string; rel?: string; folder?: string }[]>([]);
  const [outDir, setOutDir] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingList, setLoadingList] = useState(true);

  useEffect(() => {
    let stop = false;
    setLoadingList(true);
    api
      .listImageOutputFiles(projectId, kind)
      .then((res) => {
        if (stop) return;
        setDirFiles(res.files || []);
        setOutDir(res.image_output_dir || "");
      })
      .catch(() => {
        if (!stop) setDirFiles([]);
      })
      .finally(() => {
        if (!stop) setLoadingList(false);
      });
    return () => {
      stop = true;
    };
  }, [projectId, kind]);

  function togglePath(path: string) {
    setPicked((prev) => {
      if (prev.includes(path)) return prev.filter((p) => p !== path);
      if (prev.length >= 3) return prev;
      return [...prev, path];
    });
  }

  async function submit() {
    if (!prompt.trim()) {
      alert("请填写编辑提示词");
      return;
    }
    if (picked.length === 0 && files.length === 0) {
      alert("请至少选择或上传一张参考图（最多 3 张）");
      return;
    }
    setLoading(true);
    try {
      const form = new FormData();
      form.set("prompt", prompt.trim());
      form.set("target_field", targetField);
      form.set("aspect", defaultAspectForField(kind, targetField));
      if (picked.length) form.set("ref_paths", JSON.stringify(picked));
      for (const f of files.slice(0, 3 - picked.length)) form.append("files", f);
      const res = await api.editAssetImage(projectId, asset.id, form);
      onQueued(res.job);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label="编辑生成"
        data-testid="edit-image-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="panel-head">
          <h3>编辑 · {asset.name}</h3>
          <p className="hint">
            使用 Qwen Image Edit。从「{kindLabel}」文件夹勾选最多 3 张参考图并填写编辑文字。
            {outDir ? ` 目录：${outDir}\\${kindLabel}` : ""}
          </p>
        </div>
        <div className="stack">
          <label>目标槽位</label>
          <select value={targetField} onChange={(e) => setTargetField(e.target.value)}>
            {fieldOptions.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
          </select>
          <label>编辑提示词</label>
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4} />
          <label>「{kindLabel}」目录参考图（已选 {picked.length}/3）</label>
          {loadingList ? (
            <p className="muted">加载文件列表…</p>
          ) : dirFiles.length === 0 ? (
            <p className="muted">「{kindLabel}」下暂无图片</p>
          ) : (
            <div className="edit-file-list">
              {dirFiles.map((f) => (
                <label key={f.path} className="check edit-file-item">
                  <input
                    type="checkbox"
                    checked={picked.includes(f.path)}
                    disabled={!picked.includes(f.path) && picked.length >= 3}
                    onChange={() => togglePath(f.path)}
                  />
                  <span title={f.path}>{f.rel || f.name}</span>
                </label>
              ))}
            </div>
          )}
          <label>上传本地参考图</label>
          <input
            type="file"
            accept="image/*"
            multiple
            disabled={picked.length >= 3}
            onChange={(e) => setFiles(Array.from(e.target.files || []).slice(0, 3 - picked.length))}
          />
          {picked.length >= 3 ? (
            <p className="muted">已选满 3 张目录参考图，请先取消勾选再上传</p>
          ) : files.length > 0 ? (
            <p className="muted">已选上传 {files.length} 张</p>
          ) : null}
          <div className="row actions">
            <button type="button" className="primary" disabled={loading} onClick={() => submit()}>
              {loading ? "提交中…" : "排队编辑"}
            </button>
            <button type="button" className="ghost" disabled={loading} onClick={onClose}>
              取消
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

