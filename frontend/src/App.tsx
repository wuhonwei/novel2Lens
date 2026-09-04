import { useEffect, useMemo, useState } from "react";
import { api, mediaUrl, type Asset, type Bundle, type Chapter, type Project, type Proposal, type Shot } from "./api";

const CAMERAS = ["固定", "缓慢推近", "缓慢拉远", "慢摇左", "慢摇右", "微仰", "微俯", "轻度跟随左一", "轻度跟随中", "轻度跟随右一"];

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [tab, setTab] = useState<"原文" | "资产" | "分镜">("原文");
  const [chapterId, setChapterId] = useState<string>("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [title, setTitle] = useState("");
  const [style, setStyle] = useState("半写实、东方江湖、电影布光、16:9");
  const [text, setText] = useState("");
  const [keepId, setKeepId] = useState("");
  const [dropId, setDropId] = useState("");

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
  const chapterProposals = (bundle?.proposals || []).filter((p) => p.chapter_id === chapter?.id);

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

  if (!bundle) {
    return (
      <div className="app">
        <header className="topbar">
          <div>
            <div className="kicker">TEXT STORYBOARD PLANNER</div>
            <div className="brand">novel<span>2</span>Lens</div>
            <div className="sub">读小说 · 建资产 · 上传参考图 · 写出首帧与 H3 脚本。不调用 Comfy。</div>
          </div>
        </header>
        {error && <p className="error">{error}</p>}
        {busy && <p className="muted">{busy}…</p>}
        <section className="card create home-hero stack">
          <h3>新建项目</h3>
          <label>书名</label>
          <input data-testid="new-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="青川渡" />
          <label>项目画风（必填才能标首帧就绪）</label>
          <input data-testid="new-style" value={style} onChange={(e) => setStyle(e.target.value)} />
          <label>粘贴正文</label>
          <textarea data-testid="new-text" value={text} onChange={(e) => setText(e.target.value)} placeholder="粘贴小说，或下方上传 txt/md" />
          <div className="row">
            <button
              data-testid="btn-create"
              className="primary"
              disabled={!!busy}
              onClick={() =>
                run("创建", async () => {
                  const data = await api.create({ title: title || "未命名小说", text, style });
                  setBundle(data);
                  setChapterId(data.chapters[0]?.id || "");
                  await refreshList();
                })
              }
            >
              粘贴创建
            </button>
            <label className="row">
              上传 txt/md
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
                    await refreshList();
                  });
                }}
              />
            </label>
          </div>
        </section>
        <div className="grid">
          {projects.map((p) => (
            <article className="card" key={p.id}>
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
                    })
                  }
                >
                  打开
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
      </div>
    );
  }

  const p = bundle.project;

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <div className="brand">novel<span>2</span>Lens</div>
          <div className="sub">{p.title}</div>
        </div>
        <div className="row">
          {busy && <span className="muted">{busy}…</span>}
          <button className="ghost" data-testid="btn-back" onClick={() => { setBundle(null); refreshList(); }}>返回列表</button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}

      <section className="card stack" style={{ marginBottom: "1rem" }}>
        <div className="row">
          <div className="stack" style={{ flex: 1 }}>
            <label>画风</label>
            <input data-testid="proj-style" value={p.style} onChange={(e) => setBundle({ ...bundle, project: { ...p, style: e.target.value } })} />
          </div>
          <div className="stack" style={{ flex: 1 }}>
            <label>主模型地址</label>
            <input value={p.llm_base_url} onChange={(e) => setBundle({ ...bundle, project: { ...p, llm_base_url: e.target.value } })} />
          </div>
          <div className="stack">
            <label>主模型名</label>
            <input value={p.llm_model} onChange={(e) => setBundle({ ...bundle, project: { ...p, llm_model: e.target.value } })} />
          </div>
        </div>
        <div className="row">
          <div className="stack" style={{ flex: 1 }}>
            <label>降级地址</label>
            <input value={p.fallback_base_url} onChange={(e) => setBundle({ ...bundle, project: { ...p, fallback_base_url: e.target.value } })} />
          </div>
          <div className="stack">
            <label>降级模型</label>
            <input value={p.fallback_model} onChange={(e) => setBundle({ ...bundle, project: { ...p, fallback_model: e.target.value } })} />
          </div>
          <label className="row">
            <input type="checkbox" checked={p.allow_fallback} onChange={(e) => setBundle({ ...bundle, project: { ...p, allow_fallback: e.target.checked } })} />
            允许降级
          </label>
          <label className="row">
            <input data-testid="overwrite" type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
            重跑覆盖
          </label>
          <button
            data-testid="btn-save-settings"
            onClick={() => run("保存设置", async () => setBundle(await api.patch(p.id, bundle.project)))}
          >
            保存设置
          </button>
          <button data-testid="btn-prescan" disabled={!!busy} onClick={() => run("预扫描", async () => setBundle(await api.prescan(p.id)))}>
            全书预扫描
          </button>
          <button data-testid="btn-export" disabled={!!busy} onClick={() => run("导出", async () => {
            const out = await api.export(p.id);
            alert(`已导出到 ${out.path}`);
          })}>
            导出 JSON
          </button>
        </div>
      </section>

      <div className="workspace">
        <aside className="rail">
          <div className="muted" style={{ marginBottom: 8 }}>章节</div>
          {bundle.chapters.map((c) => (
            <button key={c.id} className={c.id === chapter?.id ? "active" : ""} onClick={() => { setChapterId(c.id); setTab("原文"); }}>
              <span className={`dot ${c.status}`} />
              {c.title}
              {c.used_fallback_llm ? " ·降级" : ""}
            </button>
          ))}
        </aside>
        <main>
          <div className="tabs">
            {(["原文", "资产", "分镜"] as const).map((name) => (
              <button key={name} data-testid={`tab-${name}`} className={tab === name ? "active" : ""} onClick={() => setTab(name)}>{name}</button>
            ))}
            <button
              data-testid="btn-extract"
              className="primary"
              disabled={!!busy || !chapter}
              onClick={() => run("抽取资产", async () => setBundle(await api.extract(p.id, chapter!.id, overwrite)))}
            >
              抽取本章资产
            </button>
            <button
              data-testid="btn-storyboard"
              disabled={!!busy || !chapter}
              onClick={() => run("生成分镜", async () => {
                setBundle(await api.storyboard(p.id, chapter!.id, overwrite));
                setTab("分镜");
              })}
            >
              生成本章分镜
            </button>
          </div>

          {chapter?.last_error && <p className="error">{chapter.last_error}</p>}

          {tab === "原文" && chapter && (
            <article className="original">{chapter.text}</article>
          )}

          {tab === "资产" && (
            <Assets
              bundle={bundle}
              busy={!!busy}
              keepId={keepId}
              dropId={dropId}
              setKeepId={setKeepId}
              setDropId={setDropId}
              onChange={setBundle}
              onRun={run}
              proposals={chapterProposals}
              chapter={chapter}
            />
          )}

          {tab === "分镜" && (
            <div className="stack">
              {chapterShots.length === 0 && <p className="muted">确认资产后点「生成本章分镜」。</p>}
              {chapterShots.map((shot) => (
                <ShotCard key={shot.id} shot={shot} projectId={p.id} assets={bundle.assets} onChange={async (next) => {
                  const updated = await api.patchShot(p.id, shot.id, next);
                  setBundle({
                    ...bundle,
                    shots: bundle.shots.map((s) => (s.id === shot.id ? updated : s)),
                  });
                }} />
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function Assets({
  bundle, busy, keepId, dropId, setKeepId, setDropId, onChange, onRun, proposals, chapter,
}: {
  bundle: Bundle;
  busy: boolean;
  keepId: string;
  dropId: string;
  setKeepId: (v: string) => void;
  setDropId: (v: string) => void;
  onChange: (b: Bundle) => void;
  onRun: (label: string, job: () => Promise<void>) => void;
  proposals: Proposal[];
  chapter?: Chapter;
}) {
  const [drafts, setDrafts] = useState<Proposal[]>(proposals);
  useEffect(() => setDrafts(proposals.map((p) => ({ ...p, accept: true }))), [proposals]);

  return (
    <div>
      {drafts.length > 0 && (
        <div className="banner" data-testid="proposal-banner">
          <strong>本章资产提案，确认后才写入</strong>
          {drafts.map((item, i) => (
            <div className="proposal" key={item.id || i}>
              <label className="row">
                <input type="checkbox" checked={item.accept !== false} onChange={(e) => {
                  const copy = [...drafts];
                  copy[i] = { ...copy[i], accept: e.target.checked };
                  setDrafts(copy);
                }} />
                [{item.kind}] {String(item.action)} · {String(item.name || "")}
              </label>
              <div className="muted">{JSON.stringify(item.appearance || item.desc_zh || "")}</div>
            </div>
          ))}
          <button
            data-testid="btn-confirm"
            className="primary"
            disabled={busy || !chapter}
            onClick={() => onRun("确认资产", async () => onChange(await api.confirm(bundle.project.id, chapter!.id, drafts)))}
          >
            确认写入本章资产
          </button>
        </div>
      )}

      <div className="row" style={{ marginBottom: 12 }}>
        <select value={keepId} onChange={(e) => setKeepId(e.target.value)}>
          <option value="">保留资产</option>
          {bundle.assets.map((a) => <option key={a.id} value={a.id}>{a.kind}:{a.name}</option>)}
        </select>
        <select value={dropId} onChange={(e) => setDropId(e.target.value)}>
          <option value="">合并进来并删除</option>
          {bundle.assets.map((a) => <option key={a.id} value={a.id}>{a.kind}:{a.name}</option>)}
        </select>
        <button
          data-testid="btn-merge"
          disabled={!keepId || !dropId || keepId === dropId}
          onClick={() => onRun("合并", async () => onChange(await api.merge(bundle.project.id, keepId, dropId)))}
        >
          合并角色
        </button>
      </div>

      <div className="asset-grid">
        {bundle.assets.map((asset) => (
          <AssetCard key={asset.id} asset={asset} projectId={bundle.project.id} onUpdated={(next) => {
            onChange({ ...bundle, assets: bundle.assets.map((a) => (a.id === next.id ? next : a)) });
          }} />
        ))}
      </div>
    </div>
  );
}

function AssetCard({ asset, projectId, onUpdated }: { asset: Asset; projectId: string; onUpdated: (a: Asset) => void }) {
  const [desc, setDesc] = useState(asset.desc_zh);
  useEffect(() => setDesc(asset.desc_zh), [asset.desc_zh]);

  async function upload(field: string, file?: File) {
    if (!file) return;
    onUpdated(await api.uploadAsset(projectId, asset.id, field, file));
  }

  return (
    <article className="card">
      <h3>{asset.name} <span className="muted">{asset.kind}{asset.variant_reason ? `/${asset.variant_reason}` : ""}</span></h3>
      <p className="muted">{asset.refer_as} {asset.age_band} {(asset.aliases || []).join("、")}</p>
      <textarea value={desc} onChange={(e) => setDesc(e.target.value)} />
      <div className="row">
        <button onClick={() => api.patchAsset(projectId, asset.id, { desc_zh: desc }).then(onUpdated)}>保存描述</button>
      </div>
      <div className="thumbs">
        {asset.kind === "character" ? (
          <>
            {asset.half_path ? <img src={mediaUrl(asset.half_path)} alt="半身" /> : <div className="ph">半身</div>}
            {asset.full_path ? <img src={mediaUrl(asset.full_path)} alt="全身" /> : <div className="ph">全身</div>}
          </>
        ) : (
          asset.image_path ? <img className="wide" src={mediaUrl(asset.image_path)} alt={asset.name} /> : <div className="ph wide">场景/物品</div>
        )}
      </div>
      <div className="row">
        {asset.kind === "character" ? (
          <>
            <label>半身<input type="file" accept="image/*" onChange={(e) => upload("half", e.target.files?.[0])} /></label>
            <label>全身<input type="file" accept="image/*" onChange={(e) => upload("full", e.target.files?.[0])} /></label>
          </>
        ) : (
          <label>参考图<input type="file" accept="image/*" onChange={(e) => upload("image", e.target.files?.[0])} /></label>
        )}
      </div>
    </article>
  );
}

function ShotCard({ shot, projectId, assets, onChange }: {
  shot: Shot;
  projectId: string;
  assets: Asset[];
  onChange: (patch: Partial<Shot> & { recompile?: boolean }) => Promise<void>;
}) {
  const [local, setLocal] = useState(shot);
  useEffect(() => setLocal(shot), [shot]);
  const scene = assets.find((a) => a.id === shot.scene_asset_id);

  return (
    <article className="card shot">
      <div className="row">
        <strong>镜 {shot.order_index}</strong>
        <span className="muted">锁 {shot.character_count} 人</span>
        {shot.first_frame_unready ? <span className="error">首帧未就绪</span> : <span>首帧就绪</span>}
      </div>
      {scene?.image_path && <img src={mediaUrl(scene.image_path)} alt="场景" style={{ maxWidth: 280, borderRadius: 8 }} />}
      <div className="row">
        <label>时长<input type="number" min={4} max={15} value={local.duration_s} onChange={(e) => setLocal({ ...local, duration_s: Number(e.target.value) })} /></label>
        <label>运镜
          <select value={local.camera} onChange={(e) => setLocal({ ...local, camera: e.target.value })}>
            {CAMERAS.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
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
      <button onClick={() => onChange({ ...local, recompile: false })}>保存提示词</button>
      <button onClick={() => onChange({ ...local, recompile: true })}>按站位重编译</button>
      <p className="muted">原文：{shot.source_excerpt}</p>
    </article>
  );
}
