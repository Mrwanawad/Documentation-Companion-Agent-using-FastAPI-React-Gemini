import type { ChatStatus } from "../types";

const LABELS: Record<ChatStatus, string> = {
  draft: "Draft",
  complete: "Complete",
  in_review: "In Review",
  approved: "Approved",
  superseded: "Superseded",
  archived: "Archived",
};

export function StatusBadge({ status }: { status: ChatStatus }) {
  return <span className={`badge ${status}`}>{LABELS[status]}</span>;
}
