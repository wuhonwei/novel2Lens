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
  portrait_ready: boolean;
  created_chapter_id?: string;
};

export type ImageJob = {
  id: string;
  project_id: string;
  asset_id: string;
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
  if (j.status === "queued") return "排队中";
  if (j.status === "running") return "生成中";
  if (j.status === "failed") return "失败";
  return "";
}

export type Chapter = {
  id: string;
  index: number;
  title: string;
  text: string;
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
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  list: () => req<Project[]>("/api/projects"),
  create: (body: { title: string; text: string; style: string }) =>
    req<Bundle>("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  upload: async (title: string, style: string, file: File) => {
    const data = new FormData();
    data.set("title", title);
    data.set("style", style);
    data.set("file", file);
    return req<Bundle>("/api/projects/upload", { method: "POST", body: data });
  },
  get: (id: string) => req<Bundle>(`/api/projects/${id}`),
  patch: (id: string, body: Partial<Project> & { text?: string }) =>
    req<Bundle>(`/api/projects/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  remove: (id: string) => req<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),
  /** One-click book registry. Prefer stable /prescan; also try /generate-assets. */
  generateAssets: async (id: string, replace = true) => {
    const qs = `replace=${replace}`;
    try {
      return await req<Bundle>(`/api/projects/${id}/prescan?${qs}`, { method: "POST" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (/not found/i.test(msg)) {
        return req<Bundle>(`/api/projects/${id}/generate-assets?${qs}`, { method: "POST" });
      }
      throw err;
    }
  },
  prescan: (id: string, replace = false) =>
    req<Bundle>(`/api/projects/${id}/prescan?replace=${replace}`, { method: "POST" }),
  extract: (pid: string, cid: string, overwrite = false) =>
    req<Bundle>(`/api/projects/${pid}/chapters/${cid}/extract?overwrite=${overwrite}`, { method: "POST" }),
  confirm: (pid: string, cid: string, items: unknown[]) =>
    req<Bundle>(`/api/projects/${pid}/chapters/${cid}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }),
  storyboard: (pid: string, cid: string, overwrite = false) =>
    req<Bundle>(`/api/projects/${pid}/chapters/${cid}/storyboard?overwrite=${overwrite}`, { method: "POST" }),
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
  generateImages: (pid: string) =>
    req<Bundle & { batch_id?: string; jobs?: ImageJob[]; image_gen?: Record<string, unknown> }>(
      `/api/projects/${pid}/generate-images`,
      { method: "POST" },
    ),
  generateAssetImage: (pid: string, aid: string, field?: string) => {
    const qs = field ? `?field=${encodeURIComponent(field)}` : "";
    return req<{ ok: boolean; job: ImageJob; jobs: ImageJob[]; asset: Asset }>(
      `/api/projects/${pid}/assets/${aid}/generate-image${qs}`,
      { method: "POST" },
    );
  },
  clearAssetImage: (pid: string, aid: string, field: string) =>
    req<Asset>(`/api/projects/${pid}/assets/${aid}/image?field=${encodeURIComponent(field)}`, { method: "DELETE" }),
  listImageJobs: (pid: string, activeOnly = true) =>
    req<{ jobs: ImageJob[] }>(`/api/projects/${pid}/image-jobs?active_only=${activeOnly}`),
  cancelImageBatch: (pid: string, batchId: string) =>
    req<{ ok: boolean; cancelled: number }>(`/api/projects/${pid}/image-batches/${batchId}/cancel`, { method: "POST" }),
  editAssetImage: (pid: string, aid: string, form: FormData) =>
    req<{ ok: boolean; job: ImageJob }>(`/api/projects/${pid}/assets/${aid}/edit-image`, { method: "POST", body: form }),
  listImageOutputFiles: (pid: string) =>
    req<{ image_output_dir?: string; files: { name: string; path: string; rel?: string }[] }>(
      `/api/projects/${pid}/image-output-files`,
    ),
  export: (pid: string) => req<{ document: unknown; markdown: string; path: string }>(`/api/projects/${pid}/export`, { method: "POST" }),
};

export function mediaUrl(path: string) {
  return path ? `/media/${path}` : "";
}
