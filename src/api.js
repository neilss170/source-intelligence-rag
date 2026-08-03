const API_BASE_URL = import.meta.env.VITE_API_URL || "/api";

export async function askAssistant(question, scope = "auto", history = [], sessionId = null) {
  const response = await fetch(`${API_BASE_URL}/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question, scope, history, session_id: sessionId }),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || "The assistant could not answer right now.");
  }

  return response.json();
}

export async function uploadDocuments(files) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const response = await fetch(`${API_BASE_URL}/documents`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail || "The documents could not be uploaded.");
  }

  return response.json();
}

export async function listDocuments() {
  const response = await fetch(`${API_BASE_URL}/documents`);
  if (!response.ok) {
    throw new Error("Indexed documents could not be loaded.");
  }
  return response.json();
}

export async function deleteDocument(documentId) {
  const response = await fetch(
    `${API_BASE_URL}/documents/${encodeURIComponent(documentId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail || "The document could not be removed.");
  }
}
