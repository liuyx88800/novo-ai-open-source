import { loadPublicSession } from "@/stores/use-public-session-store";
import { useUserStore } from "@/stores/use-user-store";
import { applyPublicSystemSettings, useConfigStore } from "@/stores/use-config-store";

let started = false;

export function initSession() {
  if (started) return;
  started = true;
  void loadPublicSession()
    .then((payload) => {
      if (payload?.user) useUserStore.getState().setUser(payload.user);
      if (payload?.settings) {
        const config = useConfigStore.getState().config;
        useConfigStore.getState().setConfig(applyPublicSystemSettings(config, payload.settings));
      }
    })
    .catch(() => {
      // 未登录或会话加载失败，交由页面自行处理
    });
}
