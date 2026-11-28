import { useEffect, useState } from "react";

export type DescriptionMode = "truncate" | "wrap";

export const CSV_DESCRIPTION_MODE_KEY = "ecom.csv-description-mode";
export const WORKBENCH_DESCRIPTION_MODE_KEY = "ecom.workbench-description-mode";

export function readDescriptionMode(
  storageKey: string = CSV_DESCRIPTION_MODE_KEY,
): DescriptionMode {
  try {
    return window.localStorage.getItem(storageKey) === "wrap" ? "wrap" : "truncate";
  } catch {
    return "truncate";
  }
}

export function useDescriptionMode(storageKey: string = CSV_DESCRIPTION_MODE_KEY) {
  const [mode, setMode] = useState<DescriptionMode>(() =>
    readDescriptionMode(storageKey),
  );

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, mode);
    } catch {
      // A blocked storage area should not break the preview.
    }
  }, [mode, storageKey]);

  return [mode, setMode] as const;
}
