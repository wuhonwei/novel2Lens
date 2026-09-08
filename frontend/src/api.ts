export type Asset = {
  id: string;
  kind: "character" | "scene" | "prop" | string;
  name: string;
  aliases: string[];
  refer_as: string;
  age_band: string;
  appearance: Record<string, string>;
  background_zh?: string;
  desc_zh: string;
  desc_en: string;
  parent_id: string | null;
  variant_reason: string;
  confirmed: boolean;
  half_path: string;
  full_path: string;
  far_path: string;
  near_path: string;
  image_path: string;
  voice_path: string;
  media_version?: number;
  portrait_ready: boolean;
  created_chapter_id?: string;
  image_scores?: Record<string, { score?: number; comment?: string; updated_at?: string }>;
};

export type ImageJob = {
  id: string;
  project_id: string;
  asset_id: string;
  shot_id?: string;
  kind: string;
  target_field: string;
  status: string;
  phase: string;
  prompt: string;
  error: string;
  batch_id: string;
  payload?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
};

/** Human-readable phase/status for image job badges. */
export function jobPhaseLabel(j: ImageJob): string {
  if (j.phase === "loading_t2i" || j.phase === "ensuring_comfy") return "文生图模型加载中";
  if (j.phase === "loading_edit") return "图片编辑模型加载中";
  if (j.phase?.startsWith("seq_scene")) {
    const m = j.phase.match(/^seq_scene_a(\d+)$/);
    if (m) return `逐层叠加·场景·第${m[1]}轮`;
    return "逐层叠加·场景";
  }
  if (j.phase?.startsWith("seq_prop")) {
    const m = j.phase.match(/^seq_prop(\d+)\/(\d+)_a(\d+)$/);
    if (m) return `逐层叠加·道具${m[1]}/${m[2]}·第${m[3]}轮`;
    return "逐层叠加·道具";
  }
  if (j.phase?.startsWith("seq_rebind_")) {
    const m = j.phase.match(/^seq_rebind_p(\d+)_a(\d+)$/);
    if (m) return `逐层叠加·回绑人物${m[1]}·第${m[2]}轮`;
    return "逐层叠加·回绑身份";
  }
  if (j.phase?.startsWith("seq_p")) {
    const m = j.phase.match(/^seq_p(\d+)\/(\d+)_a(\d+)$/);
    if (m) return `逐层叠加·人物${m[1]}/${m[2]}·第${m[3]}轮`;
    return "逐层叠加·人物";
  }
  if (j.phase === "generating") return "生成中";
  if (j.status === "queued") return "排队中";
  if (j.status === "running") return "生成中";
  if (j.status === "failed") return "失败";
  return "";
}

export type Chapter = {
  id: string;
  index: number;
  title: string;
  /** Omitted from slim project bundles; fetch via getChapter when needed. */
  text?: string;
  status: string;
  used_fallback_llm: boolean;
  last_error: string;
  prescan_done: boolean;
};

export type ShotReference = {
  slot_index: number | null;
  kind: string;
  image_key: string;
  image_role: string;
  asset_id: string;
  asset_name: string;
  position: string;
  path: string;
  uploaded: boolean;
  required: boolean;
  note: string;
  status_zh: string;
  mode?: "image" | "text" | string;
  text?: string;
};

export type Shot = {
  id: string;
  chapter_id: string;
  chapter_title: string;
  order_index: number;
  duration_s: number;
  scene_asset_id: string;
  prop_asset_ids?: string[];
  camera: string;
  camera_detail: string;
  narration: string;
  action: string;
  source_excerpt: string;
  character_count: number;
  first_frame_unready: boolean;
  first_frame_path?: string;
  first_frame_score?: number | null;
  first_frame_score_comment?: string;
  prompt_zh: string;
  prompt_en: string;
  h3_prompt: string;
  background: string;
  slots: Array<Record<string, unknown>>;
  lines: Array<Record<string, string>>;
  half_lock: boolean;
  references?: ShotReference[];
};

export type Proposal = Record<string, unknown> & {
  id: string;
  chapter_id: string;
  action?: string;
  kind?: string;
  name?: string;
};

export type Project = {
  id: string;
  title: string;
  style: string;
  llm_base_url: string;
  llm_model: string;
  fallback_base_url: string;
  fallback_model: string;
  allow_fallback: boolean;
  thinking: string;
  zaoxiang_base_url?: string;
  image_output_dir?: string;
  registry_scan?: {
    passes?: Array<Record<string, unknown>>;
    complete?: boolean;
    counts?: Record<string, number>;
    incomplete?: Array<Record<string, unknown>>;
  };
};

