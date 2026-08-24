export const DEFAULT_SITE_TITLE = "NOVO AI";

export function resolveSiteTitle(value: unknown) {
    return typeof value === "string" && value.trim() ? value.trim() : DEFAULT_SITE_TITLE;
}
