import { useEffect, useState } from "react";
import { jobPhaseLabel, mediaUrl, type Asset, type ImageJob, type Shot, type ShotReference } from "./api";

const CAMERAS = [
  "固定",
  "缓慢推近",
  "缓慢拉远",
  "慢摇左",
  "慢摇右",
  "微仰",
  "微俯",
  "轻度跟随左一",
  "轻度跟随中",
  "轻度跟随右一",
];

function scoreBand(score: number | null | undefined): "good" | "ok" | "bad" | "none" {
  if (score === null || score === undefined || Number.isNaN(score)) return "none";
  if (score > 80) return "good";
  if (score >= 60) return "ok";
  return "bad";
}

export function ScoreBadge({ score, comment }: { score?: number | null; comment?: string }) {
  const band = scoreBand(score ?? null);
  const label = band === "none" ? "未评估" : String(score);
  const tip = band === "none" ? "尚未评估" : comment || `分数 ${score}`;
  return (
    <span className={`score-badge band-${band}`} title={tip} data-testid="score-badge">
      {label}
    </span>
  );
}

const CN_SLOT = ["", "一", "二", "三", "四", "五"];
function cnNum(n: number) {
  return CN_SLOT[n] || String(n);
}

function fallbackShotRefs(shot: Shot, assets: Asset[]): ShotReference[] {
  const byId = Object.fromEntries(assets.map((a) => [a.id, a]));
  const out: ShotReference[] = [];
  const seenChars = new Set<string>();
  const push = (
    image_key: "scene" | "full" | "half" | "prop",
    asset: Asset | undefined,
    opts: { slot?: number; position?: string; note?: string } = {},
  ) => {
    if (!asset) return;
    if ((image_key === "half" || image_key === "full") && seenChars.has(asset.id)) return;
    const path =
      image_key === "half" ? asset.half_path : image_key === "full" ? asset.full_path : asset.image_path;
    const role =
      image_key === "scene"
        ? "核心场景参考图"
        : image_key === "full"
          ? "人物全身图"
          : image_key === "half"
            ? "人物半身图"
            : "核心物品参考图";
    if (image_key === "half" || image_key === "full") seenChars.add(asset.id);
    out.push({
      slot_index: opts.slot ?? null,
      kind: asset.kind,
      image_key,
      image_role: role,
      asset_id: asset.id,
      asset_name: asset.name,
      position: opts.position || "",
      path: path || "",
      uploaded: Boolean(path),
      required: true,
      note: opts.note || "",
      status_zh: path ? "已上传" : "尚未上传",
    });
  };
  for (const slot of shot.slots || []) {
    const asset = byId[String(slot.asset_id || "")];
    const key = String(slot.image_key || "") as "scene" | "full" | "half" | "prop";
    push(key, asset, {
      slot: Number(slot.index) || undefined,
      position: String(slot.position || ""),
      note: key === "half" ? "本镜用半身" : key === "full" ? "本镜用全身" : key === "scene" ? "场景底板" : "",
    });
  }
  if (shot.scene_asset_id && !out.some((r) => r.image_key === "scene")) {
    push("scene", byId[shot.scene_asset_id], { note: "本镜场景" });
  }
  for (const line of shot.lines || []) {
    const asset = byId[line.asset_id];
    const key = (line.image_key === "half" || line.portrait === "half" ? "half" : "full") as "half" | "full";
    push(key, asset, {
      position: line.position,
      note: key === "half" ? "本镜用半身" : "本镜用全身",
    });
  }
  for (const pid of shot.prop_asset_ids || []) {
    if (!out.some((r) => r.asset_id === pid && r.image_key === "prop")) {
      push("prop", byId[pid], { note: "本镜核心物品" });
    }
  }
  return out;
}