/** Map Chinese / alias kinds to canonical English slots used by upload UI. */
export function normalizeKind(raw: string | undefined | null): "character" | "scene" | "prop" {
  const key = (raw || "").trim().toLowerCase();
  const map: Record<string, "character" | "scene" | "prop"> = {
    character: "character",
    char: "character",
    person: "character",
    people: "character",
    角色: "character",
    人物: "character",
    人名: "character",
    scene: "scene",
    location: "scene",
    place: "scene",
    场景: "scene",
    地点: "scene",
    场所: "scene",
    prop: "prop",
    item: "prop",
    object: "prop",
    物品: "prop",
    道具: "prop",
    信物: "prop",
  };
  if (map[key]) return map[key];
  const cn = (raw || "").trim();
  return map[cn] || "prop";
}

export type Bundle = {
  project: Project;
  chapters: Chapter[];
  assets: Asset[];
  shots: Shot[];
  proposals: Proposal[];
  active_image_jobs?: ImageJob[];
};

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const raw = await res.text();
  let data: unknown = null;
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      data = raw;
    }
  }
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    if (data && typeof data === "object" && data !== null && "detail" in data) {
      const d = (data as { detail: unknown }).detail;
      detail = typeof d === "string" ? d : JSON.stringify(d);
    } else if (typeof data === "string" && data.trim()) {
      detail = data;
    }
    throw new Error(detail);
  }
  return data as T;
}

export type ReqSignal = { signal?: AbortSignal };

