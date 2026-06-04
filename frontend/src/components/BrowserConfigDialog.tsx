import { useState } from "react";
import type { ChatMeta } from "../types";
import { api } from "../api/client";

interface Props {
  chat: ChatMeta;
  onClose: () => void;
  onSaved: (updated: ChatMeta) => void;
}

export function BrowserConfigDialog({ chat, onClose, onSaved }: Props) {
  const [url, setUrl] = useState(chat.browser_url ?? "");
  const [email, setEmail] = useState(chat.browser_email ?? "");
  const [password, setPassword] = useState(chat.browser_password ?? "");
  const [notes, setNotes] = useState(chat.browser_notes ?? "");
  const [enabled, setEnabled] = useState(chat.browser_enabled);
  const [busy, setBusy] = useState(false);

  async function save() {
    if (busy) return;
    setBusy(true);
    try {
      const updated = await api.updateChat(chat.id, {
        browser_enabled: enabled,
        browser_url: url.trim(),
        browser_email: email.trim(),
        browser_password: password,
        browser_notes: notes.trim(),
      });
      onSaved(updated);
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h2>Browser walkthrough</h2>
        <p className="dialog-sub">
          The agent can open this page and verify it. Credentials are saved locally for this chat so it can log in without asking.
        </p>

        <div className="field">
          <label htmlFor="bw-url">Page URL</label>
          <input
            id="bw-url"
            type="url"
            placeholder="https://app.example.com/login"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            autoFocus
          />
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="bw-email">Email / username <span className="opt">(optional)</span></label>
            <input
              id="bw-email"
              type="text"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="field">
            <label htmlFor="bw-pass">Password <span className="opt">(optional)</span></label>
            <input
              id="bw-pass"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
          </div>
        </div>

        <div className="field">
          <label htmlFor="bw-notes">Notes <span className="opt">(optional)</span></label>
          <textarea
            id="bw-notes"
            placeholder="Anything the agent should know — e.g. 'use the Staging tenant', '2FA code will be texted'…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
          />
        </div>

        <div className="field">
          <label className="toggle">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            <span className="toggle-label">Enable browser walkthrough for this chat</span>
          </label>
          <div className="field-hint">
            When on, the agent may drive a real browser. You can also trigger a one-off walkthrough by typing <code>/browse</code> in the chat.
          </div>
        </div>

        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
