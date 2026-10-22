const API_BASE_URL = import.meta.env.VITE_API_URL || "/api";

/** An API failure with the server's stable code and readable message. */
export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function csrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)si_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function errorFrom(response) {
  const payload = await response.json().catch(() => null);
  const error = payload?.error;
  return new ApiError(
    response.status,
    error?.code || "http_error",
    error?.message || payload?.detail || "Something went wrong. Try again.",
  );
}

async function request(path, { method = "GET", json, signal } = {}) {
  const headers = {};
  if (json !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: json === undefined ? undefined : JSON.stringify(json),
      credentials: "same-origin",
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(0, "network", "Can't reach the server. Check your connection.");
  }
  if (!response.ok) throw await errorFrom(response);
  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  me: () => request("/me"),
  signUp: (email, password, name) =>
    request("/auth/signup", { method: "POST", json: { email, password, name } }),
  logIn: (email, password) =>
    request("/auth/login", { method: "POST", json: { email, password } }),
  logOut: () => request("/auth/logout", { method: "POST" }),

  listChats: () => request("/chats"),
  createChat: (title) => request("/chats", { method: "POST", json: title ? { title } : {} }),
  renameChat: (id, title) => request(`/chats/${id}`, { method: "PATCH", json: { title } }),
  deleteChat: (id) => request(`/chats/${id}`, { method: "DELETE" }),
  listMessages: (id) => request(`/chats/${id}/messages`),

  listDocuments: () => request("/documents"),
  deleteDocument: (id) => request(`/documents/${id}`, { method: "DELETE" }),

  /** Upload with progress (fetch can't report upload progress; XHR can). */
  uploadDocuments(files, onProgress) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      files.forEach((file) => form.append("files", file));
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE_URL}/documents`);
      xhr.withCredentials = true;
      xhr.setRequestHeader("X-CSRF-Token", csrfToken());
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress?.(event.loaded / event.total);
      };
      xhr.onload = () => {
        let payload = null;
        try {
          payload = JSON.parse(xhr.responseText);
        } catch {
          // Not JSON: fall through to the generic error.
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(payload);
        else {
          const error = payload?.error;
          reject(
            new ApiError(
              xhr.status,
              error?.code || "http_error",
              error?.message || "The upload failed. Try again.",
            ),
          );
        }
      };
      xhr.onerror = () =>
        reject(new ApiError(0, "network", "Can't reach the server. Check your connection."));
      xhr.send(form);
    });
  },

  /**
   * Ask a question. The answer streams as server-sent events; each one is
   * passed to onEvent(name, data) as it arrives. Abort with the signal.
   */
  async ask(chatId, question, scope, { signal, onEvent }) {
    let response;
    try {
      response = await fetch(`${API_BASE_URL}/chats/${chatId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
        body: JSON.stringify({ question, scope }),
        credentials: "same-origin",
        signal,
      });
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new ApiError(0, "network", "Can't reach the server. Check your connection.");
    }
    if (!response.ok) throw await errorFrom(response);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let name = "message";
        const data = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) name = line.slice(7);
          else if (line.startsWith("data: ")) data.push(line.slice(6));
        }
        if (data.length) onEvent(name, JSON.parse(data.join("\n")));
      }
    }
  },
};