export const api = {
  list: () => req<Project[]>("/api/projects"),
  create: (body: { title: string; text: string; style: string }, opts?: ReqSignal) =>
    req<Bundle>("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: opts?.signal,
    }),
  upload: async (title: string, style: string, file: File, opts?: ReqSignal) => {
    const data = new FormData();
    data.set("title", title);
    data.set("style", style);
    data.set("file", file);
    return req<Bundle>("/api/projects/upload", { method: "POST", body: data, signal: opts?.signal });
  },
  get: (id: string, opts?: ReqSignal) => req<Bundle>(`/api/projects/${id}`, { signal: opts?.signal }),
  /** Full chapter including text when list/bundle omits chapter.text. */
  getChapter: (pid: string, cid: string, opts?: ReqSignal) =>
    req<Chapter>(`/api/projects/${pid}/chapters/${cid}`, { signal: opts?.signal }),
  patch: (id: string, body: Partial<Project> & { text?: string }, opts?: ReqSignal) =>
    req<Bundle>(`/api/projects/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: opts?.signal,
    }),
  remove: (id: string) => req<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),
  /** One-click book registry. Prefer stable /prescan; also try /generate-assets. */
  generateAssets: async (id: string, replace = true, opts?: ReqSignal) => {
    const qs = `replace=${replace}`;
    try {
      return await req<Bundle>(`/api/projects/${id}/prescan?${qs}`, { method: "POST", signal: opts?.signal });
    } catch (err) {
      if (opts?.signal?.aborted) throw err;
      const msg = err instanceof Error ? err.message : String(err);
      if (/not found/i.test(msg)) {
        return req<Bundle>(`/api/projects/${id}/generate-assets?${qs}`, {
          method: "POST",
          signal: opts?.signal,
        });
      }
      throw err;
    }
  },
  prescan: (id: string, replace = false, opts?: ReqSignal) =>
    req<Bundle>(`/api/projects/${id}/prescan?replace=${replace}`, { method: "POST", signal: opts?.signal }),
  extract: (pid: string, cid: string, overwrite = false, opts?: ReqSignal) =>
    req<Bundle>(`/api/projects/${pid}/chapters/${cid}/extract?overwrite=${overwrite}`, {
      method: "POST",
      signal: opts?.signal,
    }),
  confirm: (pid: string, cid: string, items: unknown[]) =>
    req<Bundle>(`/api/projects/${pid}/chapters/${cid}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }),
  storyboard: (pid: string, cid: string, overwrite = false, opts?: ReqSignal) =>
    req<Bundle>(`/api/projects/${pid}/chapters/${cid}/storyboard?overwrite=${overwrite}`, {
      method: "POST",
      signal: opts?.signal,
    }),
  storyboardAll: (pid: string, overwrite = false, opts?: ReqSignal) =>
    req<
      Bundle & {
        ok?: boolean;
        cancelled?: boolean;
        generated?: string[];
        skipped?: string[];
        errors?: string[];
      }
    >(`/api/projects/${pid}/storyboard-all?overwrite=${overwrite}`, {
      method: "POST",
      signal: opts?.signal,
    }),
  patchShot: (pid: string, sid: string, body: Partial<Shot> & { recompile?: boolean }) =>
    req<Shot>(`/api/projects/${pid}/shots/${sid}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  patchAsset: (pid: string, aid: string, body: Partial<Asset>) =>
    req<Asset>(`/api/projects/${pid}/assets/${aid}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  createAsset: (
    pid: string,
    body: { kind: string; name: string; desc_zh: string; appearance?: Record<string, unknown> },
  ) =>
    req<Asset>(`/api/projects/${pid}/assets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteAsset: (pid: string, aid: string) =>
    req<Bundle & { ok?: boolean; deleted_id?: string }>(`/api/projects/${pid}/assets/${aid}`, {
      method: "DELETE",
    }),
  merge: (pid: string, keep_id: string, drop_id: string) =>
    req<Bundle>(`/api/projects/${pid}/assets/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keep_id, drop_id }),
    }),
  uploadAsset: async (pid: string, aid: string, field: string, file: File) => {
    const data = new FormData();
    data.set("field", field);
    data.set("file", file);
    return req<Asset>(`/api/projects/${pid}/assets/${aid}/upload`, { method: "POST", body: data });
  },
  generateImages: (pid: string, opts?: ReqSignal) =>
    req<Bundle & { batch_id?: string; jobs?: ImageJob[]; image_gen?: Record<string, unknown> }>(
      `/api/projects/${pid}/generate-images`,
      { method: "POST", signal: opts?.signal },
    ),
  generateChapterFirstFrames: (pid: string, cid: string, opts?: ReqSignal) =>
    req<Bundle & { batch_id?: string; queued?: number; jobs?: ImageJob[]; errors?: string[] }>(
      `/api/projects/${pid}/chapters/${cid}/generate-first-frames`,
      { method: "POST", signal: opts?.signal },
    ),
  generateProjectFirstFrames: (pid: string, opts?: ReqSignal) =>
    req<Bundle & { batch_id?: string; queued?: number; jobs?: ImageJob[]; errors?: string[] }>(
      `/api/projects/${pid}/generate-first-frames`,
      { method: "POST", signal: opts?.signal },
    ),
  generateShotFirstFrame: (pid: string, sid: string, opts?: ReqSignal) =>
    req<Bundle & { job?: ImageJob }>(`/api/projects/${pid}/shots/${sid}/generate-first-frame`, {
      method: "POST",
      signal: opts?.signal,
    }),
  generateAssetImage: (pid: string, aid: string, field?: string, opts?: ReqSignal) => {
    const qs = field ? `?field=${encodeURIComponent(field)}` : "";
    return req<{ ok: boolean; job: ImageJob; jobs: ImageJob[]; asset: Asset }>(
      `/api/projects/${pid}/assets/${aid}/generate-image${qs}`,
      { method: "POST", signal: opts?.signal },
    );
  },
  clearAssetImage: (pid: string, aid: string, field: string) =>
    req<Asset>(`/api/projects/${pid}/assets/${aid}/image?field=${encodeURIComponent(field)}`, { method: "DELETE" }),
  listImageJobs: (pid: string, activeOnly = true) =>
    req<{ jobs: ImageJob[] }>(`/api/projects/${pid}/image-jobs?active_only=${activeOnly}`),
  cancelImageBatch: (pid: string, batchId: string) =>
    req<{ ok: boolean; cancelled: number }>(`/api/projects/${pid}/image-batches/${batchId}/cancel`, { method: "POST" }),
  cancelProjectImageJobs: (pid: string) =>
    req<Bundle & { ok: boolean; cancelled: number }>(`/api/projects/${pid}/image-jobs/cancel`, { method: "POST" }),
  cancelAllImageJobs: () =>
    req<{ ok: boolean; cancelled: number }>(`/api/image-jobs/cancel-all`, { method: "POST" }),
  scoreImages: (
    pid: string,
    body: { scope?: "assets" | "shots" | "all"; kind?: string | null },
    opts?: ReqSignal,
  ) =>
    req<
      Bundle & {
        ok?: boolean;
        cancelled?: boolean;
        scored?: number;
        errors?: string[];
        asset_counts?: { good: number; ok: number; bad: number; none: number };
        shot_counts?: { good: number; ok: number; bad: number; none: number };
      }
    >(`/api/projects/${pid}/score-images`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: opts?.signal,
    }),
  editAssetImage: (pid: string, aid: string, form: FormData, opts?: ReqSignal) =>
    req<{ ok: boolean; job: ImageJob }>(`/api/projects/${pid}/assets/${aid}/edit-image`, {
      method: "POST",
      body: form,
      signal: opts?.signal,
    }),
  listImageOutputFiles: (pid: string, kind?: string | null) => {
    const qs = kind ? `?kind=${encodeURIComponent(kind)}` : "";
    return req<{
      image_output_dir?: string;
      kind?: string | null;
      files: { name: string; path: string; rel?: string; folder?: string }[];
    }>(`/api/projects/${pid}/image-output-files${qs}`);
  },
  export: (pid: string) => req<{ document: unknown; markdown: string; path: string }>(`/api/projects/${pid}/export`, { method: "POST" }),
};

export function mediaUrl(path: string, version?: number | string | null) {
  if (!path) return "";
  const base = `/media/${path}`;
  if (version === undefined || version === null || version === "") return base;
  const sep = base.includes("?") ? "&" : "?";
  return `${base}${sep}v=${encodeURIComponent(String(version))}`;
}
