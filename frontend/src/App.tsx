import { useEffect, useMemo, useRef, useState } from "react";
import { api, mediaUrl, normalizeKind, type Asset, type Bundle, type Project, type Shot } from "./api";
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

const CAMERAS = ["固定", "缓慢推近", "缓慢拉远", "慢摇左", "慢摇右", "微仰", "微俯", "轻度跟随左一", "轻度跟随中", "轻度跟随右一"];

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [tab, setTab] = useState<TabName>("全书资产");
  const [chapterId, setChapterId] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [title, setTitle] = useState("");
  const [style, setStyle] = useState("半写实、东方江湖、电影布光、16:9");
  const [text, setText] = useState("");
  const [keepId, setKeepId] = useState("");
  const [dropId, setDropId] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);

  async function refreshList() {
    setProjects(await api.list());
  }
  useEffect(() => {
    refreshList().catch((e) => setError(String(e)));
  }, []);

  const chapter = bundle?.chapters.find((c) => c.id === chapterId) || bundle?.chapters[0];
  const chapterShots = useMemo(
    () => (bundle?.shots || []).filter((s) => s.chapter_id === (chapter?.id || "")).sort((a, b) => a.order_index - b.order_index),
    [bundle, chapter],
  );
  const guide = useMemo(
    () => (bundle ? deriveGuide(bundle, chapter, chapterShots) : null),
    [bundle, chapter, chapterShots],
  );

  async function run(label: string, job: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await job();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  function selectChapter(id: string, nextTab: TabName = "原文") {
    setChapterId(id);
    setTab(nextTab);
  }

  async function actOnGuide(g: FlowGuide) {
    if (!bundle) {
      if (g.tab) setTab(g.tab);
      return;
    }
    const p = bundle.project;
    if (g.step === "style") {
      setSettingsOpen(true);
      await run("保存设置", async () => setBundle(await api.patch(p.id, bundle.project)));
      return;
    }
    if (g.step === "generate_assets") {
      await run("一键生成全书资产", async () => {
        setBundle(await api.generateAssets(p.id, true));
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
      await run("生成分镜", async () => {
        setBundle(await api.storyboard(p.id, chapter.id, overwrite));
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
          {busy && <p className="busy-line">{busy}…</p>}

          <section className="panel create-panel">
            <div className="panel-head">
              <h2>新建项目</h2>
              <p className="hint">导入后进入项目，点「一键生成全书资产」扫描人物 / 场景 / 物品。</p>
            </div>
            <div className="stack">
              <label>书名</label>
              <input data-testid="new-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：青川渡" />
              <label>项目画风</label>
              <input data-testid="new-style" value={style} onChange={(e) => setStyle(e.target.value)} />
              <label>粘贴正文</label>
              <textarea data-testid="new-text" value={text} onChange={(e) => setText(e.target.value)} placeholder="粘贴小说全文，或使用下方上传" />
              <div className="row actions">
                <button
                  data-testid="btn-create"
                  className="primary"
                  disabled={!!busy}
                  onClick={() =>
                    run("创建", async () => {
                      const data = await api.create({ title: title || "未命名小说", text, style });
                      setBundle(data);
                      setChapterId(data.chapters[0]?.id || "");
                      setTab("全书资产");
                      await refreshList();
                    })
                  }
                >
                  粘贴创建并进入
                </button>
                <label className="file-btn">
                  上传 txt 进入
                  <input
                    data-testid="file-novel"
                    type="file"
                    accept=".txt,.md,.text"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      run("上传", async () => {
                        const data = await api.upload(title || file.name.replace(/\.[^.]+$/, ""), style, file);
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
            {busy && <span className="busy-line">{busy}…</span>}
            <button className="ghost" onClick={() => setSettingsOpen((v) => !v)}>
              {settingsOpen ? "收起设置" : "模型 / 画风"}
            </button>
            <button className="ghost" data-testid="btn-back" onClick={() => { setBundle(null); refreshList(); }}>
              返回列表
            </button>
          </div>
        </header>

        {error && <p className="error banner-error">{error}</p>}
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
              disabled={!!busy}
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
              <label className="check">
                <input data-testid="overwrite" type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
                重跑时覆盖已有结果
              </label>
              <button data-testid="btn-save-settings" className="primary" onClick={() => run("保存设置", async () => setBundle(await api.patch(p.id, bundle.project)))}>
                保存设置
              </button>
              <button
                data-testid="btn-prescan"
                className="primary"
                disabled={!!busy}
                onClick={() =>
                  run("一键生成全书资产", async () => {
                    setBundle(await api.generateAssets(p.id, true));
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
                  disabled={!!busy}
                  onClick={() =>
                    run("一键生成全书资产", async () => {
                      setBundle(await api.generateAssets(p.id, true));
                      setTab("全书资产");
                    })
                  }
                >
                  一键生成全书资产
                </button>
                <button
                  data-testid="btn-storyboard"
                  className={guide?.step === "storyboard" ? "primary" : ""}
                  disabled={!!busy || !chapter || !bookAssetsReady(bundle)}
                  onClick={() =>
                    run("生成分镜", async () => {
                      setBundle(await api.storyboard(p.id, chapter!.id, overwrite));
                      setTab("分镜");
                    })
                  }
                >
                  生成本章分镜
                </button>
              </div>
            </div>

            {tab === "原文" && chapter && (
              <section className="panel">
                <div className="panel-head">
                  <h2>{chapter.title}</h2>
                  <p className="hint">全书资产在「全书资产」页一键生成；本章只需生成分镜。</p>
                </div>
                <article className="original">{chapter.text}</article>
              </section>
            )}

            {tab === "全书资产" && (
              <BookAssets
                bundle={bundle}
                busy={!!busy}
                keepId={keepId}
                dropId={dropId}
                setKeepId={setKeepId}
                setDropId={setDropId}
                onChange={setBundle}
                onRun={run}
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
                  chapterShots.map((shot) => (
                    <ShotCard
                      key={shot.id}
                      shot={shot}
                      assets={bundle.assets}
                      onChange={async (next) => {
                        const updated = await api.patchShot(p.id, shot.id, next);
                        setBundle({
                          ...bundle,
                          shots: bundle.shots.map((s) => (s.id === shot.id ? updated : s)),
                        });
                      }}
                    />
                  ))
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
  bundle, busy, keepId, dropId, setKeepId, setDropId, onChange, onRun,
}: {
  bundle: Bundle;
  busy: boolean;
  keepId: string;
  dropId: string;
  setKeepId: (v: string) => void;
  setDropId: (v: string) => void;
  onChange: (b: Bundle) => void;
  onRun: (label: string, job: () => Promise<void>) => void;
}) {
  const { characters, scenes, props } = assetsByKind(bundle);
  const scan = bundle.project.registry_scan;
  const ready = bookAssetsReady(bundle);
  const [view, setView] = useState<"character" | "scene" | "prop">("character");

  const tabs = [
    { id: "character" as const, label: "人物形象", count: characters.length, empty: "还没有人物。点上方一键生成。", assets: characters },
    { id: "scene" as const, label: "核心场景", count: scenes.length, empty: "还没有核心场景。", assets: scenes },
    { id: "prop" as const, label: "核心物品", count: props.length, empty: "还没有核心物品。", assets: props },
  ];
  const active = tabs.find((t) => t.id === view)!;

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
            disabled={busy}
            onClick={() =>
              onRun("一键生成全书资产", async () => onChange(await api.generateAssets(bundle.project.id, true)))
            }
          >
            {ready ? "重新一键生成全书资产" : "一键生成全书资产"}
          </button>
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
        <div className="panel-head">
          <h2>{active.label}</h2>
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
                onUpdated={(next) => {
                  onChange({ ...bundle, assets: bundle.assets.map((a) => (a.id === next.id ? next : a)) });
                }}
              />
            ))}
          </div>
        )}
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
              disabled={!keepId || !dropId || keepId === dropId}
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
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.max(el.scrollHeight, 48)}px`;
  }, [value]);
  return (
    <textarea
      ref={ref}
      className={`auto-textarea ${className || ""}`}
      value={value}
      placeholder={placeholder}
      rows={1}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function AssetCard({ asset, projectId, onUpdated }: { asset: Asset; projectId: string; onUpdated: (a: Asset) => void }) {
  const [background, setBackground] = useState(asset.background_zh || "");
  const [desc, setDesc] = useState(asset.desc_zh);
  useEffect(() => setBackground(asset.background_zh || ""), [asset.background_zh]);
  useEffect(() => setDesc(asset.desc_zh), [asset.desc_zh]);
  const kind = normalizeKind(asset.kind);

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

  const ready =
    kind === "character" ? Boolean(asset.half_path && asset.full_path) : Boolean(asset.image_path);

  return (
    <article className={`asset-card asset-row ${ready ? "ready" : "need-img"}`} data-kind={kind}>
      <div className="asset-row-main">
        <div className="asset-head">
          <h3>{asset.name}</h3>
          <span className={`pill ${ready ? "ok" : "warn"}`}>{ready ? "图齐" : "缺图"}</span>
        </div>
        <p className="muted">
          {kind === "character" ? "人物" : kind === "scene" ? "场景" : "物品"}
          {asset.refer_as ? ` · ${asset.refer_as}` : ""}
          {asset.age_band ? ` · ${asset.age_band}` : ""}
          {(asset.aliases || []).length > 0 ? ` · 别名 ${(asset.aliases || []).join("、")}` : ""}
        </p>

        {kind === "character" ? (
          <div className="desc-cols">
            <div className="desc-block view-only">
              <label>① 背景与身份<span className="muted"> · 仅查阅</span></label>
              <AutoTextarea
                value={background}
                onChange={setBackground}
                placeholder="出身、身份、与剧情关系……"
              />
            </div>
            <div className="desc-block look-gen">
              <label>② 样貌身材服饰<span className="muted"> · 生图关键</span></label>
              <AutoTextarea
                value={desc}
                onChange={setDesc}
                placeholder="五官、发型、身材、衣着……"
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
        </div>
      </div>

      <div className="asset-row-side">
        <div className="thumbs">
          {kind === "character" ? (
            <>
              {asset.half_path ? <img src={mediaUrl(asset.half_path)} alt="半身" /> : <div className="ph">半身</div>}
              {asset.full_path ? <img src={mediaUrl(asset.full_path)} alt="全身" /> : <div className="ph">全身</div>}
            </>
          ) : asset.image_path ? (
            <img className="wide" src={mediaUrl(asset.image_path)} alt={asset.name} />
          ) : (
            <div className="ph wide">参考图</div>
          )}
        </div>
        <div className="row upload-row">
          {kind === "character" ? (
            <>
              <label className="file-btn">半身<input type="file" accept="image/*" onChange={(e) => upload("half", e.target.files?.[0])} /></label>
              <label className="file-btn">全身<input type="file" accept="image/*" onChange={(e) => upload("full", e.target.files?.[0])} /></label>
            </>
          ) : (
            <label className="file-btn">参考图<input type="file" accept="image/*" onChange={(e) => upload("image", e.target.files?.[0])} /></label>
          )}
        </div>
      </div>
    </article>
  );
}

function ShotCard({
  shot,
  assets,
  onChange,
}: {
  shot: Shot;
  assets: Asset[];
  onChange: (patch: Partial<Shot> & { recompile?: boolean }) => Promise<void>;
}) {
  const [local, setLocal] = useState(shot);
  useEffect(() => setLocal(shot), [shot]);
  const scene = assets.find((a) => a.id === shot.scene_asset_id);

  return (
    <article className="shot-card">
      <div className="shot-head">
        <strong>镜 {shot.order_index}</strong>
        <span className="muted">锁 {shot.character_count} 人 · {shot.duration_s}s</span>
        <span className={`pill ${shot.first_frame_unready ? "warn" : "ok"}`}>
          {shot.first_frame_unready ? "首帧未就绪" : "首帧就绪"}
        </span>
      </div>
      {scene?.image_path && <img className="scene-thumb" src={mediaUrl(scene.image_path)} alt="场景" />}
      <div className="settings-grid">
        <div className="stack">
          <label>时长</label>
          <input type="number" min={4} max={15} value={local.duration_s} onChange={(e) => setLocal({ ...local, duration_s: Number(e.target.value) })} />
        </div>
        <div className="stack">
          <label>运镜</label>
          <select value={local.camera} onChange={(e) => setLocal({ ...local, camera: e.target.value })}>
            {CAMERAS.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
      </div>
      <label>运镜细节</label>
      <input value={local.camera_detail} onChange={(e) => setLocal({ ...local, camera_detail: e.target.value })} />
      <label>旁白</label>
      <input value={local.narration} onChange={(e) => setLocal({ ...local, narration: e.target.value })} />
      <label>首帧中文</label>
      <textarea value={local.prompt_zh} onChange={(e) => setLocal({ ...local, prompt_zh: e.target.value })} />
      <label>首帧英文</label>
      <textarea value={local.prompt_en} onChange={(e) => setLocal({ ...local, prompt_en: e.target.value })} />
      <label>H3</label>
      <textarea value={local.h3_prompt} onChange={(e) => setLocal({ ...local, h3_prompt: e.target.value })} />
      <div className="row">
        <button onClick={() => onChange({ ...local, recompile: false })}>保存提示词</button>
        <button className="primary" onClick={() => onChange({ ...local, recompile: true })}>按站位重编译</button>
      </div>
      {shot.source_excerpt && <p className="muted excerpt">原文：{shot.source_excerpt}</p>}
    </article>
  );
}
