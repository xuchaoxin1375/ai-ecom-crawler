import type { ECharts } from "echarts/core";

export type ChartRuntime = typeof import("echarts/core");

let runtimePromise: Promise<ChartRuntime> | null = null;

export function loadChartRuntime(): Promise<ChartRuntime> {
  if (!runtimePromise) {
    runtimePromise = (async () => {
      const [core, charts, components, renderers] = await Promise.all([
        import("echarts/core"),
        import("echarts/charts"),
        import("echarts/components"),
        import("echarts/renderers"),
      ]);
      core.use([
        charts.LineChart,
        components.GridComponent,
        components.TooltipComponent,
        components.AxisPointerComponent,
        components.DataZoomComponent,
        renderers.CanvasRenderer,
      ]);
      return core;
    })();
  }
  return runtimePromise;
}

export type ChartInstance = ECharts;
