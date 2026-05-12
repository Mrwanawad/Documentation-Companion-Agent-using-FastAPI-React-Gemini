import { jsx as _jsx } from "react/jsx-runtime";
const LABELS = {
    draft: "Draft",
    complete: "Complete",
    in_review: "In Review",
    approved: "Approved",
    superseded: "Superseded",
    archived: "Archived",
};
export function StatusBadge({ status }) {
    return _jsx("span", { className: `badge ${status}`, children: LABELS[status] });
}