export function ShotCard({
  shot,
  assets,
  firstFrameJob,
  regenDisabled,
  onRegen,
  onChange,
}: {
  shot: Shot;
  assets: Asset[];
  firstFrameJob?: ImageJob | null;
  regenDisabled?: boolean;
  onRegen?: () => void;
  onChange: (patch: Partial<Shot> & { recompile?: boolean }) => Promise<void>;
}) {
  const [local, setLocal] = useState(shot);
  useEffect(() => setLocal(shot), [shot]);
  const refs = shot.references?.length ? shot.references : fallbackShotRefs(shot, assets);
  const missing = refs.filter((r) => r.mode !== "text" && !r.uploaded).length;
  const framePhase = firstFrameJob ? jobPhaseLabel(firstFrameJob) : "";

  return (
    <article className="shot-card">
      <div className="shot-head">
        <strong>镜 {shot.order_index}</strong>
        <span className="muted">
          锁 {shot.character_count} 人 · {shot.duration_s}s
        </span>
        <span className={`pill ${shot.first_frame_unready ? "warn" : "ok"}`}>
          {shot.first_frame_unready ? "首帧未就绪" : "首帧就绪"}
        </span>
        {shot.first_frame_path ? <span className="pill ok">已出图</span> : null}
        {framePhase ? <span className="pill warn">{framePhase}</span> : null}
        {onRegen ? (
          <button
            type="button"
            className="primary compact"
            data-testid={`btn-shot-first-frame-${shot.order_index}`}
            disabled={regenDisabled}
            title={
              shot.first_frame_unready
                ? "至少需要一张可用参考图（场景/人物/物品）"
                : shot.first_frame_path
                  ? "覆盖当前首帧重新生成"
                  : "生成本镜首帧"
            }
            onClick={onRegen}
          >
            {shot.first_frame_path ? "重新生成首帧" : "生成首帧"}
          </button>
        ) : null}
      </div>

      {shot.first_frame_path ? (
        <div className="shot-first-frame">
          <div className="thumb-with-score">
            <img
              key={`${shot.id}-${shot.first_frame_version || 0}-${shot.first_frame_path}`}
              src={mediaUrl(shot.first_frame_path, shot.first_frame_version)}
              alt={`镜${shot.order_index}首帧`}
            />
            <ScoreBadge score={shot.first_frame_score} comment={shot.first_frame_score_comment} />
          </div>
        </div>
      ) : null}

      <div className="shot-refs">
        <div className="shot-refs-head">
          <h4>本镜参考图</h4>
          <span className={`pill ${missing ? "warn" : "ok"}`}>
            {missing ? `${missing} 张尚未上传` : "参考图已齐"}
          </span>
        </div>
        <div className="shot-ref-grid">
          {refs.map((ref, i) => (
            <div
              key={`${ref.asset_id}-${ref.image_key}-${i}`}
              className={`shot-ref ${ref.mode === "text" ? "text" : ref.uploaded ? "ok" : "miss"}`}
            >
              {ref.mode === "text" ? (
                <div className="ph text-ph">{(ref.text || "文字描述补足").slice(0, 72)}</div>
              ) : ref.uploaded && ref.path ? (
                <img
                  src={mediaUrl(ref.path, assets.find((a) => a.id === ref.asset_id)?.media_version)}
                  alt={ref.image_role}
                />
              ) : (
                <div className="ph">{ref.status_zh || "尚未上传"}</div>
              )}
              <div className="shot-ref-meta">
                <strong>
                  {ref.slot_index ? `图${cnNum(ref.slot_index)} · ` : ""}
                  {ref.image_role}
                </strong>
                <span>
                  {ref.asset_name}
                  {ref.position ? ` · ${ref.position}` : ""}
                </span>
                {ref.note ? <span className="muted">{ref.note}</span> : null}
                <span className={ref.mode === "text" ? "muted" : ref.uploaded ? "ok-text" : "warn-text"}>
                  {ref.status_zh}
                </span>
              </div>
            </div>
          ))}
          {refs.length === 0 && <p className="muted">本镜暂无绑定参考资产</p>}
        </div>
      </div>

      <div className="settings-grid">
        <div className="stack">
          <label>时长</label>
          <input
            type="number"
            min={4}
            max={15}
            value={local.duration_s}
            onChange={(e) => setLocal({ ...local, duration_s: Number(e.target.value) })}
          />
        </div>
        <div className="stack">
          <label>运镜</label>
          <select value={local.camera} onChange={(e) => setLocal({ ...local, camera: e.target.value })}>
            {CAMERAS.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
      </div>
      <label>运镜细节</label>
      <input
        value={local.camera_detail}
        onChange={(e) => setLocal({ ...local, camera_detail: e.target.value })}
      />
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
        <button className="primary" onClick={() => onChange({ ...local, recompile: true })}>
          按站位重编译
        </button>
      </div>
      {shot.source_excerpt && <p className="muted excerpt">原文：{shot.source_excerpt}</p>}
    </article>
  );
}
