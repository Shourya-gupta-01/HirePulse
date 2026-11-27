const TOKEN_KEY = "hirepulse_token";
const USER_KEY = "hirepulse_user";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getStoredToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveAuthSession(data) {
  if (data?.access_token) {
    localStorage.setItem(TOKEN_KEY, data.access_token);
  }
  if (data?.user_id || data?.email) {
    localStorage.setItem(
      USER_KEY,
      JSON.stringify({ id: data.user_id, email: data.email })
    );
  }
}

export function clearAuthSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function authHeaders(extra = {}) {
  const token = getStoredToken();
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function parseErrorDetail(res, fallback) {
  try {
    const data = await res.json();
    return data?.detail || data?.message || fallback;
  } catch {
    return fallback;
  }
}

export async function loginUser(email, password) {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const detail = await parseErrorDetail(res, `Login failed (${res.status})`);
    throw new ApiError(detail, res.status);
  }

  const data = await res.json();
  saveAuthSession(data);
  return data;
}

export async function signupUser(email, password) {
  const res = await fetch("/api/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const detail = await parseErrorDetail(res, `Signup failed (${res.status})`);
    throw new ApiError(detail, res.status);
  }

  const data = await res.json();
  saveAuthSession(data);
  return data;
}

export async function fetchCurrentUser() {
  const res = await fetch("/api/auth/me", {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const detail = await parseErrorDetail(res, `Session expired (${res.status})`);
    throw new ApiError(detail, res.status);
  }
  return res.json();
}

export async function fetchThreads() {
  const res = await fetch("/api/threads", {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const detail = await parseErrorDetail(res, `Failed to load threads (${res.status})`);
    throw new ApiError(detail, res.status);
  }
  const data = await res.json();
  return data.threads || [];
}

export async function fetchThreadMessages(threadId) {
  const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/messages`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const detail = await parseErrorDetail(res, `Failed to load messages (${res.status})`);
    throw new ApiError(detail, res.status);
  }
  const data = await res.json();
  return {
    messages: data.messages || [],
    files: data.files || [],
  };
}

export async function deleteThread(threadId) {
  const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) {
    const detail = await parseErrorDetail(res, `Failed to delete thread (${res.status})`);
    throw new ApiError(detail, res.status);
  }
  return res.json();
}

export async function uploadDocuments(files, threadId = null) {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  if (threadId) {
    formData.append("thread_id", threadId);
  }

  const res = await fetch("/api/documents/upload", {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    const detail = await parseErrorDetail(res, `Upload failed (${res.status})`);
    throw new ApiError(detail, res.status);
  }
  return res.json();
}

export async function streamChat({
  threadId,
  message,
  onMeta,
  onToken,
  onDone,
  onError,
  signal,
}) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ thread_id: threadId, message }),
    signal,
  });

  if (!res.ok) {
    const detail = await parseErrorDetail(res, `Chat request failed (${res.status})`);
    throw new ApiError(detail, res.status);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";

    for (const rawEvent of events) {
      const lines = rawEvent.split("\n");
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6).trim();
        if (!payload) continue;

        let evt;
        try {
          evt = JSON.parse(payload);
        } catch {
          continue;
        }

        if (evt.type === "meta" && onMeta) onMeta(evt);
        else if (evt.type === "token" && onToken) onToken(evt.content);
        else if (evt.type === "done" && onDone) onDone(evt);
        else if (evt.type === "error" && onError) onError(evt.error);
      }
    }
  }
}
