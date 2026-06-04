import type { ChatMeta, DocumentRead } from "../types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  listChats: () => request<ChatMeta[]>("/api/chats"),
  createChat: (name: string, browser_enabled: boolean) =>
    request<ChatMeta>("/api/chats", {
      method: "POST",
      body: JSON.stringify({ name, browser_enabled }),
    }),
  deleteChat: (id: string) =>
    request<void>(`/api/chats/${id}`, { method: "DELETE" }),
  updateChat: (
    id: string,
    patch: Partial<
      Pick<
        ChatMeta,
        | "name"
        | "browser_enabled"
        | "status"
        | "browser_url"
        | "browser_email"
        | "browser_password"
        | "browser_notes"
      >
    >,
  ) =>
    request<ChatMeta>(`/api/chats/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  exportUrl: (id: string) => `/api/chats/${id}/export.html`,
  getDocument: (id: string) =>
    request<DocumentRead>(`/api/chats/${id}/document`),
  writeDocument: (id: string, content: string) =>
    request<DocumentRead>(`/api/chats/${id}/document`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  clearMessages: (id: string) =>
    request<void>(`/api/chats/${id}/messages`, { method: "DELETE" }),
  uploadImage: async (id: string, file: File): Promise<UploadResponse> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`/api/chats/${id}/uploads`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status}: ${text || res.statusText}`);
    }
    return res.json() as Promise<UploadResponse>;
  },
};

export interface UploadElement {
  index: number;
  label: string;
  element_type: string;
  inferred_action: string;
  is_repeated_group?: boolean;
  instance_count?: number;
}

export interface UploadResponse {
  annotated_url: string;
  original_url: string;
  page_summary: string;
  elements: UploadElement[];
  element_count: number;
}

export interface BrowserStep {
  action: string;
  url: string;
  title: string;
  observed_labels: string[];
  validation_messages: string[];
  screenshot_url: string | null;
  notes: string;
}

export interface AttachmentEvent {
  type: "attachment";
  kind: "image" | "pdf";
  name: string;
  annotated_url?: string;
  original_url?: string;
  file_url?: string;
  page_summary?: string;
  elements?: UploadElement[];
  element_count?: number;
  error?: string;
}

export type AgentEvent =
  | { type: "text"; text: string }
  | { type: "tool_call"; name: string; args: Record<string, unknown> }
  | ({ type: "browser_step" } & BrowserStep)
  | AttachmentEvent
  | { type: "doc_updated" }
  | { type: "error"; message: string }
  | { type: "done" };

export async function streamMessage(
  chatId: string,
  text: string,
  files: File[],
  browse: boolean,
  onEvent: (e: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const form = new FormData();
  form.append("text", text);
  if (browse) form.append("browse", "true");
  for (const f of files) form.append("files", f, f.name);
  const res = await fetch(`/api/chats/${chatId}/messages`, {
    // No Content-Type header — the browser sets the multipart boundary.
    method: "POST",
    headers: { Accept: "text/event-stream" },
    body: form,
    signal,
  });
  if (!res.ok || !res.body) {
    const errText = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${errText || res.statusText}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  // SSE frames are delimited by a blank line.
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLines = frame
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart());
      if (dataLines.length === 0) continue;
      try {
        const parsed = JSON.parse(dataLines.join("\n")) as AgentEvent;
        onEvent(parsed);
      } catch {
        // ignore malformed frames
      }
    }
  }
}
