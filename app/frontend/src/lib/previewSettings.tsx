import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { getPreviewSettings } from "./api";

export interface PreviewDisplaySettings {
  /** Whether list views may load product thumbnails. */
  thumbnailsEnabled: boolean;
  /** How many recent products the workbench live panel requests. */
  realtimeLimit: number;
  /** False while the server preference is still being read. */
  ready: boolean;
}

export const PREVIEW_SETTINGS_QUERY_KEY = ["preview-settings"] as const;

export const DEFAULT_REALTIME_LIMIT = 50;
export const REALTIME_LIMIT_MIN = 10;
export const REALTIME_LIMIT_MAX = 200;
export const REALTIME_LIMIT_PRESETS = [10, 25, 50, 100, 200] as const;

const DEFAULT_PREVIEW_DISPLAY_SETTINGS: PreviewDisplaySettings = {
  thumbnailsEnabled: true,
  realtimeLimit: DEFAULT_REALTIME_LIMIT,
  ready: true,
};

export const PreviewSettingsContext = createContext<PreviewDisplaySettings>(
  DEFAULT_PREVIEW_DISPLAY_SETTINGS,
);

export function usePreviewDisplaySettings(): PreviewDisplaySettings {
  return useContext(PreviewSettingsContext);
}

export function PreviewSettingsProvider({ children }: { children: ReactNode }) {
  const query = useQuery({
    queryKey: PREVIEW_SETTINGS_QUERY_KEY,
    queryFn: ({ signal }) => getPreviewSettings(signal),
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  });
  const value = useMemo<PreviewDisplaySettings>(
    () => ({
      thumbnailsEnabled: query.data?.thumbnails_enabled ?? true,
      realtimeLimit: query.data?.realtime_limit ?? DEFAULT_REALTIME_LIMIT,
      ready: !query.isPending,
    }),
    [query.data, query.isPending],
  );
  return (
    <PreviewSettingsContext.Provider value={value}>
      {children}
    </PreviewSettingsContext.Provider>
  );
}
