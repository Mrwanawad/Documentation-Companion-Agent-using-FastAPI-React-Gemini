export type ChatStatus =
  | "draft"
  | "complete"
  | "in_review"
  | "approved"
  | "superseded"
  | "archived";

export interface ChatMeta {
  id: string;
  name: string;
  browser_enabled: boolean;
  status: ChatStatus;
  created_at: string;
  updated_at: string;
  current_version: string;
  browser_url?: string | null;
  browser_email?: string | null;
  browser_password?: string | null;
  browser_notes?: string | null;
}

export interface DocumentRead {
  chat_id: string;
  version: string;
  content: string;
  readonly: boolean;
}
