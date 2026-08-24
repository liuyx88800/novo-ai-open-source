"use client";

import { resetPublicSession } from "@/stores/use-public-session-store";
import { useAssetStore } from "@/stores/use-asset-store";
import { useUserStore } from "@/stores/use-user-store";

export async function resetClientSessionState() {
    useUserStore.getState().clearSession();
    resetPublicSession();
    useAssetStore.getState().reset();
    const [{ useDramaStore }, { useCreateDraftAttachmentsStore }] = await Promise.all([
        import("@/studio/drama/stores/use-drama-store"),
        import("@/studio/create/use-create-draft-attachments-store"),
    ]);
    useDramaStore.getState().reset();
    useCreateDraftAttachmentsStore.getState().clear();
}
