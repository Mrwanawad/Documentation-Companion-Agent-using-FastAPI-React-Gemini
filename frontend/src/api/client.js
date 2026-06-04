async function request(url, init) {
    const res = await fetch(url, {
        headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
        ...init,
    });
    if (!res.ok) {
        const text = await res.text();
        throw new Error(`${res.status} ${res.statusText}: ${text}`);
    }
    if (res.status === 204)
        return undefined;
    return res.json();
}
export const api = {
    listChats: () => request("/api/chats"),
    createChat: (name, browser_enabled) => request("/api/chats", {
        method: "POST",
        body: JSON.stringify({ name, browser_enabled }),
    }),
    deleteChat: (id) => request(`/api/chats/${id}`, { method: "DELETE" }),
    updateChat: (id, patch) => request(`/api/chats/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
    }),
    exportUrl: (id) => `/api/chats/${id}/export.html`,
    getDocument: (id) => request(`/api/chats/${id}/document`),
    writeDocument: (id, content) => request(`/api/chats/${id}/document`, {
        method: "PUT",
        body: JSON.stringify({ content }),
    }),
    clearMessages: (id) => request(`/api/chats/${id}/messages`, { method: "DELETE" }),
    uploadImage: async (id, file) => {
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
        return res.json();
    },
};
export async function streamMessage(chatId, text, files, browse, onEvent, signal) {
    const form = new FormData();
    form.append("text", text);
    if (browse)
        form.append("browse", "true");
    for (const f of files)
        form.append("files", f, f.name);
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
        if (done)
            break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            const dataLines = frame
                .split("\n")
                .filter((l) => l.startsWith("data:"))
                .map((l) => l.slice(5).trimStart());
            if (dataLines.length === 0)
                continue;
            try {
                const parsed = JSON.parse(dataLines.join("\n"));
                onEvent(parsed);
            }
            catch {
                // ignore malformed frames
            }
        }
    }
}
