export function authToken(): string {
  try {
    return localStorage.getItem("lafai_token") || localStorage.getItem("auth_token") || localStorage.getItem("token") || "";
  } catch {
    return "";
  }
}

export function installApiBridge() {
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.startsWith("/api/")) {
      const token = authToken();
      const headers = new Headers(init?.headers);
      if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
      return originalFetch(input, { ...init, headers });
    }
    return originalFetch(input, init);
  };

  const OriginalEventSource = window.EventSource;
  (window as unknown as { EventSource: typeof EventSource }).EventSource = function (url: string | URL, eventSourceInitDict?: EventSourceInit) {
    let target = String(url);
    const token = authToken();
    if (token && !target.includes("token=")) {
      target += (target.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token);
    }
    return new OriginalEventSource(target, eventSourceInitDict);
  } as typeof EventSource;
  (window as unknown as { EventSource: typeof EventSource }).EventSource.prototype = OriginalEventSource.prototype;
  (window as unknown as { EventSource: typeof EventSource }).EventSource.CONNECTING = OriginalEventSource.CONNECTING;
  (window as unknown as { EventSource: typeof EventSource }).EventSource.OPEN = OriginalEventSource.OPEN;
  (window as unknown as { EventSource: typeof EventSource }).EventSource.CLOSED = OriginalEventSource.CLOSED;
}