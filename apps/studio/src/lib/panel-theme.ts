export type StudioPanelTheme = {
    node: {
        fill: string;
        panel: string;
        stroke: string;
        activeStroke: string;
        text: string;
        muted: string;
    };
    toolbar: {
        panel: string;
        border: string;
        item: string;
    };
};

export const studioPanelThemes: Record<"light" | "dark", StudioPanelTheme> = {
    light: {
        node: { fill: "#eef6fb", panel: "#fdfefe", stroke: "#d9e7ee", activeStroke: "#0f172a", text: "#1e293b", muted: "#64748b" },
        toolbar: { panel: "rgba(253,254,254,.96)", border: "#d9e7ee", item: "#475569" },
    },
    dark: {
        node: { fill: "#111318", panel: "#0f1115", stroke: "#303642", activeStroke: "#f8fafc", text: "#f8fafc", muted: "#cbd5e1" },
        toolbar: { panel: "rgba(10,12,16,.96)", border: "#303642", item: "#e5e7eb" },
    },
};
